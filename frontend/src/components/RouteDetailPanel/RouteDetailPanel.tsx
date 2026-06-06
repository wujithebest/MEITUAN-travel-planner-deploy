// ============================================
// 路线详情面板组件
// 显示：summary总览 + daily_routes分天详情 + map_config地图配置
// ============================================

import React, { useState } from 'react';
import { Card, Collapse, Tag, Timeline, Badge, Descriptions, Statistic, Row, Col, Divider } from 'antd';
import {
  EnvironmentOutlined,
  ClockCircleOutlined,
  CloudOutlined,
  CarOutlined,
  CameraOutlined,
  StarOutlined,
  RightOutlined,
} from '@ant-design/icons';
import { useRouteStore } from '@/store/routeStore';
import type { DailyRoute, RouteSummary, MapConfig, WeatherInfo } from '@/api/types';

const { Panel } = Collapse;

/**
 * 路线详情面板
 * 从后端返回的数据直接渲染，不需要等待流式数据
 */
const RouteDetailPanel: React.FC = () => {
  const dailyRoutes = useRouteStore((s) => s.dailyRoutes);
  const summary = useRouteStore((s) => s.summary);
  const mapConfig = useRouteStore((s) => s.mapConfig);
  const weatherData = useRouteStore((s) => s.weatherData);

  const [expandedDays, setExpandedDays] = useState<string[]>(['0']);

  if (!summary || dailyRoutes.length === 0) {
    return (
      <Card className="route-detail-empty">
        <p>暂无路线数据，请先在AI助手中输入旅行需求</p>
      </Card>
    );
  }

  return (
    <div className="route-detail-panel">
      {/* 总览卡片 */}
      <SummaryCard summary={summary} mapConfig={mapConfig} />

      <Divider />

      {/* 分天详情 */}
      <h3>📅 每日行程详情</h3>
      <Collapse
        activeKey={expandedDays}
        onChange={(keys) => setExpandedDays(keys as string[])}
        accordion={false}
      >
        {dailyRoutes.map((route, index) => (
          <Panel
            key={index.toString()}
            header={<DayHeader route={route} weather={weatherData[`day_${index}`]} />}
          >
            <DailyRouteDetail route={route} />
          </Panel>
        ))}
      </Collapse>

      {/* 地图配置信息 */}
      {mapConfig && mapConfig.markers.length > 0 && (
        <>
          <Divider />
          <MapConfigInfo mapConfig={mapConfig} />
        </>
      )}
    </div>
  );
};

/**
 * 总览卡片组件
 */
const SummaryCard: React.FC<{ summary: RouteSummary; mapConfig: MapConfig }> = ({
  summary,
  mapConfig,
}) => {
  return (
    <Card title="📊 行程总览" className="summary-card">
      <Row gutter={[16, 16]}>
        <Col span={6}>
          <Statistic
            title="总天数"
            value={summary.days}
            suffix="天"
            prefix={<ClockCircleOutlined />}
          />
        </Col>
        <Col span={6}>
          <Statistic
            title="总景点"
            value={summary.total_pois}
            suffix="个"
            prefix={<EnvironmentOutlined />}
          />
        </Col>
        <Col span={6}>
          <Statistic
            title="总距离"
            value={(summary.total_distance / 1000).toFixed(1)}
            suffix="km"
            prefix={<CarOutlined />}
          />
        </Col>
        <Col span={6}>
          <Statistic
            title="总时长"
            value={Math.floor(summary.total_duration / 60)}
            suffix="小时"
            prefix={<ClockCircleOutlined />}
          />
        </Col>
      </Row>

      {(summary.main_pois || 0) > 0 && (
        <div style={{ marginTop: 16 }}>
          <Tag color="blue">主行程: {summary.main_pois}个景点</Tag>
          {(summary.enroute_pois || 0) > 0 && (
            <Tag color="green">沿途: {summary.enroute_pois}个景点</Tag>
          )}
        </div>
      )}

      {mapConfig && (
        <div style={{ marginTop: 8, fontSize: 12, color: '#888' }}>
          地图中心: {mapConfig.center} | 缩放级别: {mapConfig.zoom}
        </div>
      )}
    </Card>
  );
};

/**
 * 每日头部组件
 */
