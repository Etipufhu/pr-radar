"""Static web dashboard data: one JSON file the page in `web/` renders.

`pr-radar export-web` writes `web/data.json` (for a web server or GitHub Pages) and
`web/data.js` (the same payload as a script, so `web/index.html` also works when
opened straight from disk, where browsers block `fetch` of local files).
"""

from __future__ import annotations

import json
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any

import pandas as pd

from . import analytics as an
from .config import Settings
from .report import default_window

WINDOWS = (7, 28)
SCHEMA_VERSION = 1


def _records(df: pd.DataFrame) -> list[dict[str, Any]]:
    """JSON-safe rows: NaN/None -> null, timestamps -> ISO strings, arrays -> lists."""
    if df.empty:
        return []
    return json.loads(df.to_json(orient="records", date_format="iso", date_unit="s"))


def _iso(value: datetime) -> str:
    return value.strftime("%Y-%m-%d")


def window_payload(con, settings: Settings, window: an.Window) -> dict[str, Any]:
    primary = settings.primary_brand
    names = settings.brand_names
    sov = an.share_of_voice(con, window)
    comparison = an.period_comparison(con, window)
    baseline = an.has_baseline(con, window, settings.lookback_days)

    p_cmp = comparison[comparison["brand"] == primary]
    p_sov = sov[sov["brand"] == primary]
    rank = int(p_cmp.index[0]) + 1 if not p_cmp.empty else None
    kpis = {
        "mentions": int(p_cmp["mentions"].iloc[0]) if not p_cmp.empty else 0,
        "share": float(p_cmp["share"].iloc[0]) if not p_cmp.empty else 0.0,
        "share_change_pts": float(p_cmp["share_change_pts"].iloc[0])
        if baseline and not p_cmp.empty
        else None,
        "outlets": int(p_sov["outlets"].iloc[0]) if not p_sov.empty else 0,
        "markets": int(p_sov["markets"].iloc[0]) if not p_sov.empty else 0,
        "stories": int(p_sov["stories"].iloc[0]) if not p_sov.empty else 0,
        "rank": rank,
        "brands": len(comparison),
        "total_mentions": int(sov["mentions"].sum()) if not sov.empty else 0,
    }
    return {
        "days": (window.end - window.start).days,
        "start": _iso(window.start),
        "end": _iso(window.end - timedelta(days=1)),  # last day included
        "baseline": baseline,
        "kpis": kpis,
        "insights": an.insights(con, window, primary, names, settings.lookback_days),
        "share_of_voice": _records(sov),
        "comparison": _records(comparison),
        "weekly_trend": _records(an.weekly_trend(con, window)),
        "market_share": _records(an.market_share(con, window)),
        "market_gaps": _records(an.market_gaps(con, window, primary).head(12)),
        "outlet_gaps": _records(an.outlet_gaps(con, window, primary, limit=50)),
        "topic_gaps": _records(an.topic_gaps(con, window, primary)),
        "top_stories": _records(an.top_stories(con, window, limit=10)),
    }


def build_payload(
    con,
    settings: Settings,
    end: datetime | None = None,
    windows: tuple[int, ...] = WINDOWS,
    aspect_sentiment: list[dict[str, Any]] | None = None,
) -> dict[str, Any]:
    """Everything the web dashboard shows, keyed by window length in days.

    `aspect_sentiment` is reserved for DimABSA results; the page shows a
    "coming soon" card while it is empty.
    """
    return {
        "schema": SCHEMA_VERSION,
        "generated_at": datetime.now(UTC).strftime("%Y-%m-%dT%H:%M:%SZ"),
        "primary": settings.primary_brand,
        "brands": settings.brand_names,
        "default_window": str(windows[0]),
        "windows": {
            str(days): window_payload(con, settings, default_window(days, end)) for days in windows
        },
        "aspect_sentiment": aspect_sentiment or [],
    }


def write_web_data(
    con, settings: Settings, out_dir: str | Path, end: datetime | None = None
) -> Path:
    out_dir = Path(out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)
    sentiment = an.brand_sentiment(con, default_window(max(WINDOWS), end))
    aspect_sentiment = [
        {
            "brand": r["brand"],
            "aspect": "headline tone",
            "valence": round(float(r["valence"]), 2),
            "arousal": round(float(r["arousal"]), 2),
            "mentions": int(r["scored"]),
        }
        for r in sentiment.to_dict("records")
    ]
    payload = build_payload(con, settings, end, aspect_sentiment=aspect_sentiment)
    text = json.dumps(payload, ensure_ascii=False, indent=1)
    target = out_dir / "data.json"
    target.write_text(text, encoding="utf-8")
    (out_dir / "data.js").write_text(f"window.PR_RADAR_DATA = {text};\n", encoding="utf-8")
    return target
