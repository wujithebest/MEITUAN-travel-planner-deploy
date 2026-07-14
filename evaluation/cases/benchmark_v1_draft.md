# Dynamic Route Benchmark v1 - Review Draft

Status: pending review. This is a specification only; it does not call any live API.

## Evaluation conventions

- Dynamic pipeline only. The six fixed route snapshots are excluded.
- POI matching accepts official aliases, parent-child POI relations, and labelled category equivalents. For example, "北京菜" may match a qualifying Beijing-cuisine restaurant; it does not require one exact shop name.
- A hard constraint must be met. A soft preference may be satisfied by a closely related POI or route characteristic.
- A negative constraint is satisfied only when the prohibited category/condition is absent from the final visible route.
- For an inherently contradictory request, a correct result is either a feasible compromise that states the trade-off, or a clear constraint-aware explanation. Returning an unrelated route is incorrect.
- Main route size is evaluated against each case's requested duration and density. It is not forced to the 6+4 display convention used by fixed demo snapshots.

## Benchmark positioning

V1 evaluates the current supported boundary rather than aspirational special scenarios. The six fixed UI snapshots are retained as the six "highlight" cases: three normal showcase cases and three difficult showcase cases. The remaining cases use everyday, single-city, and clearly executable requests.

Excluded from V1: overnight Great Wall stays, fruit picking, hotel hopping, New Year flag-raising, public courtyard access, campus canteen verification, boating dock availability, real-time weather adaptation, queueing, accessibility, mother-and-baby facilities, and live POI-review data. These depend on special data, live operations, or capabilities listed as future enhancement.

## Profile presets

| Profile | City / origin | Food preferences | Activity preferences |
| --- | --- | --- | --- |
| P-BJ-ART | Beijing / Chaoyang Wangjing | coffee, light food | photography, art, local shops, relaxed pace |
| P-BJ-FOOD | Beijing / Dongcheng Beijing Hotel | Beijing food, mild food | walking, parks, history |
| P-SH-LOCAL | Shanghai / Putuo Taopu | coffee, local food | walking, photography, relaxed pace |
| P-BJ-GROUP | Beijing / Chaoyang Wangjing | mild food, accepts Sichuan-style options | friends, evening walk |

## Single-turn cases

| ID | Profile | User input | Expected intent / output | Hard constraints |
| --- | --- | --- | --- | --- |
| S01 Highlight | P-BJ-ART | 帮我推荐一条适合拍照的文艺路线，有咖啡馆和特色小店，节奏轻松一点。 | photo + art + cafe + specialty shop + relaxed route; 4-6 main POIs and 2+ candidates. | All five facets covered; no route failure from sparse recall. |
| S02 Highlight | P-BJ-FOOD | 想去天安门和故宫附近转转，中午吃顿地道的北京菜，下午去景山公园看日落。 | planned Beijing culture route with Tiananmen, Forbidden City area, Beijing-cuisine lunch, Jingshan sunset. | Fixed anchors and time order retained. |
| S03 Highlight | P-SH-LOCAL | 待会儿去附近逛逛，找一家好吃的，再散散步。 | nearby food + walk, derived from origin and profile. | Search remains near origin; food and walk both present. |
| S04 Highlight | P-BJ-GROUP | 明天朋友来北京找我，我不吃辣但他想吃川菜，帮我找一家两边都能接受的餐厅，吃完想在附近散散步。 | conflict-aware meal and nearby walk. | Restaurant supports mild/non-spicy choice and Sichuan-style choice, or gives a stated compromise. |
| S05 Highlight | P-BJ-ART | 下午推荐一条北京文艺路线，晚饭想吃点清淡的，吃完去河边走走，最后找个拍夜景的地方。 | afternoon-to-night art route with light dinner, riverside walk, night photo. | Time order and all four facets covered. |
| S06 Highlight | P-BJ-FOOD | 帮我规划一条路线，先去北海公园走走，中午吃顿烤鸭，下午去三里河公园。 | planned route with Beihai, roast duck lunch, Sanlihe Park. | All fixed anchors and stated order retained. |
| S07 | P-BJ-FOOD | 我想在北京玩半天，上午去北海公园，午饭吃北京菜，下午去什刹海散步。 | half-day planned route with park, Beijing-cuisine lunch, and walk. | Three requested activities follow the stated order. |
| S08 | P-BJ-ART | 北京一日游，只想坐地铁，想去天坛、前门和王府井。 | metro-led one-day route with three explicit landmarks. | All anchors are retained; metro preference is reflected. |
| S09 | P-BJ-ART | 下午想在三里屯附近喝咖啡、逛小店，晚上看看夜景。 | nearby afternoon-to-evening route. | Coffee, shops, and night view are all present and spatially close. |
| S10 | P-BJ-FOOD | 周末想去颐和园逛逛，中午在附近吃饭，下午继续轻松走走。 | simple park day with nearby meal and walk. | Yiheyuan is retained; meal is nearby; relaxed pace. |
| S11 | P-SH-LOCAL | 上海半日游，想去外滩拍照，喝杯咖啡，再去南京路逛逛。 | Shanghai photo + cafe + shopping route. | Bund, coffee, and Nanjing Road are present in a practical order. |
| S12 | P-SH-LOCAL | 下班后想在附近买点水果，再找个地方简单吃晚饭。 | nearby errands + dinner route. | Fruit shopping and dinner are both present and close to origin. |
| S13 | P-BJ-FOOD | 人均200元，想去故宫附近逛逛，中午吃北京菜，下午去景山。 | budget-aware planned Beijing culture route. | Fixed places retained; meal and budget are considered. |
| S14 | P-BJ-FOOD | 不想吃辣，想找家北京菜馆，吃完在附近走走。 | mild Beijing cuisine plus nearby walk. | No spicy-focused meal recommendation; meal and walk both covered. |
| S15 | P-BJ-ART | 周末和朋友在北京轻松逛一天，想拍照、喝咖啡、不要太赶。 | relaxed photo and coffee day. | Photo + coffee + relaxed pace; no forced fixed anchor. |
| S16 | P-SH-LOCAL | 待会儿在附近找个咖啡馆坐坐，再去公园散步。 | immediate nearby coffee + park walk. | Both activities stay near origin. |
| S17 | P-BJ-FOOD | 北京两日游，第一天逛故宫和景山，第二天去天坛和前门。 | clear two-day cultural route. | Day grouping and four landmarks are retained. |
| S18 | P-BJ-ART | 晚上想在国贸附近吃个清淡晚饭，再找个能看夜景的地方。 | nearby light dinner + night-view route. | Dinner comes before night view; both remain near Guomao. |
| S19 | P-BJ-ART | 北京文艺路线推荐。 | broad art-route recommendation. | At least two art/photo/cafe/local-shop related POIs; no unsupported fixed-anchor assumption. |
| S20 | P-BJ-ART | 待会儿去附近逛逛，有什么推荐？ | immediate nearby exploration based on origin. | POIs remain near origin and include at least two visitable options. |
| S21 | P-BJ-ART | 北京下午想找个适合拍照的地方，再喝杯咖啡。 | simple photo + cafe half-day route. | Both facets are present in a feasible afternoon order. |
| S22 | P-SH-LOCAL | 上海周末想轻松逛逛，喝咖啡、散散步。 | relaxed coffee-and-walk route. | Coffee and walk are present; no hard fixed POI required. |
| S23 | P-BJ-FOOD | 北京一日游，上午去天坛，下午去前门逛逛。 | simple two-anchor one-day route. | Both anchors appear in chronological order. |
| S24 | P-SH-LOCAL | 待会儿想在附近找个地方吃饭，饭后走一走。 | immediate nearby meal + walk. | Food and walk are both near origin. |

