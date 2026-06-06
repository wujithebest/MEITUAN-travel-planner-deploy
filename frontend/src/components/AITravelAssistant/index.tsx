/**
 * AI 旅游助手组件 - 路线规划系统
 * 支持模式选择、流式输出、路线数据传递
 */

import React, { useEffect, useRef, useState, useCallback } from 'react';
import {
  LoadingOutlined,
  ReloadOutlined,
  SendOutlined,
  UserOutlined,
  CompassOutlined,
  OrderedListOutlined,
} from '@ant-design/icons';
import { Spin, Input, Button } from 'antd';
import {
  sendMeituanMessageStream,
  extractMeituanMapData,
  MeituanRouteData,
  MeituanIntentData,
} from '@/api/meituanChat';
import styles from './AITravelAssistant.module.css';

const { TextArea } = Input;

interface AITravelAssistantProps {
  /** 是否正在加载 */
  isLoading?: boolean;
  /** 错误信息 */
  error?: string | null;
  /** 重新生成回调 */
  onRegenerate?: () => void;
  /** 点击锚点回调（用于地图联动） */
  onAnchorClick?: (anchorName: string) => void;
  /** 路线数据更新回调（用于地图渲染） */
  onRouteUpdate?: (routeData: MeituanRouteData) => void;
}

interface ChatMessage {
  id: string;
  type: 'user' | 'agent' | 'system';
  text: string;
  route?: MeituanRouteData;
  timestamp: number;
}

type AppState = 'welcome' | 'selecting_mode' | 'planning' | 'result';

/**
 * AI 旅游助手组件
 * 
 * 功能：
 * 1. 初始显示欢迎信息和模式选择按钮
 * 2. 支持自由探索和连续决策两种模式
 * 3. 流式显示规划进度
 * 4. 支持路线数据传递给地图组件
 */
