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

import React, { useState, useRef, useEffect, useMemo } from 'react';
import { SendOutlined, MenuOutlined } from '@ant-design/icons';
import { Trash2, History, Star, MessageCircle } from 'lucide-react';
import { Input, Tooltip, Modal as AntModal } from 'antd';
import { ChatMessage } from '@/hooks/useChat';
import { useRouteStore } from '@/store/routeStore';
import { useUserStore, type User } from '@/store/userStore';
import styles from './ChatPanel.module.css';

const { TextArea } = Input;

// v21: City-based example prompts (first 3 only)
const EXAMPLES_BY_CITY: Record<string, string[]> = {
  Beijing: [
    '我明天想去故宫玩一整天，帮我规划一下路线',
    '上午去王府井步行街逛逛，下午想去国贸，晚上找个好吃的地方',
    '想去奥林匹克公园逛一逛',
  ],
  Shanghai: [
    '我明天想去外滩玩一整天，帮我规划一下路线',
    '上午去南京路步行街逛逛，下午想去陆家嘴，晚上找个好吃的地方',
    '还有两个小时，我在杨浦滨江附近随便走走',
  ],
};

// Fallback examples (prompts 4-6, city-independent)
const FALLBACK_PROMPTS: string[] = [
  '待会儿下班，在附近找一家日料店，然后回家',
  '下班路上想顺便买点水果，再找个地方简单吃晚饭',
  '回家前想理个发，附近如果有不错的咖啡店也可以坐一会儿',
];

export function detectDepartureCity(user: User | null): 'Beijing' | 'Shanghai' {
  const homeLocation = user?.home_location;
  const homeAddress = user?.location?.home_address;
  const combined = [
    user?.city,
    user?.location?.city,
    homeLocation?.label,
    homeAddress?.name,
    homeAddress?.full_address,
  ].filter(Boolean).join(' ');

  if (/北京/.test(combined)) return 'Beijing';
  if (/上海/.test(combined)) return 'Shanghai';

  // Address result labels may contain only a POI name (for example "国贸").
  // In that case, use the saved route-departure coordinates.  These bounds
  // intentionally cover the supported Beijing/Shanghai search regions.
  const lng = Number(homeLocation?.lng ?? homeAddress?.lng ?? user?.location?.longitude);
  const lat = Number(homeLocation?.lat ?? homeAddress?.lat ?? user?.location?.latitude);
  if (Number.isFinite(lng) && Number.isFinite(lat)) {
    if (lng >= 115.4 && lng <= 117.7 && lat >= 39.3 && lat <= 41.2) return 'Beijing';
    if (lng >= 120.7 && lng <= 122.3 && lat >= 30.5 && lat <= 32.1) return 'Shanghai';
  }

  return 'Shanghai'; // default fallback
}

