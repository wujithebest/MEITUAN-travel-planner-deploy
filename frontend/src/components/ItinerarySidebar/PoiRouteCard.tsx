/**
 * POI 路线卡片 — 按 slot 展示地图路线 POI 列表
 */
import React from 'react';
import styles from './PoiRouteCard.module.css';

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

export interface PanelSlotData {
  type: string;
  label: string;
  time_range: string;
  pois: PanelPoiData[];
  recommend_reason?: string;
  recommend_reasons?: Array<{ name: string; reason: string }>;
}

export interface PanelDayData {
  day_index: number;
  slots: PanelSlotData[];
}

interface PoiRouteCardProps {
  panelDays: PanelDayData[];
  onPOIClick?: (name: string) => void;
  planMode?: 'exploratory' | 'planned' | null;
}

const SLOT_ORDER: Record<string, number> = {
  short_trip: 1,
  half_day: 1,
  morning: 1, lunch: 2, afternoon: 3, dinner: 4, evening: 5,
};

export const PoiRouteCard: React.FC<PoiRouteCardProps> = ({ panelDays, onPOIClick, planMode = null }) => {
  if (!panelDays || panelDays.length === 0) return null;
  const isPlanned = planMode === 'planned';

  return (
    <div className={styles.container}>
      {panelDays.map(day => {
        const sortedSlots = [...day.slots].sort(
          (a, b) => (SLOT_ORDER[a.type] || 99) - (SLOT_ORDER[b.type] || 99)
        );

        return (
          <div key={day.day_index} className={styles.dayCard}>
            <div className={styles.dayTitle}>{isPlanned ? '待会儿' : `第${day.day_index}天`}</div>

            {sortedSlots.map(slot => {
              if (!slot.pois || slot.pois.length === 0) return null;
              const isMealSlot = slot.type === 'lunch' || slot.type === 'dinner';
              const reasonItems = slot.recommend_reasons && slot.recommend_reasons.length > 0
                ? slot.recommend_reasons
                : slot.recommend_reason
                  ? [{ name: '', reason: slot.recommend_reason }]
                  : [];
              const isCompactSlot = slot.type === 'short_trip' || slot.type === 'half_day';
              const shouldShowSlotHeader =
                !isPlanned && !isCompactSlot && Boolean(slot.time_range || slot.label);

              return (
                <div
                  key={slot.type}
                  className={`${styles.slotSection} ${isMealSlot ? styles.mealSlotSection : ''}`}
                >
                  {shouldShowSlotHeader && (
                    <div className={styles.slotHeader}>
                      {slot.time_range && <span className={styles.slotTime}>{slot.time_range}</span>}
                      {slot.label && (
                        <span className={`${styles.slotLabel} ${isMealSlot ? styles.mealSlotLabel : ''}`}>
                          {slot.label}
                        </span>
                      )}
                    </div>
                  )}

                  <div className={styles.poiList}>
                    {slot.pois.map(poi => (
                      <div key={`${poi.order}-${poi.name}`} className={styles.poiItem}>
                        <div className={styles.poiNumber}>{poi.order}</div>
                        <div className={styles.poiContent}>
                          <div className={styles.poiNameRow}>
                            <span
                              className={styles.poiName}
                              onClick={() => onPOIClick?.(poi.name)}
                            >
                              {poi.name}
                            </span>
                            {poi.is_start && (
                              <span className={styles.startTag}>起点</span>
                            )}
                          </div>
                          {poi.transport_text && (
                            <div className={styles.poiMeta}>{poi.transport_text}</div>
                          )}
                        </div>
                      </div>
                    ))}
                  </div>

                  {reasonItems.length > 0 && (
                    <div className={styles.reasonCard}>
                      <div className={styles.reasonTitle}>推荐理由</div>
                      <div className={styles.reasonList}>
                        {reasonItems.map((item, idx) => (
                          <div key={`${item.name}-${idx}`} className={styles.reasonItem}>
                            {item.name && <span className={styles.reasonName}>{item.name}：</span>}
                            <span className={styles.reasonText}>{item.reason}</span>
                          </div>
                        ))}
                      </div>
                    </div>
                  )}
                </div>
              );
            })}
          </div>
        );
      })}
    </div>
  );
};

export default PoiRouteCard;
