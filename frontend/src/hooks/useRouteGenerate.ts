// ============================================
// 路线生成 Hook - 简化版（非SSE流式）
// 交互流程：loading → request → response → render
// ============================================

import { useCallback, useRef } from 'react';
import { useRouteStore } from '@/store/routeStore';
import { generateRoute, RouteAPIError } from '@/api/route';
import { mockGenerateRoute, shouldUseMock } from '@/api/mockRoute';
import type { LocationInput, RouteResponse, POI } from '@/api/types';

/**
 * 路线生成进度模拟步骤
 * 用于在前端显示规划进度（因为后端不是流式返回）
 */
const PLANNING_STEPS = [
  { progress: 10, message: '正在理解您的需求...', duration: 500 },
  { progress: 30, message: '正在搜索景点和餐厅...', duration: 800 },
  { progress: 50, message: '正在获取天气信息...', duration: 600 },
  { progress: 70, message: '正在规划最佳路线...', duration: 1000 },
  { progress: 90, message: '正在生成行程详情...', duration: 700 },
  { progress: 100, message: '规划完成！', duration: 300 },
];

/**
 * 路线生成 Hook
 * 
 * 使用方式：
 * const { generate, isLoading, progress, error } = useRouteGenerate();
 * await generate({ query: '周末想去上海外滩拍夜景' });
 */
