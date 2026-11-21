"""Review tool for the FOREO-domain DimABSA set: check and correct the LLM pre-labels.

    .venv/Scripts/python -m streamlit run annotation/review_app.py
    .venv/Scripts/python -m streamlit run annotation/review_app.py -- --lang tr

One headline at a time, low-confidence items first. For each brand mention the
reviewer answers two questions (how positive, how intense) on a labelled scale;
the DimABSA fields (aspect, opinion, category) sit under "Advanced". Every
button press rewrites data/annotations/foreo_domain_v1.reviewed.jsonl
(atomically), so closing the browser loses nothing. The silver file is never
modified. The interface is in English or Turkish.
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
DEFAULT_LANG = sys.argv[sys.argv.index("--lang") + 1] if "--lang" in sys.argv else "en"
BRANDS = sorted(BRAND_VALUES)
CATS = sorted(CATEGORIES)
SCALE = [x / 4 for x in range(4, 37)]  # 1.00 .. 9.00 in quarter steps

BRAND_NAMES = {
    "foreo": "FOREO",
    "nuface": "NuFACE",
    "currentbody": "CurrentBody",
    "therabody": "Therabody",
    "pmd": "PMD Beauty",
    "solawave": "Solawave",
}

TEXT = {
    "en": {
        "title": "Headline label review",
        "what": "What am I doing here?",
        "explain": (
            "A language model read each news headline and rated how every brand in it is "
            "talked about. Your job is to check those ratings.\n\n"
            "1. Read the headline.\n"
            "2. For each brand or product mentioned, look at the two sliders: **how positive** and "
            "**how intense** the wording is. They start at the model's suggestion.\n"
            "3. If they look right, press **Suggestion is right**. If not, move the sliders "
            "and press **Save my changes**. If you can't tell, press **Not sure, skip**.\n\n"
            "Your everyday judgement is what counts; there are no wrong answers. "
            "Everything saves on each click, so you can stop any time."
        ),
        "progress": "{done} of {total} headlines checked",
        "counts": "✓ {accepted} right as suggested · ✎ {fixed} changed · ⏭ {skipped} skipped",
        "revisit": "Show headlines I already checked",
        "language": "Language / Dil",
        "saved_to": "Saved to",
        "all_done": "All headlines checked. Thank you!",
        "item": "Headline {n} of {total}",
        "open": "open article",
        "low": "the model was unsure about this one",
        "already": "already checked",
        "mention": "Mention {i}",
        "about": "about",
        "valence": "How positive is the headline about it?",
        "arousal": "How intense is the wording?",
        "reason": "Why the model suggested this (in English)",
        "advanced": "Advanced: aspect, opinion word, category",
        "aspect": "Aspect (exact words from the headline)",
        "opinion": "Opinion word (exact words, or NULL)",
        "category": "Category",
        "brand": "Brand",
        "remove": "This is not a real brand mention, remove it",
        "not_in_text": "the brand is not named in the headline itself",
        "add": "＋ add a mention the model missed",
        "note": "Note (optional)",
        "accept": "✓ Suggestion is right",
        "accept_help": "The model's ratings are fine as they are",
        "fix": "💾 Save my changes",
        "fix_help": "Save the sliders as you set them",
        "skip": "⏭ Not sure, skip",
        "skip_help": "Unclear, or nothing worth rating",
        "back": "← Back",
        "cant_save": "Can't save yet: ",
        "v_labels": [
            (2.0, "very negative"),
            (4.0, "negative"),
            (4.75, "slightly negative"),
            (5.25, "neutral, just news"),
            (6.0, "slightly positive"),
            (7.5, "positive"),
            (9.0, "very positive"),
        ],
        "a_labels": [
            (3.0, "calm, factual"),
            (5.0, "a little lively"),
            (6.5, "lively"),
            (7.75, "excited"),
            (9.0, "very intense"),
        ],
        "brand_other": "another brand",
        "brand_generic": "a product type",
        "brand_unknown": "unclear brand",
    },
    "tr": {
        "title": "Başlık etiketi kontrolü",
        "what": "Bu ekranda ne yapıyorum?",
        "explain": (
            "Bir dil modeli her haber başlığını okudu ve başlıktaki her markanın nasıl "
            "anıldığını puanladı. Senin işin bu puanları kontrol etmek.\n\n"
            "1. Başlığı oku.\n"
            "2. Anılan her marka ya da ürün için iki kaydırıcıya bak: başlık onun hakkında **ne kadar olumlu** ve "
            "**ne kadar yoğun/heyecanlı**. Kaydırıcılar modelin önerisiyle başlar.\n"
            "3. Doğru görünüyorsa **Öneri doğru**'ya bas. Değilse kaydırıcıları oynat ve "
            "**Değişikliklerimi kaydet**'e bas. Karar veremiyorsan **Emin değilim, atla**.\n\n"
            "Önemli olan senin günlük sezgin; yanlış cevap yok. Her tıklamada kaydedilir, "
            "istediğin an bırakıp sonra devam edebilirsin."
        ),
        "progress": "{total} başlığın {done} tanesi kontrol edildi",
        "counts": "✓ {accepted} öneri doğru · ✎ {fixed} düzeltildi · ⏭ {skipped} atlandı",
        "revisit": "Kontrol ettiğim başlıkları da göster",
        "language": "Language / Dil",
        "saved_to": "Kayıt dosyası",
        "all_done": "Bütün başlıklar kontrol edildi. Teşekkürler!",
        "item": "Başlık {n} / {total}",
        "open": "haberi aç",
        "low": "model bu başlıktan emin değildi",
        "already": "zaten kontrol edildi",
        "mention": "{i}. anılma",
        "about": "konu",
        "valence": "Başlık bunun hakkında ne kadar olumlu?",
        "arousal": "Dil ne kadar yoğun/heyecanlı?",
        "reason": "Modelin bu öneriyi neden yaptığı (İngilizce)",
        "advanced": "Gelişmiş: konu kelimesi, görüş kelimesi, kategori",
        "aspect": "Konu (başlıktaki kelimelerle aynen)",
        "opinion": "Görüş kelimesi (aynen, yoksa NULL)",
        "category": "Kategori",
        "brand": "Marka",
        "remove": "Bu gerçek bir marka anılması değil, kaldır",
        "not_in_text": "marka başlığın kendisinde geçmiyor",
        "add": "＋ modelin kaçırdığı bir anılma ekle",
        "note": "Not (isteğe bağlı)",
        "accept": "✓ Öneri doğru",
        "accept_help": "Modelin puanları olduğu gibi doğru",
        "fix": "💾 Değişikliklerimi kaydet",
        "fix_help": "Kaydırıcıları ayarladığın gibi kaydet",
        "skip": "⏭ Emin değilim, atla",
        "skip_help": "Belirsiz ya da puanlanacak bir şey yok",
        "back": "← Geri",
        "cant_save": "Henüz kaydedilemiyor: ",
        "v_labels": [
            (2.0, "çok olumsuz"),
            (4.0, "olumsuz"),
            (4.75, "biraz olumsuz"),
            (5.25, "nötr, sadece haber"),
            (6.0, "biraz olumlu"),
            (7.5, "olumlu"),
            (9.0, "çok olumlu"),
        ],
        "a_labels": [
            (3.0, "sakin, bilgi veren"),
            (5.0, "biraz canlı"),
            (6.5, "canlı"),
            (7.75, "heyecanlı"),
            (9.0, "çok yoğun"),
        ],
        "brand_other": "başka bir marka",
        "brand_generic": "bir ürün türü",
        "brand_unknown": "markası belirsiz",
    },
}


def t(key: str) -> object:
    return TEXT[st.session_state.get("lang", DEFAULT_LANG)][key]


def word_for(value: float, labels: list[tuple[float, str]]) -> str:
    return next(word for upper, word in labels if value <= upper)


def brand_label(brand: str) -> str:
    return BRAND_NAMES.get(brand) or str(t(f"brand_{brand}"))


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


def snap(value: float) -> float:
    return min(SCALE, key=lambda s: abs(s - value))


def quad_editor(rid: str, i: int, q: dict) -> dict | None:
    """Widgets for one brand mention; returns the edited quadruplet, or None if removed."""
    v0, a0 = parse_va(q["VA"])
    v_start, a_start = snap(v0), snap(a0)
    with st.container(border=True):
        aspect_txt = "" if q["Aspect"] == "NULL" else f" · {t('about')}: “{md(q['Aspect'])}”"
        st.markdown(
            f"**{t('mention').format(i=i + 1)}: {brand_label(q.get('Brand', 'generic'))}**{aspect_txt}"
        )
        v_labels, a_labels = t("v_labels"), t("a_labels")
        v = st.select_slider(
            str(t("valence")),
            SCALE,
            v_start,
            format_func=lambda x: f"{x:g} · {word_for(x, v_labels)}",
            key=f"{rid}_{i}_v",
        )
        a = st.select_slider(
            str(t("arousal")),
            SCALE,
            a_start,
            format_func=lambda x: f"{x:g} · {word_for(x, a_labels)}",
            key=f"{rid}_{i}_a",
        )
        notes = []
        if q.get("Confidence") == "low":
            notes.append(f"⚠️ {t('low')}")
        if q.get("BrandInText") is False:
            notes.append(str(t("not_in_text")))
        if notes:
            st.caption(" · ".join(notes))
        with st.expander(str(t("advanced"))):
            cols = st.columns(2)
            aspect = cols[0].text_input(str(t("aspect")), q["Aspect"], key=f"{rid}_{i}_asp")
            opinion = cols[1].text_input(str(t("opinion")), q["Opinion"], key=f"{rid}_{i}_op")
            cat = cols[0].selectbox(
                str(t("category")), CATS, index=CATS.index(q["Category"]), key=f"{rid}_{i}_cat"
            )
            brand = cols[1].selectbox(
                str(t("brand")),
                BRANDS,
                index=BRANDS.index(q.get("Brand", "generic")),
                format_func=brand_label,
                key=f"{rid}_{i}_br",
            )
            removed = st.checkbox(str(t("remove")), key=f"{rid}_{i}_del")
    if removed:
        return None
    # Keep the original value when the slider was not moved (it snaps to quarter steps).
    va = q["VA"] if (v, a) == (v_start, a_start) else va_string(v, a)
    return {
        **q,
        "Aspect": aspect.strip() or "NULL",
        "Opinion": opinion.strip() or "NULL",
        "Category": cat,
        "Brand": brand,
        "VA": va,
    }


def main() -> None:
    st.set_page_config(page_title="Label review", page_icon="📝", layout="centered")
    silver, reviewed = load()

    with st.sidebar:
        st.radio(
            "Language / Dil",
            ["en", "tr"],
            index=["en", "tr"].index(DEFAULT_LANG),
            format_func=lambda x: {"en": "English", "tr": "Türkçe"}[x],
            horizontal=True,
            key="lang",
        )
        done = len(reviewed)
        st.progress(
            done / len(silver), text=str(t("progress")).format(done=done, total=len(silver))
        )
        counts = {
            s: sum(r["Status"] == s for r in reviewed.values())
            for s in ("accepted", "fixed", "skipped")
        }
        st.write(str(t("counts")).format(**counts))
        show_all = st.toggle(str(t("revisit")), value=False)
        st.caption(f"{t('saved_to')}: `{REVIEWED.relative_to(ROOT).as_posix()}`")

    st.title(str(t("title")))
    with st.expander(str(t("what")), expanded=len(reviewed) == 0):
        st.markdown(str(t("explain")))

    queue = [r for r in silver if show_all or r["ID"] not in reviewed]
    if not queue:
        st.success(str(t("all_done")))
        st.balloons()
        return
    pos = st.session_state.setdefault("pos", 0) % len(queue)
    item = queue[pos]
    rid = item["ID"]
    current = reviewed.get(rid, item)  # revisit: start from the saved version

    meta = item.get("Meta", {})
    st.caption(
        f"{t('item').format(n=pos + 1, total=len(queue))} · {meta.get('source_domain', '')} · "
        f"{(meta.get('published_at') or '')[:10]} · {item.get('Language', '?')}"
        + (f" · ⚠️ {t('low')}" if item.get("Confidence") == "low" else "")
        + (f" · {t('already')}" if rid in reviewed else "")
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
        st.markdown(f"[{t('open')}]({meta['url']})")
    if item.get("Rationale"):
        st.caption(f"**{t('reason')}:** {md(item['Rationale'])}")

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
    if st.button(str(t("add"))):
        st.session_state[f"{rid}_extra"] = n_extra + 1
        st.rerun()

    note = st.text_input(str(t("note")), current.get("ReviewNote", ""), key=f"{rid}_note")
    b = st.columns([3, 3, 3, 2])
    accept = b[0].button(
        str(t("accept")), type="primary", width="stretch", help=str(t("accept_help"))
    )
    fix = b[1].button(str(t("fix")), width="stretch", help=str(t("fix_help")))
    skip = b[2].button(str(t("skip")), width="stretch", help=str(t("skip_help")))
    back = b[3].button(str(t("back")), width="stretch")

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
            st.error(str(t("cant_save")) + "; ".join(errs))
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
