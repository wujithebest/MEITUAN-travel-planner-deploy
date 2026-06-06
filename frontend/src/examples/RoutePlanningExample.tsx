/**
 * 路线规划使用示例
 * 展示如何使用 useRoutePlanning hook 和 RoutePolylineService
 */

import React, { useState } from 'react';
import { Button, Space, message, Card, Typography } from 'antd';
import { useGaodeMap } from '@/hooks/useGaodeMap';
import { useRoutePlanning } from '@/hooks/useRoutePlanning';
import { PlanningProgress } from '@/components/PlanningProgress';
import { RoutePanel } from '@/components/RoutePanel';
import type { DayRoute, DayPlan, RouteSegment, PlanData } from '@/types/route';

const { Title, Text } = Typography;

/**
 * 示例：路线规划组件
 */
export const RoutePlanningExample: React.FC = () => {
  // 地图容器 ID
  const containerId = 'map-container';

  // 初始化地图
  const { map, mapReady } = useGaodeMap(containerId);

  // 路线规划状态
  const [dayRoutes, setDayRoutes] = useState<DayRoute[]>([]);
  const [selectedDay, setSelectedDay] = useState<number | null>(null);
  const [showProgress, setShowProgress] = useState(false);

  // 初始化路线规划 hook
  const {
    progress,
    planDayRoute,
    planFullRoute,
    renderDayRoute,
    clearRoute,
    cancelPlanning,
  } = useRoutePlanning({
    map,
    onComplete: (result) => {
      message.success('路线规划完成！');
      setDayRoutes(result.dayRoutes);
    },
    onError: (error) => {
      message.error(`规划失败: ${error.message}`);
    },
  });

  // 示例 POI 数据（上海外滩区域）
  const sampleDayPlan: DayPlan = {
    day: 1,
    pois: [
      {
        name: '外滩',
        lat: 31.2397,
        lng: 121.4906,
        subAnchorId: 'bund',
        category: '景点',
      },
      {
        name: '南京路步行街',
        lat: 31.2352,
        lng: 121.4737,
        subAnchorId: 'bund',
        category: '购物',
      },
      {
        name: '豫园',
        lat: 31.2270,
        lng: 121.4920,
        subAnchorId: 'yuyuan',
        category: '景点',
      },
      {
        name: '城隍庙',
        lat: 31.2255,
        lng: 121.4930,
        subAnchorId: 'yuyuan',
        category: '景点',
      },
    ],
  };

  // 多日行程示例
  const sampleMultiDayPlan: PlanData = {
    days: [
      sampleDayPlan,
      {
        day: 2,
        pois: [
          {
            name: '东方明珠',
            lat: 31.2397,
            lng: 121.4998,
            subAnchorId: 'lujiazui',
            category: '景点',
          },
          {
            name: '陆家嘴',
            lat: 31.2350,
            lng: 121.5050,
            subAnchorId: 'lujiazui',
            category: '商业区',
          },
        ],
      },
    ],
  };

  /**
   * 规划单日路线
   */
  const handlePlanDayRoute = async () => {
    if (!mapReady) {
      message.warning('地图尚未准备好');
      return;
    }

    setShowProgress(true);
    try {
      const dayRoute = await planDayRoute(sampleDayPlan);

      if (dayRoute) {
        setDayRoutes([dayRoute]);
        renderDayRoute(dayRoute);
        message.success('单日路线规划完成！');
      }
    } catch (error) {
      console.error('规划错误:', error);
    } finally {
      setShowProgress(false);
    }
  };

  /**
   * 规划完整行程
   */
  const handlePlanFullRoute = async () => {
    if (!mapReady) {
      message.warning('地图尚未准备好');
      return;
    }

    setShowProgress(true);
    try {
      const result = await planFullRoute(sampleMultiDayPlan);

      if (result) {
        message.success('完整行程规划完成！');
      }
    } catch (error) {
      console.error('规划错误:', error);
    } finally {
      setShowProgress(false);
    }
  };

  /**
   * 切换显示某天的路线
   */
  const handleDaySelect = (day: number) => {
    setSelectedDay(day);
    const dayRoute = dayRoutes.find((dr) => dr.day === day);
    if (dayRoute) {
      renderDayRoute(dayRoute);
    }
  };

  /**
   * 路线段点击事件
   */
  const handleSegmentClick = (segment: RouteSegment) => {
    console.log('路线段点击:', segment);
    const distKm = (segment.distance / 1000).toFixed(1);
    const durMin = Math.round(segment.duration / 60);
    message.info(
      `${segment.fromName || '起点'} → ${segment.toName || '终点'}: ${segment.transport} ${durMin}分钟 ${distKm}km`
    );
  };

  /**
   * 清除路线
   */
  const handleClearRoute = () => {
    clearRoute();
    setDayRoutes([]);
    setSelectedDay(null);
    message.info('路线已清除');
  };

  return (
    <div style={{ display: 'flex', height: '100vh' }}>
      {/* 左侧控制面板 */}
      <div style={{ width: 400, padding: 16, overflowY: 'auto', background: '#f5f5f5' }}>
        <Card title="路线规划示例" size="small" style={{ marginBottom: 16 }}>
          <Space direction="vertical" style={{ width: '100%' }}>
            <Text>地图状态: {mapReady ? '✓ 已就绪' : '加载中...'}</Text>

            <Button
              type="primary"
              block
              onClick={handlePlanDayRoute}
              disabled={!mapReady || progress.isPlanning}
            >
              规划单日路线
            </Button>

            <Button
              block
              onClick={handlePlanFullRoute}
              disabled={!mapReady || progress.isPlanning}
            >
              规划完整行程
            </Button>

            <Button
              block
              danger
              onClick={handleClearRoute}
              disabled={progress.isPlanning}
            >
              清除路线
            </Button>

            {progress.isPlanning && (
              <Button block onClick={cancelPlanning}>
                取消规划
              </Button>
            )}
          </Space>
        </Card>

        {/* 路线信息面板 */}
        {dayRoutes.length > 0 && (
          <RoutePanel
            dayRoutes={dayRoutes}
            selectedDay={selectedDay}
            onDaySelect={handleDaySelect}
            onSegmentClick={handleSegmentClick}
          />
        )}

        {/* 使用说明 */}
        <Card title="使用说明" size="small" style={{ marginTop: 16 }}>
          <Typography>
            <Title level={5}>功能说明</Title>
            <ul>
              <li><Text strong>规划单日路线</Text>: 规划上海外滩区域的步行路线</li>
              <li><Text strong>规划完整行程</Text>: 规划多日行程，包含步行和公交</li>
              <li><Text strong>清除路线</Text>: 清除地图上的所有路线</li>
            </ul>

            <Title level={5}>交通方式</Title>
            <ul>
              <li><Text style={{ color: '#1890ff' }}>步行</Text>: 蓝色实线，适合短距离</li>
              <li><Text style={{ color: '#52c41a' }}>地铁/公交</Text>: 绿色虚线，适合长距离</li>
              <li><Text style={{ color: '#fa8c16' }}>自驾</Text>: 橙色虚线，适合驾车</li>
              <li><Text style={{ color: '#722ed1' }}>骑行</Text>: 紫色实线，适合中距离</li>
            </ul>
          </Typography>
        </Card>
      </div>

      {/* 右侧地图容器 */}
      <div style={{ flex: 1, position: 'relative' }}>
        <div
          id={containerId}
          style={{ width: '100%', height: '100%' }}
        />

        {/* 规划进度浮层 */}
        {showProgress && (
          <div style={{ position: 'absolute', bottom: 24, right: 24, width: 360 }}>
            <PlanningProgress
              progress={progress}
              onClose={() => setShowProgress(false)}
            />
          </div>
        )}
      </div>
    </div>
  );
};

export default RoutePlanningExample;
