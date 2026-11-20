"""GDELT DOC 2.0 collector: global, multilingual news coverage (100+ languages)."""

from __future__ import annotations

import json
import logging
import time
from datetime import datetime

import requests

from ..config import Brand, Settings
from ..http import HttpClient
from ..language import country_name_to_code, language_name_to_code
from ..models import Article
from ..text import domain_of

log = logging.getLogger(__name__)

API_URL = "https://api.gdeltproject.org/api/v2/doc/doc"
HOST = "api.gdeltproject.org"
# GDELT asks for at most one request every 5 seconds and enforces it strictly,
# so keep a margin and back off hard on 429.
MIN_INTERVAL_SECONDS = 8.0
RATE_LIMIT_COOLDOWNS = (30.0, 90.0)
MAX_FAILURES = 2


def build_query(brand_query: str) -> str:
    """GDELT requires OR-ed terms to be wrapped in parentheses."""
    query = brand_query.strip()
    if " OR " in query and not query.startswith("("):
        query = f"({query})"
    return query


def build_params(brand: Brand, lookback_days: int, max_records: int) -> dict[str, str]:
    return {
        "query": build_query(brand.query),
        "mode": "ArtList",
        "format": "json",
        "sort": "DateDesc",
        "maxrecords": str(max_records),
        "timespan": f"{lookback_days}d",
    }


def parse_response(payload: str, *, brand_id: str) -> list[Article]:
    """GDELT answers errors (rate limits, bad queries) with plain text, not JSON."""
    try:
        data = json.loads(payload) if payload.strip() else {}
    except json.JSONDecodeError:
        log.warning("GDELT returned a non-JSON answer for %s: %.120s", brand_id, payload.strip())
        return []

    articles: list[Article] = []
    for item in data.get("articles", []):
        title = (item.get("title") or "").strip()
        seen = item.get("seendate")
        if not title or not seen:
            continue
        try:
            published = datetime.strptime(seen, "%Y%m%dT%H%M%SZ")
        except ValueError:
            continue
        domain = domain_of(item.get("domain") or item.get("url", ""))
        articles.append(
            Article(
                title=title,
                url=item.get("url", ""),
                source_name=domain,
                source_domain=domain,
                published_at=published,
                collector="gdelt",
                query_brand=brand_id,
                language=language_name_to_code(item.get("language")),
                country=country_name_to_code(item.get("sourcecountry")),
            )
        )
    return articles


class GdeltCollector:
    """Optional source. GDELT sometimes rate-limits an IP for a long time, so the
    collector stops early instead of stalling the weekly job:

    * after MAX_FAILURES failed brands, or
    * once the run has used settings.gdelt.time_budget_seconds.

    Either way the run continues with Google News data.
    """

    name = "gdelt"

    def __init__(self, settings: Settings, http: HttpClient) -> None:
        self.settings = settings
        self.http = http
        self.http.min_interval.setdefault(HOST, MIN_INTERVAL_SECONDS)
        self.http.cooldowns.setdefault(HOST, RATE_LIMIT_COOLDOWNS)
        self.errors = 0
        self.clock = time.monotonic  # swapped out in tests

    def fetch(self, brand: Brand) -> list[Article]:
        params = build_params(brand, self.settings.lookback_days, self.settings.gdelt.max_records)
        try:
            response = self.http.get(API_URL, params=params)
        except requests.RequestException as exc:
            self.errors += 1
            log.warning("GDELT %s failed: %s", brand.id, exc)
            return []
        return parse_response(response.text, brand_id=brand.id)

    def collect(self) -> list[Article]:
        results: list[Article] = []
        budget = self.settings.gdelt.time_budget_seconds
        started = self.clock()
        for brand in self.settings.brands:
            if self.clock() - started > budget:
                log.warning("GDELT time budget (%ss) used up; skipping remaining brands", budget)
                break
            batch = self.fetch(brand)
            log.info("GDELT       %-12s %3d articles", brand.id, len(batch))
            results.extend(batch)
            if self.errors >= MAX_FAILURES:
                log.warning("GDELT failed for %d brands; skipping it for this run", self.errors)
                break
        return results
