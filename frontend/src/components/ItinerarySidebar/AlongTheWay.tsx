/**
 * 沿途可顺路游览组件
 * 显示途经的POI列表
 */

import React from 'react';
import type { AlongPOI } from '@/utils/parseItinerary';
import styles from './styles.module.css';

interface AlongTheWayProps {
  pois: AlongPOI[];
  onPOIClick: (name: string) => void;
}

export const AlongTheWay: React.FC<AlongTheWayProps> = ({ pois, onPOIClick }) => {
  if (pois.length === 0) return null;

  return (
    <div className={styles.alongTheWay}>
      <div className={styles.alongHeader}>
        <span className={styles.alongIcon}>🌿</span>
        <span className={styles.alongTitle}>沿途可顺路游览</span>
      </div>
      <div className={styles.alongList}>
        {pois.map((poi, index) => (
          <div
            key={index}
            className={styles.alongItem}
            onClick={() => onPOIClick(poi.name)}
          >
            <span className={styles.alongDot}>·</span>
            <span className={styles.alongName}>{poi.name}</span>
            <span className={styles.alongWalkTime}>（{poi.walkTime}）</span>
          </div>
        ))}
      </div>
    </div>
  );
};

export default AlongTheWay;
