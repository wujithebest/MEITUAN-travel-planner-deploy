/**
 * 美团 AI 对话 API - 流式版本
 * 调用后端 /api/meituan/chat/stream 接口
 * 支持 SSE 实时推送规划进度，使用不同的 event 类型区分消息
 * 
 * SSE 事件类型：
 * - status: 进度消息（如"正在加载用户信息..."）
 * - result: 最终结果（包含路线数据）
 * - done: 完成标记
 * - error: 错误消息
 */

import { buildApiUrl } from '@/config/api.config';

/**
 * 游客画像数据（传给后端）
 */
export interface GuestProfile {
  nickname: string;
  gender: string;
  age: number;
  activity_pref_tag: string[];
  food_pref_tag: string[];
  permanent_city: string[];
  permanent_city_coord: { lat: number; lng: number };
  current_device_location: { lat: number; lng: number; label: string } | null;
  home_location: { lat: number; lng: number; label: string } | null;
  budget_per_capita: number;
}

/** v11: 聊天编辑上下文 — 携带当前路线信息供后端判断修改/新增/删除意图 */
export interface ChatRouteContext {
  route_id?: string | null;
  context_source?: "live" | "history_loaded";
  point_names: string[];
  candidate_names: string[];
  points: any[];
  segments?: Array<{
    from_poi?: string;
    to_poi?: string;
    day_index?: number;
    period?: string;
    degraded?: boolean;
    polyline_source?: string;
  }>;
  exclusions?: string[];
  recent_user_messages?: string[];
  previous_user_messages?: string[];
  previous_intent?: object;
  previous_complete_plan?: object;
  current_route_compact?: {
    points: any[];
    segments: any[];
    candidate_names: string[];
  };
}

/**
 * 路线数据
 */
export interface MeituanRouteData {
  /** 路线 polyline */
  polyline: string;
  /** POI 列表 */
  pois: Array<{
    name: string;
    location: { lat: number; lng: number };
    typecode: string;
    is_meal: boolean;
    parent_anchor: string;
    gaode_rating?: number;
    avg_cost?: number;
  }>;
  /** 天数 */
  days: number;
  /** 每日计划 */
  day_plans: Array<{
    day_index: number;
    anchors: Array<{
      name: string;
      recommend_reason: string;
      location: { lat: number; lng: number };
      typecode: string;
      final_score: number;
    }>;
    meal_slots: any[];
  }>;
  /** 锚点列表 */
  anchors: Array<{
    name: string;
    recommend_reason: string;
    location: { lat: number; lng: number };
    typecode: string;
    final_score: number;
  }>;
  /** 路线 polyline 列表 */
  polylines: Array<{
    day_index: number;
    from_poi: string;
    to_poi: string;
    polyline: Array<[number, number]>;
    transport: string;
    duration_min: number;
    distance_km: number;
  }>;
  /** 行程摘要 */
  summary: string;
  /** 意图数据 */
  intent?: MeituanIntentData;
  /** 回复文本 */
  reply?: string;
  /** v9: Pipeline 资源消耗统计 */
  stats?: PipelineStatsData;
}

/** v9: Pipeline 资源消耗统计 */
export interface PipelineStatsData {
  elapsed_seconds: number;
  deepseek_calls: number;
  deepseek_prompt_tokens: number;
  deepseek_completion_tokens: number;
  total_tokens: number;
  gaode_calls: number;
  bocha_calls: number;
}

/**
 * 后端路线点（用于验证）
 */
export interface BackendRoutePoint {
  name: string;
  location: { lat: number; lng: number };
  kind: string;
  day: number;
  is_waypoint: boolean;
  walk_from_route_min: number;
  route_annotation: string;
}

/**
 * 后端路线段（用于验证）
 */
export interface BackendRouteSegment {
  from_poi: string;
  to_poi: string;
  day_index: number;
  transport: string;
  duration_min: number;
  distance_km: number;
  polyline: [number, number][]; // [[lat, lng], ...]
  degraded?: boolean;
  polyline_source?: string;
  route_error?: string;
}

/**
 * 路线数据（用于前端验证）
 */
export interface RouteVerificationData {
  /** 路线点列表 */
  points: BackendRoutePoint[];
  /** 路线段列表 */
  segments: BackendRouteSegment[];
  /** 锚点提示 */
  hints: Record<string, string>;
  /** 途经点标注 */
  waypoint_annotations: Record<string, {
    is_waypoint: boolean;
    walk_from_route_min: number;
    day: number;
    same_building?: boolean;
  }>;
}

/**
 * 完整计划数据（包含 route_data）
 */
