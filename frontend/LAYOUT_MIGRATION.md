# TravelOS 布局迁移指南

## 概述

本文档描述了将现有旅游规划前端改造为 TravelOS 风格界面的第一步：全局布局改造。

## 已完成的改造

### 1. 设计系统 (Design System)

创建了完整的设计系统，包括：

- **CSS 变量** (`src/styles/variables.css`)
  - 颜色系统：主色调、文本色、背景色、边框色、状态色
  - 布局尺寸：顶部栏高度、侧边栏宽度、右侧面板宽度、底部统计栏高度
  - 圆角：卡片 16px、按钮 12px、输入框 8px、徽章 20px
  - 阴影：卡片、卡片悬停、下拉框、模态框
  - 过渡动画：fast、normal、slow
  - Z-index 层级

- **全局样式** (`src/styles/global.css`)
  - CSS Reset 和基础样式
  - 滚动条样式
  - 动画工具类
  - 卡片和按钮样式
  - 响应式工具类

### 2. 布局组件

创建了新的布局组件：

#### MainLayout (`src/components/Layout/MainLayout.tsx`)
主布局容器，包含：
- TopBar（顶部栏）
- TravelSidebar（左侧边栏）
- RoutePanel（右侧行程面板）
- BottomStats（底部统计栏）

#### TopBar (`src/components/TopBar/TopBar.tsx`)
- 左侧：菜单按钮 + Logo
- 中间：搜索框
- 右侧：功能按钮（协作、通知、日记、行程面板切换）+ 用户头像菜单

#### TravelSidebar (`src/components/TravelSidebar/TravelSidebar.tsx`)
- 导航菜单（规划路线、目的地、行程安排、收藏夹、最近查看）
- 位置输入组件
- 已保存的行程列表
- 支持折叠/展开

#### RoutePanel (`src/components/RoutePanel/RoutePanel.tsx`)
- 行程概览
- 标签页切换（行程、地点、路线）
- 支持折叠/展开

#### BottomStats (`src/components/BottomStats/BottomStats.tsx`)
- 统计数据展示（天数、距离、时长、地点数）
- 进度条

### 3. 页面改造

#### PlannerPage (`src/pages/PlannerPage/PlannerPage.tsx`)
- 使用新的 MainLayout
- 地图容器占据中间区域
- 保留了原有的业务逻辑

### 4. App 配置更新

#### App.tsx
- 引入全局样式
- 更新 Ant Design 主题配置（主色调改为黄色）
- 保持原有路由结构

## 响应式布局

### 桌面端 (> 1024px)
- 三栏完整显示
- 左侧边栏：280px
- 中间地图：flex: 1
- 右侧面板：360px

### 平板端 (768px - 1024px)
- 隐藏右侧行程面板
- 可通过按钮切换显示

### 移动端 (< 768px)
- 左侧边栏变抽屉
- 地图全屏显示
- 底部统计栏自适应

## 文件结构

```
src/
├── styles/
│   ├── variables.css      # CSS 变量定义
│   └── global.css         # 全局样式
├── components/
│   ├── Layout/
│   │   ├── MainLayout.tsx
│   │   └── MainLayout.module.css
│   ├── TopBar/
│   │   ├── TopBar.tsx
│   │   └── TopBar.module.css
│   ├── TravelSidebar/
│   │   ├── TravelSidebar.tsx
│   │   └── TravelSidebar.module.css
│   ├── RoutePanel/
│   │   ├── RoutePanel.tsx
│   │   └── RoutePanel.module.css
│   ├── BottomStats/
│   │   ├── BottomStats.tsx
│   │   └── BottomStats.module.css
│   └── index.ts           # 组件导出
└── pages/
    └── PlannerPage/
        ├── PlannerPage.tsx
        └── PlannerPage.module.css
```

## 使用示例

```tsx
import { MainLayout } from '@/components';

const YourPage: React.FC = () => {
  return (
    <MainLayout>
      <div style={{ width: '100%', height: '100%' }}>
        {/* 你的内容 */}
      </div>
    </MainLayout>
  );
};
```

## 下一步计划

1. **完善侧边栏功能**
   - 实现导航切换逻辑
   - 完善已保存行程的交互

2. **完善右侧面板**
   - 集成完整的 RouteTimeline 组件
   - 添加地点和路线标签页内容

3. **优化地图容器**
   - 添加地图控制按钮
   - 优化地图标记样式

4. **响应式优化**
   - 完善平板端和移动端的交互
   - 添加触摸手势支持

5. **动画和过渡**
   - 添加面板切换动画
   - 优化加载状态

## 注意事项

1. 所有 CSS 变量定义在 `variables.css` 中，使用 `var(--variable-name)` 引用
2. 组件使用 CSS Modules，样式文件命名为 `*.module.css`
3. 响应式断点：768px（移动端）、1024px（平板端）
4. 主色调为黄色 (#FFD700)，与 Ant Design 主题保持一致

## 构建验证

项目已通过构建验证：
```bash
cd frontend
npm run build
```

构建成功，无错误。
