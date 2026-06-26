// ============================================
// API 类型定义 - 与后端Pydantic模型对应
// ============================================

/** 地点输入 - 用户自然语言查询 */
export interface LocationInput {
  /** 用户自然语言输入，如'周末想去上海外滩拍夜景，想吃本帮菜' */
  text: string;
  /** 可选，起点坐标'lng,lat'或地点名称，如'121.4737,31.2304' */
  origin?: string;
  /** 可选，开始日期'2026-06-01' */
  start_date?: string;
  /** 可选，交通方式：'driving'|'walking'|'transit'|'riding'，默认driving */
  transport_mode?: 'driving' | 'walking' | 'transit' | 'riding';
  /** 是否考虑天气 */
  consider_weather?: boolean;
  /** 可选，行程天数 */
  days?: number;
  /** 可选，规划模式 */
  plan_mode?: 'precise' | 'intent' | 'exploratory';
}

/** 意图识别结果 */
export interface Intent {
  /** 目标区域 */
  area: string;
  /** 天数 */
  days: number;
  /** 关键词 */
  keywords: string[];
  /** 规划模式 */
  plan_mode: 'precise' | 'exploratory';
}

export interface POIPhoto {
  title?: string;
  url: string;
}

export interface POIChild {
  id?: string;
  name: string;
  location?: string;
  address?: string;
  type?: string;
  rating?: number;
}

/** POI信息 */
export interface POI {
  /** POI唯一标识 */
  id: string;
  /** POI名称 */
  name: string;
  /** 坐标 'lng,lat' */
  location: string;
  /** 详细地址 */
  address?: string;
  /** POI类型：main(主行程) | enroute(沿途) */
  poi_type?: 'main' | 'enroute';
  /** 分类：景点、餐饮、购物等 */
  category?: string;
  city?: string;
  type?: string;
  /** 评分 0-5 */
  rating?: number;
  /** 开放时间 */
  open_time?: string;
  close_time?: string;
  ambiguity?: boolean;
  duration_minutes?: number;
  /** 建议游玩时长（分钟） */
  suggested_duration?: number;
  /** 最佳游玩时间 */
  best_visit_time?: string;
  /** 描述 */
  description?: string;
  /** 人均消费 */
  price?: string | number;
  /** 照片列表 */
  photos?: POIPhoto[];
  /** 标签 */
  tags?: string[];
  /** 后端扩展字段 */
  tag?: string[];
  tel?: string;
  indoor?: boolean;
  metro_hint?: string;
  district?: string;
  website?: string;
  children?: POIChild[];
  biz_type?: string;
  navi_poiid?: string;
  entr_location?: string;
  exit_location?: string;
  groupbuynum?: number;
  discountnum?: number;
  event?: string;
}

/** 交通方式信息 */
export interface TransportInfo {
  /** 交通方式 */
  mode: string;
  /** 耗时（分钟） */
  duration: number;
  /** 距离（米） */
  distance: number;
}

/** 每日路线中的POI点 */
export interface DailyRoutePOI {
  /** POI信息 */
  poi: POI;
  poi_type?: 'main' | 'enroute';
  polyline?: string;
  /** 到达时间 HH:MM */
  arrival_time?: string;
  /** 离开时间 HH:MM */
  departure_time?: string;
  /** 从上一个点过来的交通方式 */
  transport_from_prev?: TransportInfo | string;
  stay_minutes?: number;
  distance_from_prev?: number;
  duration_from_prev?: number;
  polyline_coords?: [number, number][];
  steps?: string[];
  weather?: WeatherInfo;
  note?: string;
  enroute_info?: {
    insert_after_index: number;
    discovery_reason: string;
    distance_from_route: number;
  };
}

/** 沿途POI - 路线规划时发现的顺路景点 */
export interface EnroutePOI extends POI {
  /** POI类型 */
  type?: string;
  /** 距离路线的距离（米） */
  distance_from_route: number;
  /** 建议游玩时长（分钟） */
  duration_minutes?: number;
  insert_after_index?: number;
  discovery_reason?: string;
  reviews?: Review[];
}

