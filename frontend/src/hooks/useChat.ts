/**
 * useChat Hook - 聊天交互状态管理
 * 处理用户输入、AI 回复、路线数据解析、模式选择
 * 支持 SSE 不同 event 类型：status、result、done、error
 */

import { useState, useCallback, useRef, useEffect } from 'react';
import { sendMeituanMessageStream, extractMeituanMapData, MeituanRouteData, GuestProfile, ChatRouteContext } from '@/api/meituanChat';
import { useRouteStore } from '@/store/routeStore';
import { useUserStore } from '@/store/userStore';
import { FALLBACK_HOME_LOCATION, normalizeLocationPayload } from '@/utils/locationDefaults';
import type { CompletePlan, DayPlan, TimeSlot, TimeSlotType, Activity, RestaurantRecommendation, POI } from '@/types/plan';
import type { DailyRouteDTO } from '@/api/types';

/**
 * Slot-structured recommend reasons item
 */
export interface SlotReasonItem {
  name: string;
  reason?: string;
  order?: number;
  kind?: string;
  transport_text?: string;
  isMeal?: boolean;
}

/**
 * Slot-structured recommend reasons
 */
export interface SlotStructuredReasons {
  slot: string;
  slotLabel: string;
  slotOrder: number;
  items: SlotReasonItem[];
}

/**
 * 聊天消息
 */
export interface ChatMessage {
  id: string;
  role: 'user' | 'assistant' | 'system';
  content: string;
  timestamp: number;
  routeData?: any;
  parsedStructure?: any;
  /** 显示类型：text = 普通文本, recommendReasons = 推荐理由 */
  displayType?: 'text' | 'recommendReasons';
  /** 本轮请求 ID，同一 request 的 complete 事件更新同一条推荐理由消息 */
  requestId?: string;
  /** 发起本轮请求的用户消息 ID */
  parentUserMessageId?: string;
  /** 推荐理由快照（从 completePlan 提取，避免历史消息被最新 currentPlan 覆盖）*/
  /** @deprecated 旧格式，保留兼容 */
  recommendReasons?: Array<{ name: string; reason: string }>;
  /** 结构化推荐理由（新格式，按 slot 组织） */
  slotReasons?: SlotStructuredReasons[];
  /** v18: 路线卡片推送 */
  routeCardTitle?: string;
  routeCardSubtitle?: string;
  /** 统计信息文本（如 耗时 / Token） */
  statsText?: string;
  routeSnapshot?: {
    title: string;
    complete_plan: any;
    route_data: any;
    panel_days: any[];
    map_route_data: any;
    poi_details?: Record<string, any>;
    summary?: { poi_count: number; distance: number; duration: number };
  };
}

/**
 * 规划模式
 */
export type PlanMode = 'exploratory' | 'planned' | null;

/**
 * 路线数据（用于地图渲染）
 */
export interface RouteData {
  polylines: Array<{ day_index: number; polyline: string; color: string }>;
  markers: Array<{ name: string; location: string; type: string; day_index: number }>;
  center: [number, number] | null;
}

/**
 * useChat Hook 返回值
 */
export interface UseChatReturn {
  /** 聊天消息列表 */
  messages: ChatMessage[];
  /** 当前路线数据 */
  routeData: RouteData | null;
  /** 是否正在加载 */
  isLoading: boolean;
  /** 错误信息 */
  error: string | null;
  /** 当前 SSE 状态文本（最新一条） */
  currentPlanningStatus: string | null;
  /** 规划已耗时（秒） */
  planningElapsedSeconds: number;
  /** 是否正在规划中 */
  isPlanningActive: boolean;
  /** 发送消息 */
  sendMessage: (text: string) => Promise<void>;
  /** 替换消息列表（加载历史时使用） */
  replaceMessages: (nextMessages: ChatMessage[]) => void;
  /** 清空聊天 */
  clearChat: () => void;
  /** 当前高亮的天数 */
  activeDay: number | null;
  /** 设置高亮天数 */
  setActiveDay: (day: number | null) => void;
  /** 当前规划模式 */
  planMode: PlanMode;
  /** 设置规划模式 */
  setPlanMode: (mode: PlanMode) => void;
}

/**
 * 格式化耗时文本
 */
function formatElapsed(seconds: number): string {
  if (seconds < 60) return `${seconds}s`;
  const m = Math.floor(seconds / 60);
  const s = seconds % 60;
  return `${m}m ${s}s`;
}

function isHalfDayPlan(data: any): boolean {
  return data?.duration === 'a half day' || Number(data?.time_budget || 0) === 0.5;
}

/** v6: 从后端 display_granularity 或多层数据推断展示粒度 */
function getDisplayGranularity(data: any): 'short' | 'half_day' | 'day' {
  const explicit =
    data?.display_granularity ||
    data?._route_data?.display_granularity ||
    data?.route_data?.display_granularity;
  if (explicit === 'short' || explicit === 'half_day' || explicit === 'day') return explicit;

  const duration = data?.duration || data?.full_plan?.duration;
  const timeBudget = Number(data?.time_budget ?? data?.full_plan?.time_budget ?? 0);

  if (duration === 'a quarter day' || (timeBudget > 0 && timeBudget < 0.5)) return 'short';
  if (duration === 'a half day' || timeBudget === 0.5) return 'half_day';
  return 'day';
}

function isCompactExploratoryPlan(data: any): boolean {
  const mode =
    data?.plan_mode ||
    data?._route_data?.plan_mode ||
    data?.route_data?.plan_mode ||
    'exploratory';
  return mode !== 'planned' && getDisplayGranularity(data) !== 'day';
}

/**
 * 规范化错误消息：兼容对象和多种字段名
 */
function normalizeErrorMessage(raw: any): string {
  if (typeof raw === 'string' && raw.trim().length > 0) {
    return raw.trim();
  }
  if (raw && typeof raw === 'object') {
    const extracted = raw.error || raw.content || raw.msg || raw.message || raw.detail || raw.error_message;
    if (typeof extracted === 'string' && extracted.trim().length > 0) {
      return extracted.trim();
    }
  }
  return '路线规划失败，但后端未返回错误详情，请查看后端容器日志';
}

/**
 * 生成唯一 ID
 */
function generateId(): string {
  return `msg_${Date.now()}_${Math.random().toString(36).substr(2, 9)}`;
}

/**
 * 按规划模式生成欢迎语
 */
/** v18: 从用户 query 和后端 parsedIntent 生成路线卡片标题 */

// ── title helpers ──

/** 白名单主题词 */
const TITLE_THEME_WHITELIST = new Set([
  '文艺', '历史文化', '历史', '文史', '美食', '逛吃', '夜游', '夜景',
  '亲子', '溜娃', '遛娃', '自然', '赏花', '骑行', '养生', '雅致',
  '购物', '摄影', '户外', '城市漫游', '市井', '热闹',
]);

/** 白名单地点词 */
const TITLE_LOCATION_WHITELIST = new Set([
  '外滩', '陆家嘴', '南京路', '武康路', '豫园', '人民广场',
  '五角场', '徐家汇', '新天地', '田子坊', '淮海路', '北外滩',
  '苏州河', '杨浦滨江',
]);

/** 不允许进入标题的脏词/时间词 */
const TITLE_RAW_BLOCKED = new Set([
  '路线', '规划', '推荐', '攻略', '帮我', '想去', '想逛', '想玩', '想去玩',
  '玩', '游', '逛', '走', '走走', '玩玩', '逛逛', '帮我规划', '请', '安排',
  '今天', '明天', '后天', '今晚', '周末', '本周末', '下周末',
  '一整天', '全天', '整天', '半天', '上午', '下午', '晚上', '夜里', '夜间', '夜游',
  '两天', '2天', '三天', '3天', '全天游',
]);

function _titleTokenIsClean(token: string): boolean {
  const t = String(token || '').trim();
  if (!t || t.length > 6) return false;
  if (TITLE_THEME_WHITELIST.has(t)) return true;
  if (TITLE_LOCATION_WHITELIST.has(t)) return true;
  return ![...TITLE_RAW_BLOCKED].some(word => word && t.includes(word));
}

function getRouteTitleDurationLabel(parsedIntent: any, planData: any, query: string): string {
  const duration =
    parsedIntent?.duration
    || planData?.duration
    || '';

  const timeBudget = Number(
    parsedIntent?.time_budget
    ?? planData?.time_budget
    ?? 0
  );

  const eveningRequested = Boolean(parsedIntent?.evening_requested);

  if (eveningRequested && (duration === 'a quarter day' || duration === 'a half day' || timeBudget <= 0.5)) {
    return '夜游';
  }

  switch (duration) {
    case 'a quarter day': return '短途游';
    case 'a half day': return '半日游';
    case 'a full day': return '一日游';
    case 'a day and a half': return '一日半游';
    case 'two days': return '两日游';
    case 'two and a half days': return '两日半游';
    case 'three days': return '三日游';
  }

  if (timeBudget > 0) {
    if (timeBudget <= 0.25) return '短途游';
    if (timeBudget <= 0.5) return '半日游';
    if (timeBudget <= 1.0) return '一日游';
    if (timeBudget <= 1.5) return '一日半游';
    if (timeBudget <= 2.0) return '两日游';
    if (timeBudget <= 2.5) return '两日半游';
    return '三日游';
  }

  // query 兜底（仅当 parsedIntent 无数据时）
  if (/半天|上午|下午/.test(query)) return '半日游';
  if (/夜游|夜景|晚上|夜里|夜间/.test(query)) return '夜游';
  if (/两天|2天|周末/.test(query)) return '两日游';
  if (/三天|3天/.test(query)) return '三日游';

  return '一日游';
}

