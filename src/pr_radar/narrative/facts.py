"""The weekly numbers as a short fact sheet.

The LLM sees only this sheet. Every number is pre-formatted here, so the
grounding check can require that each number in the brief appears in the sheet.
"""

from __future__ import annotations

from datetime import timedelta
from typing import Any

from .. import analytics as an
from ..config import Settings


def weekly_facts(con, settings: Settings, window: an.Window) -> dict[str, Any]:
    """Structured facts for one report window (plain Python types, JSON-safe)."""
    names = settings.brand_names
    primary = settings.primary_brand

    def name(brand_id: str | None) -> str:
        return names.get(brand_id or "", brand_id or "?")

    baseline = an.has_baseline(con, window, settings.lookback_days)
    comp = an.period_comparison(con, window)
    sov = an.share_of_voice(con, window).set_index("brand")
    brands = []
    for rank, r in enumerate(comp.itertuples(), start=1):
        if r.mentions == 0:
            continue
        brands.append(
            {
                "brand": name(r.brand),
                "primary": r.brand == primary,
                "rank": rank,
                "mentions": int(r.mentions),
                "share_pct": round(r.share * 100),
                "headline_mentions": int(sov.loc[r.brand, "headline_mentions"])
                if r.brand in sov.index
                else 0,
                "change_pts": round(float(r.share_change_pts), 1) if baseline else None,
            }
        )

    markets = [
        {
            "country": g.country,
            "leader": name(g.leader),
            "leader_pct": round(g.leader_share * 100),
            "primary_pct": round(g.primary_share * 100),
        }
        for g in an.market_gaps(con, window, primary).head(3).itertuples()
    ]
    og = an.outlet_gaps(con, window, primary, limit=50)
    outlets = {
        "count": len(og),
        "warm": int((og["primary_all_time"] > 0).sum()) if not og.empty else 0,
        "top": [
            {
                "outlet": o.outlet,
                "competitor_articles": int(o.competitor_articles),
                "warm": bool(o.primary_all_time > 0),
            }
            for o in og.head(5).itertuples()
        ],
    }
    tg = an.topic_gaps(con, window, primary)
    tg = tg[(tg["gap_pts"] >= 5) & (tg["competitor_articles"] >= 3)]
    topics = [
        {
            "topic": t.topic.replace("_", " "),
            "competitor_pct": round(t.competitor_share * 100),
            "primary_pct": round(t.primary_share * 100),
            "leader": name(t.top_competitor),
        }
        for t in tg.head(3).itertuples()
    ]
    risks = [
        {
            "title": r.title,
            "outlet": r.source_domain,
            "brands": [name(b) for b in (list(r.headline_brands) or list(r.brands))],
        }
        for r in an.risk_headlines(con, window, limit=3).itertuples()
    ]
    tone = [
        {
            "brand": name(s.brand),
            "valence": round(float(s.valence), 1),
            "scored": int(s.scored),
        }
        for s in an.brand_sentiment(con, window).itertuples()
    ]
    stories = [
        {"title": s.title, "outlets": int(s.outlets), "brands": [name(b) for b in s.brands]}
        for s in an.top_stories(con, window, limit=3).itertuples()
        if s.outlets > 1
    ]
    return {
        "primary": name(primary),
        "start": window.start.date().isoformat(),
        "end": (window.end - timedelta(seconds=1)).date().isoformat(),
        "baseline": baseline,
        "total_mentions": int(comp["mentions"].sum()) if not comp.empty else 0,
        "brands": brands,
        "market_gaps": markets,
        "outlet_gaps": outlets,
        "topic_gaps": topics,
        "risks": risks,
        "tone": tone,
        "stories": stories,
    }


def fact_sheet(f: dict[str, Any]) -> str:
    """Render the facts as short plain lines for the prompt."""
    p = f["primary"]
    lines = [
        f"Brand: {p}",
        f"Period: {f['start']} to {f['end']}",
        f"Total brand mentions in the period: {f['total_mentions']}",
    ]
    if not f["baseline"]:
        lines.append("Previous period: not collected, so there are no week-over-week changes.")
    lines.append("Share of voice (mentions, share, mentions in the headline):")
    for b in f["brands"]:
        change = "" if b["change_pts"] is None else f", {b['change_pts']:+.1f} pts vs last week"
        lines.append(
            f"- #{b['rank']} {b['brand']}: {b['mentions']} mention{'' if b['mentions'] == 1 else 's'}, "
            f"{b['share_pct']}%, "
            f"{b['headline_mentions']} in the headline{change}"
        )
    if f["market_gaps"]:
        lines.append(f"Markets where a competitor leads {p}:")
        for m in f["market_gaps"]:
            lines.append(
                f"- {m['country']}: {m['leader']} {m['leader_pct']}%, {p} {m['primary_pct']}%"
            )
    o = f["outlet_gaps"]
    if o["count"]:
        lines.append(
            f"Outlets that covered competitors but not {p}: {o['count']} "
            f"({o['warm']} of them covered {p} before)"
        )
        for t in o["top"]:
            warm = f", covered {p} before" if t["warm"] else ""
            lines.append(f"- {t['outlet']}: {t['competitor_articles']} competitor articles{warm}")
    if f["topic_gaps"]:
        lines.append("Topics where competitors get more coverage (share of each side's coverage):")
        for t in f["topic_gaps"]:
            lines.append(
                f"- {t['topic']}: competitors {t['competitor_pct']}%, {p} {t['primary_pct']}% "
                f"(led by {t['leader']})"
            )
    if f["risks"]:
        lines.append("Risk headlines (recall, lawsuit, injury keywords):")
        for r in f["risks"]:
            lines.append(f'- {", ".join(r["brands"])}: "{r["title"]}" ({r["outlet"]})')
    if f["tone"]:
        lines.append("Headline tone, valence on a 1-9 scale (5 is neutral):")
        for t in f["tone"]:
            lines.append(f"- {t['brand']}: {t['valence']:.1f} over {t['scored']} headlines")
    if f["stories"]:
        lines.append("Stories picked up by several outlets:")
        for s in f["stories"]:
            lines.append(f'- "{s["title"]}" ({s["outlets"]} outlets; {", ".join(s["brands"])})')
    return "\n".join(lines)
