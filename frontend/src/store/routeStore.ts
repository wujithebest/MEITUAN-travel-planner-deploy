// ============================================
// 路线状态管理 - Zustand Store
// 简化版：移除SSE流式相关状态
// ============================================

import { create } from 'zustand';
import type {
  LocationInput,
  DailyRoute,
  RouteSummary,
  POI,
  WeatherInfo,
  MapConfig,
  RouteResponse,
  DailyRouteDTO,
  RoutePointDTO,
  RouteSegmentDTO,
  MapRouteData,
  EnroutePOI,
  TrafficSegment,
} from '@/api/types';
import type { CompletePlan } from '@/types/plan';
import { replanRoute, replanPipelineRoute } from '@/api/route';
import { userApi } from '@/api/user';
import dayjs from 'dayjs';

// 聊天消息类型
export interface ChatMessage {
  id: string;
  role: 'user' | 'assistant' | 'system';
  content: string;
  timestamp: number;
  actions?: ChatAction[];
  sender?: {
    id: string;
    name: string;
    is_agent?: boolean;
  };
  content_type?: string;
  route_data?: any;
}

export interface ChatAction {
  type: 'view_route' | 'modify' | 'save';
  label: string;
  payload?: any;
}

export interface RouteData {
  route_id?: string;
  daily_routes?: DailyRoute[];
  summary?: RouteSummary;
  assistant_message?: string;
}

// AI助手消息类型
export interface AgentMessage {
  id: string;
  sender: {
    id: string;
    name: string;
    is_agent: boolean;
  };
  content: {
    type: string;
    text: string;
    route_data?: any;
  };
  timestamp: string;
}

// 侧边栏标签页类型
type SidebarTab = 'plan' | 'itineraries';

// 规划步骤类型（简化版，仅用于显示进度）
export type PlanningStep = string;

/** 面板POI（从 route_data.points 转换） */
export interface PanelPoi {
  order: number;
  name: string;
  kind: string;
  day_index: number;
  slot: string;
  location: string;
  is_start: boolean;
  transport_text: string;
  recommend_reason: string;
  photo_url?: string;
  rating?: string | number;
  address?: string;
  parent_anchor?: string;
}

/** 面板Slot */
export interface PanelSlot {
  type: string;
  label: string;
  time_range: string;
  pois: PanelPoi[];
  recommend_reason?: string;
}

/** 面板Day */
export interface PanelDay {
  day_index: number;
  slots: PanelSlot[];
}

interface RouteState {
  // UI状态
  activeTab: SidebarTab;
  sidebarCollapsed: boolean;
  timelineCollapsed: boolean;

  // 用户输入
  travelDescription: string;
  transportMode: 'driving' | 'transit' | 'walking' | 'riding';
  travelDate: string;
  considerWeather: boolean;

  // 聊天消息
  chatMessages: ChatMessage[];
  isChatLoading: boolean;

  // AI助手消息
  assistantMessage: string | null;
  agentMessages: AgentMessage[];

  // 路线规划状态（简化）
  isPlanning: boolean;
  planningStep: PlanningStep;
  planningProgress: number;
  currentPlan: CompletePlan | null;
  planCache: Record<string, CompletePlan>;

  // 路线数据
  routeId: string | null;
  dailyRoutes: DailyRoute[];
  summary: RouteSummary | null;
  mainPOIs: POI[];
  enroutePOIs: EnroutePOI[];
  hiddenEnrouteIds: Set<string>;
  trafficSegments: TrafficSegment[];
  planMode: 'precise' | 'intent' | null;

  // 天气数据
  weatherData: Record<string, WeatherInfo>;

  // 加载和错误状态
  loading: boolean;
  error: string | null;

  // POI消歧
  needsDisambiguation: boolean;
  disambiguationOptions: POI[];
  disambiguationContext: string;

  // 选中状态
  selectedPoiId: string | null;
  selectedDay: number | null;
  selectedPOI: POI | null;

  // POI 替换模式
  replaceMode: {
    active: boolean;
    sourcePoiId: string;
    sourceType: 'enroute' | 'route';
  } | null;
  pendingReplaceTarget: POI | null;

  // 地图配置
  mapConfig: MapConfig;

  // ========== 新增：原始后端数据和转换函数 ==========
  
  /** 原始后端路线数据 */
  rawRouteData: DailyRouteDTO | null;
  
  /** 转换后的地图路线数据 */
  mapRouteData: MapRouteData | null;

  /** 右侧面板数据（从 route_data.points 构建） */
  panelDays: PanelDay[];

  // ==================== Actions ====================

  setActiveTab: (tab: SidebarTab) => void;
  setTravelDescription: (desc: string) => void;
  setTransportMode: (mode: 'driving' | 'transit' | 'walking' | 'riding') => void;
  setTravelDate: (date: string) => void;
  setConsiderWeather: (consider: boolean) => void;

  // 聊天相关
  addChatMessage: (message: ChatMessage) => void;
  setChatLoading: (loading: boolean) => void;
  clearChat: () => void;

  // AI助手消息相关
  setAssistantMessage: (message: string | null) => void;
  addAgentMessage: (message: AgentMessage) => void;
  clearAgentMessages: () => void;

