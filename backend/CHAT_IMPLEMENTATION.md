# 聊天模块实现总结

## 概述

已成功将多人协作重构为"旅行群聊+AI助手"模式，类似现代IM应用（Kimi/微信）。

## 文件结构

```
backend/
├── models/
│   └── chat.py                 # 核心聊天模型
├── services/
│   ├── intent_extractor.py     # 意图提取器
│   └── agent_service.py        # AI助手核心
├── routers/
│   └── chat.py                 # WebSocket + REST API
├── CHAT_API.md                 # API文档
└── CHAT_IMPLEMENTATION.md      # 本文档
```

## 核心组件

### 1. models/chat.py - 核心模型

#### ChatRoom（聊天室）
- 房间基本信息（名称、头像、描述）
- 成员列表
- 最后消息预览
- 未读数
- 房间设置
- AI提取的旅行意图

#### ChatMessage（聊天消息）
- 支持多类型内容（text, image, location, route_card, poi_card, itinerary_preview, system_notice）
- 发送者信息（用户或AI）
- 回复功能
- 表情反应

#### TravelIntent（旅行意图）
- 从群聊中累计提取的旅行意图
- 包含：目的地、天数、日期、主题、必去地点、偏好、预算、同行人
- 信息完整度评分（confidence）

#### AgentAction（AI动作）
- AI助手的决策结果
- 包含：动作类型、回复内容、路线草稿、澄清问题

### 2. services/intent_extractor.py - 意图提取器

功能：
- 从群聊历史中提取旅行意图
- 使用LLM分析对话内容
- 支持增量提取和意图合并
- 计算信息完整度

提取字段：
- destination: 目的地
- days: 天数
- dates: 日期范围
- themes: 主题（美食、历史、文艺等）
- must_visit: 必去地点
- preferences: 偏好限制
- budget_level: 预算等级
- travelers: 同行人类型
- confidence: 完整度评分

### 3. services/agent_service.py - AI助手核心

TravelAgent类：
- 实时分析群聊内容
- 自然参与对话
- 回答问题，给出建议
- 生成路线预览
- 引导提问收集信息

触发条件：
1. 被@提及（@旅行助手、@小游、@AI）
2. 旅行相关问题
3. 信息充足且长时间未发言
4. 用户明确请求生成路线
5. 新成员加入

回应策略：
| 意图完整度 | 行为 |
|-----------|------|
| < 0.3 | 引导提问，收集关键信息 |
| 0.3 - 0.7 | 给出建议，询问补充信息 |
| > 0.7 | 生成路线预览 |

### 4. routers/chat.py - API路由

#### WebSocket端点
```
WS /api/chat/ws/room/{room_id}
```

支持的消息类型：
- message: 发送消息
- typing: 正在输入
- read_ack: 已读回执
- join_room: 加入房间
- leave_room: 离开房间

#### REST API端点

| 方法 | 路径 | 说明 |
|------|------|------|
| POST | /api/chat/rooms | 创建聊天室 |
| GET | /api/chat/rooms | 获取房间列表 |
| GET | /api/chat/rooms/{room_id} | 获取房间详情 |
| PUT | /api/chat/rooms/{room_id}/settings | 更新房间设置 |
| GET | /api/chat/rooms/{room_id}/messages | 获取消息历史 |
| POST | /api/chat/rooms/{room_id}/messages | 发送消息 |
| POST | /api/chat/rooms/{room_id}/members | 添加成员 |
| GET | /api/chat/rooms/{room_id}/intent | 获取当前意图 |
| POST | /api/chat/rooms/{room_id}/generate-route | 生成路线 |

## 数据流

```
用户发送消息
    ↓
WebSocket广播
    ↓
保存消息
    ↓
触发AI分析
    ↓
AI提取意图
    ↓
决策回应
    ↓
保存AI消息
    ↓
广播AI消息
    ↓
更新房间意图
```

## 使用示例

### 创建房间
```bash
curl -X POST http://localhost:8002/api/chat/rooms \
  -H "Content-Type: application/json" \
  -H "Authorization: Bearer <token>" \
  -d '{
    "name": "五一上海游",
    "description": "五一假期上海3日游"
  }'
```

### 发送消息
```bash
curl -X POST http://localhost:8002/api/chat/rooms/{room_id}/messages \
  -H "Content-Type: application/json" \
  -H "Authorization: Bearer <token>" \
  -d '{
    "content_type": "text",
    "text": "我们想去上海玩3天"
  }'
```

### WebSocket连接
```javascript
const ws = new WebSocket(
  'ws://localhost:8002/api/chat/ws/room/{room_id}?token={token}'
);

ws.onmessage = (event) => {
  const data = JSON.parse(event.data);
  console.log('Received:', data);
};

// 发送消息
ws.send(JSON.stringify({
  type: 'message',
  content_type: 'text',
  text: '@旅行助手 有什么推荐？'
}));
```

## 前端UI结构

```
┌─────────────────────────────────────────────────────────────┐
│                         顶部导航栏                           │
├──────────┬──────────────────────────────────┬───────────────┤
│          │                                  │               │
│  房间列表 │          聊天流                  │  AI助手面板   │
│          │                                  │               │
│ ┌──────┐ │  ┌────────────────────────────┐  │  ┌─────────┐ │
│ │房间1 │ │  │ 张三: 我们想去上海玩3天    │  │  │意图提取 │ │
│ │房间2 │ │  │                            │  │  │进度: 60%│ │
│ │房间3 │ │  │ 旅行助手: 好的！还需要... │  │  │         │ │
│ └──────┘ │  │                            │  │  │[生成路线]│ │
│          │  └────────────────────────────┘  │  └─────────┘ │
│          │  [输入框...              ] [发送] │               │
└──────────┴──────────────────────────────────┴───────────────┘
```

## 特性

### ✅ 已实现
- [x] WebSocket实时通信
- [x] 房间管理（创建、列表、详情）
- [x] 消息管理（发送、历史、分页）
- [x] 成员管理（添加、在线状态）
- [x] AI意图提取
- [x] AI自动回应
- [x] 意图完整度评估
- [x] 路线生成触发
- [x] 已读回执
- [x] 正在输入指示器
- [x] 多类型消息支持

### 🔄 待优化
- [ ] 数据库持久化（当前为内存存储）
- [ ] 消息搜索
- [ ] 文件上传
- [ ] 消息撤回
- [ ] 消息编辑
- [ ] 更丰富的AI回应模板
- [ ] 多语言支持

## 测试

运行测试：
```bash
cd backend
python -m pytest test_chat.py -v
```

## 注意事项

1. **认证**：所有请求需要有效的JWT token
2. **权限**：只有房间成员可以发送消息
3. **AI响应**：AI响应是异步的，不会立即返回
4. **WebSocket**：需要实现自动重连机制
5. **数据库**：当前使用内存存储，生产环境需要替换为MongoDB

## 与现有系统的集成

聊天模块已集成到现有系统中：
- 复用现有用户认证系统
- 复用现有路线规划服务
- 复用现有LLM解析服务
- 注册到main.py的路由系统中

## 下一步

1. 实现前端聊天界面
2. 添加数据库持久化
3. 优化AI回应质量
4. 添加更多消息类型支持
5. 实现消息搜索功能
