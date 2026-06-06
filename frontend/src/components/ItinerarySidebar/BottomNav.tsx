/**
 * 底部导航组件
 * 显示行程统计信息和开始导航按钮
 */

import React from 'react';
import { Navigation, MapPin, Clock, DollarSign } from 'lucide-react';
import type { ParsedItinerary } from '@/utils/parseItinerary';
import styles from './styles.module.css';

interface BottomNavProps {
  data: ParsedItinerary;
  onStartNavigation?: () => void;
}

export const BottomNav: React.FC<BottomNavProps> = ({
  data,
  onStartNavigation,
}) => {
  // 计算统计数据
  const totalPOIs = data.days.reduce((sum, day) => {
    return sum + day.timeSlots.reduce((slotSum, slot) => {
      if (slot.type === 'activity') {
        return slotSum + slot.routeSteps.length + 1;
      }
      return slotSum + 1;
    }, 0);
  }, 0);

  const totalDays = data.days.length;

  // 估算总距离（简化计算）
  const estimatedDistance = totalDays * 5; // 假设每天约5km

  // 估算总时间
  const estimatedHours = totalDays * 8; // 假设每天约8小时

  return (
    <div className={styles.bottomNav}>
      {/* 统计信息 */}
      <div className={styles.statsRow}>
        <div className={styles.statItem}>
          <MapPin size={14} className={styles.statIcon} />
          <span className={styles.statValue}>{estimatedDistance}km</span>
        </div>
        <div className={styles.statItem}>
          <Clock size={14} className={styles.statIcon} />
          <span className={styles.statValue}>{estimatedHours}h</span>
        </div>
        <div className={styles.statItem}>
          <DollarSign size={14} className={styles.statIcon} />
          <span className={styles.statValue}>¥0</span>
        </div>
        <div className={styles.statItem}>
          <MapPin size={14} className={styles.statIcon} />
          <span className={styles.statValue}>{totalPOIs}地点</span>
        </div>
      </div>

      {/* 开始导航按钮 */}
      <button className={styles.navButton} onClick={onStartNavigation}>
        <Navigation size={18} className={styles.navButtonIcon} />
        <span className={styles.navButtonText}>Start Navigation</span>
      </button>
    </div>
  );
};

export default BottomNav;
