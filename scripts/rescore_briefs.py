"""Re-check saved first drafts with the current checks.

The checks grew while the models were being compared, so older result files
were scored with fewer rules. This re-runs `check_brief` on every first draft
in the given brief-eval files and prints one comparable table.

    python scripts/rescore_briefs.py results/brief_eval_*.json
"""

from __future__ import annotations

import json
import re
import sys
from collections import Counter
from pathlib import Path

from pr_radar.narrative.checks import check_brief


def rescore(path: Path) -> dict:
    result = json.loads(path.read_text(encoding="utf-8"))
    passed = 0
    errors: Counter[str] = Counter()
    for s in result["samples"]:
        res = check_brief(s["drafts"][0]["text"], s["sheet"], s["facts"])
        passed += res.ok
        errors.update(re.sub(r"wrong leader for .*", "wrong leader for a market or topic",
                             e.split(":")[0]) for e in res.errors)  # fmt: skip
    n = len(result["samples"])
    return {
        "file": path.name,
        "weeks": n,
        "first_draft_pass": passed,
        "judge_mean": result.get("judge_mean"),
        "judge_share_4_plus": result.get("judge_share_4_plus"),
        "errors": dict(errors.most_common()),
    }


def main(paths: list[str]) -> None:
    rows = [rescore(Path(p)) for p in paths]
    for r in rows:
        judge = (
            f"judge {r['judge_mean']:.2f}, {r['judge_share_4_plus']:.0%} at 4+"
            if r["judge_mean"] is not None
            else "not judged"
        )
        print(f"{r['file']}: {r['first_draft_pass']}/{r['weeks']} first drafts pass, {judge}")
        for e, c in r["errors"].items():
            print(f"    {c:3d}  {e}")


if __name__ == "__main__":
    main(sys.argv[1:])
