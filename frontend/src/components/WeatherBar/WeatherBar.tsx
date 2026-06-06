import React, { useState } from 'react';
import { ChevronDown, ChevronUp } from 'lucide-react';
import type { WeatherInfo } from '@/api/types';
import styles from './WeatherBar.module.css';

interface WeatherBarProps {
  weather: WeatherInfo;
  date: string;
}

const getWeatherIcon = (text: string): string => {
  if (text.includes('晴')) return '☀️';
  if (text.includes('云') || text.includes('阴')) return '⛅';
  if (text.includes('雨')) return '🌧️';
  if (text.includes('雪')) return '❄️';
  if (text.includes('雾')) return '🌫️';
  if (text.includes('雷')) return '⛈️';
  return '🌤️';
};

const WeatherBar: React.FC<WeatherBarProps> = ({ weather, date }) => {
  const [expanded, setExpanded] = useState(false);
  const isSevere = weather.is_rainy || weather.is_strong_wind || weather.is_high_temp;

  return (
    <div className={`${styles.container} ${isSevere ? styles.severe : ''}`}>
      <div className={styles.summary} onClick={() => setExpanded(!expanded)}>
        <span className={styles.icon}>{getWeatherIcon(weather.text_day || weather.condition || '')}</span>
        <span className={styles.date}>{date}</span>
        <span className={styles.temp}>
          {weather.temp_low}° ~ {weather.temp_high}°
        </span>
        {weather.weather_tip && (
          <span className={styles.tip}>{weather.weather_tip}</span>
        )}
        {expanded ? <ChevronUp size={16} /> : <ChevronDown size={16} />}
      </div>
      {isSevere && <div className={styles.warning}>⚠️ {weather.weather_tip}</div>}
    </div>
  );
};

export default WeatherBar;
