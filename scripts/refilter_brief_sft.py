"""Bring the distilled training briefs up to date after the checks or prompt change.

Facts are rebuilt from the same synthetic seeds and matched to each example by
its fact sheet (outlet labels ignored, so an older sheet format still matches). Each
example is then re-checked with the current checks and its prompt is rebuilt
with the current system prompt and fact sheet format. Examples that fail are
dropped; the teacher's brief itself is never edited.
"""

import json
import re
import sys
from collections import Counter
from pathlib import Path

from pr_radar.config import load_config
from pr_radar.narrative.checks import check_brief
from pr_radar.narrative.distill import training_weeks
from pr_radar.narrative.facts import fact_sheet
from pr_radar.narrative.prompt import messages


def key(sheet: str) -> str:
    return re.sub(r"(competitor articles),? .*", r"\1", sheet)


path = Path(sys.argv[1] if len(sys.argv) > 1 else "data/brief_sft/train.jsonl")
brands = list(load_config("config/brands.yaml").brand_names.values())
by_sheet = {key(fact_sheet(f)): f for f in training_weeks(brands, 1000)}

kept, reasons = [], Counter()
for line in path.read_text(encoding="utf-8").splitlines():
    rec = json.loads(line)
    user = rec["messages"][-2]["content"]
    old = user.removeprefix("Fact sheet:\n").removesuffix("\n\nWrite the brief.")
    facts = by_sheet[key(old)]
    sheet, brief = fact_sheet(facts), rec["messages"][-1]["content"]
    res = check_brief(brief, sheet, facts)
    if res.ok and not res.style:
        msgs = [*messages(facts["primary"], sheet, example=False)]
        kept.append(json.dumps({"messages": [*msgs, {"role": "assistant", "content": brief}]},
                               ensure_ascii=False))  # fmt: skip
    reasons.update(e.split(":")[0] for e in res.errors)

path.write_text("\n".join(kept) + "\n", encoding="utf-8")
print(f"kept {len(kept)}; dropped for: {dict(reasons)}")
