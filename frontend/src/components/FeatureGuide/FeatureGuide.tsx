/**
 * FeatureGuide — DOM 锚点式功能指引覆盖层 (v3)
 * v3: 折线引线 + 小高亮框 + 卡片避让 + 关键词加粗
 */
import React, { useEffect, useState, useCallback, useRef } from 'react';
import styles from './FeatureGuide.module.css';

type GuidePlacement = 'right' | 'left' | 'center-map';

interface Step {
  target: string;
  title: string;
  text: string;
  placement?: GuidePlacement;
  highlights?: string[];
}

const STEPS: Step[] = [
  {
    target: 'mode-toggle',
    placement: 'right',
    title: '选择规划方式',
    text: '自由探索适合"我还没有明确目的地，想让系统帮我找一条舒服路线"；精准规划适合"我已经知道要做几件事，想按顺序安排"。先选模式，再把想法告诉我，我们一起把路线揉顺。',
    highlights: ['自由探索', '精准规划', '先选模式'],
  },
  {
    target: 'recent-plans',
    placement: 'right',
    title: '近期规划',
    text: '这里会显示最近生成过的路线，方便快速回看。第一次使用时如果还没有记录，会保留一个空白栏提示"近期没有路线规划记录"；发送第一条需求后，这块会收起，之后可通过历史入口访问。',
    highlights: ['近期规划', '路线', '历史入口'],
  },
  {
    target: 'chat-input',
    placement: 'right',
    title: '对话与示例',
    text: '下方可以清除当前对话、发送你的出行需求，也可以点推荐示例快速试用。你可以直接说自然语言，不需要整理成表格。',
    highlights: ['清除当前对话', '发送', '推荐示例'],
  },
  {
    target: 'user-menu',
    placement: 'left',
    title: '游客与个人设置',
    text: '点击这里可以访问用户信息、个人收藏和历史记录。游客首次进入时会默认用设备位置作为常住地址，也可以在"我的设置"里手动修改。',
    highlights: ['用户信息', '个人收藏', '历史记录', '常住地址'],
  },
  {
    target: 'itinerary-sidebar',
    placement: 'left',
    title: '行程概览',
    text: '路线生成后，右侧会出现行程概览。这里会展示地点顺序、推荐理由、路线分段和可查看的地点信息。',
    highlights: ['行程概览', '地点顺序', '推荐理由', '路线分段'],
  },
  {
    target: 'map-area',
    placement: 'center-map',
    title: '地图路线与交互',
    text: '路线结果会呈现在中央地图。黄色点是最终路线点，蓝色点是备选点。点击地点卡片后可以替换、删除或增加，交互结果会被记录，用于后续更贴合你的个性化推荐。',
    highlights: ['黄色点', '蓝色点', '替换', '删除', '增加', '个性化推荐'],
  },
];

interface Rect {
  top: number;
  left: number;
  width: number;
  height: number;
  right: number;
  bottom: number;
}

function toRect(r: DOMRect): Rect {
  return { top: r.top, left: r.left, width: r.width, height: r.height, right: r.right, bottom: r.bottom };
}

function makeRect(top: number, left: number, width: number, height: number): Rect {
  return { top, left, width, height, right: left + width, bottom: top + height };
}

interface LinePoint {
  x: number;
  y: number;
}

interface StepLayout {
  idx: number;
  targetRect: Rect | null;
  cardTop: number;
  cardLeft: number;
  cardWidth: number;
  cardHeight: number;
  connectorPoints: LinePoint[];
}

const FALLBACK_POSITIONS: Record<string, Rect> = {
  'mode-toggle': makeRect(120, 24, 300, 48),
  'recent-plans': makeRect(200, 24, 300, 120),
  'chat-input': makeRect(420, 24, 300, 80),
  'user-menu': makeRect(16, 780, 160, 40),
  'itinerary-sidebar': makeRect(80, 1080, 300, 400),
  'map-area': makeRect(160, 400, 600, 420),
};

