"""Train and evaluate the DimASR model; write a results table.

Evaluation:
* official test sets of every language/domain (gold labels released by the organisers)
* the PR Radar beauty-tech headline set, to see how well the model transfers to
  news about consumer devices (a domain DimABSA does not cover)
* a constant baseline (training-set mean), so every number has a reference point
* optionally, a held-out language never seen in training, to estimate zero-shot
  transfer to languages such as German or Turkish that DimABSA has no data for
"""

from __future__ import annotations

import json
import logging
from datetime import UTC, datetime
from pathlib import Path

from .data import VAExample, load_domain_set, load_split
from .metrics import evaluate

log = logging.getLogger(__name__)


def _mean_baseline(train: list[VAExample]) -> tuple[float, float]:
    return (
        sum(e.valence for e in train) / len(train),
        sum(e.arousal for e in train) / len(train),
    )


def _score_constant(examples: list[VAExample], va: tuple[float, float]) -> dict:
    return evaluate([(e.valence, e.arousal) for e in examples], [va] * len(examples))


def run_experiment(
    data_root: str | Path,
    model_dir: str | Path,
    results_dir: str | Path,
    base_model: str = "xlm-roberta-base",
    epochs: int = 4,
    batch_size: int = 32,
    lr: float = 2e-5,
    max_length: int = 160,
    domain_set: str | Path | None = None,
    holdout_lang: str | None = None,
) -> dict:
    from .model import VARegressor  # heavy import, only when training

    train_sets = load_split(data_root, "train")
    dev_sets = load_split(data_root, "dev")
    test_sets = load_split(data_root, "test")
    if holdout_lang:
        train_sets = {k: v for k, v in train_sets.items() if k[0] != holdout_lang}
        dev_sets = {k: v for k, v in dev_sets.items() if k[0] != holdout_lang}

    train = [e for exs in train_sets.values() for e in exs]
    dev = {f"{lang}_{dom}": exs for (lang, dom), exs in dev_sets.items()}
    log.info("train: %d aspect pairs from %d files", len(train), len(train_sets))

    reg = VARegressor(base_model, max_length=max_length)
    history = reg.fit(train, dev, model_dir, epochs=epochs, batch_size=batch_size, lr=lr)
    best = VARegressor.load(model_dir)
    baseline = _mean_baseline(train)

    test = {}
    for (lang, dom), exs in sorted(test_sets.items()):
        test[f"{lang}_{dom}"] = {
            "model": best.evaluate(exs),
            "baseline": _score_constant(exs, baseline),
            "zero_shot": lang == holdout_lang,
        }

    domain = None
    if domain_set and Path(domain_set).exists():
        exs = load_domain_set(domain_set)
        if exs:
            domain = {
                "file": str(Path(domain_set).as_posix()),
                "model": best.evaluate(exs),
                "baseline": _score_constant(exs, baseline),
            }

    results = {
        "created_at": datetime.now(UTC).isoformat(timespec="seconds"),
        "base_model": base_model,
        "holdout_lang": holdout_lang,
        "hyperparameters": {
            "epochs": epochs,
            "batch_size": batch_size,
            "lr": lr,
            "max_length": max_length,
        },
        "train_pairs": len(train),
        "baseline_va": baseline,
        "history": history,
        "test": test,
        "domain_set": domain,
    }
    results_dir = Path(results_dir)
    results_dir.mkdir(parents=True, exist_ok=True)
    stem = base_model.split("/")[-1] + (f"_holdout-{holdout_lang}" if holdout_lang else "")
    (results_dir / f"dimasr_{stem}.json").write_text(
        json.dumps(results, indent=2), encoding="utf-8"
    )
    (results_dir / f"dimasr_{stem}.md").write_text(to_markdown(results), encoding="utf-8")
    return results


def to_markdown(results: dict) -> str:
    def row(name: str, r: dict, note: str = "") -> str:
        m, b = r["model"], r["baseline"]
        gain = (1 - m["rmse_norm"] / b["rmse_norm"]) * 100
        return (
            f"| {name}{note} | {m['n']} | **{m['rmse_norm']:.3f}** | {b['rmse_norm']:.3f} "
            f"| {gain:.0f}% | {m['pcc_valence']:.2f} | {m['pcc_arousal']:.2f} |"
        )

    lines = [
        f"# DimASR results: `{results['base_model']}`",
        "",
        f"Trained {results['created_at']} on {results['train_pairs']:,} aspect pairs "
        f"({results['hyperparameters']['epochs']} epochs, lr {results['hyperparameters']['lr']}, "
        f"batch {results['hyperparameters']['batch_size']}).",
        "",
        "RMSE is the official normalised RMSE over (valence, arousal), lower is better. "
        "Baseline = always predict the training-set mean. PCC = Pearson correlation.",
        "",
        "| Test set | Aspects | RMSE (model) | RMSE (baseline) | Error reduction | PCC valence | PCC arousal |",
        "|---|---:|---:|---:|---:|---:|---:|",
    ]
    for name, r in results["test"].items():
        lines.append(row(name, r, " (zero-shot)" if r.get("zero_shot") else ""))
    if results.get("domain_set"):
        lines.append(row("beauty-tech news headlines (PR Radar)", results["domain_set"]))
        lines += [
            "",
            "The beauty-tech set was pre-annotated by an LLM and is being verified by a human; "
            "treat it as indicative until the reviewed version replaces it.",
        ]
    lines += [
        "",
        "## Training history",
        "",
        "| Epoch | Train loss | Dev mean RMSE | Time |",
        "|---:|---:|---:|---:|",
    ]
    for h in results["history"]:
        lines.append(
            f"| {h['epoch']} | {h['train_loss']:.4f} | {h['dev_mean_rmse_norm']:.4f} | {h['seconds']:.0f}s |"
        )
    return "\n".join(lines) + "\n"


