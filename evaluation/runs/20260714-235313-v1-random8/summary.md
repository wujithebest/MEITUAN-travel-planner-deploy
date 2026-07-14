# Dynamic Route Benchmark V1 - Random 8 Validation

- Run: `20260714-235313-v1-random8`
- Sampling: fixed seed `20260714`, 8 cases sampled from the 24 single-turn dynamic cases.
- Execution: serial (`concurrency=1`), local API only, no fixed-route snapshot endpoint.
- Complete: 7/8; technical invalid: 1; review required: 0.
- End-to-end average (completed): 53.8s.

| Case | Profile | Total | Key stages | POIs / polylines | Verdict | Evaluation |
| --- | --- | ---: | --- | --- | --- | --- |
| S03 | P-SH-LOCAL | 33.8s | step1_intent 12.9s; planned_route 16.5s; photo_enrichment 3.8s | 3 / 3 | PASS | 可见 POI 3 个；路线段完整：3/2；需求证据可见：散步 |
| S24 | P-SH-LOCAL | 29.2s | step1_intent 14.0s; planned_route 13.5s; photo_enrichment 1.6s | 2 / 2 | PASS | 可见 POI 2 个；路线段完整：2/1 |
| S10 | P-BJ-FOOD | 64.6s | step1_intent 31.9s; planned_route 31.3s; photo_enrichment 1.4s | 3 / 3 | PASS | 可见 POI 3 个；路线段完整：3/2；固定锚点可见：颐和园 |
| S02 | P-BJ-FOOD | 78.9s | not emitted | 0 / 0 | FAIL | 未能满足以下明确行程需求：北京菜。已保留其他行程要求，请调整该地点或目标类型后重试。 |
| S12 | P-SH-LOCAL | 19.7s | step1_intent 7.2s; planned_route 8.5s; photo_enrichment 3.9s | 2 / 1 | PASS | 可见 POI 2 个；路线段完整：1/1 |
| S06 | P-BJ-FOOD | 69.8s | step1_intent 46.4s; planned_route 21.8s; photo_enrichment 1.6s | 3 / 3 | PASS | 可见 POI 3 个；路线段完整：3/2；固定锚点可见：北海、三里河 |
| S15 | P-BJ-ART | 103.5s | step1_intent 37.8s; step2_macro 18.1s; step3_micro 42.6s; exploratory_route 60.7s; reason_generation 5.0s; photo_enrichment 5.0s | 5 / 5 | PASS | 可见 POI 5 个；路线段完整：5/4；需求证据可见：咖啡、拍照 |
| S21 | P-BJ-ART | 55.8s | step1_intent 22.8s; planned_route 24.2s; photo_enrichment 8.7s | 3 / 2 | PASS | 可见 POI 3 个；路线段完整：2/2；需求证据可见：咖啡、拍照 |

## Major issue decision

Major issue: yes. At least one request did not produce a parseable complete response; inspect its raw SSE artifact before changing scoring or route logic.

- `step1_intent` mean: 24.7s across 7 emitted cases.
- `step2_macro` mean: 18.1s across 1 emitted cases.
- `step3_micro` mean: 42.6s across 1 emitted cases.
- `planned_route` mean: 19.3s across 6 emitted cases.
- `exploratory_route` mean: 60.7s across 1 emitted cases.
- `reason_generation` mean: 5.0s across 1 emitted cases.
- `photo_enrichment` mean: 3.7s across 7 emitted cases.