function buildRouteCardTitle(query: string, planData: any, backendRouteData: any): string {
  const text = query || '';

  // 1. scope
  const explicitCity = text.match(/(上海|北京|广州|深圳|杭州|苏州|南京|成都|重庆|武汉|西安|长沙|厦门|青岛|天津|宁波|无锡|佛山|东莞|珠海|大连|沈阳|昆明|三亚)(市)?/)?.[1];
  const planCity =
    planData?.city
    || planData?.parsed_intent?.destination
    || backendRouteData?.city
    || backendRouteData?.planning_state?.parsed_intent?.resolved_city
    || '';
  const scope = /附近|周边|身边|附近逛|周围/.test(text)
    ? '附近'
    : (explicitCity || String(planCity).replace(/市$/, '') || '上海');

  // 2. parsedIntent（用于 duration label）
  const parsedIntent =
    backendRouteData?.planning_state?.parsed_intent
    || backendRouteData?.parsed_intent
    || planData?.parsed_intent
    || {};

  const fixedPoiNames = (parsedIntent.fixed_pois || [])
    .map((p: any) => typeof p === 'string' ? p : p?.name)
    .filter(Boolean);

  // auxTerms：只从白名单字段取，raw_keywords 严格过滤
  const rawFiltered = (parsedIntent.raw_keywords || [])
    .map((t: any) => String(t || '').trim())
    .filter((t: string) => t.length <= 6 && text.includes(t) && _titleTokenIsClean(t));

  const auxTerms = [
    parsedIntent.theme_label,
    ...rawFiltered,
    ...(parsedIntent.theme_keywords || []),
    ...(parsedIntent.micro_poi_keywords || []),
    ...fixedPoiNames,
  ].filter(Boolean).map((t: any) => String(t).trim());

  // 标记词的类型：whitelist | aux
  const isWhitelist = (t: string) =>
    TITLE_LOCATION_WHITELIST.has(t) || TITLE_THEME_WHITELIST.has(t);

  const matched: string[] = [];
  const seen = new Set<string>();

  const tryPush = (term: string, fromWhitelist: boolean) => {
    const t = term.trim();
    if (!t || seen.has(t)) return;
    if (!text.includes(t)) return;
    if (!fromWhitelist && !_titleTokenIsClean(t)) return;
    if (fromWhitelist && !isWhitelist(t)) return; // 不应该发生

    // 去重：如果新词是白名单词，看是否和已有词重叠
    const existingIdx = matched.findIndex(existing =>
      existing.includes(t) || t.includes(existing)
    );

    if (existingIdx >= 0) {
      const existingIsWL = isWhitelist(matched[existingIdx]);
      // 只有同是白名单词时，更长词才能替换短词（如"北外滩"替换"外滩"）
      if (fromWhitelist && existingIsWL && t.length > matched[existingIdx].length) {
        matched[existingIdx] = t;
        seen.add(t);
      }
      // aux 词遇到已有白名单词 → 跳过，不替换
      return;
    }

    seen.add(t);
    matched.push(t);
  };

  // 按长度从长到短匹配白名单
  for (const loc of [...TITLE_LOCATION_WHITELIST].sort((a, b) => b.length - a.length)) tryPush(loc, true);
  for (const theme of [...TITLE_THEME_WHITELIST].sort((a, b) => b.length - a.length)) tryPush(theme, true);
  for (const aux of auxTerms) tryPush(aux, false);

  // 最多取 1 个地点/主题词
  const core = matched[0] || '';
  const durationLabel = getRouteTitleDurationLabel(parsedIntent, planData, text);

  // 3. 拼装 — dedup repeated prefix words
  const parts = [scope, core, durationLabel].filter(Boolean);
  let title = parts.join('');
  // v22: Remove repeated words (e.g. "附近附近" → "附近")
  title = title.replace(/(.{1,4})\1{1,}/g, '$1');
  return `${title}路线`;
}

function createWelcomeMessage(_planMode: PlanMode): ChatMessage {
  // v18: 统一欢迎语，不再区分模式
  const content = '一句话，就出发！';
  return {
    id: 'welcome-1',
    role: 'assistant',
    content,
    timestamp: Date.now(),
  };
}

/**
 * 将后端 emit_done 发送的 full_plan 转换为 CompletePlan
 * 适配后端实际数据结构
 */
function convertMeituanToCompletePlan(data: any): CompletePlan {
  const dayPlans: DayPlan[] = [];
  
  // 处理后端发送的 days 数组（来自 full_plan.days）
  const daysData = data.days || data.day_plans || [];
  
  if (Array.isArray(daysData)) {
    for (const dayData of daysData) {
      const timeSlots: TimeSlot[] = [];
      const restaurants: RestaurantRecommendation[] = [];
      
      // 转换锚点为活动
      const anchors = dayData.anchors || [];
      if (anchors.length > 0) {
        const activities: Activity[] = anchors.map((anchor: any) => {
          // 处理 location - 可能不存在，使用默认值
          const location = anchor.location || { lng: 0, lat: 0 };
          
          const poi: POI = {
            id: anchor.name,
            name: anchor.name,
            location: { 
              lng: location.lng || 0, 
              lat: location.lat || 0 
            },
            address: anchor.address || '',
            type: (anchor.type as any) || 'scenic',
            rating: anchor.final_score || anchor.rating || 0,
            description: anchor.recommend_reason || anchor.description || '',
          };
          return {
            poi,
            duration: anchor.duration || 120, // 默认2小时
            description: anchor.recommend_reason || anchor.description || '',
          };
        });
        
        // 根据 duration/time_budget 创建时间槽
        const hasActivities = activities.length > 0;
        if (hasActivities) {
          const granularity = getDisplayGranularity(data);

          if (granularity === 'short') {
            timeSlots.push({
              type: 'short_trip',
              label: '短途路线',
              time_range: '',
              start_time: '',
              end_time: '',
              activities,
            });
          } else if (granularity === 'half_day') {
            timeSlots.push({
              type: 'half_day',
              label: '半天',
              time_range: '',
              start_time: '',
              end_time: '',
              activities,
            });
          } else {
            // 上午槽
            timeSlots.push({
              type: 'morning',
              label: '上午',
              time_range: '09:00-12:00',
              start_time: '09:00',
              end_time: '12:00',
              activities: [activities[0]],
            });

            // 下午槽
            const afternoonActivity = activities.length >= 2 ? activities[1] : activities[0];
            timeSlots.push({
              type: 'afternoon',
              label: '下午',
              time_range: '14:00-18:00',
              start_time: '14:00',
              end_time: '18:00',
              activities: [afternoonActivity],
            });

            // 晚上槽
            if (activities.length >= 3) {
              timeSlots.push({
                type: 'evening',
                label: '晚上',
                time_range: '19:00-21:00',
                start_time: '19:00',
                end_time: '21:00',
                activities: [activities[2]],
              });
            }
          }
        }
      }
      
      // 转换餐饮推荐 → 同时存入 timeSlots 和 restaurants
      const mealSlots = dayData.meal_slots || [];
      for (const meal of mealSlots) {
        if (meal.poi_name) {
          // 将餐饮作为独立时间槽加入
          timeSlots.push({
            type: meal.meal === 'dinner' ? 'dinner' : 'lunch',
            label: meal.meal === 'dinner' ? '晚餐' : '午餐',
            time_range: meal.time_range || (meal.meal === 'dinner' ? '18:00-19:30' : '12:00-14:00'),
            start_time: meal.time_range ? meal.time_range[0]?.toString() || '12:00' : '12:00',
            end_time: meal.time_range ? meal.time_range[1]?.toString() || '14:00' : '14:00',
            activities: [{
              poi: {
                id: meal.poi_name,
                name: meal.poi_name,
                location: {
                  lng: meal.location?.lng || 0,
                  lat: meal.location?.lat || 0,
                },
                address: meal.address || '',
                type: 'restaurant' as any,
                rating: meal.rating || meal.gaode_rating || 0,
                avg_price: meal.avg_cost || meal.avg_price || 0,
              },
              duration: 90,
              description: meal.recommend_reason || `步行${meal.meal_walk_distance_km || 0}km可达`,
            }],
          });
        }
      }
      for (const meal of mealSlots) {
        if (meal.poi_name) {
          restaurants.push({
            poi: {
              id: meal.poi_name,
              name: meal.poi_name,
              location: { 
                lng: meal.location?.lng || 0, 
                lat: meal.location?.lat || 0 
              },
              address: meal.address || '',
              type: 'restaurant',
              rating: meal.rating || meal.gaode_rating || 0,
              avg_price: meal.avg_cost || meal.avg_price || 0,
            },
            cuisine_type: meal.cuisine_type || '',
            avg_price: meal.avg_cost || meal.avg_price || 0,
            rating: meal.rating || meal.gaode_rating || 0,
            distance_from_previous: meal.meal_walk_distance_km || 0,
          });
        }
      }
      
      dayPlans.push({
        day_index: dayData.day_index || 1,
        date: dayData.date || '',
        day_of_week: dayData.day_of_week || '',
        time_slots: timeSlots,
        route_segments: [],
        restaurants,
        daily_distance: 0,
        daily_duration: 0,
        highlights: dayData.highlights || [],
        tips: dayData.tips || [],
      });
    }
  }
  
  // 从多个可能的位置获取天数
  const totalDays = daysData.length || data.days || data.duration || 1;
  
  return {
    plan_id: `plan-${Date.now()}`,
    parsed_intent: {
      destination: data.city || data.destination || '',
      days: typeof totalDays === 'number' ? totalDays : parseInt(totalDays) || 1,
      start_date: data.start_date || '',
      themes: data.themes || [],
      keywords: data.keywords || [],
    },
    days: dayPlans,
    total_distance: data.total_distance || 0,
    total_duration: data.total_duration || 0,
    weather_summary: data.weather_summary || '',
    status: 'confirmed',
  };
}

