import client from './client';
import type { WeatherInfo } from './types';

export async function getWeather(
  location: [number, number],
  date: string
): Promise<WeatherInfo> {
  const [lng, lat] = location;
  // client baseURL 已经是 /api，所以这里用 /weather 而不是 /api/weather
  const { data } = await client.get<WeatherInfo>('/weather', {
    params: { lng, lat, date },
  });
  return data;
}

export async function getWeatherBatch(
  location: [number, number],
  dates: string[]
): Promise<WeatherInfo[]> {
  const [lng, lat] = location;
  // client baseURL 已经是 /api，所以这里用 /weather/batch 而不是 /api/weather/batch
  const { data } = await client.post<WeatherInfo[]>('/weather/batch', {
    lng,
    lat,
    dates,
  });
  return data;
}
