# Travel Planner 项目交接文档

更新时间：2026-06-30  
工作区：`D:\pm_project\meituan_project\travel-planner-final`

## 1. 当前目标

当前最高优先级是修复路线生成完成后的推荐理由展示：

- 左侧“AI旅游助手”路线卡片下方显示整条路线的推荐理由；
- 右侧“路线地点”中每个 POI 在评分下方显示自己的推荐理由；
- 两类理由都必须关联用户本次明确偏好或约束；
- DeepSeek 返回无效 JSON 或缺少可靠证据时保持为空，不生成通用兜底理由。

## 2. 当前容器状态

最近一次检查时：

- `travel-planner-final-backend-1` 正常运行；
- `travel-planner-final-frontend-1` 正常运行；
- 前后端镜像均已包含最新的推荐理由代码；
- 前端编译产物已包含 `route_recommend_reason`、`为什么推荐` 和 `RouteReasonFrontendAudit`，不是旧镜像问题。

常用检查命令：

```powershell
docker compose ps
docker logs --since 10m travel-planner-final-backend-1
docker exec travel-planner-final-frontend-1 sh -lc "grep -oE 'RouteReasonFrontendAudit|route_recommend_reason|为什么推荐' /usr/share/nginx/html/assets/*.js | sort | uniq -c"
```

## 3. 最新端到端验证结果

实际在 `http://localhost/app` 输入：

```text
想去周围的公园逛逛，求推荐
```

结果：

- 路线成功生成；
- 左侧“为什么推荐”已经显示，DOM 数量为 1；
- 右侧“路线地点”正常显示“官园公园”；
- 右侧逐 POI 推荐理由节点数量为 0。

因此，当前自由探索模式下的真实状态是：**左侧已恢复，右侧仍失败**。

后端关键日志：

```text
[RouteReason] generated: 这条路线以官园公园为核心……
[ReasonAudit] ... reason_written=False ... failure_reason=vague_preference_match
[ReasonSummary] valid_reason_count=0 empty_reason_count=1 deepseek_call_count=1
[RouteReasonTransportAudit] generated=True length=57 route_data_has_reason=False
[RouteRecReason] route_recommend_reason=这条路线以官园公园为核心……
```

## 4. 右侧理由不显示的直接根因

文件：`backend/services/reason_generator.py`

当前 `_validate_reason_item` 包含：

```python
pref_match = str(item.get("preference_match", "")).strip()
if not pref_match or "符合" in pref_match:
    return False, "vague_preference_match"
```

这会把所有包含“符合”二字的具体说明也误判为无效，例如“符合用户短途散步偏好，因为……”。DeepSeek 已经返回理由，但校验失败后代码执行：

```python
poi["recommend_reason"] = ""
```

随后：

- Step4 输出的 `route_data.points[*].recommend_reason` 为空；
- `useChat.buildPanelDays()` 收到空值；
- `RoutePlacesList.tsx` 的渲染条件不成立；
- 右侧没有推荐理由。

右侧前端的数据传递和渲染代码目前基本完整，不是当前自由探索请求的主要故障点。

## 5. 推荐理由链路中的其他缺陷

### 5.1 异常处理存在潜在 NameError

`backend/services/reason_generator.py` 中捕获变量是 `exc`，但循环日志使用了未定义的 `e`：

```python
except (asyncio.TimeoutError, Exception) as exc:
    ...
    failure_reason={type(e).__name__}
```

应改为 `type(exc).__name__`，并简化为 `except Exception as exc`。

### 5.2 Pydantic 子项模型没有真正启用

已经定义 `ReasonItemResponse`，但当前为：

```python
class RouteReasonResponse(BaseModel):
    route_recommend_reason: str = ""
    items: list[dict] = Field(default_factory=list)
```

应改为：

```python
items: list[ReasonItemResponse] = Field(default_factory=list)
```

然后使用 `response.model_dump()` 得到字典。

### 5.3 实际用户原话没有进入理由上下文

`_build_user_context()` 尝试读取：

```python
getattr(parsed_intent, "user_request", "")
```

但 `ParsedIntent` 没有可靠保存该字段。应将当前有效请求显式传给理由生成器，或为 `ParsedIntent` 增加 `user_request/raw_user_request` 并在 Step1 写入。

否则 DeepSeek 只能依赖 `raw_keywords` 等裁剪字段，难以准确关联“情侣约会、拍照、附近、短途”等原始偏好。

### 5.4 只为 exploratory 模式生成理由

`backend/routers/meituan_chat.py` 当前仅在以下条件调用：

```python
if _final_plan_mode == "exploratory" and route_points:
```

所以 `planned`、`mixed`、部分 `chat_edit` 路线不会生成左侧路线理由，也不会生成右侧逐 POI 理由。这很可能是用户观察到“左侧和右侧都没有”的原因之一。

应明确支持所有成功路线模式，至少包括：

- `exploratory`；
- `planned`；
- `mixed`；
- 路线增删改后新增或替换的 POI。

### 5.5 display POI 过滤过严

当前过滤要求：

```python
if p.get("is_waypoint") not in (False, None)
```

部分合法路线点未显式写入 `is_waypoint` 时会被排除。建议使用：

```python
p.get("is_waypoint", True) is not False
```

同时继续排除 `start/origin/hint/free_explore/route_only`。

### 5.6 TransportAudit 打印顺序错误

`backend/services/step4_output.py` 当前先打印：

```text
route_data_has_reason=False
```

之后才执行：

```python
route_data["route_recommend_reason"] = _route_rec_reason
```

这只是审计顺序错误，但会造成误判。应先写入，再打印最终状态。

