# 聊天模块 API 文档

## 概述

旅行群聊+AI助手模块，支持多人实时协作规划旅行。

## 架构

```
┌─────────────────────────────────────────────────────────────┐
│                        客户端                                │
├─────────────────────────────────────────────────────────────┤
│  ┌──────────┐  ┌──────────────────┐  ┌──────────────────┐   │
│  │ 房间列表  │  │     聊天流        │  │   AI助手面板     │   │
│  │ (左侧)   │  │     (中间)        │  │    (右侧)        │   │
│  └──────────┘  └──────────────────┘  └──────────────────┘   │
└─────────────────────────────────────────────────────────────┘
                              │
                              ▼
┌─────────────────────────────────────────────────────────────┐
│                       WebSocket                              │
│                  /api/chat/ws/room/{room_id}                 │
└─────────────────────────────────────────────────────────────┘
                              │
                              ▼
┌─────────────────────────────────────────────────────────────┐
│                      FastAPI 后端                            │
├─────────────────────────────────────────────────────────────┤
│  ┌──────────────┐  ┌──────────────┐  ┌──────────────────┐  │
│  │ Connection   │  │  TravelAgent │  │ IntentExtractor  │  │
│  │ Manager      │  │  (AI助手)    │  │ (意图提取器)      │  │
│  └──────────────┘  └──────────────┘  └──────────────────┘  │
└─────────────────────────────────────────────────────────────┘
```

## WebSocket API

### 连接

```
WS /api/chat/ws/room/{room_id}
```

需要在查询参数或头部携带认证token。

### 消息类型

#### 客户端发送

##### 1. 发送消息
```json
{
  "type": "message",
  "content_type": "text",
  "text": "我们想去上海玩3天",
  "reply_to": null
}
```

##### 2. 正在输入
```json
{
  "type": "typing"
}
```

##### 3. 已读回执
```json
{
  "type": "read_ack",
  "last_message_id": "msg_xxx"
}
```

##### 4. 加入房间
```json
{
  "type": "join_room"
}
```

##### 5. 离开房间
```json
{
  "type": "leave_room"
}
```

#### 服务端发送

##### 1. 新消息
```json
{
  "type": "new_message",
  "data": {
    "id": "msg_xxx",
    "room_id": "room_xxx",
    "sender": {
      "id": "user_xxx",
      "name": "张三",
      "avatar": "/avatar.png",
      "is_agent": false
    },
    "content": {
      "type": "text",
      "text": "我们想去上海玩3天"
    },
    "timestamp": "2024-01-01T12:00:00"
  }
}
```

##### 2. 成员上线
```json
{
  "type": "member_online",
  "data": {
    "user_id": "user_xxx",
    "timestamp": "2024-01-01T12:00:00"
  }
}
```

##### 3. 成员离线
```json
{
  "type": "member_offline",
  "data": {
    "user_id": "user_xxx"
  }
}
```

##### 4. 正在输入指示器
```json
{
  "type": "typing_indicator",
  "data": {
    "user_id": "user_xxx",
    "username": "张三"
  }
}
```

##### 5. 意图更新
```json
{
  "type": "intent_updated",
  "data": {
    "destination": "上海",
    "days": 3,
    "themes": ["美食", "历史"],
    "confidence": 0.6,
    "last_updated": "2024-01-01T12:00:00"
  }
}
```

## REST API

### 房间管理

#### 创建房间
```http
POST /api/chat/rooms
Content-Type: application/json

{
  "name": "五一上海游",
  "description": "五一假期上海3日游",
  "avatar": "/room-avatar.png",
  "initial_members": ["user_xxx", "user_yyy"]
}
```

响应：
```json
{
  "success": true,
  "data": {
    "id": "room_xxx",
    "name": "五一上海游",
    "creator_id": "user_xxx",
    "members": [...],
    "created_at": "2024-01-01T12:00:00"
  },
  "message": "房间创建成功"
}
```

#### 获取房间列表
```http
GET /api/chat/rooms
```