## Multi-turn and conflict cases

| ID | Profile | First turn | Follow-up turn | Expected operation and preservation |
| --- | --- | --- | --- | --- |
| M01 Highlight | P-BJ-FOOD | 帮我规划一条路线，先去北海公园走走，中午吃顿烤鸭，下午去景山公园。 | 不想吃烤鸭。想吃川菜。 | Replace the meal only; retain Beihai and Jingshan. |
| M02 | P-BJ-FOOD | 想去天安门和故宫附近转转，中午吃顿地道的北京菜，下午去景山公园看日落。 | 下午不去景山了，换成北海公园。 | Replace destination; preserve Tiananmen, Forbidden City area, and Beijing-cuisine lunch. |
| M03 | P-BJ-ART | 帮我推荐一条适合拍照的文艺路线，有咖啡馆和特色小店，节奏轻松一点。 | 不想去咖啡馆了，改成书店。 | Remove cafe category and add/retain bookstore option; preserve photo, art, shop, and relaxed facets. |
| M04 | P-SH-LOCAL | 待会儿去附近逛逛，找一家好吃的，再散散步。 | 再加一家适合坐一会儿的咖啡馆。 | Local follow-up append; preserve nearby center and existing route. |
| M05 | P-BJ-ART | 下午推荐一条北京文艺路线，晚饭想吃点清淡的，吃完去河边走走，最后找个拍夜景的地方。 | 人均控制在150元以内，晚饭不要西餐。 | Apply budget and meal exclusions while retaining afternoon, river, and night-view intent. |
| M06 | P-BJ-FOOD | 我想在北京玩半天，上午去北海公园，午饭吃北京菜，下午去什刹海散步。 | 午饭改成不辣的川菜，其他不变。 | Replace the meal only; retain Beihai and Shichahai. |
| M07 | P-BJ-ART | 北京一日游，只想坐地铁，想去天坛、前门和王府井。 | 还是只坐地铁，晚饭改成清淡一点。 | Retain transport and landmarks; update meal constraint only. |
| M08 | P-BJ-GROUP | 明天朋友来北京找我，我不吃辣但他想吃川菜，帮我找一家两边都能接受的餐厅，吃完想在附近散散步。 | 不吃饭了，改成下午逛展和喝咖啡。 | New plan detection; do not inherit the previous conflict meal requirement. |

## Proposed batch stop mechanism

The runner must stop immediately, write partial results, and request review instead of silently continuing when one of the following occurs:

1. Any confirmed external rate-limit response (`429`) occurs. The runner does not retry the whole batch.
2. Three consecutive technical failures occur, including TLS/network errors, malformed SSE, server exceptions, or missing final `done` events.
3. Two route-generation timeouts occur within any rolling five-case window. The router's current hard SSE limit is 300 seconds.
4. After at least eight completed cases, technical invalid results account for 25% or more of executed cases.
5. A single case consumes the 300-second hard limit; record it, stop the batch, and preserve its trace for diagnosis.

An allowed constraint-aware fallback is scored as a quality result, not a technical invalid result. Technical invalid results mean that the system could not provide a parseable terminal response or failed for infrastructure/runtime reasons.

## Proposed safe execution phases

1. Review and approve this draft.
2. Implement hooks and a runner with evaluation mode disabled by default.
3. Validate scoring locally with mocked stored responses; make no live API calls.
4. Run a five-case serial pilot with a delay between requests and inspect its result table.
5. Only after pilot review, run the remaining approved cases serially.
