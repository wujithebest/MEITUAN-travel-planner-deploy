# 交接文档 — 旅行规划系统修复 (2026-07-13)

## 一、线上生产事故修复 — Guest Profile 归一化

**问题**：Render 后端所有路线请求失败，Pydantic `ValidationError: home_location.label` list→float/str 转换失败。

**根因**：前端 localStorage 存储 `home_location.label = []`（空数组），`build_profile_from_guest` 未做数据清洗直接传入 `UserProfile`。

**修改文件**（已 push 到 `origin/master`，commit `6d6d5b6`）：

| 文件 | 改动 |
|------|------|
| `backend/services/mock_profile.py` | 新增 `_coerce_float`/`_coerce_label`/`_normalize_home_location`/`_coerce_str_list`，在边界清洗所有 guest 输入 |
| `frontend/src/utils/locationDefaults.ts` | 新增 `normalizeLocationPayload()` |
| `frontend/src/hooks/useChat.ts` | `canonicalHome` 改用 `normalizeLocationPayload` |
| `frontend/src/store/userStore.ts` | `ensureGuestSession` 中 `home_location` 改用 `normalizeLocationPayload` |
| `backend/tests/test_guest_profile_normalization.py` | 13 个测试用例 |

---

## 二、多轮对话餐饮偏好修改修复

**问题**：二轮"不想吃烤鸭。想吃川菜"生成"北京川菜半日游路线"，北海公园、景山公园丢失。

**修改文件**：

| 文件 | 改动 |
|------|------|
| `backend/services/conversation_replan.py` | 新增 `_is_meal_preference_refine()` 识别 6 种餐饮替换模式；`_is_food_term`、`_expand_food_keywords` 等辅助函数；新增 `is_meal_preference_refine_decision()` |
| `backend/routers/meituan_chat.py` | 新增 `_try_meal_slot_replan()` — 找旧餐饮点、搜新菜系、replace 操作、保留原路线；fast path 对 meal replacement 直接短路；refine_current 分支优先调用 meal slot replan |
| `backend/services/step1_intent.py` | 新增 `_extract_latest_user_input()` / `_has_conversation_context()`；`run_step1()` 所有 waypoint 解析使用 `_nl_input`；`_postprocess` 同步 |
| `backend/services/step2_macro.py` | `run_step2()` 开头 guard：`meal_replacement` 时跳过宏观搜索 |
| `backend/services/step3_micro.py` | `run_step3()` 开头 guard：`meal_replacement` 时跳过微观路由 |

**关键行为**：
- "不想吃烤鸭。想吃川菜" → `refine_current` + `meal_replacement=True`，直接替换午餐点
- 北海公园、景山公园保持不变，不生成新路线
- "北海换成什刹海" → 正常 POI 替换逻辑，不走餐饮替换
- "明天重新安排川菜路线" → `new_plan`，不走餐饮替换

---

## 三、Step1 LLM 离线兜底 NameError 修复

**问题**：LLM 网络失败时 `_llm_parse()` except 分支引用未定义的 `permanent_city` → `NameError`。

**修改文件**：

| 文件 | 改动 |
|------|------|
| `backend/services/step1_intent.py` | `_llm_parse()` 新增 `fallback_city` 参数；except 分支用 `fallback_city` 替代 `permanent_city`；使用 `_extract_latest_user_input()` 防止 XML 污染 |
| 同上 | `_deterministic_fallback_parsed_intent()` 重写为分句时间槽解析，支持"先去A，中午吃B，下午去C"生成 3 个有序 PlannedWaypoint |
| 同上 | `run_step1()` 计算 `_fallback_city` 并传入 |

**测试**：冒烟测试验证"先去北海公园走走，中午吃顿烤鸭，下午去景山公园"→3 个有序 waypoint。

---

## 四、文艺路线餐饮点绕路排序修复

**问题**：单 SubAnchor 半日文艺路线中，系统默认插入的午餐/咖啡点（gaga）被放在 start 后导致 `gaga→望京公园(2.13km)` 绕路。

**修改文件**：

| 文件 | 改动 |
|------|------|
| `backend/services/step3_micro.py` | `_route_planning()` 消费 `meal_after_mid` 将餐饮点内联插入；`_reorder_by_proximity()` 放宽保护逻辑，单 anchor + 探索模式 + 仅午餐时允许 meal 参与空间重排 |

**日志**：`[SpatialMealReorderAudit] reason=single_anchor_default_lunch`

---

## 五、类别级删除/负向偏好修改

**问题**：二轮"不想去咖啡馆了。修改下路线"被当成 `target_name=整句话` 的 point_edit，匹配不到具体 POI 后回落完整 pipeline，又把"咖啡馆"解析成正向 primary_query。

**修改文件**：

