from datetime import datetime
from urllib.parse import parse_qs, urlparse

import pytest
import requests
from conftest import FIXTURES

from pr_radar.collectors.gdelt import (
    GdeltCollector,
    build_params,
    build_query,
    parse_response,
)
from pr_radar.collectors.google_news import build_url, parse_feed
from pr_radar.config import Brand, Edition
from pr_radar.http import HttpClient

US = Edition(hl="en-US", gl="US", ceid="US:en")


def test_google_news_url_has_market_and_window():
    qs = parse_qs(urlparse(build_url('"FOREO"', US, 7)).query)
    assert qs["q"] == ['"FOREO" when:7d']
    assert qs["gl"] == ["US"] and qs["ceid"] == ["US:en"]


def test_parse_google_news_feed():
    articles = parse_feed((FIXTURES / "google_news.xml").read_bytes(), brand_id="foreo", edition=US)
    assert len(articles) == 2  # item without a date is skipped

    first = articles[0]
    assert first.title == "FOREO unveils a new facial cleansing device for sensitive skin"
    assert first.source_name == "Example Beauty"
    assert first.source_domain == "examplebeauty.com"
    assert first.published_at == datetime(2026, 11, 17, 9, 30)
    assert first.country == "US"
    assert first.language == "en"

    german = articles[1]
    assert german.source_domain == "stern.de"
    assert german.language == "de"  # detected from the headline, not the US edition


def test_gdelt_query_wraps_or_terms():
    assert build_query('"TheraFace" OR "Therabody"') == '("TheraFace" OR "Therabody")'
    assert build_query('"FOREO"') == '"FOREO"'
    brand = Brand(id="x", name="X", query='"X"')
    params = build_params(brand, 7, 250)
    assert params["timespan"] == "7d" and params["mode"] == "ArtList"


def test_parse_gdelt_response():
    articles = parse_response((FIXTURES / "gdelt.json").read_text("utf-8"), brand_id="nuface")
    assert len(articles) == 2  # bad date skipped
    uk, tr = articles
    assert uk.source_domain == "example-news.co.uk"
    assert uk.language == "en" and uk.country == "GB"
    assert uk.published_at == datetime(2026, 11, 18, 14, 30)
    assert tr.language == "tr" and tr.country == "TR"


def test_gdelt_plain_text_error_is_not_fatal():
    assert parse_response("Please limit requests to one every 5 seconds", brand_id="x") == []
    assert parse_response("", brand_id="x") == []
    assert parse_response("{}", brand_id="x") == []


class _Resp:
    def __init__(self, status: int, text: str = "", headers: dict | None = None):
        self.status_code, self.text, self.headers = status, text, headers or {}

    def raise_for_status(self):
        if self.status_code >= 400:
            raise requests.HTTPError(f"{self.status_code}", response=self)


class _FakeSession:
    def __init__(self, replies):
        self.replies, self.calls = list(replies), 0

    def get(self, url, params=None, timeout=None):
        self.calls += 1
        return self.replies.pop(0)


def _client(replies, **kwargs):
    http = HttpClient(**kwargs)
    http.session = _FakeSession(replies)
    slept = []
    http.sleep = slept.append
    return http, slept


def test_http_client_cools_down_on_429_then_succeeds():
    http, slept = _client(
        [_Resp(429), _Resp(429), _Resp(200, "ok")], cooldowns={"example.org": (30.0, 90.0)}
    )
    assert http.get("https://example.org/feed").text == "ok"
    assert slept == [30.0, 90.0]


def test_http_client_honours_retry_after_and_gives_up():
    http, slept = _client([_Resp(429, headers={"Retry-After": "7"}), _Resp(429)])
    with pytest.raises(requests.HTTPError):
        http.get("https://example.org/feed")  # default: one cooldown, then give up
    assert slept == [7.0]


def test_gdelt_stops_after_repeated_failures(settings):
    settings.gdelt.enabled = True
    http, _ = _client([_Resp(429)] * 20)
    collector = GdeltCollector(settings, http)
    assert collector.collect() == []
    assert collector.errors == 2
    assert http.session.calls == 2 * 3  # two brands x (1 try + 2 cooldown retries), rest skipped


def test_gdelt_respects_time_budget(settings):
    payload = (FIXTURES / "gdelt.json").read_text("utf-8")
    http, _ = _client([_Resp(200, payload)] * 10)
    collector = GdeltCollector(settings, http)
    ticks = iter([0, 0, 100, 200])  # start, brand 1, brand 2, brand 3 (over 180 s budget)
    collector.clock = lambda: next(ticks)
    assert len(collector.collect()) == 4  # two brands x two fixture articles
    assert http.session.calls == 2


def test_gdelt_is_opt_in(settings):
    assert settings.gdelt.enabled is False


def test_google_news_runs_extra_queries_only_when_the_brand_has_coverage():
    from pr_radar.collectors.google_news import GoogleNewsCollector
    from pr_radar.config import Settings

    payload = (FIXTURES / "google_news.xml").read_bytes()
    asked = []

    class Http:
        min_interval: dict = {}

        def get(self, url):
            q = parse_qs(urlparse(url).query)["q"][0]
            asked.append((q, parse_qs(urlparse(url).query)["gl"][0]))

            class R:
                content = payload if parse_qs(urlparse(url).query)["gl"] == ["US"] else b"<rss/>"

            return R()

    brand = Brand(id="foreo", name="FOREO", query='"FOREO"', extra_queries=['"FOREO LUNA"'])
    de = Edition(hl="de", gl="DE", ceid="DE:de")
    settings = Settings(primary_brand="foreo", brands=[brand], editions=[US, de])
    articles = GoogleNewsCollector(settings, Http()).collect()
    assert asked == [
        ('"FOREO" when:7d', "US"),
        ('"FOREO LUNA" when:7d', "US"),
        ('"FOREO" when:7d', "DE"),  # nothing in DE, so no product query there
    ]
    assert len(articles) == 4
