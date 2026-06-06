import React, { useEffect, useState } from 'react';
import { MapPin, Cloud, Sun, CloudRain, Loader, Droplets, Wind } from 'lucide-react';
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
  onSetLocationClick?: () => void;
}

const HeaderWeather: React.FC<HeaderWeatherProps> = ({ onSetLocationClick: _onSetLocationClick }) => {
  const [weather, setWeather] = useState<WeatherData | null>(null);
  const [loading, setLoading] = useState(false);
  const [isLocated, setIsLocated] = useState(false);
  const [error, setError] = useState(false);

  useEffect(() => {
    let cancelled = false;

    const fetchWeatherByCoords = async (lat: number, lng: number) => {
      try {
        const response = await fetch(`/api/weather/location?lat=${lat}&lng=${lng}`);
        const result = await response.json();
        if (result.success && result.data && !cancelled) {
          setWeather({
            city: result.data.city,
            temperature: result.data.temperature,
            condition: result.data.weather,
            humidity: result.data.humidity,
            winddirection: result.data.winddirection,
            windpower: result.data.windpower,
            reporttime: result.data.reporttime,
          });
          setError(false);
        } else if (!cancelled) {
          setError(true);
        }
      } catch (err) {
        console.error('定位天气获取失败:', err);
        if (!cancelled) setError(true);
      } finally {
        if (!cancelled) setLoading(false);
      }
    };

    const fetchShanghaiFallback = async () => {
      try {
        const response = await fetch('/api/weather/current');
        const result = await response.json();
        if (result.success && result.data && !cancelled) {
          setWeather({
            city: '上海',
            temperature: result.data.temp ?? 25,
            condition: result.data.text ?? '晴',
            humidity: result.data.humidity,
            winddirection: result.data.winddirection,
            windpower: result.data.windpower,
          });
          setError(false);
          return;
        }
      } catch {}
      if (!cancelled) {
        setWeather({ city: '上海', temperature: '', condition: '' });
        setError(true);
        setLoading(false);
      }
    };

    setLoading(true);

    // 尝试浏览器定位（高精度；天气仅展示，不写入路线规划 state）
    if (navigator.geolocation) {
      navigator.geolocation.getCurrentPosition(
        (position) => {
          if (cancelled) return;
          const { latitude, longitude, accuracy } = position.coords;
          if (accuracy && accuracy > 300) {
            console.warn(`[LocationDebug] HeaderWeather geolocation accuracy is low: ${accuracy}m`);
          }
          setIsLocated(true);
          fetchWeatherByCoords(latitude, longitude);
        },
        (err) => {
          console.warn('定位失败，降级到上海天气:', err.message);
          if (!cancelled) fetchShanghaiFallback();
        },
        { enableHighAccuracy: true, timeout: 15000, maximumAge: 30000 }
      );
    } else {
      if (!cancelled) fetchShanghaiFallback();
    }

    // 每 30 分钟刷新（天气定位不写入路线状态，仅用于展示）
    const interval = setInterval(() => {
      if (navigator.geolocation) {
        navigator.geolocation.getCurrentPosition(
          (pos) => fetchWeatherByCoords(pos.coords.latitude, pos.coords.longitude),
          () => fetchShanghaiFallback(),
          { enableHighAccuracy: true, timeout: 15000, maximumAge: 30000 }
        );
      }
    }, 30 * 60 * 1000);

    return () => {
      cancelled = true;
      clearInterval(interval);
    };
  }, []);

  // 加载中
  if (loading && !weather) {
    return (
      <div className={`${styles.container} ${styles.loading}`}>
        <Loader size={16} className={styles.spinner} />
        <span>加载中...</span>
      </div>
    );
  }

  // 天气数据显示
  if (weather) {
    const prefix = isLocated ? '当前位置' : weather.city;
    const hasTemp = weather.temperature !== '' && weather.temperature != null;
    const hasCond = weather.condition && weather.condition !== '';
    const hasHumidity = weather.humidity !== '' && weather.humidity != null;
    const hasWind = (weather.winddirection || weather.windpower);

    // 如果连温度和天气都没有，显示不可用
    if (!hasTemp && !hasCond && !hasHumidity && !hasWind) {
      return (
        <div className={`${styles.container} ${styles.noLocation}`}>
          <MapPin size={14} className={styles.cityIcon} />
          <span className={styles.setText}>{prefix} 天气暂不可用</span>
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
        <span className={styles.setText}>天气暂不可用</span>
      </div>
    );
  }

  return null;
};

export default HeaderWeather;
