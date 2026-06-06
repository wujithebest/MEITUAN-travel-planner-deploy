# RouteTimeline Component

路线时间轴组件，展示行程的详细时间安排。

## 功能特性

- 宽度 360px，白色背景，左侧边框
- 标题栏："Your Itinerary" + Optimize 按钮
- 时间轴列表：
  - 起点：绿色圆点 + 时间 + 卡片
  - 景点：黄色圆圈 + 白色数字 + 时间段 + 卡片
  - 交通：灰色圆点 + 汽车图标 + 交通信息
  - 终点：灰色圆点 + End + 卡片
- 卡片内容：名称、评分、预计时长、缩略图
- 底部 "Add Activity" 按钮
- 滚动条样式

## 使用方法

```tsx
import { RouteTimelineSimple } from '@/components';

const MyComponent = () => {
  const nodes = [
    {
      id: '1',
      type: 'start',
      time: '09:00',
      title: 'Hotel Name',
      subtitle: '酒店名称',
      rating: 4.8,
      reviewCount: 2341,
      duration: 'Check-in',
      imageUrl: 'https://example.com/image.jpg'
    },
    {
      id: '2',
      type: 'transport',
      time: '',
      title: '',
      transportInfo: {
        mode: 'Drive',
        duration: '1h 15m',
        distance: '66 km',
        arrivalTime: '10:15'
      }
    },
    {
      id: '3',
      type: 'poi',
      time: '10:15',
      title: 'Attraction Name',
      subtitle: '景点名称',
      rating: 4.9,
      reviewCount: 5678,
      duration: '3 hours',
      imageUrl: 'https://example.com/image.jpg',
      index: 1
    },
    {
      id: '4',
      type: 'end',
      time: '19:30',
      title: 'Restaurant Name',
      subtitle: '餐厅名称',
      rating: 4.5,
      reviewCount: 4532,
      duration: 'Dinner',
      imageUrl: 'https://example.com/image.jpg'
    }
  ];

  return (
    <RouteTimelineSimple
      nodes={nodes}
      onOptimize={() => console.log('Optimize')}
      onAddActivity={() => console.log('Add Activity')}
      onNodeClick={(node) => console.log('Node clicked:', node)}
    />
  );
};
```

## Props

| 属性 | 类型 | 必填 | 默认值 | 描述 |
|------|------|------|--------|------|
| nodes | TimelineNode[] | 是 | - | 时间轴节点数组 |
| onOptimize | function | 否 | - | 优化路线回调 |
| onAddActivity | function | 否 | - | 添加活动回调 |
| onNodeClick | function | 否 | - | 节点点击回调 |

### TimelineNode 结构

```typescript
{
  id: string;
  type: 'start' | 'poi' | 'transport' | 'end';
  time: string;
  title: string;
  subtitle?: string;
  rating?: number;
  reviewCount?: number;
  duration?: string;
  transportInfo?: {
    mode: string;
    duration: string;
    distance: string;
    arrivalTime: string;
  };
  imageUrl?: string;
  index?: number;  // 景点序号
}
```

## 节点类型

### start（起点）
- 绿色圆点 (#52C41A)
- 显示 "Start" 标签
- 酒店卡片

### poi（景点）
- 黄色圆圈 (#FFD700)
- 白色数字序号
- 景点卡片

### transport（交通）
- 灰色圆点 (#999)
- 汽车图标
- 显示：Drive 1h 15m (66 km)
- 到达时间

### end（终点）
- 灰色圆点
- 显示 "End" 标签
- 餐厅卡片

## 样式

组件使用 CSS Modules，样式文件：`RouteTimelineSimple.module.css`

主要样式：
- 宽度：360px
- 左侧边框：1px #E8E8E8
- 时间线：2px 宽竖线
- 圆点：12px（起点/终点 16px，景点 24px）
- 缩略图：60x60px，圆角 8px
