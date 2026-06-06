/**
 * 锚点总结组件
 * 显示主要POI的简要总结
 */

import React from 'react';
import type { AnchorSummary as AnchorSummaryType } from '@/utils/parseItinerary';
import styles from './styles.module.css';

interface AnchorSummaryListProps {
  anchors: AnchorSummaryType[];
  onPOIClick: (name: string) => void;
}

export const AnchorSummaryList: React.FC<AnchorSummaryListProps> = ({
  anchors,
  onPOIClick,
}) => {
  if (anchors.length === 0) return null;

  return (
    <div className={styles.anchorSummary}>
      {anchors.map((anchor, index) => (
        <div key={index} className={styles.anchorItem}>
          <div
            className={styles.anchorName}
            onClick={() => onPOIClick(anchor.name)}
          >
            <span className={styles.anchorDot}>·</span>
            {anchor.name}
          </div>

          <div className={styles.anchorDetails}>
            {anchor.highlights && (
              <div className={styles.anchorDetail}>
                <span className={styles.anchorLabel}>核心看点：</span>
                <span className={styles.anchorValue}>{anchor.highlights}</span>
              </div>
            )}

            {anchor.matchReason && (
              <div className={styles.anchorDetail}>
                <span className={styles.anchorLabel}>匹配理由：</span>
                <span className={styles.anchorValue}>{anchor.matchReason}</span>
              </div>
            )}

            {anchor.advice && (
              <div className={styles.anchorDetail}>
                <span className={styles.anchorLabel}>安排建议：</span>
                <span className={styles.anchorValue}>{anchor.advice}</span>
              </div>
            )}

            {anchor.commuteTime && (
              <div className={styles.anchorDetail}>
                <span className={styles.anchorLabel}>通勤：</span>
                <span className={styles.anchorValue}>{anchor.commuteTime}</span>
              </div>
            )}
          </div>
        </div>
      ))}
    </div>
  );
};

export default AnchorSummaryList;
