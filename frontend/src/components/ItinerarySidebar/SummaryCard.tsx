/**
 * 总摘要卡片组件
 */

import React from 'react';
import styles from './styles.module.css';

interface SummaryCardProps {
  summary: string;
}

export const SummaryCard: React.FC<SummaryCardProps> = ({ summary }) => {
  return (
    <div className={styles.summaryCard}>
      <div className={styles.summaryIcon}>🗺️</div>
      <p className={styles.summaryText}>{summary}</p>
    </div>
  );
};

export default SummaryCard;
