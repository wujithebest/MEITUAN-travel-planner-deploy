/**
 * 路线规划 Hook
 * 管理路线规划状态，与 Zustand store 集成
 * 
 * 对应后端: step3_micro.py 中的路线规划流程
 * - planDayRoute 对应单日路线规划
 * - planFullRoute 对应完整行程规划
 */

import { useState, useCallback, useRef } from 'react';
import { RoutePolylineService } from '@/services/routePolyline';
import type {
  RouteSegment,
  DayRoute,
  DayPlan,
  PlanData,
  PlanningProgress,
} from '@/types/route';

/** Hook 配置选项 */
interface UseRoutePlanningOptions {
  /** 地图实例 */
  map?: AMap.Map | null;
  /** 进度回调 */
  onProgress?: (progress: PlanningProgress) => void;
  /** 完成回调 */
  onComplete?: (result: { dayRoutes: DayRoute[]; totalDistance: number; totalDuration: number }) => void;
  /** 错误回调 */
  onError?: (error: Error) => void;
}

/** Hook 返回值 */
interface UseRoutePlanningReturn {
  /** 规划进度状态 */
  progress: PlanningProgress;
  /** 规划后的单日路线列表 */
  dayRoutes: DayRoute[];
  /** 规划单日路线 */
  planDayRoute: (dayPlan: DayPlan) => Promise<DayRoute | null>;
  /** 规划完整行程 */
  planFullRoute: (planData: PlanData) => Promise<DayRoute[] | null>;
  /** 渲染单日路线 */
  renderDayRoute: (dayRoute: DayRoute) => void;
  /** 清除路线 */
  clearRoute: () => void;
  /** 取消规划 */
  cancelPlanning: () => void;
}

/**
 * 路线规划 Hook
 * 
 * 功能：
 * 1. 管理规划状态（isPlanning, progress, dayRoutes）
 * 2. planDayRoute - 规划单日路线，实时更新进度
 * 3. planFullRoute - 规划完整行程（遍历所有天数）
 * 4. renderDayRoute - 渲染单日路线到地图
 * 5. 错误降级：API 失败时自动降级为直线连接
 */
