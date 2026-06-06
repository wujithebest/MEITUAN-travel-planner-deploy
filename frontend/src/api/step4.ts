/**
 * Step4 输出 API
 * 获取自然语言行程方案和地图渲染数据
 */

import client from './client';
import type { Step4Output, ApiResponse } from './types';

/**
 * 从聊天室生成行程方案
 * 后端接口：POST /api/chat/rooms/{room_id}/generate-itinerary
 * 
 * @param roomId 聊天室ID
 * @param userRequest 用户请求文本
 * @param mapFilePath 地图文件路径（可选）
 * @returns step4 输出数据
 */
export async function generateItinerary(
  roomId: string,
  userRequest: string,
  mapFilePath: string = ''
): Promise<Step4Output> {
  console.log('[Step4API] 生成行程方案', { roomId, userRequest });

  try {
    // client baseURL 已经是 /api，所以路径不加 /api 前缀
    const { data } = await client.post<ApiResponse<{ itinerary: Step4Output }>>(
      `/chat/rooms/${roomId}/generate-itinerary`,
      {
        user_request: userRequest,
        map_file_path: mapFilePath,
      }
    );

    console.log('[Step4API] 行程方案生成成功', {
      success: data.success,
      days: data.data?.itinerary?.days?.length || 0,
      anchors: data.data?.itinerary?.anchors?.length || 0,
    });

    if (!data.success || !data.data?.itinerary) {
      throw new Step4APIError(data.message || '行程方案生成失败', data);
    }

    return data.data.itinerary;
  } catch (error: any) {
    if (error instanceof Step4APIError) {
      throw error;
    }

    console.error('[Step4API] 生成行程方案失败:', error);
    throw new Step4APIError(
      error.message || '行程方案生成失败',
      error.response?.data
    );
  }
}

/**
 * 从完整规划结果获取 step4 输出
 * 后端接口：POST /api/plan/step4
 * 
 * @param planData 完整规划数据（包含 parsed_intent, complete_plan, micro_pois, route_segments）
 * @returns step4 输出数据
 */
export async function getStep4Output(planData: {
  parsed_intent: any;
  complete_plan: any;
  micro_pois: any[];
  route_segments: any[];
  map_file_path?: string;
  anchor_hints?: Record<string, string>;
  waypoint_annotations?: Record<string, any>;
}): Promise<Step4Output> {
  console.log('[Step4API] 获取 step4 输出', {
    days: planData.complete_plan?.day_plans?.length || 0,
    pois: planData.micro_pois?.length || 0,
    segments: planData.route_segments?.length || 0,
  });

  try {
    // client baseURL 已经是 /api，所以路径不加 /api 前缀
    const { data } = await client.post<ApiResponse<Step4Output>>(
      '/plan/step4',
      planData
    );

    console.log('[Step4API] step4 输出获取成功', {
      success: data.success,
      days: data.data?.days?.length || 0,
    });

    if (!data.success || !data.data) {
      throw new Step4APIError(data.message || '获取 step4 输出失败', data);
    }

    return data.data;
  } catch (error: any) {
    if (error instanceof Step4APIError) {
      throw error;
    }

    console.error('[Step4API] 获取 step4 输出失败:', error);
    throw new Step4APIError(
      error.message || '获取 step4 输出失败',
      error.response?.data
    );
  }
}

/**
 * 解析 step4 文本输出为结构化数据
 * 用于处理已有的 step4_output.py 输出
 * 
 * @param textOutput step4_output.py 的文本输出
 * @returns 结构化的 step4 输出数据
 */
export function parseStep4TextOutput(textOutput: string): Step4Output {
  const lines = textOutput.split('\n');
  
  let summary = '';
  const days: Step4Output['days'] = [];
  const anchors: Step4Output['anchors'] = [];
  let totalDistance = '';
  let mapUrl = '';
  
  let currentDay: Step4Output['days'][0] | null = null;
  
  for (const line of lines) {
    // 解析摘要行
    if (line.startsWith('为您规划了')) {
      summary = line;
      continue;
    }
    
    // 解析 Day 标题
    const dayMatch = line.match(/【Day(\d+)】/);
    if (dayMatch) {
      if (currentDay) {
        days.push(currentDay);
      }
      currentDay = {
        day_index: parseInt(dayMatch[1]),
        title: `Day${dayMatch[1]}`,
        detail: line,
        anchors: [],
      };
      continue;
    }
    
    // 解析推荐理由行
    const reasonMatch = line.match(/· (.+?)：(.+)/);
    if (reasonMatch) {
      anchors.push({
        name: reasonMatch[1],
        reason: reasonMatch[2],
      });
      continue;
    }
    
    // 解析地图URL
    if (line.includes('[ROUTE_PLANNER]:') && line.includes('地图')) {
      const urlMatch = line.match(/点击查看：(.+)/);
      if (urlMatch) {
        mapUrl = urlMatch[1].trim();
      }
      continue;
    }
    
    // 解析总距离
    const distanceMatch = line.match(/总距离[：:]?\s*([\d.]+)\s*km/i);
    if (distanceMatch) {
      totalDistance = `${distanceMatch[1]}km`;
      continue;
    }
    
    // 其他内容追加到当前天的详情
    if (currentDay) {
      currentDay.detail += '\n' + line;
    }
  }
  
  // 添加最后一天
  if (currentDay) {
    days.push(currentDay);
  }
  
  return {
    summary,
    days,
    anchors,
    total_distance: totalDistance,
    map_url: mapUrl,
  };
}

/**
 * Step4 API 错误类
 */
export class Step4APIError extends Error {
  constructor(
    message: string,
    public data: any
  ) {
    super(message);
    this.name = 'Step4APIError';
  }
}