/** 天气信息 */
export interface WeatherInfo {
  forecast_date?: string;
  city?: string;
  /** 最高温度 */
  temp_high: number;
  /** 最低温度 */
  temp_low: number;
  /** 天气状况 */
  condition?: string;
  text_day?: string;
  text_night?: string;
  /** 降雨概率 0-100 */
  rain_probability?: number;
  /** 空气质量指数 */
  aqi?: number;
  /** 出行建议 */
  suggestion?: string;
  wind_level?: number;
  wind_direction?: string;
  humidity?: number;
  is_rainy?: boolean;
  is_high_temp?: boolean;
  is_strong_wind?: boolean;
  indoor_recommended?: boolean;
  weather_tip?: string;
}

/** 每日路线 */
export interface DailyRoute {
  /** 天数索引（从0开始） */
  day_index?: number;
  /** 后端从1开始的天数 */
  day: number;
  /** 日期 YYYY-MM-DD */
  date?: string;
  /** 当日POI列表（包含时间、交通信息） */
  pois: POI[];
  /** 包含交通信息的路线点 */
  points?: DailyRoutePOI[];
  main_pois?: POI[];
  enroute_pois?: EnroutePOI[];
  /** 路线polyline坐标串 */
  polyline?: string;
  /** 总距离（米） */
  distance?: number;
  /** 总时长（分钟） */
  duration?: number;
  total_distance?: number;
  total_duration?: number;
  total_transport_duration?: number;
  enroute_extra_duration?: number;
  weather_tip?: string;
  traffic_segments?: TrafficSegment[];
  smoothness_score?: number;
  /** 当日天气 */
  weather?: WeatherInfo;
}

/** 路线摘要 */
export interface RouteSummary {
  /** 总距离（米） */
  total_distance: number;
  /** 总时长（分钟） */
  total_duration: number;
  /** 总POI数 */
  total_pois: number;
  /** 主行程POI数 */
  main_pois?: number;
  /** 沿途POI数 */
  enroute_pois?: number;
  /** 天数 */
  days?: number;
  total_days?: number;
  plan_count?: number;
  main_pois_count?: number;
  enroute_pois_count?: number;
  enroute_extra_duration?: number;
  route_quality?: 'excellent' | 'good' | 'fair' | 'poor';
  transportation?: string;
}

/** 地图标记点 */
export interface MapMarker {
  /** POI ID */
  id: string;
  /** 名称 */
  name: string;
  /** 坐标 'lng,lat' */
  location: string;
  /** 类型 */
  type: string;
  /** 所属天数 */
  day: number;
}

/** 每日路线polyline */
export interface DailyPolyline {
  /** 天数 */
  day: number;
  /** polyline坐标串 */
  polyline: string;
  /** 颜色 */
  color: string;
}

/** 地图配置 */
export interface MapConfig {
  /** 中心点坐标 */
  center: string | [number, number];
  /** 缩放级别 */
  zoom: number;
  /** 标记点列表 */
  markers: MapMarker[];
  /** 每日路线polyline */
  daily_polylines: DailyPolyline[];
  showTraffic?: boolean;
}

/** 评论信息 */
export interface Review {
  /** 评论ID */
  id: string;
  /** 用户名 */
  username: string;
  /** 评分 */
  rating: number;
  /** 评论内容 */
  content: string;
  /** 评论时间 */
  created_at: string;
  user_id?: string;
  helpful_count?: number;
}

/** 路线响应 - 后端返回的完整数据 */
export interface RouteResponse {
  /** 是否成功 */
  success: boolean;
  /** 提示消息 */
  message: string;
  /** 意图识别结果 */
  intent?: Intent;
  /** 主行程POI列表 */
  main_pois?: POI[];
  /** 沿途POI列表 */
  enroute_pois?: EnroutePOI[];
  /** 每日路线 */
  daily_routes: DailyRoute[];
  /** 路线摘要 */
  summary: RouteSummary;
  /** 地图配置 */
  map_config: MapConfig;
  /** 天气预报 */
  weather?: WeatherInfo[];
  /** 评论列表 */
  reviews?: Review[];
  traffic_segments?: TrafficSegment[];
  plan_mode?: 'precise' | 'intent';
}

