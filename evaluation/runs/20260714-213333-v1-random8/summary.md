# Dynamic Route Benchmark V1 - Random 8 Validation

- Run: `20260714-213333-v1-random8`
- Sampling: fixed seed `20260714`, 8 cases sampled from the 24 single-turn dynamic cases.
- Execution: serial (`concurrency=1`), local API only, no fixed-route snapshot endpoint.
- Complete: 5/8; technical invalid: 3; review required: 1.
- End-to-end average (completed): 79.1s.

| Case | Profile | Total | Key stages | POIs / polylines | Verdict | Evaluation |
| --- | --- | ---: | --- | --- | --- | --- |
| S03 | P-SH-LOCAL | 71.2s | not emitted | 1 / 1 | REVIEW | 可见 POI 过少：1 个；路线段不足：1/0；需求证据不足：散步 |
| S24 | P-SH-LOCAL | 70.5s | not emitted | 3 / 2 | PASS | 可见 POI 3 个；路线段完整：2/2 |
| S10 | P-BJ-FOOD | 135.6s | not emitted | 0 / 0 | FAIL | 当前条件下可组成完整路线的有效地点较少。请补充目的地、调整活动偏好或扩大出行范围后重试。 |
| S02 | P-BJ-FOOD | 135.8s | not emitted | 0 / 0 | FAIL | 当前条件下可组成完整路线的有效地点较少。请补充目的地、调整活动偏好或扩大出行范围后重试。 |
| S12 | P-SH-LOCAL | 48.8s | not emitted | 2 / 2 | PASS | 可见 POI 2 个；路线段完整：2/1 |
| S06 | P-BJ-FOOD | 109.2s | not emitted | 9 / 9 | PASS | 可见 POI 9 个；路线段完整：9/8；固定锚点可见：北海、三里河 |
| S15 | P-BJ-ART | 48.3s | not emitted | 0 / 0 | FAIL | 外部地图服务暂时不稳定，我已按餐饮偏好冲突为你生成可执行的折中建议；具体店铺可稍后再刷新。 |
| S21 | P-BJ-ART | 95.7s | not emitted | 2 / 2 | PASS | 可见 POI 2 个；路线段完整：2/1；需求证据可见：咖啡、拍照 |

## Major issue decision

Major issue: yes. At least one request did not produce a parseable complete response; inspect its raw SSE artifact before changing scoring or route logic.
