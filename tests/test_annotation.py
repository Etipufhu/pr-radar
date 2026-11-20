"""Candidate selection and JSONL schema for the FOREO-domain DimABSA set (annotation/)."""

from __future__ import annotations

import re
import sys
from collections import Counter
from datetime import datetime
from pathlib import Path

import pytest
from conftest import make_article

from pr_radar.storage import Store

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "annotation"))

import build_candidates as bc  # noqa: E402
import dimabsa_format as fmt  # noqa: E402

SILVER = ROOT / "data" / "annotations" / "foreo_domain_v1.silver.jsonl"


def cand(cid: str, title: str, brand: str = "foreo", lang: str = "en", **kw) -> bc.Candidate:
    return bc.Candidate(
        id=cid,
        title=title,
        url=None,
        source_domain="x.com",
        language=lang,
        country="US",
        brands=[brand],
        topics=kw.pop("topics", []),
        published_at="2026-11-20T00:00:00",
        cluster_id=kw.pop("cluster_id", cid),
        source_db="t.duckdb",
        brands_in_title=kw.pop("brands_in_title", []),
    )


def test_score_prefers_evaluative_headlines():
    good = cand("a", "The best FOREO deal: 40% off the viral Luna 4", topics=["deals_pricing"])
    plain = cand("b", "FOREO opens office in Stockholm", topics=["business"])
    assert bc.score(good) > bc.score(plain)
    assert "best" in good.cues


def test_cue_words_do_not_match_inside_other_words():
    c = cand("a", "Public Transportation Reaches New Riders")
    bc.score(c)
    assert c.cues == []


def test_dedupe_drops_same_cluster_and_rewrites():
    items = [
        cand("1", "Therabody Acquires Embr Labs Thermal Technology, Expands Women's Health"),
        cand("2", "Therabody Acquires Embr Labs Thermal Technology"),  # contained in 1
        cand("3", "A different story about LED masks", cluster_id="1"),  # same cluster as 1
        cand("4", "CurrentBody Series 3 review: best LED mask"),
    ]
    assert [c.id for c in bc.dedupe(items)] == ["1", "4"]


def test_select_balances_brands_and_languages():
    titles = [
        "The best FOREO Luna 4 deal",
        "Bear 2 review: worth it",
        "UFO 3 mask is the best gift",
        "Issa toothbrush now 30% off",
        "I tried Peach 2 and loved it",
        "Faq 211: an amazing launch",
    ]
    items = [cand(f"f{i}", t, "foreo") for i, t in enumerate(titles)]
    items += [cand("n1", "NuFACE device worth it?", "nuface", "es")]
    items += [cand("s1", "Solawave deal: best price", "solawave", "fr")]
    picked = bc.select(items, n=5, min_score=0)
    brands = Counter(b for c in picked for b in c.brands)
    assert len(picked) == 5
    assert brands["nuface"] == 1 and brands["solawave"] == 1


def test_load_articles_reads_store_read_only(tmp_path):
    db = tmp_path / "t.duckdb"
    store = Store(db)
    arts = [
        make_article("FOREO Luna 4 is the best", "a.com", ["foreo"], datetime(2026, 11, 18)),
        make_article("Therabody recall", "b.com", ["therabody"], datetime(2026, 11, 19)),
    ]
    for a in arts:
        a.cluster_id = a.id
    store.upsert(arts, datetime(2026, 11, 20))
    store.close()

    rows = bc.load_articles([db, tmp_path / "missing.duckdb"])
    assert {r.title for r in rows} == {a.title for a in arts}
    assert all(r.source_db == "t.duckdb" for r in rows)


def quad(**over) -> dict:
    q = {"Aspect": "Luna 4", "Category": "PRODUCT#QUALITY", "Opinion": "best", "VA": "7.25#6.00"}
    return {**q, **over}


def test_validate_record_accepts_good_and_flags_bad():
    rec = {"ID": "x", "Text": "FOREO Luna 4 is the best", "Quadruplet": [quad()]}
    assert fmt.validate_record(rec) == []
    bad = {
        **rec,
        "Quadruplet": [
            quad(Aspect="Luna 5"),
            quad(VA="7.3#6"),
            quad(Category="FOOD#QUALITY"),
            quad(VA="9.50#5.00", Opinion="NULL"),
        ],
    }
    errs = " | ".join(fmt.validate_record(bad))
    assert "not a span" in errs
    assert "two decimals" in errs
    assert "unknown Category" in errs
    assert "outside [1, 9]" in errs


def test_to_official_matches_dimabsa_shapes():
    rec = {
        "ID": "x",
        "Text": "FOREO Luna 4 is the best",
        "Quadruplet": [quad(Brand="foreo"), quad(Aspect="NULL", Category="BRAND#GENERAL")],
    }
    assert fmt.to_official(rec, 1) == {
        "ID": "x",
        "Text": rec["Text"],
        "Aspect_VA": [{"Aspect": "Luna 4", "VA": "7.25#6.00"}],
    }
    assert set(fmt.to_official(rec, 2)["Triplet"][0]) == {"Aspect", "Opinion", "VA"}
    assert set(fmt.to_official(rec, 3)["Quadruplet"][0]) == {
        "Aspect",
        "Category",
        "Opinion",
        "VA",
    }


@pytest.mark.skipif(not SILVER.exists(), reason="silver annotation file not built")
def test_silver_file_schema():
    records = fmt.read_jsonl(SILVER)
    assert 100 <= len(records) <= 200
    assert len({r["ID"] for r in records}) == len(records)
    for r in records:
        assert re.fullmatch(r"foreo_v1_\d{3}", r["ID"])
        assert fmt.validate_record(r) == [], r["ID"]
        assert r["Status"] == "silver"
        assert r["Confidence"] in fmt.CONFIDENCE_VALUES
        assert r["Rationale"]
        for q in r["Quadruplet"]:
            assert q["Brand"] in fmt.BRAND_VALUES
            assert q["Confidence"] in fmt.CONFIDENCE_VALUES
