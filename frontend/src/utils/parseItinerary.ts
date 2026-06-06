/**
 * 旅游行程解析器
 * 解析后端通过 SSE 流推送的纯文本行程数据
 */

export interface ParsedItinerary {
  summary: string;
  days: DayItinerary[];
  anchorSummaries: AnchorSummary[];
  mapPaths: MapPath[];
  weatherWarning?: string;
  
  // 新增：按类型分类的数据
  itinerary: ItineraryView;    // "行程" Tab 数据
  locations: LocationView;     // "地点" Tab 数据
  routes: RouteView;           // "路线" Tab 数据
}

// ========== 行程 Tab ==========

export interface ItineraryView {
  days: DayTimeline[];
}

export interface DayTimeline {
  dayNumber: number;
  timeSlots: TimeSlot[];
}

// ========== 地点 Tab ==========

export interface LocationView {
  anchors: AnchorDetail[];
}

export interface AnchorDetail {
  name: string;
  highlights: string;
  matchReason: string;
  advice: string;
  commuteTime: string;
  rating?: number;
  type?: string;
  distance?: string;
  suggestTime?: string;
}

// ========== 路线 Tab ==========

export interface RouteView {
  days: DayRouteInfo[];
  totalDistance: number;
  totalDuration: number;
}

export interface DayRouteInfo {
  dayNumber: number;
  mapPath: string;      // HTML 文件路径
  jsonPath: string;     // JSON 数据路径
  segments: RouteSegmentInfo[];
  stats: {
    totalDistance: number;
    totalDuration: number;
    walkCount: number;
    transitCount: number;
  };
}

export interface RouteSegmentInfo {
  from: string;
  to: string;
  transport: string;
  duration: string;
  distance: number;
}

// ========== 原有类型（保持兼容） ==========

export interface DayItinerary {
  dayNumber: number;
  timeSlots: TimeSlot[];
  alongTheWay: AlongPOI[];
  sameBuildingPOIs: string[];
}

export type TimeSlot = ActivitySlot | MealSlot;

export interface ActivitySlot {
  type: 'activity';
  period: string;           // "白天"、"上午"、"下午"、"晚上"
  timeRange: string;        // "9:00-18:00"
  title: string;            // "外滩周边游览"
  routeSteps: RouteStep[];
  recommendation?: Recommendation;
  hint?: string;            // 提示信息
}

export interface MealSlot {
  type: 'meal';
  period: string;           // "中午"、"晚餐"
  timeRange: string;        // "12:00-14:00"
  restaurantName: string;
  distanceFromLast: string;  // "距上一站步行约0.18km"
  meta: MealMeta;
  routeSteps: RouteStep[];
  walkInfo?: string;        // "步行约180米到达xxx"
}

export interface RouteStep {
  from: string;
  to: string;
  transport: string;
  duration: string;
}

export interface Recommendation {
  highlights: string;
  matchReason: string;
  advice: string;
  commuteTime: string;      // "从出发地约47分钟"
}

export interface MealMeta {
  rating?: number;
  avgCost?: number;
  type: string;             // "正餐 POI"
}

export interface AlongPOI {
  name: string;
  walkTime: string;         // "步行1分钟可达"
}

export interface AnchorSummary {
  name: string;
  highlights: string;
  matchReason: string;
  advice: string;
  commuteTime: string;
}

export interface MapPath {
  day: number;
  path: string;
}

/**
 * 解析路线步骤
 * 格式：起点 - 交通方式(时长) - 终点
 */
function parseRouteLine(line: string): RouteStep | null {
  // 匹配格式：xxx - 交通(xxx) - xxx
  const routeMatch = line.match(/^(.+?)\s*-\s*(.+?)\(([^)]+)\)\s*-\s*(.+)$/);
  if (routeMatch) {
    return {
      from: routeMatch[1].trim(),
      transport: routeMatch[2].trim(),
      duration: routeMatch[3].trim(),
      to: routeMatch[4].trim(),
    };
  }
  return null;
}

