import json
from datetime import datetime, timedelta

import pytest
from conftest import ROOT, make_article

from pr_radar.cli import main
from pr_radar.storage import Store
from pr_radar.web_export import build_payload, write_web_data

NOW = datetime(2026, 11, 20)
END = NOW - timedelta(days=1)  # last day of the window -> window ends at NOW
DAY = timedelta(days=1)


def _articles():
    arts = [
        # last 7 days: foreo 2 (US), nuface 3 (DE), solawave 1 with nuface (US)
        make_article("FOREO launch one", "vogue.com", ["foreo"], NOW - 2 * DAY, "US", ["launch"]),
        make_article("FOREO review two", "allure.com", ["foreo"], NOW - 3 * DAY, "US", ["reviews"]),
        make_article(
            "NuFACE deal a", "bild.de", ["nuface"], NOW - 1 * DAY, "DE", ["deals_pricing"]
        ),
        make_article("NuFACE gift c", "stern.de", ["nuface"], NOW - 2 * DAY, "DE", ["gift_guides"]),
        make_article(
            "NuFACE and Solawave e",
            "elle.com",
            ["nuface", "solawave"],
            NOW - 4 * DAY,
            "US",
            ["deals_pricing"],
        ),
        # older, only inside the 28-day window; elle.com covered foreo before
        *[
            make_article(f"FOREO old {i}", "elle.com", ["foreo"], NOW - 12 * DAY, "US")
            for i in range(3)
        ],
    ]
    for a in arts:
        a.cluster_id = a.id
    return arts


@pytest.fixture
def seeded(store):
    store.upsert(_articles(), NOW)
    return store


def test_payload_has_both_windows_and_metadata(seeded, settings):
    data = build_payload(seeded.con, settings, END)
    assert data["primary"] == "foreo"
    assert data["brands"]["nuface"] == "NuFACE"
    assert set(data["windows"]) == {"7", "28"}
    assert data["default_window"] == "7"
    assert data["aspect_sentiment"] == []
    assert data["generated_at"].endswith("Z")

    week = data["windows"]["7"]
    assert (week["start"], week["end"], week["days"]) == ("2026-11-13", "2026-11-19", 7)
    month = data["windows"]["28"]
    assert month["start"] == "2026-10-23" and month["days"] == 28
    assert month["kpis"]["mentions"] == 5  # old foreo coverage counts in the 28-day window


def test_kpis_and_first_period(seeded, settings):
    k = build_payload(seeded.con, settings, END)["windows"]["7"]["kpis"]
    assert k["mentions"] == 2
    assert k["share"] == pytest.approx(2 / 6)
    assert k["share_change_pts"] is None  # previous week was never collected
    assert (k["outlets"], k["markets"], k["rank"], k["brands"]) == (2, 1, 2, 3)
    assert k["total_mentions"] == 6


def test_payload_is_strict_json(seeded, settings):
    data = build_payload(seeded.con, settings, END)
    # allow_nan=False fails on NaN/inf; default=None fails on timestamps or numpy types.
    text = json.dumps(data, allow_nan=False)
    week = json.loads(text)["windows"]["7"]

    gaps = {o["outlet"]: o for o in week["outlet_gaps"]}
    assert gaps["elle.com"]["competitors"] == ["nuface", "solawave"]
    assert gaps["elle.com"]["primary_all_time"] == 3  # warm contact
    assert "vogue.com" not in gaps

    topics = {t["topic"]: t for t in week["topic_gaps"]}
    assert topics["launch"]["top_competitor"] is None
    # 2 of 3 competitor articles are deals vs 0 of 2 foreo articles
    assert topics["deals_pricing"]["gap_pts"] == pytest.approx(200 / 3, abs=1e-6)

    story = week["top_stories"][0]
    assert isinstance(story["brands"], list) and isinstance(story["markets"], list)
    assert story["first_seen"].startswith("2026-11-")
    assert {r["country"] for r in week["market_share"]} == {"DE", "US"}
    assert week["market_gaps"] == []  # DE has 3 mentions, below the 5-mention minimum
    assert week["insights"][0].startswith("FOREO share of voice is 33%")


