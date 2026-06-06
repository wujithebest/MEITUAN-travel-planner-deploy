/**
 * 路线 Tab 组件
 * 按 POI 顺序展示点到点交通段，数据源为 rawRouteData.segments
 */

import React from 'react';
import { Footprints, Bus, Car, Navigation } from 'lucide-react';
import styles from './styles.module.css';

interface SegmentData {
  segment_order: number;
  from_poi: string;
  to_poi: string;
  day_index: number;
  transport: string;
  duration_min: number;
  distance_km: number;
  polyline: string;
  period: string;
  color: string;
  from_display_order?: number | null;
  to_display_order?: number | null;
}

interface PanelDayData {
  day_index: number;
  slots: Array<{
    type: string;
    label: string;
    pois: Array<{ order: number; name: string }>;
  }>;
}

interface RoutesTabProps {
  segments: SegmentData[];
  panelDays: PanelDayData[] | null;
  onRouteClick?: (segment: SegmentData) => void;
}

const PERIOD_LABEL_MAP: Record<string, string> = {
  morning: '上午',
  lunch: '午餐',
  afternoon: '下午',
  dinner: '晚餐',
  evening: '晚上',
  half_day: '半日',
};

const TransportIcon: React.FC<{ transport: string }> = ({ transport }) => {
  const t = transport || '';
  if (t.includes('步行') || t.includes('walk')) return <Footprints size={14} />;
  if (t.includes('公交') || t.includes('地铁') || t.includes('transit') || t.includes('bus')) return <Bus size={14} />;
  if (t.includes('自驾') || t.includes('drive') || t.includes('car')) return <Car size={14} />;
  return <Navigation size={14} />;
};

const formatDuration = (min: number): string => {
  if (min == null || isNaN(min)) return '';
  if (min < 1) return '约1分钟';
  return `约${Math.round(min)}分钟`;
};

const formatDistance = (km: number): string => {
  if (km == null || isNaN(km)) return '';
  if (km >= 1) return `${km.toFixed(1)}km`;
  return `${Math.round(km * 1000)}m`;
};

export const RoutesTab: React.FC<RoutesTabProps> = ({ segments, panelDays, onRouteClick }) => {
  if (!segments || segments.length === 0) {
    return (
      <div className={styles.emptyState}>
        <p>暂无路线数据</p>
        <p className={styles.emptyHint}>规划完成后将显示路线步骤</p>
      </div>
    );
  }

  const sorted = [...segments].sort((a, b) => (a.segment_order || 0) - (b.segment_order || 0));

  return (
    <div className={styles.routesTabNew}>
      {sorted.map((seg, idx) => {
        const periodLabel = PERIOD_LABEL_MAP[seg.period] || seg.period || '';
        const isLast = idx === sorted.length - 1;
        return (
          <div key={`seg-${seg.segment_order || idx}`} className={styles.routeStepRow}>
            {/* 左侧时间线 */}
            <div className={styles.routeStepTimeline}>
              <div className={styles.routeStepDot} />
              {!isLast && <div className={styles.routeStepLine} />}
            </div>
            {/* 右侧卡片 — 可点击进入单段路线模式 */}
            <div className={styles.routeStepCard} onClick={() => onRouteClick?.(seg)} style={{ cursor: onRouteClick ? 'pointer' : 'default' }}>
              <div className={styles.routeStepHeader}>
                <span className={styles.routeStepFrom}>{seg.from_poi}</span>
                <span className={styles.routeStepArrow}>→</span>
                <span className={styles.routeStepTo}>{seg.to_poi}</span>
              </div>
              <div className={styles.routeStepInfo}>
                <span className={styles.routeStepTransportPill}>
                  <TransportIcon transport={seg.transport} />
                  <span>{seg.transport}</span>
                </span>
                {seg.duration_min != null && seg.duration_min > 0 && (
                  <span className={styles.routeStepDurationPill}>{formatDuration(seg.duration_min)}</span>
                )}
                {seg.distance_km != null && seg.distance_km > 0 && (
                  <span className={styles.routeStepDistance}>{formatDistance(seg.distance_km)}</span>
                )}
              </div>
              {periodLabel && (
                <div className={styles.routeStepPeriod}>
                  <span className={styles.routeStepPeriodTag}>{periodLabel}</span>
                </div>
              )}
            </div>
          </div>
        );
      })}
    </div>
  );
};

export default RoutesTab;
