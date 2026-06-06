/**
 * 推荐理由卡片组件
 * 显示核心看点、匹配理由、安排建议
 */

import React from 'react';
import type { Recommendation } from '@/utils/parseItinerary';
import styles from './styles.module.css';

interface RecommendationCardProps {
  recommendation: Recommendation;
}

export const RecommendationCard: React.FC<RecommendationCardProps> = ({
  recommendation,
}) => {
  const { highlights, matchReason, advice, commuteTime } = recommendation;

  return (
    <div className={styles.recommendationCard}>
      <div className={styles.recommendationHeader}>
        <span className={styles.recommendationIcon}>💡</span>
        <span className={styles.recommendationTitle}>推荐理由</span>
      </div>

      <div className={styles.recommendationContent}>
        {highlights && (
          <div className={styles.recommendationItem}>
            <span className={styles.recommendationLabel}>核心看点：</span>
            <span className={styles.recommendationValue}>{highlights}</span>
          </div>
        )}

        {matchReason && (
          <div className={styles.recommendationItem}>
            <span className={styles.recommendationLabel}>匹配理由：</span>
            <span className={styles.recommendationValue}>{matchReason}</span>
          </div>
        )}

        {advice && (
          <div className={styles.recommendationItem}>
            <span className={styles.recommendationLabel}>安排建议：</span>
            <span className={styles.recommendationValue}>{advice}</span>
          </div>
        )}

        {commuteTime && (
          <div className={styles.recommendationItem}>
            <span className={styles.recommendationLabel}>通勤时间：</span>
            <span className={styles.recommendationValue}>{commuteTime}</span>
          </div>
        )}
      </div>
    </div>
  );
};

export default RecommendationCard;
