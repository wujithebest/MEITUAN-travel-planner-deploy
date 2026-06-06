// ============================================
// AI聊天面板组件 - 简化版（非SSE流式）
// 交互流程：用户输入 → 显示"正在规划..." → 收到结果 → 显示AI回复+地图
// ============================================

import React, { useState, useRef, useEffect } from 'react';
import { Button, Input, Spin, Progress } from 'antd';
import { SendOutlined } from '@ant-design/icons';
import { useRouteStore } from '@/store/routeStore';
import { useRouteGenerate } from '@/hooks/useRouteGenerate';
import styles from './AIChatPanel.module.css';

const { TextArea } = Input;

interface ChatMessage {
  id: string;
  role: 'user' | 'assistant' | 'system';
  content: string;
  timestamp: number;
  isProgress?: boolean; // 是否为进度消息
}

interface AIChatPanelProps {
  onViewRoute?: (routeData: any) => void;
}

// 欢迎消息
const WELCOME_MESSAGE: ChatMessage = {
  id: 'welcome',
  role: 'assistant',
  content: '你好！我是你的AI旅行助手 🤖\n\n告诉我你想去哪里玩，我会为你规划完美的路线！\n\n例如：\n- 周末想去上海外滩拍夜景\n- 推荐上海美食之旅\n- 成都周末游，想看熊猫',
  timestamp: Date.now(),
};

const AIChatPanel: React.FC<AIChatPanelProps> = ({ onViewRoute }) => {
  const [messages, setMessages] = useState<ChatMessage[]>([WELCOME_MESSAGE]);
  const [inputText, setInputText] = useState('');
  const [isLoading, setIsLoading] = useState(false);
  const [progress, setProgress] = useState(0);
  const messagesEndRef = useRef<HTMLDivElement>(null);
  const inputRef = useRef<any>(null);

  const { generate } = useRouteGenerate();
  const planningProgress = useRouteStore((s) => s.planningProgress);

  // 自动滚动到底部
  useEffect(() => {
    messagesEndRef.current?.scrollIntoView({ behavior: 'smooth' });
  }, [messages, isLoading]);

  /**
   * 发送消息
   */
  const handleSend = async () => {
    const trimmedInput = inputText.trim();
    if (!trimmedInput || isLoading) return;

    // 添加用户消息
    const userMessage: ChatMessage = {
      id: `user-${Date.now()}`,
      role: 'user',
      content: trimmedInput,
      timestamp: Date.now(),
    };
    setMessages((prev) => [...prev, userMessage]);
    setInputText('');
    setIsLoading(true);
    setProgress(0);

    try {
      // 添加"正在规划..."消息
      const loadingMessage: ChatMessage = {
        id: `loading-${Date.now()}`,
        role: 'assistant',
        content: '正在为您规划路线...',
        timestamp: Date.now(),
        isProgress: true,
      };
      setMessages((prev) => [...prev, loadingMessage]);

      // 调用路线生成
      const requestBody = {
        text: trimmedInput,
        consider_weather: true,
      };
      console.log('[API Request Body]', JSON.stringify(requestBody));
      const result = await generate(requestBody);

      // 移除loading消息
      setMessages((prev) => prev.filter((m) => !m.isProgress));

      if (result) {
        // 添加AI回复消息
        const aiMessage: ChatMessage = {
          id: `ai-${Date.now()}`,
          role: 'assistant',
          content: generateSuccessMessage(result),
          timestamp: Date.now(),
        };
        setMessages((prev) => [...prev, aiMessage]);

        // 通知父组件查看地图
        if (onViewRoute) {
          onViewRoute(result);
        }
      }
    } catch (error: any) {
      console.error('发送消息失败:', error);

      // 移除loading消息，添加错误消息
      setMessages((prev) => {
        const filtered = prev.filter((m) => !m.isProgress);
        return [
          ...filtered,
          {
            id: `error-${Date.now()}`,
            role: 'assistant',
            content: `抱歉，规划失败：${error.message || '未知错误'}。请稍后再试。`,
            timestamp: Date.now(),
          },
        ];
      });
    } finally {
      setIsLoading(false);
      setProgress(0);
    }
  };

  /**
   * 生成成功消息
   */
  const generateSuccessMessage = (result: any): string => {
    const { summary, intent, daily_routes } = result;

    let message = `✅ 已为您规划好${summary.days}天的行程！\n\n`;

    // 意图识别结果
    if (intent) {
      message += `📍 目标区域：${intent.area}\n`;
      if (intent.keywords?.length > 0) {
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
    daily_routes.forEach((route: any, index: number) => {
      const dayPois = route.pois.slice(0, 3).map((p: any) => p.poi.name).join(' → ');
      const moreText = route.pois.length > 3 ? ` 等${route.pois.length}个景点` : '';
      message += `第${index + 1}天：${dayPois}${moreText}\n`;
    });

    message += '\n💡 点击右侧地图可查看详细路线！';

    return message;
  };

  /**
   * 键盘事件
   */
  const handleKeyDown = (e: React.KeyboardEvent) => {
    if (e.key === 'Enter' && !e.shiftKey) {
      e.preventDefault();
      handleSend();
    }
  };

  /**
   * 渲染消息
   */
  const renderMessage = (message: ChatMessage) => {
    const isUser = message.role === 'user';
    const isProgress = message.isProgress;

    return (
      <div
        key={message.id}
        className={`${styles.messageBubble} ${isUser ? styles.userBubble : styles.aiBubble}`}
      >
        {!isUser && (
          <div className={styles.avatar}>
            <img 
              src="/ai-travel-logo.png" 
              alt="AI旅行助手" 
              className={styles.avatarLogo}
            />
          </div>
        )}
        <div className={styles.messageContent}>
          <div className={styles.messageText}>
            {isProgress ? (
              <span>
                {message.content}
                <Spin size="small" style={{ marginLeft: 8 }} />
              </span>
            ) : (
              message.content
            )}
          </div>
        </div>
      </div>
    );
  };

  return (
    <div className={styles.chatPanel}>
      {/* 头部 */}
      <div className={styles.chatHeader}>
        <img 
          src="/ai-travel-logo.png" 
          alt="AI旅行助手" 
          className={styles.headerLogo}
        />
        <span className={styles.headerTitle}>AI旅行助手</span>
      </div>

      {/* 消息列表 */}
      <div className={styles.messageList}>
        {messages.map(renderMessage)}

        {/* 进度条 */}
        {isLoading && progress > 0 && (
          <div className={styles.progressContainer}>
            <Progress percent={progress} size="small" status="active" />
          </div>
        )}

        <div ref={messagesEndRef} />
      </div>

      {/* 输入区域 */}
      <div className={styles.inputArea}>
        <div className={styles.inputRow}>
          <TextArea
            ref={inputRef}
            value={inputText}
            onChange={(e) => setInputText(e.target.value)}
            placeholder="告诉我你想去哪里玩..."
            autoSize={{ minRows: 1, maxRows: 4 }}
            onKeyDown={handleKeyDown}
            className={styles.textInput}
            disabled={isLoading}
          />
          <Button
            type="primary"
            icon={<SendOutlined />}
            onClick={handleSend}
            disabled={!inputText.trim() || isLoading}
            className={styles.sendBtn}
            loading={isLoading}
          >
            发送
          </Button>
        </div>
      </div>
    </div>
  );
};

export default AIChatPanel;
