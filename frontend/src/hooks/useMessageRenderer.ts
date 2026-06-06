/**
 * React Hook - 消息渲染层集成
 */

import { useState, useEffect, useCallback } from 'react';
import { MessageRenderer, Message, createMessage } from '../utils/messageRenderer';

interface UseMessageRendererReturn {
  messages: Message[];
  sendMessage: (userId: string, content: string, options?: Partial<Message>) => boolean;
  receiveMessage: (message: Message) => boolean;
  confirmMessage: (messageId: string) => void;
  pendingMessages: Message[];
  showDuplicateAlert: boolean;
  clearDuplicateAlert: () => void;
}

export function useMessageRenderer(): UseMessageRendererReturn {
  const [messageRenderer] = useState(() => new MessageRenderer());
  const [messages, setMessages] = useState<Message[]>([]);
  const [pendingMessages, setPendingMessages] = useState<Message[]>([]);
  const [showDuplicateAlert, setShowDuplicateAlert] = useState(false);

  // 监听重复消息告警
  useEffect(() => {
    const handleDuplicateAlert = (event: CustomEvent) => {
      setShowDuplicateAlert(true);
    };

    window.addEventListener('message-duplicate-alert', handleDuplicateAlert as EventListener);
    
    return () => {
      window.removeEventListener('message-duplicate-alert', handleDuplicateAlert as EventListener);
    };
  }, []);

  // 发送消息
  const sendMessage = useCallback((userId: string, content: string, options?: Partial<Message>): boolean => {
    const message = createMessage(userId, content, options);
    const success = messageRenderer.sendMessage(message);
    
    if (success) {
      setMessages(messageRenderer.getMessages());
      setPendingMessages(messageRenderer.getPendingMessages());
    }
    
    return success;
  }, [messageRenderer]);

  // 接收消息
  const receiveMessage = useCallback((message: Message): boolean => {
    const success = messageRenderer.receiveServerMessage(message);
    
    if (success) {
      setMessages(messageRenderer.getMessages());
      setPendingMessages(messageRenderer.getPendingMessages());
    }
    
    return success;
  }, [messageRenderer]);

  // 确认消息
  const confirmMessage = useCallback((messageId: string): void => {
    messageRenderer.confirmLocalMessage(messageId);
    setMessages(messageRenderer.getMessages());
    setPendingMessages(messageRenderer.getPendingMessages());
  }, [messageRenderer]);

  // 清除重复告警
  const clearDuplicateAlert = useCallback((): void => {
    setShowDuplicateAlert(false);
  }, []);

  return {
    messages,
    sendMessage,
    receiveMessage,
    confirmMessage,
    pendingMessages,
    showDuplicateAlert,
    clearDuplicateAlert
  };
}