  // 路线规划相关
  setPlanningState: (isPlanning: boolean) => void;
  setPlanningStep: (step: PlanningStep) => void;
  setPlanningProgress: (progress: number) => void;
  setCurrentPlan: (plan: CompletePlan | null) => void;
  cachePlan: (planId: string, plan: CompletePlan) => void;

  // 路线数据相关
  setRoute: (routeId: string, dailyRoutes: DailyRoute[], summary: RouteSummary) => void;
  setRouteFromResponse: (response: RouteResponse) => void;
  setEnroutePOIs: (pois: EnroutePOI[]) => void;
  setMainPOIs: (pois: POI[]) => void;
  setMapConfig: (config: Partial<MapConfig>) => void;
  setLoading: (v: boolean) => void;
  setError: (e: string | null) => void;

  // POI消歧相关
  setDisambiguation: (opts: POI[], ctx: string) => void;
  clearDisambiguation: () => void;

  // 选中状态相关
  setSelectedPoi: (id: string | null) => void;
  setSelectedDay: (day: number | null) => void;
  setSelectedPOI: (poi: POI | null) => void;

  // 天气相关
  setWeather: (date: string, weather: WeatherInfo) => void;

  // 沿途POI显示/隐藏
  toggleEnroutePOI: (enrouteId: string) => void;
  getVisibleEnroutePOIs: () => EnroutePOI[];

  // UI相关
  toggleSidebar: () => void;
  toggleTimeline: () => void;

  // POI排序
  reorderPois: (day: number, pois: POI[]) => void;
  movePoiAcrossDays: (fromDay: number, toDay: number, poi: POI, toIndex: number) => void;

  // 更新每日路线
  updateDailyRoute: (day: number, route: DailyRoute) => void;

  // POI 替换模式
  setReplaceMode: (mode: { active: boolean; sourcePoiId: string; sourceType: 'enroute' | 'route' } | null) => void;
  setPendingReplaceTarget: (poi: POI | null) => void;

  // POI 操作 (异步)
  addPoiToRoute: (poi: POI) => Promise<void>;
  removePoiFromRoute: (poiId: string) => Promise<void>;
  replacePoiInRoute: (removeId: string, addPoi: POI) => Promise<void>;
  replanPipelineRoute: (operations: { action: 'remove' | 'replace' | 'add'; poi_id: string; poi?: any; gaode_poi_id?: string; poi_name?: string; poi_location?: string; after_poi_id?: string; after_poi_name?: string; after_poi_location?: string }[]) => Promise<void>;
  recordPoiLike: (poiName: string, poiType: string) => void;
  recordPoiDislike: (poiName: string, poiType: string) => void;
  recordPoiRemove: (poiName: string, poiType: string) => void;

  // ========== 新增 Actions ==========
  
  /** 设置原始后端路线数据 */
  setRawRouteData: (data: DailyRouteDTO | null) => void;
  
  /** 转换并设置地图路线数据 */
  convertAndSetRoute: (data: DailyRouteDTO) => void;

  /** 设置右侧面板 POI 数据 */
  setPanelDays: (data: PanelDay[]) => void;

  /** v6: 应用本地面板突变并重排 */
  applyPanelMutation: (mutation: import('@/utils/panelPoiReorder').PanelMutation) => void;

  /** 从收藏加载路线：恢复完整状态 */
  loadFavoriteRoute: (favorite: any) => void;

  /** 从规划历史加载路线 */
  loadHistoryRoute: (history: any) => void;

  // 重置
  reset: () => void;
}

// 初始状态
const initialState = {
  activeTab: 'plan' as SidebarTab,
  sidebarCollapsed: false,
  timelineCollapsed: false,

  travelDescription: '',
  transportMode: 'driving' as const,
  travelDate: dayjs().format('YYYY-MM-DD'),
  considerWeather: true,

  chatMessages: [],
  isChatLoading: false,

  assistantMessage: null,
  agentMessages: [],

  isPlanning: false,
  planningStep: 'idle' as PlanningStep,
  planningProgress: 0,
  currentPlan: null,
  planCache: {},

  routeId: null,
  dailyRoutes: [],
  summary: null,
  mainPOIs: [],
  enroutePOIs: [],
  hiddenEnrouteIds: new Set<string>(),
  trafficSegments: [],
  planMode: null,

  weatherData: {},

  loading: false,
  error: null,

  needsDisambiguation: false,
  disambiguationOptions: [],
  disambiguationContext: '',

  selectedPoiId: null,
  selectedDay: null,
  selectedPOI: null,

  replaceMode: null,
  pendingReplaceTarget: null,

  mapConfig: {
    center: '121.4906,31.2397',
    zoom: 13,
    markers: [],
    daily_polylines: [],
  } as MapConfig,

  // 新增字段初始值
  rawRouteData: null,
  mapRouteData: null,
  panelDays: [],
  // v20: mutation infrastructure
  routeRevision: 0,
  routeGenerationId: '',
  mutationStatus: 'idle' as 'idle' | 'pending',
  activeMutationId: null as string | null,
};

/**
 * 将后端 DailyRouteDTO 转换为前端 MapRouteData
 */