/** API响应包装 */
export interface ApiResponse<T = unknown> {
  success: boolean;
  data?: T;
  message?: string;
  code?: string;
}

/** 交通拥堵段 */
export interface TrafficSegment {
  start_index: number;
  end_index: number;
  status: 'smooth' | 'slow' | 'congested' | 'blocked';
  road_name: string;
}

/** 日记条目 */
export interface DiaryEntry {
  id: string;
  day: number;
  title: string;
  content: string;
  photos: string[];
  highlights: string[];
  voice_url?: string;
  map_snapshot?: string;
  created_at: string;
  updated_at: string;
}

/** 旅行日记 */
export interface Diary {
  id: string;
  route_id: string;
  title: string;
  cover_url?: string;
  entries: DiaryEntry[];
  stats: DiaryStats;
  achievements: Achievement[];
  share_link?: string;
  created_at: string;
  updated_at: string;
}

/** 日记统计 */
export interface DiaryStats {
  total_days: number;
  total_distance: number;
  total_photos: number;
  cities_visited: number;
  pois_visited: number;
}

/** 成就徽章 */
export interface Achievement {
  id: string;
  name: string;
  description: string;
  icon: string;
  unlocked_at: string;
}

/** 聊天消息类型 */
export interface ChatMessage {
  id: string;
  role: 'user' | 'assistant' | 'system';
  content: string;
  timestamp: number;
  actions?: ChatAction[];
}

export interface ChatAction {
  type: 'view_route' | 'modify' | 'save';
  label: string;
  payload?: any;
}

/** 规划步骤类型 */
export type PlanningStep = 'idle' | 'intent' | 'poi' | 'weather' | 'route' | 'restaurant' | 'complete' | 'error';

// ============================================
// 新增：后端结构化路线数据类型
// ============================================

/** 路线点 DTO - 与后端 RoutePointDTO 对应 */
export interface RoutePointDTO {
  day: number;
  name: string;
  location: string;        // "lng,lat" 格式
  kind: 'start' | 'anchor' | 'anchor_internal' | 'meal' | 'enroute' | 'hint';
  sub_anchor_name?: string;
  parent_name?: string;
  is_waypoint: boolean;
  is_passthrough: boolean;
  walk_from_route_min: number;
  route_annotation?: string;
  travel_before_min?: number;
}

/** 路线段 DTO - 与后端 RouteSegmentDTO 对应 */
export interface RoutePointDTO {
  poi_id?: string;
  gaode_poi_id?: string;
  typecode?: string;
  category?: string;
  address?: string;
  rating?: number | null;
  avg_cost?: number | string | null;
  photo_url?: string;
  photo_source?: string;
  recommend_reason?: string;
  parent_anchor?: string;
  visit_duration_min?: number | null;
}

export interface RouteSegmentDTO {
  from_poi: string;
  to_poi: string;
  day_index: number;
  transport: '步行' | '地铁/公交' | '自驾' | '骑行';
  duration_min: number;
  distance_km: number;
  polyline: string;         // "lng,lat;lng,lat" 高德格式
  degraded?: boolean;
  polyline_source?: string;
  route_error?: string;
  transport_options?: Array<{
    mode: string;
    label: string;
    transport: string;
    distance_km: number;
    duration_min: number;
    estimated_fare_yuan?: number;
  }>;
}

/** 时间段 DTO - 与后端 TimePeriodDTO 对应 */
export interface TimePeriodDTO {
  period: 'morning' | 'lunch' | 'afternoon' | 'dinner' | 'evening';
  label: string;            // "上午（9:00-12:00）"
  anchor_name: string;      // "南京路步行街周边游览"
  pois: string[];           // 该时段的 POI 名称列表
}

/** 每日路线 DTO - 与后端 DailyRouteDTO 对应 */
export interface DailyRouteDTO {
  day: number;
  points: RoutePointDTO[];
  segments: RouteSegmentDTO[];
  time_periods: TimePeriodDTO[];
  anchor_hints: Record<string, string>;  // 锚点推荐理由
}

/** 规划路线响应 DTO - 与后端 PlanRouteResponse 对应 */
export interface PlanRouteResponse {
  reply: string;             // 现有的文本回复
  has_route: boolean;        // 是否包含路线数据
  route: DailyRouteDTO | null;
  total_days: number;
  map_html_paths: string[];  // 地图文件路径
}

