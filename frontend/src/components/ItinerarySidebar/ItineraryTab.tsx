/**
 * 行程 Tab 组件
 * 显示时间轴（时间段 + 路线 + 餐饮）
 */

import React from 'react';
import type { DayTimeline, TimeSlot, ActivitySlot, MealSlot } from '@/utils/parseItinerary';
import styles from './styles.module.css';

interface ItineraryTabProps {
  days: DayTimeline[];
  onPOIClick: (name: string) => void;
  planMode?: 'exploratory' | 'planned' | null;
}

export const ItineraryTab: React.FC<ItineraryTabProps> = ({ days, onPOIClick, planMode = null }) => {
  const isPlanned = planMode === 'planned';
  return (
    <div className={styles.itineraryTab}>
      {days.map(day => (
        <div key={day.dayNumber} className={styles.dayPanel}>
          <div className={styles.dayHeader}>
            <span className={styles.dayTitle}>{isPlanned ? '待会儿' : `第${day.dayNumber}天`}</span>
          </div>
          
          <div className={styles.dayContent}>
            {day.timeSlots.map((slot, index) => (
              <TimeSlotItem key={index} slot={slot} onPOIClick={onPOIClick} />
            ))}
          </div>
        </div>
      ))}
    </div>
  );
};

const TimeSlotItem: React.FC<{ slot: TimeSlot; onPOIClick: (name: string) => void }> = ({
  slot,
  onPOIClick
}) => {
  if (slot.type === 'activity') {
    return <ActivitySlotItem slot={slot} onPOIClick={onPOIClick} />;
  }

  if (slot.type === 'meal') {
    return <MealSlotItem slot={slot} onPOIClick={onPOIClick} />;
  }

  return null;
};

const ActivitySlotItem: React.FC<{ slot: ActivitySlot; onPOIClick: (name: string) => void }> = ({
  slot,
  onPOIClick
}) => {
  return (
    <div className={styles.activitySlot}>
      <div className={styles.timeSlotHeader}>
        <span className={styles.timeRange}>{slot.timeRange}</span>
        <span className={styles.periodBadge}>{slot.period}</span>
      </div>
      <div className={styles.activityTitle}>{slot.title}</div>
      
      {/* 提示信息 */}
      {slot.hint && (
        <div className={styles.hintBox}>
          <span className={styles.hintIcon}>💡</span>
          {slot.hint}
        </div>
      )}
      
      {/* 路线时间轴 */}
      {slot.routeSteps.length > 0 && (
        <div className={styles.routeTimeline}>
          {slot.routeSteps.map((step, i) => (
            <div key={i} className={styles.timelineItem}>
              <div className={styles.timelineAxis}>
                <div 
                  className={styles.timelineDot}
                  style={{ backgroundColor: getTransportColor(step.transport) }}
                />
                {i < slot.routeSteps.length - 1 && (
                  <div 
                    className={styles.timelineLine}
                    style={{ backgroundColor: getTransportColor(step.transport) }}
                  />
                )}
              </div>
              <div className={styles.timelineContent}>
                <div 
                  className={styles.poiName}
                  onClick={() => onPOIClick(step.from)}
                >
                  {step.from}
                </div>
                <div className={styles.transportInfo}>
                  <span className={styles.transportIcon}>
                    {getTransportIcon(step.transport)}
                  </span>
                  <span style={{ color: getTransportColor(step.transport) }}>
                    {step.transport} {step.duration}
                  </span>
                </div>
                {i === slot.routeSteps.length - 1 && (
                  <div 
                    className={styles.poiName}
                    onClick={() => onPOIClick(step.to)}
                  >
                    {step.to}
                  </div>
                )}
              </div>
            </div>
          ))}
        </div>
      )}
      
      {/* 推荐理由卡片 */}
      {slot.recommendation && (
        <div className={styles.recommendationCard}>
          <div className={styles.recommendationHeader}>
            <span className={styles.recommendationIcon}>💡</span>
            <span className={styles.recommendationTitle}>推荐理由</span>
          </div>
          <div className={styles.recommendationContent}>
            {slot.recommendation.highlights && (
              <div className={styles.recommendationItem}>
                <span className={styles.recommendationLabel}>核心看点：</span>
                <span className={styles.recommendationValue}>{slot.recommendation.highlights}</span>
              </div>
            )}
            {slot.recommendation.matchReason && (
              <div className={styles.recommendationItem}>
                <span className={styles.recommendationLabel}>匹配理由：</span>
                <span className={styles.recommendationValue}>{slot.recommendation.matchReason}</span>
              </div>
            )}
            {slot.recommendation.advice && (
              <div className={styles.recommendationItem}>
                <span className={styles.recommendationLabel}>安排建议：</span>
                <span className={styles.recommendationValue}>{slot.recommendation.advice}</span>
              </div>
            )}
            {slot.recommendation.commuteTime && (
              <div className={styles.recommendationItem}>
                <span className={styles.recommendationLabel}>通勤：</span>
                <span className={styles.recommendationValue}>{slot.recommendation.commuteTime}</span>
              </div>
            )}
          </div>
        </div>
      )}
    </div>
  );
};

const MealSlotItem: React.FC<{ slot: MealSlot; onPOIClick: (name: string) => void }> = ({
  slot,
  onPOIClick
}) => {
  return (
    <div className={styles.mealSlot}>
      <div className={styles.mealHeader}>
        <span className={styles.mealIcon}>🍽️</span>
        <span className={styles.mealTimeRange}>{slot.timeRange}</span>
        <span className={styles.mealPeriod}>{slot.period}</span>
      </div>
      
      <div className={styles.mealRestaurant}>
        <span 
          className={styles.restaurantName}
          onClick={() => onPOIClick(slot.restaurantName)}
        >
          {slot.restaurantName}
        </span>
      </div>
      
      <div className={styles.metaInfo}>
        <span className={styles.metaDistance}>{slot.distanceFromLast}</span>
        {slot.meta.rating && (
          <span className={styles.metaRating}>⭐ {slot.meta.rating.toFixed(1)}</span>
        )}
        {slot.meta.avgCost && (
          <span className={styles.metaCost}>人均约{slot.meta.avgCost}元</span>
        )}
        <span className={styles.metaType}>{slot.meta.type}</span>
      </div>
      
      {slot.walkInfo && (
        <div className={styles.walkInfo}>
          <span className={styles.walkIcon}>🚶</span>
          {slot.walkInfo}
        </div>
      )}
      
      {/* 路线步骤 */}
      {slot.routeSteps.length > 0 && (
        <div className={styles.mealRoute}>
          {slot.routeSteps.map((step, i) => (
            <div key={i} className={styles.mealRouteStep}>
              <span className={styles.routeTransport}>
                {getTransportIcon(step.transport)} {step.transport} {step.duration}
              </span>
            </div>
          ))}
        </div>
      )}
    </div>
  );
};

// 辅助函数
function getTransportColor(transport: string): string {
  const colors: Record<string, string> = {
    '步行': '#1890ff',
    '地铁/公交': '#52c41a',
    '自驾': '#fa8c16',
    '骑行': '#722ed1',
  };
  return colors[transport] || '#1890ff';
}

function getTransportIcon(transport: string): string {
  const icons: Record<string, string> = {
    '步行': '🚶',
    '地铁/公交': '🚇',
    '自驾': '🚗',
    '骑行': '🚴',
  };
  return icons[transport] || '🚶';
}

export default ItineraryTab;
