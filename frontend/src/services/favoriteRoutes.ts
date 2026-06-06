/**
 * 路线收藏服务
 * - 注册用户：调用后端 API（MongoDB 持久化）
 * - 游客模式：使用浏览器 localStorage
 */

import { userApi } from '@/api/user';
import type { PoiDetail } from '@/api/poi';

const STORAGE_KEY = 'travel-planner-route-favorites-v1';

export interface FavoriteRoute {
  id: string;
  favorite_id?: string;
  title: string;
  destination: string;
  days: number;
  created_at: string;
  updated_at: string;
  route_id?: string;
  route_hash: string;
  complete_plan: any;
  route_data: any;
  panel_days: any;
  map_route_data: any;
  poi_details?: Record<string, any>;
  summary?: { poi_count: number; distance: number; duration: number };
}

function generateId(): string {
  return `fav_${Date.now()}_${Math.random().toString(36).substr(2, 9)}`;
}

/** 简单 hash 用于去重 */
export function routeHash(data: any): string {
  const str = JSON.stringify({
    title: data?.title || '',
    days: data?.days || 1,
    points: (data?.route_data?.points || []).map((p: any) => p.name).join('|'),
  });
  let hash = 0;
  for (let i = 0; i < str.length; i++) {
    const chr = str.charCodeAt(i);
    hash = ((hash << 5) - hash) + chr;
    hash |= 0;
  }
  return String(Math.abs(hash));
}

function getLocalFavorites(): FavoriteRoute[] {
  try {
    const raw = localStorage.getItem(STORAGE_KEY);
    return raw ? JSON.parse(raw) : [];
  } catch {
    return [];
  }
}

function setLocalFavorites(favorites: FavoriteRoute[]): void {
  localStorage.setItem(STORAGE_KEY, JSON.stringify(favorites));
}

function normalizeLocation(loc: any): string {
  if (!loc) return '';
  if (typeof loc === 'string') return loc;
  const lng = loc.lng ?? loc.longitude ?? '';
  const lat = loc.lat ?? loc.latitude ?? '';
  return lng !== '' && lat !== '' ? `${lng},${lat}` : '';
}

function samePoi(target: any, item: any, detail?: PoiDetail | null): boolean {
  if (!target || !item) return false;
  const targetIds = [target.poi_id, target.gaode_poi_id, target.poiId, target.gaodePoiId].filter(Boolean);
  const itemIds = [item.poi_id, item.gaode_poi_id, item.poiId, item.gaodePoiId, detail?.poi_id, detail?.gaode_poi_id].filter(Boolean);
  if (targetIds.some((id: string) => itemIds.includes(id))) return true;
  const targetName = target.name || target.nameEn || '';
  const itemName = item.name || item.nameEn || detail?.name || '';
  if (!targetName || targetName !== itemName) return false;
  const targetLoc = normalizeLocation(target.location);
  const itemLoc = normalizeLocation(item.location || detail?.location);
  return !targetLoc || !itemLoc || targetLoc === itemLoc;
}

function isFallbackPhoto(url: string, source: string): boolean {
  if (source === 'fallback') return true;
  if (!url) return false;
  const lowered = url.toLowerCase();
  return (
    lowered.includes('/images/shanghai.jpg') ||
    lowered.includes('unsplash.com/photo-1508804185872')
  );
}

function mergeDetail(item: any, detail: PoiDetail): any {
  // Determine safe photo_url: never persist fallback/default images
  const detailPhotoUrl = detail.photo_url || '';
  const detailPhotoSource = detail.photo_source || '';
  const detailPhotoIsValid = detailPhotoUrl && !isFallbackPhoto(detailPhotoUrl, detailPhotoSource);

  const existingPhotoUrl = item.photo_url || '';
  const existingPhotoSource = item.photo_source || '';
  const existingPhotoIsValid = existingPhotoUrl && !isFallbackPhoto(existingPhotoUrl, existingPhotoSource);

  // Only use a photo if it's valid (not fallback)
  let mergedPhotoUrl = '';
  let mergedPhotoSource = '';
  if (existingPhotoIsValid) {
    mergedPhotoUrl = existingPhotoUrl;
    mergedPhotoSource = existingPhotoSource;
  } else if (detailPhotoIsValid) {
    mergedPhotoUrl = detailPhotoUrl;
    mergedPhotoSource = detailPhotoSource;
  }
  // Otherwise both are empty/fallback — leave empty

  return {
    ...item,
    poi_id: item.poi_id || detail.poi_id || detail.gaode_poi_id,
    gaode_poi_id: item.gaode_poi_id || detail.gaode_poi_id || detail.poi_id,
    address: item.address || detail.address || '',
    rating: item.rating ?? detail.rating ?? detail.gaode_rating ?? null,
    gaode_rating: item.gaode_rating ?? detail.gaode_rating ?? detail.rating ?? null,
    avg_cost: item.avg_cost ?? detail.avg_cost ?? null,
    photo_url: mergedPhotoUrl,
    photo_source: mergedPhotoSource,
    typecode: item.typecode || detail.typecode || '',
    category: item.category || detail.category || '',
  };
}

