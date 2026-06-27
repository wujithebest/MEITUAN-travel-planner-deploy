import React, { useEffect, useState, useRef } from 'react';
import { MapPin, Cloud, Sun, CloudRain, Loader, Droplets, Wind } from 'lucide-react';
import { buildApiUrl } from '@/config/api.config';
import styles from './HeaderWeather.module.css';

interface WeatherData {
  city: string;
  temperature: number | string;
  condition: string;
  humidity?: string | number;
  winddirection?: string;
  windpower?: string;
  reporttime?: string;
}

function WeatherIcon({ condition }: { condition: string }) {
  if (condition.includes('雨')) return <CloudRain size={18} />;
  if (condition.includes('晴')) return <Sun size={18} />;
  return <Cloud size={18} />;
}

interface HeaderWeatherProps {
  /** 路线出发地坐标（来自 PlannerPage savedDepartureLocation） */
  location: {
    lat: number;
    lng: number;
    label?: string;
  };
  onSetLocationClick?: () => void;
}

const HeaderWeather: React.FC<HeaderWeatherProps> = ({ location, onSetLocationClick: _onSetLocationClick }) => {
  const [weather, setWeather] = useState<WeatherData | null>(null);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState(false);

  // Ref to track latest request for abort/ignore logic
  const requestIdRef = useRef(0);

  useEffect(() => {
    const requestId = ++requestIdRef.current;
    const controller = new AbortController();
    const label = location.label || '路线出发地';

    const loadWeather = async () => {
      // Not the initial load of this effect invocation — keep existing weather until new data arrives
      const isRefresh = requestIdRef.current > requestId;

      setLoading(true);
      setError(false);
      if (isRefresh) {
        // Don't clear weather on refresh; keep showing current weather while loading
      } else {
        setWeather(null);
      }

      try {
        const response = await fetch(
          buildApiUrl(`/weather/location?lat=${location.lat}&lng=${location.lng}`),
          { signal: controller.signal }
        );

        // Ignore if this request was superseded
        if (requestIdRef.current !== requestId) return;

        const result = await response.json();

        if (!result.success || !result.data) {
          throw new Error(result.message || '天气数据为空');
        }

        setWeather({
          city: result.data.city || label,
          temperature: result.data.temperature,
          condition: result.data.weather,
          humidity: result.data.humidity,
          winddirection: result.data.winddirection,
          windpower: result.data.windpower,
          reporttime: result.data.reporttime,
        });
        setError(false);
      } catch (err: any) {
        if (err.name === 'AbortError') return;
        // Ignore stale
        if (requestIdRef.current !== requestId) return;
        setError(true);
        setWeather(null);
      } finally {
        if (requestIdRef.current === requestId && !controller.signal.aborted) {
          setLoading(false);
        }
      }
    };

    loadWeather();

    // Refresh every 30 minutes for the same departure location
    const timer = window.setInterval(() => {
      const refreshId = ++requestIdRef.current;
      const refreshController = new AbortController();
      const refreshLabel = location.label || '路线出发地';

      (async () => {
        try {
          const response = await fetch(
            buildApiUrl(`/weather/location?lat=${location.lat}&lng=${location.lng}`),
            { signal: refreshController.signal }
          );
          if (requestIdRef.current !== refreshId) return;

          const result = await response.json();
          if (!result.success || !result.data) return;

          setWeather({
            city: result.data.city || refreshLabel,
            temperature: result.data.temperature,
            condition: result.data.weather,
            humidity: result.data.humidity,
            winddirection: result.data.winddirection,
            windpower: result.data.windpower,
            reporttime: result.data.reporttime,
          });
          setError(false);
        } catch {
          // Refresh failure: keep last valid weather
        }
      })();
    }, 30 * 60 * 1000);

    return () => {
      controller.abort();
      window.clearInterval(timer);
    };
  }, [location.lat, location.lng, location.label]);

  const displayLabel = location.label || '路线出发地';

  // 加载中（无旧数据）
  if (loading && !weather) {
    return (
      <div className={`${styles.container} ${styles.loading}`}>
        <Loader size={16} className={styles.spinner} />
        <span>天气加载中...</span>
      </div>
    );
  }

  // 天气数据显示
  if (weather) {
    const prefix = weather.city || displayLabel;
    const hasTemp = weather.temperature !== '' && weather.temperature != null;
    const hasCond = weather.condition && weather.condition !== '';
    const hasHumidity = weather.humidity !== '' && weather.humidity != null;
    const hasWind = (weather.winddirection || weather.windpower);

    if (!hasTemp && !hasCond && !hasHumidity && !hasWind) {
      return (
        <div className={`${styles.container} ${styles.noLocation}`}>
          <MapPin size={14} className={styles.cityIcon} />
          <span className={styles.setText}>{displayLabel} 天气暂不可用</span>
        </div>
      );
    }

    return (
      <div className={styles.container} style={{ backgroundColor: '#fffde7' }}>
        <div className={styles.weatherContent}>
          <div className={styles.cityInfo}>
            <MapPin size={14} className={styles.cityIcon} />
            <span className={styles.cityName}>{prefix}</span>
          </div>
          <div className={styles.tempInfo}>
            <WeatherIcon condition={weather.condition} />
            {hasTemp && <span className={styles.temperature}>{weather.temperature}°</span>}
            {hasCond && <span className={styles.conditionText}>{weather.condition}</span>}
          </div>
          {hasHumidity && (
            <div className={styles.extraInfo}>
              <Droplets size={12} />
              <span className={styles.extraText}>湿度{weather.humidity}%</span>
            </div>
          )}
          {hasWind && (
            <div className={styles.extraInfo}>
              <Wind size={12} />
              <span className={styles.extraText}>
                {weather.winddirection || ''}
                {weather.windpower ? `${weather.windpower}级` : ''}
              </span>
            </div>
          )}
        </div>
      </div>
    );
  }

  // error 但没有 weather 数据
  if (error) {
    return (
      <div className={`${styles.container} ${styles.noLocation}`}>
        <MapPin size={14} className={styles.cityIcon} />
        <span className={styles.setText}>{displayLabel} 天气暂不可用</span>
      </div>
    );
  }

  return null;
};

export default HeaderWeather;
