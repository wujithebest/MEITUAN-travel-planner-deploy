import client from './client';
import type { ApiResponse, Diary, DiaryEntry } from './types';

function unwrap<T>(response: ApiResponse<T>): T {
  if (!response.success || response.data === undefined) {
    throw new Error(response.message || '请求失败');
  }
  return response.data;
}

function normalizeEntry(entry: any): DiaryEntry {
  const createdAt = String(entry.created_at || new Date().toISOString());
  return {
    id: entry.id || entry.entry_id,
    day: entry.day || 0,
    title: entry.title || '',
    content: entry.content || '',
    photos: entry.photos || [],
    highlights: entry.highlights || (entry.is_highlight ? [entry.title || '高光时刻'] : []),
    voice_url: entry.voice_url || entry.voice_memo || undefined,
    created_at: createdAt,
    updated_at: String(entry.updated_at || createdAt),
    map_snapshot: entry.map_snapshot || undefined,
  };
}

function normalizeDiary(diary: any): Diary {
  const stats = diary.stats || {};
  return {
    id: diary.id || diary.diary_id,
    route_id: diary.route_id,
    title: diary.title || '我的旅行日记',
    cover_url: diary.cover_url || diary.cover_image || undefined,
    entries: (diary.entries || []).map(normalizeEntry),
    stats: {
      total_days: stats.total_days ?? stats.days ?? 0,
      total_distance: stats.total_distance ?? 0,
      total_photos: stats.total_photos ?? stats.photo_count ?? 0,
      cities_visited: stats.cities_visited ?? stats.city_count ?? 0,
      pois_visited: stats.pois_visited ?? stats.poi_count ?? 0,
    },
    achievements: diary.achievements || [],
    share_link: diary.share_link || undefined,
    created_at: String(diary.created_at || new Date().toISOString()),
    updated_at: String(diary.updated_at || diary.created_at || new Date().toISOString()),
  };
}

function readFileAsDataUrl(file: File): Promise<string> {
  return new Promise((resolve, reject) => {
    const reader = new FileReader();
    reader.onload = () => resolve(String(reader.result));
    reader.onerror = () => reject(reader.error || new Error('照片读取失败'));
    reader.readAsDataURL(file);
  });
}

export async function generateDiary(routeId: string): Promise<Diary> {
  const { data } = await client.post<ApiResponse<any>>(
    `/diary/generate?route_id=${encodeURIComponent(routeId)}`
  );
  return normalizeDiary(unwrap(data));
}

export async function getDiary(diaryId: string): Promise<Diary> {
  const { data } = await client.get<ApiResponse<any>>(`/diary/${diaryId}`);
  return normalizeDiary(unwrap(data));
}

export async function addDiaryEntry(
  diaryId: string,
  entry: Partial<DiaryEntry>
): Promise<DiaryEntry> {
  const { data } = await client.post<ApiResponse<any>>('/diary/entry', {
    diary_id: diaryId,
    day: entry.day || 1,
    title: entry.title || '',
    content: entry.content || '',
    poi_name: '',
    is_highlight: Boolean(entry.highlights?.length),
  });
  return normalizeEntry(unwrap(data));
}

export async function updateDiaryEntry(
  diaryId: string,
  entryId: string,
  entry: Partial<DiaryEntry>
): Promise<DiaryEntry> {
  const { data } = await client.put<ApiResponse<any>>(
    `/diary/${diaryId}/entry/${entryId}`,
    {
      title: entry.title,
      content: entry.content,
      is_highlight: entry.highlights ? entry.highlights.length > 0 : undefined,
    }
  );
  return normalizeEntry(unwrap(data));
}

export async function uploadPhoto(
  diaryId: string,
  file: File,
  entryId: string
): Promise<{ url: string }> {
  const photoUrl = await readFileAsDataUrl(file);
  const { data } = await client.post<ApiResponse<{ url: string }>>('/diary/photo', {
    diary_id: diaryId,
    entry_id: entryId,
    photo_url: photoUrl,
  });
  return unwrap(data);
}

export async function exportDiary(
  diaryId: string,
  format: 'image' | 'pdf'
): Promise<{ url: string }> {
  const { data } = await client.get<ApiResponse<{ url: string }>>(
    `/diary/${diaryId}/export?format=${encodeURIComponent(format)}`
  );
  return unwrap(data);
}

export async function getShareLink(diaryId: string): Promise<{ link: string }> {
  const { data } = await client.post<ApiResponse<{ link: string }>>(`/diary/${diaryId}/share`);
  const result = unwrap(data);
  return { link: new URL(result.link, window.location.origin).toString() };
}