export function patchGuestFavoritePoiDetail(target: any, detail: PoiDetail): void {
  if (!detail) return;
  const favorites = getLocalFavorites();
  let changed = false;
  const detailKey = detail.poi_id || detail.gaode_poi_id || `${detail.name || target?.name || ''}:${normalizeLocation(detail.location || target?.location)}`;

  const patched = favorites.map((favorite) => {
    const next = { ...favorite };
    if (next.poi_details) {
      next.poi_details = { ...next.poi_details };
      for (const key of Object.keys(next.poi_details)) {
        if (samePoi(target, next.poi_details[key], detail)) {
          next.poi_details[key] = mergeDetail(next.poi_details[key], detail);
          changed = true;
        }
      }
    } else {
      next.poi_details = {};
    }
    if (detailKey && !next.poi_details[detailKey]) {
      const merged = mergeDetail({ name: detail.name || target?.name, location: detail.location || target?.location }, detail);
      // Only add if the result has meaningful data (not just fallback image)
      next.poi_details[detailKey] = merged;
      changed = true;
    }
    if (next.map_route_data?.markers) {
      next.map_route_data = {
        ...next.map_route_data,
        markers: next.map_route_data.markers.map((marker: any) => {
          if (!samePoi(target, marker, detail)) return marker;
          changed = true;
          return mergeDetail(marker, detail);
        }),
      };
    }
    if (next.route_data?.points) {
      next.route_data = {
        ...next.route_data,
        points: next.route_data.points.map((point: any) => {
          if (!samePoi(target, point, detail)) return point;
          changed = true;
          return mergeDetail(point, detail);
        }),
      };
    }
    if (next.panel_days) {
      next.panel_days = next.panel_days.map((day: any) => ({
        ...day,
        slots: (day.slots || []).map((slot: any) => ({
          ...slot,
          pois: (slot.pois || []).map((poi: any) => {
            if (!samePoi(target, poi, detail)) return poi;
            changed = true;
            return mergeDetail(poi, detail);
          }),
        })),
      }));
    }
    return next;
  });

  if (changed) {
    setLocalFavorites(patched);
  }
}

export const favoriteRoutesService = {
  /** 列出所有收藏 */
  async listFavorites(isGuest: boolean): Promise<FavoriteRoute[]> {
    if (isGuest) {
      return getLocalFavorites().sort(
        (a, b) => new Date(b.updated_at).getTime() - new Date(a.updated_at).getTime()
      );
    }
    try {
      const res = await userApi.getFavorites();
      // userApi 返回 Axios response: { data: { success, data: [...] } }
      const innerData = res?.data?.data || res?.data || [];
      return (Array.isArray(innerData) ? innerData : []) as FavoriteRoute[];
    } catch {
      return [];
    }
  },

  /** 保存收藏（route_hash 去重） */
  async saveFavorite(isGuest: boolean, payload: Omit<FavoriteRoute, 'id' | 'created_at' | 'updated_at'>): Promise<FavoriteRoute> {
    if (isGuest) {
      const favorites = getLocalFavorites();
      // 去重
      const existingIdx = favorites.findIndex(
        f => f.route_hash === payload.route_hash
      );
      const now = new Date().toISOString();
      if (existingIdx >= 0) {
        favorites[existingIdx] = {
          ...favorites[existingIdx],
          ...payload,
          updated_at: now,
        };
      } else {
        favorites.push({
          ...payload,
          id: generateId(),
          created_at: now,
          updated_at: now,
        } as FavoriteRoute);
      }
      setLocalFavorites(favorites);
      return favorites[existingIdx >= 0 ? existingIdx : favorites.length - 1];
    }

    // 注册用户：调用后端
    try {
      const res = await userApi.createFavorite(payload);
      // userApi 返回 Axios response: { data: { success, data: {...} } }
      return (res?.data?.data || res?.data) as FavoriteRoute;
    } catch {
      throw new Error('收藏失败');
    }
  },

  /** 删除收藏 */
  async deleteFavorite(isGuest: boolean, fav: FavoriteRoute): Promise<void> {
    const favId = fav.favorite_id || fav.id;
    if (isGuest) {
      const favorites = getLocalFavorites().filter(
        f => (f.favorite_id || f.id) !== favId
      );
      setLocalFavorites(favorites);
      return;
    }
    await userApi.deleteFavorite(favId);
  },

  /** 检查当前路线是否已收藏 */
  isCurrentRouteFavorited(isGuest: boolean, hash: string, favorites: FavoriteRoute[]): boolean {
    return favorites.some(f => f.route_hash === hash);
  },
};

export default favoriteRoutesService;
