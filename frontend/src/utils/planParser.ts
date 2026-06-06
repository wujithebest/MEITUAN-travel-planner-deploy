/**
 * 路线数据解析工具
 */

import type { POI, CompletePlan, MapMarkerData, MapPolylineData, RouteRenderData } from '@/types/plan';

export function extractPOINamesFromText(text: string): string[] {
  const patterns = [/【([^】]+)】/g, /「([^」]+)」/g, /"([^"]+)"/g];
  const names: string[] = [];
  for (const pattern of patterns) {
    let match;
    while ((match = pattern.exec(text)) !== null) {
      const name = match[1]?.trim();
      if (name && name.length > 1 && name.length < 20) {
        names.push(name);
      }
    }
  }
  return [...new Set(names)];
}

export function hasRecognizablePOI(text: string): boolean {
  return extractPOINamesFromText(text).length > 0;
}

export function extractAllPOIs(plan: CompletePlan): POI[] {
  const pois: POI[] = [];
  const seenIds = new Set<string>();
  for (const day of plan.days) {
    for (const timeSlot of day.time_slots) {
      for (const activity of timeSlot.activities) {
        if (!seenIds.has(activity.poi.id)) {
          pois.push(activity.poi);
          seenIds.add(activity.poi.id);
        }
      }
    }
    for (const restaurant of day.restaurants) {
      if (!seenIds.has(restaurant.poi.id)) {
        pois.push(restaurant.poi);
        seenIds.add(restaurant.poi.id);
      }
    }
  }
  return pois;
}

export function prepareMapMarkers(plan: CompletePlan): MapMarkerData[] {
  const markers: MapMarkerData[] = [];
  let globalIndex = 0;
  for (let dayIndex = 0; dayIndex < plan.days.length; dayIndex++) {
    const day = plan.days[dayIndex];
    const dayPOIs: POI[] = [];
    for (const timeSlot of day.time_slots) {
      for (const activity of timeSlot.activities) {
        dayPOIs.push(activity.poi);
      }
    }
    for (let poiIndex = 0; poiIndex < dayPOIs.length; poiIndex++) {
      const poi = dayPOIs[poiIndex];
      markers.push({
        poi,
        index: globalIndex++,
        dayIndex,
        isStart: poiIndex === 0 && dayIndex === 0,
        isEnd: poiIndex === dayPOIs.length - 1 && dayIndex === plan.days.length - 1,
        marker_type: poi.type === 'restaurant' ? 'restaurant' : 'attraction',
      });
    }
  }
  return markers;
}

export function prepareMapPolylines(plan: CompletePlan): MapPolylineData[] {
  const polylines: MapPolylineData[] = [];
  const dayColors = ['#1677ff', '#722ed1', '#fa8c16', '#13c2c2', '#eb2f96'];
  for (let dayIndex = 0; dayIndex < plan.days.length; dayIndex++) {
    const day = plan.days[dayIndex];
    const color = dayColors[dayIndex % dayColors.length];
    if (day.daily_polyline) {
      const path = decodePolyline(day.daily_polyline);
      polylines.push({ path, dayIndex, color, strokeStyle: 'solid', strokeWeight: 6 });
    }
  }
  return polylines;
}

export function decodePolyline(polyline: string): [number, number][] {
  const path: [number, number][] = [];
  if (polyline.startsWith('[')) {
    try { return JSON.parse(polyline); } catch { /* continue */ }
  }
  const coordinates = polyline.split(';');
  for (const coord of coordinates) {
    const [lng, lat] = coord.split(',').map(Number);
    if (!isNaN(lng) && !isNaN(lat)) {
      path.push([lng, lat]);
    }
  }
  return path;
}

export function calculateBounds(pois: POI[]): { northEast: [number, number]; southWest: [number, number] } {
  if (pois.length === 0) {
    return { northEast: [121.5, 31.3], southWest: [121.4, 31.2] };
  }
  let minLng = Infinity, maxLng = -Infinity;
  let minLat = Infinity, maxLat = -Infinity;
  for (const poi of pois) {
    minLng = Math.min(minLng, poi.location.lng);
    maxLng = Math.max(maxLng, poi.location.lng);
    minLat = Math.min(minLat, poi.location.lat);
    maxLat = Math.max(maxLat, poi.location.lat);
  }
  const padding = 0.01;
  return { northEast: [maxLng + padding, maxLat + padding], southWest: [minLng - padding, minLat - padding] };
}

export function prepareRouteRenderData(plan: CompletePlan): RouteRenderData {
  const markers = prepareMapMarkers(plan);
  const polylines = prepareMapPolylines(plan);
  const allPOIs = extractAllPOIs(plan);
  const bounds = calculateBounds(allPOIs);
  return { plan, markers, polylines, bounds };
}

export function formatDistance(meters: number): string {
  return meters < 1000 ? `${meters}米` : `${(meters / 1000).toFixed(1)}公里`;
}

export function formatDuration(minutes: number): string {
  if (minutes < 60) return `${minutes}分钟`;
  const hours = Math.floor(minutes / 60);
  const mins = minutes % 60;
  return mins > 0 ? `${hours}小时${mins}分钟` : `${hours}小时`;
}

export function getTransportIcon(transport: string): string {
  const icons: Record<string, string> = { '步行': '🚶', '地铁/公交': '🚇', '自驾': '🚗', '骑行': '🚴', '打车': '🚕' };
  return icons[transport] || '🚶';
}

export function getPOIIcon(type: string): string {
  const icons: Record<string, string> = { scenic: '🏛️', restaurant: '🍽️', hotel: '🏨', transport: '🚇', shopping: '🛍️', entertainment: '🎭' };
  return icons[type] || '📍';
}
