/** 统一兜底常量 — 同济大学四平路校区 */
export const FALLBACK_HOME_LOCATION = {
  lat: 31.2809,
  lng: 121.5011,
  label: '同济大学四平路校区',
};

/** v26: Normalize any location-shaped input into a guaranteed-valid payload.
 *  Prevents bad data (label=[], lat=NaN, etc.) from reaching the backend
 *  and causing Pydantic ValidationError in UserProfile.
 */
export function normalizeLocationPayload(
  raw: unknown,
  fallback?: { lat: number; lng: number; label: string },
): { lat: number; lng: number; label: string; source?: string } {
  const fb = fallback || FALLBACK_HOME_LOCATION;

  const coerceNumber = (v: unknown, fbNum: number): number => {
    if (v == null) return fbNum;
    if (typeof v === 'number' && Number.isFinite(v)) return v;
    if (typeof v === 'string') {
      const n = Number(v);
      if (Number.isFinite(n)) return n;
    }
    return fbNum;
  };

  const coerceLabel = (v: unknown, ...extraFallbacks: (string | undefined | null)[]): string => {
    if (typeof v === 'string' && v.trim()) return v.trim();
    if (Array.isArray(v)) {
      for (const item of v) {
        if (typeof item === 'string' && item.trim()) return item.trim();
      }
    }
    for (const ef of extraFallbacks) {
      if (typeof ef === 'string' && ef.trim()) return ef.trim();
    }
    return fb.label;
  };

  const rawObj = raw && typeof raw === 'object' && !Array.isArray(raw) ? (raw as Record<string, unknown>) : {};

  const result: { lat: number; lng: number; label: string; source?: string } = {
    lat: coerceNumber(rawObj.lat, fb.lat),
    lng: coerceNumber(rawObj.lng, fb.lng),
    label: coerceLabel(
      rawObj.label,
      rawObj.name as string | undefined,
      rawObj.full_address as string | undefined,
      rawObj.address as string | undefined,
    ),
  };

  // Only preserve source if it's a real string
  if (typeof rawObj.source === 'string' && rawObj.source.trim()) {
    result.source = rawObj.source.trim();
  }

  return result;
}

export const FALLBACK_HOME_ADDRESS = {
  name: '同济大学四平路校区',
  full_address: '同济大学四平路校区',
  lng: 121.5011,
  lat: 31.2809,
};

export const makeDeviceHomeAddress = (lat: number, lng: number) => ({
  name: '当前设备位置',
  full_address: '当前设备位置',
  lng,
  lat,
});

export const makeLocationPayload = (lat: number, lng: number, label = '常住地址') => ({
  lat,
  lng,
  label,
});

/** 默认展示文案 */
export const DEFAULT_DEPARTURE_LABEL = '路线出发地';

const normalizeDepartureLabel = (value?: string | null) => {
  const label = String(value || '').trim();
  if (!label || label === '.' || label === '·') return '';
  return label;
};

/**
 * 从用户数据中读取路线出发地展示标签（优先级从高到低）。
 * 用于 PlannerPage 顶部 HeaderWeather 和任何需要显示出发地的组件。
 */
export function getUserDepartureLabel(user: {
  home_location?: { label?: string; lat?: number; lng?: number } | null;
  location?: {
    home_address?: { name?: string; full_address?: string; address?: string } | string | null;
    latitude?: number;
    longitude?: number;
  } | null;
} | null | undefined): string {
  // 1. home_location.label
  const homeLocationLabel = normalizeDepartureLabel(user?.home_location?.label);
  if (homeLocationLabel) return homeLocationLabel;

  // 2. location.home_address as object
  const ha = user?.location?.home_address;
  if (ha && typeof ha === 'object') {
    const name = normalizeDepartureLabel(ha.name);
    if (name) return name;
    const fullAddress = normalizeDepartureLabel(ha.full_address);
    if (fullAddress) return fullAddress;
    const address = normalizeDepartureLabel(ha.address);
    if (address) return address;
  }

  // 3. location.home_address as string
  if (ha && typeof ha === 'string') {
    const address = normalizeDepartureLabel(ha);
    if (address) return address;
  }

  // 4. Fallback
  return DEFAULT_DEPARTURE_LABEL;
}