def test_aspect_sentiment_passthrough(seeded, settings):
    rows = [{"brand": "foreo", "aspect": "price", "valence": 6.2, "arousal": 5.1}]
    data = build_payload(seeded.con, settings, END, aspect_sentiment=rows)
    assert data["aspect_sentiment"] == rows


def _save_brief(tmp_path, start, end, published):
    from pr_radar.narrative.writer import Brief, save_brief

    text = "Summary: FOREO had 2 mentions.\nActions:\n- Pitch bild.de.\n- Pitch stern.de."
    brief = Brief(
        text, "Qwen/Qwen3-1.7B + LoRA", published, [], [], 1, {"start": start, "end": end}
    )
    save_brief(brief, tmp_path / "briefs")


def test_published_brief_is_in_its_window_only(seeded, settings, tmp_path):
    _save_brief(tmp_path, "2026-11-13", "2026-11-19", published=True)
    data = build_payload(seeded.con, settings, END, briefs_dir=tmp_path / "briefs")
    brief = data["windows"]["7"]["brief"]
    assert brief["summary"] == "FOREO had 2 mentions."
    assert brief["actions"] == ["Pitch bild.de.", "Pitch stern.de."]
    assert brief["model"] == "Qwen3-1.7B + LoRA" and brief["checks_passed"] is True
    assert brief["created_at"]
    assert brief["start"] == "2026-11-13" and brief["end"] == "2026-11-19"
    assert data["windows"]["28"]["brief"] is None  # a 7-day brief does not fill a 28-day window


def test_newest_fitting_brief_is_used(seeded, settings, tmp_path):
    # The dashboard is rebuilt on a schedule, so the window rarely matches a brief exactly.
    _save_brief(tmp_path, "2026-11-10", "2026-11-16", published=True)
    _save_brief(tmp_path, "2026-11-11", "2026-11-17", published=False)
    _save_brief(tmp_path, "2026-11-01", "2026-11-07", published=True)  # older than the window
    data = build_payload(seeded.con, settings, END, briefs_dir=tmp_path / "briefs")
    assert data["windows"]["7"]["brief"]["end"] == "2026-11-16"


def test_unpublished_or_missing_brief_is_null(seeded, settings, tmp_path):
    data = build_payload(seeded.con, settings, END, briefs_dir=tmp_path / "briefs")
    assert data["windows"]["7"]["brief"] is None
    _save_brief(tmp_path, "2026-11-13", "2026-11-19", published=False)
    data = build_payload(seeded.con, settings, END, briefs_dir=tmp_path / "briefs")
    assert data["windows"]["7"]["brief"] is None


def test_write_web_data_writes_json_and_script(seeded, settings, tmp_path):
    path = write_web_data(seeded.con, settings, tmp_path / "web", END)
    data = json.loads(path.read_text(encoding="utf-8"))
    script = (tmp_path / "web" / "data.js").read_text(encoding="utf-8")
    assert script.startswith("window.PR_RADAR_DATA = ")
    assert json.loads(script.removeprefix("window.PR_RADAR_DATA = ").rstrip().rstrip(";")) == data


def test_cli_export_web_reads_database_read_only(settings, tmp_path, capsys):
    db = tmp_path / "radar.duckdb"
    store = Store(db)
    store.upsert(_articles(), NOW)
    store.close()

    out = tmp_path / "site"
    args = ["--config", str(ROOT / "config" / "brands.yaml"), "--db", str(db)]
    assert main([*args, "export-web", "--out", str(out), "--end", "2026-11-19"]) == 0
    assert "web data:" in capsys.readouterr().out
    data = json.loads((out / "data.json").read_text(encoding="utf-8"))
    assert data["windows"]["7"]["kpis"]["mentions"] == 2
