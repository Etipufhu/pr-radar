"""Select ~150 headlines for the FOREO-domain DimABSA evaluation set.

Reads one or more PR Radar DuckDB files read-only, drops near-duplicate stories,
scores each headline for how much it *evaluates* something (a product, a price or
deal, a feature, the brand) and picks a set balanced across brands, languages and
topics. Output: one JSON object per line with the article metadata.

    .venv/Scripts/python annotation/build_candidates.py
    .venv/Scripts/python annotation/build_candidates.py --db data/pr_radar.duckdb --n 150

The default sources are the main database plus, if present, the wider 30-day pool
in data/annotations/candidate_pool.duckdb (see annotation/README.md).
"""

from __future__ import annotations

import argparse
import json
import re
from collections import Counter
from collections.abc import Iterable, Sequence
from dataclasses import asdict, dataclass, field
from pathlib import Path

from pr_radar.config import load_config
from pr_radar.dedup import DEFAULT_THRESHOLD, jaccard, shingles
from pr_radar.matching import BrandMatcher
from pr_radar.storage import Store

ROOT = Path(__file__).resolve().parents[1]
DEFAULT_DBS = (
    ROOT / "data" / "pr_radar.duckdb",
    ROOT / "data" / "annotations" / "candidate_pool.duckdb",
)
DEFAULT_CONFIG = ROOT / "config" / "brands.yaml"
DEFAULT_OUT = ROOT / "data" / "annotations" / "foreo_domain_v1.candidates.jsonl"

# Words that signal an opinion, a judgement or a price/deal claim. Prefix match at a
# word start, case-insensitive, same convention as config/brands.yaml topics.
EVALUATIVE_CUES = tuple(
    cue.strip()
    for line in """
# en
best, worth, love, loved, favorite, favourite, must, game-changer
game changer, obsessed, amazing, incredible, genius, impressive, top
review, tested, i tried, honest, verdict, worst, disappoint, overrated
underrated, scam, recall, lawsuit, complain, problem, fail, cheap
cheapest, lowest, record low, deal, % off, save, sale, discount
bargain, steal, splurge, pricey, expensive, affordable, budget, luxury
award, winner, results, effective, works, really work, glow, younger
wrinkle, transform, viral, sold out, hype, fan, skip, avoid, misleading, warning
# es / it / fr / de / pl / pt / tr / sv / ja
mejor, oferta, chollo, rebaja, descuento, precio, barat, probado
merece, favorit, migliore, migliori, efficace, sconto, offerta, prezzo, meilleur, promo
prix, soldes, avis, beste, rabatt, angebot, test, günstig, preis
najlep, promocja, cena, taniej, melhor, desconto, preço, en iyi
indirim, fiyat, bästa, おすすめ, セール, 最安, レビュー, 人気
""".splitlines()
    if not line.startswith("#")
    for cue in line.split(",")
    if cue.strip()
)
_CUE_RE = re.compile(
    r"(?<!\w)(" + "|".join(re.escape(c) for c in EVALUATIVE_CUES) + r")", re.IGNORECASE
)
# Topics whose headlines usually carry an evaluation (deal, review, award) score higher
# than plain business news.
TOPIC_WEIGHT = {
    "reviews": 2.0,
    "deals_pricing": 1.5,
    "awards": 1.5,
    "gift_guides": 1.0,
    "launch": 1.0,
    "skin_science": 1.0,
    "sustainability": 1.0,
    "business": 0.3,
}


@dataclass
class Candidate:
    id: str
    title: str
    url: str | None
    source_domain: str | None
    language: str | None
    country: str | None
    brands: list[str]
    topics: list[str]
    published_at: str
    cluster_id: str | None
    source_db: str
    brands_in_title: list[str] = field(default_factory=list)
    evaluative_score: float = 0.0
    cues: list[str] = field(default_factory=list)


def load_articles(db_paths: Iterable[Path], matcher: BrandMatcher | None = None) -> list[Candidate]:
    """All articles from the given databases (missing files are skipped)."""
    rows: list[Candidate] = []
    for path in db_paths:
        if not Path(path).exists():
            continue
        store = Store(path, read_only=True)
        try:
            result = store.con.execute(
                """SELECT id, title, url, source_domain, language, country, brands, topics,
                          strftime(published_at, '%Y-%m-%dT%H:%M:%S'), cluster_id
                   FROM articles ORDER BY published_at DESC, id"""
            ).fetchall()
        finally:
            store.close()
        for r in result:
            rows.append(
                Candidate(
                    id=r[0],
                    title=r[1],
                    url=r[2],
                    source_domain=r[3],
                    language=r[4],
                    country=r[5],
                    brands=sorted(r[6] or []),
                    topics=sorted(r[7] or []),
                    published_at=r[8],
                    cluster_id=r[9],
                    source_db=Path(path).name,
                    brands_in_title=matcher.match(r[1]) if matcher else [],
                )
            )
    return rows


