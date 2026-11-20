from datetime import datetime

from conftest import make_article

from pr_radar.config import Brand
from pr_radar.dedup import assign_clusters, merge_duplicates
from pr_radar.matching import BrandMatcher, TopicMatcher
from pr_radar.text import domain_of, normalize_title, strip_source_suffix

T = datetime(2026, 11, 17, 12)


def test_text_helpers():
    assert domain_of("https://www.Vogue.com/article") == "vogue.com"
    assert domain_of("example.org") == "example.org"
    assert strip_source_suffix("Big news - Vogue", "Vogue") == "Big news"
    assert normalize_title("  FOREO’s NEW device!! ") == "foreo s new device"


def test_brand_matcher_respects_word_boundaries_and_excludes():
    matcher = BrandMatcher(
        [
            Brand(id="foreo", name="FOREO", query="", aliases=["FOREO"]),
            Brand(id="pmd", name="PMD", query="", aliases=["PMD Beauty"], exclude=["PMD stock"]),
        ]
    )
    assert matcher.match("Foreo launches a device") == ["foreo"]
    assert matcher.match("A foreordained outcome") == []
    assert matcher.match("PMD Beauty and FOREO face off") == ["foreo", "pmd"]
    assert matcher.match("PMD Beauty owner: PMD stock rises") == []


def test_topic_matcher_prefixes_and_languages(settings):
    topics = TopicMatcher(settings.topics)
    assert "sustainability" in topics.match("Why sustainable beauty tech matters")
    assert "deals_pricing" in topics.match("Black Friday: 40% off face devices")
    assert "deals_pricing" in topics.match("Cilt bakım cihazlarında büyük indirim")
    assert "launch" in topics.match("NuFACE lanza un nuevo dispositivo")
    assert topics.match("Quarterly weather outlook") == []


def test_merge_duplicates_unions_brands_and_prefers_publisher_url():
    gn = make_article("Same headline here", "vogue.com", ["foreo"], T, collector="google_news")
    gn.url = "https://news.google.com/rss/articles/abc"
    gd = make_article("Same headline here", "vogue.com", ["nuface"], T)
    merged = merge_duplicates([gn, gd])
    assert len(merged) == 1
    assert merged[0].brands == ["foreo", "nuface"]
    assert merged[0].url.startswith("https://vogue.com/")


def test_clusters_group_syndicated_copies_only():
    a = make_article("FOREO unveils new LED face mask for at-home skincare", "a.com", ["foreo"], T)
    b = make_article("FOREO unveils new LED face mask for at home skincare", "b.com", ["foreo"], T)
    c = make_article("NuFACE cuts prices for Black Friday", "c.com", ["nuface"], T)
    assign_clusters([a, b, c])
    assert a.cluster_id == b.cluster_id == a.id
    assert c.cluster_id == c.id


def test_clusters_join_existing_story():
    new = make_article(
        "FOREO unveils new LED face mask for at-home skincare", "z.com", ["foreo"], T
    )
    assign_clusters(
        [new], existing=[("old-cluster", "FOREO unveils new LED face mask for at-home skincare!")]
    )
    assert new.cluster_id == "old-cluster"