响应：
```json
{
  "success": true,
  "data": [
    {
      "id": "room_xxx",
      "name": "五一上海游",
      "avatar": "/room-avatar.png",
      "last_message": {
        "text": "我们想去上海玩3天",
        "sender_name": "张三",
        "timestamp": "2024-01-01T12:00:00"
      },
      "unread_count": 5,
      "member_count": 3,
      "is_online": true,
      "updated_at": "2024-01-01T12:00:00"
    }
  ]
}
```

#### 获取房间详情
```http
GET /api/chat/rooms/{room_id}
```

#### 更新房间设置
```http
PUT /api/chat/rooms/{room_id}/settings
Content-Type: application/json

{
  "is_private": false,
  "allow_invite": true,
  "agent_enabled": true,
  "agent_personality": "friendly"
}
```

### 消息管理

#### 获取消息历史
```http
GET /api/chat/rooms/{room_id}/messages?before=msg_xxx&limit=20
```

响应：
```json
{
  "success": true,
  "data": {
    "messages": [...],
    "has_more": true,
    "next_cursor": "msg_yyy"
  }
}
```

#### 发送消息（REST方式）
```http
POST /api/chat/rooms/{room_id}/messages
Content-Type: application/json

{
  "content_type": "text",
  "text": "推荐一些美食",
  "reply_to": null
}
```

### 成员管理

#### 添加成员
```http
POST /api/chat/rooms/{room_id}/members?member_id=user_xxx
```

### 意图和路线

#### 获取当前意图
```http
GET /api/chat/rooms/{room_id}/intent
```

响应：
```json
{
  "success": true,
  "data": {
    "destination": "上海徐汇区",
    "days": 3,
    "themes": ["美食", "历史"],
    "must_visit": ["外滩", "豫园"],
    "preferences": ["不爬山"],
    "budget_level": "中等",
    "travelers": ["情侣"],
    "confidence": 0.8,
    "last_updated": "2024-01-01T12:00:00"
  }
}
```

#### 根据群聊生成路线
```http
POST /api/chat/rooms/{room_id}/generate-route
```

响应：
```json
{
  "success": true,
  "data": {
    "id": "route_xxx",
    "name": "上海徐汇区3日游",
    "summary": "3天上海徐汇区精选路线",
    "pois": [...]
  },
  "message": "路线生成成功"
}
```

## AI助手行为

### 触发条件

AI助手会在以下情况主动发言：

1. **被@提及**：消息中包含 `@旅行助手`、`@小游` 或 `@AI`
2. **旅行相关问题**：消息包含关键词如"怎么玩"、"推荐"、"攻略"等
3. **信息充足**：意图完整度 > 0.8 且距离上次发言 > 5分钟
4. **用户请求**：消息包含"生成路线"、"帮我规划"等
5. **新成员加入**：有新成员加入群聊

### 回应策略

| 意图完整度 | 行为 |
|-----------|------|
| < 0.3 | 引导提问，收集关键信息 |
| 0.3 - 0.7 | 给出建议，询问补充信息 |
| > 0.7 | 生成路线预览 |

### 意图提取字段

| 字段 | 说明 | 示例 |
|------|------|------|
| destination | 目的地 | "上海徐汇区" |
| days | 天数 | 3 |
| dates | 日期范围 | ("2024-05-01", "2024-05-03") |
| themes | 主题 | ["美食", "历史"] |
| must_visit | 必去地点 | ["外滩", "豫园"] |
| preferences | 偏好限制 | ["不爬山", "少走路"] |
| budget_level | 预算等级 | "中等" |
| travelers | 同行人类型 | ["亲子", "情侣"] |
| confidence | 完整度 | 0.8 |

## 消息内容类型

| 类型 | 说明 |
|------|------|
| text | 文本消息 |
| image | 图片消息 |
| location | 位置分享 |
| route_card | 路线卡片 |
| poi_card | POI卡片 |
| itinerary_preview | 路线预览 |
| system_notice | 系统通知 |

## 使用示例

### JavaScript WebSocket 客户端

