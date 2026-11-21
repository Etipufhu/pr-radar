from datetime import datetime

from conftest import FIXTURES

from pr_radar.collectors.rss import RssCollector, clean, parse_feed
from pr_radar.config import Brand, RssFeed, RssSettings, Settings
from pr_radar.matching import BrandMatcher
from pr_radar.pipeline import tag

BRANDS = [
    Brand(id="foreo", name="FOREO", query='"FOREO"'),
    Brand(id="currentbody", name="CurrentBody", query='"CurrentBody"'),
    Brand(id="solawave", name="Solawave", query='"Solawave"'),
]
FEED = RssFeed(url="https://www.examplebeauty.com/feed", country="GB", language="en")
PAYLOAD = (FIXTURES / "outlet_feed.xml").read_bytes()


def test_clean_strips_html_and_entities():
    assert clean("<p>From <strong>CurrentBody</strong> &amp; more</p>") == "From CurrentBody & more"


def test_parse_keeps_only_items_that_name_a_brand():
    articles = parse_feed(
        PAYLOAD, feed=FEED, matcher=BrandMatcher(BRANDS), since=datetime(2026, 11, 1)
    )
    # LED-mask round-up names two brands in the teaser -> one article per brand;
    # the FOREO launch names FOREO in the title. The routine piece, the March
    # review (outside the window) and the undated item are dropped.
    assert sorted((a.title, a.query_brand) for a in articles) == [
        ("FOREO launches a new cleansing brush", "foreo"),
        ("The 12 best LED masks, tested by our editors", "currentbody"),
        ("The 12 best LED masks, tested by our editors", "solawave"),
    ]
    launch = next(a for a in articles if a.query_brand == "foreo")
    assert launch.collector == "rss"
    assert launch.source_name == "Example Beauty & Style"
    assert launch.source_domain == "examplebeauty.com"
    assert launch.country == "GB" and launch.language == "en"
    assert launch.published_at == datetime(2026, 11, 18, 12, 0)


def test_teaser_mentions_are_not_headline_mentions():
    settings = Settings(primary_brand="foreo", brands=BRANDS, editions=[])
    articles = tag(parse_feed(PAYLOAD, feed=FEED, matcher=BrandMatcher(BRANDS)), settings)
    roundup = next(a for a in articles if a.title.startswith("The 12 best"))
    assert roundup.headline_brands == []
    launch = next(a for a in articles if a.title.startswith("FOREO"))
    assert launch.headline_brands == ["foreo"]


def test_collector_counts_failed_feeds(monkeypatch):
    import requests

    class Http:
        min_interval: dict = {}

        def get(self, url):
            if "broken" in url:
                raise requests.ConnectionError("down")

            class R:
                content = PAYLOAD

            return R()

    feeds = [FEED, RssFeed(url="https://broken.example/feed", country="US")]
    settings = Settings(
        primary_brand="foreo", brands=BRANDS, editions=[], lookback_days=30,
        rss=RssSettings(feeds=feeds),
    )  # fmt: skip
    monkeypatch.setattr("pr_radar.collectors.rss.datetime", _FixedNow)
    collector = RssCollector(settings, Http())
    assert len(collector.collect()) == 3 and collector.errors == 1


class _FixedNow(datetime):
    @classmethod
    def now(cls, tz=None):
        return datetime(2026, 11, 21, tzinfo=tz)