export interface FullPlanData {
  /** 行程摘要 */
  summary: string;
  /** 城市 */
  city: string;
  /** 时长 */
  duration: string;
  /** 每日计划 */
  days: Array<{
    day_index: number;
    anchors: Array<{
      name: string;
      recommend_reason: string;
    }>;
    meal_slots: any[];
  }>;
}

/**
 * Complete 事件数据
 */
export interface CompleteEventData {
  /** 地图路径 */
  map_paths: string[];
  /** 完整计划 */
  full_plan: FullPlanData;
  /** 路线数据（用于验证） */
  route_data: RouteVerificationData;
}

/**
 * 意图数据
 */
export interface MeituanIntentData {
  /** 时长 */
  duration: string;
  /** 开始时间 */
  start_time: string | null;
  /** 原始关键词 */
  raw_keywords: string[];
  /** 搜索关键词 */
  search_keywords: string[];
  /** 固定 POI */
  fixed_pois: Array<{
    name: string;
    user_time_budget: string | null;
  }>;
  /** 餐饮偏好 */
  food_pref_keywords: string[];
  /** 人均预算 */
  budget_per_capita: number | null;
  /** 交通方式 */
  transport_hint: string;
  /** 是否包含晚上活动 */
  evening_requested: boolean;
}

/**
 * SSE 事件类型
 */
export type SSEEventType = 'status' | 'result' | 'done' | 'error' | 'complete';

/**
 * SSE 消息
 */
export interface SSEMessage {
  event: SSEEventType;
  data: any;
}

/**
 * 流式聊天回调函数
 */
export interface StreamCallbacks {
  /** 收到状态消息（进度更新） */
  onStatus?: (message: string) => void;
  /** 收到最终结果 */
  onResult?: (data: MeituanRouteData) => void;
  /** 规划完成 */
  onDone?: (data: { 
    html_paths?: string[];
    route_data?: RouteVerificationData;
  }) => void;
  /** 发生错误 */
  onError?: (error: string) => void;
  /** 兼容旧版：收到消息片段 */
  onMessage?: (content: string) => void;
  /** 兼容旧版：规划完成 */
  onComplete?: (reply: string, route: MeituanRouteData, intent: MeituanIntentData) => void;
}

/**
 * 解析 SSE 消息
 * 
 * @param rawData 原始 SSE 数据
 * @returns 解析后的消息对象
 */
function parseSSEMessage(rawData: string): SSEMessage | null {
  const lines = rawData.trim().split('\n');
  let event: SSEEventType = 'status';
  let dataStr = '';

  for (const line of lines) {
    if (line.startsWith('event: ')) {
      event = line.slice(7) as SSEEventType;
    } else if (line.startsWith('data: ')) {
      dataStr = line.slice(6);
    }
  }

  if (!dataStr) {
    return null;
  }

  try {
    const data = JSON.parse(dataStr);
    return { event, data };
  } catch (e) {
    console.error('[MeituanChatAPI] 解析 SSE 数据失败:', e);
    return null;
  }
}

/**
 * 发送流式聊天消息
 * 后端接口：POST /api/meituan/chat/stream
 * 
 * @param message 用户输入文本
 * @param planMode 规划模式：exploratory（自由探索）或 planned（连续决策）
 * @param userId 用户ID（可选）
 * @param callbacks 回调函数
 * @returns AbortController 用于取消请求
 */
