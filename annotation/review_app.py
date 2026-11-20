"""Review tool for the FOREO-domain DimABSA set: check and correct the LLM pre-labels.

    .venv/Scripts/python -m streamlit run annotation/review_app.py

One headline at a time, low-confidence items first. Every button press rewrites
data/annotations/foreo_domain_v1.reviewed.jsonl (atomically), so closing the browser
loses nothing. The silver file is never modified.
"""

from __future__ import annotations

import sys
from datetime import UTC, datetime
from pathlib import Path

import streamlit as st
import streamlit.components.v1 as components

sys.path.insert(0, str(Path(__file__).resolve().parent))
from dimabsa_format import (  # noqa: E402
    BRAND_VALUES,
    CATEGORIES,
    parse_va,
    read_jsonl,
    va_string,
    validate_record,
    write_jsonl,
)

ROOT = Path(__file__).resolve().parents[1]
SILVER = ROOT / "data" / "annotations" / "foreo_domain_v1.silver.jsonl"
REVIEWED = ROOT / "data" / "annotations" / "foreo_domain_v1.reviewed.jsonl"
# Optional override for trying the tool without touching the real file:
#   streamlit run annotation/review_app.py -- --reviewed some/other.jsonl
if "--reviewed" in sys.argv:
    REVIEWED = Path(sys.argv[sys.argv.index("--reviewed") + 1]).resolve()
BRANDS = sorted(BRAND_VALUES)
CATS = sorted(CATEGORIES)


def md(text: str) -> str:
    """Escape characters Streamlit markdown would interpret ($…$ is LaTeX)."""
    return text.replace("$", "\\$").replace("*", "\\*").replace("_", "\\_")


def review_order(records: list[dict]) -> list[dict]:
    """Low-confidence first, then by ID."""
    return sorted(records, key=lambda r: (r.get("Confidence") != "low", r["ID"]))


def load() -> tuple[list[dict], dict[str, dict]]:
    silver = review_order(read_jsonl(SILVER))
    reviewed = {r["ID"]: r for r in read_jsonl(REVIEWED)} if REVIEWED.exists() else {}
    return silver, reviewed


def save(reviewed: dict[str, dict], silver: list[dict]) -> None:
    order = {r["ID"]: i for i, r in enumerate(sorted(silver, key=lambda r: r["ID"]))}
    write_jsonl(sorted(reviewed.values(), key=lambda r: order.get(r["ID"], 1 << 30)), REVIEWED)


def make_reviewed(item: dict, quads: list[dict], status: str, note: str) -> dict:
    rec = {k: v for k, v in item.items() if k not in ("Quadruplet", "Status")}
    rec["Quadruplet"] = quads
    rec["Status"] = status
    rec["SilverQuadruplet"] = item["Quadruplet"]  # kept for LLM-vs-human agreement
    rec["Reviewer"] = "human"
    rec["ReviewNote"] = note
    rec["ReviewedAt"] = datetime.now(UTC).strftime("%Y-%m-%dT%H:%M:%SZ")
    return rec


def same_labels(a: list[dict], b: list[dict]) -> bool:
    keys = ("Aspect", "Category", "Opinion", "VA", "Brand")
    return [{k: q.get(k) for k in keys} for q in a] == [{k: q.get(k) for k in keys} for q in b]


def quad_editor(rid: str, i: int, q: dict) -> dict | None:
    """Widgets for one aspect; returns the edited quadruplet, or None if removed."""
    v0, a0 = parse_va(q["VA"])
    with st.container(border=True):
        top = st.columns([3, 3, 1])
        aspect = top[0].text_input("Aspect (verbatim / aynen)", q["Aspect"], key=f"{rid}_{i}_asp")
        opinion = top[1].text_input("Opinion (verbatim or NULL)", q["Opinion"], key=f"{rid}_{i}_op")
        removed = top[2].checkbox("Remove", key=f"{rid}_{i}_del")
        mid = st.columns(2)
        cat = mid[0].selectbox(
            "Category", CATS, index=CATS.index(q["Category"]), key=f"{rid}_{i}_cat"
        )
        brand = mid[1].selectbox(
            "Brand", BRANDS, index=BRANDS.index(q.get("Brand", "generic")), key=f"{rid}_{i}_br"
        )
        sl = st.columns(2)
        v = sl[0].slider(
            "Valence — 1 negative · 5 neutral · 9 positive", 1.0, 9.0, v0, 0.25, key=f"{rid}_{i}_v"
        )
        a = sl[1].slider(
            "Arousal — 1 calm/factual · 9 intense", 1.0, 9.0, a0, 0.25, key=f"{rid}_{i}_a"
        )
        flags = []
        if q.get("Confidence") == "low":
            flags.append("⚠️ low confidence")
        if q.get("BrandInText") is False:
            flags.append("brand not in headline (from article)")
        if flags:
            st.caption(" · ".join(flags))
    if removed:
        return None
    return {
        **q,
        "Aspect": aspect.strip() or "NULL",
        "Opinion": opinion.strip() or "NULL",
        "Category": cat,
        "Brand": brand,
        "VA": va_string(v, a),
    }


