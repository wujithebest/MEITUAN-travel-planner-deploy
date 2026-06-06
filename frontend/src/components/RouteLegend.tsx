/**
 * 路线图例组件
 * 显示在地图右下角，展示时间段颜色和标记含义
 */

import React from 'react';
import styles from './RouteLegend.module.css';

const PERIODS = [
  { key: 'morning', label: '上午', color: '#E67E22' },
  { key: 'lunch', label: '午餐', color: '#D35400' },
  { key: 'afternoon', label: '下午', color: '#2980B9' },
  { key: 'dinner', label: '晚餐', color: '#C0392B' },
  { key: 'evening', label: '晚间', color: '#8E44AD' },
];

interface RouteLegendProps {
  /** 天数（用于显示 Day1, Day2 等） */
  day?: number;
  /** 自定义类名 */
  className?: string;
}

export const RouteLegend: React.FC<RouteLegendProps> = ({ day = 1, className }) => {
  return (
    <div className={`${styles.legend} ${className || ''}`}>
      <b className={styles.title}>图例 Day{day}</b>
      
      {PERIODS.map(p => (
        <div key={p.key} className={styles.item}>
          <span className={styles.dot} style={{ color: p.color }}>●</span>
          <span>{p.label}</span>
        </div>
      ))}
      
      <div className={styles.item}>
        <span className={styles.start}>▶</span>
        <span>出发地</span>
      </div>
      
      <div className={styles.divider} />
      
      <div className={styles.item}>
        <span>★</span>
        <span>主要景点</span>
      </div>
      <div className={styles.item}>
        <span style={{ color: '#3498DB' }}>●</span>
        <span>途经点（旁支）</span>
      </div>
      
      <div className={styles.divider} />
      
      <div className={styles.item}>
        <span className={styles.dashed}>- - -</span>
        <span>公交/自驾</span>
      </div>
      <div className={styles.item}>
        <span className={styles.solid}>━━━</span>
        <span>步行</span>
      </div>
    </div>
  );
};

export default RouteLegend;
