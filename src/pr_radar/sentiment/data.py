"""Load SemEval-2026 Task 3 (DimABSA) data as (text, aspect, valence, arousal) pairs.

Official files live in `task-dataset/track_a/subtask_1/<lang>/` and are named
`<lang>_<domain>_<split>_<task1|alltasks>.jsonl`. Records come in three shapes:

* subtask 1:   {"ID", "Text", "Aspect_VA": [{"Aspect", "VA"}]}
* subtask 2:   {"ID", "Text", "Triplet":   [{"Aspect", "Opinion", "VA"}]}
* subtask 3:   {"ID", "Text", "Quadruplet":[{"Aspect", "Category", "Opinion", "VA"}]}

VA is a "V#A" string, both on a 1.00-9.00 scale. Implicit aspects ("NULL") are
skipped because subtask 1 scores an aspect that appears in the text.
"""

from __future__ import annotations

import json
import re
from collections.abc import Iterable
from dataclasses import dataclass
from pathlib import Path

VA_MIN, VA_MAX = 1.0, 9.0
SUBTASK1_DIR = Path("task-dataset/track_a/subtask_1")
_FILE_RE = re.compile(r"^(?P<lang>[a-z]{3})_(?P<domain>[a-z]+)_(?P<split>train|dev|test)_")


@dataclass(frozen=True)
class VAExample:
    id: str
    text: str
    aspect: str
    valence: float
    arousal: float
    lang: str = ""
    domain: str = ""


def parse_va(value: str) -> tuple[float, float]:
    v, a = value.split("#")
    return float(v), float(a)


def clip(x: float) -> float:
    return min(VA_MAX, max(VA_MIN, x))


def format_va(valence: float, arousal: float) -> str:
    return f"{clip(valence):.2f}#{clip(arousal):.2f}"


def records_to_examples(
    records: Iterable[dict], lang: str = "", domain: str = ""
) -> list[VAExample]:
    examples: list[VAExample] = []
    for rec in records:
        items = rec.get("Aspect_VA") or rec.get("Triplet") or rec.get("Quadruplet") or []
        for item in items:
            aspect = (item.get("Aspect") or "").strip()
            if not aspect or aspect == "NULL" or not item.get("VA"):
                continue
            v, a = parse_va(item["VA"])
            examples.append(
                VAExample(
                    id=str(rec.get("ID", "")),
                    text=rec["Text"],
                    aspect=aspect,
                    valence=v,
                    arousal=a,
                    lang=lang or rec.get("Language", ""),
                    domain=domain,
                )
            )
    return examples


def read_jsonl(path: str | Path) -> list[dict]:
    with open(path, encoding="utf-8") as fh:
        return [json.loads(line) for line in fh if line.strip()]


def discover(root: str | Path) -> dict[tuple[str, str, str], Path]:
    """Map (lang, domain, split) -> file for the official subtask 1 data."""
    base = Path(root) / SUBTASK1_DIR
    found: dict[tuple[str, str, str], Path] = {}
    for path in sorted(base.glob("*/*.jsonl")):
        m = _FILE_RE.match(path.name)
        if m:
            found[(m["lang"], m["domain"], m["split"])] = path
    return found


def load_split(
    root: str | Path, split: str, langs: Iterable[str] | None = None
) -> dict[tuple[str, str], list[VAExample]]:
    """Examples per (lang, domain) for one split."""
    wanted = set(langs) if langs else None
    out: dict[tuple[str, str], list[VAExample]] = {}
    for (lang, domain, s), path in discover(root).items():
        if s != split or (wanted and lang not in wanted):
            continue
        out[(lang, domain)] = records_to_examples(read_jsonl(path), lang, domain)
    return out


def load_domain_set(path: str | Path) -> list[VAExample]:
    """The PR Radar beauty-tech headline set (same JSONL shape, subtask 3 style)."""
    return records_to_examples(read_jsonl(path), domain="beautytech_news")