def main() -> None:
    st.set_page_config(page_title="DimABSA review", page_icon="📝", layout="centered")
    silver, reviewed = load()

    with st.sidebar:
        st.header("FOREO-domain DimABSA v1")
        done = len(reviewed)
        st.progress(done / len(silver), text=f"{done} / {len(silver)} reviewed")
        counts = {
            s: sum(r["Status"] == s for r in reviewed.values())
            for s in ("accepted", "fixed", "skipped")
        }
        st.write(
            f"✓ {counts['accepted']} accepted · ✎ {counts['fixed']} fixed · ⏭ {counts['skipped']} skipped"
        )
        show_all = st.toggle("Revisit reviewed items", value=False)
        st.markdown(
            "**V** 1 very negative · 5 neutral/factual · 9 very positive  \n"
            "**A** 1 calm/factual · 9 intense/excited  \n"
            "Your ordinary judgement is what's wanted. See `annotation/GUIDELINES.md`."
        )
        st.caption(f"Autosaves to `{REVIEWED.as_posix()}`")

    queue = [r for r in silver if show_all or r["ID"] not in reviewed]
    if not queue:
        st.success("All items reviewed — thank you! Hepsi bitti, teşekkürler.")
        st.balloons()
        return
    pos = st.session_state.setdefault("pos", 0) % len(queue)
    item = queue[pos]
    rid = item["ID"]
    current = reviewed.get(rid, item)  # revisit: start from the saved version

    meta = item.get("Meta", {})
    st.caption(
        f"{rid} · {item.get('Language', '?')} · {meta.get('source_domain', '')} · "
        f"{(meta.get('published_at') or '')[:10]} · item {pos + 1} of {len(queue)} in queue"
        + (" · ⚠️ low confidence" if item.get("Confidence") == "low" else "")
        + (f" · already **{reviewed[rid]['Status']}**" if rid in reviewed else "")
    )
    # Streamlit keeps the scroll position across reruns; jump back to the headline
    # whenever a new item is shown (the script text changes only with the item ID).
    components.html(
        f"<script>// {rid}\n"
        "const d = window.parent.document;"
        "for (const s of ['[data-testid=stMain]', '[data-testid=stAppViewContainer]'])"
        "{ const e = d.querySelector(s); if (e) e.scrollTo(0, 0); }"
        "window.parent.scrollTo(0, 0);</script>",
        height=0,
    )
    st.markdown(f"### {md(item['Text'])}")
    if meta.get("url"):
        st.markdown(f"[open article]({meta['url']}) · tags: {', '.join(meta.get('brands', []))}")
    st.info(f"**Claude's rationale:** {md(item.get('Rationale', ''))}")

    edited = [quad_editor(rid, i, q) for i, q in enumerate(current["Quadruplet"])]
    n_extra = st.session_state.get(f"{rid}_extra", 0)
    for j in range(n_extra):
        new = {
            "Aspect": "NULL",
            "Category": "PRODUCT#GENERAL",
            "Opinion": "NULL",
            "VA": "5.00#5.00",
            "Brand": "generic",
            "Confidence": "high",
        }
        edited.append(quad_editor(rid, len(current["Quadruplet"]) + j, new))
    quads = [q for q in edited if q is not None]
    if st.button("＋ add aspect"):
        st.session_state[f"{rid}_extra"] = n_extra + 1
        st.rerun()

    note = st.text_input("Note (optional)", current.get("ReviewNote", ""), key=f"{rid}_note")
    b = st.columns(4)
    accept = b[0].button(
        "✓ Accept",
        type="primary",
        width="stretch",
        help="Claude's labels are fine as proposed",
    )
    fix = b[1].button("✎ Save fix", width="stretch", help="Save your edits")
    skip = b[2].button("⏭ Skip", width="stretch", help="Nothing worth rating / unclear")
    back = b[3].button("← Back", width="stretch")

    def advance() -> None:
        # The saved item leaves the queue, so the same index now points at the next one.
        st.session_state["pos"] = pos if not show_all else pos + 1
        st.rerun()

    if back:
        st.session_state["pos"] = max(pos - 1, 0)
        st.rerun()
    if accept:
        reviewed[rid] = make_reviewed(item, item["Quadruplet"], "accepted", note)
        save(reviewed, silver)
        advance()
    if fix:
        status = "accepted" if same_labels(quads, item["Quadruplet"]) else "fixed"
        rec = make_reviewed(item, quads, status, note)
        errs = validate_record(rec)
        if errs:
            st.error("Can't save yet: " + "; ".join(errs))
        else:
            reviewed[rid] = rec
            save(reviewed, silver)
            advance()
    if skip:
        reviewed[rid] = make_reviewed(item, item["Quadruplet"], "skipped", note)
        save(reviewed, silver)
        advance()


if __name__ == "__main__":
    main()
