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

const HeaderWeather: React.FC<HeaderWeatherProps> = ({ location, onSetLocationClick }) => {
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

  const displayLabel = location.label || '请选择';
  const prefix = weather?.city || displayLabel;

  // ── weather node (loading / data / error) ──
  let weatherNode: React.ReactNode;
  if (loading && !weather) {
    weatherNode = (
      <div className={styles.weatherStatus}>
        <Loader size={16} className={styles.spinner} />
        <span>天气加载中...</span>
      </div>
    );
  } else if (weather) {
    const hasTemp = weather.temperature !== '' && weather.temperature != null;
    const hasCond = weather.condition && weather.condition !== '';
    const hasHumidity = weather.humidity !== '' && weather.humidity != null;
    const hasWind = !!(weather.winddirection || weather.windpower);
    weatherNode = (
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
          <span className={styles.extraStat}>
            <Droplets size={12} /> {weather.humidity}%
          </span>
        )}
        {hasWind && (
          <span className={styles.extraStat}>
            <Wind size={12} /> {weather.winddirection}{weather.windpower || ''}
          </span>
        )}
      </div>
    );
  } else {
    weatherNode = (
      <div className={styles.weatherStatus}>
        <Cloud size={16} />
        <span>天气暂不可用</span>
      </div>
    );
  }

  // ── unified layout: departure button | weather ──
  return (
    <div className={styles.container}>
      <button
        type="button"
        className={styles.departureButton}
        onClick={onSetLocationClick}
        title={`路线出发点：${displayLabel}`}
        aria-label={`修改路线出发点，当前为${displayLabel}`}
      >
        <MapPin size={16} />
        <span className={styles.departureTitle}>路线出发点</span>
        <span className={styles.departureValue}>{displayLabel}</span>
      </button>

      <div className={styles.divider} aria-hidden="true" />

      <div className={styles.weatherArea}>
        {weatherNode}
      </div>
    </div>
  );
};

export default HeaderWeather;
