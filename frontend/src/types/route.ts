/**
 * Local route-planning types used by the browser-side AMap planner.
 *
 * These types intentionally stay separate from src/api/types.ts, which
 * mirrors the backend JSON contract.
 */

export type TransportMode = '步行' | '自驾' | '骑行' | '地铁/公交';
export type TimePeriod = 'morning' | 'lunch' | 'afternoon' | 'dinner' | 'evening';

export interface POI {
  id?: string;
  name: string;
  lat: number;
  lng: number;
  subAnchorId?: string;
  category?: string;
}

export interface RoutePoint {
  name: string;
  location: [number, number];
  kind: 'start' | 'waypoint' | 'enroute' | 'meal';
  period: TimePeriod;
  isWaypoint: boolean;
  tooltip?: string;
  walkMin?: number;
  label?: string;
}

export interface RouteSegment {
  polyline: [number, number][];
  transport: TransportMode;
  distance: number;
  duration: number;
  instructions?: string[];
  fromName?: string;
  toName?: string;
  color?: string;
  isDashed?: boolean;
}

export interface DayRoute {
  day: number;
  segments: RouteSegment[];
  totalDistance: number;
  totalDuration: number;
  center?: [number, number];
  points?: RoutePoint[];
}

export interface DayPlan {
  day: number;
  pois: POI[];
}

export interface PlanData {
  days: DayPlan[];
}

export interface PlanningProgress {
  isPlanning: boolean;
  progress: number;
  message: string;
  messages: string[];
}

export const PERIOD_COLORS: Record<TimePeriod, { primary: string; light: string }> = {
  morning: { primary: '#E67E22', light: '#F5CBA7' },
  lunch: { primary: '#D35400', light: '#FAD7A1' },
  afternoon: { primary: '#2980B9', light: '#AED6F1' },
  dinner: { primary: '#C0392B', light: '#F5B7B1' },
  evening: { primary: '#8E44AD', light: '#D2B4DE' },
};

export const TRANSPORT_STYLES: Record<
  string,
  {
    strokeColor: string;
    strokeWeight: number;
    weight: number;
    isDashed?: boolean;
    dashArray?: number[];
    showDirection?: boolean;
  }
> = {
  '步行': { strokeColor: '#27AE60', strokeWeight: 4, weight: 4, showDirection: true },
  '地铁/公交': { strokeColor: '#3498DB', strokeWeight: 3, weight: 3, isDashed: true, dashArray: [10, 10] },
  '自驾': { strokeColor: '#E67E22', strokeWeight: 3, weight: 3, isDashed: true, dashArray: [10, 10], showDirection: true },
  '骑行': { strokeColor: '#9B59B6', strokeWeight: 3, weight: 3, isDashed: true, dashArray: [5, 5], showDirection: true },
};
