# Rebuild the brief adapter and the comparison in results/ (about 2.5 hours on an 8 GB GPU).
$ErrorActionPreference = "Stop"
$py = ".\.venv\Scripts\python.exe"
$teacher = "Qwen/Qwen3-4B-Instruct-2507"
$adapter = "adapters/brief-lora-qwen3-1.7b"

# 1. The teacher writes 4 candidates per synthetic week; the best passing one is kept.
& $py -m pr_radar.cli brief-distill --model $teacher --load-4bit --weeks 250 --samples 4
# 2. Re-check with the current checks and prompt format.
& $py scripts/refilter_brief_sft.py
# 3. LoRA fine-tune of the 1.7B student.
& $py -m pr_radar.cli -v brief-train --out $adapter
# 4. Evaluate the student and the teacher on held-out weeks, then judge the first drafts.
& $py -m pr_radar.cli brief-eval --weeks 20 --tries 3 --adapter $adapter
& $py -m pr_radar.cli brief-eval --weeks 20 --tries 3 --model $teacher --load-4bit
& $py -m pr_radar.cli brief-judge results/brief_eval_brief-lora-qwen3-1.7b.json results/brief_eval_Qwen3-4B-Instruct-2507.json
& $py scripts/rescore_briefs.py (Get-ChildItem results/brief_eval_*.json)