const AITravelAssistant: React.FC<AITravelAssistantProps> = ({
  onRegenerate,
  onAnchorClick,
  onRouteUpdate,
}) => {
  const contentRef = useRef<HTMLDivElement>(null);
  const inputRef = useRef<any>(null);
  const abortControllerRef = useRef<AbortController | null>(null);
  
  const [appState, setAppState] = useState<AppState>('welcome');
  const [planMode, setPlanMode] = useState<'exploratory' | 'planned' | null>(null);
  const [messages, setMessages] = useState<ChatMessage[]>([]);
  const [inputText, setInputText] = useState('');
  const [isPlanning, setIsPlanning] = useState(false);
  const [streamingText, setStreamingText] = useState('');
  const [error, setError] = useState<string | null>(null);
  const [isWelcomeLoading, setIsWelcomeLoading] = useState(false); // 新增：欢迎语加载状态

  // 生成唯一 ID
  const generateId = () => `msg_${Date.now()}_${Math.random().toString(36).substr(2, 9)}`;

  // 添加消息
  const addMessage = useCallback((msg: Omit<ChatMessage, 'id' | 'timestamp'>) => {
    const newMsg: ChatMessage = {
      ...msg,
      id: generateId(),
      timestamp: Date.now(),
    };
    setMessages(prev => [...prev, newMsg]);
    return newMsg;
  }, []);

  // ========== 新增：组件挂载时自动获取后端欢迎语 ==========
  useEffect(() => {
    const loadWelcome = async () => {
      setIsWelcomeLoading(true);
      setIsPlanning(true);
      
      try {
        abortControllerRef.current = sendMeituanMessageStream(
          '__welcome__',  // 特殊标记，让后端返回欢迎语
          'exploratory',  // 默认模式，后端会忽略
          undefined,
          {
            onMessage: (content) => {
              setStreamingText(prev => prev + content);
            },
            onComplete: (reply, route, intent) => {
              // 将后端欢迎语作为第一条 agent 消息
              addMessage({
                type: 'agent',
                text: reply,
              });
              setIsPlanning(false);
              setStreamingText('');
              setIsWelcomeLoading(false);
            },
            onError: (err) => {
              console.error('[AITravelAssistant] 欢迎语获取失败:', err);
              // 降级：显示后端格式的静态欢迎语
              addMessage({
                type: 'agent',
                text: `[ROUTE_PLANNER]: 欢迎使用路线规划系统！\n[ROUTE_PLANNER]: 请选择规划模式：\n[ROUTE_PLANNER]:   1 - 自由探索（系统推荐路线）\n[ROUTE_PLANNER]:   2 - 连续决策（指定途经点，逐步规划）`,
              });
              setIsPlanning(false);
              setStreamingText('');
              setIsWelcomeLoading(false);
            },
          }
        );
      } catch (err: any) {
        console.error('[AITravelAssistant] 初始化失败:', err);
        setIsPlanning(false);
        setIsWelcomeLoading(false);
      }
    };

    // 组件挂载时自动加载欢迎语
    loadWelcome();

    // 清理函数
    return () => {
      if (abortControllerRef.current) {
        abortControllerRef.current.abort();
      }
    };
  }, []); // 空依赖数组，只在组件挂载时执行

  // 选择模式
  const handleSelectMode = (mode: 'exploratory' | 'planned') => {
    setPlanMode(mode);
    setAppState('planning');
    
    // 添加系统消息显示选择结果
    const modeText = mode === 'exploratory' ? '自由探索' : '连续决策';
    addMessage({
      type: 'system',
      text: `[ROUTE_PLANNER]: 已选择【${modeText}】模式`,
    });

    if (mode === 'planned') {
      addMessage({
        type: 'system',
        text: '[ROUTE_PLANNER]: 请描述您的有序途经点，如：去百联又一城逛→找麦当劳吃晚饭→顺路买水果',
      });
    }

    // 聚焦输入框
    setTimeout(() => inputRef.current?.focus(), 100);
  };

  // 发送消息
  const sendMessage = async () => {
    const text = inputText.trim();
    if (!text || isPlanning || !planMode) return;

    // 清空输入
    setInputText('');

    // 显示用户消息
    addMessage({ type: 'user', text });

    setIsPlanning(true);
    setStreamingText('');
    setError(null);
    setAppState('result');

    try {
      // 取消之前的请求
      if (abortControllerRef.current) {
        abortControllerRef.current.abort();
      }

      // 发送流式请求
      abortControllerRef.current = sendMeituanMessageStream(
        text,
        planMode,
        undefined,
        {
          onMessage: (content) => {
            // 实时更新流式文本
            setStreamingText(prev => prev + content + '\n');
          },
          onComplete: (reply, route, intent) => {
            // 规划完成，添加最终消息
            addMessage({
              type: 'agent',
              text: reply,
              route: route,
            });

            // 通知地图更新
            if (route && onRouteUpdate) {
              onRouteUpdate(route);
            }

            setIsPlanning(false);
            setStreamingText('');
          },
          onError: (err) => {
            console.error('[AITravelAssistant] 规划失败:', err);
            setError(err || '服务暂时不可用');
            addMessage({
              type: 'agent',
              text: `[ROUTE_PLANNER]: 抱歉，处理您的请求时遇到了问题：${err || '未知错误'}。请重试。`,
            });
            setIsPlanning(false);
            setStreamingText('');
          },
        }
      );
    } catch (err: any) {
      console.error('[AITravelAssistant] 发送消息失败:', err);
      setError(err.message || '服务暂时不可用');
      addMessage({
        type: 'agent',
        text: '[ROUTE_PLANNER]: 抱歉，服务暂时不可用，请稍后重试。',
      });
      setIsPlanning(false);
    }
  };

  // 处理按键
  const handleKeyDown = (e: React.KeyboardEvent) => {
    if (e.key === 'Enter' && !e.shiftKey) {
      e.preventDefault();
      sendMessage();
    }
  };

  // 重置到欢迎界面
  const handleReset = () => {
    if (abortControllerRef.current) {
      abortControllerRef.current.abort();
    }
    setAppState('welcome');
    setPlanMode(null);
    setMessages([]);
    setInputText('');
    setStreamingText('');
    setIsPlanning(false);
    setError(null);
  };

  // 自动滚动到底部
  useEffect(() => {
    if (contentRef.current) {
      contentRef.current.scrollTop = contentRef.current.scrollHeight;
    }
  }, [messages, streamingText, isPlanning]);

  // 渲染消息气泡
  const renderMessage = (msg: ChatMessage) => {
    if (msg.type === 'user') {
      return (
        <div key={msg.id} className={styles.userMessage}>
          <div className={styles.userAvatar}>
            <UserOutlined />
          </div>
          <div className={styles.userBubble}>
            {msg.text}
          </div>
        </div>
      );
    }

    if (msg.type === 'system') {
      return (
        <div key={msg.id} className={styles.systemMessage}>
          <div className={styles.systemBubble}>
            {msg.text}
          </div>
        </div>
      );
    }

    // Agent 消息
    return (
      <div key={msg.id} className={styles.agentMessage}>
        <div className={styles.agentAvatar}>
          <img 
            src="/ai-travel-logo.png" 
            alt="AI旅游助手" 
            className={styles.agentLogo}
            onError={(e) => {
              // 如果图片加载失败，显示文字
              e.currentTarget.style.display = 'none';
              e.currentTarget.parentElement!.textContent = '🤖';
            }}
          />
        </div>
        <div className={styles.agentBubble}>
          {renderOutputText(msg.text)}
        </div>
      </div>
    );
  };

  // 渲染输出文本（完全按照后端格式）
  const renderOutputText = (text: string): React.ReactNode[] => {
    const lines = text.split('\n');
    const elements: React.ReactNode[] = [];

    lines.forEach((line, index) => {
      const key = `line-${index}`;

      // 保留 [ROUTE_PLANNER]: 前缀
      const isRoutePlanner = line.startsWith('[ROUTE_PLANNER]:');
      const displayLine = isRoutePlanner ? line : line;

      // 标题：【Day1】等
      if (displayLine.match(/^【Day\d+】/)) {
        elements.push(
          <h3 key={key} className={styles.dayTitle}>
            {displayLine}
          </h3>
        );
        return;
      }

      // 时间段标题
      if (displayLine.match(/^(?:上午|下午|晚上|傍晚|全天)/)) {
        elements.push(
          <h4 key={key} className={styles.timeSlot}>
            {displayLine}
          </h4>
        );
        return;
      }

      // 列表项：· 或 - 或数字.
      const listMatch = displayLine.match(/^[·\-]\s+(.+)/);
      if (listMatch) {
        const content = listMatch[1];
        elements.push(
          <div key={key} className={styles.listItem}>
            <span className={styles.bullet}>•</span>
            <span>{renderInlineMarkdown(content)}</span>
          </div>
        );
        return;
      }

      // 缩进内容（子项）
      if (line.startsWith('  ') || line.startsWith('\t')) {
        elements.push(
          <p key={key} className={styles.indentedText}>
            {renderInlineMarkdown(displayLine.trim())}
          </p>
        );
        return;
      }

      // 地图链接
      if (displayLine.includes('地图') && displayLine.includes('点击查看')) {
        const mapMatch = displayLine.match(/点击查看：(.+)/);
        elements.push(
          <div key={key} className={styles.mapLinkContainer}>
            <span className={styles.mapLink}>
              🗺️ {mapMatch ? `查看地图: ${mapMatch[1]}` : '查看完整地图'}
            </span>
          </div>
        );
        return;
      }

      // 空行
      if (displayLine.trim() === '') {
        elements.push(<div key={key} className={styles.spacer} />);
        return;
      }

      // 普通段落
      elements.push(
        <p key={key} className={styles.paragraph}>
          {renderInlineMarkdown(displayLine)}
        </p>
      );
    });

    return elements;
  };

  // 渲染行内 Markdown
  const renderInlineMarkdown = (text: string): React.ReactNode => {
    // 处理 **强调**
    const parts = text.split(/(\*\*[^*]+\*\*|`[^`]+`)/g);

    return parts.map((part, index) => {
      // **强调**
      if (part.startsWith('**') && part.endsWith('**')) {
        return <strong key={index} className={styles.strong}>{part.slice(2, -2)}</strong>;
      }
      // `代码`
      if (part.startsWith('`') && part.endsWith('`')) {
        return <code key={index} className={styles.code}>{part.slice(1, -1)}</code>;
      }
      return part;
    });
  };

  // 渲染流式输出
  const renderStreamingOutput = () => {
    if (!streamingText && !isPlanning) return null;

    return (
      <div className={styles.streamingMessage}>
        <div className={styles.agentAvatar}>
          <img 
            src="/ai-travel-logo.png" 
            alt="AI旅游助手" 
            className={styles.agentLogo}
            onError={(e) => {
              e.currentTarget.style.display = 'none';
              e.currentTarget.parentElement!.textContent = '🤖';
            }}
          />
        </div>
        <div className={styles.agentBubble}>
          {streamingText && renderOutputText(streamingText)}
          {isPlanning && (
            <div className={styles.typingIndicator}>
              <Spin indicator={<LoadingOutlined spin />} size="small" />
              <span>正在规划...</span>
            </div>
          )}
        </div>
      </div>
    );
  };

  // 渲染欢迎界面（现在只显示模式选择，欢迎语已由后端提供）
  const renderWelcome = () => (
    <div className={styles.welcomeContainer}>
      {isWelcomeLoading ? (
        <div className={styles.welcomeLoading}>
          <Spin indicator={<LoadingOutlined spin />} size="large" />
          <span>正在初始化...</span>
        </div>
      ) : (
        <>
          <div className={styles.welcomeHeader}>
            <div className={styles.welcomeIcon}>🤖</div>
            <h2 className={styles.welcomeTitle}>路线规划系统</h2>
            <p className={styles.welcomeSubtitle}>请选择规划模式：</p>
          </div>
          <div className={styles.modeSelection}>
            <button
              className={`${styles.modeButton} ${styles.exploratoryMode}`}
              onClick={() => handleSelectMode('exploratory')}
            >
              <div className={styles.modeIcon}>
                <span className={styles.modeNumber}>1</span>
              </div>
              <div className={styles.modeContent}>
                <h3 className={styles.modeTitle}>自由探索</h3>
                <p className={styles.modeDescription}>系统推荐路线</p>
              </div>
            </button>
            <button
              className={`${styles.modeButton} ${styles.plannedMode}`}
              onClick={() => handleSelectMode('planned')}
            >
              <div className={styles.modeIcon}>
                <span className={styles.modeNumber}>2</span>
              </div>
              <div className={styles.modeContent}>
                <h3 className={styles.modeTitle}>连续决策</h3>
                <p className={styles.modeDescription}>指定途经点，逐步规划</p>
              </div>
            </button>
          </div>
        </>
      )}
    </div>
  );

  // 渲染聊天界面
  const renderChat = () => (
    <>
      <div className={styles.messagesContainer}>
        {messages.map(renderMessage)}
        {renderStreamingOutput()}
      </div>
    </>
  );

  return (
    <div className={styles.container}>
      {/* 头部 */}
      <div className={styles.header}>
        <div className={styles.headerLeft}>
          <img 
            src="/ai-travel-logo.png" 
            alt="AI旅游助手" 
            className={styles.headerLogo}
            onError={(e) => {
              e.currentTarget.style.display = 'none';
            }}
          />
          <span className={styles.headerTitle}>AI 旅游助手</span>
          {planMode && (
            <span className={styles.modeBadge}>
              {planMode === 'exploratory' ? '自由探索' : '连续决策'}
            </span>
          )}
        </div>
        <div className={styles.headerRight}>
          {appState !== 'welcome' && (
            <button 
              className={styles.resetBtn} 
              onClick={handleReset}
              title="重新开始"
            >
              <ReloadOutlined /> 重新开始
            </button>
          )}
          {onRegenerate && messages.length > 0 && (
            <button 
              className={styles.regenerateBtn} 
              onClick={onRegenerate} 
              title="重新生成"
              disabled={isPlanning}
            >
              <ReloadOutlined />
            </button>
          )}
        </div>
      </div>

      {/* 内容区 */}
      <div className={styles.content} ref={contentRef}>
        {/* 欢迎语已作为 agent 消息加入 messages，所以 welcome 状态显示消息列表 + 模式选择 */}
        {appState === 'welcome' ? (
          <>
            {messages.length > 0 && renderChat()}
            {renderWelcome()}
          </>
        ) : (
          renderChat()
        )}
      </div>

      {/* 输入框 - 只在非欢迎界面显示 */}
      {appState !== 'welcome' && (
        <div className={styles.inputContainer}>
          {error && (
            <div className={styles.errorBanner}>
              <span>⚠️ {error}</span>
              <button onClick={() => setError(null)}>✕</button>
            </div>
          )}
          <div className={styles.inputWrapper}>
            <TextArea
              ref={inputRef}
              value={inputText}
              onChange={(e) => setInputText(e.target.value)}
              onKeyDown={handleKeyDown}
              placeholder={
                planMode === 'planned'
                  ? "描述您的有序途经点，如：去百联又一城逛→找麦当劳吃晚饭..."
                  : "输入您的出行需求..."
              }
              autoSize={{ minRows: 1, maxRows: 4 }}
              className={styles.textInput}
              disabled={isPlanning}
            />
            <Button
              type="primary"
              icon={<SendOutlined />}
              onClick={sendMessage}
              disabled={!inputText.trim() || isPlanning}
              className={styles.sendButton}
              loading={isPlanning}
            />
          </div>
        </div>
      )}
    </div>
  );
};

export default AITravelAssistant;
