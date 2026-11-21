"""Quick human check of the LLM headline labels: good, neutral or bad for the brand.

    .venv/Scripts/python -m streamlit run annotation/quick_check.py -- --lang tr
    .venv/Scripts/python annotation/quick_check.py --summary

The full review tool (review_app.py) asks for valence and arousal on a 1-9
scale per aspect, which needs a reader who knows the products and languages.
This asks one question a non-expert can answer for 30 English headlines: is
the headline good, neutral or bad news for the brand? The LLM's label is
hidden until the end. Agreement is measured against the LLM valence binned
as bad (< 4.5), neutral (4.5-5.5) or good (> 5.5).

Selection: all English headlines that name a tracked brand and that the LLM
rated neutral or bad, plus random ones it rated good, 30 in total, in a fixed
shuffled order. Turkish translations (quick_check_tr.json) can be shown to the
reader; the English original is always shown too.
"""

from __future__ import annotations

import json
import random
import sys
from collections import Counter
from datetime import UTC, datetime
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from dimabsa_format import TRACKED_BRANDS, parse_va, read_jsonl, write_jsonl  # noqa: E402

ROOT = Path(__file__).resolve().parents[1]
SILVER = ROOT / "data" / "annotations" / "foreo_domain_v1.silver.jsonl"
ANSWERS = ROOT / "data" / "annotations" / "foreo_domain_v1.quick_check.jsonl"
TRANSLATIONS = Path(__file__).resolve().parent / "quick_check_tr.json"
N_ITEMS = 30
BRAND_NAMES = {
    "foreo": "FOREO",
    "nuface": "NuFACE",
    "currentbody": "CurrentBody",
    "therabody": "Therabody",
    "pmd": "PMD Beauty",
    "solawave": "Solawave",
}


def tone(valence: float) -> str:
    return "bad" if valence < 4.5 else "neutral" if valence <= 5.5 else "good"


def pick_items(silver: list[dict], n: int = N_ITEMS) -> list[dict]:
    """English headlines with a tracked brand; every non-good one, then random good ones."""
    items = []
    for r in silver:
        if r.get("Language") != "en":
            continue
        q = next((q for q in r["Quadruplet"] if q.get("Brand") in TRACKED_BRANDS), None)
        if q is None:
            continue
        v, _ = parse_va(q["VA"])
        items.append({"ID": r["ID"], "Text": r["Text"], "Brand": q["Brand"], "LlmValence": v})
    rest = [i for i in items if tone(i["LlmValence"]) != "good"]
    good = [i for i in items if tone(i["LlmValence"]) == "good"]
    random.Random(0).shuffle(good)
    picked = rest + good[: max(n - len(rest), 0)]
    random.Random(1).shuffle(picked)
    return picked


def summary(items: list[dict], answers: dict[str, dict]) -> dict:
    answered = [a for a in answers.values() if a["Answer"] != "unsure"]
    agree = sum(a["Answer"] == tone(a["LlmValence"]) for a in answered)
    pairs = Counter((tone(a["LlmValence"]), a["Answer"]) for a in answered)
    # Cohen's kappa: agreement corrected for what the two label distributions give by chance.
    n = len(answered)
    human = Counter(a["Answer"] for a in answered)
    llm = Counter(tone(a["LlmValence"]) for a in answered)
    chance = sum(human[k] * llm[k] for k in human) / n / n if n else 0
    kappa = (agree / n - chance) / (1 - chance) if n and chance < 1 else None
    return {
        "items": len(items),
        "answered": len(answered),
        "unsure": sum(a["Answer"] == "unsure" for a in answers.values()),
        "agree": agree,
        "agreement": agree / len(answered) if answered else None,
        "cohen_kappa": round(kappa, 2) if kappa is not None else None,
        "always_good_baseline": human["good"] / n if n else None,
        "llm_vs_human": {f"{k[0]}->{k[1]}": v for k, v in sorted(pairs.items())},
    }


