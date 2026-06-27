import React, { useEffect, useState, useRef } from 'react';
import { MapPin, Cloud, Sun, CloudRain, Loader, Droplets, Wind } from 'lucide-react';
import { buildApiUrl } from '@/config/api.config';
import styles from './HeaderWeather.module.css';

const DEFAULT_WEATHER_LOCATION = {
  lat: 31.2304,
  lng: 121.4737,
};

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

  // Ref: 设备天气是否已成功并设为了当前显示
  const deviceWeatherWonRef = useRef(false);

  useEffect(() => {
    let cancelled = false;

    // ── 请求：设备坐标天气 ──
    const fetchDeviceWeather = async (lat: number, lng: number) => {
      try {
        const response = await fetch(buildApiUrl(`/weather/location?lat=${lat}&lng=${lng}`));
        const result = await response.json();
        if (cancelled) return;

        if (result.success && result.data) {
          // 设备天气成功 → 覆盖天气 + 标记 isLocated
          setWeather({
            city: result.data.city,
            temperature: result.data.temperature,
            condition: result.data.weather,
            humidity: result.data.humidity,
            winddirection: result.data.winddirection,
            windpower: result.data.windpower,
            reporttime: result.data.reporttime,
          });
          setIsLocated(true);
          setError(false);
          setLoading(false);
          deviceWeatherWonRef.current = true;
        }
        // 设备天气失败 → 什么都不做，保留已有天气
      } catch (err) {
        console.error('设备天气获取失败:', err);
        // 失败不覆盖已有天气
      }
    };

    // ── 请求：默认上海天气（兜底） ──
    const fetchDefaultCityWeather = async () => {
      try {
        const { lat, lng } = DEFAULT_WEATHER_LOCATION;
        const response = await fetch(buildApiUrl(`/weather/location?lat=${lat}&lng=${lng}`));
        const result = await response.json();
        if (cancelled) return;

        if (result.success && result.data) {
          // 如果设备天气已经成功，默认天气不再覆盖
          if (deviceWeatherWonRef.current) return;
          setWeather({
            city: result.data.city || '上海',
            temperature: result.data.temperature ?? 25,
            condition: result.data.weather ?? '晴',
            humidity: result.data.humidity,
            winddirection: result.data.winddirection,
            windpower: result.data.windpower,
            reporttime: result.data.reporttime,
          });
          setIsLocated(false);
          setError(false);
          setLoading(false);
          return;
        }
        // 默认请求 success=false — 不覆盖
      } catch (err) {
        console.error('默认天气获取失败:', err);
        // 不覆盖已有天气
      }
    };

    setLoading(true);

    // 立即发起默认城市天气（可靠兜底）
    fetchDefaultCityWeather();

    // 同时尝试设备定位 → 成功后发起设备天气
    if (navigator.geolocation) {
      navigator.geolocation.getCurrentPosition(
        (position) => {
          if (cancelled) return;
          const { latitude, longitude, accuracy } = position.coords;
          if (accuracy && accuracy > 300) {
            console.warn(`[LocationDebug] HeaderWeather geolocation accuracy is low: ${accuracy}m`);
          }
          // 收到坐标 ≠ 天气成功；不在这里设置 isLocated 或 geoResolved
          fetchDeviceWeather(latitude, longitude);
        },
        (err) => {
          console.warn('定位失败，使用默认城市天气:', err.message);
          // 默认城市天气请求已并行发起，无需额外操作
        },
        { enableHighAccuracy: false, timeout: 8000, maximumAge: 60000 }
      );
    }

    // ── 每 30 分钟刷新 ──
    const interval = setInterval(() => {
      if (navigator.geolocation) {
        navigator.geolocation.getCurrentPosition(
          (pos) => fetchDeviceWeather(pos.coords.latitude, pos.coords.longitude),
          // 刷新定位失败：请求一次默认城市天气
          () => fetchDefaultCityWeather(),
          { enableHighAccuracy: false, timeout: 8000, maximumAge: 60000 }
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

    // 如果连温度和天气描述都没有，显示不可用
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