| 文件 | 改动 |
|------|------|
| `backend/services/conversation_replan.py` | 新增 `_CATEGORY_EXCLUSION_MAP`（cafe/specialty_shop/restaurant/bar/bookstore）、`_detect_category_exclusion()`、`is_category_exclusion_decision()`；`classify_conversation_route_change_fast` 在 point edit 前优先检查类别排除 |
| `backend/routers/meituan_chat.py` | `_classify_chat_edit` 新增 `remove_category` 识别；`_try_chat_edit_replan` 新增批量删除匹配点、保留路线兜底；point_edit 失败时对 remove/remove_category 调用 `_emit_preserved_route` 而非继续 Step1；merge instruction 加入否定词优先级规则 |
| `backend/services/step1_intent.py` | 新增 `_CATEGORY_NEGATION_KEYWORDS`、`_extract_category_exclusions_from_request()` 剥离否定品类的关键词和 typecodes；`run_step1` 末尾调用 |
| `backend/services/step2_macro.py` | 宏观搜索结果硬过滤 `excluded_typecode_prefixes` 和 `excluded_terms` |
| `backend/services/step3_micro.py` | `_search_anchor_internals` 新增 `parsed_intent` 参数，每个 raw POI 做排除过滤 |
| `backend/tests/test_conversation_category_exclusion.py` | 9 个测试用例 |

**关键行为**：
- "不想去咖啡馆了" → `remove_category:cafe`，删除路线中所有咖啡类 POI
- 删除后无匹配点 → `_emit_preserved_route`，不回落完整 pipeline
- Step1 收到否定 → 剥离咖啡关键词，加入 `excluded_typecode_prefixes=[050400]`
- 首轮"有咖啡馆" → 不受影响（无否定触发词）

---

## 六、multi_facet_art 路线密度修复

**问题**："节奏轻松一点"被误判为半日游（`time_budget=0.5`），Step2 只选 1 个 anchor，Step3 上限 4，Step4 备选仅 1 个。

**修改文件**：

| 文件 | 改动 |
|------|------|
| `backend/services/data_schema.py` | ParsedIntent 新增 `density_min_visible_pois`/`density_target_visible_pois`/`candidate_target` |
| `backend/services/step1_intent.py` | multi_facet_art 分支：无明确半天标记时默认 `a full day` + `time_budget=1.0`，设置密度目标值 5/6/4；final_normalize 同步 |
| `backend/services/step2_macro.py` | `_select_anchors()` 对 multi_facet_art 提升 target，密度审计日志 |
| `backend/services/step3_micro.py` | RouteDensityAudit：multi_facet_art 时 `_internal_limit` 4→6-7 |
| `backend/services/step4_output.py` | CandidateBackupAudit：触发阈值 2→4，搜索半径 3km→5km |
| `backend/services/plan_reality_validator.py` | `visible_count < 4` 追加 `multi_facet_art_route_too_sparse` |
| `backend/tests/test_multi_facet_art_density.py` | 4 个测试用例 |

---

## 七、已部署到 master 的 commit

```
6d6d5b6 Fix guest home location normalization
```

其余修改在 `brunch` 分支（含之前 `ab774f3` 的 v22/v25 改动），尚未部署。

---

## 八、所有测试

```bash
python -m pytest backend/tests/test_guest_profile_normalization.py    # 13 passed
python -m pytest backend/tests/test_conversation_category_exclusion.py # 9 passed
python -m pytest backend/tests/test_multi_facet_art_density.py        # 4 passed
```

---

## 九、编译验证

```bash
python -m compileall backend/services backend/routers  # all pass
npm --prefix frontend run build                        # ✓ built in ~20s
```

---

## 十、已知注意事项

1. `backend/services/step1_intent.py` 中 `_extract_latest_user_input()` 和 `_has_conversation_context()` 为模块级函数，`run_step1()` 和 `_postprocess()` 均已使用。
2. `_is_meal_preference_refine()` 的 `_MEAL_REFINE_NEW_PLAN_SIGNALS` 排除"明天/后天/重新"等信号，防止误判。
3. `_detect_category_exclusion()` 与 `_is_meal_preference_refine()` 互斥：前者处理"不想去咖啡馆"（类别删除），后者处理"不想吃烤鸭→想吃川菜"（餐饮替换）。
4. `_extract_category_exclusions_from_request()` 仅在无 route_context 的 Step1 路径激活；多轮场景由 conversation dispatch 提前拦截。
5. `is_category_exclusion_decision()` 用于 meituan_chat 判断 point_edit 是否为类别排除，失败时走 `_emit_preserved_route` 而非完整 pipeline。
6. density 字段（`density_min_visible_pois` 等）仅在 multi_facet_art 分支设置，不影响普通主题路线。
7. 博查（Bocha）搜索可能失败，但不是核心原因——高德返回 `raw=26 valid=26` 的内部 POI 足够，密度由 Step2/Step3/Step4 策略控制。
