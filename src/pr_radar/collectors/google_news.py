"""Google News RSS collector: one search feed per brand per market edition."""

from __future__ import annotations

import logging
from datetime import datetime
from urllib.parse import urlencode

import feedparser
import requests

from ..config import Brand, Edition, Settings
from ..http import HttpClient
from ..language import detect_language
from ..models import Article
from ..text import domain_of, strip_source_suffix

log = logging.getLogger(__name__)

SEARCH_URL = "https://news.google.com/rss/search"
HOST = "news.google.com"


def build_url(query: str, edition: Edition, lookback_days: int) -> str:
    params = {
        "q": f"{query} when:{lookback_days}d",
        "hl": edition.hl,
        "gl": edition.gl,
        "ceid": edition.ceid,
    }
    return f"{SEARCH_URL}?{urlencode(params)}"


def parse_feed(payload: str | bytes, *, brand_id: str, edition: Edition) -> list[Article]:
    feed = feedparser.parse(payload)
    articles: list[Article] = []
    for entry in feed.entries:
        source = entry.get("source") or {}
        source_name = (source.get("title") or "").strip()
        raw_title = (entry.get("title") or "").strip()
        published = entry.get("published_parsed")
        if not raw_title or published is None:
            continue
        title = strip_source_suffix(raw_title, source_name)
        detected = detect_language(title)
        articles.append(
            Article(
                title=title,
                url=entry.get("link", ""),
                source_name=source_name,
                source_domain=domain_of(source.get("href", "")),
                published_at=datetime(*published[:6]),
                collector="google_news",
                query_brand=brand_id,
                # Titles are short, so only trust detection when it is confident.
                language=detected or edition.language,
                country=edition.gl.upper(),
            )
        )
    return articles


class GoogleNewsCollector:
    name = "google_news"

    def __init__(self, settings: Settings, http: HttpClient) -> None:
        self.settings = settings
        self.http = http
        self.http.min_interval.setdefault(HOST, 1.5)
        self.errors = 0

    def fetch_query(self, query: str, brand: Brand, edition: Edition) -> list[Article]:
        url = build_url(query, edition, self.settings.lookback_days)
        try:
            response = self.http.get(url)
        except requests.RequestException as exc:
            self.errors += 1
            log.warning("Google News %s/%s failed: %s", query, edition.ceid, exc)
            return []
        return parse_feed(response.content, brand_id=brand.id, edition=edition)

    def fetch(self, brand: Brand, edition: Edition) -> list[Article]:
        articles = self.fetch_query(brand.query, brand, edition)
        if not articles:
            return []  # extra queries all contain the brand name, so they would be empty too
        for query in brand.extra_queries:
            articles.extend(self.fetch_query(query, brand, edition))
        return articles

    def collect(self) -> list[Article]:
        results: list[Article] = []
        for brand in self.settings.brands:
            for edition in self.settings.editions:
                batch = self.fetch(brand, edition)
                log.info("Google News %-12s %-10s %3d articles", brand.id, edition.ceid, len(batch))
                results.extend(batch)
        return results
