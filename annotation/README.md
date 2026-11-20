# FOREO-domain DimABSA evaluation set (v1)

A small, in-domain test set for PR Radar's aspect-level sentiment: **139 news headlines,
186 aspects**, about FOREO and its competitors (NuFACE, CurrentBody, Therabody, PMD,
Solawave), in 10 languages, each aspect with a continuous **valence** and **arousal**
score on DimABSA's 1.00–9.00 scale. Its job is to measure how well a model trained on the
official DimABSA data (restaurants, laptops, hotels, finance) transfers to beauty-tech
news.

**Provenance: LLM pre-annotated, human-verified.** Claude (claude-opus-5-5) proposed every
label (`*.silver.jsonl`); a human reviewer accepts, fixes or skips each item in the review
tool (`*.reviewed.jsonl`). Only the reviewed file is the evaluation set; the silver file
is kept so LLM-vs-human agreement can be reported.

## Format followed

Source: SemEval-2026 Task 3, Track A (DimABSA), official repository and data
<https://github.com/DimABSA/DimABSA2026> (README, `task-dataset/track_a/`; checked
2026-11-20); dataset paper <https://arxiv.org/abs/2601.23022>.

What we copy from DimABSA:

- JSONL, one sentence per line, keys `ID`, `Text`, and for Subtask 3 (DimASQP)
  `Quadruplet: [{"Aspect", "Category", "Opinion", "VA"}]`. Subtask 1 (DimASR) uses
  `Aspect_VA: [{"Aspect", "VA"}]`, Subtask 2 (DimASTE) `Triplet: [{"Aspect", "Opinion", "VA"}]`.
- `VA` is a string `"V#A"` with two decimals, e.g. `"6.75#6.38"`; both in [1.00, 9.00].
  Valence 1 = extremely negative, 5 = neutral, 9 = extremely positive; arousal 1 = very
  low, 5 = medium, 9 = very high intensity.
- `Aspect` and `Opinion` are verbatim, case-sensitive spans of `Text`; an implicit
  aspect/opinion is the string `"NULL"` (as in the ACOS-based training files; the official
  test sets drop implicit aspects, and our Subtask-1 export does too).
- `Category` is `ENTITY#ATTRIBUTE` in upper case. DimABSA has no beauty-tech domain, so we
  define one in the same SemEval-2016 style (see `dimabsa_format.py`):
  entities `BRAND`, `PRODUCT`; attributes `GENERAL`, `PRICES`, `QUALITY`, `PERFORMANCE`,
  `DESIGN_FEATURES`, `USABILITY`, `POPULARITY`, `SAFETY`, `BUSINESS`.
- No duplicate `(Aspect, Category, Opinion)` tuple per sentence (the official scorer
  invalidates those).

What we add (extra keys; the official scorer ignores them, `export` strips them):

| key | where | meaning |
|---|---|---|
| `Brand` | quadruplet | `foreo` … `solawave`, `other` (named, untracked brand/retailer), `generic` (product category), `unknown` (product whose brand the headline hides) |
| `BrandInText` | quadruplet | `true` if the tracked brand is named in the headline, `false` if it comes from the article (search query); `null` for non-tracked |
| `Confidence` | quadruplet and record | `high` / `low` (record is `low` if any aspect is) |
| `Rationale` | record | one line from the first annotator |
| `Language`, `Meta` | record | language code; article id, url, outlet, country, tags, date, cluster |
| `Annotator`, `Status` | record | `llm:claude-opus-5-5`; `silver` → `accepted` / `fixed` / `skipped` |
| `SilverQuadruplet`, `Reviewer`, `ReviewNote`, `ReviewedAt` | reviewed file | original proposal and review metadata |

Example (silver):

```json
{"ID": "foreo_v1_073", "Text": "Foreo Luna 5 LED elimina el 99% de la suciedad en un minuto", "Language": "es",
 "Quadruplet": [{"Aspect": "Foreo Luna 5 LED", "Category": "PRODUCT#PERFORMANCE",
   "Opinion": "elimina el 99% de la suciedad en un minuto", "VA": "7.75#6.75",
   "Brand": "foreo", "BrandInText": true, "Confidence": "high"}],
 "Rationale": "Spanish efficacy claim (99% of dirt in a minute): positive, punchy.",
 "Confidence": "high", "Annotator": "llm:claude-opus-5-5", "Status": "silver", "Meta": {...}}
```

