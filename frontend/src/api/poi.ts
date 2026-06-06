import client from './client';

export interface PoiPreferencePayload {
  user_id?: string;
  poi_id?: string;
  poi_name: string;
  poi_type?: string;
  action: 'like' | 'dislike' | 'delete' | 'remove';
  route_id?: string;
  timestamp?: number;
}

export interface AlternativePoi {
  poi_id: string;
  gaode_poi_id?: string;
  name: string;
  category?: string;
  typecode?: string;
  lnglat: [number, number];
  location?: { lat: number; lng: number };
  address?: string;
  rating?: number | null;
  avg_cost?: number | string | null;
  theme_color: string;
  score: number;
  photo_url?: string;
  photo_source?: string;
}

export interface PoiDetail {
  poi_id?: string;
  gaode_poi_id?: string;
  name?: string;
  location?: { lat: number; lng: number } | string;
  address?: string;
  rating?: number | string | null;
  gaode_rating?: number | string | null;
  avg_cost?: number | string | null;
  photo_url?: string;
  photo_source?: string;
  typecode?: string;
  category?: string;
}

export async function recordPoiPreference(payload: PoiPreferencePayload): Promise<void> {
  try {
    await client.post('/v1/user/preference', {
      user_id: payload.user_id || localStorage.getItem('user_id') || '',
      poi_id: payload.poi_id || '',
      poi_name: payload.poi_name,
      poi_type: payload.poi_type || '',
      action: payload.action,
      route_id: payload.route_id,
      timestamp: payload.timestamp || Math.floor(Date.now() / 1000),
    });
  } catch (error) {
    console.warn('[PoiAPI] record preference failed:', error);
  }
}

export async function getPoiDetail(params: {
  poi_id?: string;
  poi_name?: string;
  location?: string;
  category?: string;
}): Promise<PoiDetail | null> {
  try {
    const { data } = await client.get<{ success: boolean; data: PoiDetail | null }>(
      '/v1/pois/detail',
      {
        params: {
          poi_id: params.poi_id || '',
          poi_name: params.poi_name || '',
          location: params.location || '',
          category: params.category || '',
        },
      }
    );
    return data?.data || null;
  } catch (error) {
    console.warn('[PoiAPI] get detail failed:', error);
    return null;
  }
}

export async function getPoiAlternatives(params: {
  poi_id: string;
  user_id?: string;
  limit?: number;
  poi_name?: string;
  location?: string;
  category?: string;
}): Promise<AlternativePoi[]> {
  const { data } = await client.get<{ alternatives: AlternativePoi[] }>(
    `/v1/pois/${encodeURIComponent(params.poi_id)}/alternatives`,
    {
      params: {
        user_id: params.user_id || localStorage.getItem('user_id') || '',
        limit: params.limit || 5,
        poi_name: params.poi_name || '',
        location: params.location || '',
        category: params.category || '',
      },
    }
  );
  return data.alternatives || [];
}
