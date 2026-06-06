/**
 * 后端AI旅行规划相关类型定义
 */

export interface UserProfile {
  user_id?: string;
  preferences?: {
    budget?: string;
    transport?: string;
    pace?: 'relaxed' | 'moderate' | 'intense';
  };
}

export interface ParsedIntent {
  destination: string;
  days: number;
  start_date: string;
  themes: string[];
  budget?: { min: number; max: number; currency: string };
  transport?: string;
  pace?: string;
  keywords: string[];
}

export interface POI {
  id: string;
  name: string;
  name_en?: string;
  location: { lng: number; lat: number };
  address: string;
  type: POIType;
  category?: string;
  rating?: number;
  description?: string;
  duration?: number;
  tags?: string[];
  avg_price?: number;
}

export type POIType = 'scenic' | 'restaurant' | 'hotel' | 'transport' | 'shopping' | 'entertainment' | 'other';

export type TimeSlotType = 'half_day' | 'morning' | 'afternoon' | 'evening' | 'night' | 'lunch' | 'dinner';

export interface TimeSlot {
  type: TimeSlotType;
  label: string;
  time_range: string;
  start_time: string;
  end_time: string;
  activities: Activity[];
}

export interface Activity {
  poi: POI;
  duration: number;
  description?: string;
  tips?: string[];
}

export type TransportMode = '步行' | '地铁/公交' | '自驾' | '骑行' | '打车';

export interface RouteSegment {
  from: POI;
  to: POI;
  transport: TransportMode;
  distance: number;
  duration: number;
  polyline?: string;
  instruction: string;
}

export interface RestaurantRecommendation {
  poi: POI;
  cuisine_type: string;
  avg_price: number;
  rating: number;
  distance_from_previous: number;
}

export interface DayPlan {
  day_index: number;
  date: string;
  day_of_week: string;
  theme?: string;
  weather?: WeatherInfo;
  time_slots: TimeSlot[];
  route_segments: RouteSegment[];
  restaurants: RestaurantRecommendation[];
  daily_polyline?: string;
  daily_distance: number;
  daily_duration: number;
  highlights: string[];
  tips: string[];
}

export interface WeatherInfo {
  date: string;
  condition: string;
  temperature: { high: number; low: number };
  humidity?: number;
  wind?: string;
  travel_suggestion?: string;
}

export interface CompletePlan {
  plan_id?: string;
  user_profile?: UserProfile;
  parsed_intent: ParsedIntent;
  days: DayPlan[];
  total_distance: number;
  total_duration: number;
  weather_summary: string;
  status: 'draft' | 'confirmed' | 'completed';
}

export type SSEEventType = 'status' | 'result' | 'complete' | 'error' | 'intent' | 'poi_search' | 'weather' | 'route' | 'restaurant';

export interface SSEEvent {
  type: SSEEventType;
  content: any;
  timestamp?: number;
  progress?: number;
}

export interface PlanRequest {
  user_request: string;
  plan_mode: 'exploratory' | 'planned';
  user_location?: { lng: number; lat: number };
}

export interface MapMarkerData {
  poi: POI;
  index: number;
  dayIndex: number;
  isStart: boolean;
  isEnd: boolean;
  marker_type: 'attraction' | 'restaurant' | 'hotel' | 'transport';
}

export interface MapPolylineData {
  path: [number, number][];
  dayIndex: number;
  color: string;
  strokeStyle: 'solid' | 'dashed';
  strokeWeight: number;
}

export interface RouteRenderData {
  plan: CompletePlan;
  markers: MapMarkerData[];
  polylines: MapPolylineData[];
  bounds: { northEast: [number, number]; southWest: [number, number] };
}
