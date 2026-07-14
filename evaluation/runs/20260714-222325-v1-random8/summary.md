# Dynamic Route Benchmark V1 - Random 8 Validation

- Run: `20260714-222325-v1-random8`
- Sampling: fixed seed `20260714`, 8 cases sampled from the 24 single-turn dynamic cases.
- Execution: serial (`concurrency=1`), local API only, no fixed-route snapshot endpoint.
- Complete: 7/8; technical invalid: 1; review required: 2.
- End-to-end average (completed): 81.1s.

| Case | Profile | Total | Key stages | POIs / polylines | Verdict | Evaluation |
| --- | --- | ---: | --- | --- | --- | --- |
| S03 | P-SH-LOCAL | 46.2s | step1_intent 22.5s; planned_route 18.8s; photo_enrichment 3.9s | 2 / 2 | PASS | 可见 POI 2 个；路线段完整：2/1；需求证据可见：散步 |
| S24 | P-SH-LOCAL | 26.6s | step1_intent 17.4s; planned_route 9.1s; photo_enrichment 0.0s | 2 / 2 | PASS | 可见 POI 2 个；路线段完整：2/1 |
| S10 | P-BJ-FOOD | 61.8s | step1_intent 18.8s; planned_route 39.6s; photo_enrichment 3.3s | 3 / 3 | REVIEW | 可见 POI 3 个；路线段完整：3/2；固定锚点未见：颐和园 |
| S02 | P-BJ-FOOD | 125.5s | step1_intent 46.0s; step2_macro 15.6s; step3_micro 52.0s; exploratory_route 67.5s; reason_generation 5.0s; photo_enrichment 11.9s | 6 / 6 | REVIEW | 可见 POI 6 个；路线段完整：6/5；固定锚点未见：天安门、故宫 |
| S12 | P-SH-LOCAL | 25.6s | not emitted | 0 / 0 | FAIL | 未能满足以下明确行程需求：晚饭。已保留其他行程要求，请调整该地点或目标类型后重试。 |
| S06 | P-BJ-FOOD | 109.1s | step1_intent 43.9s; step2_macro 26.0s; step3_micro 37.8s; exploratory_route 63.8s; reason_generation 0.0s; photo_enrichment 1.3s | 9 / 9 | PASS | 可见 POI 9 个；路线段完整：9/8；固定锚点可见：北海、三里河 |
| S15 | P-BJ-ART | 109.9s | step1_intent 48.5s; step2_macro 18.5s; step3_micro 36.8s; exploratory_route 55.3s; reason_generation 5.0s; photo_enrichment 6.1s | 4 / 4 | PASS | 可见 POI 4 个；路线段完整：4/3；需求证据可见：咖啡、拍照 |
| S21 | P-BJ-ART | 88.5s | step1_intent 29.4s; step2_macro 29.3s; step3_micro 26.0s; exploratory_route 55.2s; reason_generation 3.8s; photo_enrichment 3.8s | 2 / 2 | PASS | 可见 POI 2 个；路线段完整：2/1；需求证据可见：咖啡、拍照 |

## Major issue decision

Major issue: yes. At least one request did not produce a parseable complete response; inspect its raw SSE artifact before changing scoring or route logic.

- `step1_intent` mean: 32.4s across 7 emitted cases.
- `step2_macro` mean: 22.3s across 4 emitted cases.
- `step3_micro` mean: 38.1s across 4 emitted cases.
- `planned_route` mean: 22.5s across 3 emitted cases.
- `exploratory_route` mean: 60.5s across 4 emitted cases.
- `reason_generation` mean: 3.5s across 4 emitted cases.
- `photo_enrichment` mean: 4.3s across 7 emitted cases.
