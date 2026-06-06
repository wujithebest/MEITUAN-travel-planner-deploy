import dayjs from 'dayjs';

export function formatDistance(meters: number): string {
  if (meters < 1000) return `${meters}m`;
  return `${(meters / 1000).toFixed(1)}km`;
}

export function formatDuration(seconds: number): string {
  const hours = Math.floor(seconds / 3600);
  const minutes = Math.floor((seconds % 3600) / 60);
  if (hours > 0) return `${hours}h ${minutes}min`;
  return `${minutes}min`;
}

export function formatDate(date: string | dayjs.Dayjs): string {
  return dayjs(date).format('MM月DD日');
}

export function formatDateFull(date: string | dayjs.Dayjs): string {
  return dayjs(date).format('YYYY年MM月DD日');
}

export function formatTime(seconds: number): string {
  const date = dayjs().startOf('day').add(seconds, 'second');
  return date.format('HH:mm');
}

export function getWeatherIcon(condition: string): string {
  const icons: Record<string, string> = {
    sunny: '☀️',
    cloudy: '⛅',
    rainy: '🌧️',
    stormy: '⛈️',
    snowy: '❄️',
    foggy: '🌫️',
  };
  return icons[condition] || '🌤️';
}

export function getWeatherColor(condition: string): string {
  const colors: Record<string, string> = {
    sunny: '#FFD100',
    cloudy: '#8c8c8c',
    rainy: '#FFD100',
    stormy: '#f5222d',
    snowy: '#FFD100',
    foggy: '#8c8c8c',
  };
  return colors[condition] || '#FFD100';
}

export function getTrafficLabel(status: string): string {
  const labels: Record<string, string> = {
    smooth: '畅通',
    slow: '缓行',
    congested: '拥堵',
    blocked: '严重拥堵',
  };
  return labels[status] || status;
}

export function getTrafficColor(status: string): string {
  const colors: Record<string, string> = {
    smooth: '#52c41a',
    slow: '#FFD100',
    congested: '#f5222d',
    blocked: '#722ed1',
  };
  return colors[status] || '#FFD100';
}

export function simplifyPolyline(points: [number, number][], maxPoints: number = 1000): [number, number][] {
  if (points.length <= maxPoints) return points;
  const step = Math.ceil(points.length / maxPoints);
  const result: [number, number][] = [];
  for (let i = 0; i < points.length; i += step) {
    result.push(points[i]);
  }
  if (result[result.length - 1] !== points[points.length - 1]) {
    result.push(points[points.length - 1]);
  }
  return result;
}
