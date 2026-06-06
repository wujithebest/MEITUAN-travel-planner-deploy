/**
 * 核心Hook：聊天转路线
 */

import { useCallback, useRef } from 'react';
import { useRouteStore } from '@/store/routeStore';
import { planRoute, createPlanAbortController } from '@/api/plan';
import { prepareRouteRenderData } from '@/utils/planParser';
import type { CompletePlan, PlanRequest } from '@/types/plan';

interface UseChatToRouteOptions {
  onProgress?: (step: string, progress: number) => void;
  onComplete?: (plan: CompletePlan) => void;
  onError?: (error: string) => void;
}

export function useChatToRoute(options: UseChatToRouteOptions = {}) {
  const abortControllerRef = useRef<ReturnType<typeof createPlanAbortController> | null>(null);
  const mapRef = useRef<any>(null);

  const {
    isPlanning,
    planningStep,
    planningProgress,
    currentPlan,
    setPlanningState,
    setPlanningStep,
    setPlanningProgress,
    setError,
    setCurrentPlan,
    addChatMessage,
  } = useRouteStore();

  const updateStep = useCallback((type: string) => {
    const stepMap: Record<string, { step: string; progress: number }> = {
      intent: { step: '解析意图', progress: 20 },
      poi_search: { step: '搜索地点', progress: 40 },
      weather: { step: '查询天气', progress: 60 },
      route: { step: '规划路线', progress: 80 },
      restaurant: { step: '推荐餐饮', progress: 90 },
      complete: { step: '完成', progress: 100 },
    };
    const { step, progress } = stepMap[type] || { step: '处理中', progress: 0 };
    setPlanningStep(step);
    setPlanningProgress(progress);
    options.onProgress?.(step, progress);
  }, [setPlanningStep, setPlanningProgress, options]);

  const renderPlanOnMap = useCallback((plan: CompletePlan) => {
    const map = mapRef.current;
    if (!map) return;

    const renderData = prepareRouteRenderData(plan);

    for (const markerData of renderData.markers) {
      const { poi, index, isStart, isEnd, marker_type } = markerData;
      let bgColor = '#1677ff';
      if (isStart) bgColor = '#52c41a';
      else if (isEnd) bgColor = '#ff4d4f';
      else if (marker_type === 'restaurant') bgColor = '#fa8c16';

      const marker = new (window as any).AMap.Marker({
        position: [poi.location.lng, poi.location.lat],
        content: `<div style="background:${bgColor};color:white;border-radius:50%;width:30px;height:30px;display:flex;align-items:center;justify-content:center;font-weight:bold;">${isStart ? '🚩' : isEnd ? '🏁' : index + 1}</div>`,
        offset: new (window as any).AMap.Pixel(-15, -30),
        title: poi.name,
      });
      map.add(marker);
    }

    for (const polylineData of renderData.polylines) {
      const polyline = new (window as any).AMap.Polyline({
        path: polylineData.path,
        strokeColor: polylineData.color,
        strokeWeight: polylineData.strokeWeight,
        strokeStyle: polylineData.strokeStyle,
        strokeOpacity: 0.8,
      });
      map.add(polyline);
    }

    map.setFitView(undefined, false, [50, 50, 50, 50]);
  }, []);

  const generateRoute = useCallback(async (chatText: string, userLocation?: { lng: number; lat: number }) => {
    if (abortControllerRef.current) {
      abortControllerRef.current.cancel();
    }
    abortControllerRef.current = createPlanAbortController();
    setPlanningState(true);
    setPlanningStep('准备中...');
    setPlanningProgress(0);
    setError(null);

    const request: PlanRequest = {
      user_request: chatText,
      plan_mode: 'exploratory',
      user_location: userLocation,
    };

    try {
      const plan = await planRoute(request, {
        onIntent: () => updateStep('intent'),
        onPOISearch: () => updateStep('poi_search'),
        onWeather: () => updateStep('weather'),
        onRoute: () => updateStep('route'),
        onRestaurant: () => updateStep('restaurant'),
        onComplete: (plan) => {
          updateStep('complete');
          if (plan) {
            setCurrentPlan(plan);
            addChatMessage({
              id: `route-${Date.now()}`,
              role: 'assistant',
              content: generatePlanSummary(plan),
              timestamp: Date.now(),
            });
            renderPlanOnMap(plan);
            options.onComplete?.(plan);
          }
        },
        onError: (error) => {
          setError(error);
          setPlanningState(false);
          options.onError?.(error);
        },
      }, abortControllerRef.current.controller.signal);

      setPlanningState(false);
      return plan;
    } catch (error: any) {
      if (error.name !== 'AbortError') {
        setError(error.message || '路线规划失败');
        options.onError?.(error.message);
      }
      setPlanningState(false);
      return null;
    }
  }, [setPlanningState, setPlanningStep, setPlanningProgress, setError, setCurrentPlan, addChatMessage, updateStep, renderPlanOnMap, options]);

  const cancelRoute = useCallback(() => {
    if (abortControllerRef.current) {
      abortControllerRef.current.cancel();
      abortControllerRef.current = null;
    }
    setPlanningState(false);
    setPlanningStep('idle');
    setPlanningProgress(0);
  }, [setPlanningState, setPlanningStep, setPlanningProgress]);

  return {
    generateRoute,
    cancelRoute,
    isPlanning,
    planningStep,
    planningProgress,
    currentPlan,
    setMapInstance: (map: any) => { mapRef.current = map; },
  };
}

function generatePlanSummary(plan: CompletePlan): string {
  let summary = `为您规划了${plan.parsed_intent.destination}${plan.days.length}日行程：\n\n`;
  for (const day of plan.days) {
    summary += `【Day${day.day_index} - ${day.day_of_week}】\n`;
    for (const timeSlot of day.time_slots) {
      summary += `\n${timeSlot.label}（${timeSlot.time_range}）：\n`;
      for (const activity of timeSlot.activities) {
        summary += `• ${activity.poi.name}\n`;
        if (activity.description) summary += `  ${activity.description}\n`;
      }
    }
    summary += '\n';
  }
  summary += `\n📊 总行程：${(plan.total_distance / 1000).toFixed(1)}公里`;
  if (plan.weather_summary) summary += `\n🌤️ ${plan.weather_summary}`;
  return summary;
}

export default useChatToRoute;
