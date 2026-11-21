"""Draw the brief-model comparison for the README (light and dark PNGs).

    python scripts/plot_brief_results.py

Reads the judged result files in results/ and re-checks each first draft with
the current checks, so the chart always matches scripts/rescore_briefs.py.
"""

from __future__ import annotations

import json
from pathlib import Path

import matplotlib.pyplot as plt

from pr_radar.narrative.checks import check_brief

MODELS = [
    ("Qwen3-1.7B, example in prompt", "brief_eval_Qwen3-1.7B.json", False),
    ("+ LoRA on its own outputs", "brief_eval_lora-self-distilled.json", False),
    ("+ LoRA on Qwen3-4B outputs (shipped)", "brief_eval_brief-lora-qwen3-1.7b.json", True),
    ("Qwen3-4B teacher, example in prompt", "brief_eval_Qwen3-4B-Instruct-2507.json", False),
]
THEMES = {
    "light": {"bg": "#fcfcfb", "ink": "#0b0b0b", "ink2": "#52514e", "muted": "#898781",
              "main": "#2a78d6", "other": "#c9c7c0"},
    "dark": {"bg": "#1a1a19", "ink": "#f0efec", "ink2": "#c3c2b7", "muted": "#898781",
             "main": "#3987e5", "other": "#4a4945"},
}  # fmt: skip


def scores() -> list[tuple[str, int, float, bool]]:
    rows = []
    for label, name, shipped in MODELS:
        r = json.loads(Path("results", name).read_text(encoding="utf-8"))
        passed = sum(
            check_brief(s["drafts"][0]["text"], s["sheet"], s["facts"]).ok for s in r["samples"]
        )
        rows.append((label, passed, r["judge_mean"], shipped))
    return rows


def draw(rows, theme: str, out: Path) -> None:
    c = THEMES[theme]
    fig, axes = plt.subplots(1, 2, figsize=(10, 3.1), dpi=150, facecolor=c["bg"])
    panels = [
        ("First drafts that pass every check (of 21)", 1, 21, "{:.0f}"),
        ("LLM judge, mean score (1–5)", 2, 5, "{:.2f}"),
    ]
    labels = [r[0] for r in rows][::-1]
    for ax, (title, col, xmax, fmt) in zip(axes, panels, strict=True):
        values = [r[col] for r in rows][::-1]
        colors = [c["main"] if r[3] else c["other"] for r in rows][::-1]
        ax.set_facecolor(c["bg"])
        ax.barh(range(len(values)), values, height=0.5, color=colors)
        for y, v in enumerate(values):
            ax.text(v + xmax * 0.015, y, fmt.format(v), va="center", fontsize=9, color=c["ink"])
        ax.set_xlim(0, xmax * 1.08)
        ax.set_title(title, loc="left", fontsize=10, color=c["ink"], pad=8)
        ax.set_yticks(range(len(labels)))
        ax.set_yticklabels(labels if ax is axes[0] else [], fontsize=9, color=c["ink2"])
        ax.tick_params(axis="x", colors=c["muted"], labelsize=8, length=0)
        ax.tick_params(axis="y", length=0)
        for side in ("top", "right", "left"):
            ax.spines[side].set_visible(False)
        ax.spines["bottom"].set_color(c["muted"])
        ax.grid(axis="x", color=c["muted"], alpha=0.25, linewidth=0.6)
        ax.set_axisbelow(True)
    fig.text(0.01, 0.01, "21 held-out weeks. Judge: Qwen3-4B with a rubric.",
             fontsize=8, color=c["muted"])  # fmt: skip
    fig.tight_layout(rect=(0, 0.05, 1, 1))
    fig.savefig(out, facecolor=c["bg"])
    plt.close(fig)


if __name__ == "__main__":
    rows = scores()
    Path("docs/img").mkdir(parents=True, exist_ok=True)
    for theme in THEMES:
        draw(rows, theme, Path(f"docs/img/brief-results-{theme}.png"))
    print(rows)
