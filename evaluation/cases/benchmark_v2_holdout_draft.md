# Dynamic Route Benchmark v2 - Holdout Review Draft

Status: pending review. This file is a held-out evaluation set and must not be used to modify prompts, rules, retrieval terms, or regression fixtures. It is stored separately from `benchmark_v1_draft.md` because V1 has been used during implementation.

## Evaluation conventions

- Dynamic pipeline only. Fixed route snapshots are excluded from live metrics.
- Coverage, matching, fallback, and stop rules are the same as V1 unless a later evaluation-spec version explicitly changes them.
- Query text is deliberately different from V1, while the underlying supported capability mix remains comparable.
- POI matching accepts official aliases, parent-child POI relations, and labelled category equivalents.

## Profile presets

| Profile | City / origin | Food preferences | Activity preferences |
| --- | --- | --- | --- |
| P-BJ-ART | Beijing / Chaoyang Wangjing | coffee, light food | photography, art, local shops, relaxed pace |
| P-BJ-FOOD | Beijing / Dongcheng Beijing Hotel | Beijing food, mild food | walking, parks, history |
| P-SH-LOCAL | Shanghai / Putuo Taopu | coffee, local food | walking, photography, relaxed pace |
| P-BJ-GROUP | Beijing / Chaoyang Wangjing | mild food, accepts Sichuan-style options | friends, evening walk |

## Single-turn cases

| ID | Profile | User query | Expected intent / output | Hard constraints |
| --- | --- | --- | --- |
| H01 Highlight | P-BJ-ART | 在北京安排一天慢节奏的艺术散步吧，想拍些照片，途中要有咖啡店和有意思的小店。 | photo + art + cafe + specialty shop + relaxed route. | All five facets covered; no sparse-recall failure. |
| H02 Highlight | P-BJ-FOOD | 先到天安门和故宫一带看看，中午安排一家正宗北京菜，傍晚前去景山看日落。 | planned Beijing culture route with Tiananmen, Forbidden City area, Beijing-cuisine lunch, Jingshan sunset. | Fixed anchors and stated time order retained. |
| H03 Highlight | P-SH-LOCAL | 我一会儿就在周边随便走走，顺便找点好吃的，有适合散步的地方吗？ | nearby food + walk derived from origin and profile. | Search remains near origin; food and walk both present. |
| H04 Highlight | P-BJ-GROUP | 朋友明天来北京，我口味偏清淡，他很想吃川味，能找个我们都能点菜的地方吗？饭后想在周围走走。 | conflict-aware meal and nearby walk. | Mild/non-spicy option and Sichuan-style option, or a stated compromise. |
| H07 | P-BJ-FOOD | 只打算玩半天：上午逛北海，吃完北京菜再去什刹海走走。 | half-day park, Beijing-cuisine meal, and walk. | Three activities follow the stated order. |
| H09 | P-BJ-ART | 三里屯附近下午想坐坐咖啡馆、看看特色店铺，晚上顺路看夜景。 | nearby afternoon-to-evening route. | Coffee, shops, and night view are present and spatially close. |
| H11 | P-SH-LOCAL | 上海只留半天，先去外滩拍照，找家咖啡馆歇会儿，再逛逛南京路。 | Shanghai photo + cafe + shopping route. | Bund, coffee, and Nanjing Road in practical order. |
| H12 | P-SH-LOCAL | 下班路上想买些水果，然后在附近简单吃个晚饭。 | nearby errands + dinner route. | Fruit shopping and dinner both present and close to origin. |
| H13 | P-BJ-FOOD | 预算每人别超过200，故宫周边走走，中午吃北京菜，下午上景山。 | budget-aware planned Beijing culture route. | Fixed places retained; meal and budget considered. |
| H14 | P-BJ-FOOD | 想吃口味不辣的北京菜，吃饱后在餐厅旁边散会儿步。 | mild Beijing cuisine plus nearby walk. | No spicy-focused meal; meal and walk covered. |
| H18 | P-BJ-ART | 晚上在国贸一带，先吃清淡一点，再去一个适合看城市夜景的点。 | nearby light dinner + night-view route. | Dinner before night view; both near Guomao. |
| H20 | P-BJ-ART | 我马上想在附近转转，帮我挑几个值得去的地方。 | immediate nearby exploration based on origin. | POIs remain near origin; at least two visitable options. |

## Multi-turn and conflict cases

| ID | Profile | First turn | Follow-up query | Expected operation and preservation |
| --- | --- | --- | --- | --- |
| HM01 Highlight | P-BJ-FOOD | 我想上午逛北海公园，中午安排烤鸭，下午去景山公园。 | 烤鸭先不要了，换成川菜吧。 | Replace meal only; retain Beihai and Jingshan. |
| HM03 | P-BJ-ART | 我想在北京走一条能拍照、喝咖啡、逛小店的轻松路线。 | 咖啡馆不需要了，能换成书店吗？ | Remove cafe category and add/retain bookstore; preserve photo, art, shop, relaxed facets. |
| HM04 | P-SH-LOCAL | 我待会儿想在附近吃点东西，顺便散步。 | 再补一个可以坐下来喝咖啡的地方。 | Local follow-up append; preserve nearby center and existing route. |
| HM08 | P-BJ-GROUP | 朋友来北京，我不吃辣、他想吃川菜，吃完在附近走走。 | 不吃饭了，下午改成看展再喝咖啡。 | New-plan detection; previous meal conflict must not remain mandatory. |

## Holdout discipline

1. Do not use any V2 query, expected label, scoring miss, or response detail to change routing logic before the V2 evaluation is completed.
2. If V2 exposes a defect, record it in the run artifacts first. Any subsequent code fix requires a new V3 holdout set for final reporting.
3. The runner must record the benchmark version as `v2_holdout` in `manifest.json` and use a separate run ID from all V1 attempts.
