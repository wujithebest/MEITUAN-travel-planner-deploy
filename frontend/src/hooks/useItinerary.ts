/**
 * useItinerary Hook - 行程侧边栏状态管理
 * 
 * 管理右侧行程栏的显示/隐藏状态、规划进度、解析后的行程数据
 * 
 * 交互流程：
 * 1. 用户输入需求 → startPlanning()
 * 2. AI 助手流式返回 SSE 事件 → handleSSEEvent()
 *    - type='status' → 进度消息（正在加载、正在解析等）
 *    - type='result' → 行程结果片段（Day1、Day2 等）
 *    - type='complete' → 完成标记，解析并显示右侧栏
 *    - type='error' → 错误信息
 * 3. 收到 complete 事件 → 右侧栏自动滑入显示
 */

import { useState, useCallback, useRef } from 'react';
import { parseItinerary, ParsedItinerary } from '@/utils/parseItinerary';
import type { SSEEvent } from '@/types/plan';

/**
 * 地图路径数据
 */
export interface MapPath {
  day: number;
  path: string;
}

/**
 * useItinerary Hook 返回值
 */
export interface UseItineraryReturn {
  /** 右侧栏是否可见 */
  isVisible: boolean;
  /** 是否正在规划 */
  isPlanning: boolean;
  /** 进度消息列表 */
  progress: string[];
  /** 解析后的行程数据 */
  data: ParsedItinerary | null;
  /** 地图路径列表 */
  mapPaths: MapPath[];
  /** 是否收起 */
  collapsed: boolean;
  /** 开始规划 */
  startPlanning: () => void;
  /** 处理 SSE 事件（用于直接调用） */
  handleSSEEvent: (event: SSEEvent) => void;
  /** 添加进度消息 */
  addProgress: (msg: string) => void;
  /** 完成规划（旧接口，保留兼容） */
  completePlanning: (resultText: string, paths?: MapPath[]) => void;
  /** 关闭右侧栏 */
  closeSidebar: () => void;
  /** 打开右侧栏 */
  openSidebar: () => void;
  /** 切换收起/展开状态 */
  toggleCollapse: () => void;
  /** 重置状态 */
  reset: () => void;
}

/**
 * useItinerary Hook
 */