export function getQuickPrompts(user: User | null): string[] {
  const city = detectDepartureCity(user);
  const cityExamples = EXAMPLES_BY_CITY[city] || EXAMPLES_BY_CITY.Shanghai;
  return [...cityExamples, ...FALLBACK_PROMPTS];
}

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
  /** v18: 路线卡片点击回调 */
  onRouteCardSelect?: (snapshot: any) => void;
  /** v18: 路线卡片收藏回调 */
  onRouteCardFavorite?: (snapshot: any) => void;
  /** v22: 当前选中的路线 ID，用于高亮卡片 */
  activeRouteId?: string | null;
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
  onRouteCardSelect,
  onRouteCardFavorite,
  activeRouteId,
}) => {
  const [inputText, setInputText] = useState('');
  const [historyPanelOpen, setHistoryPanelOpen] = useState(false);
  const [feedbackOpen, setFeedbackOpen] = useState(false);
  const [feedbackSnapshot, setFeedbackSnapshot] = useState<any>(null);
  const [feedbackTitle, setFeedbackTitle] = useState('');
  const [feedbackDetail, setFeedbackDetail] = useState('');
  const messagesEndRef = useRef<HTMLDivElement>(null);
  // v21: Dynamic city-based quick prompts
  // The user profile is nested at state.user.  Subscribing to root-level
  // home_location/permanent_city never updated when SettingsModal saved.
  const departureUser = useUserStore((state) => state.user);
  const quickPrompts = useMemo(
    () => getQuickPrompts(departureUser),
    [departureUser],
  );
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

  const cleanReasonFragment = (text: string, maxLen = 24): string => {
    return String(text || '')
      .replace(/^这条路线/, '')
      .replace(/^让您/, '')
      .replace(/^接着/, '')
      .replace(/^随后/, '')
      .replace(/^最后/, '')
      .replace(/^然后/, '')
      .replace(/全程.*$/, '')
      .replace(/[。；;]+$/g, '')
      .trim()
      .slice(0, maxLen);
  };

  const pickReasonSentence = (sentences: string[], keywords: string[]): string => {
    return sentences.find(sentence => keywords.some(keyword => sentence.includes(keyword))) || '';
  };

  const formatPlainRouteReason = (reason: string): Array<{ label: string; content: string }> => {
    const cleaned = stripArrangeAdvice(reason)
      .replace(/\s+/g, '')
      .replace(/。+/g, '。');
    const sentences = cleaned
      .split(/[。；;]/)
      .map(sentence => sentence.trim())
      .filter(Boolean);
    if (sentences.length === 0) return [];

    const lines: Array<{ label: string; content: string }> = [];
    const morningSentence = sentences[0] || '';
    const mealSentence = pickReasonSentence(sentences, ['午餐', '中餐', '品尝', '用餐', '吃', '餐厅', '美食']);
    const afternoonSentence =
      [...sentences].reverse().find(sentence => sentence !== mealSentence && sentence !== morningSentence) || '';

    const startMatch = morningSentence.match(/从(.{2,14}?)(?:开始|出发|起步)/);
    const morningStops = [
      startMatch?.[1],
      morningSentence.includes('苏州河') ? '苏州河' : '',
      morningSentence.includes('外滩源') ? '外滩源' : '',
    ].filter(Boolean).slice(0, 2);
    const morningValue = morningSentence.includes('摄影') || morningSentence.includes('拍')
      ? (morningSentence.includes('陆家嘴') ? '拍陆家嘴机位' : '拍照打卡')
      : cleanReasonFragment(morningSentence, 14);
    lines.push({
      label: '上午',
      content: `${morningStops.length ? `${morningStops.join('-')}，` : ''}${morningValue}`.slice(0, 28),
    });

    if (mealSentence) {
      const restaurantMatch = mealSentence.match(/在(.{2,24}?)(?:品尝|用餐|吃|享用|补充)/);
      const restaurant = restaurantMatch?.[1]?.replace(/^.*至/, '').trim();
      let mealValue = '补充能量';
      if (/意式|意大利|Mozzarella/i.test(mealSentence)) mealValue = '品尝意式美食';
      else if (mealSentence.includes('火锅')) mealValue = '兼顾火锅口味';
      else if (mealSentence.includes('烧烤')) mealValue = '兼顾烧烤口味';
      else if (mealSentence.includes('素食')) mealValue = '兼顾清淡素食';
      lines.push({
        label: '中餐',
        content: `${restaurant ? `${restaurant}，` : ''}${mealValue}`.slice(0, 28),
      });
    }

    if (afternoonSentence) {
      const afternoonStops = [
        afternoonSentence.includes('外白渡桥') ? '外白渡桥' : '',
        afternoonSentence.includes('外滩观景台') ? '外滩观景台' : (afternoonSentence.includes('外滩') ? '外滩' : ''),
        afternoonSentence.includes('陆家嘴') ? '陆家嘴' : '',
      ].filter(Boolean).slice(0, 2);
      let afternoonValue = cleanReasonFragment(afternoonSentence, 14);
      if (afternoonSentence.includes('万国建筑群')) afternoonValue = '赏万国建筑群';
      else if (afternoonSentence.includes('天际线')) afternoonValue = '看浦东天际线';
      else if (afternoonSentence.includes('历史')) afternoonValue = '感受历史街景';
      lines.push({
        label: '下午',
        content: `${afternoonStops.length ? `${afternoonStops.join('-')}，` : ''}${afternoonValue}`.slice(0, 28),
      });
    }

    return lines
      .filter(line => line.content)
      .slice(0, 3);
  };

  const normalizeReasonLines = (reason: string): Array<{ label: string; content: string }> => {
    const rawLines = reason
      .split('\n')
      .map(line => line.trim())
      .filter(Boolean);
    const sourceLines = rawLines.length >= 2
      ? rawLines
      : reason.split(/[。；;]/).map(line => line.trim()).filter(Boolean);

    const structured = sourceLines
      .map(line => {
        const colonIdx = line.search(/[：:]/);
        if (colonIdx <= 0) return null;
        return {
          label: cleanReasonFragment(line.slice(0, colonIdx), 6),
          content: cleanReasonFragment(line.slice(colonIdx + 1), 28),
        };
      })
      .filter((line): line is { label: string; content: string } => Boolean(line?.label && line?.content));

    const lines = structured.length > 0 ? structured : formatPlainRouteReason(reason);
    const capped: Array<{ label: string; content: string }> = [];
    let total = 0;
    for (const line of lines) {
      const label = line.label.slice(0, 6);
      const remaining = Math.max(0, 70 - total - label.length - 1);
      if (remaining <= 0) break;
      const content = line.content.slice(0, Math.min(28, remaining));
      if (!content) continue;
      capped.push({ label, content });
      total += label.length + content.length + 1;
    }
    return capped.slice(0, 4);
  };

  const getRouteMessageId = (message: ChatMessage): string => {
    const snapshot: any = message.routeSnapshot || {};
    return String(
      snapshot.__active_route_id
      || snapshot.route_hash
      || snapshot.title
      || message.requestId
      || message.parentUserMessageId
      || message.id
      || ''
    );
  };

  /**
   * 从 routeStore.currentPlan 中提取推荐理由
   */
  /** v18: 路线卡片推送 — 替代推荐理由长文本 */
  const renderRoutePushCard = (message: ChatMessage) => {
    const snapshot = message.routeSnapshot;
    const mapData = snapshot?.map_route_data || message.routeData;
    const markers = Array.isArray(mapData?.markers) ? mapData.markers : [];
    const poiCount =
      snapshot?.summary?.poi_count
      || markers.filter((m: any) => m.type !== 'candidate' && m.kind !== 'hint').length;

    const statsText = message.routeCardSubtitle || (message as any).statsText || '';

    const handleClick = () => {
      if (snapshot) {
        onRouteCardSelect?.({
          ...snapshot,
          __active_route_id: getRouteMessageId(message),
        });
      } else if (message.routeData) {
        onRouteChange?.(message.routeData);
      }
    };

    return (
      <div className={styles.routePushGroup}>
        <div role="button" tabIndex={0} className={styles.routePushCard} onClick={handleClick} onKeyDown={(e) => { if (e.key === 'Enter' || e.key === ' ') handleClick(); }}>
          <div className={styles.routePushOverlay} />
          <div className={styles.routePushContent}>
            <div className={styles.routePushActions}>
              <button type="button" className={styles.routePushIconBtn} title="反馈" onClick={(e) => { e.stopPropagation(); setFeedbackSnapshot(snapshot); setFeedbackOpen(true); }}>
                <MessageCircle size={16} />
              </button>
              <button type="button" className={styles.routePushIconBtn} title="收藏路线" onClick={(e) => { e.stopPropagation(); onRouteCardFavorite?.(snapshot); }}>
                <Star size={16} />
              </button>
            </div>
            <div className={styles.routePushKicker}>路线已生成</div>
            <div className={styles.routePushTitle}>{message.routeCardTitle || '路线规划'}</div>
            <div className={styles.routePushMeta}>
              <span>{poiCount > 0 ? `${poiCount} 个地点` : '点击查看路线'}</span>
              {statsText && <span className={styles.routePushStats}>{statsText}</span>}
            </div>
          </div>
        </div>
        {renderRouteRecReason(message)}
      </div>
    );
  };

  const renderRouteRecReason = (message: ChatMessage) => {
    const reason =
      message.routeData?.route_recommend_reason?.trim() ||
      message.routeSnapshot?.route_data?.route_recommend_reason?.trim() ||
      '';
    if (!reason) return null;

    const capped = normalizeReasonLines(reason);
    if (capped.length === 0) return null;

    return (
      <div className={styles.routeRecReason}>
        <div className={styles.routeRecReasonTitle}>为什么推荐</div>
        <div className={styles.routeRecReasonList}>
          {capped.map((line, i) => {
            return (
              <div key={i} className={styles.routeRecReasonLine}>
                <strong className={styles.routeRecReasonBold}>{line.label}：</strong>
                {line.content}
              </div>
            );
          })}
        </div>
      </div>
    );
  };

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
          {(message as any).statsText && (
            <div className={styles.statsText}>{(message as any).statsText}</div>
          )}
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
          {(message as any).statsText && (
            <div className={styles.statsText}>{(message as any).statsText}</div>
          )}
        </div>
      );
    }

    // No data at all
    return null;
  };

  const renderMessageContent = (message: ChatMessage) => {
    // v18: 推荐理由消息 → 渲染路线卡片（内含推荐理由）
    if (message.role === 'assistant' && message.displayType === 'recommendReasons') {
      return renderRoutePushCard(message);
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

    // v22: Check if this message's route is the active/highlighted one
    const _routeId = getRouteMessageId(message);
    const _isActive = activeRouteId && _routeId && activeRouteId === _routeId;

    return (
      <div
        key={message.id}
        className={`${styles.messageBubble} ${isUser ? styles.userBubble : styles.aiBubble} ${_isActive ? styles.messageBubbleActive : ''}`}
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
  const getInputPlaceholder = () => '请描述您的出行需求...';

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
              {quickPrompts.map((prompt, idx) => (
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

      {/* v18: 反馈弹窗 */}
      <AntModal
        title="路线反馈"
        open={feedbackOpen}
        onCancel={() => { setFeedbackOpen(false); setFeedbackTitle(''); setFeedbackDetail(''); }}
        footer={null}
        width={400}
        centered
      >
        <div style={{ display: 'flex', flexDirection: 'column', gap: 12 }}>
          <Input
            placeholder="问题概括（如：路线太远、缺少某个地点）"
            value={feedbackTitle}
            onChange={(e) => setFeedbackTitle(e.target.value)}
          />
          <Input.TextArea
            rows={4}
            placeholder="详细描述您的问题或建议"
            value={feedbackDetail}
            onChange={(e) => setFeedbackDetail(e.target.value)}
          />
          <div className={styles.feedbackUploadBox}>
            <span style={{ fontSize: 24, color: '#ccc' }}>+</span>
            <span style={{ fontSize: 12, color: '#aaa' }}>上传截图</span>
          </div>
          <div style={{ display: 'flex', gap: 8, justifyContent: 'flex-end' }}>
            <button type="button" className={styles.routePushIconBtn} onClick={() => { setFeedbackOpen(false); setFeedbackTitle(''); setFeedbackDetail(''); }}>取消</button>
            <button type="button" className={styles.submitBtn} onClick={() => { message.success('反馈已提交，感谢！'); setFeedbackOpen(false); setFeedbackTitle(''); setFeedbackDetail(''); }}>提交反馈</button>
          </div>
        </div>
      </AntModal>
    </div>
  );
};

export default ChatPanel;
