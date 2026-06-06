/**
 * 高德地图路线渲染 Hook
 * 
 * 使用高德 JS API 2.0 渲染路线
 * 需要先加载高德地图 SDK
 * 
 * 注意：AMap 类型定义在 types/amap.d.ts 中
 */

import { useCallback, useRef } from 'react';
import type { DayRoute, RoutePoint, RouteSegment } from '../types/route';
import { PERIOD_COLORS } from '../types/route';

export interface RouteRendererOptions {
  /** 高德地图实例 */
  map: AMap.Map | null;
  /** 是否显示方向箭头 */
  showDirection?: boolean;
  /** 点击标记时的回调 */
  onMarkerClick?: (point: RoutePoint) => void;
}

export interface RouteRendererResult {
  /** 渲染单日路线 */
  renderDayRoute: (dayRoute: DayRoute) => { markers: AMap.Marker[]; polylines: AMap.Polyline[] };
  /** 清除所有渲染 */
  clearRoute: () => void;
  /** 自适应视野 */
  fitView: () => void;
}

/**
 * 高德地图路线渲染 Hook
 */
export function useRouteRenderer(options: RouteRendererOptions): RouteRendererResult {
  const { map, showDirection = true, onMarkerClick } = options;
  
  // 保存所有渲染的标记和路线
  const markersRef = useRef<AMap.Marker[]>([]);
  const polylinesRef = useRef<AMap.Polyline[]>([]);

  /**
   * 创建标记内容 HTML
   */
  const createMarkerContent = useCallback((point: RoutePoint): string => {
    const { kind, period, label } = point;
    
    switch (kind) {
      case 'start':
        return `
          <div style="
            width: 36px; height: 36px; border-radius: 50%;
            background: #27AE60; border: 3px solid #fff;
            display: flex; align-items: center; justify-content: center;
            color: #fff; font-size: 14px; font-weight: bold;
            box-shadow: 0 2px 8px rgba(0,0,0,0.4);
            cursor: pointer;
          ">起</div>`;
      
      case 'meal':
        return `
          <div style="
            width: 32px; height: 32px; border-radius: 50%;
            background: #E74C3C; border: 3px solid #fff;
            display: flex; align-items: center; justify-content: center;
            color: #fff; font-size: 16px;
            box-shadow: 0 2px 8px rgba(0,0,0,0.4);
            cursor: pointer;
          ">🍴</div>`;
      
      case 'enroute':
        return `
          <div style="
            width: 16px; height: 16px; border-radius: 50%;
            background: #3498DB; border: 2px solid #fff;
            box-shadow: 0 1px 4px rgba(0,0,0,0.3);
            cursor: pointer;
          "></div>`;
      
      case 'waypoint':
      default: {
        const color = PERIOD_COLORS[period]?.primary || '#E67E22';
        const displayLabel = label || '';
        return `
          <div style="
            width: 28px; height: 28px; border-radius: 50%;
            background: ${color}; border: 2px solid #fff;
            display: flex; align-items: center; justify-content: center;
            color: #fff; font-size: 11px; font-weight: bold;
            box-shadow: 0 2px 6px rgba(0,0,0,0.3);
            cursor: pointer;
          ">${displayLabel}</div>`;
      }
    }
  }, []);

  /**
   * 创建标记
   */
  const createMarker = useCallback((point: RoutePoint): AMap.Marker | null => {
    if (!map) return null;

    const content = createMarkerContent(point);
    
    const marker = new AMap.Marker({
      position: point.location,
      content,
      title: point.name,
      zIndex: point.kind === 'start' ? 100 : point.kind === 'meal' ? 90 : 80,
    });

    // 点击事件
    marker.on('click', () => {
      const infoContent = `
        <div style="padding: 10px; font-size: 14px; font-weight: bold; min-width: 120px;">
          ${point.name}
          ${point.walkMin ? `<br/><span style="font-size: 12px; color: #666; font-weight: normal;">步行${point.walkMin}分钟可达</span>` : ''}
          ${point.tooltip && !point.walkMin ? `<br/><span style="font-size: 12px; color: #666; font-weight: normal;">${point.tooltip}</span>` : ''}
        </div>
      `;
      const info = new AMap.InfoWindow({
        content: infoContent,
        offset: new AMap.Pixel(0, -30),
      });
      info.open(map, point.location);
      
      onMarkerClick?.(point);
    });

    map.add(marker);
    return marker;
  }, [map, createMarkerContent, onMarkerClick]);

  /**
   * 创建路线
   */
  const createPolyline = useCallback((segment: RouteSegment): AMap.Polyline | null => {
    if (!map) return null;

    const polyline = new AMap.Polyline({
      path: segment.polyline,
      strokeColor: segment.color || '#3498DB',
      strokeWeight: segment.isDashed ? 3 : 4,
      strokeOpacity: 0.9,
      strokeStyle: segment.isDashed ? 'dashed' : 'solid',
      strokeDasharray: segment.isDashed ? [10, 10] : undefined,
      showDir: showDirection,
      zIndex: 50,
    });

    map.add(polyline);
    return polyline;
  }, [map, showDirection]);

  /**
   * 渲染单日路线
   */
  const renderDayRoute = useCallback((dayRoute: DayRoute) => {
    if (!map) return { markers: [], polylines: [] };

    // 设置中心点和缩放
    if (dayRoute.center) {
      map.setCenter(dayRoute.center);
    }
    map.setZoom(13);

    // 渲染标记
    const markers: AMap.Marker[] = [];
    for (const point of dayRoute.points || []) {
      const marker = createMarker(point);
      if (marker) {
        markers.push(marker);
        markersRef.current.push(marker);
      }
    }

    // 渲染路线
    const polylines: AMap.Polyline[] = [];
    for (const segment of dayRoute.segments) {
      const polyline = createPolyline(segment);
      if (polyline) {
        polylines.push(polyline);
        polylinesRef.current.push(polyline);
      }
    }

    // 自适应视野
    map.setFitView([...markers, ...polylines], true, [60, 60, 60, 60]);

    return { markers, polylines };
  }, [map, createMarker, createPolyline]);

  /**
   * 清除所有渲染
   */
  const clearRoute = useCallback(() => {
    if (!map) return;

    for (const marker of markersRef.current) {
      map.remove(marker);
    }
    for (const polyline of polylinesRef.current) {
      map.remove(polyline);
    }

    markersRef.current = [];
    polylinesRef.current = [];
  }, [map]);

  /**
   * 自适应视野
   */
  const fitView = useCallback(() => {
    if (!map) return;
    map.setFitView([...markersRef.current, ...polylinesRef.current], true, [60, 60, 60, 60]);
  }, [map]);

  return {
    renderDayRoute,
    clearRoute,
    fitView,
  };
}

export default useRouteRenderer;