function convertDailyRouteDTOToMapRouteData(data: DailyRouteDTO): MapRouteData {
  const polylines: MapRouteData['polylines'] = [];
  const markers: MapRouteData['markers'] = [];
  let center: [number, number] | null = null;

  // 颜色优先级: seg.color > period 映射 > transport fallback
  const PERIOD_COLOR_MAP: Record<string, string> = {
    morning: '#E67E22', lunch: '#D35400', afternoon: '#2980B9',
    dinner: '#C0392B', evening: '#8E44AD', half_day: '#E67E22',
  };
  const LINE_COLORS = ['#E67E22', '#2980B9', '#27AE60', '#8E44AD', '#E74C3C', '#F39C12'];

  // 转换 segments 为 polylines（v7: 过滤不可绘制路线）
  for (let sIdx = 0; sIdx < (data.segments || []).length; sIdx++) {
    const seg = (data.segments || [])[sIdx];
    const src = (seg as any).polyline_source || '';
    const blockedSources = new Set([
      'fallback_straight', 'route_api_failed', 'invalid_geometry',
      'discontinuous_polyline', 'sparse_polyline',
    ]);
    if (blockedSources.has(src)) {
      console.log('[RouteStore] skip non-drawable polyline:', src, seg.from_poi, '->', seg.to_poi);
      continue;
    }
    if ((seg as any).degraded === true && Array.isArray(seg.polyline) && seg.polyline.length <= 2) {
      console.log('[RouteStore] skip degraded stub polyline:', seg.from_poi, '->', seg.to_poi);
      continue;
    }
    let polylineStr = '';
    if (Array.isArray(seg.polyline)) {
      polylineStr = seg.polyline
        .map((coord: number[]) => {
          if (coord.length >= 2) return `${coord[1]},${coord[0]}`;
          return '';
        })
        .filter(Boolean)
        .join(';');
    } else if (typeof seg.polyline === 'string') {
      polylineStr = seg.polyline;
    }
    let segColor = (seg as any).color || (seg as any).route_color || (seg as any).strokeColor || '';
    if (!segColor) {
      const period = (seg as any).period || (seg as any).slot || '';
      segColor = PERIOD_COLOR_MAP[period] || '';
    }
    if (!segColor) {
      segColor = LINE_COLORS[sIdx % LINE_COLORS.length];
    }
    polylines.push({
      day_index: seg.day_index,
      polyline: polylineStr,
      color: segColor,
      transport: seg.transport,
      period: (seg as any).period || (seg as any).slot || '',
      degraded: (seg as any).degraded || (seg as any).polyline_source === 'fallback_straight' || false,
      polyline_source: (seg as any).polyline_source || '',
      route_error: (seg as any).route_error || '',
    });
  }

  // 转换 points 为 markers
  for (const pt of (data.points || [])) {
    if ((pt.kind as string) === 'hint') continue;

    // 兼容 location 为 string 或 object 格式
    let lng: number, lat: number;
    if (typeof pt.location === 'string') {
      const parts = pt.location.split(',').map(Number);
      lng = parts[0];
      lat = parts[1];
    } else if (pt.location && typeof pt.location === 'object') {
      lng = Number((pt.location as any).lng || 0);
      lat = Number((pt.location as any).lat || 0);
    } else {
      continue;
    }

    if (isNaN(lng) || isNaN(lat)) continue;

    if (!center) {
      center = [lng, lat];
    }

    // 确定 marker 类型
    const isStart = pt.kind === 'start' || (pt as any).display_label === '起点';
    let markerType: MapRouteData['markers'][0]['type'] = 'waypoint';
    if (isStart) {
      markerType = 'start';
    } else if (pt.kind === 'meal') {
      markerType = 'meal';
    } else if (pt.kind === 'enroute' || !pt.is_waypoint) {
      markerType = 'enroute';
    } else if (pt.kind === 'anchor' || pt.kind === 'anchor_internal') {
      markerType = 'anchor';
    }

    // start 不显示数字 0，使用 undefined
    const markerIndex = isStart ? undefined : ((pt as any).display_order ?? undefined);

    markers.push({
      poi_id: pt.poi_id,
      gaode_poi_id: pt.gaode_poi_id,
      name: pt.name,
      location: `${lng},${lat}`,
      type: markerType,
      day_index: pt.day,
      index: markerIndex,
      route_order: (pt as any).route_order,
      display_order: isStart ? undefined : ((pt as any).display_order ?? undefined),
      display_slot: (pt as any).display_slot || '',
      is_display_poi: isStart ? true : ((pt as any).is_display_poi ?? (markerIndex != null)),
      is_waypoint: pt.is_waypoint,
      kind: pt.kind,
      display_label: isStart ? '起点' : ((pt as any).display_label || ''),
      typecode: pt.typecode,
      category: pt.category,
      address: pt.address,
      rating: pt.rating,
      avg_cost: pt.avg_cost,
      photo_url: pt.photo_url,
      photo_source: pt.photo_source,
      recommend_reason: pt.recommend_reason,
      parent_anchor: pt.parent_anchor || pt.parent_name,
      visit_duration_min: pt.visit_duration_min,
    });
  }

  // v18: candidate_points 默认不显示在地图上，仅保留在 rawRouteData 供右侧面板备选
  // 转换 candidate_points 为蓝色候选 markers（已禁用）

  return { polylines, markers, center };
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
      return '#95A5A6';  // 灰色
  }
}

