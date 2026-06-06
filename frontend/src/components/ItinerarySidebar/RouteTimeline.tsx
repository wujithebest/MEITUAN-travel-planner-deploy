/**
 * 路线时间轴组件
 * 显示起点到终点的路线步骤，带时间轴样式
 */

import React from 'react';
import type { RouteStep } from '@/utils/parseItinerary';
import { getTransportColor, getTransportIcon } from '@/utils/parseItinerary';
import styles from './styles.module.css';

interface RouteTimelineProps {
  steps: RouteStep[];
  onPOIClick: (name: string) => void;
  onTransportClick: (from: string, to: string, transport: string) => void;
}

export const RouteTimeline: React.FC<RouteTimelineProps> = ({
  steps,
  onPOIClick,
  onTransportClick,
}) => {
  if (steps.length === 0) return null;

  // 获取第一个交通方式的颜色作为时间轴颜色
  const timelineColor = getTransportColor(steps[0].transport);

  return (
    <div className={styles.routeTimeline}>
      {steps.map((step, index) => {
        const isFirst = index === 0;
        const isLast = index === steps.length - 1;
        const transportColor = getTransportColor(step.transport);
        const transportIcon = getTransportIcon(step.transport);

        return (
          <div key={index} className={styles.timelineItem}>
            {/* 时间轴线 */}
            <div className={styles.timelineAxis}>
              {/* 圆点 */}
              <div
                className={styles.timelineDot}
                style={{
                  backgroundColor: isFirst || isLast ? transportColor : '#fff',
                  boxShadow: `0 0 0 2px ${transportColor}`,
                }}
              />
              {/* 连接线 */}
              {!isLast && (
                <div
                  className={styles.timelineLine}
                  style={{ backgroundColor: timelineColor }}
                />
              )}
            </div>

            {/* 内容 */}
            <div className={styles.timelineContent}>
              {/* 起点/终点名称 */}
              <div
                className={styles.poiName}
                onClick={() => onPOIClick(isFirst ? step.from : step.to)}
              >
                {isFirst ? step.from : step.to}
              </div>

              {/* 交通信息 */}
              <div
                className={styles.transportInfo}
                style={{ color: transportColor }}
                onClick={() => onTransportClick(step.from, step.to, step.transport)}
              >
                <span className={styles.transportIcon}>{transportIcon}</span>
                <span className={styles.transportText}>
                  {step.transport} {step.duration}
                </span>
              </div>
            </div>
          </div>
        );
      })}
    </div>
  );
};

export default RouteTimeline;
