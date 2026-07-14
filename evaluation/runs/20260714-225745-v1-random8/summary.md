# Dynamic Route Benchmark V1 - Random 8 Validation

- Run: `20260714-225745-v1-random8`
- Sampling: fixed seed `20260714`, 8 cases sampled from the 24 single-turn dynamic cases.
- Execution: serial (`concurrency=1`), local API only, no fixed-route snapshot endpoint.
- Complete: 5/8; technical invalid: 3; review required: 0.
- End-to-end average (completed): 40.4s.

| Case | Profile | Total | Key stages | POIs / polylines | Verdict | Evaluation |
| --- | --- | ---: | --- | --- | --- | --- |
| S03 | P-SH-LOCAL | 26.8s | step1_intent 15.1s; planned_route 8.5s; photo_enrichment 2.8s | 2 / 2 | PASS | 可见 POI 2 个；路线段完整：2/1；需求证据可见：散步 |
| S24 | P-SH-LOCAL | 20.6s | step1_intent 12.1s; planned_route 6.8s; photo_enrichment 1.6s | 2 / 2 | PASS | 可见 POI 2 个；路线段完整：2/1 |
| S10 | P-BJ-FOOD | 49.3s | not emitted | 0 / 0 | FAIL | 未能满足以下明确行程需求：继续轻松。已保留其他行程要求，请调整该地点或目标类型后重试。 |
| S02 | P-BJ-FOOD | 57.9s | not emitted | 0 / 0 | FAIL | 路线规划暂时失败：'route_order' |
| S12 | P-SH-LOCAL | 29.6s | step1_intent 7.7s; planned_route 7.2s; photo_enrichment 14.7s | 2 / 1 | PASS | 可见 POI 2 个；路线段完整：1/1 |
| S06 | P-BJ-FOOD | 48.7s | step1_intent 24.3s; planned_route 23.3s; photo_enrichment 1.1s | 3 / 3 | PASS | 可见 POI 3 个；路线段完整：3/2；固定锚点可见：北海、三里河 |
| S15 | P-BJ-ART | 185.9s | not emitted | 0 / 0 | FAIL | 外部地图服务暂时不稳定，我已按餐饮偏好冲突为你生成可执行的折中建议；具体店铺可稍后再刷新。 |
| S21 | P-BJ-ART | 76.2s | step1_intent 43.1s; planned_route 25.5s; photo_enrichment 7.5s | 2 / 2 | PASS | 可见 POI 2 个；路线段完整：2/1；需求证据可见：咖啡、拍照 |

## Major issue decision

Major issue: yes. At least one request did not produce a parseable complete response; inspect its raw SSE artifact before changing scoring or route logic.

- `step1_intent` mean: 20.4s across 5 emitted cases.
- `planned_route` mean: 14.3s across 5 emitted cases.
- `photo_enrichment` mean: 5.5s across 5 emitted cases.
