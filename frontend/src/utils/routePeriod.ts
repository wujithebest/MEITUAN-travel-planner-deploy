export const ROUTE_PERIOD_COLORS: Record<string, string> = {
  morning: '#E67E22',
  lunch: '#D35400',
  afternoon: '#2980B9',
  dinner: '#C0392B',
  evening: '#8E44AD',
  half_day: '#E67E22',
};

const PERIOD_ALIASES: Record<string, string> = {
  上午: 'morning',
  早上: 'morning',
  morning: 'morning',
  午餐: 'lunch',
  中午: 'lunch',
  lunch: 'lunch',
  下午: 'afternoon',
  afternoon: 'afternoon',
  晚餐: 'dinner',
  dinner: 'dinner',
  晚上: 'evening',
  夜间: 'evening',
  夜景: 'evening',
  evening: 'evening',
  night: 'evening',
  半天: 'half_day',
  half_day: 'half_day',
};

export function normalizeRoutePeriod(value: unknown): string {
  const raw = String(value ?? '').trim();
  return PERIOD_ALIASES[raw] || raw;
}

export function getRoutePeriodColor(...values: unknown[]): string | undefined {
  for (const value of values) {
    const period = normalizeRoutePeriod(value);
    if (ROUTE_PERIOD_COLORS[period]) return ROUTE_PERIOD_COLORS[period];
  }
  return undefined;
}

/** Correct stale cached colors while preserving route geometry and metadata. */
export function normalizeMapRouteColors<T extends { polylines?: any[] }>(data: T | null | undefined): T | null | undefined {
  if (!data || !Array.isArray(data.polylines)) return data;
  return {
    ...data,
    polylines: data.polylines.map((polyline: any) => ({
      ...polyline,
      color: getRoutePeriodColor(polyline.display_slot, polyline.period, polyline.slot) || polyline.color,
    })),
  };
}
