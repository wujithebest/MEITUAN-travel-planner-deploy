# 路线 Polyline 服务迁移文档

## 概述

本文档描述了将后端高德地图 Polyline 路线规划逻辑迁移到前端的过程。

## 文件结构

```
src/
├── types/
│   ├── amap.d.ts          # 高德地图类型定义（已更新）
│   └── route.ts           # 路线规划类型定义（新增）
├── services/
│   └── routePolyline.ts   # 路线规划核心服务（新增）
├── hooks/
│   └── useRoutePlanning.ts # 路线规划 Hook（新增）
├── components/
│   ├── PlanningProgress/   # 规划进度浮层（新增）
│   │   ├── index.tsx
│   │   └── PlanningProgress.module.css
│   └── RoutePanel/         # 路线信息面板（新增）
│       ├── index.tsx
│       └── RoutePanel.module.css
└── examples/
    └── RoutePlanningExample.tsx # 使用示例（新增）
```

## 后端到前端的映射

### 1. api_client.py → routePolyline.ts

| 后端函数 | 前端方法 | 说明 |
|---------|---------|------|
| `_parse_gaode_polyline()` | `parseGaodePolyline()` | 解析高德 polyline 字符串 |
| `_merge_polyline_chunks()` | `mergeSegments()` | 多段 polyline 拼接去重 |
| `_extract_path_polyline()` | `parseGaodePath()` | 解析步行/驾车路径 |
| `_extract_transit_polyline()` | `parseTransitPath()` | 解析公交/地铁路径 |
| `gaode_walking_route()` | `queryWalking()` | 查询步行路线 |
| `gaode_driving_route()` | `queryDriving()` | 查询驾车路线 |
| `gaode_bicycling_route()` | `queryRiding()` | 查询骑行路线 |
| `gaode_transit_route()` | `queryTransit()` | 查询公交路线 |

### 2. step3_micro.py → routePolyline.ts

| 后端函数 | 前端方法 | 说明 |
|---------|---------|------|
| `_simplify_polyline()` | `simplifyPolyline()` | Douglas-Peucker 简化 |
| `_route_between()` | `planRoute()` | 智能选择交通方式 |
| `_render_single_day_map()` | `renderDayRoute()` | 渲染单日路线 |
| 短段合并逻辑 | `mergeShortSegments()` | 合并 <500m 步行段 |
| 拼接处去重逻辑 | `deduplicateJunction()` | 去除 <15m 重合点 |
| 支路去除逻辑 | `removeSpurs()` | 去除投影回退 >30m 支路 |
| 段间衔接逻辑 | `connectSegments()` | 补接 <50m 空隙 |

### 3. 新增组件

| 组件 | 说明 |
|-----|------|
| `PlanningProgress` | 规划进度浮层，显示实时消息 |
| `RoutePanel` | 路线信息面板，显示每日路线概览 |
| `useRoutePlanning` | 路线规划 Hook，管理规划状态 |

## 交通方式样式

| 交通方式 | 颜色 | 线宽 | 样式 |
|---------|-----|-----|------|
| 步行 | #1890ff (蓝色) | 4px | 实线 |
| 地铁/公交 | #52c41a (绿色) | 5px | 虚线 [10, 10] |
| 自驾 | #fa8c16 (橙色) | 5px | 虚线 [10, 10] |
| 骑行 | #722ed1 (紫色) | 4px | 实线 |

## 智能路线选择规则

```
距离 < 50m:     直接两点连线
同 sub-anchor:   步行导航
跨 sub-anchor:
  - ≥ 2km:      驾车
  - 1-2km:      骑行
  - < 1km:      步行
```

## 渲染优化步骤

1. **短段合并**: 连续步行段 <500m 合并
2. **拼接处去重**: 去除 <15m 重合点
3. **支路去除**: 去除投影回退 >30m 的支路
4. **段间衔接**: 补接 <50m 空隙

## 使用示例

```tsx
import { useRoutePlanning } from '@/hooks/useRoutePlanning';
import { PlanningProgress } from '@/components/PlanningProgress';
import { RoutePanel } from '@/components/RoutePanel';

function MyComponent() {
  const { map, mapReady } = useGaodeMap('map-container');
  
  const {
    progress,
    planDayRoute,
    planFullRoute,
    renderDayRoute,
  } = useRoutePlanning({ map });

  // 规划单日路线
  const handlePlan = async () => {
    const dayPlan = {
      day: 1,
      pois: [
        { id: '1', name: '外滩', lat: 31.2397, lng: 121.4906 },
        { id: '2', name: '豫园', lat: 31.2270, lng: 121.4920 },
      ],
    };
    
    const dayRoute = await planDayRoute(dayPlan);
    if (dayRoute) {
      renderDayRoute(dayRoute);
    }
  };

  return (
    <div>
      <button onClick={handlePlan}>规划路线</button>
      <PlanningProgress progress={progress} />
      <RoutePanel dayRoutes={dayRoutes} />
    </div>
  );
}
```

## 错误处理

所有高德 API 调用都有降级处理：
- API 调用失败时，自动降级为两点直线连接
- 不会导致页面崩溃
- 在进度消息中显示降级信息

## 性能优化

- **Douglas-Peucker 简化**: 减少 polyline 点数
- **分段简化**: 驾车/公交路线使用 30m 容差，步行路线使用 5m 容差
- **requestAnimationFrame**: 大量 polyline 点时分批渲染（待实现）

## 注意事项

1. 需要确保高德地图 JS API 2.0 已加载
2. 需要配置 `VITE_GAODE_JSAPI_KEY` 和 `VITE_GAODE_SECURITY_CONFIG` 环境变量
3. 类型定义文件 `amap.d.ts` 已更新以支持更多高德 API 类型

## 验证清单

- [x] RoutePolylineService 可以正确调用高德 API 获取路线
- [x] 不同交通方式的 polyline 样式正确（颜色、实线/虚线）
- [x] 多段路线拼接后没有重复点
- [x] 地图视野自动调整到包含所有路线
- [x] 规划进度可以实时显示
- [x] 错误时降级为直线连接，不崩溃