export function useRoutePlanning(options: UseRoutePlanningOptions = {}): UseRoutePlanningReturn {
  const { map, onProgress, onComplete, onError } = options;

  // 本地状态
  const [progress, setProgress] = useState<PlanningProgress>({
    isPlanning: false,
    progress: 0,
    message: '',
    messages: [],
  });
  const [dayRoutes, setDayRoutes] = useState<DayRoute[]>([]);

  // 服务实例（保持引用稳定）
  const serviceRef = useRef<RoutePolylineService | null>(null);
  if (!serviceRef.current) {
    serviceRef.current = new RoutePolylineService(map || undefined);
  }

  // 更新地图实例
  if (map) {
    serviceRef.current.setMap(map);
  }

  // 取消标志
  const cancelRef = useRef(false);

  /**
   * 更新进度状态
   */
  const updateProgress = useCallback((update: Partial<PlanningProgress>) => {
    setProgress((prev) => {
      const newProgress = { ...prev, ...update };
      onProgress?.(newProgress);
      return newProgress;
    });
  }, [onProgress]);

  /**
   * 添加进度消息
   */
  const addMessage = useCallback((message: string) => {
    setProgress((prev) => ({
      ...prev,
      messages: [...prev.messages, message],
      message,
    }));
  }, []);

  /**
   * 规划单日路线
   * 
   * 流程（对应后端 step3_micro.py 单日规划逻辑）：
   * 1. 按顺序遍历 dayPlan.pois，相邻两点调用 planRoute
   * 2. 判断 sameSubAnchor: poi[i].sub_anchor_id === poi[i+1].sub_anchor_id
   * 3. 收集所有 RouteSegment
   * 4. 调用 optimizeForRender 优化
   * 5. 返回 DayRoute
   * 6. 实时更新 progress
   */
  const planDayRoute = useCallback(async (
    dayPlan: DayPlan
  ): Promise<DayRoute | null> => {
    if (!serviceRef.current) return null;

    cancelRef.current = false;

    updateProgress({
      isPlanning: true,
      progress: 0,
      message: '开始规划路线...',
      messages: [],
    });

    try {
      const { pois } = dayPlan;
      if (pois.length < 2) {
        throw new Error('至少需要2个POI才能规划路线');
      }

      addMessage(`正在规划第 ${dayPlan.day} 天的路线，共 ${pois.length} 个地点`);
      updateProgress({ progress: 10 });

      const segments: RouteSegment[] = [];
      const totalPairs = pois.length - 1;

      // 逐段规划路线
      for (let i = 0; i < pois.length - 1; i++) {
        if (cancelRef.current) {
          addMessage('规划已取消');
          return null;
        }

        const origin = pois[i];
        const destination = pois[i + 1];

        // 判断是否同 sub-anchor
        const sameSubAnchor =
          !!origin.subAnchorId &&
          !!destination.subAnchorId &&
          origin.subAnchorId === destination.subAnchorId;

        addMessage(`正在规划: ${origin.name} → ${destination.name}`);
        updateProgress({
          progress: 10 + Math.round((i / totalPairs) * 70),
        });

        try {
          const segment = await serviceRef.current.planRoute(
            origin,
            destination,
            { sameSubAnchor }
          );

          if (segment) {
            segments.push(segment);
            const distKm = (segment.distance / 1000).toFixed(1);
            const durMin = Math.round(segment.duration / 60);
            addMessage(`✓ ${segment.transport} ${durMin}分钟 ${distKm}km`);
          }
        } catch (err) {
          console.error('路线规划失败:', origin.name, '->', destination.name, err);
          addMessage(`✗ ${origin.name} → ${destination.name} 规划失败，使用直线连接`);

          // 降级为直线
          const stubSegment: RouteSegment = {
            polyline: [[origin.lat, origin.lng], [destination.lat, destination.lng]],
            transport: '步行',
            distance: 0,
            duration: 0,
            fromName: origin.name,
            toName: destination.name,
          };
          segments.push(stubSegment);
        }
      }

      if (cancelRef.current) return null;

      addMessage('正在优化路线...');
      updateProgress({ progress: 85 });

      // 渲染前优化（对应后端 _render_single_day_map）
      const optimizedSegments = serviceRef.current.optimizeForRender(segments);

      addMessage('正在计算边界...');
      updateProgress({ progress: 95 });

      // 计算总距离和总时长
      const totalDistance = optimizedSegments.reduce((sum, s) => sum + s.distance, 0);
      const totalDuration = optimizedSegments.reduce((sum, s) => sum + s.duration, 0);

      const dayRoute: DayRoute = {
        day: dayPlan.day,
        segments: optimizedSegments,
        totalDistance,
        totalDuration,
      };

      addMessage('路线规划完成！');
      updateProgress({
        isPlanning: false,
        progress: 100,
        message: '路线规划完成',
      });

      return dayRoute;
    } catch (err) {
      const error = err instanceof Error ? err : new Error('路线规划失败');
      console.error('路线规划错误:', error);

      addMessage(`规划失败: ${error.message}`);
      updateProgress({
        isPlanning: false,
        progress: 0,
        message: `规划失败: ${error.message}`,
      });

      onError?.(error);
      return null;
    }
  }, [updateProgress, addMessage, onError]);

  /**
   * 规划完整行程
   * 
   * 遍历所有天数，依次调用 planDayRoute
   * 对应后端完整行程规划流程
   */
  const planFullRoute = useCallback(async (
    planData: PlanData
  ): Promise<DayRoute[] | null> => {
    if (!serviceRef.current) return null;

    cancelRef.current = false;

    updateProgress({
      isPlanning: true,
      progress: 0,
      message: `开始规划 ${planData.days.length} 天的行程...`,
      messages: [],
    });

    try {
      const allDayRoutes: DayRoute[] = [];
      let totalDistance = 0;
      let totalDuration = 0;

      for (let i = 0; i < planData.days.length; i++) {
        if (cancelRef.current) {
          addMessage('规划已取消');
          return null;
        }

        const dayPlan = planData.days[i];
        addMessage(`\n=== 第 ${dayPlan.day} 天 ===`);
        updateProgress({
          progress: Math.round((i / planData.days.length) * 100),
        });

        const dayRoute = await planDayRoute(dayPlan);
        if (dayRoute) {
          allDayRoutes.push(dayRoute);
          totalDistance += dayRoute.totalDistance;
          totalDuration += dayRoute.totalDuration;
        }
      }

      if (cancelRef.current) return null;

      // 更新本地状态
      setDayRoutes(allDayRoutes);

      addMessage('\n=== 行程规划完成 ===');
      addMessage(`总距离: ${(totalDistance / 1000).toFixed(1)}km`);
      addMessage(`总时长: ${Math.round(totalDuration / 3600)}小时`);

      updateProgress({
        isPlanning: false,
        progress: 100,
        message: '行程规划完成',
      });

      onComplete?.({
        dayRoutes: allDayRoutes,
        totalDistance,
        totalDuration,
      });

      return allDayRoutes;
    } catch (err) {
      const error = err instanceof Error ? err : new Error('行程规划失败');
      console.error('行程规划错误:', error);

      addMessage(`规划失败: ${error.message}`);
      updateProgress({
        isPlanning: false,
        progress: 0,
        message: `规划失败: ${error.message}`,
      });

      onError?.(error);
      return null;
    }
  }, [planDayRoute, updateProgress, addMessage, onComplete, onError]);

  /**
   * 渲染单日路线到地图
   */
  const renderDayRoute = useCallback((dayRoute: DayRoute): void => {
    if (!serviceRef.current) return;
    serviceRef.current.renderDayRoute(dayRoute);
  }, []);

  /**
   * 清除地图上的路线覆盖物
   */
  const clearRoute = useCallback(() => {
    if (!serviceRef.current) return;
    serviceRef.current.clearOverlays();
  }, []);

  /**
   * 取消当前规划
   */
  const cancelPlanning = useCallback(() => {
    cancelRef.current = true;
    updateProgress({
      isPlanning: false,
      message: '规划已取消',
    });
  }, [updateProgress]);

  return {
    progress,
    dayRoutes,
    planDayRoute,
    planFullRoute,
    renderDayRoute,
    clearRoute,
    cancelPlanning,
  };
}
