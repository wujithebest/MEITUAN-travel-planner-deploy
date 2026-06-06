// Chat related types

export interface ChatRoom {
  id: string;
  name: string;
  avatar?: string;
  created_by: string;
  created_at: string;
  last_message?: {
    sender_name: string;
    text_preview: string;
    timestamp: string;
  };
  unread_count: number;
  member_count: number;
}

export interface ChatUser {
  id: string;
  name: string;
  avatar: string;
  is_agent: boolean;
  is_online?: boolean;
}

// 澄清消息数据
export interface ClarificationData {
  missing?: string[];
  received?: string[];
  destination?: string;
}

export interface ChatMessage {
  id: string;
  room_id: string;
  sender: ChatUser;
  content: MessageContent;
  timestamp: string;
  reply_to?: string;
  metadata?: {
    extracted_pois?: ExtractedPOI[];
    intent?: TravelIntent;
    generated_by?: string;
    user_request?: string;
    response_status?: string;
    missing_fields?: string[];
    received_fields?: string[];
    clarification?: ClarificationData;
  };
}

export interface ItineraryDayData {
  day_index: number;
  title: string;
  detail: string;
  anchors: string[];
  polyline?: string;
}

export interface ItineraryAnchor {
  name: string;
  reason: string;
}

export interface ItineraryPreviewData {
  summary: string;
  days: ItineraryDayData[];
  anchors: ItineraryAnchor[];
  total_distance?: string;
  map_url?: string;
}

export interface MessageContent {
  type: 'text' | 'route_card' | 'poi_card' | 'image' | 'location' | 'itinerary_preview' | 'clarification';
  text?: string;
  route_data?: RouteCardData | ItineraryPreviewData;
  poi_data?: POICardData;
  media_url?: string;
  location?: LocationData;
  metadata?: {
    extracted_pois?: ExtractedPOI[];
    intent?: TravelIntent;
    generated_by?: string;
    user_request?: string;
  };
  clarification_data?: ClarificationData;
}

export interface RouteCardData {
  route_id: string;
  title: string;
  days: number;
  summary: string;
  preview_image?: string;
  pois: Array<{
    id: string;
    name: string;
    lat: number;
    lng: number;
  }>;
  total_distance?: string;
  estimated_duration?: string;
}

export interface POICardData {
  id: string;
  name: string;
  address: string;
  category: string;
  rating?: number;
  image_url?: string;
  lat: number;
  lng: number;
  description?: string;
}

export interface LocationData {
  name: string;
  address: string;
  lat: number;
  lng: number;
}

export interface ExtractedPOI {
  id: string;
  name: string;
  confidence: number;
  source_message_id: string;
  lat?: number;
  lng?: number;
  category?: string;
}

export interface TravelIntent {
  destination: string;
  days?: number;
  start_date?: string;
  end_date?: string;
  themes: string[];
  budget?: string;
  transportation?: string;
  accommodation?: string;
}
