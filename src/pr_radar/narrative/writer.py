"""Generate, check and store the weekly brief."""

from __future__ import annotations

import json
import logging
from collections.abc import Callable
from dataclasses import asdict, dataclass, field
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from .checks import CheckResult, check_brief
from .facts import fact_sheet
from .prompt import messages, revision

log = logging.getLogger(__name__)

DEFAULT_MODEL = "Qwen/Qwen3-1.7B"
# (messages, sample) -> generated text
Generate = Callable[[list[dict[str, str]], bool], str]


@dataclass
class Brief:
    text: str
    model: str
    published: bool
    errors: list[str]
    style: list[str]
    attempts: int
    facts: dict[str, Any]
    drafts: list[dict[str, Any]] = field(default_factory=list)  # every attempt + its errors
    created_at: str = field(default_factory=lambda: datetime.now(UTC).isoformat(timespec="seconds"))


class LocalLLM:
    """A small instruct model run with transformers (GPU if available).

    `adapter` loads a LoRA adapter trained with `pr-radar brief-train`.
    """

    def __init__(
        self,
        name: str = DEFAULT_MODEL,
        adapter: str | None = None,
        max_new_tokens: int = 320,
        load_4bit: bool = False,
    ):
        import torch
        from transformers import AutoModelForCausalLM, AutoTokenizer

        self.name = name
        self.max_new_tokens = max_new_tokens
        self.device = "cuda" if torch.cuda.is_available() else "cpu"
        dtype = torch.bfloat16 if self.device == "cuda" else torch.float32
        self.tok = AutoTokenizer.from_pretrained(name)
        self.tok.padding_side = "left"
        if load_4bit:  # larger teacher/judge models on an 8 GB GPU
            from transformers import BitsAndBytesConfig

            quant = BitsAndBytesConfig(
                load_in_4bit=True, bnb_4bit_quant_type="nf4", bnb_4bit_compute_dtype=dtype
            )
            model = AutoModelForCausalLM.from_pretrained(
                name, quantization_config=quant, device_map=self.device
            )
        else:
            model = AutoModelForCausalLM.from_pretrained(name, dtype=dtype).to(self.device)
        if adapter:
            from peft import PeftModel

            model = PeftModel.from_pretrained(model, adapter).merge_and_unload()
        self.model = model.eval()

    def __call__(self, msgs: list[dict[str, str]], sample: bool) -> str:
        return self.batch([msgs], sample)[0]

    def batch(
        self, convs: list[list[dict[str, str]]], sample: bool, temperature: float = 0.7
    ) -> list[str]:
        import torch

        prompts = [
            self.tok.apply_chat_template(
                m, tokenize=False, add_generation_prompt=True, enable_thinking=False
            )
            for m in convs
        ]
        inputs = self.tok(prompts, return_tensors="pt", padding=True).to(self.device)
        opts: dict[str, Any] = {"max_new_tokens": self.max_new_tokens, "do_sample": sample}
        if sample:
            opts.update(temperature=temperature, top_p=0.9, top_k=50)
        with torch.no_grad():
            out = self.model.generate(**inputs, **opts, pad_token_id=self.tok.eos_token_id)
        new = out[:, inputs["input_ids"].shape[1] :]
        return [t.strip() for t in self.tok.batch_decode(new, skip_special_tokens=True)]


def write_brief(
    facts: dict[str, Any], generate: Generate, model: str, tries: int = 4, few_shot: bool = True
) -> Brief:
    """Draft, check, and revise with the failed checks as feedback.

    Even attempts revise the best draft so far; odd retries sample a fresh draft
    in case the model is stuck. The brief is published only if it passes every
    error check.
    """
    sheet = fact_sheet(facts)
    msgs = messages(facts["primary"], sheet, example=few_shot)
    best: tuple[str, CheckResult] | None = None
    attempts = 0
    drafts: list[dict[str, Any]] = []
    for i in range(tries):
        attempts += 1
        if best is None or i % 2 == 0:
            prompt = msgs if best is None else revision(msgs, best[0], best[1])
            text = generate(prompt, False)
        else:
            text = generate(msgs, True)
        res = check_brief(text, sheet, facts)
        drafts.append({"text": text, "errors": res.errors, "style": res.style})
        log.info("brief attempt %d: %d errors, %d style", i + 1, len(res.errors), len(res.style))
        if best is None or res.score < best[1].score:
            best = (text, res)
        if res.ok and not res.style:
            break
    assert best is not None
    text, res = best
    return Brief(text, model, res.ok, res.errors, res.style, attempts, facts, drafts)


def brief_path(directory: str | Path, facts: dict[str, Any]) -> Path:
    return Path(directory) / f"brief-{facts['start']}_{facts['end']}.json"


def save_brief(brief: Brief, directory: str | Path) -> Path:
    path = brief_path(directory, brief.facts)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(asdict(brief), ensure_ascii=False, indent=2), encoding="utf-8")
    return path


def load_brief(directory: str | Path, start: str, end: str) -> Brief | None:
    path = Path(directory) / f"brief-{start}_{end}.json"
    if not path.exists():
        return None
    return Brief(**json.loads(path.read_text(encoding="utf-8")))
