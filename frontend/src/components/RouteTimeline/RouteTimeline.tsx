import React, { useState } from 'react';
import { Collapse, Tag, Badge, Button, Tooltip } from 'antd';
import { ChevronDown, ChevronRight, MapPin, Sparkles, Star, Clock, Eye, EyeOff } from 'lucide-react';
import { DailyTimeline } from '@/components/DailyTimeline';
import { useRouteStore } from '@/store/routeStore';
import type { EnroutePOI } from '@/api/types';
import styles from './RouteTimeline.module.css';

const { Panel } = Collapse;

const RouteTimeline: React.FC = () => {
  const dailyRoutes = useRouteStore((s) => s.dailyRoutes);
  const enroutePOIs = useRouteStore((s) => s.enroutePOIs);
  const hiddenEnrouteIds = useRouteStore((s) => s.hiddenEnrouteIds);
  const toggleEnroutePOI = useRouteStore((s) => s.toggleEnroutePOI);
  const trafficSegments = useRouteStore((s) => s.trafficSegments);
  const planMode = useRouteStore((s) => s.planMode) as 'precise' | 'intent' | undefined;
  const setSelectedPoi = useRouteStore((s) => s.setSelectedPoi);
  const error = useRouteStore((s) => s.error);
  
  const [expandedEnroute, setExpandedEnroute] = useState<Record<string, boolean>>({});

  // 创建交通状态到图标的映射
  const getTrafficIcon = (segmentName: string): React.ReactNode => {
    if (!trafficSegments || trafficSegments.length === 0) {
      return segmentName;
    }
    
    const segmentIndex = Math.floor(Math.random() * trafficSegments.length);
    const segment = trafficSegments[segmentIndex];
    
    if (!segment) return segmentName;
    
    const trafficColors: Record<string, string> = {
      smooth: '#52c41a',
      slow: '#FFD100',
      congested: '#f5222d',
      blocked: '#820014',
    };
    
    return (
      <div 
        className={styles.trafficDot}
        style={{ backgroundColor: trafficColors[segment.status] }}
        title={`${segment.road_name}: ${segment.status}`}
      />
    );
  };

  // 切换沿途POI展开状态
  const toggleEnrouteExpand = (enrouteId: string) => {
    setExpandedEnroute(prev => ({
      ...prev,
      [enrouteId]: !prev[enrouteId]
    }));
  };

  // 渲染照片缩略图
  const renderPhotoThumbnails = (poi: EnroutePOI) => {
    if (!poi.photos || poi.photos.length === 0) return null;
    
    return (
      <div className={styles.photoThumbnails}>
        {poi.photos.slice(0, 3).map((photo, idx) => (
          <img
            key={idx}
            src={photo.url}
            alt={photo.title || poi.name}
            className={styles.photoThumb}
            onClick={() => window.open(photo.url, '_blank')}
          />
        ))}
        {poi.photos.length > 3 && (
          <span className={styles.photoMore}>+{poi.photos.length - 3}</span>
        )}
      </div>
    );
  };

  // 渲染沿途POI卡片
  const renderEnroutePOICard = (poi: EnroutePOI, index: number) => {
    const isHidden = hiddenEnrouteIds.has(poi.id);
    const isExpanded = expandedEnroute[poi.id];
    const review = poi.reviews?.[0];

    return (
      <div 
        key={poi.id} 
        className={`${styles.enrouteCard} ${isHidden ? styles.hidden : ''}`}
      >
        {/* 照片缩略图 */}
        {renderPhotoThumbnails(poi)}

        <div className={styles.enrouteHeader}>
          <div className={styles.enrouteTitleRow}>
            <Sparkles size={14} className={styles.enrouteIcon} />
            <span className={styles.enrouteLabel}>E{index + 1}</span>
            <span className={styles.enrouteName}>{poi.name}</span>
            {poi.indoor !== null && poi.indoor !== undefined && (
              <span className={styles.indoorBadge}>{poi.indoor ? '🏠' : '🌳'}</span>
            )}
          </div>
          <div className={styles.enrouteActions}>
            <Tooltip title={isHidden ? '显示此沿途点' : '隐藏此沿途点'}>
              <Button
                type="text"
                size="small"
                icon={isHidden ? <EyeOff size={14} /> : <Eye size={14} />}
                onClick={() => toggleEnroutePOI(poi.id)}
                className={styles.actionBtn}
              />
            </Tooltip>
            <Button
              type="text"
              size="small"
              icon={isExpanded ? <ChevronDown size={14} /> : <ChevronRight size={14} />}
              onClick={() => toggleEnrouteExpand(poi.id)}
              className={styles.actionBtn}
            />
          </div>
        </div>

        <div className={styles.enrouteInfo}>
          <Tag color="purple">{poi.type}</Tag>
          {poi.rating && poi.rating > 0 && (
            <span className={styles.rating}>
              <Star size={12} fill="#FFD100" color="#FFD100" />
              {poi.rating.toFixed(1)}
            </span>
          )}
          {poi.price && (
            <span className={styles.price}>💰 {poi.price}</span>
          )}
          <span className={styles.distanceFromRoute}>
            距路线 {Math.round(poi.distance_from_route)}m
          </span>
          <span className={styles.duration}>
            <Clock size={12} />
            建议停留 {poi.duration_minutes || 20} 分钟
          </span>
        </div>

        {/* 标签 */}
        {poi.tag && poi.tag.length > 0 && (
          <div className={styles.tags}>
            {poi.tag.map((tag, idx) => (
              <Tag key={idx} color="blue">{tag}</Tag>
            ))}
          </div>
        )}

        {poi.open_time && (
          <div className={styles.openTime}>🕐 {poi.open_time}</div>
        )}

        {poi.discovery_reason && (
          <div className={styles.discoveryReason}>
            💡 {poi.discovery_reason}
          </div>
        )}

        {isExpanded && (
          <div className={styles.enrouteDetails}>
            {poi.address && <p className={styles.address}>{poi.address}</p>}
            {poi.tel && (
              <p className={styles.tel}>
                📞 <a href={`tel:${poi.tel}`}>{poi.tel}</a>
              </p>
            )}
            {poi.website && (
              <p className={styles.website}>
                🌐 <a href={poi.website} target="_blank" rel="noopener noreferrer">官网</a>
              </p>
            )}
            {/* 子POI */}
            {poi.children && poi.children.length > 0 && (
              <details className={styles.childrenSection}>
                <summary className={styles.childrenSummary}>
                  内部店铺 ({poi.children.length})
                </summary>
                <div className={styles.childrenList}>
                  {poi.children.map((child, idx) => (
                    <div key={idx} className={styles.childItem}>
                      <span className={styles.childName}>{child.name}</span>
                      {child.rating && <span className={styles.childRating}>⭐ {child.rating.toFixed(1)}</span>}
                    </div>
                  ))}
                </div>
              </details>
            )}
            {review && (
              <div className={styles.review}>
                <div className={styles.reviewContent}>"{review.content.slice(0, 80)}..."</div>
                <div className={styles.reviewAuthor}>—— {review.username}</div>
              </div>
            )}
            <Button
              type="link"
              size="small"
              onClick={() => setSelectedPoi(poi.id)}
              className={styles.locateBtn}
            >
              在地图上查看
            </Button>
          </div>
        )}
      </div>
    );
  };

  // 调试信息
  console.log('RouteTimeline render - dailyRoutes:', dailyRoutes.length, 'enroutePOIs:', enroutePOIs.length, 'error:', error);

  if (dailyRoutes.length === 0 && !error) {
    return (
      <div className={styles.empty}>
        <p>输入旅行描述后点击"生成路线"</p>
      </div>
    );
  }

  if (error) {
    return (
      <div className={styles.errorContainer}>
        <h3>路线生成失败</h3>
        <p>{error}</p>
        <button 
          onClick={() => window.location.reload()} 
          className={styles.retryBtn}
        >
          重新加载
        </button>
      </div>
    );
  }

  // 按天分组沿途POI
  const enrouteByDay: Record<number, EnroutePOI[]> = {};
  enroutePOIs.forEach(poi => {
    const dayIndex = Math.min(
      Math.floor((poi.insert_after_index || 0) / 3),
      dailyRoutes.length - 1
    );
    if (!enrouteByDay[dayIndex + 1]) {
      enrouteByDay[dayIndex + 1] = [];
    }
    enrouteByDay[dayIndex + 1].push(poi);
  });

  return (
    <div className={styles.container}>
      {/* 沿途POI统计横幅 */}
      {enroutePOIs.length > 0 && (
        <div className={styles.enrouteBanner}>
          <Sparkles size={16} color="#722ed1" />
          <span className={styles.bannerText}>
            顺路发现 <strong>{enroutePOIs.length}</strong> 个好去处，
            已为您绕路不超过 <strong>{dailyRoutes[0]?.enroute_extra_duration || 12}</strong> 分钟
          </span>
          <Badge 
            count={enroutePOIs.filter(p => !hiddenEnrouteIds.has(p.id)).length} 
            style={{ backgroundColor: '#722ed1' }}
          />
        </div>
      )}

      <Collapse
        defaultActiveKey={dailyRoutes.map((d) => d.day.toString())}
        ghost
        expandIcon={({ isActive }) =>
          isActive ? <ChevronDown size={16} /> : <ChevronRight size={16} />
        }
      >
        {dailyRoutes.map((route) => (
          <Panel
            key={route.day.toString()}
            header={
              <div className={styles.panelHeader}>
                <div className={styles.headerLeft}>
                  <span className={styles.dayLabel}>第{route.day}天</span>
                  <span className={styles.dateLabel}>{route.date}</span>
                </div>
                <div className={styles.headerRight}>
                  <Tag color="blue">
                    <MapPin size={12} />
                    {route.main_pois?.length || route.pois.length} 主行程
                  </Tag>
                  {enrouteByDay[route.day]?.length > 0 && (
                    <Tag color="purple">
                      <Sparkles size={12} />
                      {enrouteByDay[route.day].length} 顺路
                    </Tag>
                  )}
                </div>
              </div>
            }
          >
            {/* 沿途POI区域 */}
            {enrouteByDay[route.day]?.length > 0 && (
              <div className={styles.enrouteSection}>
                <div className={styles.enrouteSectionTitle}>
                  <Sparkles size={14} color="#722ed1" />
                  顺路推荐
                </div>
                {enrouteByDay[route.day].map((poi, index) => 
                  renderEnroutePOICard(poi, index)
                )}
              </div>
            )}

            {/* 主行程时间轴 */}
            <DailyTimeline 
              dailyRoute={route} 
              onPoiClick={setSelectedPoi}
              trafficSegments={trafficSegments}
              getTrafficIcon={getTrafficIcon}
              planMode={planMode}
            />
          </Panel>
        ))}
      </Collapse>
    </div>
  );
};

export default React.memo(RouteTimeline);