### 5.7 失败审计丢失真实模型输出

ReasonAudit 在校验失败时把日志硬编码为：

```text
matched_preferences=[] evidence_ids=[]
```

即使 DeepSeek 实际返回了内容也看不到。失败日志应打印真实的：

- `item.matched_preferences`；
- `item.preference_match`；
- `item.evidence_ids`；
- `item.recommend_reason` 长度；
- 精确 rejection reason。

## 6. 建议的下一步修改

### 后端

1. 删除 `"符合" in pref_match` 这种全局子串拒绝。
2. 只拒绝完全空泛的固定句式，例如：
   - `符合用户偏好`；
   - `符合本次路线偏好`；
   - `值得推荐`；
   - `适合用户需求`。
3. 要求 `preference_match` 或最终理由至少明确包含一个真实 `matched_preferences.term`，并拥有可追溯 `evidence_ids`。
4. 修复异常变量 `e -> exc`。
5. 使用 `list[ReasonItemResponse]`。
6. 把原始用户请求传入 `_build_user_context()`。
7. 为 `exploratory/planned/mixed` 都调用统一的路线理由生成器。
8. 放宽缺失 `is_waypoint` 的合法显示 POI。
9. Step4 在赋值后输出 `RouteReasonTransportAudit`。
10. 增加 `point_reason_count`，确认最终 points 中有多少条有效 `recommend_reason`。

### 前端

当前已确认：

- `useChat.ts` 已把 `route_recommend_reason` 写入路线消息；
- `ChatPanel.tsx` 已支持从 `message.routeData` 和 `routeSnapshot.route_data` 读取；
- `buildPanelDays()` 已复制 `recommend_reason`；
- `RoutePlacesList.tsx` 已在评分下方渲染非空理由。

仍建议增加审计日志：

```ts
console.log('[PoiReasonFrontendAudit]', {
  backendPointReasonCount,
  panelReasonCount,
  flatPoiReasonCount,
  namesWithReason,
});
```

若后端 point reason 非空而右侧仍为空，再检查：

- `buildPanelDays()` 是否绑定了同一个 POI；
- `panelDays` 是否被后续旧状态覆盖；
- 历史路线恢复是否丢失字段；
- `RoutePlacesList` 是否拿到最新 `points` 与 `panelDays`。

## 7. 验收用例

### 用例 A：自由探索

```text
想去周围的公园逛逛，求推荐
```

期望：

- 左侧“为什么推荐”出现一次；
- 右侧“官园公园”等真实 POI 下方出现独立理由；
- `valid_reason_count >= 1`；
- `point_reason_count >= 1`。

### 用例 B：明确偏好

```text
找个周围适合情侣约会和拍照的地方
```

期望：

- 路线级理由明确关联“情侣约会、拍照、周围”；
- 每个 POI 理由说明自身特点、偏好匹配和路线安排价值；
- 不允许只写“环境优美、值得一去”。

### 用例 C：精准规划

```text
明早去故宫，明天下午去天坛公园
```

期望：

- planned 模式同样生成左侧路线理由；
- 右侧故宫、天坛公园分别有理由；
- 不因模式不同跳过理由生成。

### 用例 D：无可靠证据

让 DeepSeek 返回空字段或无 evidence：

- 对应理由保持为空；
- 不生成通用兜底；
- 路线本身仍正常输出。

## 8. 重要产品约束

- 不改变 Step1 总体逻辑，只补充字段传递和后置协调。
- 不删除或绕过 `PlanRealityAudit`。
- 不硬编码城市或 POI 名称。
- 不重复建立已有主题画像或类别映射。
- 不使用“本次搜索的核心目标”作为推荐理由。
- 无合理 JSON 或证据时直接留空。
- 左侧理由是整条路线总结，位置在路线卡片下方。
- 右侧理由是单个 POI 理由，位置在评分信息下方。
- 两者都必须关联用户真实偏好，不能互相简单复制。

## 9. 其他已知问题（非当前最高优先级）

1. 雨天公园请求仍出现 `before_filter=12 after_filter=1`，说明户外硬过滤可能仍然过强。
2. “外滩一整天”测试曾出现北京出发点连接上海 POI、路线间隔约 1062km、`required_fixed_anchor_missing: 外滩`，城市切换和固定锚点保留仍需独立修复。
3. 社交场景画像 `relationship_group_scenarios` 已存在，不应重复创建；此前的问题是抽象主题与可执行 POI 原型、主题验真之间没有完全打通。

## 10. 关键文件

- `backend/services/reason_generator.py`
- `backend/routers/meituan_chat.py`
- `backend/services/step4_output.py`
- `backend/services/data_schema.py`
- `frontend/src/hooks/useChat.ts`
- `frontend/src/components/ChatPanel/ChatPanel.tsx`
- `frontend/src/components/ItinerarySidebar/RoutePlacesList.tsx`
- `frontend/src/components/ItinerarySidebar/PoiRouteCard.tsx`
- `frontend/src/store/routeStore.ts`

## 11. 完成标准

不能只以单元测试或编译通过作为完成。必须：

1. 重建 backend、frontend 容器；
2. 在 `http://localhost/app` 真实提交上述请求；
3. 检查后端 ReasonAudit/ReasonSummary/TransportAudit；
4. 检查前端 RouteReasonFrontendAudit/PoiReasonFrontendAudit；
5. DOM 中左侧理由数量大于 0；
6. 右侧 `routePlaceReason` 节点数量大于 0；
7. 刷新并打开规划历史后理由仍能恢复；
8. 连续生成两条路线时理由不会串线或重复。
