"""Training data for the LoRA fine-tune, made by rejection sampling.

The base model writes several candidate briefs per synthetic week using the
few-shot prompt. Only candidates that pass every check are kept, and per week
the one that uses the most facts from the sheet wins. The training example
pairs that brief with the prompt *without* the worked example, so the tuned
model learns the task instead of copying the example.

Synthetic weeks use seeds from 1000 up; evaluation uses seeds below 1000 and
the real week, so the two never overlap.
"""

from __future__ import annotations

import json
import logging
import random
from pathlib import Path
from typing import Any

from .checks import check_brief
from .evaluate import synthetic_facts
from .facts import fact_sheet
from .prompt import messages

log = logging.getLogger(__name__)

TRAIN_SEED_OFFSET = 1000


def content_score(text: str, facts: dict[str, Any]) -> int:
    """How many distinct facts from the sheet the brief uses."""
    low = text.lower()
    items = [b["brand"] for b in facts["brands"]]
    items += [m["country"] for m in facts["market_gaps"]]
    items += [o["outlet"] for o in facts["outlet_gaps"]["top"]]
    items += [t["topic"] for t in facts["topic_gaps"]]
    items += [r["outlet"] for r in facts["risks"]]
    return sum(1 for i in set(items) if i.lower() in low)


def training_weeks(brands: list[str], n: int, start: int = 0) -> list[dict[str, Any]]:
    """Synthetic weeks with a random primary brand, so the model is not tied to one brand."""
    weeks = []
    for i in range(start, start + n):
        seed = TRAIN_SEED_OFFSET + i
        primary = random.Random(seed).choice(brands)
        weeks.append(synthetic_facts(primary, [b for b in brands if b != primary], seed))
    return weeks


def build_dataset(
    llm,
    weeks: list[dict[str, Any]],
    out_path: str | Path,
    samples_per_week: int = 8,
    weeks_per_batch: int = 2,
    temperature: float = 0.8,
    append: bool = False,
) -> dict[str, Any]:
    out_path = Path(out_path)
    out_path.parent.mkdir(parents=True, exist_ok=True)
    kept = candidates = passed = 0
    with out_path.open("a" if append else "w", encoding="utf-8") as fh:
        from tqdm.auto import tqdm

        bar = tqdm(total=len(weeks), desc="distill", unit="week")
        for start in range(0, len(weeks), weeks_per_batch):
            chunk = weeks[start : start + weeks_per_batch]
            sheets = [fact_sheet(f) for f in chunk]
            convs = [
                messages(f["primary"], sheet)
                for f, sheet in zip(chunk, sheets, strict=True)
                for _ in range(samples_per_week)
            ]
            texts = llm.batch(convs, sample=True, temperature=temperature)
            for j, (f, sheet) in enumerate(zip(chunk, sheets, strict=True)):
                good = []
                for text in texts[j * samples_per_week : (j + 1) * samples_per_week]:
                    candidates += 1
                    res = check_brief(text, sheet, f)
                    if res.ok and not res.style:
                        passed += 1
                        good.append(text)
                if not good:
                    continue
                best = max(good, key=lambda t: content_score(t, f))
                record = {
                    "messages": [
                        *messages(f["primary"], sheet, example=False),
                        {"role": "assistant", "content": best},
                    ]
                }
                fh.write(json.dumps(record, ensure_ascii=False) + "\n")
                fh.flush()  # keep finished weeks if the run is stopped
                kept += 1
            bar.update(len(chunk))
            bar.set_postfix(kept=kept)
        bar.close()
    return {
        "weeks": len(weeks),
        "candidates": candidates,
        "candidate_pass_rate": passed / max(candidates, 1),
        "examples": kept,
    }
