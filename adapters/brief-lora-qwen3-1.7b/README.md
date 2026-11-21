---
base_model: Qwen/Qwen3-1.7B
library_name: peft
license: apache-2.0
language: en
tags: [lora, pr, media-monitoring, distillation]
---

# brief-lora-qwen3-1.7b

LoRA adapter for Qwen3-1.7B that writes PR Radar's weekly brief: a two or three sentence summary of a brand's media coverage and two to four actions for its PR team, written only from a fact sheet of numbers.

## Use

```bash
pr-radar brief --adapter adapters/brief-lora-qwen3-1.7b
```

The adapter expects the system prompt and fact sheet built by `pr_radar.narrative` (`messages(brand, sheet, example=False)`), with Qwen3's thinking mode off. Every output should go through `check_brief`; PR Radar publishes a brief only if it passes.

## Training

- Data: 154 briefs written by Qwen3-4B-Instruct-2507 (4-bit) for synthetic weeks, each the best of 4 candidates that passed every check (`data/brief_sft/train.jsonl`). The primary brand is picked at random per week.
- LoRA rank 16, alpha 32, dropout 0.05, on q/k/v/o and gate/up/down projections. 17.4M trainable parameters.
- 3 epochs, lr 2e-4 with warmup and cosine decay, batch 2 with 8 gradient accumulation steps, loss on the brief only. 139 training and 15 validation examples; validation loss 2.94 → 0.43. See `training_stats.json`.
- About 10 minutes on an RTX 5070 Laptop GPU (8 GB), bf16.

## Evaluation

21 held-out weeks (the real week plus 20 synthetic weeks with seeds not used in training).

| | First draft passes every check | Published within 3 attempts | LLM judge mean (1–5) |
|---|---:|---:|---:|
| Qwen3-1.7B, worked example in prompt | 1 of 21 | – | 3.52 |
| This adapter, no example | 11 of 21 | 86% | 4.19 |
| Qwen3-4B-Instruct-2507 (teacher) | 10 of 21 | 81% | 4.52 |

The judge is Qwen3-4B-Instruct-2507 with a rubric, the same model as the teacher, so it may favour the teacher's style.

## Limitations

- It overuses "re-pitch", including for outlets that never covered the brand (6 of 21 first drafts in the evaluation). Most of the training briefs contain a re-pitch action.
- It sometimes names a country or outlet that is not in the fact sheet, which the checks catch, or a vague target ("outlets that covered FOREO before"), which they do not.
- Trained on synthetic weeks for six beauty-tech brands in English. Other brands should work, since the brand is part of the prompt, but other industries or languages were not tested.
- It summarises numbers; it does not know why coverage changed. A person should read the brief before it is shared.