export function useRouteGenerate() {
  const setLoading = useRouteStore((s) => s.setLoading);
  const setError = useRouteStore((s) => s.setError);
  const setRouteFromResponse = useRouteStore((s) => s.setRouteFromResponse);
  const setPlanningState = useRouteStore((s) => s.setPlanningState);
  const setPlanningStep = useRouteStore((s) => s.setPlanningStep);
  const setPlanningProgress = useRouteStore((s) => s.setPlanningProgress);
  const addChatMessage = useRouteStore((s) => s.addChatMessage);

  // 用于取消进度模拟
  const progressTimerRef = useRef<NodeJS.Timeout | null>(null);
  const abortControllerRef = useRef<AbortController | null>(null);

  /**
   * 模拟规划进度
   * 因为后端一次性返回完整数据，前端用setTimeout模拟步骤进度
   */
  const simulateProgress = useCallback(() => {
    let currentStep = 0;

    const runStep = () => {
      if (currentStep >= PLANNING_STEPS.length) return;

      const step = PLANNING_STEPS[currentStep];
      setPlanningProgress(step.progress);
      setPlanningStep('loading');

      // 添加进度消息到聊天
      addChatMessage({
        id: `progress-${Date.now()}`,
        role: 'assistant',
        content: step.message,
        timestamp: Date.now(),
      });

      currentStep++;
      progressTimerRef.current = setTimeout(runStep, step.duration);
    };

    runStep();
  }, [setPlanningProgress, setPlanningStep, addChatMessage]);

  /**
   * 停止进度模拟
   */
  const stopProgressSimulation = useCallback(() => {
    if (progressTimerRef.current) {
      clearTimeout(progressTimerRef.current);
      progressTimerRef.current = null;
    }
    if (abortControllerRef.current) {
      abortControllerRef.current.abort();
      abortControllerRef.current = null;
    }
  }, []);

  /**
   * 生成路线
   * 
   * @param input 用户输入的位置和偏好信息
   * @returns 生成的路线数据
   * 
   * @example
   * ```ts
   * const { generate } = useRouteGenerate();
   * const route = await generate({
   *   query: '周末想去上海外滩拍夜景，想吃本帮菜',
   *   consider_weather: true,
   * });
   * ```
   */
  const generate = useCallback(
    async (input: LocationInput): Promise<RouteResponse | null> => {
      console.log('[useRouteGenerate] 开始生成路线', input);

      // 重置状态
      stopProgressSimulation();
      setLoading(true);
      setError(null);
      setPlanningState(true);
      setPlanningStep('loading');
      setPlanningProgress(0);

      // 添加用户消息到聊天
      addChatMessage({
        id: `user-${Date.now()}`,
        role: 'user',
        content: input.text,
        timestamp: Date.now(),
      });

      // 开始模拟进度
      simulateProgress();

      try {
        let response: RouteResponse;

        // 判断是否使用Mock数据
        if (shouldUseMock()) {
          console.log('[useRouteGenerate] 使用Mock数据');
          response = await mockGenerateRoute(input);
        } else {
          console.log('[useRouteGenerate] 调用后端API');
          response = await generateRoute(input);
        }

        // 停止进度模拟
        stopProgressSimulation();

        // 检查响应
        if (!response.success) {
          throw new RouteAPIError(response.message || '路线生成失败', response);
        }

        console.log('[useRouteGenerate] 路线生成成功', {
          daily_routes: response.daily_routes.length,
          total_pois: response.summary.total_pois,
        });

        // 更新Store
        setRouteFromResponse(response);

        // 添加AI回复到聊天
        addChatMessage({
          id: `ai-${Date.now()}`,
          role: 'assistant',
          content: generateAIMessage(response),
          timestamp: Date.now(),
        });

        return response;
      } catch (err: any) {
        // 停止进度模拟
        stopProgressSimulation();

        // 分类处理错误
        let errorMessage = '路线生成失败';

        if (err instanceof RouteAPIError) {
          // 后端业务错误
          errorMessage = err.message;
          console.error('[useRouteGenerate] 后端业务错误:', errorMessage);

          // 特殊错误处理
          if (errorMessage.includes('OUT_OF_SHANGHAI')) {
            errorMessage = '抱歉，目前仅支持上海市内的路线规划';
          } else if (errorMessage.includes('INSUFFICIENT_POI')) {
            errorMessage = '抱歉，未找到足够的景点信息，请尝试其他关键词';
          } else if (errorMessage.includes('INVALID_COORDINATES')) {
            errorMessage = '坐标信息有误，请检查输入';
          }
        } else if (err.name === 'AbortError') {
          errorMessage = '请求已取消';
        } else {
          // 网络或其他错误
          errorMessage = err.message || '网络连接失败，请稍后重试';
          console.error('[useRouteGenerate] 错误:', err);
        }

        // 更新错误状态
        setError(errorMessage);
        setPlanningState(false);
        setPlanningStep('error');

        // 添加错误消息到聊天
        addChatMessage({
          id: `error-${Date.now()}`,
          role: 'assistant',
          content: `抱歉，${errorMessage}。请稍后再试。`,
          timestamp: Date.now(),
        });

        return null;
      } finally {
        setLoading(false);
      }
    },
    [
      setLoading,
      setError,
      setRouteFromResponse,
      setPlanningState,
      setPlanningStep,
      setPlanningProgress,
      addChatMessage,
      simulateProgress,
      stopProgressSimulation,
    ]
  );

  /**
   * 取消路线生成
   */
  const cancel = useCallback(() => {
    console.log('[useRouteGenerate] 取消路线生成');
    stopProgressSimulation();
    setLoading(false);
    setPlanningState(false);
    setPlanningStep('idle');
    setPlanningProgress(0);
  }, [stopProgressSimulation, setLoading, setPlanningState, setPlanningStep, setPlanningProgress]);

  /**
   * 确认POI消歧
   */
  const confirmDisambiguation = useCallback(
    async (poi: POI) => {
      console.log('[useRouteGenerate] 确认POI消歧', poi.name);
      // TODO: 实现POI消歧确认
    },
    []
  );

  return {
    generate,
    cancel,
    confirmDisambiguation,
  };
}

/**
 * 生成AI回复消息
 */
function generateAIMessage(response: RouteResponse): string {
  const { summary, intent, daily_routes } = response;

  let message = `已为您规划好${summary.days || summary.total_days || daily_routes.length}天的行程！\n\n`;

  // 意图识别结果
  if (intent) {
    message += `📍 目标区域：${intent.area}\n`;
    if (intent.keywords.length > 0) {
      message += `🏷️ 关键词：${intent.keywords.join('、')}\n`;
    }
    message += '\n';
  }

  // 行程概览
  message += `📊 行程概览：\n`;
  message += `- 共 ${summary.total_pois} 个景点\n`;
  message += `- 总距离 ${(summary.total_distance / 1000).toFixed(1)} 公里\n`;
  message += `- 预计游玩 ${Math.floor(summary.total_duration / 60)} 小时\n\n`;

  // 每日行程简介
  message += `🗓️ 每日行程：\n`;
  daily_routes.forEach((route, index) => {
    const dayPois = route.pois.slice(0, 3).map((p) => p.name).join(' → ');
    const moreText = route.pois.length > 3 ? ` 等${route.pois.length}个景点` : '';
    message += `第${index + 1}天：${dayPois}${moreText}\n`;
  });

  message += '\n点击地图可查看详细路线！';

  return message;
}