export function sendMeituanMessageStream(
  message: string,
  planMode: 'exploratory' | 'planned' = 'exploratory',
  userId?: string,
  callbacks?: StreamCallbacks,
  guestProfile?: GuestProfile,
  routeContext?: ChatRouteContext
): AbortController {
  const controller = new AbortController();
  const { onStatus, onResult, onDone, onError, onMessage, onComplete } = callbacks || {};

  console.log('[MeituanChatAPI] 发送流式消息', { message, planMode });

  let receivedAnyEvent = false;
  let receivedTerminalEvent = false;

  // 使用 fetch 直接调用以支持 SSE（buildApiUrl 会在生产环境指向 Render 后端）
  fetch(buildApiUrl('/meituan/chat/stream'), {
    method: 'POST',
    headers: {
      'Content-Type': 'application/json',
    },
    body: JSON.stringify({
      message,
      user_id: userId || localStorage.getItem('user_id') || 'default',
      plan_mode: planMode,
      guest_profile: guestProfile || undefined,
      route_context: routeContext || undefined,
      client_sent_at: new Date().toISOString(),
      client_timezone: Intl.DateTimeFormat().resolvedOptions().timeZone || 'Asia/Shanghai',
    }),
    signal: controller.signal,
  })
    .then(async (response) => {
      if (!response.ok) {
        throw new Error(`HTTP error! status: ${response.status}`);
      }

      const reader = response.body?.getReader();
      if (!reader) {
        throw new Error('Response body is not readable');
      }

      const decoder = new TextDecoder();
      let buffer = '';

      while (true) {
        const { done, value } = await reader.read();
        if (done) break;

        buffer += decoder.decode(value, { stream: true });

        // 处理 SSE 消息（以 \n\n 分隔）
        const messages = buffer.split('\n\n');
        buffer = messages.pop() || ''; // 保留最后一个不完整的消息

        for (const msg of messages) {
          if (!msg.trim()) continue;

          const parsed = parseSSEMessage(msg);
          if (!parsed) continue;

          const { event, data } = parsed;
          receivedAnyEvent = true;

          console.log(`[MeituanChatAPI] 收到 ${event} 事件:`, data);

          switch (event) {
            case 'status':
              // 进度消息 — 只更新状态行，不创建 assistant 消息
              if (data.msg && onStatus) {
                onStatus(data.msg);
              }
              // 注意：status 事件绝对不能调用 onMessage/onResult
              break;

            case 'result':
              // 最终结果
              if (onResult) {
                onResult(data as MeituanRouteData);
              }
              // 兼容旧版
              if (onComplete) {
                const routeData = data as MeituanRouteData;
                onComplete(
                  routeData.reply || '',
                  routeData,
                  routeData.intent || {} as MeituanIntentData
                );
              }
              break;

            case 'complete':
              receivedTerminalEvent = true;
              // 完成标记 - 后端发送的完整计划数据
              console.log('[MeituanChatAPI] 收到 complete 事件');
              console.log('[MeituanChatAPI] complete data:', data);
              
              // 后端可能直接发送 CompleteEventData 或包装在 content 中
              const completeData = data.content as CompleteEventData || data as CompleteEventData;
              
              console.log('[MeituanChatAPI] completeData:', completeData);
              console.log('[MeituanChatAPI] route_data:', completeData?.route_data);
              console.log('[MeituanChatAPI] route_data.points:', completeData?.route_data?.points?.length);
              console.log('[MeituanChatAPI] route_data.segments:', completeData?.route_data?.segments?.length);
              
              // 存储 route_data 到全局状态（用于验证）
              if (completeData?.route_data) {
                (window as any).__ROUTE_DATA__ = completeData.route_data;
                console.log('[MeituanChatAPI] 已存储 route_data 到 window.__ROUTE_DATA__');
              }
              
              // 触发 onResult 回调，传递完整数据
              // v9: 提取 pipeline 资源统计
              const pipelineStats = (data as any).stats as import('./meituanChat').PipelineStatsData | undefined;

              if (onResult && completeData?.full_plan) {
                console.log('[MeituanChatAPI] 触发 onResult 回调');
                onResult({
                  ...completeData.full_plan,
                  _route_data: completeData.route_data,
                  _map_paths: completeData.map_paths,
                  stats: pipelineStats,
                } as any);
              }
              // 同时触发 onDone 回调
              if (onDone) {
                console.log('[MeituanChatAPI] 触发 onDone 回调');
                onDone({
                  html_paths: completeData?.map_paths || [],
                  route_data: completeData?.route_data,
                  stats: pipelineStats,
                });
              }
              break;

            case 'done':
              receivedTerminalEvent = true;
              // 完成标记
              if (onDone) {
                onDone(data as { html_paths?: string[] });
              }
              break;

            case 'error':
              receivedTerminalEvent = true;
              // 兼容多种后端错误字段：后端 emit_error 使用 content，也支持 error/msg/message/detail
              {
              console.error('[MeituanChatAPI] 收到 SSE error 事件:', data);
              const errorMsg =
                data?.error ||
                data?.content ||
                data?.msg ||
                data?.message ||
                data?.detail ||
                data?.error_message ||
                '未知错误';
              if (onError) {
                onError(String(errorMsg));
              }
              break;
            }

            default:
              console.warn('[MeituanChatAPI] 未知事件类型:', event);
          }
        }
      }
    })
    .catch((error) => {
      if (error.name === 'AbortError') {
        console.log('[MeituanChatAPI] 请求已取消');
        return;
      }

      // 如果已收到终止事件（complete/done/error），后续网络关闭是正常的
      if (receivedTerminalEvent) {
        console.warn('[MeituanChatAPI] 终止事件后连接关闭，忽略后续网络错误:', error);
        return;
      }

      console.error('[MeituanChatAPI] 流式请求失败:', error);

      if (onError) {
        const rawMessage = String(error?.message || '');
        const isNetworkError =
          error instanceof TypeError ||
          /network|failed to fetch|load failed|connection|transport|terminated/i.test(rawMessage);

        const friendlyMessage = isNetworkError
          ? (receivedAnyEvent
              ? '规划连接在处理中被中断，可能是云服务空闲连接被关闭，请重试一次。'
              : '暂时无法连接后端服务，请检查网络后重试。')
          : (rawMessage || '请求失败');

        onError(friendlyMessage);
      }
    });

  return controller;
}