## Files

| path | what |
|---|---|
| `annotation/build_candidates.py` | selects the headlines (read-only on the DuckDB files) |
| `annotation/dimabsa_format.py` | schema, validation, export to official Subtask 1/2/3 files |
| `annotation/review_app.py` | Streamlit review tool |
| `annotation/GUIDELINES.md` | annotation guidelines, Turkish + English, with anchors |
| `data/annotations/foreo_domain_v1.candidates.jsonl` | selected headlines + metadata |
| `data/annotations/foreo_domain_v1.silver.jsonl` | Claude's pre-labels |
| `data/annotations/foreo_domain_v1.reviewed.jsonl` | human-reviewed labels (created by the tool) |
| `data/annotations/pool_config.yaml` | `config/brands.yaml` with `lookback_days: 30` |

## How it was built

1. **Candidate pool.** The main database held 83 articles (77 stories) from one week, too
   few for ~150 items, so a wider 30-day pool was collected into a *separate* file with the
   project's own collector (the main database and archive are untouched; `--archive ""`
   writes no Parquet):

   ```bash
   .venv/Scripts/python -m pr_radar --config data/annotations/pool_config.yaml --db data/annotations/candidate_pool.duckdb --archive "" collect
   ```

2. **Selection.** `build_candidates.py` reads `data/pr_radar.duckdb` and the pool
   read-only, keeps one headline per story (same `cluster_id`, character-4-gram Jaccard
   ≥ 0.6, or one headline ≥ 60 % contained in another, which catches press-release
   rewrites), scores each for evaluative content (multilingual cue words such as
   *best / worth / deal / % off / chollo / migliori / bäst*, topic, brand named in the
   headline) and picks greedily with a bonus for under-represented brands, languages and
   topics. 139 stories passed the filters, so the set has 139 items rather than 150.

   ```bash
   .venv/Scripts/python annotation/build_candidates.py
   ```

   The selection is deterministic for the same input files, but the silver labels are
   keyed to the `foreo_v1_NNN` IDs: re-running it after a new collection renumbers the
   candidates, so build a `v2` file instead of overwriting `v1`.

3. **Pre-labelling.** Claude labelled every candidate as first annotator (aspects,
   opinions, category, brand, V/A, rationale, confidence); every span was validated to be
   verbatim in the headline.
4. **Review.** A human checks each item (below).

## Reviewing (≈ 45 minutes)

```bash
.venv/Scripts/python -m streamlit run annotation/review_app.py
```

Read `GUIDELINES.md` first (5 minutes). The tool shows one headline at a time,
low-confidence items first, with Claude's labels and rationale, sliders to adjust, and
**Accept / Save fix / Skip / Back** buttons and a progress bar. Every click autosaves to
`data/annotations/foreo_domain_v1.reviewed.jsonl`; close it any time and resume later.
`-- --reviewed other.jsonl` after the command writes somewhere else (for trying it out).

## After review

```bash
.venv/Scripts/python annotation/dimabsa_format.py validate data/annotations/foreo_domain_v1.reviewed.jsonl
.venv/Scripts/python annotation/dimabsa_format.py export data/annotations/foreo_domain_v1.reviewed.jsonl --out data/annotations/export
```

`export` writes `foreo_domain_v1_task1.jsonl` (DimASR), `_task2` (DimASTE) and `_task3`
(DimASQP) in the official format, without skipped items. Score a model with the
official metrics: RMSE over V and A for Subtask 1, continuous F1 (cF1) for 2 and 3
(<https://github.com/DimABSA/DimABSA2026/tree/main/evaluation_script>).

## Known limitations

- Collected in Oct–Nov 2026, i.e. the Black Friday season: labels skew positive
  (silver mean valence 6.74; only 9 of 186 aspects below 4.5). Report results per
  valence band, not only overall RMSE.
- Mostly English (98 of 139); other languages have 1–11 items each, enough for a sanity
  check, not for per-language scores.
- Single human reviewer seeded by an LLM: expect some anchoring toward the proposed
  values. DimABSA gold values average several annotators; a second reviewer on a sample
  would allow an agreement estimate.
- Headlines only. Many aspects are product categories (`generic`) because list articles
  rarely name the brand in the headline.