/**
 * 解析推荐理由
 * 格式：核心看点：xxx；匹配理由：xxx；安排建议：xxx，从出发地约xx分钟
 */
function parseRecommendation(text: string): Recommendation | null {
  const result: Recommendation = {
    highlights: '',
    matchReason: '',
    advice: '',
    commuteTime: '',
  };

  // 提取核心看点
  const highlightsMatch = text.match(/核心看点[：:](.+?)(?:；|$)/);
  if (highlightsMatch) {
    result.highlights = highlightsMatch[1].trim();
  }

  // 提取匹配理由
  const matchReasonMatch = text.match(/匹配理由[：:](.+?)(?:；|$)/);
  if (matchReasonMatch) {
    result.matchReason = matchReasonMatch[1].trim();
  }

  // 提取安排建议
  const adviceMatch = text.match(/安排建议[：:](.+?)(?:，从出发地|$)/);
  if (adviceMatch) {
    result.advice = adviceMatch[1].trim();
  }

  // 提取通勤时间
  const commuteMatch = text.match(/从出发地约(.+?)(?:分钟|$)/);
  if (commuteMatch) {
    result.commuteTime = `从出发地约${commuteMatch[1]}分钟`;
  }

  return result.highlights || result.matchReason || result.advice ? result : null;
}

/**
 * 解析餐饮信息
 * 格式：中午（12:00-14:00）：餐饮推荐 - 餐厅名（距上一站步行约0.18km）（评分4.5，人均约200元，正餐 POI）
 */
function parseMealLine(line: string): {
  period: string;
  timeRange: string;
  restaurantName: string;
  distanceFromLast: string;
  meta: MealMeta;
} | null {
  const mealMatch = line.match(/^(.+?)（(.+?)）[：:]\s*餐饮推荐\s*-\s*(.+?)（(.+?)）(?:（(.+?)）)?$/);
  if (!mealMatch) return null;

  const period = mealMatch[1].trim();
  const timeRange = mealMatch[2].trim();
  const restaurantName = mealMatch[3].trim();
  const distanceFromLast = mealMatch[4].trim();
  const metaStr = mealMatch[5] || '';

  const meta: MealMeta = { type: '正餐 POI' };

  // 解析评分
  const ratingMatch = metaStr.match(/评分([\d.]+)/);
  if (ratingMatch) {
    meta.rating = parseFloat(ratingMatch[1]);
  }

  // 解析人均
  const costMatch = metaStr.match(/人均约(\d+)元/);
  if (costMatch) {
    meta.avgCost = parseInt(costMatch[1]);
  }

  // 解析类型
  const typeMatch = metaStr.match(/(正餐 POI|小吃 POI|饮品 POI)/);
  if (typeMatch) {
    meta.type = typeMatch[1];
  }

  return { period, timeRange, restaurantName, distanceFromLast, meta };
}

/**
 * 解析沿途POI
 * 格式：途经POI名（步行x分钟可达）
 */
function parseAlongPOI(text: string): AlongPOI | null {
  const match = text.match(/^(.+?)（(.+?)）$/);
  if (match) {
    return {
      name: match[1].trim(),
      walkTime: match[2].trim(),
    };
  }
  return null;
}

/**
 * 解析地图路径
 * 格式：[ROUTE_PLANNER]: Day1: path1；Day2: path2
 */
function parseMapPaths(text: string): MapPath[] {
  const paths: MapPath[] = [];
  const match = text.match(/\[ROUTE_PLANNER\][：:]\s*(.+)/);
  if (!match) return paths;

  const pathStr = match[1];
  // 分割多天路径
  const dayPaths = pathStr.split(/[；;]/);

  for (const dayPath of dayPaths) {
    const dayMatch = dayPath.match(/Day(\d+)[：:]\s*(.+)/i);
    if (dayMatch) {
      paths.push({
        day: parseInt(dayMatch[1]),
        path: dayMatch[2].trim(),
      });
    }
  }

  return paths;
}

/**
 * 解析后端推送的纯文本行程数据
 * 输入：后端通过 SSE push_output 推送的多行文本
 * 输出：结构化数据
 */
