# SSE连接修复总结

## 修复内容

### 1. 新增 `streamPlanRoute` 函数 (`frontend/src/api/plan.ts`)

使用 `fetch` + `ReadableStream` 替代原生 `EventSource`，解决了以下问题：

- ✅ **支持POST请求和自定义Header** - EventSource只支持GET，新函数使用fetch支持完整的HTTP功能
- ✅ **超时处理** - 默认30秒超时，可通过参数自定义
- ✅ **详细的错误分类** - 区分连接错误、超时错误、服务器错误、解析错误
- ✅ **用户友好的错误提示** - 每种错误类型都包含具体的解决建议

### 2. 新增错误类型定义 (`frontend/src/api/plan.ts`)

```typescript
export type PlanErrorType = 'connection' | 'timeout' | 'server' | 'parse' | 'unknown';

export interface PlanError {
  type: PlanErrorType;
  message: string;
  details?: string;        // 详细描述
  suggestions?: string[];  // 解决建议列表
}
```

### 3. 新增 `ErrorDisplay` 组件 (`frontend/src/components/ErrorDisplay/`)

专门用于展示详细的错误信息：

- ✅ 根据错误类型显示不同的图标和标题
- ✅ 显示详细的错误描述
- ✅ 列出可能的原因和解决方案
- ✅ 提供重试按钮（普通重试和简化需求重试）
- ✅ 开发环境下显示诊断按钮
- ✅ 响应式设计，支持移动端

### 4. 更新 `AIChatPanel` 组件 (`frontend/src/components/AIChatPanel/index.tsx`)

- ✅ 集成新的 `streamPlanRoute` 函数
- ✅ 使用 `ErrorDisplay` 组件展示错误
- ✅ 添加进度提示（正在理解需求、搜索景点等）
- ✅ 支持重试和简化需求重试

## 错误处理流程

```
用户发送请求
    ↓
streamPlanRoute 发起fetch请求
    ↓
成功 → 解析SSE流 → 显示进度 → 完成
    ↓
失败 → 创建PlanError对象 → 显示ErrorDisplay组件
    ↓
用户可选择：重试 / 简化需求重试 / 查看诊断
```

## 错误类型对应表

| 错误类型 | 图标 | 标题 | 场景 |
|---------|------|------|------|
| connection | 🔌 | 无法连接到规划服务 | 网络断开、后端未启动 |
| timeout | ⏱️ | 请求超时 | 处理时间超过限制 |
| server | 🔧 | 服务器错误 | HTTP 5xx、API错误 |
| parse | 📄 | 数据解析错误 | SSE格式异常 |
| unknown | ❌ | 发生错误 | 其他未知错误 |

## 文件变更

### 修改的文件
1. `frontend/src/api/plan.ts` - 添加streamPlanRoute和错误处理
2. `frontend/src/components/AIChatPanel/index.tsx` - 集成新的错误处理
3. `frontend/src/components/AIChatPanel/AIChatPanel.module.css` - 添加错误容器样式
4. `frontend/src/components/index.ts` - 导出新组件
5. `frontend/tsconfig.json` - 移除无效的ignoreDeprecations配置

### 新增的文件
1. `frontend/src/components/ErrorDisplay/index.tsx` - 错误展示组件
2. `frontend/src/components/ErrorDisplay/ErrorDisplay.module.css` - 组件样式
3. `frontend/SSE_CONNECTION_FIX_SUMMARY.md` - 本文档

## 向后兼容

原有的 `planRoute` 函数保持不变，内部已更新为使用新的错误处理逻辑，确保现有代码不受影响。

## 使用示例

```typescript
import { streamPlanRoute } from '@/api/plan';

// 使用新的流式规划函数
await streamPlanRoute(
  '我想去北京3日游',
  'exploratory',
  (event) => {
    console.log('进度:', event);
  },
  (error) => {
    console.error('错误:', error);
    // error.type: 'connection' | 'timeout' | 'server' | 'parse' | 'unknown'
    // error.message: 简短错误信息
    // error.details: 详细描述
    // error.suggestions: 解决建议数组
  },
  60000 // 超时时间（毫秒）
);
