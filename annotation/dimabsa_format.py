"""Record schema for the FOREO-domain DimABSA set, validation and export.

The annotation files are DimABSA (SemEval-2026 Task 3, Track A) Subtask-3 records,
``{"ID", "Text", "Quadruplet": [{"Aspect", "Category", "Opinion", "VA"}]}``, with
extra keys that the official evaluation ignores (Brand, Confidence, Rationale, Meta).
``export`` strips them and writes the official Subtask 1/2/3 files.

    .venv/Scripts/python annotation/dimabsa_format.py export \
        data/annotations/foreo_domain_v1.reviewed.jsonl --out data/annotations/export
"""

from __future__ import annotations

import argparse
import json
from collections.abc import Iterable, Iterator
from pathlib import Path

VA_MIN, VA_MAX = 1.0, 9.0

# ENTITY#ATTRIBUTE inventory for beauty-tech news (SemEval-2016 / DimABSA style).
ENTITIES = ("BRAND", "PRODUCT")
ATTRIBUTES = (
    "GENERAL",
    "PRICES",
    "QUALITY",
    "PERFORMANCE",
    "DESIGN_FEATURES",
    "USABILITY",
    "POPULARITY",
    "SAFETY",
    "BUSINESS",
)
CATEGORIES = frozenset(f"{e}#{a}" for e in ENTITIES for a in ATTRIBUTES)

TRACKED_BRANDS = ("foreo", "nuface", "currentbody", "therabody", "pmd", "solawave")
# other = a named but untracked brand or retailer; generic = a product category
# ("LED masks"); unknown = a specific product whose brand the headline does not reveal.
BRAND_VALUES = frozenset((*TRACKED_BRANDS, "other", "generic", "unknown"))
CONFIDENCE_VALUES = frozenset(("high", "low"))
STATUS_VALUES = frozenset(("silver", "accepted", "fixed", "skipped"))


def va_string(valence: float, arousal: float) -> str:
    """DimABSA writes VA as 'V#A' with two decimals, e.g. '6.75#6.38'."""
    return f"{valence:.2f}#{arousal:.2f}"


def parse_va(va: str) -> tuple[float, float]:
    v, a = va.split("#")
    return float(v), float(a)


def validate_record(rec: dict) -> list[str]:
    """Problems with one record; an empty list means it is valid."""
    errs: list[str] = []
    for key in ("ID", "Text", "Quadruplet"):
        if key not in rec:
            errs.append(f"missing {key}")
    if errs:
        return errs
    text = rec["Text"]
    if rec.get("Status", "silver") not in STATUS_VALUES:
        errs.append(f"bad Status {rec.get('Status')!r}")
    if rec.get("Status") != "skipped" and not rec["Quadruplet"]:
        errs.append("no quadruplets")
    seen: set[tuple[str, str, str]] = set()
    for i, q in enumerate(rec["Quadruplet"]):
        where = f"quad {i}"
        missing = [
            k
            for k in ("Aspect", "Category", "Opinion", "VA")
            if not isinstance(q.get(k), str) or not q[k]
        ]
        if missing:
            errs.append(f"{where}: missing {', '.join(missing)}")
            continue
        for key in ("Aspect", "Opinion"):
            if q[key] != "NULL" and q[key] not in text:
                errs.append(f"{where}: {key} {q[key]!r} is not a span of Text")
        if q["Category"] not in CATEGORIES:
            errs.append(f"{where}: unknown Category {q['Category']!r}")
        try:
            v, a = parse_va(q["VA"])
        except ValueError:
            errs.append(f"{where}: VA {q['VA']!r} is not 'V#A'")
        else:
            if not (VA_MIN <= v <= VA_MAX and VA_MIN <= a <= VA_MAX):
                errs.append(f"{where}: VA {q['VA']} outside [1, 9]")
            if q["VA"] != va_string(v, a):
                errs.append(f"{where}: VA {q['VA']!r} must have two decimals")
        if "Brand" in q and q["Brand"] not in BRAND_VALUES:
            errs.append(f"{where}: unknown Brand {q['Brand']!r}")
        if "Confidence" in q and q["Confidence"] not in CONFIDENCE_VALUES:
            errs.append(f"{where}: bad Confidence {q['Confidence']!r}")
        key = (q["Aspect"], q["Category"], q["Opinion"])
        if key in seen:
            # The official scorer invalidates duplicate categorical tuples.
            errs.append(f"{where}: duplicate (Aspect, Category, Opinion)")
        seen.add(key)
    return errs


def read_jsonl(path: str | Path) -> list[dict]:
    with open(path, encoding="utf-8") as f:
        return [json.loads(line) for line in f if line.strip()]


def write_jsonl(records: Iterable[dict], path: str | Path) -> None:
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(path.suffix + ".tmp")
    with tmp.open("w", encoding="utf-8", newline="\n") as f:
        for rec in records:
            f.write(json.dumps(rec, ensure_ascii=False) + "\n")
    tmp.replace(path)  # atomic on the same volume: a crash never leaves half a file


def to_official(rec: dict, subtask: int) -> dict:
    """Official DimABSA record for Subtask 1 (DimASR), 2 (DimASTE) or 3 (DimASQP)."""
    quads = rec["Quadruplet"]
    if subtask == 1:
        # Subtask 1 has no implicit aspects; each aspect string appears once.
        items, seen = [], set()
        for q in quads:
            if q["Aspect"] != "NULL" and q["Aspect"] not in seen:
                seen.add(q["Aspect"])
                items.append({"Aspect": q["Aspect"], "VA": q["VA"]})
        return {"ID": rec["ID"], "Text": rec["Text"], "Aspect_VA": items}
    if subtask == 2:
        trips = [{"Aspect": q["Aspect"], "Opinion": q["Opinion"], "VA": q["VA"]} for q in quads]
        return {"ID": rec["ID"], "Text": rec["Text"], "Triplet": trips}
    if subtask == 3:
        keys = ("Aspect", "Category", "Opinion", "VA")
        return {
            "ID": rec["ID"],
            "Text": rec["Text"],
            "Quadruplet": [{k: q[k] for k in keys} for q in quads],
        }
    raise ValueError(f"subtask must be 1, 2 or 3, not {subtask}")


def exportable(records: Iterable[dict]) -> Iterator[dict]:
    for rec in records:
        if rec.get("Status") != "skipped" and rec["Quadruplet"]:
            yield rec


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(description="Validate or export the DimABSA annotation file.")
    sub = p.add_subparsers(dest="cmd", required=True)
    v = sub.add_parser("validate")
    v.add_argument("path", type=Path)
    e = sub.add_parser("export")
    e.add_argument("path", type=Path)
    e.add_argument("--out", type=Path, default=Path("data/annotations/export"))
    args = p.parse_args(argv)

    records = read_jsonl(args.path)
    bad = {r.get("ID", "?"): errs for r in records if (errs := validate_record(r))}
    for rid, errs in bad.items():
        print(f"{rid}: " + "; ".join(errs))
    if args.cmd == "validate":
        print(f"{len(records)} records, {len(bad)} invalid")
        return 1 if bad else 0

    keep = [r for r in exportable(records) if r.get("ID") not in bad]
    stem = args.path.name.split(".")[0]
    for n in (1, 2, 3):
        out = args.out / f"{stem}_task{n}.jsonl"
        write_jsonl((to_official(r, n) for r in keep), out)
        print(f"wrote {out} ({len(keep)} records)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
