/**
 * ChatPanel 组件 - 左侧 AI 旅游助手聊天框
 * 
 * 功能：
 * 1. 美团黄背景渐变 (#FFD100 → #FFC300)
 * 2. 固定在左侧，宽度 320px
 * 3. 聊天消息气泡：用户白色右对齐，AI 黄色左对齐
 * 4. AI 回复中"行程概览"、"Day X"等关键字高亮
 * 5. 输入框可输入，发送按钮可用，其他按钮 disabled
 * 6. 模式选择交互：先选择模式，再输入出行需求
 * 7. 显示 SSE status 事件的进度消息
 */

import React, { useState, useRef, useEffect } from 'react';
import { SendOutlined, MenuOutlined } from '@ant-design/icons';
import { Trash2, History } from 'lucide-react';
import { Input, Tooltip } from 'antd';
import { ChatMessage } from '@/hooks/useChat';
import { useRouteStore } from '@/store/routeStore';
import styles from './ChatPanel.module.css';

const { TextArea } = Input;

const QUICK_PROMPTS_BY_MODE: Record<string, string[]> = {
  exploratory: [
    '我明天想去外滩玩一整天，帮我规划一下路线',
    '上午去南京路步行街逛逛，下午想去陆家嘴，晚上找个好吃的地方',
    '还有两个小时，我在杨浦滨江附近随便走走',
  ],
  planned: [
    '待会儿下班，在附近找一家日料店，然后回家',
    '下班路上想顺便买点水果，再找个地方简单吃晚饭',
    '回家前想理个发，附近如果有不错的咖啡店也可以坐一会儿',
  ],
};

interface ChatPanelProps {
  /** 聊天消息列表 */
  messages: ChatMessage[];
  /** 是否正在加载 */
  isLoading: boolean;
  /** 错误信息 */
  error: string | null;
  /** 当前 SSE 状态文本 */
  currentPlanningStatus: string | null;
  /** 规划已耗时（秒） */
  planningElapsedSeconds: number;
  /** 是否正在规划中 */
  isPlanningActive: boolean;
  /** 当前高亮的天数 */
  activeDay: number | null;
  /** 当前规划模式 */
  planMode: 'exploratory' | 'planned' | null;
  /** 设置规划模式 */
  setPlanMode: (mode: 'exploratory' | 'planned') => void;
  /** 发送消息 */
  sendMessage: (text: string) => Promise<void>;
  /** 清空聊天 */
  clearChat: () => void;
  /** 设置高亮天数 */
  setActiveDay: (day: number | null) => void;
  /** 路线数据变化回调 */
  onRouteChange?: (routeData: {
    polylines: Array<{ day_index: number; polyline: string; color: string }>;
    markers: Array<{ name: string; location: string; type: string; day_index: number }>;
    center: [number, number] | null;
  }) => void;
  /** 天数高亮变化回调 */
  onDayChange?: (day: number | null) => void;
  /** 规划完成回调 - 用于触发行程侧边栏显示 */
  onPlanningComplete?: (resultText: string) => void;
  /** 切换右侧栏折叠状态 */
  onToggleSidebar?: () => void;
  /** 右侧栏是否折叠 */
  isSidebarCollapsed?: boolean;
  /** 加载规划历史回调 */
  onLoadHistory?: (history: any) => void;
  /** 删除规划历史回调 */
  onDeleteHistory?: (historyId: string) => void;
  /** 发送消息时回调（用于标记已发送状态） */
  onSend?: () => void;
  /** 近期历史列表（用于欢迎框） */
  recentHistories?: any[];
  /** 是否已发送过消息 */
  hasSentInSession?: boolean;
}

/**
 * ChatPanel 组件
 */
