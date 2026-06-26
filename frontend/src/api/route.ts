// ============================================
// 路线生成 API - 普通JSON请求（非SSE流式）
// ============================================

import client from './client';
import type { LocationInput, RouteResponse, ApiResponse } from './types';

// API路径配置：支持通过环境变量配置，默认使用 /route/generate
// 注意：client 的 baseURL 已经是 /api（来自 VITE_API_BASE_URL），所以这里不需要再加 /api 前缀
const API_PATH = import.meta.env.VITE_API_ROUTE_PATH || '/route/generate';

function normalizeRouteResponse(payload: any): RouteResponse {
  if (!payload?.success) {
    throw new RouteAPIError(payload?.message || '路线生成失败', payload);
  }

  const route = payload.data || payload;
  if (route.summary && route.map_config) {
    return route as RouteResponse;
  }

  const dailyRoutes = route.daily_routes || [];
  const mainPOIs = route.main_pois || [];
  const enroutePOIs = route.enroute_pois || [];
  const totalDistance = route.total_distance || 0;
  const totalDuration = route.total_duration || 0;

  return {
    ...route,
    success: true,
    message: payload.message || route.message || '路线生成成功',
    daily_routes: dailyRoutes,
    main_pois: mainPOIs,
    enroute_pois: enroutePOIs,
    summary: {
      total_days: dailyRoutes.length,
      total_distance: totalDistance,
      total_duration: totalDuration,
      total_pois: mainPOIs.length + enroutePOIs.length,
      main_pois: mainPOIs.length,
      enroute_pois: enroutePOIs.length,
      main_pois_count: mainPOIs.length,
      enroute_pois_count: enroutePOIs.length,
      transportation: route.transport_mode,
      days: dailyRoutes.length,
    },
    map_config: {
      center: mainPOIs[0]?.location || '121.4737,31.2304',
      zoom: 13,
      markers: mainPOIs.map((poi: any, index: number) => ({
        id: poi.id || `poi-${index}`,
        name: poi.name,
        location: poi.location,
        type: 'main',
        day: 1,
      })),
      daily_polylines: dailyRoutes.map((dailyRoute: any) => ({
        day: dailyRoute.day,
        polyline: dailyRoute.polyline || '',
        color: '#1677ff',
      })),
    },
    weather: route.weather_forecast || [],
  };
}

/**
 * 生成旅行路线
 * 后端接口：POST /api/route/generate
 * 一次性返回完整路线数据，非流式
 * 
 * @param input 用户输入的位置和偏好信息
 * @returns 完整的路线规划结果
 * @throws 网络错误、后端业务错误、超时错误
 */
export async function generateRoute(input: LocationInput): Promise<RouteResponse> {
  console.log('[RouteAPI] 开始生成路线', {
    text: input.text,
    origin: input.origin,
    transport_mode: input.transport_mode || 'driving',
    start_date: input.start_date,
    consider_weather: input.consider_weather ?? true,
    api_path: API_PATH,
  });

  try {
    // 发送POST请求，后端一次性返回完整数据
    const { data: payload } = await client.post<ApiResponse<RouteResponse> | RouteResponse>(API_PATH, input);
    const data = normalizeRouteResponse(payload);

    console.log('[RouteAPI] 路线生成成功', {
      success: data.success,
      message: data.message,
      daily_routes_count: data.daily_routes?.length || 0,
      total_pois: data.summary?.total_pois || 0,
    });

    return data;
  } catch (error: any) {
    // 分类处理错误
    if (error instanceof RouteAPIError) {
      throw error;
    }

    // 404错误处理：尝试fallback路径
    if (error.response?.status === 404 && API_PATH === '/route/generate') {
      const fallbackPath = '/api/route/generate';
      console.warn(`[RouteAPI] 404错误，尝试fallback路径: ${fallbackPath}`);
      
      try {
        const { data: payload } = await client.post<ApiResponse<RouteResponse> | RouteResponse>(fallbackPath, input);
        const data = normalizeRouteResponse(payload);
        
        console.log('[RouteAPI] Fallback路径请求成功', {
          success: data.success,
          message: data.message,
        });

        return data;
      } catch (fallbackError: any) {
        console.error('[RouteAPI] Fallback路径也失败:', fallbackError.message);
        throw new RouteAPIError('接口路径错误，请检查后端路由配置', null);
      }
    }

    if (error.code === 'ECONNABORTED') {
      console.error('[RouteAPI] 请求超时');
      throw new RouteAPIError('请求超时，请稍后重试', null);
    }

    if (!error.response) {
      console.error('[RouteAPI] 网络错误:', error.message);
      throw new RouteAPIError('网络连接失败，请检查后端服务是否运行', null);
    }

    // HTTP错误
    const status = error.response?.status;
    const backendMessage = error.response?.data?.message || error.response?.data?.detail;
    console.error('[RouteAPI] HTTP错误:', { status, message: backendMessage });

    // 404错误的特殊提示
    if (status === 404) {
      throw new RouteAPIError(
        `接口路径错误 (404)：${backendMessage || '请求的资源不存在'}。请检查后端路由配置，可能存在重复前缀问题。`,
        error.response?.data
      );
    }

    throw new RouteAPIError(backendMessage || `请求失败 (${status})`, error.response?.data);
  }
}

