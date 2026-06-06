/**
 * 餐饮时段组件
 * 显示中午/晚餐的餐饮推荐
 */

import React from 'react';
import type { MealSlot as MealSlotType } from '@/utils/parseItinerary';
import { getTransportIcon } from '@/utils/parseItinerary';
import styles from './styles.module.css';

interface MealSlotProps {
  slot: MealSlotType;
  onPOIClick: (name: string) => void;
}

export const MealSlot: React.FC<MealSlotProps> = ({ slot, onPOIClick }) => {
  const { period, timeRange, restaurantName, distanceFromLast, meta, routeSteps, walkInfo } = slot;

  return (
    <div className={styles.mealSlot}>
      {/* 餐饮标题 */}
      <div className={styles.mealHeader}>
        <span className={styles.mealIcon}>🍽️</span>
        <span className={styles.mealTimeRange}>{timeRange}</span>
        <span className={styles.mealPeriod}>{period}</span>
      </div>

      {/* 餐厅名称 */}
      <div className={styles.mealRestaurant} onClick={() => onPOIClick(restaurantName)}>
        <span className={styles.restaurantName}>{restaurantName}</span>
      </div>

      {/* 餐厅元信息 */}
      <div className={styles.metaInfo}>
        <span className={styles.metaDistance}>{distanceFromLast}</span>
        {meta.rating && (
          <span className={styles.metaRating}>⭐ {meta.rating}</span>
        )}
        {meta.avgCost && (
          <span className={styles.metaCost}>人均 ¥{meta.avgCost}</span>
        )}
        <span className={styles.metaType}>{meta.type}</span>
      </div>

      {/* 步行信息 */}
      {walkInfo && (
        <div className={styles.walkInfo}>
          <span className={styles.walkIcon}>🚶</span>
          {walkInfo}
        </div>
      )}

      {/* 路线步骤 */}
      {routeSteps.length > 0 && (
        <div className={styles.mealRoute}>
          {routeSteps.map((step, index) => (
            <div key={index} className={styles.mealRouteStep}>
              <span className={styles.routeTransport}>
                {getTransportIcon(step.transport)} {step.transport} {step.duration}
              </span>
              <span className={styles.routeArrow}>→</span>
              <span className={styles.routeTo} onClick={() => onPOIClick(step.to)}>
                {step.to}
              </span>
            </div>
          ))}
        </div>
      )}
    </div>
  );
};

export default MealSlot;
