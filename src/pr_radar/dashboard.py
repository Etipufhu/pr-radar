"""Interactive dashboard. Run with:  pr-radar dashboard"""

from __future__ import annotations

import os
from datetime import datetime, time, timedelta

import altair as alt
import pandas as pd
import streamlit as st

from pr_radar import analytics as an
from pr_radar.config import load_config
from pr_radar.storage import Store

DB_PATH = os.environ.get("PR_RADAR_DB", "data/pr_radar.duckdb")
CONFIG_PATH = os.environ.get("PR_RADAR_CONFIG", "config/brands.yaml")

st.set_page_config(page_title="PR Radar", page_icon="📡", layout="wide")


@st.cache_resource
def get_store() -> Store:
    return Store(DB_PATH, read_only=True)


settings = load_config(CONFIG_PATH)
names = settings.brand_names
primary = settings.primary_brand
con = get_store().con


def label(df: pd.DataFrame, col: str = "brand") -> pd.DataFrame:
    df = df.copy()
    df[col] = df[col].map(lambda b: names.get(b, b))
    return df


bounds = con.execute("SELECT min(published_at), max(published_at) FROM articles").fetchone()
if bounds[0] is None:
    st.title("PR Radar")
    st.info("The database is empty. Run `pr-radar collect` first.")
    st.stop()

with st.sidebar:
    st.header("PR Radar")
    st.caption(f"Primary brand: **{names[primary]}**")
    max_day = bounds[1].date()
    default_start = max(bounds[0].date(), max_day - timedelta(days=settings.lookback_days - 1))
    picked = st.date_input(
        "Period", (default_start, max_day), min_value=bounds[0].date(), max_value=max_day
    )
    start_day, end_day = (
        picked if isinstance(picked, tuple) and len(picked) == 2 else (picked, picked)
    )
    window = an.Window(
        datetime.combine(start_day, time()), datetime.combine(end_day, time()) + timedelta(days=1)
    )
    st.caption(
        f"Comparing with {window.previous.start:%d %b} – {window.start - timedelta(days=1):%d %b}"
    )

st.title(f"{names[primary]} · PR coverage")

comp = an.period_comparison(con, window)
sov = an.share_of_voice(con, window)
p = comp[comp["brand"] == primary]
p_sov = sov[sov["brand"] == primary]
baseline = an.has_baseline(con, window, settings.lookback_days)
show_delta = baseline and not p.empty
c1, c2, c3, c4 = st.columns(4)
c1.metric(
    "Mentions",
    int(p["mentions"].iloc[0]) if not p.empty else 0,
    int(p["mentions"].iloc[0] - p["mentions_prev"].iloc[0]) if show_delta else None,
)
c2.metric(
    "Share of voice",
    f"{p['share'].iloc[0]:.0%}" if not p.empty else "0%",
    f"{p['share_change_pts'].iloc[0]:+.1f} pts" if show_delta else None,
)
c3.metric("Outlets", int(p_sov["outlets"].iloc[0]) if not p_sov.empty else 0)
c4.metric("Markets", int(p_sov["markets"].iloc[0]) if not p_sov.empty else 0)

with st.container(border=True):
    st.subheader("Key takeaways")
    for line in an.insights(con, window, primary, names, settings.lookback_days):
        st.markdown(f"- {line}")

tab_sov, tab_markets, tab_gaps, tab_stories, tab_articles = st.tabs(
    ["Share of voice", "Markets", "Gaps", "Stories", "Articles"]
)

with tab_sov:
    left, right = st.columns([2, 3])
    with left:
        chart = (
            alt.Chart(label(sov))
            .mark_bar()
            .encode(
                x=alt.X("share:Q", axis=alt.Axis(format="%"), title="Share of voice"),
                y=alt.Y("brand:N", sort="-x", title=None),
                color=alt.condition(
                    alt.datum.brand == names[primary], alt.value("#d6336c"), alt.value("#9aa0ac")
                ),
                tooltip=[
                    "brand",
                    "mentions",
                    "stories",
                    "outlets",
                    alt.Tooltip("share:Q", format=".1%"),
                ],
            )
        )
        st.altair_chart(chart, use_container_width=True)
    with right:
        trend_window = an.Window(window.end - timedelta(weeks=12), window.end)
        trend = label(an.weekly_trend(con, trend_window))
        if not trend.empty:
            st.altair_chart(
                alt.Chart(trend)
                .mark_line(point=True)
                .encode(
                    x=alt.X("week:T", title="Week"),
                    y=alt.Y("share:Q", axis=alt.Axis(format="%"), title="Weekly share of voice"),
                    color=alt.Color("brand:N", title=None),
                    tooltip=["week:T", "brand", "mentions", alt.Tooltip("share:Q", format=".1%")],
                ),
                use_container_width=True,
            )
    st.dataframe(label(comp), hide_index=True, use_container_width=True)

with tab_markets:
    ms = label(an.market_share(con, window))
    if ms.empty:
        st.info("No data for this period.")
    else:
        st.altair_chart(
            alt.Chart(ms)
            .mark_rect()
            .encode(
                x=alt.X("brand:N", title=None),
                y=alt.Y("country:N", title="Market", sort="ascending"),
                color=alt.Color(
                    "share:Q", scale=alt.Scale(scheme="purples"), legend=alt.Legend(format="%")
                ),
                tooltip=["country", "brand", "mentions", alt.Tooltip("share:Q", format=".0%")],
            )
            .properties(height=max(240, 22 * ms["country"].nunique())),
            use_container_width=True,
        )

with tab_gaps:
    st.markdown("**Market gaps:** competitor leads the market")
    st.dataframe(
        label(an.market_gaps(con, window, primary), "leader"),
        hide_index=True,
        use_container_width=True,
    )
    st.markdown(
        "**Outlet gaps:** covered competitors, not us (`primary_all_time` > 0 = warm contact)"
    )
    st.dataframe(
        an.outlet_gaps(con, window, primary, limit=50), hide_index=True, use_container_width=True
    )
    st.markdown("**Narrative gaps by topic**")
    st.dataframe(
        label(an.topic_gaps(con, window, primary), "top_competitor"),
        hide_index=True,
        use_container_width=True,
    )

with tab_stories:
    st.dataframe(
        an.top_stories(con, window, limit=30),
        hide_index=True,
        use_container_width=True,
        column_config={"url": st.column_config.LinkColumn("link", display_text="open")},
    )

with tab_articles:
    arts = an.latest_articles(con, window, limit=1000)
    brand_filter = st.multiselect("Brands", list(names), format_func=names.get)
    if brand_filter:
        arts = arts[arts["brands"].apply(lambda bs: any(b in bs for b in brand_filter))]
    st.dataframe(
        arts,
        hide_index=True,
        use_container_width=True,
        column_config={"url": st.column_config.LinkColumn("link", display_text="open")},
    )