TEXT = {
    "en": {
        "title": "Quick check: good, neutral or bad?",
        "explain": (
            "A language model rated how each headline talks about a brand. Here you give "
            "your own answer, without seeing the model's. No product knowledge is needed: "
            "answer the way you would if a friend showed you the headline. If you can't "
            "tell, press **Not sure**. The model's answers are shown at the end."
        ),
        "progress": "{done} of {total} answered",
        "question": "Is this headline good, neutral or bad news for **{brand}**?",
        "original": "Original headline",
        "good": "👍 Good",
        "neutral": "😐 Neutral",
        "bad": "👎 Bad",
        "unsure": "🤷 Not sure",
        "back": "← Back",
        "done": "Done, thank you! How your answers compare with the model's:",
        "agree": "You and the model agree on {agree} of the {answered} headlines you answered "
        "({pct:.0%}); {unsure} marked not sure.",
        "table_h": ("Headline", "Brand", "You", "Model"),
        "words": {"good": "good", "neutral": "neutral", "bad": "bad", "unsure": "not sure"},
    },
    "tr": {
        "title": "Hızlı kontrol: iyi, nötr ya da kötü?",
        "explain": (
            "Bir dil modeli her başlığın bir markadan nasıl bahsettiğini puanladı. Burada "
            "modelin cevabını görmeden kendi cevabını veriyorsun. Ürün bilgisi gerekmiyor: "
            "bir arkadaşın sana bu başlığı gösterse ne derdin, onu seç. Karar veremiyorsan "
            "**Bilmiyorum**'a bas. Modelin cevapları en sonda gösterilecek."
        ),
        "progress": "{total} başlığın {done} tanesi cevaplandı",
        "question": "Bu başlık **{brand}** için iyi haber mi, nötr mü, kötü haber mi?",
        "original": "Orijinal başlık",
        "good": "👍 İyi",
        "neutral": "😐 Nötr",
        "bad": "👎 Kötü",
        "unsure": "🤷 Bilmiyorum",
        "back": "← Geri",
        "done": "Bitti, teşekkürler! Cevaplarının modelinkilerle karşılaştırması:",
        "agree": "Cevapladığın {answered} başlığın {agree} tanesinde modelle aynı fikirdesin "
        "(%{pct100:.0f}); {unsure} tanesine 'bilmiyorum' dedin.",
        "table_h": ("Başlık", "Marka", "Sen", "Model"),
        "words": {"good": "iyi", "neutral": "nötr", "bad": "kötü", "unsure": "bilmiyorum"},
    },
}


def main() -> None:
    import streamlit as st

    lang = sys.argv[sys.argv.index("--lang") + 1] if "--lang" in sys.argv else "en"
    T = TEXT[lang]
    st.set_page_config(page_title="Quick check", page_icon="✅", layout="centered")
    items = pick_items(read_jsonl(SILVER))
    answers = {a["ID"]: a for a in read_jsonl(ANSWERS)} if ANSWERS.exists() else {}
    translations = json.loads(TRANSLATIONS.read_text(encoding="utf-8")) if lang == "tr" else {}

    st.title(T["title"])
    st.markdown(T["explain"])
    st.progress(
        len(answers) / len(items), text=T["progress"].format(done=len(answers), total=len(items))
    )

    queue = [i for i in items if i["ID"] not in answers]
    if not queue:
        s = summary(items, answers)
        st.success(T["done"])
        if s["answered"]:
            pct = s["agreement"]
            st.markdown(
                T["agree"].format(
                    agree=s["agree"],
                    answered=s["answered"],
                    unsure=s["unsure"],
                    pct=pct,
                    pct100=pct * 100,
                )
            )
        rows = [
            {
                T["table_h"][0]: translations.get(i["ID"], i["Text"]),
                T["table_h"][1]: BRAND_NAMES[i["Brand"]],
                T["table_h"][2]: T["words"][answers[i["ID"]]["Answer"]],
                T["table_h"][3]: T["words"][tone(i["LlmValence"])],
            }
            for i in items
        ]
        st.dataframe(rows, hide_index=True)
        if st.button(T["back"]):
            last = max(answers.values(), key=lambda a: a["AnsweredAt"])
            answers.pop(last["ID"])
            write_jsonl(list(answers.values()), ANSWERS)
            st.rerun()
        return

    item = queue[0]
    brand = BRAND_NAMES[item["Brand"]]
    st.divider()
    if item["ID"] in translations:
        st.markdown(f"### {translations[item['ID']]}")
        st.caption(f"{T['original']}: {item['Text']}")
    else:
        st.markdown(f"### {item['Text']}")
    st.markdown(T["question"].format(brand=brand))

    cols = st.columns(4)
    choice = None
    for col, key in zip(cols, ("good", "neutral", "bad", "unsure"), strict=True):
        if col.button(T[key], width="stretch", key=f"{item['ID']}_{key}"):
            choice = key
    if answers and st.button(T["back"]):
        last = max(answers.values(), key=lambda a: a["AnsweredAt"])
        answers.pop(last["ID"])
        write_jsonl(list(answers.values()), ANSWERS)
        st.rerun()
    if choice:
        answers[item["ID"]] = {
            "ID": item["ID"],
            "Brand": item["Brand"],
            "Answer": choice,
            "LlmValence": item["LlmValence"],
            "ShownTranslation": item["ID"] in translations,
            "AnsweredAt": datetime.now(UTC).strftime("%Y-%m-%dT%H:%M:%S.%fZ"),
        }
        write_jsonl(list(answers.values()), ANSWERS)
        st.rerun()


if "--summary" in sys.argv:
    items = pick_items(read_jsonl(SILVER))
    answers = {a["ID"]: a for a in read_jsonl(ANSWERS)} if ANSWERS.exists() else {}
    print(json.dumps(summary(items, answers), indent=2))
else:
    main()
