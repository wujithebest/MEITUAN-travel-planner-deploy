import React from 'react';
import styles from './TrafficLegend.module.css';

const TRAFFIC_ITEMS = [
  { status: 'smooth', label: '畅通', color: '#52c41a' },
{ status: 'slow', label: '缓行', color: '#FFD100' },
  { status: 'congested', label: '拥堵', color: '#f5222d' },
  { status: 'blocked', label: '严重拥堵', color: '#722ed1' },
];

const TrafficLegend: React.FC = () => {
  return (
    <div className={styles.container}>
      <div className={styles.title}>路况</div>
      {TRAFFIC_ITEMS.map((item) => (
        <div key={item.status} className={styles.item}>
          <span className={styles.line} style={{ background: item.color }} />
          <span className={styles.label}>{item.label}</span>
        </div>
      ))}
    </div>
  );
};

export default TrafficLegend;
