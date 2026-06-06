# RouteOverview Component

悬浮于地图底部中央的路线概览卡片组件。

## 功能特性

- 三栏布局：AI Assistant、Route Overview、预留位
- 显示天气和拥挤度信息
- 支持 Plan B 切换
- 统计卡片展示：总距离、总时间、预估费用、停靠点数
- 旅行提示列表
- 响应式设计

## 使用方法

```tsx
import { RouteOverview } from '@/components';

const MyComponent = () => {
  const stats = {
    totalDistance: 12500, // 米
    totalDuration: 480, // 分钟
    estimatedCost: 350,
    totalStops: 6
  };

  const weather = {
    city: 'Beijing',
    temperature: 23,
    condition: 'Sunny'
  };

  return (
    <RouteOverview
      stats={stats}
      weather={weather}
      crowdLevel="Moderate"
      onViewPlanB={() => console.log('View Plan B')}
    />
  );
};
```

## Props

| 属性 | 类型 | 必填 | 默认值 | 描述 |
|------|------|------|--------|------|
| stats | object | 是 | - | 路线统计数据 |
| weather | object | 否 | Beijing 23°C Sunny | 天气信息 |
| crowdLevel | string | 否 | 'Moderate' | 拥挤度级别 |
| onViewPlanB | function | 否 | - | 查看 Plan B 回调 |

### stats 对象结构

```typescript
{
  totalDistance: number;  // 总距离（米）
  totalDuration: number;  // 总时长（分钟）
  estimatedCost: number;  // 预估费用
  totalStops: number;     // 停靠点数
}
```

### weather 对象结构

```typescript
{
  city: string;       // 城市名称
  temperature: number; // 温度
  condition: string;   // 天气状况
}
```

## 样式

组件使用 CSS Modules，样式文件：`RouteOverview.module.css`

主要样式变量：
- 宽度：800px
- 圆角：16px
- 阴影：0 4px 24px rgba(0,0,0,0.12)
- 底部距离：80px

## 响应式

- 屏幕宽度 < 900px：AI Section 和 Route Section 垂直堆叠
- 屏幕宽度 < 600px：统计卡片两列布局