/**
 * 重新规划某一天的路线
 * 后端接口：POST /api/route/reroute
 */
export async function rerouteDay(
  routeId: string,
  day: number,
  pois: string[]
): Promise<ApiResponse<RouteResponse>> {
  console.log('[RouteAPI] 重新规划路线', { routeId, day, pois });

  try {
    const { data } = await client.post<ApiResponse<RouteResponse>>('/route/reroute', {
      route_id: routeId,
      day,
      poi_ids: pois,
    });

    console.log('[RouteAPI] 重新规划成功', { success: data.success });
    return data;
  } catch (error: any) {
    console.error('[RouteAPI] 重新规划失败:', error.message);
    throw new RouteAPIError(error.message || '重新规划失败', null);
  }
}

/**
 * 确认POI消歧（当有多个相似地点时）
 * 后端接口：POST /api/route/confirm
 */
export async function confirmDisambiguation(
  routeId: string,
  poiId: string
): Promise<ApiResponse<RouteResponse>> {
  console.log('[RouteAPI] 确认POI消歧', { routeId, poiId });

  try {
    const { data } = await client.post<ApiResponse<RouteResponse>>('/route/confirm', {
      route_id: routeId,
      poi_id: poiId,
    });

    console.log('[RouteAPI] 消歧确认成功', { success: data.success });
    return data;
  } catch (error: any) {
    console.error('[RouteAPI] 消歧确认失败:', error.message);
    throw new RouteAPIError(error.message || '确认失败', null);
  }
}

/**
 * 路线API错误类
 */
export interface ReplanOperation {
  action: 'add' | 'remove' | 'replace';
  poi?: any;
  poi_id?: string;
}

export interface ReplanRequest {
  route_id?: string;
  main_pois: any[];
  enroute_pois: any[];
  operations: ReplanOperation[];
  transport_mode?: string;
}

/**
 * 重规划路线（POI 增删替换后）
 * 后端接口：POST /api/route/replan
 */
export async function replanRoute(req: ReplanRequest): Promise<RouteResponse> {
  console.log('[RouteAPI] 重规划路线', { operations: req.operations.length });

  try {
    const { data: payload } = await client.post<ApiResponse<RouteResponse>>('/route/replan', req);
    const data = normalizeRouteResponse(payload);
    console.log('[RouteAPI] 重规划成功', { daily_routes_count: data.daily_routes?.length || 0 });
    return data;
  } catch (error: any) {
    console.error('[RouteAPI] 重规划失败:', error.message);
    throw new RouteAPIError(error.message || '重规划失败', null);
  }
}

// ==================== Pipeline Route Replan ====================

export interface PipelineReplanRequest {
  points: any[];
  segments: any[];
  operations: { action: 'remove' | 'replace' | 'add'; poi_id: string; poi?: any; gaode_poi_id?: string; poi_name?: string; poi_location?: string; after_poi_id?: string; after_poi_name?: string; after_poi_location?: string }[];
  transport_mode?: string;
  route_id?: string | null;
}

export interface PipelineReplanResponse {
  route: {
    points: any[];
    segments: any[];
  };
  route_id: string;
}

/**
 * 管线格式路线重新计算（删除/替换 POI 后）
 * 后端接口：POST /api/route/replan-pipeline
 */
export async function replanPipelineRoute(
  req: PipelineReplanRequest
): Promise<PipelineReplanResponse> {
  console.log('[RouteAPI] 管线重规划', { operations: req.operations.length });
  try {
    const { data: payload } = await client.post<{
      success: boolean;
      data?: PipelineReplanResponse;
      message?: string;
    }>('/route/replan-pipeline', req);
    if (payload?.data) {
      console.log('[RouteAPI] 管线重规划成功');
      return payload.data;
    }
    throw new Error(payload?.message || 'Pipeline replan failed');
  } catch (error: any) {
    console.error('[RouteAPI] 管线重规划失败:', error.message);
    throw new RouteAPIError(error.message || '管线重规划失败', null);
  }
}

export class RouteAPIError extends Error {
  constructor(
    message: string,
    public data: any
  ) {
    super(message);
    this.name = 'RouteAPIError';
  }
}
