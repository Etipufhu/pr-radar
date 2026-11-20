"""Merge duplicate articles and cluster syndicated copies of the same story.

Two levels:
* Same headline from the same outlet (found by several collectors or market
  editions) is ONE article: merged by id.
* The same story picked up by several outlets is one CLUSTER. Mentions count
  articles (PR placements); stories count clusters.

Clustering uses character 4-gram Jaccard similarity on normalised headlines, which
works without word segmentation, so it also handles Japanese or Chinese titles.
"""

from __future__ import annotations

from collections.abc import Iterable

from .models import Article
from .text import normalize_title

DEFAULT_THRESHOLD = 0.6


def shingles(text: str, k: int = 4) -> frozenset[str]:
    norm = normalize_title(text)
    if len(norm) <= k:
        return frozenset({norm}) if norm else frozenset()
    return frozenset(norm[i : i + k] for i in range(len(norm) - k + 1))


def jaccard(a: frozenset[str], b: frozenset[str]) -> float:
    if not a and not b:
        return 0.0
    return len(a & b) / len(a | b)


def merge_duplicates(articles: Iterable[Article]) -> list[Article]:
    merged: dict[str, Article] = {}
    for art in articles:
        current = merged.get(art.id)
        if current is None:
            merged[art.id] = art
            continue
        current.brands = sorted(set(current.brands) | set(art.brands))
        current.topics = sorted(set(current.topics) | set(art.topics))
        current.headline_brands = sorted(set(current.headline_brands) | set(art.headline_brands))
        current.language = current.language or art.language
        current.country = current.country or art.country
        if not current.url.startswith("http") or "news.google.com" in current.url:
            # Prefer the publisher's own URL (GDELT) over a Google News redirect.
            current.url = art.url or current.url
        current.published_at = min(current.published_at, art.published_at)
    return list(merged.values())


def assign_clusters(
    articles: list[Article],
    existing: Iterable[tuple[str, str]] = (),
    threshold: float = DEFAULT_THRESHOLD,
) -> None:
    """Set cluster_id on each article in place.

    existing: (cluster_id, title) pairs already stored, so new copies of a story
    join the cluster created in an earlier run.
    """
    clusters: list[tuple[str, frozenset[str]]] = [(cid, shingles(t)) for cid, t in existing]
    for art in articles:
        sig = shingles(art.title)
        best_id, best_score = None, 0.0
        for cid, other in clusters:
            # Cheap upper bound on Jaccard before computing the intersection.
            if min(len(sig), len(other)) / max(len(sig), len(other), 1) < threshold:
                continue
            score = jaccard(sig, other)
            if score > best_score:
                best_id, best_score = cid, score
        if best_id is not None and best_score >= threshold:
            art.cluster_id = best_id
        else:
            art.cluster_id = art.id
            clusters.append((art.id, sig))