/**
 * 从用户数据中读取路线出发地坐标（优先级从高到低），返回 [lng, lat]。
 */
export function getUserDepartureCoords(user: {
  home_location?: { label?: string; lat?: number; lng?: number } | null;
  location?: {
    home_address?: { lng?: number | null; lat?: number | null } | null;
    latitude?: number;
    longitude?: number;
  } | null;
} | null | undefined): [number, number] {
  // 1. home_location
  const hl = user?.home_location;
  if (hl?.lng != null && hl?.lat != null) {
    const lng = Number(hl.lng);
    const lat = Number(hl.lat);
    if (Number.isFinite(lng) && Number.isFinite(lat) && lng >= 73 && lng <= 136 && lat >= 18 && lat <= 54) {
      return [lng, lat];
    }
  }

  // 2. location.home_address
  const ha = user?.location?.home_address;
  if (ha && typeof ha === 'object') {
    const lng = Number(ha.lng);
    const lat = Number(ha.lat);
    if (Number.isFinite(lng) && Number.isFinite(lat) && lng >= 73 && lng <= 136 && lat >= 18 && lat <= 54) {
      return [lng, lat];
    }
  }

  // 3. location.latitude / longitude
  const loc = user?.location;
  if (loc) {
    const lng = Number(loc.longitude);
    const lat = Number(loc.latitude);
    if (Number.isFinite(lng) && Number.isFinite(lat) && lng >= 73 && lng <= 136 && lat >= 18 && lat <= 54) {
      return [lng, lat];
    }
  }

  // 4. Fallback
  return [FALLBACK_HOME_LOCATION.lng, FALLBACK_HOME_LOCATION.lat];
}

export function hasManualDeparture(user: {
  home_location?: { label?: string; lat?: number; lng?: number; source?: string } | null;
  location?: {
    home_address?: { name?: string; full_address?: string; source?: string; lng?: number | null; lat?: number | null } | string | null;
    latitude?: number;
    longitude?: number;
  } | null;
} | null | undefined): boolean {
  if (!user) return false;
  // Check if home_location was explicitly set by user
  if (user.home_location?.source === 'manual') return true;
  if (user.home_location?.source === 'device') return true; // device-located but valid
  const ha = user.location?.home_address;
  if (ha && typeof ha === 'object' && (ha.name || ha.full_address) && ha.lng && ha.lat) {
    // Has a valid home address with coordinates
    const [lng, lat] = getUserDepartureCoords(user);
    const isFallback =
      Math.abs(lng - FALLBACK_HOME_LOCATION.lng) < 0.000001 &&
      Math.abs(lat - FALLBACK_HOME_LOCATION.lat) < 0.000001;
    if (!isFallback) return true;
  }
  return false;
}

export function shouldAutoLocateDeparture(user: {
  home_location?: { label?: string; lat?: number; lng?: number; source?: string } | null;
  location?: {
    home_address?: { name?: string; full_address?: string; address?: string; source?: string; lng?: number | null; lat?: number | null } | string | null;
    latitude?: number;
    longitude?: number;
  } | null;
} | null | undefined): boolean {
  if (!user) return false;
  if (hasManualDeparture(user)) return false;
  // Only auto-locate if truly no saved location
  const label = getUserDepartureLabel(user);
  const [lng, lat] = getUserDepartureCoords(user);
  const isFallbackCoord =
    Math.abs(lng - FALLBACK_HOME_LOCATION.lng) < 0.000001 &&
    Math.abs(lat - FALLBACK_HOME_LOCATION.lat) < 0.000001;
  return label === DEFAULT_DEPARTURE_LABEL || label === FALLBACK_HOME_LOCATION.label || isFallbackCoord;
}