const ChatPanel: React.FC<ChatPanelProps> = ({
  messages,
  isLoading,
  error,
  currentPlanningStatus,
  planningElapsedSeconds,
  isPlanningActive,
  activeDay,
  planMode,
  setPlanMode,
  sendMessage,
  clearChat,
  setActiveDay,
  onRouteChange,
  onDayChange,
  onPlanningComplete,
  onToggleSidebar,
  isSidebarCollapsed = false,
  onLoadHistory,
  onDeleteHistory,
  onSend,
  recentHistories = [],
  hasSentInSession = false,
}) => {
  const [inputText, setInputText] = useState('');
  const [historyPanelOpen, setHistoryPanelOpen] = useState(false);
  const messagesEndRef = useRef<HTMLDivElement>(null);
  const inputRef = useRef<any>(null);
  const prevIsLoadingRef = useRef<boolean>(false);
  const hasTriggeredCompleteRef = useRef<boolean>(false);

  // 自动滚动到底部
  useEffect(() => {
    messagesEndRef.current?.scrollIntoView({ behavior: 'smooth' });
  }, [messages, isLoading, isPlanningActive]);

  /** 判断文本是否为加载状态文本（不应进入气泡） */
  const isPlanningStatusText = (content: string): boolean => {
    const text = content.trim();
    return /^正在/.test(text)
      && (
        text.includes('加载用户信息')
        || text.includes('解析您的出行意图')
        || text.includes('查询天气')
        || text.includes('查询目的地')
        || text.includes('搜索周边')
        || text.includes('补充目的地')
        || text.includes('规划路线')
        || text.includes('生成路线')
        || text.includes('路线规划完成')
        || text.includes('整理路线')
      );
  };

  /** 检查是否有推荐理由数据（优先检查消息自身快照，回退到全局 currentPlan） */
  const hasReasonsInMessage = (msg: ChatMessage): boolean => {
    if (msg.recommendReasons && msg.recommendReasons.length > 0) return true;
    // 回退：最新消息可能还没有快照，从全局 plan 读取
    const plan = useRouteStore.getState().currentPlan;
    if (!plan?.days) return false;
    for (const day of plan.days) {
      for (const slot of day.time_slots) {
        for (const activity of slot.activities) {
          if (activity.description && activity.poi?.name) return true;
        }
      }
    }
    return false;
  };

  /** 过滤消息列表：排除空内容、状态文本、无数据的推荐理由消息 */
  const visibleMessages = React.useMemo(() => {
    return messages.filter(msg => {
      // 推荐理由消息：有真实数据才显示（检查消息自身快照或全局 plan）
      if (msg.role === 'assistant' && msg.displayType === 'recommendReasons') {
        return hasReasonsInMessage(msg);
      }
      // 排除状态文本
      if (msg.role === 'assistant' && isPlanningStatusText(msg.content)) {
        return false;
      }
      // 排除空内容
      return typeof msg.content === 'string' && msg.content.trim().length > 0;
    });
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [messages]);

  /** 格式化耗时 */
  const formatElapsed = (seconds: number): string => {
    if (seconds < 60) return `${seconds}s`;
    const m = Math.floor(seconds / 60);
    const s = seconds % 60;
    return `${m}m ${s}s`;
  };

  // 通知父组件路线数据变化
  useEffect(() => {
    if (onRouteChange) {
      const lastAiMessage = [...messages].reverse().find((m) => m.role === 'assistant' && m.routeData);
      if (lastAiMessage?.routeData) {
        // 防御：确保 routeData 有必要的属性
        const routeData = lastAiMessage.routeData;
        const safeRouteData = {
          polylines: Array.isArray(routeData.polylines) ? routeData.polylines : [],
          markers: Array.isArray(routeData.markers) ? routeData.markers : [],
          center: routeData.center || null,
        };
        onRouteChange(safeRouteData);
      }
    }
  }, [messages, onRouteChange]);

  // 通知父组件天数变化
  useEffect(() => {
    if (onDayChange) {
      onDayChange(activeDay);
    }
  }, [activeDay, onDayChange]);

  // 检测规划完成 - 当 isLoading 从 true 变为 false 时触发
  useEffect(() => {
    const wasLoading = prevIsLoadingRef.current;

    if (wasLoading && !isLoading && onPlanningComplete) {
      console.log('[ChatPanel] 检测到规划完成');

      // 查找最后一条真实的 assistant 消息（排除推荐理由和状态文本）
      const realAiMessage = [...messages].reverse().find(m => {
        if (m.role !== 'assistant') return false;
        if (m.displayType === 'recommendReasons') return false;
        if (isPlanningStatusText(m.content)) return false;
        return typeof m.content === 'string' && m.content.trim().length > 0;
      });

      if (realAiMessage && realAiMessage.content.length > 0) {
        console.log('[ChatPanel] 触发 onPlanningComplete 回调');
        hasTriggeredCompleteRef.current = true;
        onPlanningComplete(realAiMessage.content);
      } else {
        // 没有真实文本内容时，传入摘要兜底
        const summary = useRouteStore.getState().currentPlan?.weather_summary || '路线规划完成';
        hasTriggeredCompleteRef.current = true;
        onPlanningComplete(summary);
      }
    }

    // 当开始新的加载时，重置标记
    if (isLoading && !wasLoading) {
      hasTriggeredCompleteRef.current = false;
    }

    prevIsLoadingRef.current = isLoading;
  }, [isLoading, messages, onPlanningComplete]);

  /**
   * 发送消息
   */
  const handleSend = async () => {
    const trimmedInput = inputText.trim();
    if (!trimmedInput || isLoading) return;

    setInputText('');
    onSend?.();
    await sendMessage(trimmedInput);
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
   * 渲染消息内容（高亮关键字）
   */
  /**
   * 解析推荐理由文本，按关键词分段
   */
  const SECTION_KEYWORDS = [
    { key: 'core', labels: ['核心看点', '新看点', '和新看点'] },
    { key: 'match', labels: ['匹配理由'] },
    { key: 'play', labels: ['玩法建议'] },
    { key: 'commute', labels: ['通勤成本', '通勤'] },
    { key: 'transport', labels: ['交通建议'] },
  ];

  const SECTION_LABEL_MAP: Record<string, string> = {
    core: '核心看点',
    match: '匹配理由',
    play: '玩法建议',
    commute: '通勤成本',
    transport: '交通建议',
  };

  const parseReasonSections = (reason: string): Array<{ label: string; content: string }> => {
    if (!reason || typeof reason !== 'string') return [];
    // Try to split by section keywords
    const sepPattern = /[：:;；、]/;
    const parts: Array<{ label: string; content: string }> = [];
    let remaining = reason.trim();

    for (const kw of SECTION_KEYWORDS) {
      for (const label of kw.labels) {
        // Find label followed by separator
        const idx = remaining.indexOf(label);
        if (idx < 0) continue;
        const afterLabel = remaining.slice(idx + label.length);
        const sepMatch = afterLabel.match(sepPattern);
        const contentStart = sepMatch ? idx + label.length + sepMatch[0].length : idx + label.length;
        // Find the end: next keyword or end of string
        let contentEnd = remaining.length;
        for (const kw2 of SECTION_KEYWORDS) {
          for (const label2 of kw2.labels) {
            const nextIdx = remaining.indexOf(label2, contentStart);
            if (nextIdx >= 0 && nextIdx < contentEnd) {
              contentEnd = nextIdx;
            }
          }
        }
        const content = remaining.slice(contentStart, contentEnd).replace(/^[：:;；、\s]+/, '').trim();
        if (content) {
          parts.push({ label: SECTION_LABEL_MAP[kw.key] || label, content });
        }
        remaining = remaining.slice(0, idx) + remaining.slice(contentEnd);
        break;
      }
    }

    // If no sections found, return empty so caller falls back to raw text
    return parts;
  };

  // 餐饮 slot 标签 map
  const MEAL_SLOT_LABELS: Record<string, string> = { lunch: '午饭', dinner: '晚饭' };

  /**
   * 清理推荐理由文本中的"安排建议"相关内容
   */
  const stripArrangeAdvice = (text: string): string => {
    if (!text) return '';
    // Remove "安排建议：xxx" or "安排建议: xxx" sections
    let cleaned = text.replace(/安排建议[：:]\s*[^。\n]*[。\n]?/g, '');
    // Remove standalone "安排建议" keyword
    cleaned = cleaned.replace(/安排建议/g, '');
    return cleaned.trim();
  };

  /**
   * 从 routeStore.currentPlan 中提取推荐理由
   */
  const renderRecommendReasons = (message: ChatMessage) => {
    if (message.role !== 'assistant') return null;

    // 新格式：slot-structured reasons
    if (message.slotReasons && message.slotReasons.length > 0) {
      return (
        <div className={styles.reasonsSection}>
          <div className={styles.reasonsTitle}>✨ 推荐理由</div>
          {message.slotReasons.map((slotData, slotIdx) => {
            const isMealSlot = slotData.slot === 'lunch' || slotData.slot === 'dinner';
            const isFirst = slotIdx === 0;
            return (
              <div
                key={`slot-${slotData.slot}-${slotIdx}`}
                className={`${styles.slotBlock} ${!isFirst ? styles.slotBlockDivider : ''}`}
              >
                <span className={`${styles.slotLabel} ${isMealSlot ? styles.slotLabelMeal : ''}`}>
                  {slotData.slotLabel}
                </span>
                {slotData.items.map((item, itemIdx) => {
                  if (item.isMeal) {
                    // 餐饮 POI 行
                    return (
                      <div key={`meal-${itemIdx}`} className={styles.reasonPoiBlock}>
                        <div className={styles.reasonPoiName}>{item.name}</div>
                        {item.transport_text && (
                          <div className={styles.reasonMealTransport}>{item.transport_text}</div>
                        )}
                      </div>
                    );
                  }
                  // 普通推荐理由: parse sections
                  const reasonText = item.reason || '';
                  const sections = parseReasonSections(reasonText);
                  const hasSections = sections.length > 0;
                  const fallbackText = hasSections ? '' : stripArrangeAdvice(reasonText);
                  if (!hasSections && !fallbackText) return null;
                  return (
                    <div key={`reason-${itemIdx}`} className={styles.reasonPoiBlock}>
                      <div className={styles.reasonPoiName}>{item.name}</div>
                      {hasSections ? (
                        sections.map((sec, sIdx) => (
                          <div key={sIdx} className={styles.reasonSectionRow}>
                            <span className={styles.reasonSectionTag}>{sec.label}</span>
                            <span className={styles.reasonSectionContent}>{sec.content}</span>
                          </div>
                        ))
                      ) : (
                        <div className={styles.reasonFallbackText}>{fallbackText}</div>
                      )}
                    </div>
                  );
                })}
              </div>
            );
          })}
        </div>
      );
    }

    // 旧格式 fallback: 扁平 { name, reason } 数组
    if (message.recommendReasons && message.recommendReasons.length > 0) {
      return (
        <div className={styles.reasonsSection}>
          <div className={styles.reasonsTitle}>✨ 推荐理由</div>
          {message.recommendReasons.map((item, idx) => {
            const reason = item.reason || '';
            const sections = parseReasonSections(reason);
            const hasSections = sections.length > 0;
            const fallbackText = hasSections ? '' : stripArrangeAdvice(reason);
            if (!hasSections && !fallbackText) return null;
            return (
              <div key={idx} className={styles.reasonPoiBlock}>
                <div className={styles.reasonPoiName}>{item.name}</div>
                {hasSections ? (
                  sections.map((sec, sIdx) => (
                    <div key={sIdx} className={styles.reasonSectionRow}>
                      <span className={styles.reasonSectionTag}>{sec.label}</span>
                      <span className={styles.reasonSectionContent}>{sec.content}</span>
                    </div>
                  ))
                ) : (
                  <div className={styles.reasonFallbackText}>{fallbackText}</div>
                )}
              </div>
            );
          })}
        </div>
      );
    }

    // No data at all
    return null;
  };

  const renderMessageContent = (message: ChatMessage) => {
    // 推荐理由消息：只渲染推荐理由组件，不显示 __RECOMMEND_REASONS__
    if (message.role === 'assistant' && message.displayType === 'recommendReasons') {
      return renderRecommendReasons(message);
    }

    const content = message.content;

    // 系统消息（模式选择确认）特殊样式
    if (message.role === 'system') {
      return (
        <div className={styles.systemMessage}>
          <span className={styles.systemIcon}>✓</span>
          {content.replace('[ROUTE_PLANNER]: ', '')}
        </div>
      );
    }

    // 如果是 AI 消息且有解析结构，高亮关键字
    if (message.role === 'assistant' && message.parsedStructure) {
      const { highlights } = message.parsedStructure;
      const lines = content.split('\n');

      return (
        <>
          <div className={styles.messageText}>
            {lines.map((line, index) => {
              // 检查是否需要高亮
              const isHighlight = highlights.some(
                (h: string) => line.includes(h) || line.match(/Day\s*\d+/i) || line.includes('行程概览')
              );
              const isDayHeader = line.match(/Day\s*\d+|第\d+天|【Day\d+】/i);
              const isSummary = line.includes('为您规划了') || line.includes('行程概览');

              if (isSummary) {
                return (
                  <div key={index} className={styles.summaryLine}>
                    📋 {line}
                  </div>
                );
              }

              if (isDayHeader) {
                const dayNum = line.match(/Day\s*(\d+)|第(\d+)天|【Day(\d+)】/i);
                const day = dayNum ? parseInt(dayNum[1] || dayNum[2] || dayNum[3]) : null;
                const isActive = day === activeDay;

                return (
                  <div
                    key={index}
                    className={`${styles.dayHeader} ${isActive ? styles.dayHeaderActive : ''}`}
                    onClick={() => day && setActiveDay(isActive ? null : day)}
                  >
                    🗓️ {line}
                  </div>
                );
              }

              if (isHighlight) {
                return (
                  <div key={index} className={styles.highlightLine}>
                    {line}
                  </div>
                );
              }

              return (
                <div key={index} className={styles.normalLine}>
                  {line}
                </div>
              );
            })}
          </div>
        </>
      );
    }

    // 用户消息和普通 AI 消息直接显示
    // 移除 [ROUTE_PLANNER]: 前缀以美化显示
    const displayContent = content.replace(/\[ROUTE_PLANNER\]:\s*/g, '');
    return <div className={styles.messageText}>{displayContent}</div>;
  };

  /**
   * 渲染消息气泡
   */
  const renderMessage = (message: ChatMessage) => {
    const isUser = message.role === 'user';
    const isSystem = message.role === 'system';

    // 系统消息居中显示
    if (isSystem) {
      return (
        <div key={message.id} className={styles.systemMessageContainer}>
          {renderMessageContent(message)}
        </div>
      );
    }

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
          {renderMessageContent(message)}
          <div className={styles.messageTime}>
            {new Date(message.timestamp).toLocaleTimeString('zh-CN', {
              hour: '2-digit',
              minute: '2-digit',
            })}
          </div>
        </div>
      </div>
    );
  };

  /**
   * 渲染规划状态行（非气泡式轻量内联状态）
   * 只在规划进行中且已有用户消息后展示
   */
  const renderPlanningStatusInline = () => {
    if (!isPlanningActive) return null;

    const statusText = currentPlanningStatus || '正在整理路线...';
    const elapsed = formatElapsed(planningElapsedSeconds);
    const displayText = `正在思考 ${elapsed} · ${statusText}`;

    return (
      <div className={styles.planningStatusInline}>
        <span className={styles.statusSpinner} />
        <span className={styles.statusText}>{displayText}</span>
      </div>
    );
  };

  /**
   * 获取输入框占位符
   */
  const getInputPlaceholder = () => {
    if (planMode === 'planned') {
      return '请描述您的有序途经点...';
    }
    return '请描述您的出行需求...';
  };

  // v6: 推荐用例常驻显示，不因发送消息而消失
  const shouldShowQuickPrompts = true;
  // v6: "近期规划"在发送首条消息后消失。首次使用时即使无历史也显示固定高度空白栏。
  const shouldShowRecentHistories = !hasSentInSession;

  return (
    <div className={styles.chatPanel}>
      {/* 头部 */}
      <div className={styles.header}>
        <img 
          src="/ai-travel-logo.png" 
          alt="AI旅行助手" 
          className={styles.headerLogo}
        />
        <span className={styles.headerTitle}>AI 旅游助手</span>
        {onLoadHistory && (
          <button
            className={styles.historyBtn}
            onClick={() => setHistoryPanelOpen(!historyPanelOpen)}
            title="规划历史"
            aria-label="规划历史"
          >
            <History size={18} />
          </button>
        )}
        <button
          className={styles.sidebarToggleBtn}
          onClick={onToggleSidebar}
          title={isSidebarCollapsed ? '展开行程面板' : '折叠行程面板'}
        >
          <MenuOutlined />
        </button>
      </div>

      {/* 浮动历史面板 */}
      {historyPanelOpen && (
        <div className={styles.historyFloatPanel}>
          {recentHistories.length === 0 ? (
            <div className={styles.historyFloatEmpty}>暂无规划历史</div>
          ) : (
            recentHistories.slice(0, 20).map(h => (
              <div
                key={h.history_id}
                className={styles.historyFloatItem}
                onClick={() => {
                  onLoadHistory?.(h);
                  setHistoryPanelOpen(false);
                }}
              >
                <div className={styles.historyFloatBody}>
                  <div className={styles.historyFloatTitle}>{h.title || `${h.destination} ${h.days}日游`}</div>
                  <div className={styles.historyFloatMeta}>
                    {h.created_at ? new Date(h.created_at).toLocaleString('zh-CN', { month: '2-digit', day: '2-digit', hour: '2-digit', minute: '2-digit' }) : ''}
                    {' · '}
                    {h.summary?.poi_count || 0} 地点
                  </div>
                </div>
                <button
                  className={styles.historyFloatDelete}
                  onClick={(e) => {
                    e.stopPropagation();
                    onDeleteHistory?.(h.history_id);
                  }}
                  title="删除"
                  aria-label="删除"
                >
                  <Trash2 size={14} />
                </button>
              </div>
            ))
          )}
        </div>
      )}

      {/* 规划模式切换 */}
      <div className={styles.modeToggleWrapper} data-guide="mode-toggle">
        <div className={styles.modeToggleTrack}>
          <div
            className={`${styles.modeToggleSlider} ${
              planMode === 'planned' ? styles.modeToggleSliderRight : ''
            }`}
          />
          <Tooltip
            title={`适合还没有明确行程安排的情况。你可以用自然语言描述大概想法，例如“下午想在外滩附近随便逛逛，顺便找点好吃的”，系统会根据当前位置、兴趣偏好和时间余量，自动推荐一条轻量、灵活、可随时调整的探索路线。`}
            color="#262626"
            overlayStyle={{ maxWidth: 300 }}
            overlayInnerStyle={{ color: '#fff', backgroundColor: '#262626', fontWeight: 300 }}
            mouseEnterDelay={0.5}
          >
            <button
              className={`${styles.modeToggleOption} ${
                planMode === 'exploratory' ? styles.modeToggleOptionActive : ''
              }`}
              onClick={() => setPlanMode('exploratory')}
              disabled={isLoading}
            >
              自由探索
            </button>
          </Tooltip>
          <Tooltip
            title={`适合已经有明确目的地、时间段或必去地点的情况。你可以直接说明上午、下午、晚上分别想去哪里，或指定餐饮、交通、预算等要求，系统会按时间顺序组织 POI、餐饮和路线，并生成更稳定的完整行程安排。`}
            color="#262626"
            overlayStyle={{ maxWidth: 300 }}
            overlayInnerStyle={{ color: '#fff', backgroundColor: '#262626', fontWeight: 300 }}
            mouseEnterDelay={0.5}
          >
            <button
              className={`${styles.modeToggleOption} ${
                planMode === 'planned' ? styles.modeToggleOptionActive : ''
              }`}
              onClick={() => setPlanMode('planned')}
              disabled={isLoading}
            >
              精准规划
            </button>
          </Tooltip>
        </div>
      </div>

      {/* 消息列表 */}
      <div className={styles.messageList}>
        {visibleMessages.map(renderMessage)}

        {/* 规划状态行 — 非气泡轻量内联 */}
        {renderPlanningStatusInline()}

        {/* 错误消息 */}
        {error && (
          <div className={styles.errorMessage}>
            <span className={styles.errorIcon}>⚠️</span>
            <span>{error}</span>
          </div>
        )}

        {/* 近期历史框（欢迎语下方，未发送消息时显示，发送后消失） */}
        {shouldShowRecentHistories && (
          <div className={styles.recentHistoryBox} data-guide="recent-plans">
            <div className={styles.recentHistoryTitle}>近期规划</div>
            {recentHistories.length === 0 ? (
              <div className={styles.recentHistoryEmpty}>近期没有路线规划记录</div>
            ) : (
              recentHistories.slice(0, 5).map(h => (
                <div
                  key={h.history_id}
                  className={styles.recentHistoryItem}
                  onClick={() => onLoadHistory?.(h)}
                >
                  <div className={styles.recentHistoryItemBody}>
                    <div className={styles.recentHistoryItemTitle}>{h.title || `${h.destination} ${h.days}日游`}</div>
                    <div className={styles.recentHistoryItemMeta}>
                      {h.created_at ? new Date(h.created_at).toLocaleString('zh-CN', { month: '2-digit', day: '2-digit', hour: '2-digit', minute: '2-digit' }) : ''}
                      {' · '}
                      {h.summary?.poi_count || 0} 地点
                    </div>
                  </div>
                  <button
                    className={styles.recentHistoryDelete}
                    onClick={(e) => {
                      e.stopPropagation();
                      onDeleteHistory?.(h.history_id);
                    }}
                    title="删除"
                    aria-label="删除"
                  >
                    <Trash2 size={14} />
                  </button>
                </div>
              ))
            )}
          </div>
        )}
        <div ref={messagesEndRef} />
      </div>

      {/* 输入区域 */}
      <div className={styles.inputArea} data-guide="chat-input">
        <div className={styles.inputRow}>
          <button
            className={styles.clearBtn}
            onClick={clearChat}
            disabled={isLoading}
            title="清空对话"
            aria-label="清空对话"
          >
            <Trash2 size={18} />
          </button>
          <TextArea
            ref={inputRef}
            value={inputText}
            onChange={(e) => setInputText(e.target.value)}
            placeholder={getInputPlaceholder()}
            autoSize={{ minRows: 1, maxRows: 3 }}
            onKeyDown={handleKeyDown}
            className={styles.textInput}
            disabled={isLoading}
          />
          <button
            className={styles.sendBtn}
            onClick={handleSend}
            disabled={!inputText.trim() || isLoading}
            title="发送"
          >
            <SendOutlined />
          </button>
        </div>
        {/* 快捷测试案例（未发送消息时显示，按模式切换） */}
        {shouldShowQuickPrompts && (
          <div className={styles.quickPrompts} data-guide="quick-prompts">
            <div className={styles.quickPromptsTitle}>例如</div>
            <div className={styles.quickPromptsList}>
              {QUICK_PROMPTS_BY_MODE[planMode || 'exploratory'].map((prompt, idx) => (
                <button
                  key={idx}
                  className={styles.quickPromptBtn}
                  disabled={isLoading}
                  title={prompt}
                  onClick={() => {
                    setInputText(prompt);
                    requestAnimationFrame(() => inputRef.current?.focus?.());
                  }}
                >
                  {prompt}……
                </button>
              ))}
            </div>
          </div>
        )}
      </div>
    </div>
  );
};

export default ChatPanel;
