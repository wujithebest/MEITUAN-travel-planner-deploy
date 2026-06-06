import React from 'react';
import { useSortable } from '@dnd-kit/sortable';
import { CSS } from '@dnd-kit/utilities';
import { POICard } from '@/components/POICard';
import { WeatherBar } from '@/components/WeatherBar';
import type { DailyRoute, TrafficSegment } from '@/api/types';
import { formatDistance, formatDuration } from '@/utils/formatters';
import styles from './DailyTimeline.module.css';

interface DailyTimelineProps {
  dailyRoute: DailyRoute;
  onPoiClick: (poiId: string) => void;
  trafficSegments?: TrafficSegment[];
  getTrafficIcon?: (segmentName: string) => React.ReactNode;
  planMode?: 'precise' | 'intent'; // 计划模式
}

const SortablePOI: React.FC<{
  poi: DailyRoute['pois'][0];
  index: number;
  isFirst: boolean;
  isLast: boolean;
  onClick: () => void;
  isRecommended?: boolean; // 是否推荐POI
}> = ({ poi, index, isFirst, isLast, onClick, isRecommended = false }) => {
  const { attributes, listeners, setNodeRef, transform, transition, isDragging } = useSortable({
    id: poi.id,
  });

  const style = {
    transform: CSS.Transform.toString(transform),
    transition,
    opacity: isDragging ? 0.5 : 1,
  };

  return (
    <div ref={setNodeRef} style={style} {...attributes} {...listeners} className={styles.sortableItem}>
      <POICard poi={poi} index={index} isStart={isFirst} isEnd={isLast} onClick={onClick} isRecommended={isRecommended} />
    </div>
  );
};

const DailyTimeline: React.FC<DailyTimelineProps> = ({ dailyRoute, onPoiClick, trafficSegments, getTrafficIcon, planMode }) => {
  const pois = dailyRoute.pois || [];

  // 创建交通状态到图标的映射
  const createTrafficIcon = (segmentName: string): React.ReactNode => {
    if (!trafficSegments || !getTrafficIcon) {
      return segmentName;
    }
    return getTrafficIcon(segmentName);
  };

  // 检查是否为推荐POI（意图模式下的所有POI都标记为推荐）
  const isRecommendedPOI = (index: number) => {
    return planMode === 'intent' && index >= 0;
  };

  return (
    <div className={styles.container}>
      <div className={styles.header}>
        <span className={styles.day}>第{dailyRoute.day}天</span>
        <span className={styles.date}>{dailyRoute.date}</span>
        <span className={styles.stats}>
          {formatDistance(dailyRoute.total_distance || 0)} · {formatDuration(dailyRoute.total_duration || 0)}
        </span>
      </div>

      {dailyRoute.weather_tip && (
        <WeatherBar 
          weather={{ 
            forecast_date: dailyRoute.date || '',
            city: '上海',
            text_day: '',
            text_night: '',
            temp_high: 0,
            temp_low: 0,
            wind_level: 0,
            wind_direction: '',
            humidity: 0,
            rain_probability: 0,
            is_rainy: false,
            is_high_temp: false,
            is_strong_wind: false,
            indoor_recommended: false,
            weather_tip: dailyRoute.weather_tip
          }} 
          date={dailyRoute.date || ''} 
        />
      )}

      <div className={styles.timeline}>
        {pois.map((poi, index) => (
          <React.Fragment key={poi.id}>
            <SortablePOI
              poi={poi}
              index={index + 1}
              isFirst={index === 0}
              isLast={index === pois.length - 1}
              onClick={() => onPoiClick(poi.id)}
              isRecommended={isRecommendedPOI(index)}
            />
            {index < pois.length - 1 && (
              <div className={styles.segment}>
                <div className={styles.segmentLine} />
                <div className={styles.segmentInfo}>
                  <span>{createTrafficIcon(poi.metro_hint || '步行')}</span>
                </div>
              </div>
            )}
          </React.Fragment>
        ))}
      </div>
    </div>
  );
};

export default React.memo(DailyTimeline);
