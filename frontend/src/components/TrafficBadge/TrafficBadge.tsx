import React from 'react';
import { Badge } from 'antd';
import styles from './TrafficBadge.module.css';

interface TrafficBadgeProps {
  status: 'smooth' | 'slow' | 'congested' | 'blocked';
  onClick?: () => void;
}

const TRAFFIC_COLORS = {
  smooth: '#52c41a',    // 绿
  slow: '#FFD100',      // 黄
  congested: '#f5222d', // 红
  blocked: '#820014',   // 深红
};

const TRAFFIC_LABELS = {
  smooth: '畅通',
  slow: '缓行',
  congested: '拥堵',
  blocked: '严重拥堵',
};

const TrafficBadge: React.FC<TrafficBadgeProps> = ({ status, onClick }) => {
  const color = TRAFFIC_COLORS[status];
  const label = TRAFFIC_LABELS[status];

  return (
    <Badge 
      count={label} 
      style={{ backgroundColor: color }}
      onClick={onClick}
      className={styles.badge}
    />
  );
};

export default TrafficBadge;
