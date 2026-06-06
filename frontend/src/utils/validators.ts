export function isValidDate(date: string): boolean {
  const d = new Date(date);
  return d instanceof Date && !isNaN(d.getTime());
}

export function isValidDateRange(start: string, end: string): boolean {
  if (!isValidDate(start) || !isValidDate(end)) return false;
  return new Date(start) <= new Date(end);
}

export function isValidLocation(location: [number, number]): boolean {
  const [lng, lat] = location;
  return lng >= -180 && lng <= 180 && lat >= -90 && lat <= 90;
}

export function isValidQuery(query: string): boolean {
  return query.trim().length >= 2 && query.trim().length <= 500;
}

export function validateRouteInput(input: {
  text: string;
  start_date: string;
  days: number;
}): { valid: boolean; error?: string } {
  if (!isValidQuery(input.text)) {
    return { valid: false, error: '请输入有效的旅行描述（2-500字）' };
  }
  if (!isValidDate(input.start_date)) {
    return { valid: false, error: '请选择有效的开始日期' };
  }
  if (input.days < 1 || input.days > 30) {
    return { valid: false, error: '旅行天数应在1-30天之间' };
  }
  return { valid: true };
}
