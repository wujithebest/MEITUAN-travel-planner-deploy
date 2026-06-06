# 聊天界面组件

## 概述

聊天界面是一个类似 Kimi 的三栏式聊天布局，用于旅行协作规划。

## 组件结构

```
ChatPage/
├── index.tsx              # 主页面组件
├── ChatPage.module.css    # 页面样式
└── README.md              # 本文件

components/
├── Sidebar/               # 左侧房间列表
│   ├── index.tsx
│   └── Sidebar.module.css
├── ChatArea/              # 中间聊天区域
│   ├── index.tsx
│   └── ChatArea.module.css
├── MessageBubble/         # 消息气泡组件
│   ├── index.tsx
│   └── MessageBubble.module.css
├── AgentPanel/            # 右侧AI助手面板
│   ├── index.tsx
│   └── AgentPanel.module.css
└── RouteCard/             # 路线卡片组件
    ├── index.tsx
    └── RouteCard.module.css
```

## 功能特性

### 1. 左侧房间列表 (Sidebar)
- 显示所有旅行群聊房间
- 显示最后一条消息预览
- 显示未读消息数量
- 支持创建新群聊

### 2. 中间聊天区域 (ChatArea)
- 消息列表自动滚动
- 支持文本消息
- 支持路线卡片、地点卡片
- 支持图片和位置分享
- 表情选择器
- Enter 发送，Shift+Enter 换行

### 3. 消息气泡 (MessageBubble)
- 区分自己/他人消息
- AI 消息特殊样式
- 支持多种内容类型
- 显示发送时间

### 4. 右侧AI助手面板 (AgentPanel)
- 实时识别旅行意图
- 提取讨论中提到的地点
- 一键生成路线预览
- 快捷操作按钮

### 5. 路线卡片 (RouteCard)
- 显示路线概览
- 途经地点列表
- 总距离和预计用时
- 查看详情和地图查看

## 路由

- `/chat` - 聊天页面（需要登录）

## WebSocket 连接

WebSocket URL: `ws://localhost:8002/ws/room/{roomId}?token={token}`

消息类型:
- `new_message` - 新消息
- `typing` - 正在输入
- `member_online` - 成员上线
- `member_offline` - 成员下线
- `history` - 历史消息

## 类型定义

详见 `types/chat.ts`

## 使用示例

```tsx
import ChatPage from './pages/ChatPage';

// 在路由中使用
<Route path="/chat" element={<ChatPage />} />
```

## 验证标准

1. 创建群聊 → 邀请好友 → 自由聊天
2. 发送"周末去徐汇吃本帮菜" → AI自动识别"徐汇""美食""周末"
3. 右侧面板显示：地点"徐汇区"、主题"美食"
4. @旅行助手 → AI回复具体建议
5. 讨论充分后点击"生成路线" → 聊天流出现路线卡片
6. 卡片含地图预览、每日安排、可点击跳转详细页
