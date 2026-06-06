import React, { useState } from 'react';
import { Badge, Button, Card, List, Popover, Tag, Tooltip } from 'antd';
import { Sparkles, MapPin, Star, Clock, ChevronDown, ChevronUp, Eye, EyeOff } from 'lucide-react';
import { useRouteStore } from '@/store/routeStore';
import type { EnroutePOI } from '@/api/types';
import styles from './EnrouteBadge.module.css';

const EnrouteBadge: React.FC = () => {
  const enroutePOIs = useRouteStore((s) => s.enroutePOIs);
  const hiddenEnrouteIds = useRouteStore((s) => s.hiddenEnrouteIds);
  const toggleEnroutePOI = useRouteStore((s) => s.toggleEnroutePOI);
  const setSelectedPoi = useRouteStore((s) => s.setSelectedPoi);
  const [popoverOpen, setPopoverOpen] = useState(false);

  if (enroutePOIs.length === 0) {
    return null;
  }

  const visibleCount = enroutePOIs.filter(p => !hiddenEnrouteIds.has(p.id)).length;
  const totalExtraDuration = enroutePOIs
    .filter(p => !hiddenEnrouteIds.has(p.id))
    .reduce((sum, p) => sum + (p.duration_minutes || 20), 0);

  const handlePoiClick = (poi: EnroutePOI) => {
    setSelectedPoi(poi.id);
    setPopoverOpen(false);
  };

  const popoverContent = (
    <div className={styles.popoverContent}>
      <div className={styles.popoverHeader}>
        <Sparkles size={16} color="#722ed1" />
        <span className={styles.popoverTitle}>顺路发现</span>
        <Tag color="purple">{visibleCount} / {enroutePOIs.length}</Tag>
      </div>
      
      <List
        size="small"
        dataSource={enroutePOIs}
        renderItem={(poi, index) => {
          const isHidden = hiddenEnrouteIds.has(poi.id);
          return (
            <List.Item
              className={`${styles.poiItem} ${isHidden ? styles.poiItemHidden : ''}`}
              onClick={() => handlePoiClick(poi)}
            >
              <div className={styles.poiItemContent}>
                <div className={styles.poiItemLeft}>
                  <span className={styles.poiIndex}>E{index + 1}</span>
                  <div className={styles.poiInfo}>
                    <div className={styles.poiName}>{poi.name}</div>
                    <div className={styles.poiMeta}>
                      <Tag color="purple" className={styles.poiType}>{poi.type}</Tag>
                      {poi.rating && (
                        <span className={styles.poiRating}>
<Star size={10} fill="#FFD100" color="#FFD100" />
                          {poi.rating.toFixed(1)}
                        </span>
                      )}
                      <span className={styles.poiDistance}>
                        <MapPin size={10} />
                        {Math.round(poi.distance_from_route)}m
                      </span>
                    </div>
                  </div>
                </div>
                <Tooltip title={isHidden ? '显示' : '隐藏'}>
                  <Button
                    type="text"
                    size="small"
                    icon={isHidden ? <EyeOff size={14} /> : <Eye size={14} />}
                    onClick={(e) => {
                      e.stopPropagation();
                      toggleEnroutePOI(poi.id);
                    }}
                    className={styles.toggleBtn}
                  />
                </Tooltip>
              </div>
            </List.Item>
          );
        }}
        className={styles.poiList}
      />
      
      <div className={styles.popoverFooter}>
        <Clock size={12} color="#666" />
        <span>预计额外用时约 {totalExtraDuration} 分钟</span>
      </div>
    </div>
  );

  return (
    <div className={styles.container}>
      <Popover
        content={popoverContent}
        title={null}
        trigger="click"
        open={popoverOpen}
        onOpenChange={setPopoverOpen}
        placement="topLeft"
        overlayClassName={styles.popover}
      >
        <Badge count={visibleCount} size="small" offset={[-5, 5]}>
          <Button
            type="primary"
            className={styles.badge}
            icon={<Sparkles size={14} />}
          >
            <span className={styles.badgeText}>
              顺路发现 {visibleCount} 个
            </span>
            {popoverOpen ? <ChevronUp size={12} /> : <ChevronDown size={12} />}
          </Button>
        </Badge>
      </Popover>
    </div>
  );
};

export default EnrouteBadge;
