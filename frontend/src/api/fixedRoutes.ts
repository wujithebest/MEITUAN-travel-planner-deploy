/**
 * Fixed route API — fetches pre-generated route JSON from backend.
 * The backend router is mounted at /api/meituan, so use the shared URL
 * builder instead of concatenating VITE_API_BASE_URL manually.
 */
import { buildApiUrl } from '@/config/api.config';

export async function getFixedRoute(fixtureId: string): Promise<any | null> {
  try {
    const url = buildApiUrl(`/meituan/fixed-routes/${encodeURIComponent(fixtureId)}`);
    const resp = await fetch(url, { headers: { Accept: 'application/json' } });
    if (!resp.ok) {
      console.error(`[FixedRoute] HTTP ${resp.status} for ${fixtureId}`);
      return null;
    }
    const json = await resp.json();
    if (!json?.success || !json?.data) {
      console.error(`[FixedRoute] invalid response for ${fixtureId}:`, json);
      return null;
    }
    return json.data;
  } catch (err) {
    console.error(`[FixedRoute] fetch failed for ${fixtureId}:`, err);
    return null;
  }
}