const CARD_WIDTH = 350;
const CARD_HEIGHT = 128;
const CALLOUT_GAP = 36;
const SAFE_MARGIN = 16;
const HEADER_OFFSET = 72;

function clamp(value: number, min: number, max: number): number {
  return Math.max(min, Math.min(max, value));
}

function layoutRect(l: StepLayout): Rect {
  return makeRect(l.cardTop, l.cardLeft, l.cardWidth, l.cardHeight);
}

function intersects(a: Rect, b: Rect): boolean {
  return !(a.right < b.left || a.left > b.right || a.bottom < b.top || a.top > b.bottom);
}

function resolveVerticalCollisions(items: StepLayout[], viewportHeight: number): void {
  if (items.length === 0) return;
  const sorted = [...items].sort((a, b) => a.cardTop - b.cardTop);
  let cursor = HEADER_OFFSET;
  for (const item of sorted) {
    item.cardTop = Math.max(item.cardTop, cursor);
    cursor = item.cardTop + item.cardHeight + 18;
  }
  const last = sorted[sorted.length - 1];
  const overflow = last.cardTop + last.cardHeight - (viewportHeight - 96);
  if (overflow > 0) {
    for (const item of sorted) {
      item.cardTop = clamp(item.cardTop - overflow, HEADER_OFFSET, viewportHeight - item.cardHeight - 96);
    }
  }
}

/** 从矩形边缘找到离给定点最近的边点 */
function edgePointToward(rect: Rect, point: LinePoint): LinePoint {
  const cx = rect.left + rect.width / 2;
  const cy = rect.top + rect.height / 2;
  const dx = point.x - cx;
  const dy = point.y - cy;

  if (Math.abs(dx) / rect.width > Math.abs(dy) / rect.height) {
    return { x: dx > 0 ? rect.right : rect.left, y: clamp(point.y, rect.top, rect.bottom) };
  }
  return { x: clamp(point.x, rect.left, rect.right), y: dy > 0 ? rect.bottom : rect.top };
}

/** 折线：目标框边缘 → badge 圆点中心 */
function buildConnector(targetRect: Rect, cardLeft: number, cardTop: number): { points: LinePoint[] } {
  const badgeCenter = { x: cardLeft + 14, y: cardTop + 14 };
  const start = edgePointToward(targetRect, badgeCenter);
  const midX = start.x + (badgeCenter.x - start.x) * 0.55;

  return {
    points: [
      start,
      { x: midX, y: start.y },
      { x: midX, y: badgeCenter.y },
      badgeCenter,
    ],
  };
}

/** keyword 加粗渲染（纯字符串 split，不用 dangerouslySetInnerHTML） */
function renderHighlightedText(text: string, highlights: string[]): React.ReactNode {
  if (!highlights || highlights.length === 0) return text;
  // Build a regex from sorted highlights (longest first to avoid partial match issues)
  const sorted = [...highlights].sort((a, b) => b.length - a.length);
  const escaped = sorted.map(h => h.replace(/[.*+?^${}()|[\]\\]/g, '\\$&'));
  const pattern = new RegExp(`(${escaped.join('|')})`, 'g');
  const parts = text.split(pattern);
  return parts.map((part, i) => {
    if (sorted.includes(part)) {
      return <strong key={i}>{part}</strong>;
    }
    return part;
  });
}

interface FeatureGuideProps {
  open: boolean;
  onClose: () => void;
}