# -- domain adaptation ------------------------------------------------------------


def _folds(n: int, k: int, seed: int = 0) -> list[list[int]]:
    import random

    idx = list(range(n))
    random.Random(seed).shuffle(idx)
    return [idx[i::k] for i in range(k)]


def _linear_fit(xs: list[float], ys: list[float]) -> tuple[float, float]:
    mx, my = sum(xs) / len(xs), sum(ys) / len(ys)
    sxx = sum((x - mx) ** 2 for x in xs) or 1e-9
    slope = sum((x - mx) * (y - my) for x, y in zip(xs, ys, strict=True)) / sxx
    return slope, my - slope * mx


def fit_calibration(pred: list[tuple[float, float]], gold: list[tuple[float, float]]) -> dict:
    """Per-dimension linear map from model output to the target domain's scale."""
    v = _linear_fit([p[0] for p in pred], [g[0] for g in gold])
    a = _linear_fit([p[1] for p in pred], [g[1] for g in gold])
    return {"valence": list(v), "arousal": list(a)}


def apply_calibration(
    pred: list[tuple[float, float]], cal: dict | None
) -> list[tuple[float, float]]:
    from .data import clip

    if not cal:
        return list(pred)
    (bv, av), (ba, aa) = cal["valence"], cal["arousal"]
    return [(clip(bv * v + av), clip(ba * a + aa)) for v, a in pred]


def domain_cross_validation(
    model_dir: str | Path,
    domain_set: str | Path,
    results_dir: str | Path,
    k: int = 5,
    epochs: int = 5,
    lr: float = 1e-5,
    batch_size: int = 16,
) -> dict:
    """Compare four ways to use the DimABSA model on news headlines, with k-fold CV:

    1. domain mean      : always predict the mean label of the training folds
    2. zero-shot        : the DimABSA model as is
    3. calibrated       : zero-shot + linear calibration fitted on the training folds
    4. fine-tuned       : DimABSA model further trained on the training folds
    """
    from .model import VARegressor

    examples = load_domain_set(domain_set)
    gold = [(e.valence, e.arousal) for e in examples]
    folds = _folds(len(examples), k)
    zero = VARegressor.load(model_dir).predict(
        [e.aspect for e in examples], [e.text for e in examples]
    )
    out = {
        name: [None] * len(examples)
        for name in ("domain_mean", "zero_shot", "calibrated", "fine_tuned")
    }
    for f, test_idx in enumerate(folds, start=1):
        test_set = set(test_idx)
        train_idx = [i for i in range(len(examples)) if i not in test_set]
        mean = (
            sum(gold[i][0] for i in train_idx) / len(train_idx),
            sum(gold[i][1] for i in train_idx) / len(train_idx),
        )
        cal = fit_calibration([zero[i] for i in train_idx], [gold[i] for i in train_idx])
        calibrated = apply_calibration([zero[i] for i in test_idx], cal)

        tuned = VARegressor.load(model_dir)
        tuned.fit(
            [examples[i] for i in train_idx],
            {"fold": [examples[i] for i in test_idx]},
            out_dir=None,
            epochs=epochs,
            batch_size=batch_size,
            lr=lr,
            warmup=0.1,
        )
        tuned_pred = tuned.predict(
            [examples[i].aspect for i in test_idx], [examples[i].text for i in test_idx]
        )
        for j, i in enumerate(test_idx):
            out["domain_mean"][i] = mean
            out["zero_shot"][i] = zero[i]
            out["calibrated"][i] = calibrated[j]
            out["fine_tuned"][i] = tuned_pred[j]
        log.info("fold %d/%d done", f, k)
        del tuned

    scores = {name: evaluate(gold, preds) for name, preds in out.items()}
    results = {
        "created_at": datetime.now(UTC).isoformat(timespec="seconds"),
        "model_dir": str(Path(model_dir).as_posix()),
        "domain_set": str(Path(domain_set).as_posix()),
        "k": k,
        "fine_tune": {"epochs": epochs, "lr": lr, "batch_size": batch_size},
        "scores": scores,
    }
    results_dir = Path(results_dir)
    results_dir.mkdir(parents=True, exist_ok=True)
    (results_dir / "dimasr_domain_cv.json").write_text(
        json.dumps(results, indent=2), encoding="utf-8"
    )
    return results