/**
 * 从路线数据中提取地图渲染所需的数据
 * 兼容后端发送的 full_plan 数据结构（可能缺少某些字段）
 * 
 * @param routeData 路线数据
 * @returns 地图渲染数据
 */
export function extractMeituanMapData(routeData: any): {
  polylines: Array<{ day_index: number; polyline: Array<[number, number]>; color: string }>;
  markers: Array<{ name: string; location: [number, number]; type: string; day_index: number }>;
  center: [number, number] | null;
} {
  const colors = ['#3366FF', '#FF6633', '#33CC66', '#CC33FF', '#FFCC33'];

  // 提取 polylines - 如果不存在则返回空数组
  const polylines = (routeData?.polylines || []).map((p: any, idx: number) => ({
    day_index: p.day_index || 1,
    polyline: Array.isArray(p.polyline) ? p.polyline : [],
    color: p.color || colors[idx % colors.length],
    degraded: p.degraded || false,
    polyline_source: p.polyline_source || '',
    route_error: p.route_error || '',
  }));

  // 提取 markers - 兼容 anchors 和 days[].anchors 两种结构
  let markers: Array<{ name: string; location: [number, number]; type: string; day_index: number }> = [];
  
  // 尝试从顶层 anchors 提取
  if (routeData?.anchors && Array.isArray(routeData.anchors)) {
    markers = routeData.anchors.map((anchor: any, idx: number) => ({
      name: anchor.name || `POI ${idx + 1}`,
      location: [
        anchor.location?.lng || 0,
        anchor.location?.lat || 0,
      ] as [number, number],
      type: 'anchor',
      day_index: Math.min(idx, (routeData.day_plans?.length || routeData.days?.length || 1) - 1) + 1,
    }));
  } 
  // 尝试从 days[].anchors 提取
  else if (routeData?.days && Array.isArray(routeData.days)) {
    let markerIdx = 0;
    for (const day of routeData.days) {
      if (day.anchors && Array.isArray(day.anchors)) {
        for (const anchor of day.anchors) {
          // 只有当 anchor 有 location 时才添加 marker
          if (anchor.location && (anchor.location.lng || anchor.location.lat)) {
            markers.push({
              name: anchor.name || `POI ${markerIdx + 1}`,
              location: [
                anchor.location.lng || 0,
                anchor.location.lat || 0,
              ] as [number, number],
              type: 'anchor',
              day_index: day.day_index || 1,
            });
            markerIdx++;
          }
        }
      }
    }
  }

  // 添加餐饮 POI markers
  const mealMarkers: Array<{ name: string; location: [number, number]; type: string; day_index: number }> = [];
  
  // 从顶层 pois 提取
  if (routeData?.pois && Array.isArray(routeData.pois)) {
    for (const poi of routeData.pois) {
      if (poi.is_meal && poi.location) {
        mealMarkers.push({
          name: poi.name,
          location: [
            poi.location.lng || 0,
            poi.location.lat || 0,
          ] as [number, number],
          type: 'meal',
          day_index: 1,
        });
      }
    }
  }
  
  // 从 days[].meal_slots 提取
  if (routeData?.days && Array.isArray(routeData.days)) {
    for (const day of routeData.days) {
      if (day.meal_slots && Array.isArray(day.meal_slots)) {
        for (const meal of day.meal_slots) {
          if (meal.poi_name && meal.location) {
            mealMarkers.push({
              name: meal.poi_name,
              location: [
                meal.location.lng || 0,
                meal.location.lat || 0,
              ] as [number, number],
              type: 'meal',
              day_index: day.day_index || 1,
            });
          }
        }
      }
    }
  }

  // 计算中心点
  const allMarkers = [...markers, ...mealMarkers];
  const center = allMarkers.length > 0
    ? [
        allMarkers.reduce((sum, m) => sum + m.location[0], 0) / allMarkers.length,
        allMarkers.reduce((sum, m) => sum + m.location[1], 0) / allMarkers.length,
      ] as [number, number]
    : null;

  return {
    polylines,
    markers: allMarkers,
    center,
  };
}
