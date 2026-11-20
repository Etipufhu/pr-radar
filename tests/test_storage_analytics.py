from datetime import datetime, timedelta

import pytest
from conftest import make_article

from pr_radar import analytics as an
from pr_radar.report import build_context, default_window, render
from pr_radar.storage import Store

NOW = datetime(2026, 11, 20)
W = an.Window(NOW - timedelta(days=7), NOW)
DAY = timedelta(days=1)


@pytest.fixture
def seeded(store):
    arts = [
        # current week: foreo 2 (US), nuface 5 (DE x4, US x1), solawave 1
        make_article("FOREO launch one", "vogue.com", ["foreo"], NOW - 2 * DAY, "US", ["launch"]),
        make_article("FOREO review two", "allure.com", ["foreo"], NOW - 3 * DAY, "US", ["reviews"]),
        make_article(
            "NuFACE deal a", "bild.de", ["nuface"], NOW - 1 * DAY, "DE", ["deals_pricing"]
        ),
        make_article(
            "NuFACE deal b", "stern.de", ["nuface"], NOW - 1 * DAY, "DE", ["deals_pricing"]
        ),
        make_article("NuFACE gift c", "stern.de", ["nuface"], NOW - 2 * DAY, "DE", ["gift_guides"]),
        make_article("NuFACE d", "focus.de", ["nuface"], NOW - 2 * DAY, "DE"),
        make_article(
            "NuFACE and Solawave e",
            "elle.com",
            ["nuface", "solawave"],
            NOW - 4 * DAY,
            "US",
            ["deals_pricing"],
        ),
        # previous week: foreo 4, nuface 1; elle.com covered foreo before
        *[
            make_article(f"FOREO old {i}", "elle.com", ["foreo"], NOW - 9 * DAY, "US")
            for i in range(4)
        ],
        make_article("NuFACE old", "bild.de", ["nuface"], NOW - 10 * DAY, "DE"),
    ]
    for a in arts:
        a.cluster_id = a.id
    store.upsert(arts, NOW)
    return store


def test_upsert_merges_brands_instead_of_duplicating(store):
    a = make_article("Shared headline", "vogue.com", ["foreo"], NOW)
    b = make_article("Shared headline", "vogue.com", ["nuface"], NOW)
    assert store.upsert([a], NOW) == (1, 0)
    assert store.upsert([b], NOW) == (0, 1)
    assert store.upsert([b], NOW) == (0, 0)
    assert store.count() == 1
    assert store.con.execute("SELECT brands FROM articles").fetchone()[0] == ["foreo", "nuface"]


def test_share_of_voice_sums_to_one(seeded):
    sov = an.share_of_voice(seeded.con, W)
    assert sov["share"].sum() == pytest.approx(1.0)
    assert sov.iloc[0]["brand"] == "nuface"
    assert dict(zip(sov["brand"], sov["mentions"], strict=True)) == {
        "nuface": 5,
        "foreo": 2,
        "solawave": 1,
    }


def test_period_comparison(seeded):
    comp = an.period_comparison(seeded.con, W).set_index("brand")
    assert comp.loc["foreo", "mentions_prev"] == 4
    assert comp.loc["foreo", "share_change_pts"] == pytest.approx((2 / 8 - 4 / 5) * 100)


def test_market_gaps(seeded):
    gaps = an.market_gaps(seeded.con, W, "foreo", min_mentions=1)
    de = gaps.set_index("country").loc["DE"]
    assert de["leader"] == "nuface" and de["primary_share"] == 0
    assert de["gap_pts"] == pytest.approx(100)


def test_outlet_gaps_flag_warm_contacts(seeded):
    gaps = an.outlet_gaps(seeded.con, W, "foreo").set_index("outlet")
    assert "vogue.com" not in gaps.index  # covered foreo this week
    assert gaps.loc["stern.de", "competitor_articles"] == 2
    assert list(gaps.loc["elle.com", "competitors"]) == ["nuface", "solawave"]
    assert gaps.loc["elle.com", "primary_all_time"] == 4


def test_topic_gaps(seeded):
    gaps = an.topic_gaps(seeded.con, W, "foreo").set_index("topic")
    # 3 of 5 competitor articles are deals vs 0 of 2 foreo articles
    assert gaps.loc["deals_pricing", "gap_pts"] == pytest.approx(60)
    assert gaps.loc["deals_pricing", "top_competitor"] == "nuface"
    assert gaps.loc["launch", "gap_pts"] == pytest.approx(-50)


def test_insights_and_report_render(seeded, settings):
    lines = an.insights(seeded.con, W, "foreo", settings.brand_names)
    assert lines[0].startswith("FOREO share of voice is 25%")
    assert any("outlets covered competitors but not FOREO" in line for line in lines)
    assert any("Narrative gap: 'deals_pricing'" in line for line in lines)

    html = render(build_context(seeded.con, settings, W))
    assert "<svg" in html and "stern.de" in html and "NuFACE" in html


def test_default_window_is_whole_days():
    w = default_window(7, datetime(2026, 11, 19, 15, 30))
    assert w.end == datetime(2026, 11, 20) and w.start == datetime(2026, 11, 13)


