"""Multilingual valence/arousal regressor (DimASR) on a pretrained encoder.

Input is the sentence pair (aspect, text); the head regresses two values scaled to
[0, 1]. Trained jointly on every language and domain of the official data, so the
multilingual encoder can transfer to languages DimABSA does not cover (German,
French, Spanish, Turkish, ...).
"""

from __future__ import annotations

import json
import logging
import math
import random
import time
from collections.abc import Sequence
from pathlib import Path

import torch
from torch.utils.data import DataLoader
from transformers import (
    AutoModelForSequenceClassification,
    AutoTokenizer,
    get_linear_schedule_with_warmup,
)

from .data import VA_MAX, VA_MIN, VAExample, clip
from .metrics import evaluate

log = logging.getLogger(__name__)
META_FILE = "pr_radar_dimasr.json"


def _scale(x: float) -> float:
    return (x - VA_MIN) / (VA_MAX - VA_MIN)


def _unscale(x: float) -> float:
    return clip(x * (VA_MAX - VA_MIN) + VA_MIN)


class VARegressor:
    def __init__(self, model_name_or_path: str, max_length: int = 160, device: str | None = None):
        self.device = device or ("cuda" if torch.cuda.is_available() else "cpu")
        self.max_length = max_length
        self.tokenizer = AutoTokenizer.from_pretrained(model_name_or_path)
        self.model = AutoModelForSequenceClassification.from_pretrained(
            model_name_or_path, num_labels=2, problem_type="regression"
        ).to(self.device)

    @classmethod
    def load(cls, path: str | Path, device: str | None = None) -> VARegressor:
        meta = json.loads((Path(path) / META_FILE).read_text(encoding="utf-8"))
        return cls(str(path), max_length=meta["max_length"], device=device)

    def _encode(self, aspects: Sequence[str], texts: Sequence[str]):
        return self.tokenizer(
            list(aspects),
            list(texts),
            truncation="only_second",
            max_length=self.max_length,
            padding=True,
            return_tensors="pt",
        ).to(self.device)

    @torch.no_grad()
    def predict(
        self, aspects: Sequence[str], texts: Sequence[str], batch_size: int = 64
    ) -> list[tuple[float, float]]:
        self.model.eval()
        out: list[tuple[float, float]] = []
        for i in range(0, len(texts), batch_size):
            batch = self._encode(aspects[i : i + batch_size], texts[i : i + batch_size])
            with torch.autocast(self.device, dtype=torch.bfloat16, enabled=self.device == "cuda"):
                logits = self.model(**batch).logits.float().cpu()
            out.extend((_unscale(v), _unscale(a)) for v, a in logits.tolist())
        return out

    def evaluate(self, examples: Sequence[VAExample], batch_size: int = 64) -> dict:
        preds = self.predict([e.aspect for e in examples], [e.text for e in examples], batch_size)
        return evaluate([(e.valence, e.arousal) for e in examples], preds)

    def fit(
        self,
        train: Sequence[VAExample],
        dev: dict[str, Sequence[VAExample]],
        out_dir: str | Path | None,
        epochs: int = 4,
        batch_size: int = 32,
        lr: float = 2e-5,
        warmup: float = 0.06,
        seed: int = 13,
        freeze_embeddings: bool = True,
    ) -> list[dict]:
        """Train, evaluate on every dev set after each epoch, keep the best checkpoint
        (lowest mean normalised RMSE across dev sets). Returns the epoch history."""
        random.seed(seed)
        torch.manual_seed(seed)
        out_dir = Path(out_dir) if out_dir is not None else None
        rows = [(e.aspect, e.text, _scale(e.valence), _scale(e.arousal)) for e in train]

        def collate(batch):
            aspects, texts, v, a = zip(*batch, strict=True)
            enc = self._encode(aspects, texts)
            enc["labels"] = torch.tensor(list(zip(v, a, strict=True)), device=self.device)
            return enc

        loader = DataLoader(rows, batch_size=batch_size, shuffle=True, collate_fn=collate)
        if freeze_embeddings:
            # XLM-R's 250k-token embedding matrix is ~70% of its parameters. Freezing it
            # keeps gradients and Adam state small enough for an 8 GB GPU; without it,
            # Windows spills GPU memory to system RAM and training runs ~40x slower.
            self.model.get_input_embeddings().weight.requires_grad_(False)
        params = [p for p in self.model.parameters() if p.requires_grad]
        optim = torch.optim.AdamW(params, lr=lr, weight_decay=0.01)
        steps = epochs * len(loader)
        sched = get_linear_schedule_with_warmup(optim, int(warmup * steps), steps)

        history, best = [], math.inf
        for epoch in range(1, epochs + 1):
            self.model.train()
            started, running = time.time(), 0.0
            for step, batch in enumerate(loader, start=1):
                with torch.autocast(
                    self.device, dtype=torch.bfloat16, enabled=self.device == "cuda"
                ):
                    loss = self.model(**batch).loss
                loss.backward()
                torch.nn.utils.clip_grad_norm_(self.model.parameters(), 1.0)
                optim.step()
                sched.step()
                optim.zero_grad(set_to_none=True)
                running += loss.item()
                if step % 200 == 0:
                    log.info(
                        "epoch %d step %d/%d loss %.4f", epoch, step, len(loader), running / step
                    )

            scores = {name: self.evaluate(ex) for name, ex in dev.items()}
            mean_rmse = sum(s["rmse_norm"] for s in scores.values()) / len(scores)
            record = {
                "epoch": epoch,
                "train_loss": running / len(loader),
                "dev_mean_rmse_norm": mean_rmse,
                "dev": scores,
                "seconds": round(time.time() - started, 1),
            }
            history.append(record)
            log.info(
                "epoch %d dev mean RMSE_norm %.4f (%.0fs)", epoch, mean_rmse, record["seconds"]
            )
            if mean_rmse < best:
                best = mean_rmse
                if out_dir is not None:
                    self.save(out_dir)
                    log.info("saved best checkpoint to %s", out_dir)
        return history

    def save(self, out_dir: str | Path) -> None:
        out_dir = Path(out_dir)
        out_dir.mkdir(parents=True, exist_ok=True)
        self.model.save_pretrained(out_dir)
        self.tokenizer.save_pretrained(out_dir)
        (out_dir / META_FILE).write_text(
            json.dumps({"max_length": self.max_length, "scale": [VA_MIN, VA_MAX]}, indent=2),
            encoding="utf-8",
        )
