/**
 * Fixed route API — fetches pre-generated route JSON from backend.
 * The backend router is mounted at /api/meituan, so use the shared URL
 * builder instead of concatenating VITE_API_BASE_URL manually.
 */
import { buildApiUrl } from '@/config/api.config';

export async function getFixedRoute(fixtureId: string): Promise<any | null> {
  const url = buildApiUrl(`/meituan/fixed-routes/${encodeURIComponent(fixtureId)}`);
  const resp = await fetch(url, { headers: { Accept: 'application/json' } });
  if (!resp.ok) {
    throw new Error(`固定路线接口返回 HTTP ${resp.status}`);
  }
  const json = await resp.json();
  if (!json?.success || !json?.data) {
    throw new Error(json?.error || `固定路线数据无效: ${fixtureId}`);
  }
  return json.data;
}
