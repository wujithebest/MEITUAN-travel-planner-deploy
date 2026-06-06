/**
 * 地点 Tab 组件
 * 按当前路线 POI 顺序展示卡片，数据源为 panelDays
 */

import React from 'react';
import styles from './styles.module.css';

export interface PanelPoiData {
  order: number;
  name: string;
  kind: string;
  day_index: number;
  slot: string;
  location: string;
  is_start: boolean;
  transport_text: string;
  recommend_reason: string;
  photo_url?: string;
  rating?: string | number;
  address?: string;
  parent_anchor?: string;
}

interface PanelSlotData {
  type: string;
  label: string;
  time_range: string;
  pois: PanelPoiData[];
  recommend_reasons?: Array<{ name: string; reason: string }>;
}

interface PanelDayData {
  day_index: number;
  slots: PanelSlotData[];
}

interface LocationsTabProps {
  panelDays: PanelDayData[] | null;
  onPOIClick: (name: string) => void;
}

const SLOT_LABEL_MAP: Record<string, string> = {
  half_day: '半日',
  morning: '上午',
  lunch: '午餐',
  afternoon: '下午',
  dinner: '晚餐',
  evening: '晚上',
};

const SLOT_ORDER: Record<string, number> = {
  half_day: 1, morning: 1, lunch: 2, afternoon: 3, dinner: 4, evening: 5,
};

const isMealPoi = (poi: PanelPoiData, slotType: string): boolean => {
  return slotType === 'lunch' || slotType === 'dinner' || poi.kind === 'meal' || poi.kind === 'restaurant';
};

export const LocationsTab: React.FC<LocationsTabProps> = ({ panelDays, onPOIClick }) => {
  if (!panelDays || panelDays.length === 0) {
    return (
      <div className={styles.emptyState}>
        <p>暂无地点数据</p>
        <p className={styles.emptyHint}>规划完成后将显示推荐的地点</p>
      </div>
    );
  }

  // 展平 panelDays 为有序 POI 列表
  const allPois: Array<{ poi: PanelPoiData; dayIndex: number; slotType: string; slotLabel: string }> = [];
  const sortedDays = [...panelDays].sort((a, b) => a.day_index - b.day_index);
  for (const day of sortedDays) {
    const sortedSlots = [...day.slots].sort(
      (a, b) => (SLOT_ORDER[a.type] || 99) - (SLOT_ORDER[b.type] || 99)
    );
    for (const slot of sortedSlots) {
      const sortedPois = [...slot.pois].sort((a, b) => (a.order || 0) - (b.order || 0));
      for (const poi of sortedPois) {
        allPois.push({
          poi,
          dayIndex: day.day_index,
          slotType: slot.type,
          slotLabel: SLOT_LABEL_MAP[slot.type] || slot.label || slot.type,
        });
      }
    }
  }

  if (allPois.length === 0) {
    return (
      <div className={styles.emptyState}>
        <p>暂无地点数据</p>
        <p className={styles.emptyHint}>规划完成后将显示推荐的地点</p>
      </div>
    );
  }

  return (
    <div className={styles.locationsTabNew}>
      {allPois.map(({ poi, dayIndex, slotType, slotLabel }, index) => {
        const meal = isMealPoi(poi, slotType);
        const ratingNum = poi.rating != null ? Number(poi.rating) : 0;
        return (
          <div
            key={`${poi.name}-${index}`}
            className={`${styles.locationPoiCard} ${meal ? styles.locationPoiCardMeal : ''}`}
            onClick={() => onPOIClick(poi.name)}
          >
            <div className={`${styles.locationPoiOrder} ${meal ? styles.locationPoiOrderMeal : ''}`}>
              {poi.order}
            </div>
            <div className={styles.locationPoiBody}>
              <div className={styles.locationPoiName}>{poi.name}</div>
              <div className={styles.locationPoiMeta}>
                <span className={`${styles.locationPoiSlotTag} ${meal ? styles.locationPoiSlotTagMeal : ''}`}>
                  {slotLabel}
                </span>
                {poi.transport_text && (
                  <span className={styles.locationPoiTransport}>{poi.transport_text}</span>
                )}
              </div>
              {poi.address && (
                <div className={styles.locationPoiAddress}>{poi.address}</div>
              )}
              {ratingNum > 0 && (
                <div className={styles.locationPoiRating}>⭐ {ratingNum.toFixed(1)}</div>
              )}
            </div>
          </div>
        );
      })}
    </div>
  );
};

export default LocationsTab;
