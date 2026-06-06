# ItinerarySidebar 组件

旅游规划助手右侧行程栏 UI 组件。

## 功能特性

- ✅ 解析后端 SSE 流推送的纯文本行程数据
- ✅ 支持多天行程展示
- ✅ 时间轴样式路线展示
- ✅ 餐饮推荐卡片（橙色左边框）
- ✅ 推荐理由卡片（黄色背景）
- ✅ 沿途可顺路游览 POI
- ✅ 锚点总结
- ✅ 天数折叠/展开
- ✅ 地图路径链接
- ✅ 底部导航按钮
- ✅ SSE 流式更新支持

## 文件结构

```
ItinerarySidebar/
├── index.tsx           # 主容器组件
├── SummaryCard.tsx     # 总摘要卡片
├── DayPanel.tsx        # 天数面板（可折叠）
├── ActivitySlot.tsx    # 活动时段
├── MealSlot.tsx        # 餐饮时段
├── RouteTimeline.tsx   # 路线时间轴
├── RecommendationCard.tsx  # 推荐理由卡片
├── AlongTheWay.tsx     # 沿途可顺路游览
├── AnchorSummary.tsx   # 锚点总结
├── BottomNav.tsx       # 底部导航
├── styles.module.css   # 样式文件
└── README.md           # 使用说明
```

## 使用方法

### 基本用法

```tsx
import { ItinerarySidebar } from '@/components/ItinerarySidebar';
import { parseItinerary } from '@/utils/parseItinerary';

function App() {
  const [itineraryData, setItineraryData] = useState(null);
  const [rawText, setRawText] = useState('');

  // SSE 回调中
  eventSource.onmessage = (e) => {
    const text = e.data;
    setRawText(prev => prev + text);
  };

  return (
    <ItinerarySidebar
      rawText={rawText}
      onPOIClick={(name) => console.log('POI clicked:', name)}
      onTransportClick={(from, to, transport) => 
        console.log('Transport:', from, to, transport)
      }
      onMapClick={(path) => window.open(path, '_blank')}
      onStartNavigation={() => console.log('Start navigation')}
    />
  );
}
```

### 使用已解析的数据

```tsx
import { ItinerarySidebar } from '@/components/ItinerarySidebar';
import { parseItinerary } from '@/utils/parseItinerary';

function App() {
  const [data, setData] = useState(null);

  useEffect(() => {
    // 假设从某处获取了完整文本
    const fullText = getFullTextFromSomewhere();
    const parsed = parseItinerary(fullText);
    setData(parsed);
  }, []);

  return (
    <ItinerarySidebar
      data={data}
      onPOIClick={(name) => map.highlightPOI(name)}
      onTransportClick={(from, to, t) => map.highlightRoute(from, to, t)}
    />
  );
}
```

## Props

### ItinerarySidebar Props

| 属性 | 类型 | 必填 | 说明 |
|------|------|------|------|
| rawText | string | 否 | 原始文本数据（用于 SSE 流式更新） |
| data | ParsedItinerary | 否 | 已解析的行程数据 |
| onPOIClick | (name: string) => void | 否 | POI 点击回调 |
| onTransportClick | (from, to, transport) => void | 否 | 交通方式点击回调 |
| onMapClick | (path: string) => void | 否 | 地图路径点击回调 |
| onStartNavigation | () => void | 否 | 开始导航回调 |
| collapsed | boolean | 否 | 是否收起 |
| onToggleCollapse | () => void | 否 | 收起状态变化回调 |

## 数据类型

```typescript
interface ParsedItinerary {
  summary: string;           // 总摘要
  days: DayItinerary[];      // 天数列表
  anchorSummaries: AnchorSummary[];  // 锚点总结
  mapPaths: MapPath[];       // 地图路径
  weatherWarning?: string;   // 天气警告
}

interface DayItinerary {
  dayNumber: number;         // 天数
  timeSlots: TimeSlot[];     // 时间段列表
  alongTheWay: AlongPOI[];   // 沿途POI
  sameBuildingPOIs: string[]; // 同建筑POI
}

type TimeSlot = ActivitySlot | MealSlot;

interface ActivitySlot {
  type: 'activity';
  period: string;            // "白天"、"上午"等
  timeRange: string;         // "9:00-18:00"
  title: string;             // 主题
  routeSteps: RouteStep[];   // 路线步骤
  recommendation?: Recommendation;  // 推荐理由
  hint?: string;             // 提示信息
}

interface MealSlot {
  type: 'meal';
  period: string;            // "中午"、"晚餐"
  timeRange: string;         // "12:00-14:00"
  restaurantName: string;    // 餐厅名
  distanceFromLast: string;  // 距上一站距离
  meta: MealMeta;            // 元信息（评分、人均等）
  routeSteps: RouteStep[];   // 路线步骤
  walkInfo?: string;         // 步行信息
}
```

## 样式规范

| 元素 | 颜色 | 说明 |
|------|------|------|
| 步行 | #1890ff (蓝色) | 主行程标签 |
| 地铁/公交 | #52c41a (绿色) | 公共交通 |
| 自驾 | #fa8c16 (橙色) | 驾车 |
| 骑行 | #722ed1 (紫色) | 顺路标签 |
| 餐饮 | #fa8c16 (橙色) | 餐饮卡片左边框 |
| 推荐理由 | #fffbe6 (浅黄) | 推荐理由背景 |
| 导航按钮 | #ffd666 (黄色) | 开始导航按钮 |

## 解析器

解析器位于 `src/utils/parseItinerary.ts`，支持解析以下格式：

- `为您规划了...` → 总摘要
- `【DayN】` → 天数标题
- `时段（时间范围）：主题` → 时间段
- `起点 - 交通(时长) - 终点` → 路线步骤
- `推荐理由：核心看点：...；匹配理由：...；安排建议：...` → 推荐理由
- `中午（12:00-14:00）：餐饮推荐 - 餐厅名（...）` → 餐饮信息
- `沿途可顺路游览：途经xxx（步行x分钟可达）...` → 沿途POI
- `· POI名：核心看点：...` → 锚点总结
- `[ROUTE_PLANNER]: Day1: path1；Day2: path2` → 地图路径
- `当前天气可能影响...` → 天气警告

## 验证清单

- [x] 能正确解析示例文本的所有字段
- [x] 多天数据正确分组
- [x] 时间轴交通方式颜色正确
- [x] 餐饮卡片有橙色左边框
- [x] 推荐理由卡片有黄色背景
- [x] 天数可折叠展开
- [x] 底部总结正确显示
- [x] 地图路径可点击
- [x] 无 TypeScript 错误
