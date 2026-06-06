/**
 * 路线信息面板组件
 * 显示每天的路线概览、交通方式、距离、时长
 * 
 * 对应后端: step3_micro.py 渲染结果的可视化展示
 */

import React, { useState } from 'react';
import { Card, Collapse, Typography, Space, Tag, Divider, List, Badge } from 'antd';
import {
  CarOutlined,
  RocketOutlined,
  ManOutlined,
  GlobalOutlined,
  ClockCircleOutlined,
  EnvironmentOutlined,
} from '@ant-design/icons';
import type { DayRoute, RouteSegment } from '@/types/route';
import { TRANSPORT_STYLES } from '@/types/route';
import styles from './RoutePanel.module.css';

const { Text } = Typography;
const { Panel } = Collapse;

interface RoutePanelProps {
  /** 单日路线列表 */
  dayRoutes: DayRoute[];
  /** 当前选中的天数 */
  selectedDay?: number | null;
  /** 天数切换回调 */
  onDaySelect?: (day: number) => void;
  /** 路线段点击回调 */
  onSegmentClick?: (segment: RouteSegment) => void;
}

/**
 * 获取交通方式图标
 */
const getTransportIcon = (transport: string): React.ReactNode => {
  switch (transport) {
    case '步行':
      return <ManOutlined />;
    case '自驾':
      return <CarOutlined />;
    case '地铁/公交':
      return <GlobalOutlined />;
    case '骑行':
      return <RocketOutlined />;
    default:
      return <ManOutlined />;
  }
};

/**
 * 格式化距离（米 → 可读字符串）
 */
const formatDistance = (meters: number): string => {
  if (meters < 1000) {
    return `${Math.round(meters)}m`;
  }
  return `${(meters / 1000).toFixed(1)}km`;
};

/**
 * 格式化时长（秒 → 可读字符串）
 */
const formatDuration = (seconds: number): string => {
  const mins = Math.round(seconds / 60);
  if (mins < 60) {
    return `${mins}分钟`;
  }
  const hours = Math.floor(mins / 60);
  const remainMins = Math.round(mins % 60);
  return remainMins > 0 ? `${hours}小时${remainMins}分钟` : `${hours}小时`;
};

/**
 * 路线信息面板组件
 * 
 * 功能：
 * 1. 显示每天的路线概览
 * 2. 每段路线的交通方式、距离、时长
 * 3. 颜色标识与地图 polyline 一致
 * 4. 点击可高亮地图对应 polyline
 */
