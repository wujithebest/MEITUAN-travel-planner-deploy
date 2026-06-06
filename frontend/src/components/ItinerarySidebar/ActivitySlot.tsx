/**
 * 活动时段组件
 * 显示白天/上午/下午/晚上的活动安排
 */

import React from 'react';
import type { ActivitySlot as ActivitySlotType } from '@/utils/parseItinerary';
import { RouteTimeline } from './RouteTimeline';
import { RecommendationCard } from './RecommendationCard';
import styles from './styles.module.css';

interface ActivitySlotProps {
  slot: ActivitySlotType;
  onPOIClick: (name: string) => void;
  onTransportClick: (from: string, to: string, transport: string) => void;
}

export const ActivitySlot: React.FC<ActivitySlotProps> = ({
  slot,
  onPOIClick,
  onTransportClick,
}) => {
  const { period, timeRange, title, routeSteps, recommendation, hint } = slot;

  return (
    <div className={styles.activitySlot}>
      {/* 时间段标题 */}
      <div className={styles.timeSlotHeader}>
        <span className={styles.timeRange}>{timeRange}</span>
        <span className={styles.periodBadge}>{period}</span>
      </div>
      <h4 className={styles.activityTitle}>{title}</h4>

      {/* 提示信息 */}
      {hint && (
        <div className={styles.hintBox}>
          <span className={styles.hintIcon}>💡</span>
          {hint}
        </div>
      )}

      {/* 路线时间轴 */}
      {routeSteps.length > 0 && (
        <RouteTimeline
          steps={routeSteps}
          onPOIClick={onPOIClick}
          onTransportClick={onTransportClick}
        />
      )}

      {/* 推荐理由 */}
      {recommendation && (
        <RecommendationCard recommendation={recommendation} />
      )}
    </div>
  );
};

export default ActivitySlot;
