# 消息渲染层 (Message Renderer)

消息渲染层是一个完整的消息处理系统，提供了消息去重、状态同步、群聊处理和异常检测等功能。

## 功能特性

### 1. 消息去重机制
- 基于 `message_id` 的去重
- 基于 `user_id + content + timestamp` 的指纹去重
- 5秒去重窗口时间
- 自动清理过期记录

### 2. 状态同步规则
- 本地发送的消息先进入 "pending" 状态
- 收到服务端 ACK 后转为 "confirmed" 状态
- 防止本地和服务端重复渲染

### 3. 群聊特殊处理
- 群消息必须携带 `sender_id` + `group_id` 组合校验
- 同一条群消息通过广播到达时，所有接收方用统一 `message_id` 去重

### 4. 异常兜底
- 连续3条相同内容消息自动触发"消息去重异常"告警
- 向用户显示"检测到重复消息，已自动过滤"（仅一次）

## 文件结构

```
src/
├── utils/
│   └── messageRenderer.ts          # 核心消息渲染器
├── hooks/
│   └── useMessageRenderer.ts       # React Hook 集成
├── components/
│   ├── MessageList.tsx             # 消息列表组件
│   └── DuplicateAlert.tsx          # 重复消息告警组件
├── styles/
│   └── messageRenderer.css         # 消息渲染器样式
├── __tests__/
│   └── messageRenderer.test.ts     # 单元测试
└── examples/
    ├── MessageRendererExample.tsx  # 使用示例
    └── messageRendererExample.css  # 示例样式
```

## 使用方法

### 基础使用

```tsx
import React from 'react';
import { useMessageRenderer } from './hooks/useMessageRenderer';
import { MessageList } from './components/MessageList';
import { DuplicateAlert } from './components/DuplicateAlert';

const ChatComponent = () => {
  const {
    messages,
    sendMessage,
    receiveMessage,
    showDuplicateAlert,
    clearDuplicateAlert
  } = useMessageRenderer();

  const handleSendMessage = (content: string) => {
    sendMessage('user1', content);
  };

  return (
    <div>
      <DuplicateAlert 
        show={showDuplicateAlert} 
        onClear={clearDuplicateAlert} 
      />
      <MessageList messages={messages} currentUserId="user1" />
    </div>
  );
};
```

### 群聊使用

```tsx
const handleGroupMessage = (content: string) => {
  sendMessage('user1', content, {
    group_id: 'group1',
    sender_id: 'user1'
  });
};
```

### 接收服务端消息

```tsx
const handleServerMessage = (serverMessage) => {
  receiveMessage({
    ...serverMessage,
    status: 'confirmed'
  });
};
```

## API 文档

### useMessageRenderer Hook

返回以下属性和方法：

#### 属性
- `messages: Message[]` - 所有消息列表
- `pendingMessages: Message[]` - 待确认消息列表
- `showDuplicateAlert: boolean` - 是否显示重复消息告警

#### 方法
- `sendMessage(userId: string, content: string, options?: Partial<Message>): boolean` - 发送消息
- `receiveMessage(message: Message): boolean` - 接收服务端消息
- `confirmMessage(messageId: string): void` - 确认本地消息
- `clearDuplicateAlert(): void` - 清除重复消息告警

### Message 接口

```typescript
interface Message {
  message_id: string;        // 消息唯一标识
  user_id: string;           // 用户ID
  content: string;           // 消息内容
  timestamp: number;         // 时间戳
  status: MessageStatus;     // 消息状态
  sender_id?: string;        // 发送者ID（群聊）
  group_id?: string;         // 群聊ID
}
```

### createMessage 函数

创建消息对象的工厂函数：

```typescript
const message = createMessage('user1', '你好', {
  group_id: 'group1',
  sender_id: 'user1'
});
```

## 测试

运行单元测试：

```bash
npm test messageRenderer
```

测试覆盖：
- 消息去重机制
- 状态同步规则
- 群聊特殊处理
- 异常兜底机制
- 消息队列管理

## 样式定制

所有样式都使用 CSS 类名，可以通过覆盖以下类名来自定义样式：

- `.message-list` - 消息列表容器
- `.message-item` - 消息项
- `.own-message` - 自己的消息
- `.other-message` - 其他人的消息
- `.message-status` - 消息状态
- `.duplicate-alert` - 重复消息告警

## 注意事项

1. **去重窗口**: 5秒内相同内容+相同发送者的消息会被自动过滤
2. **状态管理**: 消息发送后会自动进入pending状态，需要手动确认或等待服务端ACK
3. **群聊处理**: 群消息必须包含 `group_id` 和 `sender_id`
4. **异常检测**: 连续3条相同内容消息会触发告警，10秒内只显示一次

## 示例

查看 `examples/MessageRendererExample.tsx` 获取完整的使用示例。