export function parseItinerary(text: string): ParsedItinerary {
  const result: ParsedItinerary = {
    summary: '',
    days: [],
    anchorSummaries: [],
    mapPaths: [],
    // 初始化新的视图结构
    itinerary: { days: [] },
    locations: { anchors: [] },
    routes: { days: [], totalDistance: 0, totalDuration: 0 }
  };

  if (!text || typeof text !== 'string') {
    return result;
  }

  const lines = text.split('\n');
  let currentDay: DayItinerary | null = null;
  let currentSlot: TimeSlot | null = null;
  let pendingRecommendation: string = '';
  let pendingWalkInfo: string = '';

  for (let i = 0; i < lines.length; i++) {
    const line = lines[i].trim();
    if (!line) continue;

    // 1. 总摘要（第一行包含"为您规划了"）
    if (line.includes('为您规划了') && !result.summary) {
      result.summary = line;
      continue;
    }

    // 2. 天数标题 【DayN】
    const dayMatch = line.match(/^【Day(\d+)】$/);
    if (dayMatch) {
      if (currentDay) {
        result.days.push(currentDay);
      }
      currentDay = {
        dayNumber: parseInt(dayMatch[1]),
        timeSlots: [],
        alongTheWay: [],
        sameBuildingPOIs: [],
      };
      currentSlot = null;
      continue;
    }

    // 3. 时间段 时段（时间范围）：主题
    const timeSlotMatch = line.match(/^(.+?)（(.+?)）[：:]\s*(.+)$/);
    if (timeSlotMatch && !line.includes('餐饮推荐')) {
      const period = timeSlotMatch[1].trim();
      const timeRange = timeSlotMatch[2].trim();
      const title = timeSlotMatch[3].trim();

      currentSlot = {
        type: 'activity',
        period,
        timeRange,
        title,
        routeSteps: [],
      };

      if (currentDay) {
        currentDay.timeSlots.push(currentSlot);
      }
      continue;
    }

    // 4. 路线步骤
    if (line.includes(' - ') && !line.includes('餐饮推荐')) {
      const routeStep = parseRouteLine(line);
      if (routeStep && currentSlot) {
        currentSlot.routeSteps.push(routeStep);
      }
      continue;
    }

    // 5. 推荐理由
    if (line.includes('推荐理由')) {
      pendingRecommendation = line.replace(/推荐理由[：:]\s*/, '');
      continue;
    }

    // 推荐理由的后续行（可能跨行）
    if (pendingRecommendation && !line.startsWith('【') && !line.includes('：')) {
      pendingRecommendation += line;
      
      // 检查是否完整
      if (line.includes('从出发地')) {
        const recommendation = parseRecommendation(pendingRecommendation);
        if (recommendation && currentSlot && currentSlot.type === 'activity') {
          currentSlot.recommendation = recommendation;
        }
        pendingRecommendation = '';
      }
      continue;
    }

    // 6. 餐饮信息
    if (line.includes('餐饮推荐')) {
      const mealInfo = parseMealLine(line);
      if (mealInfo) {
        currentSlot = {
          type: 'meal',
          period: mealInfo.period,
          timeRange: mealInfo.timeRange,
          restaurantName: mealInfo.restaurantName,
          distanceFromLast: mealInfo.distanceFromLast,
          meta: mealInfo.meta,
          routeSteps: [],
        };
        if (currentDay) {
          currentDay.timeSlots.push(currentSlot);
        }
      }
      continue;
    }

    // 7. 步行信息
    if (line.match(/^步行约\d+米到达/)) {
      pendingWalkInfo = line;
      if (currentSlot && currentSlot.type === 'meal') {
        currentSlot.walkInfo = line;
      }
      continue;
    }

    // 8. 沿途可顺路游览
    if (line.includes('沿途可顺路游览')) {
      const poisStr = line.replace(/沿途可顺路游览[：:]\s*/, '');
      const poiItems = poisStr.split(/[、，,]/);
      
      for (const item of poiItems) {
        const poi = parseAlongPOI(item.trim());
        if (poi && currentDay) {
          currentDay.alongTheWay.push(poi);
        }
      }
      continue;
    }

    // 9. 同一建筑内还有
    if (line.includes('同一建筑内还有')) {
      const poisStr = line.replace(/同一建筑内还有[：:]\s*/, '');
      const poiNames = poisStr.split(/[、，,]/).map(s => s.trim()).filter(Boolean);
      if (currentDay) {
        currentDay.sameBuildingPOIs.push(...poiNames);
      }
      continue;
    }

    // 10. 锚点总结 · POI名：
    if (line.startsWith('·') || line.startsWith('•')) {
      const anchorText = line.replace(/^[·•]\s*/, '');
      const colonIndex = anchorText.indexOf('：');
      if (colonIndex > 0) {
        const name = anchorText.substring(0, colonIndex).trim();
        const recText = anchorText.substring(colonIndex + 1);
        const recommendation = parseRecommendation(recText);
        
        result.anchorSummaries.push({
          name,
          highlights: recommendation?.highlights || '',
          matchReason: recommendation?.matchReason || '',
          advice: recommendation?.advice || '',
          commuteTime: recommendation?.commuteTime || '',
        });
      }
      continue;
    }

    // 11. 地图路径
    if (line.includes('[ROUTE_PLANNER]')) {
      result.mapPaths = parseMapPaths(line);
      continue;
    }

    // 12. 天气警告
    if (line.includes('天气可能影响') || line.includes('建议选择室内')) {
      result.weatherWarning = line;
      continue;
    }

    // 13. 提示信息（[xxx]格式）
    const hintMatch = line.match(/^\[(.+)\]$/);
    if (hintMatch && currentSlot && currentSlot.type === 'activity') {
      currentSlot.hint = hintMatch[1];
      continue;
    }
  }

  // 添加最后一天
  if (currentDay) {
    result.days.push(currentDay);
  }

  // ========== 填充新的视图结构 ==========
  
  // 填充 itinerary 视图（行程 Tab）
  result.itinerary.days = result.days.map(day => ({
    dayNumber: day.dayNumber,
    timeSlots: day.timeSlots,
  }));

  // 填充 locations 视图（地点 Tab）
  result.locations.anchors = result.anchorSummaries.map(anchor => ({
    name: anchor.name,
    highlights: anchor.highlights,
    matchReason: anchor.matchReason,
    advice: anchor.advice,
    commuteTime: anchor.commuteTime,
  }));

  // 填充 routes 视图（路线 Tab）
  result.routes.days = result.mapPaths.map(mapPath => ({
    dayNumber: mapPath.day,
    mapPath: mapPath.path,
    jsonPath: mapPath.path.replace('.html', '.json'),
    segments: [],
    stats: {
      totalDistance: 0,
      totalDuration: 0,
      walkCount: 0,
      transitCount: 0,
    },
  }));

  return result;
}

/**
 * 增量解析 - 用于 SSE 流式更新
 * 将新文本追加到已有文本并重新解析
 */
export function parseItineraryIncremental(
  existing: ParsedItinerary | null,
  newText: string
): ParsedItinerary {
  if (!existing) {
    return parseItinerary(newText);
  }

  // 对于流式更新，我们重新解析完整文本
  // 实际使用时应该维护一个完整文本缓冲区
  return parseItinerary(newText);
}

/**
 * 获取交通方式对应的颜色
 */
export function getTransportColor(transport: string): string {
  const colors: Record<string, string> = {
    '步行': '#1890ff',
    '地铁/公交': '#52c41a',
    '自驾': '#fa8c16',
    '骑行': '#722ed1',
  };
  return colors[transport] || '#1890ff';
}

/**
 * 获取交通方式对应的图标
 */
export function getTransportIcon(transport: string): string {
  const icons: Record<string, string> = {
    '步行': '🚶',
    '地铁/公交': '🚇',
    '自驾': '🚗',
    '骑行': '🚴',
  };
  return icons[transport] || '🚶';
}
