"""Balance the training briefs between weeks with and without a warm outlet.

In the teacher data every week with a warm outlet (one that covered the brand
before) has a "re-pitch" action, and those weeks are about two thirds of the
set. A model trained on it re-pitches by habit, also when no outlet is warm.
This keeps every week without a warm outlet and samples the same number of
weeks with one.

    python scripts/balance_brief_sft.py data/brief_sft/train.jsonl data/brief_sft/train_balanced.jsonl
"""

import json
import random
import sys
from pathlib import Path

src, dst = Path(sys.argv[1]), Path(sys.argv[2])
lines = src.read_text(encoding="utf-8").splitlines()
warm, cold = [], []
for line in lines:
    sheet = json.loads(line)["messages"][-2]["content"]
    (warm if ", covered " in sheet else cold).append(line)

random.Random(0).shuffle(warm)
kept = cold + warm[: len(cold)]
random.Random(1).shuffle(kept)
dst.write_text("\n".join(kept) + "\n", encoding="utf-8")
print(f"{len(warm)} warm and {len(cold)} cold weeks -> {len(kept)} examples")
