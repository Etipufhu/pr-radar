"""Self-contained weekly HTML report (no JavaScript, inline SVG charts)."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from pathlib import Path

import pandas as pd
from jinja2 import Environment, FileSystemLoader, select_autoescape
from markupsafe import Markup, escape
from pandas.api.types import is_scalar

from . import analytics as an
from .config import Settings

TEMPLATES = Path(__file__).parent / "templates"


def default_window(days: int, end: datetime | None = None) -> an.Window:
    """Report window ending at the start of `end`'s day (UTC), so runs are reproducible."""
    end = end or datetime.now(UTC).replace(tzinfo=None)
    end = end.replace(hour=0, minute=0, second=0, microsecond=0) + timedelta(days=1)
    return an.Window(end - timedelta(days=days), end)


def bar_chart(
    items: list[tuple[str, float]], highlight: str | None = None, pct: bool = True
) -> Markup:
    """Horizontal bar chart as inline SVG."""
    if not items:
        return Markup('<p class="muted">No data.</p>')
    row_h, label_w, bar_w, value_w = 28, 150, 360, 64
    width = label_w + bar_w + value_w
    height = row_h * len(items)
    peak = max(v for _, v in items) or 1
    parts = [
        f'<svg class="chart" viewBox="0 0 {width} {height}" role="img" '
        f'aria-label="bar chart" xmlns="http://www.w3.org/2000/svg">'
    ]
    for i, (label, value) in enumerate(items):
        y = i * row_h
        w = max(2, value / peak * bar_w)
        cls = "bar hl" if label == highlight else "bar"
        text = f"{value:.0%}" if pct else f"{value:,.0f}"
        parts.append(
            f'<text class="lbl" x="{label_w - 10}" y="{y + 19}" text-anchor="end">{escape(label)}</text>'
            f'<rect class="{cls}" x="{label_w}" y="{y + 6}" width="{w:.1f}" height="16" rx="3"/>'
            f'<text class="val" x="{label_w + w + 8:.1f}" y="{y + 19}">{text}</text>'
        )
    parts.append("</svg>")
    return Markup("".join(parts))


def _records(df: pd.DataFrame) -> list[dict]:
    """DataFrame rows as dicts, with missing scalars as None (not NaN) for the template."""
    return [
        {k: None if is_scalar(v) and pd.isna(v) else v for k, v in row.items()}
        for row in df.to_dict("records")
    ]


def build_context(con, settings: Settings, window: an.Window) -> dict:
    names = settings.brand_names
    primary = settings.primary_brand
    sov = an.share_of_voice(con, window)
    comparison = an.period_comparison(con, window)
    primary_row = comparison[comparison["brand"] == primary]
    primary_stats = primary_row.iloc[0].to_dict() if not primary_row.empty else None
    primary_sov = sov[sov["brand"] == primary]
    baseline = an.has_baseline(con, window, settings.lookback_days)

    return {
        "generated_at": datetime.now(UTC).strftime("%Y-%m-%d %H:%M UTC"),
        "start": window.start,
        "end": window.end - timedelta(seconds=1),
        "primary": primary,
        "names": names,
        "baseline": baseline,
        "insights": an.insights(con, window, primary, names, settings.lookback_days),
        "kpis": {
            "mentions": int(primary_stats["mentions"]) if primary_stats else 0,
            "share": float(primary_stats["share"]) if primary_stats else 0.0,
            "share_change": float(primary_stats["share_change_pts"])
            if primary_stats and baseline
            else None,
            "outlets": int(primary_sov["outlets"].iloc[0]) if not primary_sov.empty else 0,
            "markets": int(primary_sov["markets"].iloc[0]) if not primary_sov.empty else 0,
            "total": int(sov["mentions"].sum()) if not sov.empty else 0,
        },
        "sov_chart": bar_chart(
            [(names.get(r.brand, r.brand), float(r.share)) for r in sov.itertuples()],
            highlight=names.get(primary),
        ),
        "comparison": comparison.pipe(_records),
        "market_gaps": an.market_gaps(con, window, primary).head(10).pipe(_records),
        "outlet_gaps": an.outlet_gaps(con, window, primary, limit=15).pipe(_records),
        "topic_gaps": an.topic_gaps(con, window, primary).pipe(_records),
        "stories": an.top_stories(con, window, limit=10).pipe(_records),
        "sentiment": an.brand_sentiment(con, window).pipe(_records),
        "headline": {r.brand: int(r.headline_mentions) for r in sov.itertuples()},
        "sentiment_headlines": an.scored_headlines(con, window, limit=8).pipe(_records),
    }


def render(context: dict) -> str:
    env = Environment(
        loader=FileSystemLoader(TEMPLATES),
        autoescape=select_autoescape(["html", "j2"]),
        trim_blocks=True,
        lstrip_blocks=True,
    )
    return env.get_template("weekly_report.html.j2").render(**context)


def write_report(con, settings: Settings, window: an.Window, out_dir: str | Path) -> Path:
    out_dir = Path(out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)
    year, week, _ = (window.end - timedelta(days=1)).isocalendar()
    target = out_dir / f"weekly-{year}-W{week:02d}.html"
    target.write_text(render(build_context(con, settings, window)), encoding="utf-8")
    return target
