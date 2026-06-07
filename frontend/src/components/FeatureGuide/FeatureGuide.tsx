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
const DEFAULT_CARD_HEIGHT = 128;
const CALLOUT_GAP = 36;
const SAFE_MARGIN = 16;
const HEADER_OFFSET = 72;
const COLLISION_GAP = 28;
const MAX_COLLISION_ROUNDS = 12;

function clamp(value: number, min: number, max: number): number {
  return Math.max(min, Math.min(max, value));
}

function layoutRect(l: StepLayout): Rect {
  return makeRect(l.cardTop, l.cardLeft, l.cardWidth, l.cardHeight);
}

function intersects(a: Rect, b: Rect): boolean {
  return !(a.right < b.left || a.left > b.right || a.bottom < b.top || a.top > b.bottom);
}

/** 带安全间距的矩形，用于碰撞检测 */
function paddedLayoutRect(l: StepLayout, gap = COLLISION_GAP): Rect {
  const rect = layoutRect(l);
  return makeRect(
    rect.top - gap / 2,
    rect.left - gap / 2,
    rect.width + gap,
    rect.height + gap,
  );
}

function hasAnyCollision(items: StepLayout[]): boolean {
  const visible = items.filter(l => l.targetRect);
  for (let i = 0; i < visible.length; i++) {
    for (let j = i + 1; j < visible.length; j++) {
      if (intersects(paddedLayoutRect(visible[i]), paddedLayoutRect(visible[j]))) {
        return true;
      }
    }
  }
  return false;
}

/** 全局碰撞避让：所有 placement 统一参与，返回 true 表示碰撞已解决 */
function resolveAllCollisions(items: StepLayout[], vw: number, vh: number): boolean {
  const sorted = items.filter(l => l.targetRect);
  if (sorted.length <= 1) return true;

  for (let round = 0; round < MAX_COLLISION_ROUNDS; round++) {
    let moved = false;
    sorted.sort((a, b) => a.cardTop - b.cardTop);

    for (let i = 0; i < sorted.length; i++) {
      const a = sorted[i];
      if (!a.targetRect) continue;
      for (let j = i + 1; j < sorted.length; j++) {
        const b = sorted[j];
        if (!b.targetRect) continue;
        if (!intersects(paddedLayoutRect(a), paddedLayoutRect(b))) continue;

        // 优先：b 下移到 a 下方
        const below = a.cardTop + a.cardHeight + COLLISION_GAP;
        if (below + b.cardHeight <= vh - SAFE_MARGIN) {
          b.cardTop = below;
          moved = true;
          continue;
        }
        // 其次：b 上移到 a 上方
        const above = a.cardTop - b.cardHeight - COLLISION_GAP;
        if (above >= HEADER_OFFSET) {
          b.cardTop = above;
          moved = true;
          continue;
        }
        // 再次：a 上移
        const aAbove = b.cardTop - a.cardHeight - COLLISION_GAP;
        if (aAbove >= HEADER_OFFSET) {
          a.cardTop = aAbove;
          moved = true;
          continue;
        }
        // 都推不动：center-map 尝试水平偏移
        const aPlace = STEPS[a.idx]?.placement;
        const bPlace = STEPS[b.idx]?.placement;
        if (aPlace === 'center-map') {
          a.cardLeft = clamp(
            b.cardLeft + b.cardWidth + COLLISION_GAP,
            SAFE_MARGIN,
            vw - a.cardWidth - SAFE_MARGIN,
          );
          moved = true;
        } else if (bPlace === 'center-map') {
          b.cardLeft = clamp(
            a.cardLeft + a.cardWidth + COLLISION_GAP,
            SAFE_MARGIN,
            vw - b.cardWidth - SAFE_MARGIN,
          );
          moved = true;
        }
      }
    }
    if (!moved) break;
  }
  return !hasAnyCollision(items);
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
  return buildConnectorToPoint(targetRect, badgeCenter);
}