```javascript
class ChatClient {
  constructor(roomId, token) {
    this.roomId = roomId;
    this.token = token;
    this.ws = null;
    this.messageHandlers = [];
  }

  connect() {
    this.ws = new WebSocket(
      `ws://localhost:8002/api/chat/ws/room/${this.roomId}?token=${this.token}`
    );

    this.ws.onopen = () => {
      console.log('Connected to chat room');
    };

    this.ws.onmessage = (event) => {
      const data = JSON.parse(event.data);
      this.handleMessage(data);
    };

    this.ws.onclose = () => {
      console.log('Disconnected from chat room');
    };

    this.ws.onerror = (error) => {
      console.error('WebSocket error:', error);
    };
  }

  handleMessage(data) {
    switch (data.type) {
      case 'new_message':
        this.messageHandlers.forEach(handler => handler(data.data));
        break;
      case 'member_online':
        console.log('Member online:', data.data.user_id);
        break;
      case 'member_offline':
        console.log('Member offline:', data.data.user_id);
        break;
      case 'typing_indicator':
        console.log('Typing:', data.data.username);
        break;
      case 'intent_updated':
        console.log('Intent updated:', data.data);
        break;
    }
  }

  sendMessage(text, contentType = 'text') {
    this.ws.send(JSON.stringify({
      type: 'message',
      content_type: contentType,
      text: text
    }));
  }

  sendTyping() {
    this.ws.send(JSON.stringify({
      type: 'typing'
    }));
  }

  markRead(lastMessageId) {
    this.ws.send(JSON.stringify({
      type: 'read_ack',
      last_message_id: lastMessageId
    }));
  }

  onMessage(handler) {
    this.messageHandlers.push(handler);
  }

  disconnect() {
    this.ws.close();
  }
}

// 使用示例
const client = new ChatClient('room_xxx', 'your_token');
client.connect();

client.onMessage((message) => {
  console.log('New message:', message);
  // 渲染消息到UI
});

// 发送消息
client.sendMessage('我们想去上海玩3天');

// 触发AI回应
client.sendMessage('@旅行助手 有什么推荐？');
```

### React Hook 示例

```typescript
import { useState, useEffect, useCallback } from 'react';

interface ChatMessage {
  id: string;
  sender: {
    id: string;
    name: string;
    avatar: string;
    is_agent: boolean;
  };
  content: {
    type: string;
    text?: string;
    route_data?: any;
  };
  timestamp: string;
}

export function useChat(roomId: string, token: string) {
  const [messages, setMessages] = useState<ChatMessage[]>([]);
  const [ws, setWs] = useState<WebSocket | null>(null);
  const [connected, setConnected] = useState(false);
  const [typingUsers, setTypingUsers] = useState<string[]>([]);

  useEffect(() => {
    const websocket = new WebSocket(
      `ws://localhost:8002/api/chat/ws/room/${roomId}?token=${token}`
    );

    websocket.onopen = () => setConnected(true);
    websocket.onclose = () => setConnected(false);
    
    websocket.onmessage = (event) => {
      const data = JSON.parse(event.data);
      
      if (data.type === 'new_message') {
        setMessages(prev => [...prev, data.data]);
      } else if (data.type === 'typing_indicator') {
        setTypingUsers(prev => [...prev, data.data.username]);
        setTimeout(() => {
          setTypingUsers(prev => prev.filter(u => u !== data.data.username));
        }, 3000);
      }
    };

    setWs(websocket);

    return () => websocket.close();
  }, [roomId, token]);

  const sendMessage = useCallback((text: string) => {
    if (ws && ws.readyState === WebSocket.OPEN) {
      ws.send(JSON.stringify({
        type: 'message',
        content_type: 'text',
        text
      }));
    }
  }, [ws]);

  const sendTyping = useCallback(() => {
    if (ws && ws.readyState === WebSocket.OPEN) {
      ws.send(JSON.stringify({ type: 'typing' }));
    }
  }, [ws]);

  return {
    messages,
    connected,
    typingUsers,
    sendMessage,
    sendTyping
  };
}
```

## 错误代码

| 代码 | 说明 |
|------|------|
| 4001 | 认证失败 |
| 4003 | 不在房间中 |
| 4004 | 房间不存在 |

## 注意事项

1. **认证**：所有请求需要有效的用户token
2. **权限**：只有房间成员可以发送消息
3. **频率限制**：建议客户端实现消息发送频率限制
4. **重连**：WebSocket断开后需要实现自动重连机制
5. **AI响应**：AI响应是异步的，不会立即返回
