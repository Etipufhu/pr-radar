"""DimASR metrics, matching the official SemEval-2026 Task 3 evaluation script.

RMSE_VA = sqrt( sum_i (dV_i^2 + dA_i^2) / N ), normalised by sqrt(128) (the
largest possible distance in the [1, 9] x [1, 9] square), so 0 is perfect and 1
is the worst possible. Pearson correlation is reported per dimension.
"""

from __future__ import annotations

import math
from collections.abc import Sequence

D_MAX = math.sqrt(128)


def rmse_va(
    gold: Sequence[tuple[float, float]],
    pred: Sequence[tuple[float, float]],
    normalize: bool = True,
) -> float:
    if len(gold) != len(pred) or not gold:
        raise ValueError("gold and pred must be non-empty and the same length")
    total = sum(
        (pv - gv) ** 2 + (pa - ga) ** 2 for (gv, ga), (pv, pa) in zip(gold, pred, strict=True)
    )
    value = math.sqrt(total / len(gold))
    return value / D_MAX if normalize else value


def pearson(x: Sequence[float], y: Sequence[float]) -> float:
    n = len(x)
    if n < 2:
        return float("nan")
    mx, my = sum(x) / n, sum(y) / n
    sxy = sum((a - mx) * (b - my) for a, b in zip(x, y, strict=True))
    sxx = sum((a - mx) ** 2 for a in x)
    syy = sum((b - my) ** 2 for b in y)
    if sxx == 0 or syy == 0:
        return float("nan")
    return sxy / math.sqrt(sxx * syy)


def evaluate(gold: Sequence[tuple[float, float]], pred: Sequence[tuple[float, float]]) -> dict:
    return {
        "n": len(gold),
        "rmse_norm": rmse_va(gold, pred, normalize=True),
        "rmse": rmse_va(gold, pred, normalize=False),
        "pcc_valence": pearson([g[0] for g in gold], [p[0] for p in pred]),
        "pcc_arousal": pearson([g[1] for g in gold], [p[1] for p in pred]),
    }
