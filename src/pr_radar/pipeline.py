"""Collection pipeline: collect -> tag -> merge -> cluster -> store -> archive."""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from datetime import UTC, datetime, timedelta
from pathlib import Path

from .collectors import GdeltCollector, GoogleNewsCollector
from .config import Settings
from .dedup import assign_clusters, merge_duplicates
from .http import HttpClient
from .matching import BrandMatcher, TopicMatcher
from .models import Article
from .storage import Store

log = logging.getLogger(__name__)

CLUSTER_WINDOW = timedelta(days=21)


@dataclass
class RunStats:
    collected: int = 0
    unique: int = 0
    inserted: int = 0
    updated: int = 0
    errors: int = 0
    by_collector: dict[str, int] = field(default_factory=dict)
    archive_file: str | None = None


def utcnow() -> datetime:
    return datetime.now(UTC).replace(tzinfo=None, microsecond=0)


def tag(articles: list[Article], settings: Settings) -> list[Article]:
    """Brands = the brand whose query found it + any brand named in the headline.

    Google News matches a query anywhere in the article, so many mentions are in
    the body only (gift guides, round-ups). headline_brands keeps the stronger,
    headline-level mentions apart. Articles from excluded outlets are dropped.
    """
    brands = BrandMatcher(settings.brands)
    topics = TopicMatcher(settings.topics)
    excluded = {d.lower() for d in settings.exclude_domains}
    kept = []
    for art in articles:
        if art.source_domain in excluded:
            continue
        art.headline_brands = brands.match(art.title)
        art.brands = sorted({art.query_brand, *art.headline_brands})
        art.topics = topics.match(art.title)
        kept.append(art)
    return kept


def process(articles: list[Article], settings: Settings, store: Store) -> list[Article]:
    merged = merge_duplicates(tag(articles, settings))
    if merged:
        since = min(a.published_at for a in merged) - CLUSTER_WINDOW
        assign_clusters(merged, store.recent_titles(since))
    return merged


def run_collection(
    settings: Settings,
    store: Store,
    archive_dir: str | Path | None = None,
    sources: tuple[str, ...] = ("google_news", "gdelt"),
    http: HttpClient | None = None,
) -> RunStats:
    http = http or HttpClient()
    now = utcnow()
    stats = RunStats()

    if archive_dir:
        store.bootstrap_from_archive(archive_dir)
    store.refresh_tags(settings)

    collectors = []
    if "google_news" in sources:
        collectors.append(GoogleNewsCollector(settings, http))
    if "gdelt" in sources and settings.gdelt.enabled:
        collectors.append(GdeltCollector(settings, http))

    raw: list[Article] = []
    for collector in collectors:
        batch = collector.collect()
        stats.by_collector[collector.name] = len(batch)
        stats.errors += collector.errors
        raw.extend(batch)
    stats.collected = len(raw)

    articles = process(raw, settings, store)
    stats.unique = len(articles)
    stats.inserted, stats.updated = store.upsert(articles, now)

    if archive_dir and (stats.inserted or stats.updated):
        path = store.export_archive((a.id for a in articles), archive_dir, now)
        stats.archive_file = str(path) if path else None
    return stats
