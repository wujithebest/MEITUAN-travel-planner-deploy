/**
 * 后端AI旅行规划API接口 - SSE流式响应
 * 使用fetch + ReadableStream替代EventSource，支持POST和自定义Header
 * 支持 event: xxx 格式的 SSE 事件
 */

import type { PlanRequest, SSEEvent, CompletePlan } from '@/types/plan';
import { API_CONFIG } from '../config/api.config';

/**
 * 解析 SSE 原始文本为 SSEEvent 对象
 * 支持 event: xxx \n data: {...} 格式
 */
function parseSSEMessage(raw: string): SSEEvent | null {
  const lines = raw.split('\n');
  let eventType = 'message';
  let data = '';

  for (const line of lines) {
    if (line.startsWith('event: ')) {
      eventType = line.slice(7).trim();
    } else if (line.startsWith('data: ')) {
      data = line.slice(6);
    }
  }

  if (!data) return null;

  try {
    const parsed = JSON.parse(data);
    // 兼容后端新旧格式：新格式有 type/content，旧格式有 msg
    const resolvedType = (parsed.type && typeof parsed.type === 'string') ? parsed.type : ('message' as any);
    return {
      type: resolvedType,
      content: parsed.content !== undefined ? parsed.content : (parsed.msg !== undefined ? parsed.msg : parsed),
      progress: parsed.progress != null ? parsed.progress : undefined,
    };
  } catch (e) {
    // 纯文本数据
    console.warn('[parseSSEMessage] 解析 JSON 失败:', e, 'raw:', raw.substring(0, 100));
    return {
      type: eventType as any,
      content: data,
      progress: undefined,
    };
  }
}

const API_BASE = API_CONFIG.BASE_URL;

// 错误类型定义
export type PlanErrorType = 'connection' | 'timeout' | 'server' | 'parse' | 'unknown';

export interface PlanError {
  type: PlanErrorType;
  message: string;
  details?: string;
  suggestions?: string[];
}

export interface SSECallbacks {
  onIntent?: (content: any) => void;
  onPOISearch?: (content: any) => void;
  onWeather?: (content: any) => void;
  onRoute?: (content: any) => void;
  onRestaurant?: (content: any) => void;
  onComplete?: (plan: CompletePlan) => void;
  onError?: (error: string) => void;
  onErrorDetailed?: (error: PlanError) => void;
  onProgress?: (progress: number) => void;
}

/**
 * 创建用户友好的错误对象
 */
function createPlanError(type: PlanErrorType, message: string, originalError?: any): PlanError {
  const errorMap: Record<PlanErrorType, { details: string; suggestions: string[] }> = {
    connection: {
      details: `无法连接到后端服务 (当前配置: ${API_BASE})`,
      suggestions: [
        '请确认后端服务已启动 (python main.py)',
        '检查端口号是否正确',
        '检查网络防火墙设置',
        '尝试刷新页面重新连接',
      ],
    },
    timeout: {
      details: '请求超时，后端处理时间过长',
      suggestions: [
        'DeepSeek API响应可能较慢，请稍后重试',
        '高德地图API调用可能失败',
        '网络连接不稳定，请检查网络',
        '尝试简化您的需求描述',
      ],
    },
    server: {
      details: message,
      suggestions: [
        '后端服务出现错误，请查看后端日志',
        '可能是API密钥配置问题',
        '尝试重新发送请求',
      ],
    },
    parse: {
      details: '响应数据解析失败',
      suggestions: [
        '服务器返回了异常数据格式',
        '请稍后重试',
      ],
    },
    unknown: {
      details: message,
      suggestions: [
        '发生未知错误，请刷新页面重试',
        '如果问题持续存在，请联系技术支持',
      ],
    },
  };

  return {
    type,
    message,
    ...errorMap[type],
  };
}

/**
 * 使用fetch + ReadableStream的增强版SSE连接
 * 支持POST请求、自定义Header、超时处理和详细错误信息
 */
