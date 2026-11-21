"""Command line interface: pr-radar collect | report | brief | stats | export-web | dashboard."""

from __future__ import annotations

import argparse
import logging
import os
import subprocess
import sys
from datetime import datetime
from pathlib import Path

from . import analytics as an
from .config import Settings, load_config
from .pipeline import run_collection
from .report import default_window, write_report
from .storage import Store
from .web_export import write_web_data

DEFAULT_CONFIG = "config/brands.yaml"
DEFAULT_DB = "data/pr_radar.duckdb"
DEFAULT_ARCHIVE = "data/archive"


def _date(value: str) -> datetime:
    return datetime.strptime(value, "%Y-%m-%d")


def cmd_collect(args: argparse.Namespace) -> int:
    settings = load_config(args.config)
    sources = tuple(s for s in ("google_news", "gdelt") if s not in args.skip)
    store = Store(args.db)
    try:
        stats = run_collection(settings, store, archive_dir=args.archive, sources=sources)
    finally:
        store.close()
    print(
        f"collected={stats.collected} unique={stats.unique} inserted={stats.inserted} "
        f"updated={stats.updated} errors={stats.errors} by_source={stats.by_collector}"
    )
    if stats.archive_file:
        print(f"archive: {stats.archive_file}")
    return 1 if stats.collected == 0 and stats.errors else 0


def _open(args: argparse.Namespace, settings: Settings) -> Store:
    store = Store(args.db)
    store.bootstrap_from_archive(args.archive)
    store.refresh_tags(settings)
    return store


def cmd_report(args: argparse.Namespace) -> int:
    settings = load_config(args.config)
    window = default_window(args.days or settings.lookback_days, args.end)
    store = _open(args, settings)
    try:
        path = write_report(store.con, settings, window, args.out)
    finally:
        store.close()
    print(f"report: {path}")
    if args.publish:
        publish = Path(args.publish)
        publish.parent.mkdir(parents=True, exist_ok=True)
        publish.write_text(path.read_text(encoding="utf-8"), encoding="utf-8")
        print(f"published: {publish}")
    return 0


def cmd_stats(args: argparse.Namespace) -> int:
    settings = load_config(args.config)
    window = default_window(args.days or settings.lookback_days, args.end)
    store = _open(args, settings)
    try:
        df = an.period_comparison(store.con, window)
        print(
            f"{window.start:%Y-%m-%d} .. {window.end:%Y-%m-%d} ({store.count()} articles in DB)\n"
        )
        print(df.to_string(index=False) if not df.empty else "No data.")
        print()
        for line in an.insights(
            store.con, window, settings.primary_brand, settings.brand_names, settings.lookback_days
        ):
            print(f"- {line}")
    finally:
        store.close()
    return 0


def cmd_export_web(args: argparse.Namespace) -> int:
    settings = load_config(args.config)
    # Export only reads, so open an existing database read-only (safe while it is in use).
    store = Store(args.db, read_only=True) if Path(args.db).exists() else _open(args, settings)
    try:
        path = write_web_data(store.con, settings, args.out, args.end)
    finally:
        store.close()
    print(f"web data: {path}")
    return 0


def cmd_dashboard(args: argparse.Namespace) -> int:
    app = Path(__file__).with_name("dashboard.py")
    env = {**os.environ, "PR_RADAR_DB": args.db, "PR_RADAR_CONFIG": args.config}
    return subprocess.call([sys.executable, "-m", "streamlit", "run", str(app)], env=env)


DEFAULT_SENTIMENT_MODEL = "models/dimasr-xlmr-base-news"


def cmd_score_sentiment(args: argparse.Namespace) -> int:
    from .sentiment.scoring import score_new_mentions

    settings = load_config(args.config)
    if not Path(args.model_dir).exists():
        print(f"No model at {args.model_dir}. Train one with: pr-radar dimabsa-train")
        return 1
    store = _open(args, settings)
    try:
        n = score_new_mentions(store, settings, args.model_dir)
    finally:
        store.close()
    print(f"scored {n} headline brand mentions")
    return 0


DEFAULT_BRIEFS = "data/briefs"