def score(c: Candidate) -> float:
    """Higher = more likely to contain an aspect with a non-neutral evaluation."""
    cues = sorted({m.group(1).lower() for m in _CUE_RE.finditer(c.title)})
    c.cues = cues
    s = min(len(cues), 3) * 1.0
    s += max((TOPIC_WEIGHT.get(t, 0.5) for t in c.topics), default=0.0)
    if c.brands_in_title:
        s += 1.5  # the aspect can be tied to a tracked brand from the text alone
    n_words = len(c.title.split())
    if n_words < 5 and c.language not in ("ja", "zh"):
        s -= 1.0  # too short to say much
    if "?" in c.title or "!" in c.title:
        s += 0.3
    c.evaluative_score = round(s, 2)
    return c.evaluative_score


def containment(a: frozenset[str], b: frozenset[str]) -> float:
    """Share of the shorter headline's shingles found in the longer one."""
    if not a or not b:
        return 0.0
    return len(a & b) / min(len(a), len(b))


def dedupe(
    cands: Sequence[Candidate],
    threshold: float = DEFAULT_THRESHOLD,
    contain: float = 0.6,
) -> list[Candidate]:
    """One headline per story: same (db, cluster_id), near-identical text across DBs,
    or one headline mostly contained in another (press-release rewrites such as
    "X Acquires Y's Technology" / "X Acquires Y's Technology, Expands ...").

    Keeps the first occurrence, so pass candidates ordered best-first.
    """
    seen_clusters: set[tuple[str, str]] = set()
    seen_ids: set[str] = set()
    kept: list[tuple[Candidate, frozenset[str]]] = []
    for c in cands:
        if c.id in seen_ids:
            continue
        key = (c.source_db, c.cluster_id or c.id)
        if key in seen_clusters:
            continue
        sig = shingles(c.title)
        if any(
            jaccard(sig, other) >= threshold or containment(sig, other) >= contain
            for _, other in kept
        ):
            continue
        seen_ids.add(c.id)
        seen_clusters.add(key)
        kept.append((c, sig))
    return [c for c, _ in kept]


def select(cands: Sequence[Candidate], n: int = 150, min_score: float = 1.0) -> list[Candidate]:
    """Greedy pick: evaluative score plus a bonus for under-represented brand/lang/topic.

    Headlines scoring below min_score (no cue, no useful topic, no brand in the text)
    are dropped first: they rarely contain an aspect worth labelling.
    """
    pool = sorted(cands, key=lambda c: (-score(c), c.id))
    pool = [c for c in dedupe(pool) if c.evaluative_score >= min_score]
    picked: list[Candidate] = []
    by_brand: Counter[str] = Counter()
    by_lang: Counter[str] = Counter()
    by_topic: Counter[str] = Counter()

    def gain(c: Candidate) -> float:
        brand = min((by_brand[b] for b in c.brands), default=0)
        topic = min((by_topic[t] for t in c.topics), default=by_topic["(none)"])
        lang = by_lang[c.language or "?"]
        return c.evaluative_score + 2.0 / (1 + brand) + 2.0 / (1 + lang) + 1.0 / (1 + topic)

    while pool and len(picked) < n:
        best = max(pool, key=lambda c: (gain(c), c.id))
        pool.remove(best)
        picked.append(best)
        by_brand.update(best.brands)
        by_lang[best.language or "?"] += 1
        by_topic.update(best.topics or ["(none)"])
    return picked


def write_jsonl(cands: Iterable[Candidate], out: Path) -> int:
    out.parent.mkdir(parents=True, exist_ok=True)
    n = 0
    with out.open("w", encoding="utf-8", newline="\n") as f:
        for i, c in enumerate(cands, 1):
            rec = {"ID": f"foreo_v1_{i:03d}", **asdict(c)}
            f.write(json.dumps(rec, ensure_ascii=False) + "\n")
            n += 1
    return n


def summary(cands: Sequence[Candidate]) -> str:
    def fmt(counter: Counter[str]) -> str:
        return ", ".join(f"{k}={v}" for k, v in counter.most_common())

    return "\n".join(
        [
            f"selected: {len(cands)}",
            "brands:    " + fmt(Counter(b for c in cands for b in c.brands)),
            "languages: " + fmt(Counter(c.language or "?" for c in cands)),
            "topics:    " + fmt(Counter(t for c in cands for t in (c.topics or ["(none)"]))),
            f"brand named in title: {sum(bool(c.brands_in_title) for c in cands)}",
            "sources:   " + fmt(Counter(c.source_db for c in cands)),
        ]
    )


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    p.add_argument("--db", action="append", type=Path, help="DuckDB file (repeatable)")
    p.add_argument("--config", type=Path, default=DEFAULT_CONFIG)
    p.add_argument("--n", type=int, default=150)
    p.add_argument("--out", type=Path, default=DEFAULT_OUT)
    args = p.parse_args(argv)

    matcher = BrandMatcher(load_config(args.config).brands)
    cands = select(load_articles(args.db or DEFAULT_DBS, matcher), args.n)
    write_jsonl(cands, args.out)
    print(summary(cands))
    print(f"wrote {args.out}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