/** 聊天响应 - 包含结构化路线数据 */
export interface ChatResponse {
  reply: string;
  has_route: boolean;
  route: DailyRouteDTO | null;
  total_days: number;
  map_html_paths: string[];
}

/** Step4 输出数据类型 - 自然语言行程方案 */
export interface Step4ItineraryDay {
  /** 天数索引 */
  day_index: number;
  /** 标题如 Day1 */
  title: string;
  /** 详细行程文本 */
  detail: string;
  /** 锚点名称列表 */
  anchors: string[];
  /** polyline坐标串 */
  polyline?: string;
}

/** Step4 输出中的锚点信息 */
export interface Step4Anchor {
  /** 锚点名称 */
  name: string;
  /** 推荐理由 */
  reason: string;
  /** 坐标 'lng,lat' */
  location?: string;
}

/** Step4 输出数据 */
export interface Step4Output {
  /** 行程摘要 */
  summary: string;
  /** 每日行程列表 */
  days: Step4ItineraryDay[];
  /** 锚点列表 */
  anchors: Step4Anchor[];
  /** 总距离 */
  total_distance: string;
  /** 地图文件URL */
  map_url: string;
  /** 路线polyline - 用于地图渲染 */
  route_polylines?: Array<{
    day_index: number;
    polyline: string;
    color?: string;
  }>;
  /** POI标记点 - 用于地图渲染 */
  poi_markers?: Array<{
    name: string;
    location: string;
    type: 'anchor' | 'meal' | 'poi';
    day_index: number;
  }>;
}

/** 聊天消息中的行程预览内容 */
export interface ItineraryPreviewContent {
  /** 消息类型 */
  type: 'itinerary_preview';
  /** 文本内容 */
  text: string;
  /** 路线数据 */
  route_data?: Step4Output;
}

/** 地图渲染用的路线数据 */
export interface MapRouteData {
  polylines: Array<{
    day_index: number;
    polyline: string;
    color: string;
    transport?: string;
    degraded?: boolean;
    polyline_source?: string;
    route_error?: string;
  }>;
  markers: Array<{
    poi_id?: string;
    gaode_poi_id?: string;
    name: string;
    location: string;
    type: 'start' | 'anchor' | 'meal' | 'enroute' | 'waypoint' | 'candidate';
    day_index: number;
    index?: number;
    typecode?: string;
    category?: string;
    address?: string;
    rating?: number | null;
    avg_cost?: number | string | null;
    photo_url?: string;
    photo_source?: string;
    recommend_reason?: string;
    parent_anchor?: string;
    visit_duration_min?: number | null;
    // candidate marker 扩展字段
    is_candidate?: boolean;
    candidate_source?: string;
    theme?: 'yellow' | 'blue';
    is_display_poi?: boolean;
    is_waypoint?: boolean;
    kind?: string;
    display_label?: string;
    display_order?: number | null;
    display_slot?: string;
    route_order?: number;
    sub_anchor_name?: string;
    gaode_rating?: number | string | null;
    candidate_score?: number;
  }>;
  center: [number, number] | null;
}

/** 时间段颜色映射 */
export const TIME_PERIOD_COLORS: Record<string, { primary: string; light: string }> = {
  morning:   { primary: '#E67E22', light: '#F5CBA7' },   // 橙
  lunch:     { primary: '#D35400', light: '#FAD7A1' },   // 深橙
  afternoon: { primary: '#2980B9', light: '#AED6F1' },   // 蓝
  dinner:    { primary: '#C0392B', light: '#F5B7B1' },   // 红
  evening:   { primary: '#8E44AD', light: '#D2B4DE' },   // 紫
};

/** 交通方式样式 */
export const TRANSPORT_STYLES: Record<string, { dashArray?: string; weight: number }> = {
  '步行':     { weight: 4 },
  '地铁/公交': { dashArray: '10, 10', weight: 3 },
  '自驾':     { dashArray: '10, 10', weight: 3 },
  '骑行':     { dashArray: '5, 5', weight: 3 },
};