def cmd_brief(args: argparse.Namespace) -> int:
    from .narrative.facts import weekly_facts
    from .narrative.writer import LocalLLM, save_brief, write_brief

    settings = load_config(args.config)
    window = default_window(args.days or settings.lookback_days, args.end)
    store = _open(args, settings)
    try:
        facts = weekly_facts(store.con, settings, window)
    finally:
        store.close()
    llm = LocalLLM(args.model, adapter=args.adapter)
    name = f"{args.model} + LoRA" if args.adapter else args.model
    brief = write_brief(facts, llm, name, tries=args.tries, few_shot=not args.adapter)
    path = save_brief(brief, args.out)
    print(brief.text)
    print(f"\nattempts={brief.attempts} errors={brief.errors} style={brief.style}")
    print(f"{'published' if brief.published else 'NOT published (failed checks)'}: {path}")
    return 0 if brief.published else 1


def cmd_brief_eval(args: argparse.Namespace) -> int:
    from .narrative.evaluate import evaluate, synthetic_facts, write_results
    from .narrative.facts import weekly_facts
    from .narrative.writer import LocalLLM

    settings = load_config(args.config)
    primary = settings.brand_names[settings.primary_brand]
    competitors = [n for b, n in settings.brand_names.items() if b != settings.primary_brand]
    fact_sets = [synthetic_facts(primary, competitors, seed) for seed in range(args.weeks)]
    store = _open(args, settings)
    try:
        fact_sets.insert(0, weekly_facts(store.con, settings, default_window(7)))
    finally:
        store.close()
    llm = LocalLLM(args.model, adapter=args.adapter, load_4bit=args.load_4bit)
    name = args.adapter or args.model
    result = evaluate(fact_sets, llm, name, tries=args.tries, few_shot=not args.adapter)
    path = write_results(result, args.results)
    print(
        f"weeks={result['weeks']} first_attempt_pass={result['first_attempt_pass_rate']:.0%} "
        f"published_with_retries={result['published_rate_with_retries']:.0%} "
        f"mean_words={result['mean_words']:.0f}"
    )
    print(f"errors={result['error_counts']}")
    print(f"style={result['style_counts']}")
    print(f"-> {path}")
    return 0


BRIEF_SFT = "data/brief_sft/train.jsonl"
BRIEF_ADAPTER = "adapters/brief-lora-qwen3-1.7b"


def cmd_brief_distill(args: argparse.Namespace) -> int:
    import json

    from .narrative.distill import build_dataset, training_weeks
    from .narrative.writer import LocalLLM

    settings = load_config(args.config)
    weeks = training_weeks(list(settings.brand_names.values()), args.weeks, args.start)
    stats = build_dataset(
        LocalLLM(args.model, load_4bit=args.load_4bit),
        weeks,
        args.out,
        args.samples,
        weeks_per_batch=args.weeks_per_batch,
        append=args.start > 0,
    )
    Path(args.out).with_suffix(".stats.json").write_text(json.dumps(stats, indent=2))
    print(stats)
    return 0


BRIEF_TEACHER = "Qwen/Qwen3-4B-Instruct-2507"


def cmd_brief_judge(args: argparse.Namespace) -> int:
    from .narrative.judge import judge_results
    from .narrative.writer import LocalLLM

    llm = LocalLLM(args.model, load_4bit=True, max_new_tokens=80)
    for f in args.files:
        print(judge_results(f, llm))
    return 0


def cmd_brief_train(args: argparse.Namespace) -> int:
    from .narrative.lora import train_lora

    stats = train_lora(args.model, args.data, args.out, epochs=args.epochs, lr=args.lr)
    print(stats)
    return 0


DEFAULT_DIMABSA = "data/external/DimABSA2026"
DOMAIN_SET_REVIEWED = "data/annotations/foreo_domain_v1.reviewed.jsonl"
DOMAIN_SET_SILVER = "data/annotations/foreo_domain_v1.silver.jsonl"


