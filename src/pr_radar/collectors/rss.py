"""RSS/Atom collector for outlet feeds (beauty, lifestyle and consumer tech).

Google News search only returns what its ranking picks for a query. Outlet feeds
add the items those outlets publish, including gift guides and round-ups that
name a brand only in the teaser. An item is kept only if a tracked brand is
named in its title or summary; everything else in the feed is ignored.
"""

from __future__ import annotations

import html
import logging
import re
from datetime import UTC, datetime, timedelta
from urllib.parse import urlparse

import feedparser
import requests

from ..config import RssFeed, Settings
from ..http import HttpClient
from ..language import detect_language
from ..matching import BrandMatcher
from ..models import Article
from ..text import domain_of

log = logging.getLogger(__name__)

_TAG = re.compile(r"<[^>]+>")
_WS = re.compile(r"\s+")


def clean(text: str) -> str:
    """Plain text from a feed field that may hold HTML and entities."""
    return _WS.sub(" ", _TAG.sub(" ", html.unescape(text or ""))).strip()


def parse_feed(
    payload: str | bytes,
    *,
    feed: RssFeed,
    matcher: BrandMatcher,
    since: datetime | None = None,
) -> list[Article]:
    """One Article per brand named in an item's title or summary."""
    parsed = feedparser.parse(payload)
    source_name = clean(parsed.feed.get("title", "")) or domain_of(feed.url)
    articles: list[Article] = []
    for entry in parsed.entries:
        title = clean(entry.get("title", ""))
        stamp = entry.get("published_parsed") or entry.get("updated_parsed")
        if not title or stamp is None:
            continue
        published = datetime(*stamp[:6])
        if since and published < since:
            continue
        brands = matcher.match(f"{title}\n{clean(entry.get('summary', ''))}")
        if not brands:
            continue
        link = entry.get("link", "")
        for brand_id in brands:
            articles.append(
                Article(
                    title=title,
                    url=link,
                    source_name=source_name,
                    source_domain=domain_of(link) or domain_of(feed.url),
                    published_at=published,
                    collector="rss",
                    query_brand=brand_id,
                    language=detect_language(title) or feed.language,
                    country=feed.country,
                )
            )
    return articles


class RssCollector:
    name = "rss"

    def __init__(self, settings: Settings, http: HttpClient) -> None:
        self.settings = settings
        self.http = http
        self.matcher = BrandMatcher(settings.brands)
        self.errors = 0

    def collect(self) -> list[Article]:
        since = datetime.now(UTC).replace(tzinfo=None) - timedelta(days=self.settings.lookback_days)
        results: list[Article] = []
        for feed in self.settings.rss.feeds:
            host = urlparse(feed.url).hostname or ""
            self.http.min_interval.setdefault(host, 1.0)  # several feeds share a host
            try:
                response = self.http.get(feed.url)
            except requests.RequestException as exc:
                self.errors += 1
                log.warning("RSS %s failed: %s", feed.url, exc)
                continue
            batch = parse_feed(response.content, feed=feed, matcher=self.matcher, since=since)
            log.info("RSS %-40s %3d brand items", host, len(batch))
            results.extend(batch)
        return results