/**
 * 从 route_data.points 构建右侧面板数据
 * 按天和 slot 分组，POI 顺序与地图 marker 一致
 */
function buildPanelDays(points: any[], segments: any[], planData?: any): any[] {
  if (!Array.isArray(points) || points.length === 0) return [];

  const excludedKinds = new Set(['hint', 'free_explore', 'route_only', 'traffic', 'empty']);
  const halfDayPlan = isHalfDayPlan(planData);

  // v6: compact exploratory display — quarter/half day use single slot
  const displayGranularity = getDisplayGranularity(planData);
  const compactSlot =
    displayGranularity === 'short' ? 'short_trip' :
    displayGranularity === 'half_day' ? 'half_day' : '';

  // v6: detect planned mode — route_order/display_order must drive ordering, not slot
  const isPlannedRoute =
    (points[0]?.plan_mode === 'planned') ||
    (planData?._route_data?.plan_mode === 'planned') ||
    (planData?.plan_mode === 'planned');

  const compactExploratory = !isPlannedRoute && compactSlot !== '';

  const normalizeLocation = (location: any): string => {
    if (!location) return '';
    if (typeof location === 'string') return location;
    if (typeof location === 'object' && location.lng !== undefined && location.lat !== undefined) {
      return `${location.lng},${location.lat}`;
    }
    return '';
  };

  const normalizeSlot = (raw: string): string | null => {
    const key = raw.toLowerCase();
    if (key.includes('short_trip') || key.includes('短途')) return 'short_trip';
    if (key.includes('morning') || key.includes('上午')) return 'morning';
    if (key.includes('half_day') || key.includes('半日') || key.includes('半天')) return 'half_day';
    if (key.includes('lunch') || key.includes('午餐')) return 'lunch';
    if (key.includes('afternoon') || key.includes('下午')) return 'afternoon';
    if (key.includes('dinner') || key.includes('晚餐')) return 'dinner';
    if (key.includes('evening') || key.includes('night') || key.includes('晚上') || key.includes('晚间')) return 'evening';
    return null;
  };

  const findSegmentTo = (point: any, previousPoint?: any) => {
    const name = point.name;
    const previousName = previousPoint?.name;
    return (segments || []).find((seg: any) => {
      if (previousName && seg.from_poi === previousName && seg.to_poi === name) return true;
      return seg.to_poi === name;
    });
  };

  const formatTransportText = (point: any, previousPoint?: any): string => {
    const seg = findSegmentTo(point, previousPoint);
    if (seg?.transport) {
      const distance = Number(seg.distance_km || 0);
      const duration = Number(seg.duration_min || 0);
      if (distance > 0) return `${seg.transport}${distance.toFixed(2)}km可达`;
      if (duration > 0) return `${seg.transport}${Math.round(duration)}分钟可达`;
      return `${seg.transport}可达`;
    }
    if (point.route_annotation) return point.route_annotation;
    if (Number(point.walk_from_route_min || 0) > 0) {
      return `步行${Math.round(Number(point.walk_from_route_min))}分钟可达`;
    }
    return '';
  };

  const dayPlanData = Array.isArray(planData?.days) ? planData.days : [];

  const getAnchorReasonsForDay = (dayIndex: number) => {
    const day = dayPlanData.find((item: any) => Number(item.day_index || item.day || 1) === dayIndex);
    const anchors = Array.isArray(day?.anchors) ? day.anchors : [];
    return anchors
      .map((anchor: any, idx: number) => ({
        name: anchor.name || anchor.poi_name || '',
        reason: anchor.recommend_reason || anchor.reason || anchor.description || '',
        fallbackSlot: compactSlot || (idx === 0 ? 'morning' : idx === 1 ? 'afternoon' : 'evening'),
      }))
      .filter((item: any) => item.name && item.reason);
  };

  const uniqueReasons = (items: Array<{ name: string; reason: string }>) => {
    const seen = new Set<string>();
    return items.filter((item) => {
      const key = `${item.name}|${item.reason}`;
      if (seen.has(key)) return false;
      seen.add(key);
      return true;
    });
  };

  // 1. 过滤有效 POI，使用后端 display_order 作为统一编号。
  // 只有 is_display_poi === true 的点才进入右侧主 POI 列表。
  const ordered = points
    .filter((pt: any) => {
      const kind = String(pt.kind || '');
      if (excludedKinds.has(kind)) return false;
      if (typeof pt.name !== 'string' || pt.name.trim().length === 0) return false;
      // Only display POIs appear in the right panel
      if (pt.is_display_poi !== true && pt.display_order == null) return false;
      return true;
    })
    .map((pt: any, idx: number) => ({
      ...pt,
      _order: Number(pt.display_order ?? pt.route_order ?? idx + 1),
      _sourceIndex: idx,
    }))
    .sort((a: any, b: any) => {
      if (a._order !== b._order) return a._order - b._order;
      return a._sourceIndex - b._sourceIndex;
    });

  // 防御：如果任意 POI 携带明确的 morning/afternoon/dinner/evening slot，
  // 禁止用全局 compact slot 把它们覆盖
  const hasAnyExplicitNonCompact = ordered.some(pt => {
    const es = normalizeSlot(
      `${pt.slot || ''} ${pt.period || ''} ${pt.time_slot || ''} ${pt.time_range || ''} ${pt.segment_period || ''} ${pt.day_period || ''} ${pt.label || ''}`
    );
    return es && es !== 'half_day' && es !== 'short_trip';
  });
  const effectiveCompact = compactExploratory && !hasAnyExplicitNonCompact;

  // 3. 按天分组
  const byDay: Record<number, any[]> = {};
  for (const pt of ordered) {
    const day = pt.day || pt.day_index || 1;
    if (!byDay[day]) byDay[day] = [];
    byDay[day].push(pt);
  }

  // 4. 为每个 POI 分配 slot
  const assignSlot = (pointsInDay: any[]) => {
    // v6: planned mode — display_slot is label only, never affects ordering
    if (isPlannedRoute) {
      return pointsInDay.map((pt) => ({
        ...pt,
        _slot: pt.kind === 'start' || pt.display_label === '起点' ? 'start' : 'planned',
      }));
    }

    // v6: compact exploratory (quarter/half day) — single slot, no morning/afternoon split
    if (compactExploratory) {
      return pointsInDay.map((pt) => ({
        ...pt,
        _slot: compactSlot,
      }));
    }

    // 防御：如果已有 POI 携带明确的 morning/afternoon/dinner/evening 字段，
    // 禁止用全局 halfDayPlan 把它们覆盖成 half_day
    const hasExplicitNonHalfDay = pointsInDay.some(pt => {
      const es = normalizeSlot(
        `${pt.slot || ''} ${pt.period || ''} ${pt.time_slot || ''} ${pt.time_range || ''} ${pt.segment_period || ''} ${pt.day_period || ''} ${pt.label || ''}`
      );
      return es && es !== 'half_day';
    });
    const effectiveHalfDay = halfDayPlan && !hasExplicitNonHalfDay;

    const mealIndices = pointsInDay
      .map((pt, idx) => ({ pt, idx }))
      .filter(({ pt }) => pt.kind === 'meal' || pt.is_meal || pt.kind === 'restaurant');
    const lunchIdx = mealIndices[0]?.idx ?? -1;
    const dinnerIdx = mealIndices[1]?.idx ?? -1;

    // v6: Build a set of meal slot overrides by index — enforce first= lunch, second= dinner
    const mealSlotOverride: Record<number, string> = {};
    for (let mi = 0; mi < mealIndices.length; mi++) {
      const midx = mealIndices[mi].idx;
      // Check if the POI name/fields strongly indicate dinner/lunch
      const pt = mealIndices[mi].pt;
      const mealText = `${pt.name || ''} ${pt.meal || ''} ${pt.category || ''} ${pt.type || ''} ${
        pt.display_slot || ''} ${pt.slot || ''}`;
      const namedSlot = normalizeSlot(mealText);
      if (namedSlot === 'dinner') {
        mealSlotOverride[midx] = 'dinner';
      } else if (namedSlot === 'lunch') {
        mealSlotOverride[midx] = 'lunch';
      } else if (mi === 0) {
        mealSlotOverride[midx] = 'lunch';   // first meal → lunch
      } else {
        mealSlotOverride[midx] = 'dinner';  // second+ meal → dinner
      }
    }
    // Recalculate lunchIdx/dinnerIdx based on overrides (may swap)
    let effectiveLunchIdx = -1;
    let effectiveDinnerIdx = -1;
    for (let mi = 0; mi < mealIndices.length; mi++) {
      const midx = mealIndices[mi].idx;
      if (mealSlotOverride[midx] === 'lunch' && effectiveLunchIdx < 0) effectiveLunchIdx = midx;
      if (mealSlotOverride[midx] === 'dinner' && effectiveDinnerIdx < 0) effectiveDinnerIdx = midx;
    }

    return pointsInDay.map((pt, i) => {
      // v6: Meal POIs — force slot from override, ignore backend display_slot
      if ((pt.kind === 'meal' || pt.is_meal || pt.kind === 'restaurant') && mealSlotOverride[i] !== undefined) {
        return { ...pt, _slot: mealSlotOverride[i] };
      }

      // Non-meal POIs: prefer backend display_slot, but validate
      const backendSlot = pt.display_slot || '';
      const explicitSlot = normalizeSlot(
        `${backendSlot} ${pt.slot || ''} ${pt.period || ''} ${pt.time_slot || ''} ${pt.time_range || ''} ${pt.segment_period || ''} ${pt.day_period || ''} ${pt.label || ''}`
      );

      let slot = explicitSlot || '';
      // v6: start/origin 不应默认 morning；跟随当天首个非 start POI 的 slot
      if (!slot && (pt.kind === 'start' || pt.kind === 'origin')) {
        // 检查是否有 meal POI 能提供 slot 线索
        if (mealIndices.length > 0) {
          const firstMeal = mealIndices[0];
          const mealSlot = mealSlotOverride[firstMeal.idx];
          if (mealSlot === 'dinner') {
            slot = 'dinner';
          } else if (mealSlot === 'lunch') {
            slot = 'lunch';
          }
        }
        if (!slot) {
          slot = compactSlot || 'morning';
        }
      }

      // v6: Defensive — if backend gave a meal slot to a non-meal POI, correct it
      // 但 start/origin 和 meal 自身除外（它们的 slot 是后端明确设定的）
      if ((slot === 'lunch' || slot === 'dinner') && pt.kind !== 'start' && pt.kind !== 'origin' && pt.kind !== 'meal') {
        slot = '';
      }

      if (!slot) {
        if (compactSlot) {
          slot = compactSlot;
        } else if (effectiveLunchIdx >= 0 && i < effectiveLunchIdx) {
          slot = 'morning';
        } else if (effectiveDinnerIdx >= 0 && i > effectiveDinnerIdx) {
          slot = 'evening';
        } else if (effectiveLunchIdx >= 0 && i > effectiveLunchIdx && (effectiveDinnerIdx < 0 || i < effectiveDinnerIdx)) {
          // Between lunch and dinner → afternoon
          slot = 'afternoon';
        } else if (effectiveLunchIdx >= 0 && i > effectiveLunchIdx) {
          // After lunch but no dinner → afternoon
          slot = 'afternoon';
        } else {
          const mid = Math.ceil(pointsInDay.length / 2);
          slot = i < mid ? 'morning' : 'afternoon';
        }
      }
      return { ...pt, _slot: slot };
    });
  };

  // 5. 构建 panelDays
  const slotMeta: Record<string, { type: string; label: string; time_range: string }> = {
    short_trip: { type: 'short_trip', label: '短途路线', time_range: '' },
    half_day: { type: 'half_day', label: '半天', time_range: '' },
    morning: { type: 'morning', label: '上午', time_range: '09:00-12:00' },
    lunch: { type: 'lunch', label: '午餐', time_range: '12:00-14:00' },
    afternoon: { type: 'afternoon', label: '下午', time_range: '14:00-18:00' },
    dinner: { type: 'dinner', label: '晚餐', time_range: '18:00-19:30' },
    evening: { type: 'evening', label: '晚上', time_range: '19:00-21:00' },
  };

  const slotOrder: Record<string, number> = {
    short_trip: 1, half_day: 1, morning: 1, lunch: 2, afternoon: 3, dinner: 4, evening: 5,
  };

  const result: any[] = [];
  let globalFirstPoiMarked = false;

  for (const day of Object.keys(byDay).map(Number).sort()) {
    const pointsInDay = assignSlot(byDay[day]);

    // 标记当天第一个 POI 为起点（全局只标记一次）
    if (!globalFirstPoiMarked && pointsInDay.length > 0) {
      pointsInDay[0]._is_start = true;
      globalFirstPoiMarked = true;
    }

    // 按 slot 分组
    if (isPlannedRoute) {
      // v6: planned mode — all POIs go into one "planned" slot ordered strictly by _order
      const pois = pointsInDay.map((pt) => {
        const previousPoint = pointsInDay.find((candidate: any) => candidate._order === pt._order - 1);
        return {
          order: pt._order,
          name: pt.name,
          kind: pt.kind,
          day_index: day,
          slot: 'planned',
          location: normalizeLocation(pt.location),
          is_start: pt._is_start === true && pt._order === pointsInDay[0]._order,
          transport_text: formatTransportText(pt, previousPoint),
          recommend_reason: pt.recommend_reason || '',
          ugc_review_summary: pt.ugc_review_summary || '',
          ugc_source: pt.ugc_source || '',
          ugc_source_type: pt.ugc_source_type || '',
          ugc_source_url: pt.ugc_source_url || '',
          ugc_evidence_count: pt.ugc_evidence_count || 0,
          ugc_match_confidence: pt.ugc_match_confidence || 0,
          ugc_status: pt.ugc_status || 'not_found',
          ugc_scope: pt.ugc_scope || '',
          ugc_source_name: pt.ugc_source_name || '',
          ugc_label: pt.ugc_label || '网络UGC数据聚合摘要',
          photo_url: pt.photo_url || '',
          rating: pt.rating,
          address: pt.address || '',
          parent_anchor: pt.parent_anchor || pt.parent_name || '',
        };
      });

      const directReasons = pois
        .filter((poi: any) => poi.recommend_reason)
        .map((poi: any) => ({ name: poi.name, reason: poi.recommend_reason }));

      const anchorReasons = getAnchorReasonsForDay(day)
        .filter((reasonItem: any) => {
          return pois.some((poi: any) => {
            return poi.name === reasonItem.name || poi.parent_anchor === reasonItem.name;
          });
        })
        .map(({ name, reason }: any) => ({ name, reason }));

      result.push({
        day_index: day,
        slots: [{
          type: 'planned',
          label: '行程',
          time_range: '',
          pois,
          recommend_reasons: uniqueReasons([...directReasons, ...anchorReasons]),
        }],
      });
    } else {
      // original slot-based grouping for exploratory mode
      const bySlot: Record<string, any[]> = {};
      for (const pt of pointsInDay) {
        const s = pt._slot;
        if (!bySlot[s]) bySlot[s] = [];
        bySlot[s].push(pt);
      }

      const slots = Object.keys(bySlot)
        .sort((a, b) => (slotOrder[a] || 99) - (slotOrder[b] || 99))
        .map(s => {
          const meta = slotMeta[s] || { type: s, label: s, time_range: '' };
          const pois = bySlot[s].map((pt) => {
            const previousPoint = pointsInDay.find((candidate: any) => candidate._order === pt._order - 1);
            return {
            order: pt._order,
            name: pt.name,
            kind: pt.kind,
            day_index: day,
            slot: s,
            location: normalizeLocation(pt.location),
            is_start: pt._is_start === true && pt._order === pointsInDay[0]._order,
            transport_text: formatTransportText(pt, previousPoint),
            recommend_reason: pt.recommend_reason || '',
            ugc_review_summary: pt.ugc_review_summary || '',
            ugc_source: pt.ugc_source || '',
            ugc_source_type: pt.ugc_source_type || '',
            ugc_source_url: pt.ugc_source_url || '',
            ugc_evidence_count: pt.ugc_evidence_count || 0,
            ugc_match_confidence: pt.ugc_match_confidence || 0,
            ugc_status: pt.ugc_status || 'not_found',
            ugc_scope: pt.ugc_scope || '',
            ugc_source_name: pt.ugc_source_name || '',
            ugc_label: pt.ugc_label || '网络UGC数据聚合摘要',
            photo_url: pt.photo_url || '',
            rating: pt.rating,
            address: pt.address || '',
            parent_anchor: pt.parent_anchor || pt.parent_name || '',
          };
          });
          const directReasons = pois
            .filter((poi: any) => poi.recommend_reason)
            .map((poi: any) => ({ name: poi.name, reason: poi.recommend_reason }));

          // anchorReasons: only bind by EXACT name match or parent_anchor match
          // No fuzzy includes matching — prevents "外滩" matching "外滩观光隧道" across slots
          // No fallbackSlot — each reason binds to ONE specific slot
          const anchorReasons = getAnchorReasonsForDay(day)
            .filter((reasonItem: any) => {
              return pois.some((poi: any) => {
                return poi.name === reasonItem.name || poi.parent_anchor === reasonItem.name;
              });
            })
            .map(({ name, reason }: any) => ({ name, reason }));

          return { ...meta, pois, recommend_reasons: uniqueReasons([...directReasons, ...anchorReasons]) };
        });

      result.push({ day_index: day, slots });
    }
  }

  return result;
}

