import React from 'react';
import { 
  Route, 
  Clock, 
  DollarSign, 
  MapPin,
  Calendar,
  TrendingUp,
  Sun,
  Users,
  Navigation
} from 'lucide-react';
import styles from './BottomStats.module.css';

interface BottomStatsProps {
  stats: {
    totalDistance: number;
    totalDuration: number;
    estimatedCost: number;
    totalStops: number;
    bestTime?: string;
    crowdLevel?: string;
    weather?: string;
  } | null;
  loading?: boolean;
  onStartNavigation?: () => void;
}

const BottomStats: React.FC<BottomStatsProps> = ({ 
  stats, 
  loading,
  onStartNavigation 
}) => {
  if (!stats && !loading) return null;

  const formatDistance = (distance: number): string => {
    if (distance >= 1000) {
      return `${(distance / 1000).toFixed(1)}km`;
    }
    return `${distance}m`;
  };

  const formatDuration = (minutes: number): string => {
    const hours = Math.floor(minutes / 60);
    const mins = minutes % 60;
    if (hours > 0) {
      return mins > 0 ? `${hours}h${mins}m` : `${hours}h`;
    }
    return `${mins}m`;
  };

  const formatCost = (cost: number): string => {
    return `¥${cost.toFixed(0)}`;
  };

  return (
    <footer className={styles.bottomStats}>
      <div className={styles.statsContainer}>
        <div className={styles.statsLeft}>
          <div className={styles.statItem}>
            <Route size={20} className={styles.statIcon} />
            <span className={styles.statValue}>
              {loading ? '--' : formatDistance(stats?.totalDistance || 0)}
            </span>
            <span className={styles.statLabel}>距离</span>
          </div>

          <div className={styles.statItem}>
            <Clock size={20} className={styles.statIcon} />
            <span className={styles.statValue}>
              {loading ? '--' : formatDuration(stats?.totalDuration || 0)}
            </span>
            <span className={styles.statLabel}>时间</span>
          </div>

          <div className={styles.statItem}>
            <DollarSign size={20} className={styles.statIcon} />
            <span className={styles.statValue}>
              {loading ? '--' : formatCost(stats?.estimatedCost || 0)}
            </span>
            <span className={styles.statLabel}>费用</span>
          </div>

          <div className={styles.statItem}>
            <MapPin size={20} className={styles.statIcon} />
            <span className={styles.statValue}>
              {loading ? '--' : stats?.totalStops || 0}
            </span>
            <span className={styles.statLabel}>地点</span>
          </div>

          {stats?.bestTime && (
            <div className={styles.statItem}>
              <Calendar size={20} className={styles.statIcon} />
              <span className={styles.statValue}>
                {loading ? '--' : stats.bestTime}
              </span>
              <span className={styles.statLabel}>最佳时间</span>
            </div>
          )}

          {stats?.crowdLevel && (
            <div className={styles.statItem}>
              <Users size={20} className={styles.statIcon} />
              <span className={styles.statValue}>
                {loading ? '--' : stats.crowdLevel}
              </span>
              <span className={styles.statLabel}>拥挤度</span>
            </div>
          )}

          {stats?.weather && (
            <div className={styles.statItem}>
              <Sun size={20} className={styles.statIcon} />
              <span className={styles.statValue}>
                {loading ? '--' : stats.weather}
              </span>
              <span className={styles.statLabel}>天气</span>
            </div>
          )}
        </div>

        <button 
          className={styles.navButton}
          onClick={onStartNavigation}
          disabled={loading}
        >
          <Navigation size={18} />
          <span>Start Navigation</span>
        </button>
      </div>
    </footer>
  );
};

export default BottomStats;
