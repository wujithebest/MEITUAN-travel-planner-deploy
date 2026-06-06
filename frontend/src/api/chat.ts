/**
 * Chat API - 聊天交互接口
 * 处理用户输入并返回 AI 回复 + 路线数据
 */

import client from './client';
import type { ApiResponse, Step4Output } from './types';

/**
 * 聊天请求
 */
export interface ChatRequest {
  /** 用户输入文本 */
  text: string;
  /** 房间ID（可选，用于群聊场景） */
  room_id?: string;
  /** 是否考虑天气 */
  consider_weather?: boolean;
}

/**
 * 聊天响应
 */
export interface ChatResponse {
  /** AI 回复文本 */
  reply: string;
  /** 路线数据（用于地图渲染） */
  route: Step4Output | null;
  /** 消息ID */
  message_id?: string;
}

/**
 * 发送聊天消息
 * 后端接口：POST /api/chat/
 * 
 * 注意：路径必须带末尾斜杠，与后端 @router.post("/") 匹配
 * 避免 FastAPI 307 重定向导致 Authorization header 丢失
 * 
 * @param request 聊天请求
 * @returns 聊天响应（包含回复文本和路线数据）
 */
export async function sendChatMessage(request: ChatRequest): Promise<ChatResponse> {
  console.log('[ChatAPI] 发送聊天消息', { text: request.text });

  try {
    // client baseURL 已经是 /api，所以这里用 /chat/
    // 注意：必须带末尾斜杠，与后端路由 @router.post("/") 匹配
    // 否则 FastAPI 会返回 307 重定向，浏览器重定向时会丢失 Authorization header
    const { data } = await client.post<ApiResponse<ChatResponse>>(
      '/chat/',
      request
    );

    console.log('[ChatAPI] 聊天响应成功', {
      success: data.success,
      replyLength: data.data?.reply?.length || 0,
      hasRoute: !!data.data?.route,
    });

    if (!data.success || !data.data) {
      throw new ChatAPIError(data.message || '聊天请求失败', data);
    }

    return data.data;
  } catch (error: any) {
    if (error instanceof ChatAPIError) {
      throw error;
    }

    console.error('[ChatAPI] 聊天请求失败:', error);
    throw new ChatAPIError(
      error.message || '聊天请求失败',
      error.response?.data
    );
  }
}

/**
 * 解析 AI 回复中的结构化数据
 * 从回复文本中提取行程概览、Day X 等信息
 * 
 * @param reply AI 回复文本
 * @returns 解析后的结构化数据
 */
export function parseReplyStructure(reply: string): {
  summary: string | null;
  days: Array<{ day: number; content: string }>;
  highlights: string[];
} {
  const lines = reply.split('\n');
  const result = {
    summary: null as string | null,
    days: [] as Array<{ day: number; content: string }>,
    highlights: [] as string[],
  };

  let currentDay: { day: number; content: string } | null = null;

  for (const line of lines) {
    // 检测行程概览
    if (line.includes('行程概览') || line.includes('为您规划了')) {
      result.summary = line;
      result.highlights.push('行程概览');
      continue;
    }

    // 检测 Day X
    const dayMatch = line.match(/Day\s*(\d+)|第(\d+)天|【Day(\d+)】/);
    if (dayMatch) {
      const dayNum = parseInt(dayMatch[1] || dayMatch[2] || dayMatch[3]);
      if (currentDay) {
        result.days.push(currentDay);
      }
      currentDay = { day: dayNum, content: line };
      result.highlights.push(`Day ${dayNum}`);
      continue;
    }

    // 追加到当前天
    if (currentDay) {
      currentDay.content += '\n' + line;
    }
  }

  // 添加最后一天
  if (currentDay) {
    result.days.push(currentDay);
  }

  return result;
}

/**
 * 从回复文本中提取路线数据
 * 用于地图渲染
 * 
 * @param reply AI 回复文本
 * @param routeData 后端返回的路线数据
 * @returns 地图渲染所需的数据，如果输入无效则返回 null
 */
export function extractRouteFromReply(
  reply: string,
  routeData: Step4Output | null | undefined
): {
  polylines: Array<{ day_index: number; polyline: string; color: string }>;
  markers: Array<{ name: string; location: string; type: string; day_index: number }>;
  center: [number, number] | null;
} | null {
  // 防御：routeData 为 null/undefined
  if (!routeData) {
    console.warn('[extractRouteFromReply] routeData is null/undefined');
    return null;
  }

  // 如果后端返回了完整的路线数据，直接使用
  if (routeData.route_polylines && Array.isArray(routeData.route_polylines) && routeData.route_polylines.length > 0) {
    const polylines = routeData.route_polylines.map(p => ({
      day_index: p.day_index,
      polyline: p.polyline,
      color: p.color || '#3366FF',
    }));

    const markers = Array.isArray(routeData.poi_markers) ? routeData.poi_markers : [];

    let center: [number, number] | null = null;
    if (routeData.poi_markers?.[0]?.location) {
      try {
        const coords = routeData.poi_markers[0].location.split(',').map(Number);
        if (coords.length === 2 && !isNaN(coords[0]) && !isNaN(coords[1])) {
          center = coords as [number, number];
        }
      } catch (e) {
        console.warn('[extractRouteFromReply] 解析中心点失败:', e);
      }
    }

    return { polylines, markers, center };
  }

  // 否则返回空结构
  return {
    polylines: [],
    markers: [],
    center: null,
  };
}

/**
 * Chat API 错误类
 */
export class ChatAPIError extends Error {
  constructor(
    message: string,
    public data: any
  ) {
    super(message);
    this.name = 'ChatAPIError';
  }
}
