"""LoRA fine-tune of the brief writer on the distilled examples.

The loss covers only the brief (the assistant turn), not the prompt. The prompt
is rendered exactly as at inference time (chat template, thinking disabled), so
training and generation see the same tokens.
"""

from __future__ import annotations

import json
import logging
import math
import random
import time
from pathlib import Path
from typing import Any

log = logging.getLogger(__name__)

TARGET_MODULES = ["q_proj", "k_proj", "v_proj", "o_proj", "gate_proj", "up_proj", "down_proj"]


def encode(tok, conv: list[dict[str, str]], max_length: int) -> dict[str, list[int]]:
    """Token ids with labels = -100 on the prompt, so only the brief is learned."""
    prompt = tok.apply_chat_template(
        conv[:-1], tokenize=False, add_generation_prompt=True, enable_thinking=False
    )
    answer = conv[-1]["content"] + tok.eos_token
    p_ids = tok(prompt, add_special_tokens=False)["input_ids"]
    a_ids = tok(answer, add_special_tokens=False)["input_ids"]
    ids = (p_ids + a_ids)[:max_length]
    labels = ([-100] * len(p_ids) + a_ids)[:max_length]
    return {"input_ids": ids, "labels": labels}


def _batches(rows: list[dict[str, list[int]]], size: int, pad_id: int, rng: random.Random):
    import torch

    order = list(range(len(rows)))
    rng.shuffle(order)
    for i in range(0, len(order), size):
        chunk = [rows[j] for j in order[i : i + size]]
        width = max(len(r["input_ids"]) for r in chunk)
        ids = torch.full((len(chunk), width), pad_id)
        labels = torch.full((len(chunk), width), -100)
        mask = torch.zeros((len(chunk), width), dtype=torch.long)
        for k, r in enumerate(chunk):
            n = len(r["input_ids"])
            ids[k, :n] = torch.tensor(r["input_ids"])
            labels[k, :n] = torch.tensor(r["labels"])
            mask[k, :n] = 1
        yield ids, labels, mask


def _eval_loss(model, rows, batch_size, pad_id, device) -> float:
    import torch

    model.eval()
    total, count = 0.0, 0
    with torch.no_grad():
        for ids, labels, mask in _batches(rows, batch_size, pad_id, random.Random(0)):
            out = model(
                input_ids=ids.to(device), attention_mask=mask.to(device), labels=labels.to(device)
            )
            n = int((labels != -100).sum())
            total += float(out.loss) * n
            count += n
    model.train()
    return total / max(count, 1)


def train_lora(
    base: str,
    data_path: str | Path,
    out_dir: str | Path,
    epochs: int = 3,
    lr: float = 2e-4,
    rank: int = 16,
    alpha: int = 32,
    batch_size: int = 2,
    grad_accum: int = 8,
    max_length: int = 1024,
    val_fraction: float = 0.1,
    seed: int = 0,
) -> dict[str, Any]:
    import torch
    from peft import LoraConfig, get_peft_model
    from tqdm.auto import tqdm
    from transformers import AutoModelForCausalLM, AutoTokenizer

    torch.manual_seed(seed)
    rng = random.Random(seed)
    device = "cuda" if torch.cuda.is_available() else "cpu"
    tok = AutoTokenizer.from_pretrained(base)
    pad_id = tok.pad_token_id if tok.pad_token_id is not None else tok.eos_token_id

    lines = Path(data_path).read_text(encoding="utf-8").splitlines()
    convs = [json.loads(line)["messages"] for line in lines if line.strip()]
    rng.shuffle(convs)
    rows = [encode(tok, c, max_length) for c in convs]
    n_val = max(1, int(len(rows) * val_fraction))
    val, train = rows[:n_val], rows[n_val:]

    model = AutoModelForCausalLM.from_pretrained(base, dtype=torch.bfloat16).to(device)
    model.gradient_checkpointing_enable()
    model.enable_input_require_grads()
    config = LoraConfig(
        r=rank, lora_alpha=alpha, lora_dropout=0.05, target_modules=TARGET_MODULES,
        task_type="CAUSAL_LM",
    )  # fmt: skip
    model = get_peft_model(model, config)
    trainable = sum(p.numel() for p in model.parameters() if p.requires_grad)
    total = sum(p.numel() for p in model.parameters())

    opt = torch.optim.AdamW([p for p in model.parameters() if p.requires_grad], lr=lr)
    steps = epochs * math.ceil(len(train) / (batch_size * grad_accum))
    warmup = max(1, steps // 20)

    def lr_at(step: int) -> float:
        if step < warmup:
            return (step + 1) / warmup
        return 0.5 * (1 + math.cos(math.pi * (step - warmup) / max(1, steps - warmup)))

    sched = torch.optim.lr_scheduler.LambdaLR(opt, lr_at)
    history = [{"epoch": 0, "val_loss": _eval_loss(model, val, batch_size, pad_id, device)}]
    log.info("before training: val loss %.4f", history[0]["val_loss"])
    model.train()
    start = time.time()
    bar = tqdm(total=epochs * math.ceil(len(train) / batch_size), desc="LoRA", unit="batch")
    step = 0
    for epoch in range(1, epochs + 1):
        running, micro = 0.0, 0
        for ids, labels, mask in _batches(train, batch_size, pad_id, rng):
            with torch.autocast(device_type="cuda", dtype=torch.bfloat16, enabled=device == "cuda"):
                out = model(
                    input_ids=ids.to(device), attention_mask=mask.to(device),
                    labels=labels.to(device),
                )  # fmt: skip
            (out.loss / grad_accum).backward()
            running += float(out.loss)
            micro += 1
            bar.update(1)
            bar.set_postfix(epoch=f"{epoch}/{epochs}", loss=f"{float(out.loss):.3f}")
            if micro % grad_accum == 0:
                torch.nn.utils.clip_grad_norm_(model.parameters(), 1.0)
                opt.step()
                sched.step()
                opt.zero_grad()
                step += 1
        if micro % grad_accum:
            opt.step()
            sched.step()
            opt.zero_grad()
        val_loss = _eval_loss(model, val, batch_size, pad_id, device)
        history.append({"epoch": epoch, "train_loss": running / micro, "val_loss": val_loss})
        log.info("epoch %d: train %.4f val %.4f", epoch, running / micro, val_loss)

    out_dir = Path(out_dir)
    bar.close()
    model.save_pretrained(out_dir)
    stats = {
        "base_model": base,
        "train_examples": len(train),
        "val_examples": len(val),
        "epochs": epochs,
        "lr": lr,
        "rank": rank,
        "alpha": alpha,
        "trainable_params": trainable,
        "total_params": total,
        "minutes": round((time.time() - start) / 60, 1),
        "history": history,
    }
    (out_dir / "training_stats.json").write_text(json.dumps(stats, indent=2))
    return stats