/**
 * 根据交通方式获取颜色
 */
function getTransportColor(transport: string): string {
  switch (transport) {
    case '步行':
      return '#27AE60';  // 绿色
    case '地铁/公交':
      return '#3498DB';  // 蓝色
    case '自驾':
      return '#E67E22';  // 橙色
    case '骑行':
      return '#9B59B6';  // 紫色
    default:
      return '#FFD100';  // 美团黄
  }
}

/**
 * useChat Hook
 */
export function useChat(): UseChatReturn {
  // v18: 单一消息列表，不再按模式隔离（模式由后端自动判断）
  const [messages, setMessages] = useState<ChatMessage[]>([]);
  const [routeData, setRouteData] = useState<RouteData | null>(null);
  const [isLoading, setIsLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [activeDay, setActiveDay] = useState<number | null>(null);
  const [planMode, setPlanMode] = useState<PlanMode>(null);  // v18: display-only, derived from backend response
  const [currentPlanningStatus, setCurrentPlanningStatus] = useState<string | null>(null);
  const [planningElapsedSeconds, setPlanningElapsedSeconds] = useState(0);
  const [isPlanningActive, setIsPlanningActive] = useState(false);

  // 获取 routeStore 的 setCurrentPlan 和 setPanelDays 方法
  const setCurrentPlan = useRouteStore(state => state.setCurrentPlan);
  const setPanelDays = useRouteStore(state => state.setPanelDays);

  // 计时器 refs
  const planningStartedAtRef = useRef<number | null>(null);
  const planningTimerRef = useRef<ReturnType<typeof setInterval> | null>(null);

  // 用于取消请求
  const abortControllerRef = useRef<AbortController | null>(null);
  // 用于跟踪当前流式消息
  const streamingMessageIdRef = useRef<string | null>(null);
  // 用于累积最终结果
  const finalResultRef = useRef<MeituanRouteData | null>(null);
  // 用于累积所有 result 事件的内容
  const accumulatedContentRef = useRef<string>('');
  // 用于存储 complete 事件的数据
  const completeDataRef = useRef<any>(null);
  const statsTextRef = useRef<string>('');
  // 本轮 request ID，用于将推荐理由消息绑定到特定用户请求
  const activeRequestIdRef = useRef<string | null>(null);
  // 本轮用户消息 ID，用于推荐理由消息关联用户消息
  const activeUserMessageIdRef = useRef<string | null>(null);

  /** 清理计时器 */
  const clearPlanningTimer = useCallback(() => {
    if (planningTimerRef.current) {
      clearInterval(planningTimerRef.current);
      planningTimerRef.current = null;
    }
  }, []);

  /** 启动计时器 */
  const startPlanningTimer = useCallback(() => {
    clearPlanningTimer();
    const startedAt = Date.now();
    planningStartedAtRef.current = startedAt;
    setPlanningElapsedSeconds(0);
    planningTimerRef.current = setInterval(() => {
      const elapsed = Math.floor((Date.now() - startedAt) / 1000);
      setPlanningElapsedSeconds(elapsed);
    }, 1000);
  }, [clearPlanningTimer]);

  // 组件卸载时清理计时器
  useEffect(() => {
    return () => clearPlanningTimer();
  }, [clearPlanningTimer]);

  /**
   * 添加消息
   */
  const addMessage = useCallback((msg: Omit<ChatMessage, 'id' | 'timestamp'>) => {
    const newMsg: ChatMessage = {
      ...msg,
      id: generateId(),
      timestamp: Date.now(),
    };
    setMessages(prev => [...prev, newMsg]);
    return newMsg;
  }, []);

  /** v11: 构建当前路线上下文，供后端判断编辑意图 */
  const buildRouteContext = useCallback((): ChatRouteContext | undefined => {
    const rawRouteData: any = useRouteStore.getState().rawRouteData;
    const mapRouteData: any = useRouteStore.getState().mapRouteData;
    const routeId: string | null = (useRouteStore.getState() as any).routeId || rawRouteData?.route_id || null;

    const rawPoints = Array.isArray(rawRouteData?.points) ? rawRouteData.points : [];
    const rawSegments = Array.isArray(rawRouteData?.segments) ? rawRouteData.segments : [];

    const sourcePoints = rawPoints.length > 0 ? rawPoints : [];

    const displayPoints = sourcePoints.filter((pt: any) => {
      const kind = pt.kind || '';
      if (kind === 'hint' || kind === 'free_explore') return false;
      return pt.is_display_poi !== false && pt.is_waypoint !== false && !!pt.name;
    });

    const pointNames = [...new Set(displayPoints.map((pt: any) => String(pt.name || '').trim()).filter(Boolean))];
    const candidateNames: string[] = [];
    const markers = Array.isArray(mapRouteData?.markers) ? mapRouteData.markers : [];
    for (const m of markers) {
      if (m.type === 'candidate' || (m as any).is_candidate) {
        const n = String(m.name || '').trim();
        if (n) candidateNames.push(n);
      }
    }

    const recentUserMessages = messages
      .filter(m => m.role === 'user')
      .slice(-3)
      .map(m => m.content);

    return {
      route_id: routeId,
      point_names: pointNames,
      candidate_names: [...new Set(candidateNames)],
      points: displayPoints,
      segments: rawSegments.map((seg: any) => ({
        from_poi: seg.from_poi,
        to_poi: seg.to_poi,
        day_index: seg.day_index,
        period: seg.period,
        degraded: seg.degraded,
        polyline_source: seg.polyline_source,
      })),
      exclusions: [],
      recent_user_messages: recentUserMessages,
      // v17: 多轮上下文
      context_source: sourcePoints.length > 0 ? 'live' : 'preplan_chat',
      previous_user_messages: messages
        .filter(m => m.role === 'user')
        .slice(-5)
        .map(m => m.content),
      // v18: previous_intent 优先从 planning_state 取，确保准确反映后端自动判定的 plan_mode
      previous_intent:
        (rawRouteData as any)?.planning_state?.parsed_intent
        || (rawRouteData as any)?.parsed_intent
        || null,
      // v18: 附带 plan_mode 信息，供 dispatch 判断 mode_changed
      previous_complete_plan: {
        ...((rawRouteData as any)?.complete_plan || {}),
        plan_mode:
          (rawRouteData as any)?.planning_state?.plan_mode
          || (rawRouteData as any)?.plan_mode
          || 'exploratory',
      },
      current_route_compact: {
        points: displayPoints.map((p: any) => ({
          name: p.name, kind: p.kind, day: p.day, display_slot: p.display_slot,
          typecode: p.typecode, address: p.address, rating: p.rating,
          parent_name: p.parent_name, sub_anchor_name: p.sub_anchor_name,
        })),
        segments: rawSegments.map((s: any) => ({
          from_poi: s.from_poi, to_poi: s.to_poi,
          day_index: s.day_index, transport: s.transport,
          duration_min: s.duration_min, distance_km: s.distance_km,
        })),
        candidate_names: [...new Set(candidateNames)],
      },
    };
  }, [messages]);

  /**
   * 发送消息
   */
  const sendMessage = useCallback(async (text: string) => {
    const trimmedInput = text.trim();
    if (!trimmedInput || isLoading) return;

    // 生成本轮 requestId，添加用户消息
    const requestId = generateId();
    const userMsg = addMessage({ role: 'user', content: trimmedInput, requestId });
    activeRequestIdRef.current = requestId;
    activeUserMessageIdRef.current = userMsg.id;

    // 调用后端 pipeline
    setIsLoading(true);
    setError(null);
    setIsPlanningActive(true);
    setCurrentPlanningStatus('正在理解你的需求...');
    startPlanningTimer();
    finalResultRef.current = null;
    streamingMessageIdRef.current = null;
    accumulatedContentRef.current = '';
    statsTextRef.current = '';
    // 注意：不清理 messages / 历史 recommendReasons / 历史 routeData

    try {
      // 取消之前的请求
      if (abortControllerRef.current) {
        abortControllerRef.current.abort();
      }

      // 游客模式：构建画像数据传给后端
      const { isGuest, user } = useUserStore.getState();
      let guestProfile: GuestProfile | undefined;
      if (isGuest && user) {
        // v18: getCanonicalHomeLocation — 统一使用 home_location 作为路线出发地
        // v26: Use normalizeLocationPayload to guard against bad localStorage data
        const canonicalHome: { lat: number; lng: number; label: string } =
          normalizeLocationPayload(
            (user as any).home_location,
            user.location?.home_address?.lat && user.location?.home_address?.lng
              ? {
                  lat: user.location.home_address.lat,
                  lng: user.location.home_address.lng,
                  label: user.location.home_address.name || FALLBACK_HOME_LOCATION.label,
                }
              : FALLBACK_HOME_LOCATION,
          );

        console.log('[useChat] canonicalHomeLocation used for route origin:', canonicalHome);

        guestProfile = {
          nickname: user.username || '游客',
          gender: user.gender || '男',
          age: user.age || 30,
          activity_pref_tag: user.activity_pref_tag || user.preferences || [],
          food_pref_tag: user.food_preferences || [],
          // city 由后端根据 home_location 自动解析，前端不再传用户可编辑 city
          permanent_city: [],
          // v18: permanent_city_coord 使用 canonical home location
          permanent_city_coord: { lat: canonicalHome.lat, lng: canonicalHome.lng },
          // v18: current_device_location 不再作为独立出发地，传 null 让后端只用 home_location
          current_device_location: null,
          home_location: canonicalHome,
          budget_per_capita: user.budget_per_capita || 100,
        };
      }

      const routeContext = buildRouteContext();

      abortControllerRef.current = sendMeituanMessageStream(
        trimmedInput,
        'auto',  // v18: 后端 LLM 自动判断 exploratory/planned
        undefined,
        {
          // 处理 status 事件 - 只更新最新状态，不创建消息
          onStatus: (message) => {
            if (abortControllerRef.current?.signal.aborted) return;
            console.log('[useChat] 收到状态消息:', message);
            setCurrentPlanningStatus(message);
          },

          // 处理 result 事件 - 累积所有内容
          onResult: (data: any) => {
            if (abortControllerRef.current?.signal.aborted) return;
            console.log('[useChat] 收到 result 事件');
            console.log('[useChat] result data keys:', Object.keys(data || {}));
            console.log('[useChat] has _route_data:', !!data?._route_data);
            console.log('[useChat] has days:', !!data?.days);
            
            // 检查是否是 complete 事件传来的 full_plan（包含 _route_data）
            const isCompleteEvent = data && data._route_data;
            
            if (isCompleteEvent) {
              // 这是 complete 事件传来的完整计划数据
              const backendRouteData = data._route_data || {};
              console.log('[useChat] 收到完整计划数据 (from complete event)');
              console.log('[useChat] route_data:', backendRouteData);
              console.log('[useChat] route_data.points:', backendRouteData?.points?.length);
              console.log('[useChat] route_data.segments:', backendRouteData?.segments?.length);
              console.log('[useChat] route_data.candidate_points.length:', (backendRouteData?.candidate_points || []).length);

              completeDataRef.current = data;

              // v21: Update planMode from authoritative backend response
              const completedRequestId = activeRequestIdRef.current;
              const backendPlanMode =
                (backendRouteData as any)?.planning_state?.plan_mode ??
                (backendRouteData as any)?.plan_mode ??
                (data as any)?.plan_mode ??
                null;
              const prevMode = planMode;
              if (backendPlanMode === 'exploratory' || backendPlanMode === 'planned') {
                setPlanMode(backendPlanMode);
              }
              console.log('[PlanModeFrontendAudit]', {
                requestId: completedRequestId,
                previousPlanMode: prevMode,
                backendRoutePlanMode: (backendRouteData as any)?.plan_mode,
                planningStatePlanMode: (backendRouteData as any)?.planning_state?.plan_mode,
                appliedPlanMode: backendPlanMode,
              });

              // v9: 追加 pipeline 资源统计到输出内容末尾
              const pipelineStats = (data as any).stats;
              if (pipelineStats && typeof pipelineStats === 'object') {
                const s = pipelineStats;
                const parts: string[] = [];
                if (s.elapsed_seconds != null) parts.push(`耗时 ${s.elapsed_seconds}s`);
                if (s.total_tokens != null) parts.push(`Token ${s.total_tokens.toLocaleString()}`);
                parts.push(`DeepSeek ${s.deepseek_calls ?? 0}次`);
                parts.push(`地图 ${s.gaode_calls ?? 0}次`);
                parts.push(`博查 ${s.bocha_calls ?? 0}次`);
                statsTextRef.current = parts.join(' · ');
              }

              // 使用 route_data 转换路线数据格式
              let safeRouteData = null;
              try {
                const routeData = backendRouteData;
                
                if (routeData) {
                  // 转换 segments 为 polylines
                  // 颜色优先级: seg.color > route_color > strokeColor > period映射 > transport fallback
                  const PERIOD_COLOR_MAP: Record<string, string> = {
                    morning: '#E67E22', lunch: '#D35400', afternoon: '#2980B9',
                    dinner: '#C0392B', evening: '#8E44AD', half_day: '#E67E22',
                  };
                  const LINE_COLORS = ['#E67E22', '#2980B9', '#27AE60', '#8E44AD', '#E74C3C', '#F39C12'];
                  const polylines = (routeData.segments || [])
                    .filter((seg: any) => {
                      // v8: 过滤不可绘制路线 — 不在地图上画假直线
                      const src = seg.polyline_source || '';
                      const blockedSources = new Set([
                        'fallback_straight', 'route_api_failed', 'invalid_geometry',
                        'discontinuous_polyline', 'sparse_polyline',
                      ]);
                      if (blockedSources.has(src)) {
                        console.log('[Map] skip non-drawable polyline:', src, seg.from_poi, '->', seg.to_poi);
                        return false;
                      }
                      if (seg.degraded === true && Array.isArray(seg.polyline) && seg.polyline.length <= 2) {
                        console.log('[Map] skip degraded stub polyline:', seg.from_poi, '->', seg.to_poi);
                        return false;
                      }
                      const polyStr = typeof seg.polyline === 'string' ? seg.polyline : '';
                      if (!polyStr && (!Array.isArray(seg.polyline) || seg.polyline.length < 2)) {
                        return false;
                      }
                      return true;
                    })
                    .map((seg: any, sIdx: number) => {
                    let polylineStr = '';
                    if (Array.isArray(seg.polyline)) {
                      polylineStr = seg.polyline.map((coord: number[]) => {
                        if (coord.length >= 2) return `${coord[1]},${coord[0]}`;
                        return '';
                      }).filter(Boolean).join(';');
                    } else if (typeof seg.polyline === 'string') {
                      polylineStr = seg.polyline;
                    }
                    // 颜色优先级链
                    let segColor = seg.color || seg.route_color || seg.strokeColor || '';
                    if (!segColor) {
                      const period = seg.period || seg.slot || '';
                      segColor = PERIOD_COLOR_MAP[period] || '';
                    }
                    if (!segColor) {
                      segColor = LINE_COLORS[sIdx % LINE_COLORS.length];
                    }
                    return {
                      day_index: seg.day_index || 1,
                      polyline: polylineStr,
                      color: segColor,
                      transport: seg.transport || '',
                      period: seg.period || seg.slot || '',
                      degraded: seg.degraded || seg.polyline_source === 'fallback_straight' || false,
                      polyline_source: seg.polyline_source || '',
                      route_error: seg.route_error || '',
                      distance_km: seg.distance_km,
                      duration_min: seg.duration_min,
                      from_poi: seg.from_poi,
                      to_poi: seg.to_poi,
                    };
                  });
                  
                  // 转换 points 为 markers
                  const markers = (routeData.points || [])
                    .filter((pt: any) => pt.kind !== 'hint' && pt.kind !== 'free_explore')
                    .map((pt: any) => {
                      let locationStr = '';

                      // 处理 location - 可能是对象或字符串
                      if (typeof pt.location === 'object') {
                        locationStr = `${pt.location.lng},${pt.location.lat}`;
                      } else if (typeof pt.location === 'string') {
                        locationStr = pt.location;
                      }

                      // 映射 kind 到 type
                      const isStart = pt.kind === 'start' || pt.kind === 'origin' || pt.display_label === '起点';
                      let markerType = 'waypoint';
                      if (isStart) markerType = 'start';
                      else if (pt.kind === 'meal') markerType = 'meal';
                      else if (pt.kind === 'enroute') markerType = 'enroute';
                      else if (pt.kind === 'anchor' || pt.kind === 'anchor_internal') markerType = 'anchor';

                      // start 不显示数字 0，使用 undefined
                      const markerIndex = isStart ? undefined : (pt.display_order ?? undefined);

                      return {
                        poi_id: pt.poi_id,
                        gaode_poi_id: pt.gaode_poi_id,
                        name: pt.name,
                        location: locationStr,
                        type: markerType,
                        day_index: pt.day || 1,
                        index: markerIndex,
                        route_order: pt.route_order,
                        display_order: isStart ? undefined : (pt.display_order ?? undefined),
                        display_slot: pt.display_slot || '',
                        is_display_poi: isStart ? true : (pt.is_display_poi ?? (markerIndex != null)),
                        is_waypoint: pt.is_waypoint,
                        kind: pt.kind,
                        display_label: isStart ? '起点' : (pt.display_label || ''),
                        typecode: pt.typecode,
                        category: pt.category,
                        address: pt.address,
                        rating: pt.rating,
                        avg_cost: pt.avg_cost,
                        photo_url: pt.photo_url,
                        photo_source: pt.photo_source,
                        recommend_reason: pt.recommend_reason,
                        ugc_review_summary: pt.ugc_review_summary || '',
                        ugc_source: pt.ugc_source || '',
                        ugc_source_type: pt.ugc_source_type || '',
                        ugc_source_url: pt.ugc_source_url || '',
                        ugc_evidence_count: pt.ugc_evidence_count || 0,
                        ugc_match_confidence: pt.ugc_match_confidence || 0,
                        ugc_status: pt.ugc_status || 'not_found',
                        ugc_scope: pt.ugc_scope || '',
                        ugc_source_name: pt.ugc_source_name || '',
                        ugc_label: pt.ugc_label || '网络UGC数据聚合摘要',
                        parent_anchor: pt.parent_anchor || pt.parent_name,
                        visit_duration_min: pt.visit_duration_min,
                      };
                    });
                  
                  // v18: candidate_points 默认不显示在地图上，仅保留在 rawRouteData 供右侧面板备选

                  // 计算中心点
                  let center: [number, number] | null = null;
                  if (markers.length > 0 && markers[0].location) {
                    const [lng, lat] = markers[0].location.split(',').map(Number);
                    if (!isNaN(lng) && !isNaN(lat)) {
                      center = [lng, lat];
                    }
                  }

                  safeRouteData = { polylines, markers, center };
                  
                  console.log('[useChat] 转换后的路线数据:', {
                    polylines: polylines.length,
                    markers: markers.length,
                    center,
                  });
                }
              } catch (e) {
                console.error('[useChat] 转换路线数据失败:', e);
              }

              // 将完整计划转换为 CompletePlan 并存储到 routeStore
              let completePlanForReasons: CompletePlan | null = null;
              try {
                completePlanForReasons = convertMeituanToCompletePlan(data);
                console.log('[useChat] 转换 CompletePlan 成功');
                setCurrentPlan(completePlanForReasons);
              } catch (e) {
                console.error('[useChat] 转换 CompletePlan 失败:', e);
              }

              // v20: Reset old route state BEFORE writing new route data (prevents stale routeId reuse)
              useRouteStore.getState().resetRouteState();
              // 写入 routeStore.rawRouteData 和 mapRouteData（收藏按钮依赖这些数据）
              try {
                useRouteStore.getState().setRawRouteData(backendRouteData);
                useRouteStore.getState().convertAndSetRoute(backendRouteData);
                console.log('[useChat] 已写入 routeStore.rawRouteData + mapRouteData (new generation)');
              } catch (e) {
                console.error('[useChat] 写入 routeStore 路线数据失败:', e);
              }

              // 构建右侧面板 POI 数据（从 route_data.points）——必须在推荐理由之前
              let panelDays: any[] = [];
              try {
                const points = backendRouteData.points || [];
                const segments = backendRouteData.segments || [];
                console.log('[ItineraryDebug] route_data.points total:', points.length);
                panelDays = buildPanelDays(points, segments, data);
                console.log('[ItineraryDebug] panelDays slots:', panelDays.map((d: any) => ({
                  day: d.day_index,
                  slots: d.slots.map((s: any) => `${s.type}(${s.pois?.length || 0})`),
                })));
                console.log('[ItineraryDebug] panelDays result:',
                  JSON.stringify(panelDays.map((d: any) => ({
                    day_index: d.day_index,
                    slots: d.slots.map((s: any) => ({
                      type: s.type, label: s.label,
                      pois_count: s.pois?.length || 0,
                      pois: (s.pois || []).map((p: any) => ({
                        order: p.order, name: p.name, kind: p.kind,
                        is_start: p.is_start, slot: p.slot
                      }))
                    }))
                  })), null, 2));
                setPanelDays(panelDays);
                console.log('[ItineraryDebug] setPanelDays called with', panelDays.length, 'days');
              } catch (e) {
                console.error('[ItineraryDebug] 构建 panelDays 失败:', e);
              }

              // 从 panelDays 构建 slot-structured 推荐理由快照
              const SLOT_LABEL_MAP: Record<string, string> = {
                short_trip: '短途路线', half_day: '半天', morning: '上午', lunch: '午饭', afternoon: '下午', dinner: '晚饭', evening: '晚上',
              };
              const SLOT_ORDER_MAP: Record<string, number> = {
                short_trip: 1, half_day: 1, morning: 1, lunch: 2, afternoon: 3, dinner: 4, evening: 5,
              };
              const MEAL_SLOTS = new Set(['lunch', 'dinner']);
              const slotReasons: SlotStructuredReasons[] = [];

              for (const day of panelDays) {
                for (const slot of (day.slots || [])) {
                  const slotType = slot.type || '';
                  const items: SlotReasonItem[] = [];

                  if (MEAL_SLOTS.has(slotType)) {
                    // 餐饮 slot: pois 本身就是午饭/晚饭 POI
                    for (const poi of (slot.pois || [])) {
                      items.push({
                        name: poi.name || '',
                        order: poi.order,
                        kind: poi.kind || 'meal',
                        transport_text: poi.transport_text || '',
                        isMeal: true,
                      });
                    }
                  } else {
                    // 普通 slot: 使用 recommend_reasons
                    for (const reason of (slot.recommend_reasons || [])) {
                      items.push({
                        name: reason.name || '',
                        reason: reason.reason || '',
                        order: 0,
                        kind: '',
                        isMeal: false,
                      });
                    }
                  }

                  if (items.length > 0) {
                    slotReasons.push({
                      slot: slotType,
                      slotLabel: SLOT_LABEL_MAP[slotType] || slot.label || slotType,
                      slotOrder: SLOT_ORDER_MAP[slotType] || 99,
                      dayIndex: (day as any).day_index || 1,
                      items,
                    });
                  }
                }
              }
              // v10: Sort by dayIndex then slotOrder
              slotReasons.sort((a, b) => ((a as any).dayIndex || 0) - ((b as any).dayIndex || 0) || a.slotOrder - b.slotOrder);

              console.log('[useChat] slotReasons built:', slotReasons.map(s => ({
                slot: s.slot, label: s.slotLabel, items: s.items.length,
              })));

              // 同时构建旧格式 reasonsSnapshot 用于向后兼容
              const reasonsSnapshot: Array<{ name: string; reason: string }> = [];
              for (const sr of slotReasons) {
                for (const item of sr.items) {
                  if (item.reason) {
                    reasonsSnapshot.push({ name: item.name, reason: item.reason });
                  } else if (item.isMeal && item.transport_text) {
                    reasonsSnapshot.push({ name: item.name, reason: item.transport_text });
                  }
                }
              }

              // 创建或更新推荐理由消息（按 requestId 绑定，新请求追加而非覆盖历史）
              // 深拷贝 routeData 防止引用被后续请求覆盖
              const routeDataForMessage = safeRouteData
                ? {
                    polylines: [...(safeRouteData.polylines || [])],
                    markers: [...(safeRouteData.markers || [])],
                    center: safeRouteData.center ? [...safeRouteData.center] as [number, number] : null,
                    // v20: Preserve route-level recommendation reason
                    route_recommend_reason: (backendRouteData as any)?.route_recommend_reason || "",
                  }
                : null;

              console.log('[RouteReasonFrontendAudit]', {
                backendReason: (backendRouteData as any)?.route_recommend_reason || '',
                messageReason: routeDataForMessage?.route_recommend_reason || '',
              });

              // v20: POI reason audit
              const points = (backendRouteData as any)?.points || [];
              const pointReasons = points.filter((p: any) => p.recommend_reason?.trim());
              console.log('[PoiReasonFrontendAudit]', {
                backendPointReasonCount: pointReasons.length,
                namesWithReason: pointReasons.map((p: any) => p.name),
              });

              const currentRequestId = activeRequestIdRef.current;
              const currentUserMessage = userMsg.content || '';
              // v18: build poiDetails BEFORE setMessages so routeSnapshot can include it
              const mapDataForPoi = useRouteStore.getState().mapRouteData || {};
              const poiDetails: Record<string, any> = {};
              for (const day of (panelDays || [])) {
                for (const slot of (day.slots || [])) {
                  for (const poi of (slot.pois || [])) {
                    const key = poi.name || '';
                    if (key && !poiDetails[key]) {
                      poiDetails[key] = {
                        poi_id: poi.poi_id || '', gaode_poi_id: poi.gaode_poi_id || '',
                        name: poi.name, location: poi.location || '',
                        address: poi.address || '', rating: poi.rating ?? null,
                        avg_cost: poi.avg_cost ?? null,
                        photo_url: poi.photo_url || '', photo_source: poi.photo_source || '',
                        category: poi.category || '', typecode: poi.typecode || '',
                      };
                    }
                  }
                }
              }

              // v18: build route card data
              const routeCardTitle = buildRouteCardTitle(currentUserMessage, completePlanForReasons, backendRouteData);
              const routeSnapshot = {
                title: routeCardTitle,
                user_input: currentUserMessage || '',
                complete_plan: completePlanForReasons,
                route_data: backendRouteData,
                panel_days: panelDays,
                map_route_data: mapDataForPoi,
                poi_details: poiDetails,
                summary: { poi_count: Object.keys(poiDetails).length, distance: 0, duration: 0 },
              };

              // Capture snapshot for history saving (to be used after setMessages)
              const historySnap = {
                routeData: backendRouteData,
                mapRouteData: mapDataForPoi,
                panelDaysSnap: panelDays,
                completePlanSnap: completePlanForReasons,
                userMsgSnap: userMsg,
                currentRequestIdSnap: currentRequestId,
                currentUserMsgSnap: currentUserMessage,
              };

              setMessages(prev => {
                const existingIdx = currentRequestId
                  ? prev.findIndex(
                      m =>
                        m.role === 'assistant' &&
                        m.displayType === 'recommendReasons' &&
                        m.requestId === currentRequestId
                    )
                  : -1;

                const recommendMsg: ChatMessage = {
                  id: existingIdx >= 0 ? prev[existingIdx].id : generateId(),
                  role: 'assistant' as const,
                  content: '__RECOMMEND_REASONS__',
                  displayType: 'recommendReasons' as const,
                  timestamp: Date.now(),
                  routeData: routeDataForMessage,
                  requestId: currentRequestId || undefined,
                  parentUserMessageId: activeUserMessageIdRef.current || undefined,
                  recommendReasons: reasonsSnapshot.length > 0 ? reasonsSnapshot : undefined,
                  slotReasons: slotReasons.length > 0 ? slotReasons : undefined,
                  statsText: statsTextRef.current || undefined,
                  routeCardTitle,
                  routeCardSubtitle: statsTextRef.current || undefined,
                  routeSnapshot,
                };

                if (existingIdx >= 0) {
                  const updated = [...prev];
                  updated[existingIdx] = recommendMsg;
                  return updated;
                }
                return [...prev, recommendMsg];
              });

              // Save history AFTER state update (outside setMessages to avoid side-effects)
              setTimeout(() => {
                try {
                  const { isGuest } = useUserStore.getState();
                  const mapData = historySnap.mapRouteData || {};
                  // poiDetails already built above, reuse
                  // Use static import at module level instead of dynamic import
                  import('@/services/routeHistory').then(({ routeHistoryService }) => {
                    routeHistoryService.saveHistory(isGuest, {
                      title: `${historySnap.completePlanSnap?.parsed_intent?.destination || '上海'} ${historySnap.completePlanSnap?.parsed_intent?.days || 1}日游`,
                      destination: historySnap.completePlanSnap?.parsed_intent?.destination || '上海',
                      days: historySnap.completePlanSnap?.parsed_intent?.days || 1,
                      request_id: historySnap.currentRequestIdSnap || undefined,
                      user_input: historySnap.currentUserMsgSnap,
                      messages: [historySnap.userMsgSnap, {
                        id: 'recommend-' + Date.now(),
                        role: 'assistant' as const,
                        content: '__RECOMMEND_REASONS__',
                        displayType: 'recommendReasons' as const,
                        timestamp: Date.now(),
                        recommendReasons: reasonsSnapshot.length > 0 ? reasonsSnapshot : undefined,
                        slotReasons: slotReasons.length > 0 ? slotReasons : undefined,
                        routeCardTitle,
                        routeCardSubtitle: statsTextRef.current || undefined,
                        routeSnapshot,
                      }],
                      complete_plan: historySnap.completePlanSnap,
                      route_data: historySnap.routeData,
                      panel_days: historySnap.panelDaysSnap,
                      map_route_data: mapData,
                      poi_details: poiDetails,
                      summary: { poi_count: Object.keys(poiDetails).length, distance: 0, duration: 0 },
                    }).then(() => {
                      console.log('[useChat] 规划历史已保存');
                    }).catch((e: any) => {
                      console.error('[useChat] 保存规划历史失败:', e);
                    });
                  }).catch((e: any) => {
                    console.error('[useChat] 加载历史服务失败:', e);
                  });
                } catch (e) {
                  console.error('[useChat] 构建历史数据失败:', e);
                }
              }, 200);
            } else {
              // 普通的 result 事件 - 累积内容
              const content = data.content || data.reply || data.summary || '';
              if (content) {
                accumulatedContentRef.current += content + '\n\n';
              }

              // 保存最新的数据（用于路线和地图）
              finalResultRef.current = data;

              // 只有累积了有效文本内容时才创建或更新 assistant 消息
              const currentContent = accumulatedContentRef.current.trim();
              const hasRealContent = currentContent.length > 0;

              if (hasRealContent) {
                setMessages(prev => {
                  const existingIdx = streamingMessageIdRef.current
                    ? prev.findIndex(m => m.id === streamingMessageIdRef.current)
                    : -1;

                  if (existingIdx >= 0) {
                    const updated = [...prev];
                    updated[existingIdx] = {
                      ...updated[existingIdx],
                      content: currentContent,
                    };
                    return updated;
                  } else {
                    const newId = generateId();
                    streamingMessageIdRef.current = newId;
                    return [
                      ...prev,
                      {
                        id: newId,
                        role: 'assistant',
                        content: currentContent,
                        timestamp: Date.now(),
                      },
                    ];
                  }
                });
              }
            }
          },

          // 处理 done 事件 - 完成标记，停止计时并清除状态行
          onDone: (data) => {
            if (abortControllerRef.current?.signal.aborted) return;
            console.log('[useChat] 规划完成:', data);
            setIsLoading(false);
            clearPlanningTimer();
            // 800ms 后移除状态行，给完成文案短暂展示
            setTimeout(() => {
              setIsPlanningActive(false);
              setCurrentPlanningStatus(null);
            }, 800);
          },

          // 处理 error 事件 - 错误消息，停止计时并清除状态
          onError: (errorMessage) => {
            if (abortControllerRef.current?.signal.aborted) return;
            console.error('[useChat] 原始错误:', errorMessage);
            const normalized = normalizeErrorMessage(errorMessage);
            console.error('[useChat] 规范化错误:', normalized);
            setError(normalized);
            setIsLoading(false);
            clearPlanningTimer();
            setIsPlanningActive(false);
            setCurrentPlanningStatus(null);

            addMessage({
              role: 'assistant',
              content: `[ROUTE_PLANNER]: 抱歉，处理您的请求时遇到了问题：${normalized}。请重试。`,
            });

            streamingMessageIdRef.current = null;
          },

          onComplete: (reply, route, intent) => {
            // 这个回调在 result 事件触发时也会被调用
            setIsLoading(false);
          },
        },
        guestProfile,
        routeContext
      );
    } catch (err: any) {
      setError(err.message || '服务暂时不可用');
      setIsLoading(false);
      clearPlanningTimer();
      setIsPlanningActive(false);
      setCurrentPlanningStatus(null);
    }
  }, [isLoading, planMode, addMessage, startPlanningTimer, clearPlanningTimer, setMessages]);

  /** 替换消息列表（用于加载历史） */
  const replaceMessages = useCallback((nextMessages: ChatMessage[]) => {
    setMessages(nextMessages.length > 0 ? nextMessages : [createWelcomeMessage(null)]);
  }, []);

  /**
   * 清空聊天
   */
  const clearChat = useCallback(() => {
    setMessages([]);
    setRouteData(null);
    setError(null);
    setActiveDay(null);
    // v6: 不再强制 setPlanMode('exploratory') — 用户停留在当前模式
    clearPlanningTimer();
    setIsPlanningActive(false);
    setCurrentPlanningStatus(null);
    setPlanningElapsedSeconds(0);
    finalResultRef.current = null;
    streamingMessageIdRef.current = null;
    accumulatedContentRef.current = '';
    statsTextRef.current = '';
    completeDataRef.current = null;

    if (abortControllerRef.current) {
      abortControllerRef.current.abort();
    }
  }, [clearPlanningTimer]);

  const currentMessages = messages;
  return {
    messages: currentMessages.length === 0 ? [createWelcomeMessage(planMode)] : currentMessages,
    routeData,
    isLoading,
    error,
    currentPlanningStatus,
    planningElapsedSeconds,
    isPlanningActive,
    sendMessage,
    replaceMessages,
    clearChat,
    activeDay,
    setActiveDay,
    planMode,
    setPlanMode,
  };
}

export default useChat;