export function useItinerary(): UseItineraryReturn {
  const [isVisible, setIsVisible] = useState(false);
  const [isPlanning, setIsPlanning] = useState(false);
  const [progress, setProgress] = useState<string[]>([]);
  const [data, setData] = useState<ParsedItinerary | null>(null);
  const [mapPaths, setMapPaths] = useState<MapPath[]>([]);
  const [collapsed, setCollapsed] = useState(false);

  // 用于累积 result 类型的事件内容
  const resultBufferRef = useRef<string>('');

  /**
   * 开始规划
   * 重置所有状态，准备接收新的规划结果
   */
  const startPlanning = useCallback(() => {
    setIsPlanning(true);
    setIsVisible(false);
    setProgress([]);
    setData(null);
    setMapPaths([]);
    resultBufferRef.current = '';
  }, []);

  /**
   * 处理 SSE 事件
   * 根据事件类型分别处理：
   * - status: 进度消息（正在加载、正在解析等）
   * - result: 行程结果片段（Day1、Day2 等），累积到 buffer
   * - complete: 完成标记，解析并显示右侧栏
   * - error: 错误信息
   */
  const handleSSEEvent = useCallback((event: SSEEvent) => {
    console.log('[useItinerary] handleSSEEvent:', event.type, typeof event.content === 'string' ? event.content.substring(0, 60) : JSON.stringify(event.content).substring(0, 60));

    switch (event.type) {
      case 'status':
        // 进度消息：添加到进度列表
        if (typeof event.content === 'string' && event.content.trim()) {
          setProgress(prev => [...prev, event.content]);
        }
        break;

      case 'result':
        // 行程结果片段：累积到 buffer
        if (typeof event.content === 'string' && event.content.trim()) {
          resultBufferRef.current += '\n\n' + event.content;
        }
        break;

      case 'complete':
        // 完成标记：解析并显示右侧栏
        const fullText = resultBufferRef.current.trim();
        console.log('[useItinerary] complete 事件，行程文本长度:', fullText.length);
        
        if (fullText) {
          try {
            const parsed = parseItinerary(fullText);
            console.log('[useItinerary] 解析结果:', {
              days: parsed.days.length,
              summary: parsed.summary.substring(0, 50) + '...',
              anchors: parsed.anchorSummaries?.length || 0,
            });
            setData(parsed);
          } catch (err) {
            console.error('[useItinerary] 解析行程数据失败:', err);
            // 解析失败时仍然显示原始文本作为 fallback
            setData({
              summary: '旅行规划完成',
              days: [],
              anchorSummaries: [],
              mapPaths: [],
              itinerary: { days: [] },
              locations: { anchors: [] },
              routes: { days: [], totalDistance: 0, totalDuration: 0 },
            });
          }
        } else {
          // 没有行程文本时也创建占位数据
          setData({
            summary: '旅行规划完成',
            days: [],
            anchorSummaries: [],
            mapPaths: [],
            itinerary: { days: [] },
            locations: { anchors: [] },
            routes: { days: [], totalDistance: 0, totalDuration: 0 },
          });
        }

        // 设置地图路径
        if (event.content?.map_paths) {
          const paths: MapPath[] = event.content.map_paths.map((p: string, i: number) => ({
            day: i + 1,
            path: p,
          }));
          setMapPaths(paths);
        }

        setIsPlanning(false);
        // 延迟显示右侧栏，让用户看到"规划完成"的消息
        setTimeout(() => {
          setIsVisible(true);
        }, 300);
        break;

      case 'error':
        // 错误处理
        console.error('[useItinerary] 服务器错误:', event.content);
        setProgress(prev => [...prev, `❌ 错误: ${typeof event.content === 'string' ? event.content : JSON.stringify(event.content)}`]);
        setIsPlanning(false);
        break;
    }
  }, []);

  /**
   * 添加进度消息
   * 用于显示 SSE status 事件的进度消息（保留兼容旧接口）
   */
  const addProgress = useCallback((msg: string) => {
    setProgress(prev => [...prev, msg]);
  }, []);

  /**
   * 完成规划（旧接口，保留向后兼容）
   * 现在优先使用 handleSSEEvent 处理 complete 事件
   * 
   * @param resultText - 后端返回的纯文本行程数据
   * @param paths - 地图路径列表
   */
  const completePlanning = useCallback((resultText: string, paths: MapPath[] = []) => {
    console.log('[useItinerary] 完成规划（旧接口），结果文本长度:', resultText.length);
    
    // 解析行程数据
    const parsed = parseItinerary(resultText);
    console.log('[useItinerary] 解析结果:', {
      days: parsed.days.length,
      summary: parsed.summary.substring(0, 50) + '...',
      anchors: parsed.anchorSummaries.length,
    });

    setData(parsed);
    setMapPaths(paths);
    setIsPlanning(false);
    
    // 延迟显示右侧栏，让用户看到"规划完成"的消息
    setTimeout(() => {
      setIsVisible(true);
    }, 300);
  }, []);

  /**
   * 关闭右侧栏
   */
  const closeSidebar = useCallback(() => {
    setIsVisible(false);
  }, []);

  /**
   * 打开右侧栏
   */
  const openSidebar = useCallback(() => {
    if (data) {
      setIsVisible(true);
    }
  }, [data]);

  /**
   * 切换收起/展开状态
   */
  const toggleCollapse = useCallback(() => {
    setCollapsed(prev => !prev);
  }, []);

  /**
   * 重置所有状态
   */
  const reset = useCallback(() => {
    setIsVisible(false);
    setIsPlanning(false);
    setProgress([]);
    setData(null);
    setMapPaths([]);
    setCollapsed(false);
    resultBufferRef.current = '';
  }, []);

  return {
    isVisible,
    isPlanning,
    progress,
    data,
    mapPaths,
    collapsed,
    startPlanning,
    handleSSEEvent,
    addProgress,
    completePlanning,
    closeSidebar,
    openSidebar,
    toggleCollapse,
    reset,
  };
}

export default useItinerary;
