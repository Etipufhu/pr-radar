from datetime import datetime, timedelta

from conftest import make_article

from pr_radar import analytics as an
from pr_radar.narrative.checks import check_brief
from pr_radar.narrative.facts import fact_sheet, weekly_facts
from pr_radar.narrative.writer import load_brief, save_brief, write_brief
from pr_radar.report import build_context, render

NOW = datetime(2026, 11, 20)
W = an.Window(NOW - timedelta(days=7), NOW)
DAY = timedelta(days=1)

GOOD = """Summary: FOREO had 2 mentions this week, 33% share of voice, behind NuFACE.
Therabody faces a recall headline on cpsc.gov.
Actions:
- Pitch stern.de, which covered NuFACE twice.
- Offer deals pricing stories, where NuFACE leads."""


def _facts(store, settings):
    arts = [
        make_article("FOREO launch one", "vogue.com", ["foreo"], NOW - 2 * DAY, "US", ["launch"]),
        make_article("FOREO review two", "allure.com", ["foreo"], NOW - 3 * DAY, "US"),
        make_article("NuFACE deal a", "stern.de", ["nuface"], NOW - DAY, "DE", ["deals_pricing"]),
        make_article("NuFACE deal b", "stern.de", ["nuface"], NOW - DAY, "DE", ["deals_pricing"]),
        make_article("NuFACE deal c", "bild.de", ["nuface"], NOW - DAY, "DE", ["deals_pricing"]),
        make_article("Therabody Recalls Charger", "cpsc.gov", ["therabody"], NOW - DAY, "US"),
    ]
    store.upsert(arts, NOW)
    store.refresh_tags(settings)
    return weekly_facts(store.con, settings, W)


def test_fact_sheet_has_the_numbers(store, settings):
    f = _facts(store, settings)
    sheet = fact_sheet(f)
    assert "#1 NuFACE: 3 mentions, 50%" in sheet
    assert "no week-over-week changes" in sheet
    assert "Therabody Recalls Charger" in sheet and "stern.de: 2 competitor articles" in sheet


def test_checks_pass_a_grounded_brief(store, settings):
    f = _facts(store, settings)
    res = check_brief(GOOD, fact_sheet(f), f)
    assert res.ok, res.errors


def test_checks_catch_made_up_facts(store, settings):
    f = _facts(store, settings)
    bad = GOOD.replace("33%", "41%").replace("stern.de", "nytimes.com")
    bad = bad.replace("Therabody faces a recall headline on cpsc.gov.", "Coverage rose sharply.")
    errors = " | ".join(check_brief(bad, fact_sheet(f), f).errors)
    assert "number not in the data: 41" in errors
    assert "outlet not in the data: nytimes.com" in errors
    assert "without a previous period" in errors
    assert "risk headline" in errors

    leak = GOOD.replace("Pitch stern.de", "Re-pitch stern.de and send review units to Japan")
    errors = " | ".join(check_brief(leak, fact_sheet(f), f).errors)
    assert "says re-pitch" in errors
    assert "country not in the fact sheet: JP" in errors
    assert "copied from the prompt example: review units" in errors


def test_checks_flag_stock_phrases(store, settings):
    f = _facts(store, settings)
    res = check_brief(GOOD + "\n- It's worth noting the crucial landscape.", fact_sheet(f), f)
    assert res.ok
    assert len(res.style) == 3


def test_write_brief_retries_and_publishes(store, settings, tmp_path):
    f = _facts(store, settings)
    outputs = iter(["FOREO is up 400% this week.", GOOD])
    calls = []

    def fake(msgs, sample):
        calls.append(sample)
        assert "Fact sheet:" in msgs[-1]["content"]
        return next(outputs)

    brief = write_brief(f, fake, "fake-llm", tries=3)
    assert calls == [False, True]  # draft, then a sampled redraft
    assert brief.published and brief.text == GOOD

    save_brief(brief, tmp_path)
    assert load_brief(tmp_path, f["start"], f["end"]).text == GOOD
    html = render(build_context(store.con, settings, W, briefs_dir=tmp_path))
    assert "Weekly brief" in html and "Pitch stern.de" in html


def test_failed_brief_is_not_published(store, settings, tmp_path):
    f = _facts(store, settings)
    brief = write_brief(f, lambda m, s: "FOREO grew 12%.", "fake-llm", tries=2)
    assert not brief.published
    save_brief(brief, tmp_path)
    html = render(build_context(store.con, settings, W, briefs_dir=tmp_path))
    assert "Weekly brief" not in html


def test_training_weeks_vary_the_brand_and_avoid_eval_seeds():
    from pr_radar.narrative.distill import TRAIN_SEED_OFFSET, content_score, training_weeks

    weeks = training_weeks(["FOREO", "NuFACE", "Therabody", "PMD Beauty"], 20)
    assert len({w["primary"] for w in weeks}) > 1
    assert TRAIN_SEED_OFFSET >= 1000  # brief-eval uses seeds 0..weeks-1
    w = weeks[0]
    assert content_score(f"{w['primary']} and more", w) >= 1


def test_encode_masks_the_prompt():
    from pr_radar.narrative.lora import encode

    class Tok:
        eos_token = "<eos>"

        def apply_chat_template(self, conv, **kw):
            return "".join(m["content"] for m in conv) + "|"

        def __call__(self, text, add_special_tokens=False):
            return {"input_ids": [ord(c) for c in text]}

    conv = [{"role": "user", "content": "abc"}, {"role": "assistant", "content": "xy"}]
    row = encode(Tok(), conv, max_length=100)
    assert row["input_ids"] == [ord(c) for c in "abc|xy<eos>"]
    assert row["labels"][:4] == [-100] * 4 and row["labels"][4:6] == [ord("x"), ord("y")]