export async function streamPlanRoute(
  userRequest: string,
  planMode: 'exploratory' | 'planned' = 'exploratory',
  onProgress: (data: SSEEvent) => void,
  onError: (error: PlanError) => void,
  timeout: number = 30000
): Promise<CompletePlan | null> {
  const controller = new AbortController();
  const timeoutId = setTimeout(() => controller.abort(), timeout);

  try {
    // API_BASE 已经是 /api，所以这里用 /plan 而不是 /api/plan
    const response = await fetch(`${API_BASE}/plan`, {
      method: 'POST',
      headers: {
        'Content-Type': 'application/json',
        'Accept': 'text/event-stream',
      },
      body: JSON.stringify({
        user_request: userRequest,
        plan_mode: planMode,
      }),
      signal: controller.signal,
    });

    if (!response.ok) {
      const errorText = await response.text().catch(() => response.statusText);
      throw createPlanError(
        'server',
        `HTTP ${response.status}: ${response.statusText}`,
        errorText
      );
    }

    const reader = response.body?.getReader();
    if (!reader) {
      throw createPlanError('server', '无法获取响应流');
    }

    const decoder = new TextDecoder();
    let buffer = '';

    while (true) {
      const { done, value } = await reader.read();
      if (done) break;

      buffer += decoder.decode(value, { stream: true });
      const chunks = buffer.split('\n\n');
      buffer = chunks.pop() || '';

      for (const chunk of chunks) {
        const event = parseSSEMessage(chunk);
        if (!event) continue;

        console.log('[SSE] parsed:', event.type, typeof event.content === 'string' ? event.content.substring(0, 50) : event.content);

        onProgress(event);

        if (event.type === 'complete') {
          return event.content?.full_plan || null;
        }
        if (event.type === 'error') {
          throw createPlanError('server', event.content || '服务器返回错误');
        }
      }
    }
    return null;
  } catch (error: any) {
    clearTimeout(timeoutId);

    if (error.name === 'AbortError') {
      onError(createPlanError('timeout', '请求超时'));
      return null;
    }

    if (error.type) {
      // 已经是PlanError
      onError(error as PlanError);
    } else if (error.message?.includes('Failed to fetch') || error.message?.includes('NetworkError')) {
      onError(createPlanError('connection', error.message));
    } else {
      onError(createPlanError('unknown', error.message || '未知错误'));
    }
    return null;
  } finally {
    clearTimeout(timeoutId);
  }
}

/**
 * 保持向后兼容的原planRoute函数
 * 内部使用streamPlanRoute实现
 */
export async function planRoute(
  request: PlanRequest,
  callbacks: SSECallbacks,
  signal?: AbortSignal
): Promise<CompletePlan | null> {
  try {
    const response = await fetch(`${API_BASE}/plan`, {
      method: 'POST',
      headers: {
        'Content-Type': 'application/json',
        'Accept': 'text/event-stream',
      },
      body: JSON.stringify(request),
      signal,
    });

    if (!response.ok) {
      const error = createPlanError('server', `HTTP ${response.status}: ${response.statusText}`);
      callbacks.onErrorDetailed?.(error);
      callbacks.onError?.(error.message);
      return null;
    }

    const reader = response.body?.getReader();
    if (!reader) {
      const error = createPlanError('server', '无法获取响应流');
      callbacks.onErrorDetailed?.(error);
      callbacks.onError?.(error.message);
      return null;
    }

    const decoder = new TextDecoder();
    let buffer = '';

    while (true) {
      const { done, value } = await reader.read();
      if (done) break;

      buffer += decoder.decode(value, { stream: true });
      const chunks = buffer.split('\n\n');
      buffer = chunks.pop() || '';

      for (const chunk of chunks) {
        const event = parseSSEMessage(chunk);
        if (!event) continue;

        console.log('[SSE] parsed:', event.type, typeof event.content === 'string' ? event.content.substring(0, 50) : event.content);

        handleSSEEvent(event, callbacks);
        if (event.type === 'complete') {
          return event.content?.full_plan || null;
        }
      }
    }
    return null;
  } catch (error: any) {
    if (error.name === 'AbortError') {
      console.log('规划请求已取消');
      return null;
    }

    const planError = error.type
      ? error
      : createPlanError('unknown', error.message || '请求失败');
    callbacks.onErrorDetailed?.(planError);
    callbacks.onError?.(planError.message);
    return null;
  }
}

function handleSSEEvent(event: SSEEvent, callbacks: SSECallbacks): void {
  if (event.progress !== undefined) {
    callbacks.onProgress?.(event.progress);
  }
  switch (event.type) {
    case 'intent': callbacks.onIntent?.(event.content); break;
    case 'poi_search': callbacks.onPOISearch?.(event.content); break;
    case 'weather': callbacks.onWeather?.(event.content); break;
    case 'route': callbacks.onRoute?.(event.content); break;
    case 'restaurant': callbacks.onRestaurant?.(event.content); break;
    case 'complete': callbacks.onComplete?.(event.content?.full_plan); break;
    case 'error': callbacks.onError?.(event.content); break;
  }
}

export function createPlanAbortController() {
  const controller = new AbortController();
  return { controller, cancel: () => controller.abort() };
}