export const RoutePanel: React.FC<RoutePanelProps> = ({
  dayRoutes,
  selectedDay,
  onDaySelect,
  onSegmentClick,
}) => {
  const [expandedDays, setExpandedDays] = useState<string[]>(
    selectedDay ? [`day-${selectedDay}`] : dayRoutes.map((dr) => `day-${dr.day}`)
  );

  // 计算总统计
  const totalDistance = dayRoutes.reduce((sum, dr) => sum + dr.totalDistance, 0);
  const totalDuration = dayRoutes.reduce((sum, dr) => sum + dr.totalDuration, 0);

  // 按天分组统计
  const getDayStats = (dayRoute: DayRoute) => {
    const distance = dayRoute.totalDistance;
    const duration = dayRoute.totalDuration;
    const transportCounts: Record<string, number> = {};

    dayRoute.segments.forEach((seg) => {
      transportCounts[seg.transport] = (transportCounts[seg.transport] || 0) + 1;
    });

    return { distance, duration, transportCounts };
  };

  return (
    <Card
      title={
        <Space>
          <EnvironmentOutlined />
          <Text strong>路线概览</Text>
        </Space>
      }
      className={styles.container}
      bodyStyle={{ padding: 0 }}
    >
      {/* 总体统计 */}
      <div className={styles.summary}>
        <Space split={<Divider type="vertical" />}>
          <Space>
            <EnvironmentOutlined style={{ color: '#1890ff' }} />
            <Text type="secondary">总距离</Text>
            <Text strong>{formatDistance(totalDistance)}</Text>
          </Space>
          <Space>
            <ClockCircleOutlined style={{ color: '#52c41a' }} />
            <Text type="secondary">总时长</Text>
            <Text strong>{formatDuration(totalDuration)}</Text>
          </Space>
          <Space>
            <Text type="secondary">天数</Text>
            <Badge count={dayRoutes.length} showZero style={{ backgroundColor: '#1890ff' }} />
          </Space>
        </Space>
      </div>

      <Divider style={{ margin: 0 }} />

      {/* 每日路线列表 */}
      <Collapse
        activeKey={expandedDays}
        onChange={(keys) => setExpandedDays(keys as string[])}
        ghost
        className={styles.dayCollapse}
      >
        {dayRoutes.map((dayRoute) => {
          const stats = getDayStats(dayRoute);
          const isSelected = selectedDay === dayRoute.day;

          return (
            <Panel
              key={`day-${dayRoute.day}`}
              header={
                <div
                  className={styles.dayHeader}
                  onClick={() => onDaySelect?.(dayRoute.day)}
                >
                  <Space align="center">
                    <Badge
                      count={dayRoute.day}
                      style={{
                        backgroundColor: isSelected ? '#1890ff' : '#999',
                      }}
                    />
                    <Text strong>第 {dayRoute.day} 天</Text>
                  </Space>
                  <Space split={<Divider type="vertical" />}>
                    <Text type="secondary">
                      <EnvironmentOutlined /> {formatDistance(stats.distance)}
                    </Text>
                    <Text type="secondary">
                      <ClockCircleOutlined /> {formatDuration(stats.duration)}
                    </Text>
                  </Space>
                </div>
              }
              className={isSelected ? styles.selectedDay : ''}
            >
              {/* 交通方式标签 */}
              <div className={styles.transportTags}>
                {Object.entries(stats.transportCounts).map(([transport, count]) => {
                  const style = TRANSPORT_STYLES[transport as keyof typeof TRANSPORT_STYLES];
                  return (
                    <Tag
                      key={transport}
                      color={style?.strokeColor}
                      icon={getTransportIcon(transport)}
                    >
                      {transport} × {count}
                    </Tag>
                  );
                })}
              </div>

              <Divider style={{ margin: '8px 0' }} />

              {/* 路线段列表 */}
              <List
                size="small"
                dataSource={dayRoute.segments}
                renderItem={(segment: RouteSegment, index: number) => {
                  const style = TRANSPORT_STYLES[segment.transport];
                  return (
                    <List.Item
                      className={styles.segmentItem}
                      onClick={() => onSegmentClick?.(segment)}
                    >
                      <div className={styles.segmentContent}>
                        {/* 序号和连接线 */}
                        <div className={styles.segmentIndex}>
                          <div
                            className={styles.segmentDot}
                            style={{ backgroundColor: style?.strokeColor }}
                          />
                          {index < dayRoute.segments.length - 1 && (
                            <div
                              className={styles.segmentLine}
                              style={{
                                backgroundColor: style?.strokeColor,
                                borderStyle: style?.isDashed ? 'dashed' : 'solid',
                              }}
                            />
                          )}
                        </div>

                        {/* 路线信息 */}
                        <div className={styles.segmentInfo}>
                          <Space align="center" style={{ marginBottom: 4 }}>
                            <Tag
                              color={style?.strokeColor}
                              icon={getTransportIcon(segment.transport)}
                            >
                              {segment.transport}
                            </Tag>
                            <Text strong>{segment.fromName || '起点'}</Text>
                            <Text type="secondary">→</Text>
                            <Text strong>{segment.toName || '终点'}</Text>
                          </Space>
                          <Space split={<Divider type="vertical" />}>
                            <Text type="secondary" style={{ fontSize: 12 }}>
                              <EnvironmentOutlined /> {formatDistance(segment.distance)}
                            </Text>
                            <Text type="secondary" style={{ fontSize: 12 }}>
                              <ClockCircleOutlined /> {formatDuration(segment.duration)}
                            </Text>
                          </Space>
                        </div>
                      </div>
                    </List.Item>
                  );
                }}
              />
            </Panel>
          );
        })}
      </Collapse>
    </Card>
  );
};

export default RoutePanel;
