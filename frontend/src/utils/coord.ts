/**
 * 坐标转换工具函数
 * 
 * 注意：后端返回的坐标已经是 [lng, lat] 格式（高德 JS API 直接使用）
 * 这些工具函数主要用于兼容旧版数据格式或特殊场景
 */

/**
 * 翻转坐标：[lat, lng] → [lng, lat]
 * 用于兼容旧版 folium 格式数据
 */
export function flipCoord([lat, lng]: [number, number]): [number, number] {
  return [lng, lat];
}

/**
 * 将 polyline 从 [[lat,lng],...] 转为 [[lng,lat],...]
 * 用于兼容旧版 folium 格式数据
 */
export function flipPolyline(polyline: [number, number][]): [number, number][] {
  return polyline.map(flipCoord);
}

/**
 * 将 polyline 转为高德路径字符串 "lng,lat;lng,lat"
 * 用于某些需要字符串格式的 API
 */
export function polylineToPath(polyline: [number, number][]): string {
  return polyline.map(([lng, lat]) => `${lng},${lat}`).join(';');
}

/**
 * 将高德路径字符串 "lng,lat;lng,lat" 转为坐标数组
 */
export function pathToPolyline(path: string): [number, number][] {
  return path.split(';').map((point) => {
    const [lng, lat] = point.split(',').map(Number);
    return [lng, lat] as [number, number];
  });
}

/**
 * 计算两点间距离（千米）
 * 使用 Haversine 公式
 */
export function haversineDistance(
  [lng1, lat1]: [number, number],
  [lng2, lat2]: [number, number]
): number {
  const R = 6371; // 地球半径（千米）
  const dLat = (lat2 - lat1) * Math.PI / 180;
  const dLng = (lng2 - lng1) * Math.PI / 180;
  const a =
    Math.sin(dLat / 2) * Math.sin(dLat / 2) +
    Math.cos(lat1 * Math.PI / 180) * Math.cos(lat2 * Math.PI / 180) *
    Math.sin(dLng / 2) * Math.sin(dLng / 2);
  const c = 2 * Math.atan2(Math.sqrt(a), Math.sqrt(1 - a));
  return R * c;
}

/**
 * 计算 polyline 总长度（千米）
 */
export function polylineDistance(polyline: [number, number][]): number {
  if (polyline.length < 2) return 0;
  let total = 0;
  for (let i = 0; i < polyline.length - 1; i++) {
    total += haversineDistance(polyline[i], polyline[i + 1]);
  }
  return total;
}

/**
 * 计算多点中心
 */
export function centerOfPoints(points: [number, number][]): [number, number] {
  if (points.length === 0) return [121.47, 31.23]; // 默认上海中心
  const sum = points.reduce(
    (acc, [lng, lat]) => [acc[0] + lng, acc[1] + lat] as [number, number],
    [0, 0] as [number, number]
  );
  return [sum[0] / points.length, sum[1] / points.length];
}