// 创建Store
export const useRouteStore = create<RouteState>((set, get) => ({
  ...initialState,

  // ==================== UI Actions ====================

  setActiveTab: (tab) => set({ activeTab: tab }),
  setTravelDescription: (desc) => set({ travelDescription: desc }),
  setTransportMode: (mode) => set({ transportMode: mode }),
  setTravelDate: (date) => set({ travelDate: date }),
  setConsiderWeather: (considerWeather) => set({ considerWeather }),

  toggleSidebar: () => set((s) => ({ sidebarCollapsed: !s.sidebarCollapsed })),
  toggleTimeline: () => set((s) => ({ timelineCollapsed: !s.timelineCollapsed })),

  // ==================== 聊天 Actions ====================

  addChatMessage: (message: ChatMessage) =>
    set((state) => ({
      chatMessages: [...state.chatMessages, message],
    })),

  setChatLoading: (isChatLoading: boolean) => set({ isChatLoading }),

  clearChat: () =>
    set({
      chatMessages: [],
      isChatLoading: false,
    }),

  // ==================== AI助手消息 Actions ====================

  setAssistantMessage: (message: string | null) => {
    console.log('[Store] 设置 assistant_message:', message ? `${message.substring(0, 50)}...` : null);
    set({ assistantMessage: message });
  },

  addAgentMessage: (message: AgentMessage) => {
    console.log('[Store] 添加 agent message:', message.content.text.substring(0, 50));
    set((state) => ({
      agentMessages: [...state.agentMessages, message],
      assistantMessage: message.content.text,
    }));
  },

  clearAgentMessages: () => set({ agentMessages: [], assistantMessage: null }),

  // ==================== 路线规划 Actions ====================

  setPlanningState: (isPlanning: boolean) => set({ isPlanning }),

  setPlanningStep: (step: PlanningStep) => set({ planningStep: step }),

  setPlanningProgress: (progress: number) =>
    set({ planningProgress: Math.min(100, Math.max(0, progress)) }),

  setCurrentPlan: (plan: CompletePlan | null) =>
    set((state) => {
      if (plan) {
        const planId = plan.plan_id || `plan-${Date.now()}`;
        return { currentPlan: plan, planCache: { ...state.planCache, [planId]: plan } };
      }
      return { currentPlan: null };
    }),

  cachePlan: (planId: string, plan: CompletePlan) =>
    set((state) => {
      const entries = Object.entries(state.planCache);
      // Keep only the last 5 plans to prevent memory leaks
      if (entries.length >= 5) {
        const sorted = entries.sort(([, a], [, b]) => {
          const aTime = (a as any).plan_id || '';
          const bTime = (b as any).plan_id || '';
          return aTime.localeCompare(bTime);
        });
        const toRemove = sorted.slice(0, entries.length - 4).map(([k]) => k);
        const next = { ...state.planCache, [planId]: plan };
        for (const k of toRemove) delete next[k];
        return { planCache: next };
      }
      return { planCache: { ...state.planCache, [planId]: plan } };
    }),

  // ==================== 路线数据 Actions ====================

  setRoute: (routeId, dailyRoutes, summary) => {
    const mainPOIs = dailyRoutes.flatMap((d) => d.pois);

    set({
      routeId,
      dailyRoutes,
      summary,
      mainPOIs,
      loading: false,
      error: null,
      isPlanning: false,
      planningStep: 'complete',
      planningProgress: 100,
    });
  },

  /** 从完整的RouteResponse设置路线数据 */
  setRouteFromResponse: (response: RouteResponse) => {
    const dailyRoutes = response.daily_routes || [];
    const mainPOIs = response.main_pois || dailyRoutes.flatMap((d) => d.pois);
    const enroutePOIs = response.enroute_pois || [];
    
    // 提取 assistant_message
    const assistantMsg = (response as any).assistant_message || null;
    console.log('[Store] setRouteFromResponse - assistant_message:', assistantMsg ? `${assistantMsg.substring(0, 50)}...` : '无');

    set({
      dailyRoutes,
      summary: response.summary,
      mainPOIs,
      enroutePOIs,
      trafficSegments: response.traffic_segments || [],
      planMode: response.plan_mode || null,
      mapConfig: response.map_config,
      weatherData: response.weather
        ? Object.fromEntries(response.weather.map((w: WeatherInfo, i: number) => [`day_${i}`, w]))
        : {},
      assistantMessage: assistantMsg,
      loading: false,
      error: null,
      isPlanning: false,
      planningStep: 'complete',
      planningProgress: 100,
    });
  },

  setEnroutePOIs: (enroutePOIs) => set({ enroutePOIs }),
  setMainPOIs: (mainPOIs) => set({ mainPOIs }),
  setMapConfig: (config) => set((state) => ({ mapConfig: { ...state.mapConfig, ...config } })),

  setLoading: (loading) => set({ loading }),

  setError: (error) => set({ error, loading: false, isPlanning: false, planningStep: 'error' }),

  // ==================== POI消歧 Actions ====================

  setDisambiguation: (opts, ctx) =>
    set({ needsDisambiguation: true, disambiguationOptions: opts, disambiguationContext: ctx }),

  clearDisambiguation: () =>
    set({ needsDisambiguation: false, disambiguationOptions: [], disambiguationContext: '' }),

  // ==================== 选中状态 Actions ====================

  setSelectedPoi: (id) => set({ selectedPoiId: id }),
  setSelectedDay: (day) => set({ selectedDay: day }),
  setSelectedPOI: (poi) => set({ selectedPOI: poi }),

  // ==================== 天气 Actions ====================

  setWeather: (date, weather) =>
    set((s) => ({
      weatherData: { ...s.weatherData, [date]: weather },
    })),

  // ==================== 沿途POI Actions ====================

  toggleEnroutePOI: (enrouteId) =>
    set((s) => {
      const newHidden = new Set(s.hiddenEnrouteIds);
      if (newHidden.has(enrouteId)) {
        newHidden.delete(enrouteId);
      } else {
        newHidden.add(enrouteId);
      }
      return { hiddenEnrouteIds: newHidden };
    }),

  getVisibleEnroutePOIs: () => {
    const state = get();
    return state.enroutePOIs.filter((p) => !state.hiddenEnrouteIds.has(p.id));
  },

  // ==================== POI排序 Actions ====================

  reorderPois: (day: number, pois: any[]) =>
    set((s) => ({
      dailyRoutes: s.dailyRoutes.map((d) => (d.day_index === day ? { ...d, pois } : d)),
    })),

  movePoiAcrossDays: (fromDay: number, toDay: number, poi: POI, toIndex: number) =>
    set((s) => {
      const routes = s.dailyRoutes.map((d) => {
        if (d.day_index === fromDay) {
          return { ...d, pois: d.pois.filter((p) => p.id !== poi.id) };
        }
        if (d.day_index === toDay) {
          const newPois = [...d.pois];
          newPois.splice(toIndex, 0, poi);
          return { ...d, pois: newPois };
        }
        return d;
      });
      return { dailyRoutes: routes };
    }),

  // ==================== 更新每日路线 ====================

  updateDailyRoute: (day, route) =>
    set((s) => ({
      dailyRoutes: s.dailyRoutes.map((d) => (d.day_index === day ? route : d)),
    })),

  // ==================== POI 替换模式 ====================

  setReplaceMode: (mode) => set({ replaceMode: mode }),
  setPendingReplaceTarget: (poi) => set({ pendingReplaceTarget: poi }),

  // ==================== POI 异步操作 ====================

  addPoiToRoute: async (poi) => {
    const state = get();
    const mainPois = state.mainPOIs;
    const enroutePois = state.enroutePOIs;
    const routeId = state.routeId || '';

    set({ loading: true });

    try {
      const ops = [{ action: 'add' as const, poi, poi_id: undefined }];
      const response = await replanRoute({
        route_id: routeId,
        main_pois: mainPois,
        enroute_pois: enroutePois,
        operations: ops as any,
        transport_mode: state.transportMode,
      });
      set((s) => ({
        dailyRoutes: response.daily_routes || [],
        mainPOIs: response.main_pois || [],
        enroutePOIs: response.enroute_pois || [],
        summary: response.summary || s.summary,
        trafficSegments: response.traffic_segments || [],
        loading: false,
      }));
    } catch {
      set({ loading: false });
    }
  },

  removePoiFromRoute: async (poiId) => {
    const state = get();
    const mainPois = state.mainPOIs;
    const enroutePois = state.enroutePOIs;
    const routeId = state.routeId || '';

    set({ loading: true });

    try {
      const ops = [{ action: 'remove' as const, poi: undefined, poi_id: poiId }];
      const response = await replanRoute({
        route_id: routeId,
        main_pois: mainPois,
        enroute_pois: enroutePois,
        operations: ops as any,
        transport_mode: state.transportMode,
      });
      set((s) => ({
        dailyRoutes: response.daily_routes || [],
        mainPOIs: response.main_pois || [],
        enroutePOIs: response.enroute_pois || [],
        summary: response.summary || s.summary,
        trafficSegments: response.traffic_segments || [],
        loading: false,
      }));
    } catch {
      set({ loading: false });
    }
  },

  replacePoiInRoute: async (removeId, addPoi) => {
    const state = get();
    const mainPois = state.mainPOIs;
    const enroutePois = state.enroutePOIs;
    const routeId = state.routeId || '';

    set({ loading: true });

    try {
      const ops = [{ action: 'replace' as const, poi: addPoi, poi_id: removeId }];
      const response = await replanRoute({
        route_id: routeId,
        main_pois: mainPois,
        enroute_pois: enroutePois,
        operations: ops as any,
        transport_mode: state.transportMode,
      });
      set((s) => ({
        dailyRoutes: response.daily_routes || [],
        mainPOIs: response.main_pois || [],
        enroutePOIs: response.enroute_pois || [],
        summary: response.summary || s.summary,
        trafficSegments: response.traffic_segments || [],
        loading: false,
        replaceMode: null,
        pendingReplaceTarget: null,
      }));
    } catch {
      set({ loading: false, replaceMode: null, pendingReplaceTarget: null });
    }
  },

  replanPipelineRoute: async (operations) => {
    const state = get();
    const rawData = state.rawRouteData;
    if (!rawData) {
      console.warn('[Store] 无 rawRouteData，跳过管线重规划');
      return;
    }

    set({ loading: true });
    try {
      const result = await replanPipelineRoute({
        points: (rawData as any).points || [],
        segments: (rawData as any).segments || [],
        operations: operations as any,
        transport_mode: state.transportMode,
        route_id: state.routeId,
      });

      const rejectedMutation = result.mutation_audit?.find(audit => !audit.applied);
      if (rejectedMutation) {
        throw new Error(rejectedMutation.failure_reason || '路线地点操作未生效');
      }

      const previousPoints = ((rawData as any).points || []).filter((point: any) =>
        point.kind !== 'hint' && point.kind !== 'free_explore'
      );
      const returnedPoints = (result.route.points || []).filter((point: any) =>
        point.kind !== 'hint' && point.kind !== 'free_explore'
      );
      const addOperations = operations.filter(operation => operation.action === 'add');
      if (addOperations.length > 0 && returnedPoints.length !== previousPoints.length + addOperations.length) {
        throw new Error('添加地点后路线点数量未正确增加');
      }
      for (const operation of addOperations) {
        const target = operation.poi || {};
        const targetId = target.gaode_poi_id || target.poi_id || operation.poi_id || '';
        const targetName = target.name || operation.poi_name || '';
        const matches = returnedPoints.filter((point: any) =>
          (targetId && (point.gaode_poi_id === targetId || point.poi_id === targetId))
          || (targetName && point.name === targetName)
        );
        if (matches.length !== 1) {
          throw new Error(matches.length === 0
            ? `添加地点未进入最终路线: ${targetName || targetId}`
            : `添加地点在最终路线中重复: ${targetName || targetId}`);
        }
      }

      const blockedPolylineSources = new Set([
        'fallback_straight', 'route_api_failed', 'invalid_geometry',
        'invalid_coordinates', 'discontinuous_polyline', 'sparse_polyline',
      ]);
      const returnedSegments = result.route.segments || [];
      const invalidSegment = returnedSegments.find((segment: any) => (
        blockedPolylineSources.has(segment.polyline_source || '')
        || !Array.isArray(segment.polyline)
        || segment.polyline.length < 2
      ));
      if (returnedSegments.length === 0 || invalidSegment) {
        console.error('[PoiMutationFrontendAudit] rejected non-drawable route', {
          segmentCount: returnedSegments.length,
          invalidSegment: invalidSegment
            ? `${invalidSegment.from_poi || ''}->${invalidSegment.to_poi || ''}`
            : 'all_segments_missing',
        });
        throw new Error('新路线未生成完整线路，已保留原地图');
      }

      get().convertAndSetRoute({
        ...rawData,
        points: result.route.points,
        segments: result.route.segments,
        route_id: result.route_id,
      } as any);
      set({ routeId: result.route_id, loading: false });
    } catch (e) {
      console.error('[Store] 管线重规划失败:', e);
      set({ loading: false });
      throw e;
    }
  },

  recordPoiLike: (poiName, poiType) => {
    userApi.recordPoiAction(poiName, poiType, 'like');
  },

  recordPoiDislike: (poiName, poiType) => {
    userApi.recordPoiAction(poiName, poiType, 'dislike');
  },

  recordPoiRemove: (poiName, poiType) => {
    userApi.recordPoiAction(poiName, poiType, 'remove');
  },

  // ========== 新增：原始后端数据和转换函数 ==========
  
  setRawRouteData: (data: DailyRouteDTO | null) => {
    console.log('[Store] 设置 rawRouteData:', data ? `${data.points?.length || 0} 个点` : null);
    set({ rawRouteData: data });
  },
  
  convertAndSetRoute: (data: DailyRouteDTO) => {
    console.log('[Store] 转换 DailyRouteDTO 为 MapRouteData');
    const mapRouteData = convertDailyRouteDTOToMapRouteData(data);
    console.log('[Store] 转换完成:', {
      polylines: mapRouteData.polylines.length,
      markers: mapRouteData.markers.length,
    });
    set({ 
      rawRouteData: data,
      mapRouteData,
    });
  },

  // v20: Reset all route state when generating a new route
  resetRouteState: () => {
    set({
      rawRouteData: null, mapRouteData: null, panelDays: [],
      routeId: null, routeRevision: 0, routeGenerationId: '',
      mutationStatus: 'idle', activeMutationId: null,
    });
  },

  // v20: Unified serialized POI mutation — ONLY entry point for add/replace/remove
  executePoiMutation: async (op) => {
    const state = get();
    if (state.mutationStatus === 'pending') {
      console.warn('[Store] mutation already pending, queuing...');
      await new Promise(r => setTimeout(r, 200));
      return get().executePoiMutation(op);
    }
    const mutationId = `mut_${Date.now()}_${Math.random().toString(36).slice(2,6)}`;
    set({ mutationStatus: 'pending', activeMutationId: mutationId });

    try {
      const cur = get();
      const ops: any[] = [{
        action: op.action,
        poi_id: op.poiId || op.candidate?.poi_id || op.candidate?.gaode_poi_id || '',
        poi: op.candidate || undefined,
        after_poi_id: op.afterPoiId || '',
      }];
      const result = await replanPipelineRoute({
        points: (cur.rawRouteData as any)?.points || [],
        segments: (cur.rawRouteData as any)?.segments || [],
        operations: ops,
        transport_mode: cur.transportMode,
        route_id: cur.routeId,
      });
      // v20: Verify the target POI is actually in the final points
      const newPoints = result.route.points || [];
      const targetName = op.candidate?.name || op.poiId;
      const found = newPoints.some((p: any) =>
        (p.name || '') === targetName
        || (p.poi_id || '') === op.poiId
        || (p.gaode_poi_id || '') === op.poiId
      );
      if (!found && op.action === 'add') {
        set({ mutationStatus: 'idle', activeMutationId: null, loading: false });
        throw new Error(`添加的POI未在最终路线中找到: ${targetName}`);
      }
      // Atomic update after success — includes panelDays rebuild
      const rawData = { ...(cur.rawRouteData || {}), points: newPoints, segments: result.route.segments, route_id: result.route_id } as any;
      cur.setRawRouteData(rawData);
      cur.convertAndSetRoute(rawData);
      // v20: Rebuild panelDays from new points
      try {
        const { buildPanelDays } = await import('@/utils/panelPoiReorder');
        const newPanel = buildPanelDays(newPoints, result.route.segments || []);
        if (newPanel && newPanel.length > 0) {
          set({ panelDays: newPanel });
        }
      } catch (_) { /* panel rebuild is best-effort */ }
      set({
        routeId: result.route_id,
        routeRevision: cur.routeRevision + 1,
        mutationStatus: 'idle',
        activeMutationId: null,
        loading: false,
      });
      console.log('[PoiMutationFrontendAudit]', {
        mutationId, routeId: result.route_id,
        routeRevision: cur.routeRevision + 1, action: op.action,
        responsePointNames: result.route.points?.map((p: any) => p.name),
        responseApplied: true, responseIgnored: false,
      });
    } catch (e: any) {
      console.error('[Store] mutation failed:', e);
      set({ mutationStatus: 'idle', activeMutationId: null, loading: false });
      throw e;
    }
  },

  setPanelDays: (data: PanelDay[]) => {
    set({ panelDays: data });
  },

  applyPanelMutation: (mutation) => {
    const state = get();
    const current = state.panelDays;
    if (!current || current.length === 0) return;
    // Dynamic import to avoid circular dependency at module level
    import('@/utils/panelPoiReorder').then(({ applyPanelPoiMutation, buildMarkerOrderMap }) => {
      const next = applyPanelPoiMutation(current, mutation);
      if (next) {
        set({ panelDays: next });
        // Also update mapRouteData markers to keep index/display_order in sync
        const orderMap = buildMarkerOrderMap(next);
        const mapRouteData = state.mapRouteData;
        if (mapRouteData?.markers) {
          const updatedMarkers = mapRouteData.markers.map((m: any) => {
            const key = m.poi_id || m.gaode_poi_id || (m.name && m.location ? `${m.name}:${m.location}` : '') || m.name || '';
            const orderInfo = orderMap[key];
            if (orderInfo) {
              return { ...m, ...orderInfo };
            }
            return m;
          });
          set({
            mapRouteData: { ...mapRouteData, markers: updatedMarkers }
          });
        }
      }
    });
  },

  loadHistoryRoute: (history: any) => {
    console.log('[Store] 加载规划历史:', history.title);
    // 复用 loadFavoriteRoute 的实现逻辑
    get().loadFavoriteRoute(history);
  },

  loadFavoriteRoute: (favorite: any) => {
    console.log('[Store] 加载收藏路线:', favorite.title);
    const routeData = favorite.route_data;
    let mapRouteData = favorite.map_route_data;

    // Helper to detect fallback images
    const isFallbackPhoto = (url: string, source: string): boolean => {
      if (source === 'fallback') return true;
      if (!url) return false;
      const lowered = url.toLowerCase();
      return lowered.includes('/images/shanghai.jpg') || lowered.includes('unsplash.com/photo-1508804185872');
    };

    // 匹配辅助：从 marker key 找 poi_detail
    const findDetail = (details: Record<string, any>, m: any): any | null => {
      const name = m.name || '';
      // 精确匹配
      if (m.poi_id && details[m.poi_id]) return details[m.poi_id];
      if (m.gaode_poi_id && details[m.gaode_poi_id]) return details[m.gaode_poi_id];
      // 遍历 name 匹配
      for (const k of Object.keys(details)) {
        const d = details[k];
        if (d.name === name) return d;
        if (d.poi_id && d.poi_id === m.poi_id) return d;
        if (d.gaode_poi_id && d.gaode_poi_id === m.gaode_poi_id) return d;
      }
      // location 模糊匹配
      const mLoc = typeof m.location === 'string' ? m.location : `${m.location?.lng || ''},${m.location?.lat || ''}`;
      for (const k of Object.keys(details)) {
        const d = details[k];
        const dLoc = typeof d.location === 'string' ? d.location : `${d.location?.lng || ''},${d.location?.lat || ''}`;
        if (name && d.name === name && dLoc === mLoc) return d;
      }
      return null;
    };
    const applyDetail = (item: any) => {
      const detail = findDetail(poiDetails, item);
      if (!detail) return item;
      // Determine safe photo: never use fallback images
      const detailPhotoOk = detail.photo_url && !isFallbackPhoto(detail.photo_url, detail.photo_source || '');
      const itemPhotoOk = item.photo_url && !isFallbackPhoto(item.photo_url, item.photo_source || '');
      let mergedPhotoUrl = '';
      let mergedPhotoSource = '';
      if (itemPhotoOk) {
        mergedPhotoUrl = item.photo_url;
        mergedPhotoSource = item.photo_source || '';
      } else if (detailPhotoOk) {
        mergedPhotoUrl = detail.photo_url;
        mergedPhotoSource = detail.photo_source || '';
      }
      return {
        ...item,
        rating: item.rating ?? detail.rating ?? null,
        gaode_rating: item.gaode_rating ?? detail.gaode_rating ?? detail.rating ?? null,
        avg_cost: item.avg_cost ?? detail.avg_cost ?? null,
        photo_url: mergedPhotoUrl,
        photo_source: mergedPhotoSource,
        address: item.address || detail.address || '',
        recommend_reason: item.recommend_reason || detail.recommend_reason || '',
        reviewCount: item.reviewCount || detail.reviewCount || 0,
        openHours: item.openHours || detail.openHours || '',
        parent_anchor: item.parent_anchor || detail.parent_anchor || '',
        typecode: item.typecode || detail.typecode || '',
        category: item.category || detail.category || '',
        poi_id: item.poi_id || detail.poi_id || '',
        gaode_poi_id: item.gaode_poi_id || detail.gaode_poi_id || '',
      };
    };

    // 构建/还原 poi_details
    let poiDetails: Record<string, any> = favorite.poi_details || {};
    // Clean existing poi_details: remove fallback photos from old cache
    for (const k of Object.keys(poiDetails)) {
      const d = poiDetails[k];
      if (d && d.photo_url && isFallbackPhoto(d.photo_url, d.photo_source || '')) {
        d.photo_url = '';
        d.photo_source = '';
      }
    }
    if (!Object.keys(poiDetails).length && routeData?.points?.length) {
      // 旧收藏兼容：从 route_data.points 直接构建
      for (const pt of routeData.points) {
        const name = pt.name || '';
        const ptLoc = pt.location;
        const ptLng = typeof ptLoc === 'object' ? ptLoc?.lng : (typeof ptLoc === 'string' ? ptLoc.split(',')[0] : '');
        const ptLat = typeof ptLoc === 'object' ? ptLoc?.lat : (typeof ptLoc === 'string' ? ptLoc.split(',')[1] : '');
        const key = pt.poi_id || pt.gaode_poi_id || `${name}:${ptLng},${ptLat}`;
        if (!key || poiDetails[key]) continue;
        const rawPhoto = pt.photo_url || pt.imageUrl || pt.photo || '';
        const rawPhotoSource = pt.photo_source || '';
        const photoIsValid = rawPhoto && !isFallbackPhoto(rawPhoto, rawPhotoSource);
        poiDetails[key] = {
          poi_id: pt.poi_id || '', gaode_poi_id: pt.gaode_poi_id || '',
          name, location: pt.location,
          address: pt.address || pt.formatted_address || '',
          rating: pt.rating ?? pt.gaode_rating ?? null,
          avg_cost: pt.avg_cost ?? null,
          photo_url: photoIsValid ? rawPhoto : '',
          photo_source: photoIsValid ? rawPhotoSource : '',
          category: pt.category || pt.typecode || '',
          typecode: pt.typecode || '',
          recommend_reason: pt.recommend_reason || '',
          visit_duration_min: pt.visit_duration_min || null,
          parent_anchor: pt.parent_anchor || pt.parent_name || '',
          reviewCount: 0, openHours: '',
        };
      }
    }

    // map_route_data 恢复
    if (mapRouteData?.polylines?.length > 0 && mapRouteData.polylines.every((p: any) => p.color)) {
      console.log('[Store] loadFavorite: 使用已保存 mapRouteData');
    } else if (routeData) {
      mapRouteData = convertDailyRouteDTOToMapRouteData(routeData);
    }

    // 将 poi_details 合并到 markers
    if (mapRouteData?.markers?.length) {
      let mergedCount = 0;
      mapRouteData.markers = mapRouteData.markers.map((m: any) => {
        const detail = findDetail(poiDetails, m);
        if (!detail) return m;
        mergedCount++;
        return applyDetail(m);
      });
      const withPhoto = mapRouteData.markers.filter((m: any) => m.photo_url).length;
      const withRating = mapRouteData.markers.filter((m: any) => m.rating != null).length;
      const withAddress = mapRouteData.markers.filter((m: any) => m.address).length;
      console.log('[Favorite] load poi meta counts:', {
        total: mapRouteData.markers.length,
        merged: mergedCount,
        withPhoto,
        withRating,
        withAddress,
        sample: mapRouteData.markers.slice(0, 3).map((m: any) => ({ name: m.name, rating: m.rating, hasPhoto: !!m.photo_url, addr: (m.address || '').slice(0, 20) })),
      });
    }
    const mergedRouteData = routeData
      ? { ...routeData, points: (routeData.points || []).map((pt: any) => applyDetail(pt)) }
      : routeData;
    const mergedPanelDays = (favorite.panel_days || []).map((day: any) => ({
      ...day,
      slots: (day.slots || []).map((slot: any) => ({
        ...slot,
        pois: (slot.pois || []).map((poi: any) => applyDetail(poi)),
      })),
    }));

    set({
      currentPlan: favorite.complete_plan || null,
      rawRouteData: mergedRouteData || null,
      mapRouteData: mapRouteData || null,
      panelDays: mergedPanelDays,
      routeId: favorite.route_id || routeData?.route_id || null,
      loading: false,
      error: null,
      isPlanning: false,
      planningStep: 'complete' as PlanningStep,
      planningProgress: 100,
    });
  },

  // ==================== 重置 ====================

  reset: () => set({ ...initialState, hiddenEnrouteIds: new Set<string>(), planCache: {} }),
}));
