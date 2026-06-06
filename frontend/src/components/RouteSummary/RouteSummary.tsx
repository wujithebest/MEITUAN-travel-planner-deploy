import React from 'react';
import { Card, Tag, Statistic, Row, Col, Divider } from 'antd';
import { 
  MapPin, 
  Sparkles, 
  Clock, 
  Route, 
  RefreshCw,
  TrendingUp
} from 'lucide-react';
import { useRouteStore } from '@/store/routeStore';
import styles from './RouteSummary.module.css';

const RouteSummary: React.FC = () => {
  const summary = useRouteStore((s) => s.summary);

  if (!summary) {
    return null;
  }

  const formatDuration = (minutes: number): string => {
    if (minutes < 60) {
      return `${minutes}分钟`;
    }
    const hours = Math.floor(minutes / 60);
    const mins = minutes % 60;
    return mins > 0 ? `${hours}小时${mins}分钟` : `${hours}小时`;
  };

  const formatDistance = (distance: number): string => {
    if (distance < 1000) {
      return `${Math.round(distance)}米`;
    }
    return `${(distance / 1000).toFixed(1)}公里`;
  };

  return (
    <Card className={styles.container} size="small">
      {/* 规划状态横幅 */}
      {(summary.plan_count || 0) > 1 && (
        <div className={styles.planBanner}>
          <RefreshCw size={14} />
          <span>
            规划次数：{summary.plan_count}次
            <span className={styles.planSteps}>
              （原始路线 → 智能增强）
            </span>
          </span>
        </div>
      )}

      {/* 主要统计 */}
      <Row gutter={[16, 12]} className={styles.statsRow}>
        <Col span={6}>
          <Statistic
            title="主行程"
            value={summary.main_pois_count || summary.total_pois}
            suffix="处"
            prefix={<MapPin className={styles.statIcon} style={{ color: '#CC9900' }} />}
            valueStyle={{ color: '#CC9900', fontSize: 18 }}
          />
        </Col>
        
        <Col span={6}>
          <Statistic
            title="顺路推荐"
            value={summary.enroute_pois_count}
            suffix="处"
            prefix={<Sparkles className={styles.statIcon} style={{ color: '#722ed1' }} />}
            valueStyle={{ color: '#722ed1', fontSize: 18 }}
          />
        </Col>
        
        <Col span={6}>
          <Statistic
            title="总路程"
            value={formatDistance(summary.total_distance)}
            prefix={<Route className={styles.statIcon} style={{ color: '#52c41a' }} />}
            valueStyle={{ color: '#52c41a', fontSize: 18 }}
          />
        </Col>
        
        <Col span={6}>
          <Statistic
            title="预计用时"
            value={formatDuration(summary.total_duration)}
            prefix={<Clock className={styles.statIcon} style={{ color: '#CC9900' }} />}
            valueStyle={{ color: '#CC9900', fontSize: 18 }}
          />
        </Col>
      </Row>

      <Divider className={styles.divider} />

      {/* 标签展示 */}
      <div className={styles.tagsRow}>
        <div className={styles.tagGroup}>
          <span className={styles.tagLabel}>主行程</span>
          <Tag color="blue" className={styles.tag}>
            <MapPin size={12} />
            {summary.main_pois_count || summary.total_pois} 个目的地
          </Tag>
        </div>
        
        {(summary.enroute_pois_count || 0) > 0 && (
          <div className={styles.tagGroup}>
            <span className={styles.tagLabel}>顺路推荐</span>
            <Tag color="purple" className={styles.tag}>
              <Sparkles size={12} />
              {summary.enroute_pois_count} 个好去处
            </Tag>
          </div>
        )}
      </div>

      {/* 额外用时提示 */}
      {(summary.enroute_extra_duration || 0) > 0 && (
        <div className={styles.extraTime}>
          <TrendingUp size={14} color="#CC9900" />
          <span>
            因顺路推荐额外用时 
            <strong style={{ color: '#CC9900', margin: '0 4px' }}>
              +{summary.enroute_extra_duration}分钟
            </strong>
            ，发现更多精彩
          </span>
        </div>
      )}

      {/* 路线质量 */}
      {summary.route_quality && (
        <div className={styles.qualityRow}>
          <span className={styles.qualityLabel}>路线质量：</span>
          <Tag 
            color={
              summary.route_quality === 'excellent' ? 'green' :
              summary.route_quality === 'good' ? 'blue' :
              summary.route_quality === 'fair' ? 'orange' : 'red'
            }
            className={styles.qualityTag}
          >
            {summary.route_quality === 'excellent' ? '优秀' :
             summary.route_quality === 'good' ? '良好' :
             summary.route_quality === 'fair' ? '一般' : '待优化'}
          </Tag>
        </div>
      )}

      {/* 交通方式 */}
      <div className={styles.transportRow}>
        <span className={styles.transportLabel}>出行方式：</span>
        <Tag className={styles.transportTag}>
          {summary.transportation === 'driving' ? '驾车' :
           summary.transportation === 'walking' ? '步行' :
           summary.transportation === 'transit' ? '公共交通' :
           summary.transportation === 'bicycling' ? '骑行' : summary.transportation}
        </Tag>
      </div>
    </Card>
  );
};

export default RouteSummary;
