# TravelOS Components

## 布局组件

### MainLayout
主布局容器，包含顶部栏、侧边栏、主内容区和底部统计栏。

```tsx
import { MainLayout } from '@/components';

<MainLayout>
  <YourContent />
</MainLayout>
```

### TopBar
顶部导航栏，包含 Logo、搜索框、通知和用户菜单。

**Props:**
- `onToggleSidebar: () => void` - 切换左侧边栏
- `onToggleRightPanel: () => void` - 切换右侧面板
- `isRightPanelVisible: boolean` - 右侧面板是否可见

### TravelSidebar
左侧导航栏，包含导航菜单、位置输入和已保存的行程。

**Props:**
- `collapsed: boolean` - 是否折叠
- `onToggle: () => void` - 切换折叠状态

### RoutePanel
右侧行程面板，显示行程概览、地点和路线。

**Props:**
- `collapsed: boolean` - 是否折叠
- `onToggle: () => void` - 切换折叠状态

### BottomStats
底部统计栏，显示行程统计数据。

**Props:**
- `stats: Stats | null` - 统计数据
- `loading?: boolean` - 是否加载中

## 设计系统

### CSS 变量
所有颜色、间距、圆角等设计令牌定义在 `styles/variables.css` 中。

### 颜色系统
- 主色调: `#FFD700` (黄色)
- 文本色: `#1A1A1A` (主要), `#666666` (次要), `#999999` (第三)
- 背景色: `#FFFFFF` (主要), `#F8F9FA` (次要), `#F0F0F0` (第三)
- 边框色: `#E8E8E8`
- 状态色: `#52C41A` (成功), `#FAAD14` (警告)

### 圆角
- 卡片: 16px
- 按钮: 12px
- 输入框: 8px
- 徽章: 20px

### 阴影
- 卡片: `0 2px 12px rgba(0,0,0,0.08)`
- 卡片悬停: `0 4px 20px rgba(0,0,0,0.12)`

### 响应式断点
- 桌面: > 1024px (三栏完整显示)
- 平板: 768px - 1024px (隐藏右侧面板)
- 移动端: < 768px (侧边栏变抽屉)

## 使用示例

### 基本用法
```tsx
import React from 'react';
import { MainLayout } from '@/components';

const PlannerPage: React.FC = () => {
  return (
    <MainLayout>
      <div style={{ width: '100%', height: '100%' }}>
        <MapContainer />
      </div>
    </MainLayout>
  );
};
```

### 响应式布局
布局会自动根据屏幕宽度调整：
- 桌面端：三栏完整显示
- 平板端：隐藏右侧行程面板，可通过按钮切换
- 移动端：左侧边栏变抽屉，地图全屏
