import React from 'react';
import { Button, Tag, Divider } from 'antd';
import { EnvironmentOutlined, ClockCircleOutlined, ArrowRightOutlined } from '@ant-design/icons';
import { RouteCardData } from '../../types/chat';
import styles from './RouteCard.module.css';

interface RouteCardProps {
  data: RouteCardData;
}

const RouteCard: React.FC<RouteCardProps> = ({ data }) => {
  const handleViewDetail = () => {
    // 跳转到路线详情页
    window.open(`/route/${data.route_id}`, '_blank');
  };

  const handleViewOnMap = () => {
    // 在地图上显示路线
    const pois = data.pois.map(p => `${p.lng},${p.lat}`).join(';');
    window.open(`/map?route=${data.route_id}&pois=${pois}`, '_blank');
  };

  return (
    <div className={styles.routeCard}>
      <div className={styles.header}>
        <div className={styles.titleRow}>
          <EnvironmentOutlined className={styles.icon} />
          <span className={styles.title}>{data.title}</span>
        </div>
        <Tag color="blue">{data.days}天行程</Tag>
      </div>

      {data.preview_image && (
        <div className={styles.preview}>
          <img src={data.preview_image} alt="路线预览" />
        </div>
      )}

      <div className={styles.summary}>{data.summary}</div>

      <Divider className={styles.divider} />

      <div className={styles.poiList}>
        <div className={styles.poiHeader}>📍 途经地点</div>
        {data.pois.slice(0, 5).map((poi, index) => (
          <div key={poi.id} className={styles.poiItem}>
            <span className={styles.poiIndex}>{index + 1}</span>
            <span className={styles.poiName}>{poi.name}</span>
            {index < Math.min(data.pois.length, 5) - 1 && (
              <ArrowRightOutlined className={styles.arrow} />
            )}
          </div>
        ))}
        {data.pois.length > 5 && (
          <div className={styles.morePois}>等{data.pois.length}个地点</div>
        )}
      </div>

      {(data.total_distance || data.estimated_duration) && (
        <>
          <Divider className={styles.divider} />
          <div className={styles.stats}>
            {data.total_distance && (
              <div className={styles.statItem}>
                <EnvironmentOutlined />
                <span>总距离: {data.total_distance}</span>
              </div>
            )}
            {data.estimated_duration && (
              <div className={styles.statItem}>
                <ClockCircleOutlined />
                <span>预计用时: {data.estimated_duration}</span>
              </div>
            )}
          </div>
        </>
      )}

      <Divider className={styles.divider} />

      <div className={styles.actions}>
        <Button type="primary" onClick={handleViewDetail}>
          查看详情
        </Button>
        <Button onClick={handleViewOnMap}>在地图查看</Button>
      </div>
    </div>
  );
};

export default RouteCard;