def test_archive_roundtrip(seeded, tmp_path):
    ids = [r[0] for r in seeded.con.execute("SELECT id FROM articles").fetchall()]
    seeded.export_archive(ids, tmp_path, NOW)

    # A later run touches one article again with an extra brand.
    later = make_article("FOREO launch one", "vogue.com", ["foreo", "pmd"], NOW - 2 * DAY)
    seeded.upsert([later], NOW + DAY)
    seeded.export_archive([later.id], tmp_path, NOW + DAY)

    fresh = Store(":memory:")
    assert fresh.bootstrap_from_archive(tmp_path) == len(ids)
    brands = fresh.con.execute("SELECT brands FROM articles WHERE id = ?", [later.id]).fetchone()[0]
    assert brands == ["foreo", "pmd"]
    assert fresh.bootstrap_from_archive(tmp_path) == 0  # no-op when not empty
    fresh.close()


def test_no_fake_deltas_on_first_period(seeded, settings):
    # Seeded rows were first seen at NOW, so with a 7-day lookback the previous
    # window (Nov 6-13) was never collected.
    assert not an.has_baseline(seeded.con, W, lookback_days=7)
    first = an.insights(seeded.con, W, "foreo", settings.brand_names, lookback_days=7)[0]
    assert "first tracked period" in first
    html = render(build_context(seeded.con, settings, W))
    assert "SoV change (first period)" in html

    assert an.has_baseline(seeded.con, W, lookback_days=14)
    first = an.insights(seeded.con, W, "foreo", settings.brand_names, lookback_days=14)[0]
    assert "pts vs previous period" in first


def test_report_shows_dash_not_nan_for_missing_competitor(seeded, settings):
    html = render(build_context(seeded.con, settings, W))
    assert ">nan<" not in html


def test_headline_vs_body_mentions_and_exclusions(store, settings):
    body_only = make_article("Best LED masks of the year", "nymag.com", ["foreo"], NOW - DAY)
    headline = make_article("FOREO and NuFACE go head to head", "vogue.com", ["foreo"], NOW - DAY)
    junk = make_article("Unrelated transport story", "junk.example", ["nuface"], NOW - DAY)
    store.upsert([body_only, headline, junk], NOW)

    settings.exclude_domains = ["junk.example"]
    assert store.refresh_tags(settings) >= 1
    assert store.count() == 2
    assert store.refresh_tags(settings) == 0  # idempotent

    sov = an.share_of_voice(store.con, W).set_index("brand")
    assert sov.loc["foreo", "mentions"] == 2
    assert sov.loc["foreo", "headline_mentions"] == 1
    assert sov.loc["nuface", "headline_mentions"] == 1  # added from the headline by re-tagging
    assert sov["headline_share"].sum() == pytest.approx(1.0)


def test_sentiment_scoring_and_analytics(store, settings):
    from pr_radar.sentiment.scoring import score_new_mentions

    good = make_article("FOREO wins best beauty device award", "vogue.com", ["foreo"], NOW - DAY)
    bad = make_article("NuFACE recall sparks outrage", "bbc.co.uk", ["nuface"], NOW - DAY)
    body = make_article("Best LED masks of the year", "nymag.com", ["foreo"], NOW - DAY)
    store.upsert([good, bad, body], NOW)
    store.refresh_tags(settings)

    seen = []

    def fake_predict(aspects, texts):
        seen.extend(zip(aspects, texts, strict=True))
        return [(8.0, 6.0) if "award" in t else (2.0, 7.5) for t in texts]

    assert score_new_mentions(store, settings, "models/fake", predict=fake_predict) == 2
    assert ("FOREO", good.title) in seen and ("NuFACE", bad.title) in seen  # body-only skipped
    assert score_new_mentions(store, settings, "models/fake", predict=fake_predict) == 0

    bs = an.brand_sentiment(store.con, W).set_index("brand")
    assert bs.loc["foreo", "valence"] == 8.0 and bs.loc["foreo", "positive_share"] == 1.0
    assert bs.loc["nuface", "heated"] == 1

    lines = an.insights(store.con, W, "foreo", settings.brand_names)
    assert any("headline tone: valence 8.0/9" in line for line in lines)
    assert any(line.startswith("Watch: 'NuFACE recall sparks outrage'") for line in lines)

    html = render(build_context(store.con, settings, W))
    assert "Headline tone (DimABSA)" in html and "NuFACE recall sparks outrage" in html


def test_risk_keywords_flag_recalls(store, settings):
    recall = make_article(
        "Therabody Recalls Theragun Charger", "cpsc.gov", ["therabody"], NOW - DAY
    )
    store.upsert([recall], NOW)
    store.refresh_tags(settings)
    lines = an.insights(store.con, W, "foreo", settings.brand_names)
    assert "Risk signal for Therabody: 'Therabody Recalls Theragun Charger' (cpsc.gov)." in lines


def test_calibration_roundtrip():
    from pr_radar.sentiment.experiment import apply_calibration, fit_calibration

    pred = [(7.0, 7.0), (8.0, 8.0), (6.0, 6.5)]
    gold = [(6.0, 5.0), (7.0, 6.0), (5.0, 4.5)]
    cal = fit_calibration(pred, gold)
    out = apply_calibration(pred, cal)
    assert [round(v, 2) for v, _ in out] == [6.0, 7.0, 5.0]
    assert apply_calibration([(12.0, 0.0)], None) == [(12.0, 0.0)]
