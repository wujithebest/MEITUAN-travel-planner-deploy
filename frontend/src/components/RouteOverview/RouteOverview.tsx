import React from 'react';
import { 
  Star, 
  Sun, 
  Users, 
  Lightbulb,
  Route,
  Clock,
  DollarSign,
  MapPin
} from 'lucide-react';
import styles from './RouteOverview.module.css';

interface RouteOverviewProps {
  stats: {
    totalDistance: number;
    totalDuration: number;
    estimatedCost: number;
    totalStops: number;
  };
  weather?: {
    city: string;
    temperature: number;
    condition: string;
  };
  crowdLevel?: 'Low' | 'Moderate' | 'High';
  onViewPlanB?: () => void;
}

const RouteOverview: React.FC<RouteOverviewProps> = ({
  stats,
  weather = { city: 'Beijing', temperature: 23, condition: 'Sunny' },
  crowdLevel = 'Moderate',
  onViewPlanB
}) => {
  const formatDistance = (distance: number): string => {
    if (distance >= 1000) {
      return `${(distance / 1000).toFixed(1)} km`;
    }
    return `${distance} m`;
  };

  const formatDuration = (minutes: number): string => {
    const hours = Math.floor(minutes / 60);
    const mins = minutes % 60;
    if (hours > 0) {
      return mins > 0 ? `${hours}h ${mins}m` : `${hours}h`;
    }
    return `${mins}m`;
  };

  const formatCost = (cost: number): string => {
    return `¥${cost.toFixed(0)}`;
  };

  const tips = [
    '建议早上8点前出发，避开早高峰',
    '景点间可选择地铁出行，更省时',
    '午餐时间建议12:00-13:00',
    '傍晚时分适合拍照，光线最佳'
  ];

  return (
    <div className={styles.container}>
      <div className={styles.card}>
        {/* Left: AI Assistant */}
        <div className={styles.aiSection}>
          <div className={styles.aiHeader}>
            <Star size={20} className={styles.aiIcon} />
            <span className={styles.aiTitle}>AI Assistant</span>
          </div>
          <p className={styles.aiDescription}>
            Your personalized travel assistant is ready to help optimize your journey.
          </p>
          
          <div className={styles.weatherInfo}>
            <Sun size={16} className={styles.weatherIcon} />
            <span className={styles.weatherText}>
              Weather in {weather.city} {weather.temperature}°C {weather.condition}
            </span>
          </div>
          
          <div className={styles.crowdInfo}>
            <Users size={16} className={styles.crowdIcon} />
            <span className={styles.crowdText}>
              Crowd Level: {crowdLevel}
            </span>
          </div>
          
          <div className={styles.planB}>
            <span className={styles.planBBadge}>Plan B available</span>
            <button className={styles.planBButton} onClick={onViewPlanB}>
              View Plan B
            </button>
          </div>
        </div>

        {/* Middle: Route Overview */}
        <div className={styles.routeSection}>
          <div className={styles.statsRow}>
            <div className={styles.statCard}>
              <Route size={20} className={styles.statIcon} />
              <span className={styles.statValue}>{formatDistance(stats.totalDistance)}</span>
              <span className={styles.statLabel}>Total Distance</span>
            </div>
            
            <div className={styles.statCard}>
              <Clock size={20} className={styles.statIcon} />
              <span className={styles.statValue}>{formatDuration(stats.totalDuration)}</span>
              <span className={styles.statLabel}>Total Time</span>
            </div>
            
            <div className={styles.statCard}>
              <DollarSign size={20} className={styles.statIcon} />
              <span className={styles.statValue}>{formatCost(stats.estimatedCost)}</span>
              <span className={styles.statLabel}>Est. Cost</span>
            </div>
            
            <div className={styles.statCard}>
              <MapPin size={20} className={styles.statIcon} />
              <span className={styles.statValue}>{stats.totalStops}</span>
              <span className={styles.statLabel}>Stops</span>
            </div>
          </div>
          
          <div className={styles.tipsList}>
            {tips.map((tip, index) => (
              <div key={index} className={styles.tipItem}>
                <Lightbulb size={14} className={styles.tipIcon} />
                <span className={styles.tipText}>{tip}</span>
              </div>
            ))}
          </div>
        </div>

        {/* Right: Empty or Ad Space */}
        <div className={styles.rightSection}>
          {/* Reserved for future use */}
        </div>
      </div>
    </div>
  );
};

export default RouteOverview;
