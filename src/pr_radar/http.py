"""Polite HTTP client: per-host minimum interval, retries, and rate-limit cooldowns."""

from __future__ import annotations

import logging
import time
from urllib.parse import urlparse

import requests
from requests.adapters import HTTPAdapter
from urllib3.util.retry import Retry

from . import __version__

log = logging.getLogger(__name__)

DEFAULT_USER_AGENT = f"pr-radar/{__version__} (+https://github.com/topics/media-monitoring)"
DEFAULT_COOLDOWNS = (20.0,)
MAX_RETRY_AFTER = 120.0


def _retry_after(response: requests.Response) -> float | None:
    value = response.headers.get("Retry-After", "")
    try:
        return min(float(value), MAX_RETRY_AFTER)
    except ValueError:
        return None


class HttpClient:
    def __init__(
        self,
        min_interval: dict[str, float] | None = None,
        cooldowns: dict[str, tuple[float, ...]] | None = None,
        timeout: float = 20.0,
        user_agent: str = DEFAULT_USER_AGENT,
    ) -> None:
        self.timeout = timeout
        self.min_interval = min_interval or {}
        # Waits after HTTP 429, per host. One entry per extra attempt.
        self.cooldowns = cooldowns or {}
        self.sleep = time.sleep  # swapped out in tests
        self._last_call: dict[str, float] = {}
        self.session = requests.Session()
        self.session.headers["User-Agent"] = user_agent
        retry = Retry(
            total=2,
            backoff_factor=2.0,
            # 429 is handled in get(): quick automatic retries only extend a rate-limit ban.
            status_forcelist=(500, 502, 503, 504),
            allowed_methods=("GET",),
        )
        self.session.mount("https://", HTTPAdapter(max_retries=retry))
        self.session.mount("http://", HTTPAdapter(max_retries=retry))

    def _wait_for_slot(self, host: str) -> None:
        interval = self.min_interval.get(host, 0.0)
        last = self._last_call.get(host)
        if interval and last is not None:
            wait = interval - (time.monotonic() - last)
            if wait > 0:
                self.sleep(wait)

    def get(self, url: str, params: dict | None = None) -> requests.Response:
        host = urlparse(url).hostname or ""
        cooldowns = self.cooldowns.get(host, DEFAULT_COOLDOWNS)
        for attempt in range(len(cooldowns) + 1):
            self._wait_for_slot(host)
            try:
                response = self.session.get(url, params=params, timeout=self.timeout)
            finally:
                self._last_call[host] = time.monotonic()
            if response.status_code != 429 or attempt == len(cooldowns):
                break
            wait = _retry_after(response) or cooldowns[attempt]
            log.info("%s rate limit hit, cooling down %.0fs", host, wait)
            self.sleep(wait)
        response.raise_for_status()
        return response
