# 右侧行程栏不显示问题修复摘要

## 问题描述
行程规划完成后，右侧行程栏没有弹出显示。

## 根本原因
1. `PlannerPage` 使用 `useItinerary` hook 管理右侧栏状态
2. `ChatPanel` 使用 `useChat` hook 处理 SSE 连接和聊天
3. **关键问题**：`useChat` hook 在收到 SSE `result` 事件后，只更新了聊天消息，但从未调用 `useItinerary` 的 `completePlanning` 方法来显示右侧栏

## 修复方案

### 1. 修改 `ChatPanel` 组件 (src/components/ChatPanel/ChatPanel.tsx)
- 将 `ChatPanel` 从内部使用 `useChat` hook 改为通过 props 接收数据
- 添加 `onPlanningComplete` 回调 prop
- 添加 `useEffect` 检测 `isLoading` 从 `true` 变为 `false` 的时刻（规划完成）
- 当检测到规划完成时，调用 `onPlanningComplete` 回调并传递最后一条 AI 消息内容

### 2. 修改 `PlannerPage` 组件 (src/pages/PlannerPage/PlannerPage.tsx)
- 在 `PlannerPage` 中使用 `useChat` hook（单一数据源）
- 将 `chat` 的状态和方法作为 props 传递给 `ChatPanel`
- 添加 `onPlanningComplete` 回调，调用 `itinerary.completePlanning(resultText, [])` 显示右侧栏

## 数据流
```
用户输入 → ChatPanel → sendMessage (useChat)
    ↓
SSE 连接 → 收到 result 事件 → 更新 messages
    ↓
isLoading: true → false → 触发 onPlanningComplete
    ↓
PlannerPage.onPlanningComplete → itinerary.completePlanning()
    ↓
parseItinerary() 解析文本 → setIsVisible(true)
    ↓
ItinerarySidebar 显示
```

## 关键代码

### ChatPanel 中的规划完成检测
```typescript
useEffect(() => {
  const wasLoading = prevIsLoadingRef.current;
  
  // 检测从加载状态变为非加载状态（规划完成）
  if (wasLoading && !isLoading && onPlanningComplete) {
    const lastAiMessage = [...messages].reverse().find(m => m.role === 'assistant');
    if (lastAiMessage && lastAiMessage.content && lastAiMessage.content.length > 20) {
      onPlanningComplete(lastAiMessage.content);
    }
  }
  
  prevIsLoadingRef.current = isLoading;
}, [isLoading, messages, onPlanningComplete]);
```

### PlannerPage 中的回调处理
```typescript
<ChatPanel
  messages={chat.messages}
  isLoading={chat.isLoading}
  // ... 其他 props
  onPlanningComplete={(resultText) => {
    console.log('[PlannerPage] 规划完成，触发行程侧边栏显示');
    itinerary.completePlanning(resultText, []);
  }}
/>
```

## 测试步骤
1. 启动前端开发服务器
2. 打开浏览器控制台
3. 选择规划模式（1 或 2）
4. 输入出行需求并发送
5. 观察控制台输出：
   - `[ChatPanel] 检测到规划完成`
   - `[PlannerPage] 规划完成，触发行程侧边栏显示`
   - `[useItinerary] 完成规划，结果文本长度: ...`
6. 右侧栏应该自动滑入显示

## 文件修改列表
- `src/components/ChatPanel/ChatPanel.tsx` - 重构为受控组件，添加规划完成检测
- `src/pages/PlannerPage/PlannerPage.tsx` - 连接 useChat 和 useItinerary
