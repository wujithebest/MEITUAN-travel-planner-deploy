# BottomStats Component

固定在页面底部的统计栏组件。

## 功能特性

- 固定底部，高度 56px
- 白色背景，顶部边框
- 横向统计项排列
- 支持：距离、时间、费用、地点数、最佳时间、拥挤度、天气
- 右侧黄色导航按钮
- 响应式设计

## 使用方法

```tsx
import { BottomStats } from '@/components';

const MyComponent = () => {
  const stats = {
    totalDistance: 12500,    // 米
    totalDuration: 480,      // 分钟
    estimatedCost: 350,
    totalStops: 6,
    bestTime: '08:00',
    crowdLevel: 'Moderate',
    weather: '23°C'
  };

  return (
    <BottomStats
      stats={stats}
      onStartNavigation={() => console.log('Start Navigation')}
    />
  );
};
```

## Props

| 属性 | 类型 | 必填 | 默认值 | 描述 |
|------|------|------|--------|------|
| stats | object | 否 | null | 统计数据 |
| loading | boolean | 否 | false | 加载状态 |
| onStartNavigation | function | 否 | - | 开始导航回调 |

### stats 对象结构

```typescript
{
  totalDistance: number;   // 总距离（米）
  totalDuration: number;   // 总时长（分钟）
  estimatedCost: number;   // 预估费用
  totalStops: number;      // 停靠点数
  bestTime?: string;       // 最佳出发时间
  crowdLevel?: string;     // 拥挤度
  weather?: string;        // 天气
}
```

## 样式

组件使用 CSS Modules，样式文件：`BottomStats.module.css`

主要样式：
- 高度：56px
- 背景：白色
- 顶部边框：1px #E8E8E8
- 统计项间距：32px
- 导航按钮：黄色背景 #FFD700，圆角 12px

## 响应式

- 屏幕宽度 < 1200px：隐藏统计标签
- 屏幕宽度 < 900px：减小间距，按钮隐藏文字
- 屏幕宽度 < 768px：垂直布局，居中显示
