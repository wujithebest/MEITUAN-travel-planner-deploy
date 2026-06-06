# 意图处理流水线 - 闭环机制实现

## 概述

本模块实现了完整的意图处理流水线，确保"识别→执行→反馈"全链路闭环。解决了用户请求后系统无响应的问题。

## 核心功能

### 1. 强制响应契约

- 意图识别成功后（confidence > 0.7），2秒内产生用户可见反馈
- 无论执行结果如何，禁止"静默失败"
- 响应类型分级：
  - 执行成功 → 返回结果 + 友好总结
  - 执行中（异步）→ 立即返回"正在处理，请稍候..." + 进度更新
  - 执行失败 → 明确告知失败原因 + 替代方案建议
  - 需要澄清 → 返回追问，不得空响应

### 2. 防断链机制

- 每个意图节点设置3秒超时熔断
- 超时后若未收到下游响应，自动触发兜底回复
- 记录断链日志：intent_type | user_input | break_point | timestamp

### 3. 响应组装校验

- 最终输出到前端前，检查 response.content 非空且长度 > 0
- 若为空，用兜底模板填充：
  - 查询类："已为您查到相关信息：[摘要]"
  - 操作类："已完成[操作名]，您可以继续下一步"
  - 规划类："正在为您规划，这是初步方案："

### 4. 端到端追踪

- 每个用户请求生成 trace_id，贯穿意图识别→工具调用→响应生成
- 响应必须携带 trace_id，前端用于关联"用户说了什么"和"助手回了什么"

## 文件结构

```
backend/
├── services/
│   ├── intent_pipeline.py      # 流水线核心模块
│   ├── intent_handlers.py      # 意图处理器
│   └── intent_extractor.py     # 意图提取器（已有）
├── routers/
│   └── chat.py                 # 聊天路由（已集成流水线）
└── tests/
    └── test_intent_pipeline.py # 流水线测试

frontend/src/components/
├── ResponseStatus.tsx          # 响应状态组件
└── ResponseStatus.css          # 响应状态样式
```

## 使用示例

### 后端使用

```python
from services.intent_pipeline import (
    IntentPipeline, 
    IntentResult, 
    IntentType,
    init_pipeline
)

# 初始化流水线
pipeline = init_pipeline()

# 创建意图结果
intent_result = IntentResult(
    intent_type=IntentType.TRAVEL_PLANNING,
    confidence=0.92,
    entities={"destination": "上海", "days": 3},
    raw_input="规划上海3日游"
)

# 处理意图
response = await pipeline.process(
    user_input="规划上海3日游",
    intent_result=intent_result
)

# 响应自动包含 trace_id 和内容
print(response.trace_id)   # 追踪ID
print(response.content)    # 响应内容（保证非空）
print(response.status)     # 处理状态
```

### 前端使用

```tsx
import { ResponseStatus, ProcessingIndicator, ErrorAlert } from './components/ResponseStatus';

// 显示处理状态
<ResponseStatus
  status="success"
  message="已为您规划好上海3日游路线！"
  traceId="xxx-xxx-xxx"
  processingTimeMs={150}
  onRetry={() => retry()}
/>

// 简化版处理中指示器
<ProcessingIndicator message="正在规划路线，请稍候..." />

// 错误提示
<ErrorAlert
  message="处理失败，请重试"
  traceId="xxx-xxx-xxx"
  onRetry={() => retry()}
/>
```

## 支持的意图类型

| 意图类型 | 描述 | 示例 |
|---------|------|------|
| TRAVEL_PLANNING | 旅行规划 | "规划北京3日游" |
| ROUTE_GENERATION | 路线生成 | "上海到杭州怎么走" |
| POI_QUERY | 地点查询 | "迪士尼门票多少钱" |
| WEATHER_QUERY | 天气查询 | "上海明天天气" |
| CHAT_MESSAGE | 普通聊天 | "你好"、"谢谢" |

## 测试

运行测试验证闭环机制：

```bash
cd backend
pytest tests/test_intent_pipeline.py -v
```

测试覆盖：
- 正常处理流程
- 2秒内响应保证
- 超时熔断机制
- 空响应兜底
- 低置信度处理
- 错误处理
- trace_id 贯穿
- 断链日志记录
- 并发处理

## 注意事项

1. 所有处理器必须返回 `PipelineResponse` 对象
2. 响应内容不能为空字符串，否则会触发兜底模板
3. 处理器执行时间不应超过3秒，否则会触发超时熔断
4. trace_id 用于追踪请求全流程，应记录到日志中
