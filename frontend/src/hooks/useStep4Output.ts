/**
 * Step4 输出数据 Hook
 * 管理 step4_output.py 返回的自然语言行程方案和地图渲染数据
 */

import { useState, useCallback } from 'react';
import { Step4Output, Step4Anchor, Step4ItineraryDay } from '@/api/types';
import { parseStep4TextOutput } from '@/api/step4';

interface UseStep4OutputReturn {
  /** step4 输出数据 */
  step4Output: Step4Output | null;
  /** 是否正在加载 */
  isLoading: boolean;
  /** 错误信息 */
  error: string | null;
  /** 设置 step4 输出数据 */
  setStep4Output: (output: Step4Output | null) => void;
  /** 从文本解析并设置 */
  parseFromText: (text: string) => void;
  /** 更新地图渲染数据 */
  updateMapData: (data: {
    route_polylines?: Step4Output['route_polylines'];
    poi_markers?: Step4Output['poi_markers'];
  }) => void;
  /** 清除数据 */
  clear: () => void;
  /** 设置加载状态 */
  setLoading: (loading: boolean) => void;
  /** 设置错误 */
  setError: (error: string | null) => void;
}

/**
 * Step4 输出数据 Hook
 * 
 * 使用方式：
 * const { step4Output, setStep4Output, parseFromText } = useStep4Output();
 */
export function useStep4Output(): UseStep4OutputReturn {
  const [step4Output, setStep4OutputState] = useState<Step4Output | null>(null);
  const [isLoading, setIsLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);

  /**
   * 设置 step4 输出数据
   */
  const setStep4Output = useCallback((output: Step4Output | null) => {
    setStep4OutputState(output);
    if (output) {
      setError(null);
    }
  }, []);

  /**
   * 从文本解析并设置
   * 用于处理 step4_output.py 的文本输出
   */
  const parseFromText = useCallback((text: string) => {
    try {
      const parsed = parseStep4TextOutput(text);
      setStep4OutputState(parsed);
      setError(null);
    } catch (err) {
      console.error('[useStep4Output] 解析文本失败:', err);
      setError('解析行程数据失败');
    }
  }, []);

  /**
   * 更新地图渲染数据
   * 用于在获取到路线和POI数据后更新
   */
  const updateMapData = useCallback((data: {
    route_polylines?: Step4Output['route_polylines'];
    poi_markers?: Step4Output['poi_markers'];
  }) => {
    setStep4OutputState(prev => {
      if (!prev) return prev;
      return {
        ...prev,
        route_polylines: data.route_polylines ?? prev.route_polylines,
        poi_markers: data.poi_markers ?? prev.poi_markers,
      };
    });
  }, []);

  /**
   * 清除数据
   */
  const clear = useCallback(() => {
    setStep4OutputState(null);
    setIsLoading(false);
    setError(null);
  }, []);

  /**
   * 设置加载状态
   */
  const setLoading = useCallback((loading: boolean) => {
    setIsLoading(loading);
  }, []);

  /**
   * 设置错误
   */
  const setErrorState = useCallback((err: string | null) => {
    setError(err);
    if (err) {
      setIsLoading(false);
    }
  }, []);

  return {
    step4Output,
    isLoading,
    error,
    setStep4Output,
    parseFromText,
    updateMapData,
    clear,
    setLoading,
    setError: setErrorState,
  };
}

export default useStep4Output;
