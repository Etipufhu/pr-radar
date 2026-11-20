# DimASR results: `xlm-roberta-base`

Trained 2026-11-20T14:58:30+00:00 on 36,435 aspect pairs (4 epochs, lr 2e-05, batch 32).

RMSE is the official normalised RMSE over (valence, arousal), lower is better. Baseline = always predict the training-set mean. PCC = Pearson correlation.

| Test set | Aspects | RMSE (model) | RMSE (baseline) | Error reduction | PCC valence | PCC arousal |
|---|---:|---:|---:|---:|---:|---:|
| eng_laptop | 1421 | **0.126** | 0.200 | 37% | 0.84 | 0.53 |
| eng_restaurant | 1504 | **0.122** | 0.210 | 42% | 0.85 | 0.59 |
| jpn_finance | 1302 | **0.086** | 0.149 | 42% | 0.79 | 0.37 |
| jpn_hotel | 1092 | **0.075** | 0.137 | 45% | 0.91 | 0.73 |
| rus_restaurant | 1637 | **0.155** | 0.202 | 23% | 0.86 | 0.56 |
| tat_restaurant | 1637 | **0.189** | 0.202 | 6% | 0.67 | 0.40 |
| ukr_restaurant | 1637 | **0.161** | 0.202 | 21% | 0.84 | 0.54 |
| zho_finance | 2354 | **0.050** | 0.107 | 53% | 0.86 | 0.59 |
| zho_laptop | 1673 | **0.072** | 0.128 | 44% | 0.87 | 0.70 |
| zho_restaurant | 1929 | **0.088** | 0.134 | 34% | 0.85 | 0.58 |
| beauty-tech news headlines (PR Radar) | 185 | **0.171** | 0.140 | -23% | 0.46 | 0.35 |

The beauty-tech set was pre-annotated by an LLM and is being verified by a human; treat it as indicative until the reviewed version replaces it.

## Training history

| Epoch | Train loss | Dev mean RMSE | Time |
|---:|---:|---:|---:|
| 1 | 0.0340 | 0.1040 | 443s |
| 2 | 0.0102 | 0.1047 | 168s |
| 3 | 0.0075 | 0.1114 | 169s |
| 4 | 0.0062 | 0.1036 | 168s |
