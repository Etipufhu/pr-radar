"""Share of voice, market/outlet/topic gap analysis and automatic insights.

All windows are half-open [start, end) in naive UTC. "Mentions" are articles that
name a brand (one article naming two brands counts once for each); "stories" are
distinct clusters of syndicated copies.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta

import duckdb
import pandas as pd

_MENTIONS = """
WITH m AS (
    SELECT id, title, url, source_name, source_domain, country, language,
           published_at, topics, cluster_id, headline_brands, unnest(brands) AS brand
    FROM articles
    WHERE published_at >= $start AND published_at < $end
)
"""


def _q(con: duckdb.DuckDBPyConnection, sql: str, **params) -> pd.DataFrame:
    return con.execute(sql, params).df()


@dataclass(frozen=True)
class Window:
    start: datetime
    end: datetime

    @property
    def previous(self) -> Window:
        return Window(self.start - (self.end - self.start), self.start)


def share_of_voice(con, w: Window) -> pd.DataFrame:
    return _q(
        con,
        _MENTIONS
        + """
        SELECT brand,
               count(*) AS mentions,
               count(DISTINCT cluster_id) AS stories,
               count(DISTINCT source_domain) AS outlets,
               count(DISTINCT country) AS markets,
               count(*) / sum(count(*)) OVER () AS share,
               -- Headline mentions: the brand is named in the title, not only in the body.
               count(*) FILTER (WHERE list_contains(headline_brands, brand)) AS headline_mentions,
               coalesce(
                   count(*) FILTER (WHERE list_contains(headline_brands, brand))
                   / nullif(sum(count(*) FILTER (WHERE list_contains(headline_brands, brand))) OVER (), 0),
                   0
               ) AS headline_share
        FROM m GROUP BY brand ORDER BY mentions DESC, brand
        """,
        start=w.start,
        end=w.end,
    )


def period_comparison(con, w: Window) -> pd.DataFrame:
    cur = share_of_voice(con, w)[["brand", "mentions", "share"]]
    prev = share_of_voice(con, w.previous)[["brand", "mentions", "share"]]
    df = cur.merge(prev, on="brand", how="outer", suffixes=("", "_prev")).fillna(0)
    df["mentions"] = df["mentions"].astype(int)
    df["mentions_prev"] = df["mentions_prev"].astype(int)
    df["share_change_pts"] = (df["share"] - df["share_prev"]) * 100
    df["mentions_change_pct"] = df.apply(
        lambda r: (
            (r.mentions - r.mentions_prev) / r.mentions_prev * 100 if r.mentions_prev else None
        ),
        axis=1,
    )
    return df.sort_values("mentions", ascending=False).reset_index(drop=True)


def weekly_trend(con, w: Window) -> pd.DataFrame:
    return _q(
        con,
        _MENTIONS
        + """
        , g AS (
            SELECT date_trunc('week', published_at) AS week, brand, count(*) AS mentions
            FROM m GROUP BY 1, 2
        )
        SELECT week, brand, mentions, mentions / sum(mentions) OVER (PARTITION BY week) AS share
        FROM g ORDER BY week, brand
        """,
        start=w.start,
        end=w.end,
    )


def market_share(con, w: Window) -> pd.DataFrame:
    return _q(
        con,
        _MENTIONS
        + """
        , g AS (
            SELECT coalesce(country, '??') AS country, brand, count(*) AS mentions
            FROM m GROUP BY 1, 2
        )
        SELECT country, brand, mentions,
               mentions / sum(mentions) OVER (PARTITION BY country) AS share
        FROM g ORDER BY country, mentions DESC, brand
        """,
        start=w.start,
        end=w.end,
    )


def market_gaps(con, w: Window, primary: str, min_mentions: int = 5) -> pd.DataFrame:
    """Markets where a competitor out-shouts the primary brand, biggest gap first."""
    df = market_share(con, w)
    if df.empty:
        return pd.DataFrame(
            columns=["country", "total", "primary_share", "leader", "leader_share", "gap_pts"]
        )
    rows = []
    for country, g in df.groupby("country"):
        total = int(g["mentions"].sum())
        if total < min_mentions or country == "??":
            continue
        primary_share = float(g.loc[g["brand"] == primary, "share"].sum())
        competitors = g[g["brand"] != primary]
        if competitors.empty:
            continue
        leader = competitors.sort_values("mentions", ascending=False).iloc[0]
        gap = (float(leader["share"]) - primary_share) * 100
        if gap > 0:
            rows.append(
                (country, total, primary_share, leader["brand"], float(leader["share"]), gap)
            )
    out = pd.DataFrame(
        rows, columns=["country", "total", "primary_share", "leader", "leader_share", "gap_pts"]
    )
    return out.sort_values(["gap_pts", "total"], ascending=False).reset_index(drop=True)


def outlet_gaps(con, w: Window, primary: str, limit: int = 20) -> pd.DataFrame:
    """Outlets that covered competitors in the window but not the primary brand.

    primary_all_time > 0 means the outlet covered us before: a warm contact to re-pitch.
    """
    return _q(
        con,
        _MENTIONS
        + """
        , per_outlet AS (
            SELECT source_domain AS outlet,
                   any_value(source_name) AS outlet_name,
                   count(DISTINCT id) FILTER (WHERE brand <> $primary) AS competitor_articles,
                   list_sort(list_distinct(list(brand) FILTER (WHERE brand <> $primary))) AS competitors,
                   count(DISTINCT id) FILTER (WHERE brand = $primary) AS primary_articles
            FROM m WHERE coalesce(source_domain, '') <> ''
            GROUP BY source_domain
        ), history AS (
            SELECT source_domain AS outlet, count(*) AS primary_all_time
            FROM articles WHERE list_contains(brands, $primary) GROUP BY 1
        )
        SELECT p.outlet, p.outlet_name, p.competitor_articles, p.competitors,
               coalesce(h.primary_all_time, 0) AS primary_all_time
        FROM per_outlet p LEFT JOIN history h USING (outlet)
        WHERE p.primary_articles = 0 AND p.competitor_articles > 0
        ORDER BY p.competitor_articles DESC, len(p.competitors) DESC, p.outlet
        LIMIT $limit
        """,
        start=w.start,
        end=w.end,
        primary=primary,
        limit=limit,
    )


# Topics that are alerts, not stories a brand would want to own.
NOT_NARRATIVES = {"risk"}


def topic_gaps(con, w: Window, primary: str) -> pd.DataFrame:
    """Share of each brand group's coverage that falls into each topic.

    gap_pts > 0: the topic is a bigger part of competitors' coverage than of ours,
    i.e. a narrative competitors own that we are missing.
    """
    counts = _q(
        con,
        _MENTIONS
        + """
        , t AS (SELECT id, brand, unnest(topics) AS topic FROM m)
        SELECT topic, brand, count(DISTINCT id) AS articles FROM t GROUP BY ALL
        """,
        start=w.start,
        end=w.end,
    )
    totals = _q(
        con,
        _MENTIONS
        + """
        SELECT count(DISTINCT id) FILTER (WHERE brand = $primary) AS primary_total,
               count(DISTINCT id) FILTER (WHERE brand <> $primary) AS competitor_total
        FROM m
        """,
        start=w.start,
        end=w.end,
        primary=primary,
    ).iloc[0]
    cols = [
        "topic",
        "primary_articles",
        "primary_share",
        "competitor_articles",
        "competitor_share",
        "gap_pts",
        "top_competitor",
    ]
    if counts.empty:
        return pd.DataFrame(columns=cols)

    competitor_ids = _q(
        con,
        _MENTIONS
        + """
        , t AS (SELECT id, brand, unnest(topics) AS topic FROM m)
        SELECT topic, count(DISTINCT id) AS articles FROM t WHERE brand <> $primary GROUP BY topic
        """,
        start=w.start,
        end=w.end,
        primary=primary,
    ).set_index("topic")["articles"]

    rows = []
    p_total = int(totals["primary_total"] or 0)
    c_total = int(totals["competitor_total"] or 0)
    for topic, g in counts.groupby("topic"):
        if topic in NOT_NARRATIVES:
            continue
        p = int(g.loc[g["brand"] == primary, "articles"].sum())
        c = int(competitor_ids.get(topic, 0))
        comp = g[g["brand"] != primary].sort_values("articles", ascending=False)
        top = comp.iloc[0]["brand"] if not comp.empty else None
        p_share = p / p_total if p_total else 0.0
        c_share = c / c_total if c_total else 0.0
        rows.append((topic, p, p_share, c, c_share, (c_share - p_share) * 100, top))
    out = pd.DataFrame(rows, columns=cols)
    return out.sort_values("gap_pts", ascending=False).reset_index(drop=True)


def top_stories(con, w: Window, limit: int = 10) -> pd.DataFrame:
    return _q(
        con,
        _MENTIONS
        + """
        SELECT cluster_id,
               arg_min(title, published_at) AS title,
               arg_min(url, published_at) AS url,
               list_sort(list_distinct(list(brand))) AS brands,
               count(DISTINCT source_domain) AS outlets,
               list_sort(list_distinct(list(country) FILTER (WHERE country IS NOT NULL))) AS markets,
               min(published_at) AS first_seen
        FROM m GROUP BY cluster_id
        ORDER BY outlets DESC, first_seen DESC
        LIMIT $limit
        """,
        start=w.start,
        end=w.end,
        limit=limit,
    )


def latest_articles(con, w: Window, limit: int = 200) -> pd.DataFrame:
    return _q(
        con,
        """
        SELECT published_at, title, source_name, source_domain, country, language,
               brands, topics, url
        FROM articles
        WHERE published_at >= $start AND published_at < $end
        ORDER BY published_at DESC
        LIMIT $limit
        """,
        start=w.start,
        end=w.end,
        limit=limit,
    )


def has_baseline(con, w: Window, lookback_days: int) -> bool:
    """True when the previous window was actually collected.

    Each run only sees the last `lookback_days` days, so data starts at the first
    run minus the lookback. Comparing against an earlier window would report fake
    jumps such as "+37 pts" on the very first run.
    """
    first_run = con.execute("SELECT min(first_seen_at) FROM articles").fetchone()[0]
    if first_run is None:
        return False
    return first_run - timedelta(days=lookback_days) <= w.previous.start


def insights(
    con, w: Window, primary: str, names: dict[str, str], lookback_days: int = 7
) -> list[str]:
    """Plain-language takeaways for the top of the weekly report."""

    def name(brand_id: str | None) -> str:
        return names.get(brand_id or "", brand_id or "?")

    out: list[str] = []
    comp = period_comparison(con, w)
    if comp.empty:
        return ["No coverage found in this period."]
    baseline = has_baseline(con, w, lookback_days)

    row = comp[comp["brand"] == primary]
    if not row.empty:
        r = row.iloc[0]
        rank = int(comp.index[comp["brand"] == primary][0]) + 1
        change = (
            f"{r.share_change_pts:+.1f} pts vs previous period"
            if baseline
            else "first tracked period, no comparison yet"
        )
        out.append(
            f"{name(primary)} share of voice is {r.share:.0%} ({change}), "
            f"ranked #{rank} of {len(comp)} brands with {r.mentions} mentions."
        )
    else:
        out.append(f"{name(primary)} received no coverage in this period.")

    leader = comp.iloc[0]
    if leader["brand"] != primary:
        out.append(f"{name(leader['brand'])} leads the conversation with {leader['share']:.0%}.")

    movers = comp[(comp["brand"] != primary) & (comp["share_change_pts"].abs() >= 5)]
    for _, m in movers.head(2 if baseline else 0).iterrows():
        verb = "gained" if m.share_change_pts > 0 else "lost"
        out.append(f"{name(m.brand)} {verb} {abs(m.share_change_pts):.1f} pts of share of voice.")

    mg = market_gaps(con, w, primary)
    if not mg.empty:
        g = mg.iloc[0]
        out.append(
            f"Biggest market gap: {g.country}, where {name(g.leader)} holds {g.leader_share:.0%} "
            f"vs {name(primary)} {g.primary_share:.0%}."
        )

    og = outlet_gaps(con, w, primary, limit=50)
    if not og.empty:
        warm = int((og["primary_all_time"] > 0).sum())
        top = og.iloc[0]
        line = (
            f"{len(og)} outlets covered competitors but not {name(primary)}; "
            f"top: {top.outlet} ({top.competitor_articles} competitor articles)."
        )
        if warm:
            line += f" {warm} of them have covered {name(primary)} before (warm re-pitch targets)."
        out.append(line)

    tg = topic_gaps(con, w, primary)
    tg = tg[(tg["gap_pts"] >= 5) & (tg["competitor_articles"] >= 3)]
    if not tg.empty:
        t = tg.iloc[0]
        out.append(
            f"Narrative gap: '{t.topic}' is {t.competitor_share:.0%} of competitor coverage "
            f"but {t.primary_share:.0%} of {name(primary)}'s (led by {name(t.top_competitor)})."
        )
    out.extend(risk_insights(con, w, names))
    out.extend(sentiment_insights(con, w, primary, names))
    return out


# -- aspect sentiment (DimABSA) ------------------------------------------------------

NEGATIVE_BELOW, POSITIVE_ABOVE = 4.5, 5.5  # valence; 5 is neutral on the 1-9 scale
HEATED_VALENCE, HEATED_AROUSAL = 4.0, 6.0  # negative AND intense: worth a PR look


def latest_sentiment_model(con) -> str | None:
    row = con.execute(
        "SELECT model FROM aspect_sentiment ORDER BY scored_at DESC LIMIT 1"
    ).fetchone()
    return row[0] if row else None


def brand_sentiment(con, w: Window, model: str | None = None) -> pd.DataFrame:
    """Average headline valence/arousal per brand, plus positive/negative shares."""
    model = model or latest_sentiment_model(con)
    cols = ["brand", "scored", "valence", "arousal", "positive_share", "negative_share", "heated"]
    if model is None:
        return pd.DataFrame(columns=cols)
    return _q(
        con,
        """
        SELECT s.brand,
               count(*) AS scored,
               avg(s.valence) AS valence,
               avg(s.arousal) AS arousal,
               count(*) FILTER (WHERE s.valence > $pos) / count(*) AS positive_share,
               count(*) FILTER (WHERE s.valence < $neg) / count(*) AS negative_share,
               count(*) FILTER (WHERE s.valence <= $hv AND s.arousal >= $ha) AS heated
        FROM aspect_sentiment s JOIN articles a ON a.id = s.article_id
        WHERE s.model = $model AND a.published_at >= $start AND a.published_at < $end
        GROUP BY s.brand ORDER BY valence DESC
        """,
        model=model,
        start=w.start,
        end=w.end,
        pos=POSITIVE_ABOVE,
        neg=NEGATIVE_BELOW,
        hv=HEATED_VALENCE,
        ha=HEATED_AROUSAL,
    )


def scored_headlines(con, w: Window, model: str | None = None, limit: int = 200) -> pd.DataFrame:
    """Scored brand mentions, most negative first."""
    model = model or latest_sentiment_model(con)
    cols = [
        "published_at",
        "brand",
        "aspect",
        "valence",
        "arousal",
        "title",
        "source_domain",
        "url",
    ]
    if model is None:
        return pd.DataFrame(columns=cols)
    return _q(
        con,
        """
        SELECT a.published_at, s.brand, s.aspect, s.valence, s.arousal,
               a.title, a.source_domain, a.url
        FROM aspect_sentiment s JOIN articles a ON a.id = s.article_id
        WHERE s.model = $model AND a.published_at >= $start AND a.published_at < $end
        ORDER BY s.valence ASC, s.arousal DESC
        LIMIT $limit
        """,
        model=model,
        start=w.start,
        end=w.end,
        limit=limit,
    )


def sentiment_insights(con, w: Window, primary: str, names: dict[str, str]) -> list[str]:
    bs = brand_sentiment(con, w)
    if bs.empty:
        return []
    out = []
    p = bs[bs["brand"] == primary]
    comp = bs[bs["brand"] != primary]
    if not p.empty:
        r = p.iloc[0]
        line = (
            f"{names.get(primary, primary)} headline tone: valence {r.valence:.1f}/9, "
            f"{r.positive_share:.0%} positive and {r.negative_share:.0%} negative "
            f"across {int(r.scored)} scored mentions"
        )
        if not comp.empty:
            avg = (comp["valence"] * comp["scored"]).sum() / comp["scored"].sum()
            line += f" (competitors average {avg:.1f})"
        out.append(line + ".")
    heated = scored_headlines(con, w, limit=50)
    heated = heated[(heated["valence"] <= HEATED_VALENCE) & (heated["arousal"] >= HEATED_AROUSAL)]
    if not heated.empty:
        h = heated.iloc[0]
        out.append(
            f"Watch: '{h.title}' ({h.source_domain}) reads negative and intense for "
            f"{names.get(h.brand, h.brand)} (valence {h.valence:.1f}, arousal {h.arousal:.1f})."
        )
    return out


def risk_headlines(con, w: Window, limit: int = 20) -> pd.DataFrame:
    """Headlines tagged with the 'risk' topic (recalls, lawsuits, injuries...)."""
    return _q(
        con,
        """
        SELECT published_at, title, source_domain, url, brands, headline_brands
        FROM articles
        WHERE published_at >= $start AND published_at < $end AND list_contains(topics, 'risk')
        ORDER BY published_at DESC
        LIMIT $limit
        """,
        start=w.start,
        end=w.end,
        limit=limit,
    )


def risk_insights(con, w: Window, names: dict[str, str]) -> list[str]:
    risks = risk_headlines(con, w)
    if risks.empty:
        return []
    first = risks.iloc[0]
    named = list(first["headline_brands"]) or list(first["brands"])
    who = ", ".join(names.get(b, b) for b in named)
    more = f" (+{len(risks) - 1} more)" if len(risks) > 1 else ""
    return [f"Risk signal for {who}: '{first.title}' ({first.source_domain}){more}."]
