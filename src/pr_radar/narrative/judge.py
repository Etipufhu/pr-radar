"""Score how useful a brief's advice is, with a larger model as judge.

The rule checks only test whether a brief is grounded in the data. The judge
reads the fact sheet and the brief and gives a 1-5 score for the advice. The
judge comes from the same model family as the teacher, so it may favour the
teacher's style; the scores are a rough guide, not ground truth.
"""

from __future__ import annotations

import json
import re
from collections.abc import Callable
from pathlib import Path
from typing import Any

JUDGE_SYSTEM = """You review weekly PR briefs written for {brand}'s PR team.
You get the fact sheet the writer used and the brief. Score the brief from 1 to 5:

5: the summary gets {brand}'s position right, and every action is a concrete,
   sensible step for {brand}'s PR team that follows from a gap in the fact sheet.
4: good, with one action that is vague or only loosely tied to the data.
3: the picture is right, but several actions are generic or weak.
2: an action makes little sense for {brand}, or the summary misreads the data.
1: the advice would help a competitor, or the brief is mostly wrong.

Answer with two lines:
Score: <1-5>
Reason: <one sentence>"""

JUDGE_USER = "Fact sheet:\n{sheet}\n\nBrief:\n{brief}"

Generate = Callable[[list[dict[str, str]], bool], str]


def judge_messages(brand: str, sheet: str, brief: str) -> list[dict[str, str]]:
    return [
        {"role": "system", "content": JUDGE_SYSTEM.format(brand=brand)},
        {"role": "user", "content": JUDGE_USER.format(sheet=sheet, brief=brief)},
    ]


def parse_score(text: str) -> int | None:
    m = re.search(r"Score:\s*([1-5])", text)
    return int(m[1]) if m else None


def judge_results(path: str | Path, generate: Generate) -> dict[str, Any]:
    """Add a judge score for each week's first draft to a brief-eval result file."""
    path = Path(path)
    result = json.loads(path.read_text(encoding="utf-8"))
    scores = []
    for s in result["samples"]:
        first = s["drafts"][0]["text"]
        reply = generate(judge_messages(s["facts"]["primary"], s["sheet"], first), False)
        s["judge"] = {"score": parse_score(reply), "reply": reply}
        if s["judge"]["score"] is not None:
            scores.append(s["judge"]["score"])
    result["judge_mean"] = sum(scores) / len(scores) if scores else None
    result["judge_share_4_plus"] = sum(x >= 4 for x in scores) / len(scores) if scores else None
    path.write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding="utf-8")
    return {
        "file": str(path),
        "mean": result["judge_mean"],
        "share_4_plus": result["judge_share_4_plus"],
    }