const DayHeader: React.FC<{ route: DailyRoute; weather?: WeatherInfo }> = ({
  route,
  weather,
}) => {
  return (
    <div className="day-header">
      <span className="day-title">第{(route.day_index ?? route.day - 1) + 1}天</span>
      <span className="day-date">{route.date}</span>
      {route.pois.length > 0 && (
        <span className="day-pois-count">{route.pois.length}个景点</span>
      )}
      {weather && (
        <Tag color="cyan" style={{ marginLeft: 8 }}>
          <CloudOutlined /> {weather.condition} {weather.temp_low}-{weather.temp_high}°C
        </Tag>
      )}
    </div>
  );
};

/**
 * 每日路线详情组件
 */
const DailyRouteDetail: React.FC<{ route: DailyRoute }> = ({ route }) => {
  return (
    <div className="daily-route-detail">
      {/* 路线统计 */}
      <Descriptions size="small" column={3} style={{ marginBottom: 16 }}>
        <Descriptions.Item label="距离">
          {((route.distance || route.total_distance || 0) / 1000).toFixed(1)} km
        </Descriptions.Item>
        <Descriptions.Item label="时长">
          {Math.floor((route.duration || route.total_duration || 0) / 60)}小时
          {(route.duration || route.total_duration || 0) % 60}分钟
        </Descriptions.Item>
        <Descriptions.Item label="景点数">{route.pois.length}个</Descriptions.Item>
      </Descriptions>

      {/* POI时间线 */}
      <Timeline mode="left">
        {(route.points || route.pois.map((poi) => ({
          poi,
          arrival_time: undefined,
          departure_time: undefined,
          transport_from_prev: undefined,
        }))).map((poiData, index) => {
          const { poi, arrival_time, departure_time, transport_from_prev } = poiData;
          return (
            <Timeline.Item
              key={poi.id}
              label={
                <div className="timeline-time">
                  <div>{arrival_time || '--:--'}</div>
                  {departure_time && <div className="departure">{departure_time}</div>}
                </div>
              }
              dot={<EnvironmentOutlined style={{ fontSize: '16px' }} />}
            >
              <div className="poi-item">
                <div className="poi-header">
                  <span className="poi-name">{poi.name}</span>
                  {poi.rating && (
                    <span className="poi-rating">
                      <StarOutlined /> {poi.rating}
                    </span>
                  )}
                  {poi.category && <Tag>{poi.category}</Tag>}
                </div>

                {poi.address && (
                  <div className="poi-address">
                    <EnvironmentOutlined /> {poi.address}
                  </div>
                )}

                {poi.description && (
                  <div className="poi-description">{poi.description}</div>
                )}

                {poi.best_visit_time && (
                  <div className="poi-best-time">
                    <ClockCircleOutlined /> 最佳时间: {poi.best_visit_time}
                  </div>
                )}

                {poi.suggested_duration && (
                  <div className="poi-duration">
                    建议游玩: {poi.suggested_duration}分钟
                  </div>
                )}

                {transport_from_prev && index > 0 && (
                  <div className="transport-info">
                    <RightOutlined />{' '}
                    {typeof transport_from_prev === 'string'
                      ? transport_from_prev
                      : `${transport_from_prev.mode}（${transport_from_prev.duration}分钟 / ${(transport_from_prev.distance / 1000).toFixed(1)}km）`}
                  </div>
                )}
              </div>
            </Timeline.Item>
          );
        })}
      </Timeline>

      {/* 路线polyline */}
      {route.polyline && (
        <div className="polyline-info" style={{ marginTop: 16, fontSize: 12, color: '#888' }}>
          <CameraOutlined /> 路线坐标: {route.polyline.substring(0, 50)}...
        </div>
      )}
    </div>
  );
};

/**
 * 地图配置信息组件
 */
const MapConfigInfo: React.FC<{ mapConfig: MapConfig }> = ({ mapConfig }) => {
  return (
    <Card title="🗺️ 地图配置" size="small">
      <Descriptions size="small" column={2}>
        <Descriptions.Item label="中心点">{mapConfig.center}</Descriptions.Item>
        <Descriptions.Item label="缩放级别">{mapConfig.zoom}</Descriptions.Item>
        <Descriptions.Item label="标记点数">{mapConfig.markers.length}</Descriptions.Item>
        <Descriptions.Item label="路线段数">{mapConfig.daily_polylines.length}</Descriptions.Item>
      </Descriptions>

      <div style={{ marginTop: 8 }}>
        <strong>标记点列表：</strong>
        <div style={{ marginTop: 4 }}>
          {mapConfig.markers.map((marker, index) => (
            <Tag key={marker.id} style={{ margin: 2 }}>
              {marker.name}
            </Tag>
          ))}
        </div>
      </div>
    </Card>
  );
};

export default RouteDetailPanel;
