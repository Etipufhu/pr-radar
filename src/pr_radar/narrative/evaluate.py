"""Measure how often the model writes a brief that passes the checks.

Real data gives only one week so far, so the evaluation also uses synthetic
weeks: random but consistent fact sets built from the configured brands.
"""

from __future__ import annotations

import json
import random
import re
from collections import Counter
from pathlib import Path
from typing import Any

from .facts import fact_sheet
from .writer import Generate, write_brief

OUTLETS = [
    "vogue.com",
    "allure.com",
    "elle.com",
    "popsugar.com",
    "wareable.com",
    "menshealth.com",
    "stern.de",
    "bild.de",
    "marieclaire.fr",
    "elle.it",
    "hurriyet.com.tr",
    "glamour.pl",
    "expressen.se",
    "shopping.yahoo.com",
    "independent.co.uk",
]
COUNTRIES = ["US", "GB", "AU", "DE", "FR", "ES", "IT", "PL", "TR", "SE", "JP", "BR"]
TOPICS = ["skin science", "gift guides", "deals pricing", "launch", "reviews", "business"]
RISK_TITLES = [
    "{b} recalls charger over overheating risk",
    "Class action lawsuit filed against {b}",
    "Users report burns from {b} device",
]
STORY_TITLES = [
    "{b} Black Friday deals: best offers",
    "{b} launches new device for at-home skincare",
    "The best beauty gifts of the year, including {b}",
]


def _split(total: int, parts: int, rng: random.Random) -> list[int]:
    cuts = sorted(rng.sample(range(1, total), parts - 1))
    return [b - a for a, b in zip([0, *cuts], [*cuts, total], strict=True)]


def synthetic_facts(primary: str, competitors: list[str], seed: int) -> dict[str, Any]:
    rng = random.Random(seed)
    names = [primary, *rng.sample(competitors, k=min(len(competitors), rng.randint(2, 5)))]
    total = rng.randint(len(names) + 5, 160)
    counts = sorted(_split(total, len(names), rng), reverse=True)
    rng.shuffle(names)
    baseline = rng.random() < 0.5
    brands = [
        {
            "brand": n,
            "primary": n == primary,
            "rank": i + 1,
            "mentions": c,
            "share_pct": round(c / total * 100),
            "headline_mentions": rng.randint(0, c),
            "change_pts": round(rng.uniform(-15, 15), 1) if baseline else None,
        }
        for i, (n, c) in enumerate(zip(names, counts, strict=True))
    ]
    others = [n for n in names if n != primary]
    markets = [
        {
            "country": c,
            "leader": rng.choice(others),
            "leader_pct": (lp := rng.randint(30, 100)),
            "primary_pct": rng.randint(0, lp - 10),
        }
        for c in rng.sample(COUNTRIES, k=rng.randint(0, 3))
    ]
    top = [
        {"outlet": o, "competitor_articles": rng.randint(1, 6), "warm": rng.random() < 0.3}
        for o in rng.sample(OUTLETS, k=rng.randint(0, 5))
    ]
    top.sort(key=lambda t: -t["competitor_articles"])
    topics = [
        {
            "topic": t,
            "competitor_pct": (cp := rng.randint(10, 40)),
            "primary_pct": rng.randint(0, cp - 5),
            "leader": rng.choice(others),
        }
        for t in rng.sample(TOPICS, k=rng.randint(0, 3))
    ]
    risks = []
    if rng.random() < 0.4:
        b = rng.choice(names)
        risks.append(
            {
                "title": rng.choice(RISK_TITLES).format(b=b),
                "outlet": rng.choice(OUTLETS),
                "brands": [b],
            }
        )
    tone = [
        {
            "brand": b["brand"],
            "valence": round(rng.uniform(4.0, 8.0), 1),
            "scored": rng.randint(1, b["mentions"]),
        }
        for b in brands
        if rng.random() < 0.6
    ]
    stories = [
        {"title": rng.choice(STORY_TITLES).format(b=b), "outlets": rng.randint(2, 6), "brands": [b]}
        for b in rng.sample(names, k=rng.randint(0, 2))
    ]
    return {
        "primary": primary,
        "start": "2026-11-14",
        "end": "2026-11-20",
        "baseline": baseline,
        "total_mentions": total,
        "brands": brands,
        "market_gaps": markets,
        "outlet_gaps": {
            "count": len(top) + rng.randint(0, 30) if top else 0,
            "warm": sum(t["warm"] for t in top),
            "top": top,
        },
        "topic_gaps": topics,
        "risks": risks,
        "tone": tone,
        "stories": stories,
    }


def _kind(error: str) -> str:
    return re.split(r"[:(']", error, maxsplit=1)[0].strip()


def evaluate(
    fact_sets: list[dict[str, Any]],
    generate: Generate,
    model: str,
    tries: int = 4,
    few_shot: bool = True,
) -> dict[str, Any]:
    """First-attempt (greedy) quality, and the publish rate after revisions."""
    first_ok = published = 0
    words: list[int] = []
    error_kinds: Counter[str] = Counter()
    style_kinds: Counter[str] = Counter()
    samples = []
    from tqdm.auto import tqdm

    for f in tqdm(fact_sets, desc="brief-eval", unit="week"):
        brief = write_brief(f, generate, model, tries=tries, few_shot=few_shot)
        first = brief.drafts[0]
        first_ok += not first["errors"]
        published += brief.published
        words.append(len(first["text"].split()))
        error_kinds.update(_kind(e) for e in first["errors"])
        style_kinds.update(_kind(s) for s in first["style"])
        samples.append(
            {"sheet": fact_sheet(f), "published": brief.published, "drafts": brief.drafts}
        )
    n = len(fact_sets)
    return {
        "model": model,
        "weeks": n,
        "first_attempt_pass_rate": first_ok / n,
        "published_rate_with_retries": published / n,
        "tries": tries,
        "few_shot": few_shot,
        "mean_words": sum(words) / n,
        "error_counts": dict(error_kinds.most_common()),
        "style_counts": dict(style_kinds.most_common()),
        "samples": samples,
    }


def write_results(result: dict[str, Any], out_dir: str | Path) -> Path:
    out = Path(out_dir)
    out.mkdir(parents=True, exist_ok=True)
    slug = Path(result["model"]).name
    path = out / f"brief_eval_{slug}.json"
    path.write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding="utf-8")
    return path