/** 折线：目标框边缘 → 任意点 */
function buildConnectorToPoint(targetRect: Rect, badgeCenter: LinePoint): { points: LinePoint[] } {
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

/** 折线：右侧绕行 — 从目标框底部出发，沿右侧空白区向下，再左转连 badge（用于右上角用户菜单等） */
function buildRightBiasedConnector(
  targetRect: Rect,
  badgeCenter: LinePoint,
  viewportWidth: number,
): { points: LinePoint[] } {
  const start = {
    x: targetRect.left + targetRect.width / 2,
    y: targetRect.bottom,
  };
  const laneX = clamp(
    targetRect.left + targetRect.width / 2,
    targetRect.right + 24,
    viewportWidth - 72,
  );
  const laneY = Math.max(start.y + 28, badgeCenter.y);
  return {
    points: [
      start,
      { x: laneX, y: start.y },
      { x: laneX, y: laneY },
      { x: badgeCenter.x, y: laneY },
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
  const [forceStacked, setForceStacked] = useState(false);
  const rafRef = useRef<number>(0);
  const stepRefs = useRef<(HTMLDivElement | null)[]>([]);
  const measuredHeights = useRef<number[]>([]);

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

  function makeStackedLayouts(): StepLayout[] {
    return STEPS.map((step, idx) => {
      const targetRect = getGuideTargetRect(step);
      return {
        idx,
        targetRect,
        cardTop: 0,
        cardLeft: 0,
        cardWidth: CARD_WIDTH,
        cardHeight: measuredHeights.current[idx] || DEFAULT_CARD_HEIGHT,
        connectorPoints: [],
      };
    });
  }

  const stackedSet = useCallback(() => {
    setLayouts(makeStackedLayouts());
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [getGuideTargetRect]);

  const computeLayouts = useCallback(() => {
    const vw = window.innerWidth;
    const vh = window.innerHeight;
    const isNarrow = vw < 1180 || vh < 760;
    const isMobile = vw <= 768;

    if (isMobile || isNarrow) {
      setForceStacked(true);
      stackedSet();
      return;
    }

    setForceStacked(false);

    // 使用实测高度或默认值
    const raw: StepLayout[] = STEPS.map((step, idx) => {
      const targetRect = getGuideTargetRect(step);
      const cardHeight = measuredHeights.current[idx] || DEFAULT_CARD_HEIGHT;

      if (!targetRect) {
        return {
          idx,
          targetRect: null,
          cardTop: 100 + idx * 140,
          cardLeft: 24,
          cardWidth: CARD_WIDTH,
          cardHeight,
          connectorPoints: [],
        };
      }

      let cardLeft: number;
      let cardTop: number;
      const placement = step.placement || 'right';
      const targetCenterY = targetRect.top + targetRect.height / 2;

      if (placement === 'center-map') {
        cardLeft = targetRect.left + targetRect.width / 2 - CARD_WIDTH / 2 - 120;
        cardTop = targetRect.top + targetRect.height / 2 - cardHeight / 2 + 12;
        cardLeft = clamp(cardLeft, SAFE_MARGIN, vw - CARD_WIDTH - SAFE_MARGIN);
        cardTop = clamp(cardTop, HEADER_OFFSET, vh - cardHeight - 96);
      } else if (placement === 'left') {
        cardLeft = targetRect.left - CARD_WIDTH - CALLOUT_GAP;
        if (cardLeft < SAFE_MARGIN) cardLeft = SAFE_MARGIN;
        cardTop = targetCenterY - cardHeight / 2;
        cardTop = clamp(cardTop, HEADER_OFFSET, vh - cardHeight - 96);
      } else {
        cardLeft = targetRect.right + CALLOUT_GAP;
        if (cardLeft + CARD_WIDTH > vw - SAFE_MARGIN) cardLeft = vw - CARD_WIDTH - SAFE_MARGIN;
        cardTop = targetCenterY - cardHeight / 2;
        cardTop = clamp(cardTop, HEADER_OFFSET, vh - cardHeight - 96);
      }

      return {
        idx,
        targetRect,
        cardTop,
        cardLeft,
        cardWidth: CARD_WIDTH,
        cardHeight,
        connectorPoints: [],
      };
    });

    // 全局碰撞避让
    const resolved = resolveAllCollisions(raw, vw, vh);

    if (!resolved) {
      // 碰撞无法解决 → 降级到纵向 stacked 模式
      setForceStacked(true);
      stackedSet();
      return;
    }

    // 碰撞解决后重新生成 connector points
    for (const l of raw) {
      if (!l.targetRect) continue;
      // 第 6 项地图中心说明不画引线；第 4 项用户菜单用右侧绕行
      if (l.idx === 5) {
        l.connectorPoints = [];
        continue;
      }
      const conn = l.idx === 3
        ? buildRightBiasedConnector(l.targetRect, { x: l.cardLeft + 14, y: l.cardTop + 14 }, window.innerWidth)
        : buildConnector(l.targetRect, l.cardLeft, l.cardTop);
      l.connectorPoints = conn.points;
    }

    setLayouts(raw);
  }, [getGuideTargetRect, stackedSet]);

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

  // Measure card heights after render + generate stacked connectors
  useEffect(() => {
    if (!open || layouts.length === 0) return;
    const raf = requestAnimationFrame(() => {
      const heights: number[] = [];
      stepRefs.current.forEach((el, i) => {
        heights[i] = el ? el.getBoundingClientRect().height : DEFAULT_CARD_HEIGHT;
      });
      const changed = heights.some((h, i) => h !== (measuredHeights.current[i] || DEFAULT_CARD_HEIGHT));
      if (changed) {
        measuredHeights.current = heights;
        computeLayouts();
      }

      // 桌面 stacked 模式补充 connector 折线
      const stackedNow = window.innerWidth <= 768 || window.innerWidth < 1180 || window.innerHeight < 760 || forceStacked;
      if (stackedNow && window.innerWidth > 768) {
        setLayouts(prev => prev.map((layout, idx) => {
          // 第 6 项地图中心说明不画引线
          if (idx === 5) {
            return { ...layout, connectorPoints: [] };
          }
          const targetRect = layout.targetRect || getGuideTargetRect(STEPS[idx]);
          const stepEl = stepRefs.current[idx];
          const badgeEl = stepEl?.querySelector('[data-guide-badge="true"]') as HTMLElement | null;
          if (!targetRect || !badgeEl) {
            return { ...layout, targetRect, connectorPoints: [] };
          }
          const badgeRect = badgeEl.getBoundingClientRect();
          const badgeCenter = {
            x: badgeRect.left + badgeRect.width / 2,
            y: badgeRect.top + badgeRect.height / 2,
          };
          return {
            ...layout,
            targetRect,
            // 第 4 项用户菜单用右侧绕行引线
            connectorPoints: idx === 3
              ? buildRightBiasedConnector(targetRect, badgeCenter, window.innerWidth).points
              : buildConnectorToPoint(targetRect, badgeCenter).points,
          };
        }));
      }
    });
    return () => cancelAnimationFrame(raf);
  }, [open, layouts.length, computeLayouts, forceStacked, getGuideTargetRect]);

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

  const [isMobileViewport, setIsMobileViewport] = useState(false);
  const [windowSmall, setWindowSmall] = useState(false);
  useEffect(() => {
    const check = () => {
      const mobile = window.innerWidth <= 768;
      setIsMobileViewport(mobile);
      setWindowSmall(mobile || window.innerWidth < 1180 || window.innerHeight < 760);
    };
    check();
    window.addEventListener('resize', check);
    return () => window.removeEventListener('resize', check);
  }, []);

  if (!open) return null;

  const effectiveStacked = windowSmall || forceStacked;
  const showDecorations = !isMobileViewport;

  return (
    <div className={styles.overlay}>
      {/* Spotlights */}
      {showDecorations && layouts.map((l) => {
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
      {showDecorations && (
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
      <div className={`${styles.stepsContainer} ${effectiveStacked ? styles.stepsStacked : ''}`}>
        {STEPS.map((step, idx) => {
          const layout = layouts[idx];
          const style: React.CSSProperties = effectiveStacked
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
                  minHeight: DEFAULT_CARD_HEIGHT,
                };

          const setStepRef = (el: HTMLDivElement | null) => {
            stepRefs.current[idx] = el;
          };

          return (
            <div key={step.target} className={styles.step} style={style} ref={setStepRef}>
              <div className={styles.badge} data-guide-badge="true">{idx + 1}</div>
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
