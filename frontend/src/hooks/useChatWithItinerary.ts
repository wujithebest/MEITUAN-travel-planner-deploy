/**
 * useChatWithItinerary Hook - 连接聊天和行程侧边栏的状态管理
 * 
 * 功能：
 * 1. 监听聊天状态变化
 * 2. 在规划开始时调用 itinerary.startPlanning()
 * 3. 在收到进度消息时调用 itinerary.addProgress()
 * 4. 在规划完成时调用 itinerary.completePlanning()
 * 
 * 交互流程：
 * 用户输入 → startPlanning() → 显示进度消息 → completePlanning() → 右侧栏滑入
 */

import { useEffect, useCallback, useRef } from 'react';
import { useChat } from '@/hooks/useChat';
import { useItinerary, MapPath } from '@/hooks/useItinerary';

/**
 * useChatWithItinerary Hook 返回值
 */
export interface UseChatWithItineraryReturn {
  /** useChat 返回的所有值 */
  chat: ReturnType<typeof useChat>;
  /** useItinerary 返回的所有值 */
  itinerary: ReturnType<typeof useItinerary>;
  /** 发送消息（包装版本） */
  sendMessage: (text: string) => Promise<void>;
  /** 清空聊天和行程 */
  clearAll: () => void;
}

/**
 * useChatWithItinerary Hook
 */
export function useChatWithItinerary(): UseChatWithItineraryReturn {
  const chat = useChat();
  const itinerary = useItinerary();

  // 用于跟踪是否已经开始规划
  const hasStartedPlanningRef = useRef(false);
  // 用于累积结果文本
  const resultTextRef = useRef<string>('');
  // 用于存储地图路径
  const mapPathsRef = useRef<MapPath[]>([]);

  // 监听 currentPlanningStatus 变化，更新进度
  useEffect(() => {
    const status = chat.currentPlanningStatus;
    if (status) {
      if (
        status.includes('规划完成') ||
        status.includes('路线规划完成') ||
        status.includes('行程规划完成')
      ) {
        if (resultTextRef.current) {
          itinerary.completePlanning(resultTextRef.current, mapPathsRef.current);
        }
      } else {
        itinerary.addProgress(status);
      }
    }
  }, [chat.currentPlanningStatus, itinerary]);

  // 监听 messages 变化，检测规划结果
  useEffect(() => {
    if (chat.messages.length > 0) {
      const lastMessage = chat.messages[chat.messages.length - 1];
      
      // 检查是否是 AI 的最终回复（包含行程数据）
      if (
        lastMessage.role === 'assistant' &&
        !lastMessage.content.includes('[ROUTE_PLANNER]') &&
        lastMessage.content.length > 100
      ) {
        // 保存结果文本
        resultTextRef.current = lastMessage.content;
        
        // 检查是否包含"规划完成"的消息
        if (
          lastMessage.content.includes('规划完成') ||
          lastMessage.content.includes('为您规划了')
        ) {
          // 延迟触发 completePlanning，让进度消息先显示
          setTimeout(() => {
            itinerary.completePlanning(lastMessage.content, mapPathsRef.current);
          }, 500);
        }
      }
    }
  }, [chat.messages, itinerary]);

  // 监听 isLoading 变化，检测规划开始
  useEffect(() => {
    if (chat.isLoading && !hasStartedPlanningRef.current) {
      // 规划开始
      hasStartedPlanningRef.current = true;
      resultTextRef.current = '';
      mapPathsRef.current = [];
      itinerary.startPlanning();
    } else if (!chat.isLoading && hasStartedPlanningRef.current) {
      // 规划结束
      hasStartedPlanningRef.current = false;
    }
  }, [chat.isLoading, itinerary]);

  /**
   * 发送消息（包装版本）
   */
  const sendMessage = useCallback(async (text: string) => {
    // 重置状态
    hasStartedPlanningRef.current = false;
    resultTextRef.current = '';
    mapPathsRef.current = [];
    
    // 调用原始的 sendMessage
    await chat.sendMessage(text);
  }, [chat]);

  /**
   * 清空聊天和行程
   */
  const clearAll = useCallback(() => {
    hasStartedPlanningRef.current = false;
    resultTextRef.current = '';
    mapPathsRef.current = [];
    chat.clearChat();
    itinerary.reset();
  }, [chat, itinerary]);

  return {
    chat,
    itinerary,
    sendMessage,
    clearAll,
  };
}

export default useChatWithItinerary;