export const FeatureGuide: React.FC<FeatureGuideProps> = ({ open, onClose }) => {
  const [layouts, setLayouts] = useState<StepLayout[]>([]);
  const rafRef = useRef<number>(0);

  const getTargetRectRaw = useCallback((target: string): Rect | null => {
    const el = document.querySelector(`[data-guide="${target}"]`) as HTMLElement | null;
    if (!el) return null;
    return toRect(el.getBoundingClientRect());
  }, []);

  /** 6 号只框地图中央子区域，避免超大框覆盖左侧面板 */
  const getGuideTargetRect = useCallback((step: Step): Rect | null => {
    const raw = getTargetRectRaw(step.target) || FALLBACK_POSITIONS[step.target] || null;
    if (!raw) return null;

    if (step.target === 'map-area') {
      const width = Math.min(420, raw.width * 0.36);
      const height = Math.min(280, raw.height * 0.40);
      const left = raw.left + raw.width * 0.44 - width / 2;
      const top = raw.top + raw.height * 0.48 - height / 2;
      return makeRect(top, left, width, height);
    }

    return raw;
  }, [getTargetRectRaw]);

  const computeLayouts = useCallback(() => {
    const vw = window.innerWidth;
    const vh = window.innerHeight;
    const isMobile = vw <= 768;

    if (isMobile) {
      setLayouts(STEPS.map((_, idx) => ({
        idx,
        targetRect: null,
        cardTop: 0,
        cardLeft: 0,
        cardWidth: CARD_WIDTH,
        cardHeight: CARD_HEIGHT,
        connectorPoints: [],
      })));
      return;
    }

    // v3: use getGuideTargetRect (smaller box for map)
    const raw: StepLayout[] = STEPS.map((step, idx) => {
      const targetRect = getGuideTargetRect(step);
      if (!targetRect) {
        return {
          idx,
          targetRect: null,
          cardTop: 100 + idx * 140,
          cardLeft: 24,
          cardWidth: CARD_WIDTH,
          cardHeight: CARD_HEIGHT,
          connectorPoints: [],
        };
      }

      let cardLeft: number;
      let cardTop: number;
      const placement = step.placement || 'right';
      const targetCenterY = targetRect.top + targetRect.height / 2;

      if (placement === 'center-map') {
        // v3: shift left by 120px and down by 12px to avoid step 5 overlap
        cardLeft = targetRect.left + targetRect.width / 2 - CARD_WIDTH / 2 - 120;
        cardTop = targetRect.top + targetRect.height / 2 - CARD_HEIGHT / 2 + 12;
        cardLeft = clamp(cardLeft, SAFE_MARGIN, vw - CARD_WIDTH - SAFE_MARGIN);
        cardTop = clamp(cardTop, HEADER_OFFSET, vh - CARD_HEIGHT - 96);
      } else if (placement === 'left') {
        cardLeft = targetRect.left - CARD_WIDTH - CALLOUT_GAP;
        if (cardLeft < SAFE_MARGIN) cardLeft = SAFE_MARGIN;
        cardTop = targetCenterY - CARD_HEIGHT / 2;
        cardTop = clamp(cardTop, HEADER_OFFSET, vh - CARD_HEIGHT - 96);
      } else {
        cardLeft = targetRect.right + CALLOUT_GAP;
        if (cardLeft + CARD_WIDTH > vw - SAFE_MARGIN) cardLeft = vw - CARD_WIDTH - SAFE_MARGIN;
        cardTop = targetCenterY - CARD_HEIGHT / 2;
        cardTop = clamp(cardTop, HEADER_OFFSET, vh - CARD_HEIGHT - 96);
      }

      return {
        idx,
        targetRect,
        cardTop,
        cardLeft,
        cardWidth: CARD_WIDTH,
        cardHeight: CARD_HEIGHT,
        connectorPoints: [],
      };
    });

    // Group for collision avoidance
    const leftGroup = raw.filter(l => STEPS[l.idx]?.placement === 'right' && l.targetRect);
    const rightGroup = raw.filter(l => STEPS[l.idx]?.placement === 'left' && l.targetRect);

    resolveVerticalCollisions(leftGroup, vh);
    resolveVerticalCollisions(rightGroup, vh);

    // v3: center-map overlap detection with right group
    const centerLayout = raw.find(l => STEPS[l.idx]?.placement === 'center-map');
    if (centerLayout && centerLayout.targetRect) {
      for (const other of rightGroup) {
        if (other.targetRect && intersects(layoutRect(centerLayout), layoutRect(other))) {
          centerLayout.cardLeft = clamp(
            other.cardLeft - centerLayout.cardWidth - 44,
            SAFE_MARGIN,
            vw - centerLayout.cardWidth - SAFE_MARGIN,
          );
        }
      }
    }

    // Build polyline connectors after final positions
    for (const l of raw) {
      if (!l.targetRect) continue;
      const conn = buildConnector(l.targetRect, l.cardLeft, l.cardTop);
      l.connectorPoints = conn.points;
    }

    setLayouts(raw);
  }, [getGuideTargetRect]);

  // Recompute on resize/scroll
  useEffect(() => {
    if (!open) return;
    computeLayouts();
    const onResize = () => {
      cancelAnimationFrame(rafRef.current);
      rafRef.current = requestAnimationFrame(computeLayouts);
    };
    const onScroll = () => {
      cancelAnimationFrame(rafRef.current);
      rafRef.current = requestAnimationFrame(computeLayouts);
    };
    window.addEventListener('resize', onResize);
    window.addEventListener('scroll', onScroll, true);
    return () => {
      window.removeEventListener('resize', onResize);
      window.removeEventListener('scroll', onScroll, true);
      cancelAnimationFrame(rafRef.current);
    };
  }, [open, computeLayouts]);

  // Lock body scroll
  useEffect(() => {
    if (!open) return;
    const prev = document.body.style.overflow;
    document.body.style.overflow = 'hidden';
    return () => { document.body.style.overflow = prev; };
  }, [open]);

  // Escape to close
  useEffect(() => {
    if (!open) return;
    const onKey = (e: KeyboardEvent) => {
      if (e.key === 'Escape') onClose();
    };
    window.addEventListener('keydown', onKey);
    return () => window.removeEventListener('keydown', onKey);
  }, [open, onClose]);

  const [mobile, setMobile] = useState(false);
  useEffect(() => {
    const check = () => setMobile(window.innerWidth <= 768);
    check();
    window.addEventListener('resize', check);
    return () => window.removeEventListener('resize', check);
  }, []);

  if (!open) return null;

  const effectiveMobile = mobile;

  return (
    <div className={styles.overlay}>
      {/* Spotlights */}
      {!effectiveMobile && layouts.map((l) => {
        if (!l.targetRect) return null;
        return (
          <div
            key={`spotlight-${l.idx}`}
            className={styles.spotlight}
            style={{
              top: l.targetRect.top - 3,
              left: l.targetRect.left - 3,
              width: l.targetRect.width + 6,
              height: l.targetRect.height + 6,
            }}
          />
        );
      })}

      {/* SVG polyline connectors */}
      {!effectiveMobile && (
        <svg className={styles.connectorLayer} aria-hidden="true">
          {layouts.map((l) => {
            if (!l.targetRect || l.connectorPoints.length === 0) return null;
            return (
              <polyline
                key={`connector-${l.idx}`}
                className={styles.connector}
                points={l.connectorPoints.map(p => `${p.x},${p.y}`).join(' ')}
              />
            );
          })}
        </svg>
      )}

      {/* Step callouts */}
      <div className={styles.stepsContainer}>
        {STEPS.map((step, idx) => {
          const layout = layouts[idx];
          const style: React.CSSProperties = effectiveMobile
            ? {}
            : layout && layout.targetRect
              ? {
                  position: 'absolute' as const,
                  top: layout.cardTop,
                  left: layout.cardLeft,
                  width: layout.cardWidth,
                  minHeight: layout.cardHeight,
                }
              : {
                  position: 'absolute' as const,
                  top: 100 + idx * 140,
                  left: 24,
                  width: CARD_WIDTH,
                  minHeight: CARD_HEIGHT,
                };

          return (
            <div key={step.target} className={styles.step} style={style}>
              <div className={styles.badge}>{idx + 1}</div>
              <div className={styles.callout}>
                <p className={styles.title}>{step.title}</p>
                <p className={styles.text}>
                  {renderHighlightedText(step.text, step.highlights || [])}
                </p>
              </div>
            </div>
          );
        })}
      </div>

      <button className={styles.closeButton} onClick={onClose} type="button">
        开始规划吧~
      </button>
    </div>
  );
};

export default FeatureGuide;
