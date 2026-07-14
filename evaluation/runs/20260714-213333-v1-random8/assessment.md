# Dynamic Route Benchmark V1 - Random 8 Assessment

## Scope

- Run ID: `20260714-213333-v1-random8`
- Sample: fixed seed `20260714`, eight cases from the 24 single-turn dynamic cases: `S03, S24, S10, S02, S12, S06, S15, S21`.
- Execution: local dynamic SSE endpoint, serial (`concurrency=1`), no fixed-route snapshot endpoint.
- Profiles: the benchmark's declared Beijing/Shanghai profile presets, including their configured home coordinates.
- Important: this is a live external-API run. The raw SSE and normalized terminal responses in this directory are the source of truth; no secret is persisted.

## Outcome

The batch ran to completion and did not hit the runner's *consecutive* technical-failure stop rule. It nevertheless exposes a **major release-blocking quality problem**:

- 3/8 requests ended in an SSE `error` event (37.5%). Two were functional route failures, not infrastructure failures: a clear fixed-anchor request was rejected as having too few valid POIs.
- 1/8 ended in a confirmed external Gaode TLS failure while Step1 requested weather.
- The other 5 responses returned a parseable route, but none satisfies all explicit user requirements on manual semantic review.
- The completed-route average was 79.1s; the slowest terminal response was 135.8s. This is far beyond a comfortable interactive planning target.

## Case Records

| Case | Stage timing | Terminal route result | Evaluation |
| --- | --- | --- | --- |
| S03 | Total 70.8s; Step1 16.1s; Step2 19.5s; Step3 32.7s; photos 2.6s | One visible POI: `韩记小吃(瑞香苑小区店)`. | **FAIL**. The user asked for nearby exploration, food, and a walk; only a snack shop was returned. The route has no visitable walking POI or walking segment. |
| S24 | Total 70.5s; Step1 26.1s; Step2 18.1s; Step3 21.8s; photos 4.5s | `克劳森精酿` -> `筷子兄弟餐厅` -> `天扬泳健会`. | **FAIL**. A pub and a gym are not evidence of "饭后走一走". The planner lost the walk constraint and picked an unrelated sports POI. |
| S10 | Error after 135.6s; terminal per-stage metrics absent because no `complete` event. | `当前条件下可组成完整路线的有效地点较少`. | **FAIL**. `颐和园` is a clear fixed anchor and the request is feasible. Returning a generic scarcity error after detailed planning is a functional fixed-anchor failure. |
| S02 | Error after 135.8s; terminal per-stage metrics absent because no `complete` event. | `当前条件下可组成完整路线的有效地点较少`. | **FAIL**. `天安门/故宫/北京菜/景山日落` are explicit, feasible anchors with an explicit time order; the system must not reject this request. |
| S12 | Total 48.8s; Step1 7.7s; planned route 37.6s; photos 3.5s | `萨莉亚意式餐厅` -> `果品行`. | **FAIL**. The required categories are present, but the user asked to buy fruit *then* eat dinner; the rendered order is reversed. |
| S06 | Total 109.2s; Step1 26.5s; Step2 26.0s; Step3 55.1s; photos 1.6s | Beihai POIs -> `老吉堂上海本帮菜(后海店)` -> Beijing planning museum / Fayuan museum -> Sanlihe. | **FAIL**. Beihai and Sanlihe were retained, but the required roast-duck lunch was replaced by Shanghai cuisine and unrelated filler POIs expand the route. This breaks a hard requirement and route compactness. |
| S15 | Error after 48.3s; no terminal stage metrics. | `外部地图服务暂时不稳定...`. Backend log identifies Gaode weather TLS retry failure during Step1. | **TECHNICAL FAIL**. Weather is not central to this relaxed photo-and-coffee request, so its failure should degrade gracefully rather than abort route generation. |
| S21 | Total 95.7s; Step1 48.7s; Step2 19.7s; Step3 23.0s; reasons/photos 4.2s | `瑞幸咖啡` -> `星巴克`. | **FAIL**. Coffee was retained, but the explicit photo-location facet was dropped entirely. The plan is effectively a coffee-only route. |

## Timing Findings

For the five completed responses:

- `Step1` averaged 25.0s. Even immediate nearby cases took 16.1s and 26.1s, so the sparse path is not reliably activated or not consistently fast in the live route path.
- Exploratory routing (`Step2 + Step3`) is the other dominant cost: `S06` took 81.1s in the aggregate exploratory route stage, with Step3 alone taking 55.1s.
- The planned short trip (`S12`) still spent 37.6s in `planned_route`; its semantic ordering was wrong despite that cost.
- Endpoint error cases did not emit final `PipelineStats`, which means per-stage error timing cannot currently be measured from the terminal SSE event. The SSE status timeline is retained in `events/`.

## Major Problems and Priority

1. **P0 - Fixed anchors may be rejected as sparse**: S02 and S10 should be deterministic feasible plans, yet both became generic errors after roughly 136s. Do not tune recommendation density before tracing the fixed-anchor/PlanReality rejection path.
2. **P0 - Required facets are not preserved through selection**: S03/S24 lose the walking facet, S06 loses roast duck, and S21 loses photography. The stage boundary must carry hard requirements into final visible-POI validation, rather than treating a broad theme or a meal result as sufficient coverage.
3. **P0 - Weather is a hard availability dependency**: the S15 failure came from a transient Gaode weather TLS error in Step1. Weather failure must be optional/degraded for requests that do not explicitly require weather-sensitive decisions.
4. **P1 - Ordering validation is incomplete**: S12 reverses two explicit planned waypoints. Verify final `route_order` against `planned_waypoints` before rendering/returning the route.
5. **P1 - Latency remains unsuitable for interactive usage**: accepted responses span 48.8s to 109.2s. First measure why simple nearby queries miss the compact Step1 path; then profile Step3's repeated map work. Do not increase Gaode concurrency beyond the agreed limit of 3.
6. **P1 - Evaluation observability is partial**: success responses contain `stats.stage_durations_ms`, but errors omit an equivalent snapshot. Persist `PipelineStats` on terminal errors so failures can be attributed without interpreting status text.

## Decision

Further modification is necessary before treating this code state as stable. The next change should be narrowly targeted at the P0 items above, followed by a rerun of these exact eight case IDs and then the multi-turn set. It should not be a broad reranking rewrite: first restore feasibility and hard-constraint preservation, then optimise latency with repeatable stage evidence.

## Artifacts

- `manifest.json`: immutable run metadata and case-file checksum.
- `cases_resolved.jsonl`: exact sampled inputs and profile payloads.
- `raw_sse/`, `events/`, `responses/`, and `scores/`: per-case wire evidence and normalized results.
- `summary.csv`: compact machine-readable index. The original `summary.md` is retained as first-pass runner output; this document corrects its overly permissive POI-only scoring with semantic review and uses the actual `stats.stage_durations_ms` field.
