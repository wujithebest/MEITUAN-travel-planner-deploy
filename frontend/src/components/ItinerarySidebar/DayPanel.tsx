/**
 * 天数面板组件
 * 显示单天的行程安排，支持折叠/展开
 */

import React, { useState } from 'react';
import { ChevronDown, ChevronRight } from 'lucide-react';
import type { DayItinerary, TimeSlot } from '@/utils/parseItinerary';
import { ActivitySlot } from './ActivitySlot';
import { MealSlot } from './MealSlot';
import { AlongTheWay } from './AlongTheWay';
import styles from './styles.module.css';

interface DayPanelProps {
  day: DayItinerary;
  onPOIClick: (name: string) => void;
  onTransportClick: (from: string, to: string, transport: string) => void;
}

export const DayPanel: React.FC<DayPanelProps> = ({
  day,
  onPOIClick,
  onTransportClick,
}) => {
  const [expanded, setExpanded] = useState(true);
  const [showMainPOIs, setShowMainPOIs] = useState(true);
  const [showPassingPOIs, setShowPassingPOIs] = useState(true);

  const toggleExpanded = () => setExpanded(!expanded);

  const renderTimeSlot = (slot: TimeSlot, index: number) => {
    if (slot.type === 'activity') {
      return (
        <ActivitySlot
          key={`activity-${index}`}
          slot={slot}
          onPOIClick={onPOIClick}
          onTransportClick={onTransportClick}
        />
      );
    }
    return (
      <MealSlot
        key={`meal-${index}`}
        slot={slot}
        onPOIClick={onPOIClick}
      />
    );
  };

  return (
    <div className={styles.dayPanel}>
      {/* 天数标题 */}
      <div className={styles.dayHeader} onClick={toggleExpanded}>
        <div className={styles.dayHeaderLeft}>
          {expanded ? (
            <ChevronDown size={16} className={styles.dayToggleIcon} />
          ) : (
            <ChevronRight size={16} className={styles.dayToggleIcon} />
          )}
          <span className={styles.dayTitle}>第{day.dayNumber}天</span>
        </div>
        <div className={styles.dayHeaderRight}>
          <button
            className={`${styles.filterTag} ${showMainPOIs ? styles.filterTagActive : ''}`}
            onClick={(e) => {
              e.stopPropagation();
              setShowMainPOIs(!showMainPOIs);
            }}
          >
            主
          </button>
          <button
            className={`${styles.filterTag} ${styles.filterTagPassing} ${showPassingPOIs ? styles.filterTagPassingActive : ''}`}
            onClick={(e) => {
              e.stopPropagation();
              setShowPassingPOIs(!showPassingPOIs);
            }}
          >
            顺
          </button>
        </div>
      </div>

      {/* 天数内容 */}
      {expanded && (
        <div className={styles.dayContent}>
          {/* 时间段列表 */}
          {day.timeSlots.map((slot, index) => renderTimeSlot(slot, index))}

          {/* 沿途可顺路游览 */}
          {showPassingPOIs && day.alongTheWay.length > 0 && (
            <AlongTheWay pois={day.alongTheWay} onPOIClick={onPOIClick} />
          )}

          {/* 同一建筑内还有 */}
          {day.sameBuildingPOIs.length > 0 && (
            <div className={styles.sameBuilding}>
              <span className={styles.sameBuildingLabel}>同一建筑内还有：</span>
              <span className={styles.sameBuildingList}>
                {day.sameBuildingPOIs.join('、')}
              </span>
            </div>
          )}
        </div>
      )}
    </div>
  );
};

export default DayPanel;