def cmd_dimabsa_train(args: argparse.Namespace) -> int:
    from .sentiment.experiment import run_experiment

    domain_set = args.domain_set or next(
        (p for p in (DOMAIN_SET_REVIEWED, DOMAIN_SET_SILVER) if Path(p).exists()), None
    )
    results = run_experiment(
        data_root=args.data,
        model_dir=args.model_dir,
        results_dir=args.results,
        base_model=args.base_model,
        epochs=args.epochs,
        batch_size=args.batch_size,
        lr=args.lr,
        max_length=args.max_length,
        domain_set=domain_set,
        holdout_lang=args.holdout_lang,
    )
    for name, r in results["test"].items():
        print(
            f"{name:20} RMSE {r['model']['rmse_norm']:.3f} (baseline {r['baseline']['rmse_norm']:.3f})"
        )
    if results["domain_set"]:
        d = results["domain_set"]
        print(
            f"{'beauty-tech news':20} RMSE {d['model']['rmse_norm']:.3f} (baseline {d['baseline']['rmse_norm']:.3f})"
        )
    return 0


def cmd_dimabsa_adapt(args: argparse.Namespace) -> int:
    """Adapt the DimABSA model to news headlines: k-fold comparison, then a final model."""
    from .sentiment.data import load_domain_set
    from .sentiment.experiment import domain_cross_validation
    from .sentiment.model import VARegressor

    domain_set = args.domain_set or next(
        (p for p in (DOMAIN_SET_REVIEWED, DOMAIN_SET_SILVER) if Path(p).exists()), None
    )
    if domain_set is None:
        print("No labelled headline set found.")
        return 1
    results = domain_cross_validation(args.base_dir, domain_set, args.results, epochs=args.epochs)
    for name, sc in results["scores"].items():
        print(
            f"{name:12} RMSE {sc['rmse_norm']:.3f}  PCC V {sc['pcc_valence']:.2f}  A {sc['pcc_arousal']:.2f}"
        )
    examples = load_domain_set(domain_set)
    final = VARegressor.load(args.base_dir)
    final.fit(
        examples,
        {"train": examples},
        out_dir=None,
        epochs=args.epochs,
        batch_size=16,
        lr=1e-5,
        warmup=0.1,
    )
    final.save(args.out_dir)
    print(f"domain-adapted model: {args.out_dir}")
    return 0


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="pr-radar", description=__doc__)
    parser.add_argument("--config", default=DEFAULT_CONFIG)
    parser.add_argument("--db", default=DEFAULT_DB)
    parser.add_argument("--archive", default=DEFAULT_ARCHIVE)
    parser.add_argument("-v", "--verbose", action="store_true")
    sub = parser.add_subparsers(dest="command", required=True)

    p = sub.add_parser("collect", help="fetch coverage from Google News and GDELT")
    p.add_argument("--skip", nargs="*", default=[], choices=["google_news", "gdelt"])
    p.set_defaults(func=cmd_collect)

    for name, func, text in (
        ("report", cmd_report, "write the weekly HTML report"),
        ("stats", cmd_stats, "print share of voice and insights"),
    ):
        p = sub.add_parser(name, help=text)
        p.add_argument("--days", type=int, help="window length (default: lookback_days)")
        p.add_argument(
            "--end", type=_date, help="last day of the window, YYYY-MM-DD (default: today)"
        )
        if name == "report":
            p.add_argument("--out", default="reports")
            p.add_argument("--publish", help="also copy the report here, e.g. docs/index.html")
        p.set_defaults(func=func)

    p = sub.add_parser("export-web", help="write web/data.json for the static web dashboard")
    p.add_argument("--out", default="web", help="directory with index.html (default: web)")
    p.add_argument("--end", type=_date, help="last day of the windows, YYYY-MM-DD (default: today)")
    p.set_defaults(func=cmd_export_web)

    p = sub.add_parser("dimabsa-train", help="train + evaluate the DimABSA sentiment model")
    p.add_argument("--data", default=DEFAULT_DIMABSA, help="clone of DimABSA/DimABSA2026")
    p.add_argument("--base-model", default="xlm-roberta-base")
    p.add_argument("--model-dir", default="models/dimasr-xlmr-base")
    p.add_argument("--results", default="results")
    p.add_argument("--epochs", type=int, default=4)
    p.add_argument("--batch-size", type=int, default=32)
    p.add_argument("--lr", type=float, default=2e-5)
    p.add_argument("--max-length", type=int, default=160)
    p.add_argument("--domain-set", help="JSONL of labelled headlines (default: annotations)")
    p.add_argument("--holdout-lang", help="leave one language out to measure zero-shot transfer")
    p.set_defaults(func=cmd_dimabsa_train)

    p = sub.add_parser("dimabsa-adapt", help="adapt the sentiment model to news headlines")
    p.add_argument("--base-dir", default="models/dimasr-xlmr-base")
    p.add_argument("--out-dir", default=DEFAULT_SENTIMENT_MODEL)
    p.add_argument("--results", default="results")
    p.add_argument("--epochs", type=int, default=5)
    p.add_argument("--domain-set")
    p.set_defaults(func=cmd_dimabsa_adapt)

    p = sub.add_parser("score-sentiment", help="score headline brand mentions with the model")
    p.add_argument("--model-dir", default=DEFAULT_SENTIMENT_MODEL)
    p.set_defaults(func=cmd_score_sentiment)

    p = sub.add_parser("brief", help="write the weekly brief with a local LLM and check it")
    p.add_argument("--days", type=int, help="window length (default: lookback_days)")
    p.add_argument("--end", type=_date, help="last day of the window, YYYY-MM-DD")
    p.add_argument("--model", default="Qwen/Qwen3-1.7B", help="Hugging Face model id or path")
    p.add_argument("--tries", type=int, default=4)
    p.add_argument("--adapter", help="LoRA adapter dir; the prompt then has no example")
    p.add_argument("--out", default=DEFAULT_BRIEFS)
    p.set_defaults(func=cmd_brief)

    p = sub.add_parser("brief-eval", help="check rate of LLM briefs on real + synthetic weeks")
    p.add_argument("--model", default="Qwen/Qwen3-1.7B")
    p.add_argument("--weeks", type=int, default=40, help="number of synthetic weeks")
    p.add_argument("--tries", type=int, default=4)
    p.add_argument("--results", default="results")
    p.add_argument("--adapter", help="LoRA adapter dir; the prompt then has no example")
    p.add_argument("--load-4bit", action="store_true", help="for larger models")
    p.set_defaults(func=cmd_brief_eval)

    p = sub.add_parser("brief-judge", help="score the advice in brief-eval results with a judge")
    p.add_argument("files", nargs="+", help="results/brief_eval_*.json")
    p.add_argument("--model", default=BRIEF_TEACHER)
    p.set_defaults(func=cmd_brief_judge)

    p = sub.add_parser("brief-distill", help="sample briefs and keep those that pass the checks")
    p.add_argument("--model", default="Qwen/Qwen3-1.7B")
    p.add_argument("--weeks", type=int, default=500)
    p.add_argument("--samples", type=int, default=8, help="candidates per week")
    p.add_argument("--start", type=int, default=0, help="resume: first week index, appends")
    p.add_argument("--weeks-per-batch", type=int, default=2)
    p.add_argument("--load-4bit", action="store_true", help="for larger teacher models")
    p.add_argument("--out", default=BRIEF_SFT)
    p.set_defaults(func=cmd_brief_distill)

    p = sub.add_parser("brief-train", help="LoRA fine-tune on the distilled briefs")
    p.add_argument("--model", default="Qwen/Qwen3-1.7B")
    p.add_argument("--data", default=BRIEF_SFT)
    p.add_argument("--out", default=BRIEF_ADAPTER)
    p.add_argument("--epochs", type=int, default=3)
    p.add_argument("--lr", type=float, default=2e-4)
    p.set_defaults(func=cmd_brief_train)

    p = sub.add_parser("dashboard", help="open the Streamlit dashboard")
    p.set_defaults(func=cmd_dashboard)
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    logging.basicConfig(
        level=logging.INFO if args.verbose else logging.WARNING,
        format="%(asctime)s %(levelname)-7s %(name)s: %(message)s",
    )
    return args.func(args)


if __name__ == "__main__":
    raise SystemExit(main())
