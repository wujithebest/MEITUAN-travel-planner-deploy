import React, { useEffect, useRef, useState, useCallback, useMemo } from 'react';
import { createRoot, Root } from 'react-dom/client';
import styles from './MapContainer.module.css';
import POIDetailModal from '../POIDetailModal';
import POIPopup, { POIData, Tag } from '../POIPopup';
import { getPoiAlternatives, getPoiDetail, recordPoiPreference, type AlternativePoi, type PoiDetail } from '@/api/poi';
import { patchGuestFavoritePoiDetail } from '@/services/favoriteRoutes';
import { useRouteStore } from '@/store/routeStore';
import type { PanelPoi } from '@/utils/panelPoiReorder';

// 扩展的 Marker 数据接口
export interface MarkerData {
  poi_id?: string;
  gaode_poi_id?: string;
  name: string;
  location: string; // "lng,lat"
  type: 'origin' | 'destination' | 'waypoint' | 'enroute' | 'candidate';
  index?: number;
  day_index?: number;
  typecode?: string;
  category?: string;
  avg_cost?: number | string | null;
  photo_url?: string;
  photo_source?: string;
  gaode_rating?: number | string | null;
  formatted_address?: string;
  photo?: string;
  image?: string;
  recommend_reason?: string;
  parent_anchor?: string;
  visit_duration_min?: number | null;
  // candidate 扩展字段
  is_candidate?: boolean;
  candidate_source?: string;
  theme?: 'yellow' | 'blue';
  candidate_score?: number;
  sub_anchor_name?: string;
  // POI 弹窗相关数据
  nameCn?: string;
  imageUrl?: string;
  rating?: number | string | null;
  reviewCount?: number;
  ranking?: string;
  openHours?: string;
  queueTime?: string;
  address?: string;
  tags?: Tag[];
  poiData?: any;
  display_order?: number | null;
  is_display_poi?: boolean;
  is_waypoint?: boolean;
  kind?: string;
  display_label?: string;
  display_slot?: string;
  route_order?: number;
}

interface MapContainerProps {
  containerId?: string;
  dailyPolylines?: Array<{
    day_index: number;
    polyline: string;
    color?: string;
    trafficStatus?: 'smooth' | 'slow' | 'congested';
  }>;
  markers?: MarkerData[];
  center?: [number, number];
  zoom?: number;
  /** POI 操作回调（删除/替换后触发路线重算 — 仅用于黄色路线点） */
  onPoiAction?: (action: { type: 'delete' | 'replace'; poiId: string; replacementPoi?: any }) => void;
  /** 路线版本号，变化时清除乐观 UI 状态 */
  routeVersion?: number;
  /** 候选 POI 本地操作回调（不触发路线重算） */
  onCandidateAction?: (action: { type: 'delete' | 'add' | 'replace'; poiId: string; candidateMarker?: any; routePoiId?: string }) => void;
  /** v6: 外部焦点请求 — 定位并可选打开弹窗 */
  focusPoiRequest?: { requestId: number; poiName: string; behavior: 'openPopup' | 'centerOnly' } | null;
}

// 路况颜色映射
const TRAFFIC_COLORS = {
  smooth: '#3366FF',    // 畅通 - 蓝色
  slow: '#FAAD14',      // 缓行 - 黄色
  congested: '#F5222D'  // 拥堵 - 红色
};

const DAY_COLORS = ['#FFD100', '#52c41a', '#FFD100', '#f5222d', '#722ed1', '#eb2f96'];

function parseRatingValue(value: any): number | null {
  if (value === undefined || value === null || value === '') return null;
  const parsed = Number(value);
  return Number.isFinite(parsed) && parsed > 0 ? parsed : null;
}

// Fallback image URLs that should never be displayed as POI photos
function isFallbackImageUrl(url: string): boolean {
  if (!url) return false;
  const lowered = url.toLowerCase();
  return (
    lowered.includes('/images/shanghai.jpg') ||
    lowered.includes('unsplash.com/photo-1508804185872') ||
    lowered === 'data:image/svg+xml;base64,phn2zyb3aw' // SVG fallback prefix
  );
}

function firstPhotoUrl(source: any): string {
  if (!source) return '';
  // Check photo_source — if it's "fallback", ignore the photo_url entirely
  const photoSource = source.photo_source || source.poiData?.photo_source || '';
  if (photoSource === 'fallback') return '';
  const direct = source.photo_url || source.imageUrl || source.photo || source.image || source.poiData?.photo_url || source.poiData?.imageUrl;
  if (direct && !isFallbackImageUrl(direct)) return direct;
  const photos = source.photos || source.poiData?.photos;
  if (Array.isArray(photos)) {
    const first = photos.find((photo: any) => (photo?.url || photo?.contentUrl) && !isFallbackImageUrl(photo.url || photo.contentUrl));
    return first?.url || first?.contentUrl || '';
  }
  return '';
}

// Distance calculation helpers for name/location matching
function normalizeLocationForCompare(loc: any): { lng: number; lat: number } | null {
  if (!loc) return null;
  if (typeof loc === 'string') {
    const parts = loc.split(',').map(Number);
    if (parts.length === 2 && !isNaN(parts[0]) && !isNaN(parts[1])) {
      return { lng: parts[0], lat: parts[1] };
    }
    return null;
  }
  const lng = Number(loc.lng ?? loc.longitude);
  const lat = Number(loc.lat ?? loc.latitude);
  if (isNaN(lng) || isNaN(lat)) return null;
  return { lng, lat };
}

function haversineDistanceMeters(a: { lng: number; lat: number }, b: { lng: number; lat: number }): number {
  const R = 6371000;
  const toRad = (deg: number) => (deg * Math.PI) / 180;
  const dLat = toRad(b.lat - a.lat);
  const dLng = toRad(b.lng - a.lng);
  const sinDLat = Math.sin(dLat / 2);
  const sinDLng = Math.sin(dLng / 2);
  const aVal = sinDLat * sinDLat + Math.cos(toRad(a.lat)) * Math.cos(toRad(b.lat)) * sinDLng * sinDLng;
  return R * 2 * Math.atan2(Math.sqrt(aVal), Math.sqrt(1 - aVal));
}

function poiNamesMatch(n1: string, n2: string): boolean {
  if (!n1 || !n2) return false;
  const a = n1.trim();
  const b = n2.trim();
  if (a === b) return true;
  if (a.includes(b) || b.includes(a)) return true;
  return false;
}

function mergePoiDetailIntoPopup(base: POIData, detail: PoiDetail, markerName?: string, markerLocation?: string): POIData {
  const detailRating = parseRatingValue(detail.rating ?? detail.gaode_rating);
  const detailLocation = typeof detail.location === 'string'
    ? detail.location
    : detail.location
      ? `${detail.location.lng},${detail.location.lat}`
      : '';

  // Validate that the detail response actually matches this marker
  // before merging photo_url (most important for image correctness)
  const detailName = detail.name || '';
  const checkName = markerName || base.nameEn || '';
  const namesOk = poiNamesMatch(detailName, checkName);
  const markerLoc = normalizeLocationForCompare(markerLocation || base.location);
  const detailLoc = normalizeLocationForCompare(detail.location || detailLocation);
  let locationOk = false;
  if (markerLoc && detailLoc) {
    locationOk = haversineDistanceMeters(markerLoc, detailLoc) <= 500;
  }
  // Photo is only safe to merge if name or location matches
  const canMergePhoto = namesOk || locationOk;

  // Determine safe photo_url: only use detail photo if it passes validation AND is not a fallback
  let safePhotoUrl = base.imageUrl || '';
  if (!safePhotoUrl && canMergePhoto && detail.photo_url && !isFallbackImageUrl(detail.photo_url) && detail.photo_source !== 'fallback') {
    safePhotoUrl = detail.photo_url;
  }

  return {
    ...base,
    poiId: base.poiId || detail.poi_id || detail.gaode_poi_id,
    gaodePoiId: base.gaodePoiId || detail.gaode_poi_id || detail.poi_id,
    imageUrl: safePhotoUrl,
    rating: base.hasRating === false && detailRating != null ? detailRating : base.rating,
    hasRating: base.hasRating || detailRating != null,
    address: base.address || detail.address || '',
    avgCost: base.avgCost ?? detail.avg_cost,
    photoSource: safePhotoUrl ? (base.photoSource || detail.photo_source || '') : '',
    typecode: base.typecode || detail.typecode,
    category: base.category || detail.category,
    location: base.location || detailLocation,
  };
}

function mergePoiDetailIntoMarker(marker: any, detail: PoiDetail): void {
  marker.poi_id = marker.poi_id || detail.poi_id || detail.gaode_poi_id;
  marker.gaode_poi_id = marker.gaode_poi_id || detail.gaode_poi_id || detail.poi_id;
  marker.address = marker.address || detail.address || '';
  marker.rating = marker.rating ?? detail.rating ?? detail.gaode_rating ?? null;
  marker.gaode_rating = marker.gaode_rating ?? detail.gaode_rating ?? detail.rating ?? null;
  marker.avg_cost = marker.avg_cost ?? detail.avg_cost ?? null;
  marker.typecode = marker.typecode || detail.typecode || '';
  marker.category = marker.category || detail.category || '';
  // Only merge photo if detail matches this marker (name or location) AND is not a fallback
  const detailName = detail.name || '';
  const markerName = marker.name || '';
  const namesOk = poiNamesMatch(detailName, markerName);
  const markerLoc = normalizeLocationForCompare(marker.location);
  const detailLoc = normalizeLocationForCompare(detail.location);
  let locationOk = false;
  if (markerLoc && detailLoc) {
    locationOk = haversineDistanceMeters(markerLoc, detailLoc) <= 500;
  }
  const canMergePhoto = namesOk || locationOk;
  if (canMergePhoto && detail.photo_url && !isFallbackImageUrl(detail.photo_url) && detail.photo_source !== 'fallback') {
    if (!marker.photo_url || isFallbackImageUrl(marker.photo_url) || marker.photo_source === 'fallback') {
      marker.photo_url = detail.photo_url;
      marker.photo_source = detail.photo_source || '';
    }
  }
  // If marker already has a fallback image, clear it
  if (marker.photo_url && isFallbackImageUrl(marker.photo_url)) {
    marker.photo_url = '';
    marker.photo_source = '';
  }
  if (marker.photo_source === 'fallback') {
    marker.photo_url = '';
    marker.photo_source = '';
  }
}

export default function MapContainer({
  containerId = 'gaode-map',
  dailyPolylines = [],
  markers = [],
  center = [116.397428, 39.90923], // 北京
  zoom = 11,
  onPoiAction,
  onCandidateAction,
  routeVersion = 0,
  focusPoiRequest,
}: MapContainerProps) {
  const mapRef = useRef<HTMLDivElement>(null);
  const mapInstanceRef = useRef<any>(null);
  const [isMapReady, setIsMapReady] = useState(false);
  const [scriptLoaded, setScriptLoaded] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [viewMode, setViewMode] = useState<'2D' | '3D'>('2D');
  const [mapStyle, setMapStyle] = useState<'standard' | 'satellite'>('standard');
  const [trafficEnabled, setTrafficEnabled] = useState(false);

  // POI详情弹窗状态
  const [poiDetailModal, setPoiDetailModal] = useState<{
    isOpen: boolean;
    poiName: string;
    poiId?: string;
    location?: string;
    poi?: any;
  }>({
    isOpen: false,
    poiName: '',
    poi: null,
  });

  // POI 弹窗数据状态（用于高德 InfoWindow）
  const [poiPopupData, setPoiPopupData] = useState<POIData | null>(null);
  const [poiPopupVisible, setPoiPopupVisible] = useState(false);
  const [poiPopupPosition, setPoiPopupPosition] = useState<[number, number] | null>(null);
  const infoWindowRef = useRef<any>(null);
  const popupRootRef = useRef<Root | null>(null);
  const [removedPoiIds, setRemovedPoiIds] = useState<Set<string>>(new Set());
  const [markerOverrides, setMarkerOverrides] = useState<Record<string, MarkerData>>({});

  // v6: Candidate POI 本地状态
  const [removedCandidatePoiIds, setRemovedCandidatePoiIds] = useState<Set<string>>(new Set());
  const [promotedCandidateIds, setPromotedCandidateIds] = useState<Set<string>>(new Set());
  const [pendingCandidateReplacement, setPendingCandidateReplacement] = useState<any | null>(null);
  // Ref to avoid stale closure in drawMarkers callback
  const pendingCandidateReplacementRef = useRef<any | null>(null);
  useEffect(() => {
    pendingCandidateReplacementRef.current = pendingCandidateReplacement;
  }, [pendingCandidateReplacement]);

  // v6: Marker refs for external focus — keyed by name, poi_id, gaode_poi_id, name:location
  const markerObjectRefs = useRef<Map<string, any>>(new Map());
  const markerDataRefs = useRef<Map<string, MarkerData>>(new Map());

  const getMarkerPoiId = useCallback((marker: MarkerData) => {
    return marker.poi_id || marker.gaode_poi_id || marker.poiData?.poi_id || `${marker.name}:${marker.location}`;
  }, []);

  const visibleMarkers = useMemo(() => {
    return markers
      .map((marker) => {
        const id = getMarkerPoiId(marker);
        // Apply overrides first
        let m = markerOverrides[id] || marker;
        // v6: Promote candidate to yellow route POI
        if (promotedCandidateIds.has(id)) {
          m = {
            ...m,
            type: 'destination' as const,
            theme: 'yellow' as const,
            is_candidate: false,
            is_display_poi: true,
          };
        }
        return m;
      })
      .filter((marker) => {
        const id = getMarkerPoiId(marker);
        if (removedPoiIds.has(id)) return false;
        // v6: Filter removed candidate POIs
        if (removedCandidatePoiIds.has(id)) return false;
        return true;
      });
  }, [getMarkerPoiId, markerOverrides, markers, removedPoiIds, removedCandidatePoiIds, promotedCandidateIds]);

  // 路线版本号变化时清除乐观 UI 状态
  // 只清除 markerOverrides；removedPoiIds 延迟清除，给新 markers 数据到达的时间
  useEffect(() => {
    if (routeVersion > 0) {
      setMarkerOverrides({});
      setRemovedCandidatePoiIds(new Set());
      setPromotedCandidateIds(new Set());
      setPendingCandidateReplacement(null);
      const timer = setTimeout(() => {
        setRemovedPoiIds(new Set());
      }, 1000);
      return () => clearTimeout(timer);
    }
  }, [routeVersion]);

  // Step 1: 动态加载高德 JS API（使用统一的安全密钥配置）
  useEffect(() => {
    // 检查是否已存在高德 API
    if (window.AMap) {
      console.log('[MapContainer] 高德 API 已存在');
      setScriptLoaded(true);
      return;
    }

    // 检查是否已有脚本在加载中
    const existingScript = document.querySelector('script[src*="webapi.amap.com"]');
    if (existingScript) {
      console.log('[MapContainer] 高德脚本已存在，等待加载...');
      const checkReady = setInterval(() => {
        if (window.AMap) {
          setScriptLoaded(true);
          clearInterval(checkReady);
        }
      }, 100);

      // 超时处理
      setTimeout(() => {
        clearInterval(checkReady);
        if (!window.AMap) {
          setError('高德地图脚本加载超时');
        }
      }, 10000);

      return;
    }

    const apiKey = import.meta.env.VITE_GAODE_JSAPI_KEY;
    if (!apiKey) {
      console.error('[MapContainer] VITE_GAODE_JSAPI_KEY 未配置');
      setError('高德地图 API Key 未配置，请在 .env 文件中设置 VITE_GAODE_JSAPI_KEY');
      return;
    }

    console.log('[MapContainer] 开始加载高德 JS API...');

    // 配置安全密钥（如果存在）
    const securityConfig = import.meta.env.VITE_GAODE_SECURITY_CONFIG;
    if (securityConfig) {
      (window as any)._AMapSecurityConfig = { securityJsCode: securityConfig };
    }

    const script = document.createElement('script');
    script.src = `https://webapi.amap.com/maps?v=2.0&key=${apiKey}&plugin=AMap.Driving,AMap.Walking,AMap.Transfer,AMap.Riding,AMap.InfoWindow,AMap.Marker,AMap.Polyline,AMap.MoveAnimation,AMap.CanvasRenderer,AMap.Scale,AMap.ToolBar,AMap.MapType,AMap.Geolocation`;
    script.async = true;

    script.onload = () => {
      console.log('[MapContainer] 高德脚本加载成功');
      if (window.AMap) {
        setScriptLoaded(true);
      } else {
        setError('高德地图 API 加载完成但未找到 AMap 对象');
      }
    };

    script.onerror = (e) => {
      console.error('[MapContainer] 高德脚本加载失败', e);
      setError('高德地图脚本加载失败，请检查网络连接和 API Key 是否正确');
    };

    document.head.appendChild(script);
  }, []);

  // Step 2: 初始化地图实例
  useEffect(() => {
    if (!scriptLoaded || !mapRef.current || mapInstanceRef.current) return;

    const container = mapRef.current;

    // 确保容器有明确尺寸
    const rect = container.getBoundingClientRect();
    console.log('[Map] 容器尺寸检查:', {
      width: rect.width,
      height: rect.height,
      offsetWidth: container.offsetWidth,
      offsetHeight: container.offsetHeight
    });

    if (rect.width === 0 || rect.height === 0) {
      console.error('[Map] 容器尺寸为0，检查CSS设置');
      setError('地图容器尺寸无效，请确保容器有明确的高度');
      return;
    }

    try {
      console.log('[Map] 开始初始化地图实例...');

      mapInstanceRef.current = new window.AMap.Map(container, {
        center,
        zoom,
        viewMode: '2D',
        resizeEnable: true,
        zooms: [3, 20],
        features: ['bg', 'road', 'building', 'point'],
        mapStyle: 'amap://styles/normal',
      });

      // 添加控件
      mapInstanceRef.current.addControl(new window.AMap.Scale({
        position: 'LB'
      }));

      // 监听地图加载完成
      mapInstanceRef.current.on('complete', () => {
        console.log('[Map] 地图加载完成事件触发');
        setIsMapReady(true);
        setError(null);
      });

      // 监听地图空白区域点击，关闭 POI 弹窗
      mapInstanceRef.current.on('click', (e: any) => {
        // 判断点击目标是地图本身还是覆盖物（Marker/Polyline 等）
        // 覆盖物有 getExtData 方法，地图本身没有
        const clickedOnOverlay = e.target && typeof e.target.getExtData === 'function';
        if (!clickedOnOverlay && infoWindowRef.current) {
          console.log('[Map] 点击地图空白区域，关闭 POI 弹窗');
          const iw = infoWindowRef.current;
          infoWindowRef.current = null;
          iw.close();
          setPoiPopupVisible(false);
          setPoiPopupData(null);
          setPoiPopupPosition(null);
        }
      });

      // 备用：3秒后强制设置就绪
      setTimeout(() => {
        if (mapInstanceRef.current && !isMapReady) {
          console.log('[Map] 备用：强制设置地图就绪');
          setIsMapReady(true);
        }
      }, 3000);

      console.log('[Map] 地图实例创建完成');

    } catch (e) {
      console.error('[Map] 地图初始化失败', e);
      setError(`地图初始化失败: ${e instanceof Error ? e.message : '未知错误'}`);
    }

    return () => {
      if (mapInstanceRef.current) {
        console.log('[Map] 销毁地图实例');
        // Clean up React portal before destroying map
        if (popupRootRef.current) {
          popupRootRef.current.unmount();
          popupRootRef.current = null;
        }
        if (infoWindowRef.current) {
          infoWindowRef.current.close();
          infoWindowRef.current = null;
        }
        mapInstanceRef.current.destroy();
        mapInstanceRef.current = null;
        setIsMapReady(false);
      }
    };
  // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [scriptLoaded]);

  // Step 2b: 当 center/zoom 变化时使用 map 方法更新，避免销毁重建整个地图
  useEffect(() => {
    if (!isMapReady || !mapInstanceRef.current) return;
    mapInstanceRef.current.setCenter(center);
    mapInstanceRef.current.setZoom(zoom);
  }, [isMapReady, center, zoom]);

  // Step 3: 解析 polyline 字符串
  const parsePolyline = useCallback((polyline: string): [number, number][] => {
    if (!polyline || typeof polyline !== 'string') {
      console.warn('[Map] polyline 无效', polyline);
      return [];
    }

    const coords = polyline.split(';')
      .map(coord => {
        const parts = coord.split(',');
        if (parts.length !== 2) return null;
        const [lng, lat] = parts.map(Number);
        if (isNaN(lng) || isNaN(lat)) return null;
        return [lng, lat] as [number, number];
      })
      .filter((c): c is [number, number] => c !== null);

    if (coords.length < 2) {
      console.error('[Map] polyline 坐标点不足:', coords.length);
    } else if (coords.length < 10) {
      console.warn('[Map] polyline 坐标点较少:', coords.length);
    } else {
      console.log('[Map] polyline 解析成功:', coords.length, '个坐标点');
    }

    return coords;
  }, []);

  // Step 4: 绘制路线（polyline）
  const drawPolylines = useCallback(() => {
    if (!isMapReady || !mapInstanceRef.current) {
      console.log('[Map] 地图未就绪，跳过绘制 polyline');
      return;
    }

    if (!dailyPolylines || dailyPolylines.length === 0) {
      console.log('[Map] 无 polyline 数据');
      return;
    }

    const map = mapInstanceRef.current;

    // 清除旧 polyline
    const oldPolylines = map.getAllOverlays('polyline') || [];
    oldPolylines.forEach((p: any) => map.remove(p));
    console.log(`[Map] 清除旧 polyline: ${oldPolylines.length} 条`);

    const drawnPolylineOverlays: any[] = [];
    let drawnCount = 0;

    dailyPolylines.forEach((day, idx) => {
      // v7: 防御 — 跳过不可绘制的假路线
      const polylineSrc = (day as any).polyline_source || '';
      if (polylineSrc === 'fallback_straight' || polylineSrc === 'route_api_failed') {
        console.log(`[Map] skip non-drawable polyline: ${polylineSrc} day=${day.day_index}`);
        return;
      }

      if (!day.polyline || typeof day.polyline !== 'string') {
        console.warn(`[Map] Day ${day.day_index} polyline 无效`);
        return;
      }

      const path = parsePolyline(day.polyline);

      if (path.length < 2) {
        console.warn(`[Map] Day ${day.day_index} 坐标点不足: ${path.length}`);
        return;
      }

      // v7: 再防 degraded 且点数不足
      const isDegraded = (day as any).degraded === true
        || (day as any).polyline_source === 'fallback_straight';
      if (isDegraded && path.length <= 2) {
        console.log(`[Map] skip degraded stub polyline day=${day.day_index}`);
        return;
      }

      // 优先使用路况颜色，其次使用自定义颜色，最后使用默认颜色
      const color = day.trafficStatus
        ? TRAFFIC_COLORS[day.trafficStatus]
        : day.color || DAY_COLORS[idx % DAY_COLORS.length];

      try {
        const polyline = new window.AMap.Polyline({
          path,
          strokeColor: color,
          strokeWeight: 6,
          strokeOpacity: 0.9,
          strokeStyle: isDegraded ? 'dashed' : 'solid',
          lineJoin: 'round',
          lineCap: 'round',
          showDir: true,
          extData: {
            day_index: day.day_index,
            degraded: isDegraded,
            polyline_source: (day as any).polyline_source || '',
          }
        });

        map.add(polyline);
        drawnPolylineOverlays.push(polyline);
        drawnCount++;

        if (isDegraded) {
          console.log(`[Map] Day ${day.day_index} 路线为降级直线占位: ${path.length} 个点`);
        } else {
          console.log(`[Map] Day ${day.day_index} 路线绘制完成: ${path.length} 个点, 颜色: ${color}`);
        }
      } catch (e) {
        console.error(`[Map] Day ${day.day_index} 路线绘制失败`, e);
      }
    });

    // v6: 只对本次绘制的 polyline 做 fitView，完整路线模式适配所有线条，单段模式只适配被选中段
    if (drawnPolylineOverlays.length > 0) {
      map.setFitView(drawnPolylineOverlays, true, [60, 60, 60, 60]);
      console.log(`[Map] 视野自适应完成，绘制了 ${drawnCount} 条路线`);
    }

  }, [isMapReady, dailyPolylines, parsePolyline]);

  // Step 5: 绘制自定义 HTML 标记点
  const drawMarkers = useCallback(() => {
    if (!isMapReady || !mapInstanceRef.current) {
      console.log('[Map] 地图未就绪，跳过绘制 markers');
      return;
    }

    if (!visibleMarkers || visibleMarkers.length === 0) {
      console.log('[Map] 无 marker 数据');
      return;
    }

    const map = mapInstanceRef.current;

    // 清除旧 markers
    const oldMarkers = map.getAllOverlays('marker') || [];
    oldMarkers.forEach((m: any) => map.remove(m));
    console.log(`[Map] 清除旧 markers: ${oldMarkers.length} 个`);

    // v6: 清空并重建 marker refs
    const newMarkerObjects = new Map<string, any>();
    const newMarkerData = new Map<string, MarkerData>();

    let drawnCount = 0;

    visibleMarkers.forEach((marker, idx) => {
      if (!marker.location || typeof marker.location !== 'string') {
        console.warn('[Map] marker 坐标无效', marker);
        return;
      }

      const parts = marker.location.split(',');
      if (parts.length !== 2) {
        console.warn('[Map] marker 坐标格式错误', marker.location);
        return;
      }

      const [lng, lat] = parts.map(Number);
      if (isNaN(lng) || isNaN(lat)) {
        console.warn('[Map] marker 坐标解析失败', marker.location);
        return;
      }

      // 创建自定义 HTML Marker — candidate POIs get a blue dot
      // v6: 如果已在 promotedCandidateIds 中，视为黄色路线点
      const markerPoiId = getMarkerPoiId(marker);
      const isPromoted = promotedCandidateIds.has(markerPoiId);
      const isCandidate = !isPromoted && (marker.type === 'candidate' || marker.is_candidate || marker.theme === 'blue');
      const markerIndex = marker.index;  // undefined for non-display POIs
      const isDisplayPoi = markerIndex != null || marker.is_display_poi === true;
      const isStart = marker.type === 'origin' || marker.type === 'start' || marker.display_label === '起点';
      const htmlContent = isCandidate
        ? `<div style="
            width: 32px;
            height: 32px;
            background: #3B82F6;
            border-radius: 50%;
            display: flex;
            align-items: center;
            justify-content: center;
            box-shadow: 0 2px 8px rgba(0,0,0,0.3);
            cursor: pointer;
            border: 2px solid white;
          "></div>`
        : isStart
        ? `<div style="
            width: 34px;
            height: 34px;
            background: #111827;
            border-radius: 50%;
            display: flex;
            align-items: center;
            justify-content: center;
            font-size: 13px;
            font-weight: 700;
            color: #fff;
            box-shadow: 0 2px 8px rgba(0,0,0,0.3);
            cursor: pointer;
            border: 2px solid white;
          ">起</div>`
        : isDisplayPoi
        ? `<div style="
            width: 32px;
            height: 32px;
            background: #FFD600;
            border-radius: 50%;
            display: flex;
            align-items: center;
            justify-content: center;
            font-size: 14px;
            font-weight: bold;
            color: white;
            box-shadow: 0 2px 8px rgba(0,0,0,0.3);
            cursor: pointer;
            border: 2px solid white;
          ">
            ${markerIndex}
          </div>`
        : `<div style="
            width: 10px;
            height: 10px;
            background: #999;
            border-radius: 50%;
            box-shadow: 0 1px 4px rgba(0,0,0,0.2);
            cursor: pointer;
            border: 1px solid white;
          "></div>`;

      try {
        const markerObj = new window.AMap.Marker({
          position: [lng, lat],
          content: htmlContent,
          offset: new window.AMap.Pixel(0, 0),
          title: marker.name,
          extData: marker
        });

        // 点击事件 - 显示 POI 弹窗（InfoWindow）
        markerObj.on('click', () => {
          console.log('[Map] 点击POI:', marker.name);

          // v6: 如果有待处理的候选替换且点击的是路线 POI，执行替换
          const currentPending = pendingCandidateReplacementRef.current;
          const isRoutePoi = !isCandidate && marker.type !== 'candidate'
            && (marker.type === 'waypoint' || marker.type === 'anchor' || marker.type === 'destination'
                || marker.type === 'origin' || marker.type === 'start' || marker.type === 'meal'
                || marker.type === 'enroute');
          if (currentPending && isRoutePoi) {
            const routePoiId = getMarkerPoiId(marker);
            const candId = getMarkerPoiId(currentPending);
            // 移除路线 POI
            setRemovedPoiIds((prev) => new Set(prev).add(routePoiId));
            // v6: Panel mutation — replace route POI with candidate
            const candPoiForPanel: PanelPoi = {
              order: 0,
              name: currentPending.name || '',
              kind: 'anchor_internal',
              day_index: marker.day_index || 1,
              slot: marker.display_slot || '',
              location: currentPending.location
                ? (typeof currentPending.location === 'string'
                  ? currentPending.location
                  : `${currentPending.location.lng},${currentPending.location.lat}`)
                : '',
              is_start: false,
              transport_text: '',
              recommend_reason: currentPending.recommend_reason || '',
              photo_url: currentPending.photo_url || '',
              rating: currentPending.rating ?? currentPending.gaode_rating ?? null,
              address: currentPending.address || '',
              parent_anchor: currentPending.parent_anchor || '',
              poi_id: currentPending.poi_id,
              gaode_poi_id: currentPending.gaode_poi_id,
              typecode: currentPending.typecode,
              category: currentPending.category,
            } as any;
            import('@/utils/panelPoiReorder').then(({ applyPanelPoiMutation, buildMarkerOrderMap }) => {
              const state = useRouteStore.getState();
              const next = applyPanelPoiMutation(state.panelDays, {
                action: 'replaceWithCandidate',
                candidate: candPoiForPanel,
                replacedPoiKey: routePoiId,
              });
              if (next) {
                const orderMap = buildMarkerOrderMap(next);
                const orderInfo = orderMap[candId] || orderMap[`${currentPending.name}:${currentPending.location}`];
                useRouteStore.getState().setPanelDays(next);
                if (orderInfo) {
                  setMarkerOverrides((prev) => ({
                    ...prev,
                    [candId]: {
                      ...currentPending,
                      type: 'destination' as const,
                      theme: 'yellow' as const,
                      is_candidate: false,
                      is_display_poi: true,
                      index: orderInfo.index,
                      display_order: orderInfo.index,
                      display_slot: orderInfo.display_slot,
                      day_index: orderInfo.day_index,
                    },
                  }));
                }
              }
            });
            // 从候选集合移除
            setRemovedCandidatePoiIds((prev) => new Set(prev).add(candId));
            // 记录偏好
            recordPoiPreference({
              poi_id: routePoiId,
              poi_name: marker.name,
              poi_type: marker.typecode || marker.category || '',
              action: 'delete',
            });
            recordPoiPreference({
              poi_id: candId,
              poi_name: currentPending.name,
              poi_type: currentPending.typecode || currentPending.category || '',
              action: 'like',
            });
            onCandidateAction?.({
              type: 'replace',
              poiId: candId,
              candidateMarker: currentPending,
              routePoiId,
            });
            setPendingCandidateReplacement(null);
            if (infoWindowRef.current) {
              infoWindowRef.current.close();
            }
            return;
          }

          // 构建 POI 弹窗数据
          const poiId = getMarkerPoiId(marker);
          const markerCategory = marker.category || marker.typecode || marker.poiData?.category || marker.poiData?.typecode || marker.type;
          // 图片、评分、地址的兼容读取链（不硬编码默认值）
          const rawPhotoSource = marker.photo_source || marker.poiData?.photo_source || '';
          const resolvedPhoto = firstPhotoUrl(marker);
          const resolvedRating =
            parseRatingValue(marker.rating) ??
            parseRatingValue(marker.gaode_rating) ??
            parseRatingValue(marker.poiData?.rating) ??
            parseRatingValue(marker.poiData?.gaode_rating) ??
            null;
          const resolvedAddress =
            marker.address || marker.formatted_address || marker.poiData?.address || '';
          const resolvedReviewCount =
            marker.reviewCount || marker.poiData?.reviewCount || 0;
          const resolvedOpenHours =
            marker.openHours || marker.poiData?.openHours || '';

          // Filter fallback: if photo_source is "fallback", clear imageUrl and photoSource
          const safePhotoSource = rawPhotoSource === 'fallback' ? '' : rawPhotoSource;
          const safeImageUrl = rawPhotoSource === 'fallback' ? '' : resolvedPhoto;

          // v6: Blue theme tags for candidate POIs
          const isCandidateMarker = marker.type === 'candidate' || marker.is_candidate || marker.theme === 'blue';
          const defaultTagBg = isCandidateMarker ? '#EFF6FF' : '#FFF3CD';
          const defaultTagColor = isCandidateMarker ? '#2563EB' : '#D4A800';

          const poiData: POIData = {
            poiId,
            gaodePoiId: marker.gaode_poi_id || marker.poiData?.gaode_poi_id,
            category: markerCategory,
            typecode: marker.typecode || marker.poiData?.typecode,
            photoSource: safePhotoSource,
            recommendReason: marker.recommend_reason || marker.poiData?.recommend_reason,
            avgCost: marker.avg_cost || marker.poiData?.avg_cost,
            location: marker.location,
            index: isCandidateMarker ? -1 : markerIndex,
            nameEn: marker.name,
            nameCn: marker.nameCn,
            imageUrl: safeImageUrl,
            rating: resolvedRating ?? 0,
            hasRating: resolvedRating != null,
            reviewCount: resolvedReviewCount,
            ranking: marker.ranking || marker.recommend_reason || marker.poiData?.recommend_reason || markerCategory || `路线地点 ${markerIndex}`,
            openHours: resolvedOpenHours,
            queueTime: marker.queueTime || marker.poiData?.queueTime || '',
            address: resolvedAddress,
            tags: marker.tags || [
              { label: markerCategory || (isCandidateMarker ? '备选' : marker.type), type: 'custom', backgroundColor: defaultTagBg, color: defaultTagColor },
              ...(safePhotoSource ? [{ label: safePhotoSource, type: 'custom' as const, backgroundColor: '#E6F7E6', color: '#52C41A' }] : []),
            ],
          };

          // 设置弹窗数据和位置
          setPoiPopupData(poiData);
          setPoiPopupPosition([lng, lat]);
          setPoiPopupVisible(true);

          // 创建或更新 InfoWindow
          if (infoWindowRef.current) {
            infoWindowRef.current.close();
          }

          // 创建容器用于 React 渲染
          const popupContainer = document.createElement('div');
          popupContainer.id = 'poi-popup-container';

          // Make a snapshot of marker data to avoid stale closure references
          const markerSnapshot = { ...marker, poiData: marker.poiData ? { ...marker.poiData } : undefined };

          const renderPopup = (dataForPopup: POIData) => {
            // Clean up previous root if exists
            if (popupRootRef.current) {
              popupRootRef.current.unmount();
              popupRootRef.current = null;
            }
            const root = createRoot(popupContainer);
            popupRootRef.current = root;

            if (isCandidateMarker) {
              // v6: 蓝色候选 POI 弹窗 — 替换、删除、增加三个动作
              root.render(
                <POIPopup
                  data={dataForPopup}
                  visible={true}
                  mode="candidate"
                  theme="blue"
                  onDelete={(data) => {
                    const deletePoiId = data.poiId || `${data.nameEn}:${data.location}`;
                    setRemovedCandidatePoiIds((prev) => new Set(prev).add(deletePoiId));
                    recordPoiPreference({
                      poi_id: data.poiId,
                      poi_name: data.nameEn,
                      poi_type: data.category || data.typecode || '',
                      action: 'delete',
                    });
                    onCandidateAction?.({ type: 'delete', poiId: deletePoiId, candidateMarker: marker });
                    if (infoWindowRef.current) {
                      infoWindowRef.current.close();
                    }
                  }}
                  onAdd={(data) => {
                    const addPoiId = data.poiId || `${data.nameEn}:${data.location}`;
                    setPromotedCandidateIds((prev) => new Set(prev).add(addPoiId));
                    // v6: Panel mutation — add candidate to panelDays
                    const candPoi: PanelPoi = {
                      order: 0,
                      name: data.nameEn,
                      kind: 'anchor_internal',
                      day_index: marker.day_index || 1,
                      slot: marker.display_slot || '',
                      location: data.location || marker.location || '',
                      is_start: false,
                      transport_text: '',
                      recommend_reason: marker.recommend_reason || '',
                      photo_url: marker.photo_url || '',
                      rating: marker.rating ?? marker.gaode_rating ?? null,
                      address: marker.address || '',
                      parent_anchor: marker.parent_anchor || '',
                      poi_id: marker.poi_id,
                      gaode_poi_id: marker.gaode_poi_id,
                      typecode: marker.typecode,
                      category: marker.category,
                      display_slot: marker.display_slot,
                      sub_anchor_name: marker.sub_anchor_name,
                    } as any;
                    import('@/utils/panelPoiReorder').then(({ applyPanelPoiMutation, buildMarkerOrderMap }) => {
                      const state = useRouteStore.getState();
                      const current = state.panelDays;
                      const next = applyPanelPoiMutation(current, {
                        action: 'addCandidate',
                        candidate: candPoi,
                      });
                      if (next) {
                        const orderMap = buildMarkerOrderMap(next);
                        const orderInfo = orderMap[addPoiId] || Object.values(orderMap).find(
                          (v: any) => v.index && candPoi.name && Object.keys(orderMap).some(k => k === addPoiId)
                        ) || Object.values(orderMap).find(
                          (v: any) => v.index
                        );
                        useRouteStore.getState().setPanelDays(next);
                        // Also apply marker override for promoted candidate
                        if (orderInfo) {
                          setMarkerOverrides((prev) => ({
                            ...prev,
                            [addPoiId]: {
                              ...marker,
                              type: 'destination' as const,
                              theme: 'yellow' as const,
                              is_candidate: false,
                              is_display_poi: true,
                              index: orderInfo.index,
                              display_order: orderInfo.index,
                              display_slot: orderInfo.display_slot,
                              day_index: orderInfo.day_index,
                            },
                          }));
                        }
                      }
                    });
                    recordPoiPreference({
                      poi_id: data.poiId,
                      poi_name: data.nameEn,
                      poi_type: data.category || data.typecode || '',
                      action: 'like',
                    });
                    onCandidateAction?.({ type: 'add', poiId: addPoiId, candidateMarker: marker });
                    if (infoWindowRef.current) {
                      infoWindowRef.current.close();
                    }
                  }}
                  onReplace={(data) => {
                    // 设置待替换状态，等待用户点击路线 POI
                    setPendingCandidateReplacement(marker);
                    if (infoWindowRef.current) {
                      infoWindowRef.current.close();
                    }
                    console.log('[Map] 候选 POI 替换模式：请点击地图上的路线 POI 进行替换');
                  }}
                  onClick={(data) => {
                    console.log('[Map] 点击候选POI弹窗:', data.nameEn);
                    setPoiPopupVisible(false);
                    if (infoWindowRef.current) {
                      infoWindowRef.current.close();
                    }
                    setPoiDetailModal({
                      isOpen: true,
                      poiName: data.nameEn,
                      poiId: data.poiId || markerSnapshot.location,
                      location: markerSnapshot.location,
                      poi: markerSnapshot.poiData,
                    });
                  }}
                />
              );
            } else {
              // 原有黄色路线 POI 弹窗逻辑
              root.render(
                <POIPopup
                  data={dataForPopup}
                  visible={true}
                  onFavoriteChange={(data, isFavorited) => {
                    recordPoiPreference({
                      poi_id: data.poiId,
                      poi_name: data.nameEn,
                      poi_type: data.category || data.typecode || '',
                      action: isFavorited ? 'like' : 'dislike',
                    });
                    const index = data.nameEn;
                    console.log(`[Map] POI ${index} 收藏状态: ${isFavorited}`);
                  }}
                  onDelete={(data) => {
                    const deletePoiId = data.poiId || `${data.nameEn}:${data.location}`;
                    setRemovedPoiIds((prev) => new Set(prev).add(deletePoiId));
                    // v6: Panel mutation — delete route POI
                    import('@/utils/panelPoiReorder').then(({ applyPanelPoiMutation }) => {
                      const state = useRouteStore.getState();
                      const next = applyPanelPoiMutation(state.panelDays, {
                        action: 'deleteRoutePoi',
                        poiKey: deletePoiId,
                      });
                      if (next) useRouteStore.getState().setPanelDays(next);
                    });
                    recordPoiPreference({
                      poi_id: data.poiId,
                      poi_name: data.nameEn,
                      poi_type: data.category || data.typecode || '',
                      action: 'delete',
                    });
                    if (infoWindowRef.current) {
                      infoWindowRef.current.close();
                    }
                    onPoiAction?.({ type: 'delete', poiId: deletePoiId });
                  }}
                  onReplaceOpen={(data) => getPoiAlternatives({
                    poi_id: data.gaodePoiId || data.poiId || data.nameEn,
                    poi_name: data.nameEn,
                    location: data.location,
                    category: data.typecode || data.category,
                    limit: 5,
                  })}
                  onReplaceSelect={(data, alternative: AlternativePoi) => {
                    const oldId = data.poiId || `${data.nameEn}:${data.location}`;
                    const [altLng, altLat] = alternative.lnglat || [0, 0];
                    setMarkerOverrides((prev) => ({
                      ...prev,
                      [oldId]: {
                        ...markerSnapshot,
                        poi_id: alternative.poi_id,
                        gaode_poi_id: alternative.gaode_poi_id,
                        name: alternative.name,
                        location: alternative.location
                          ? `${alternative.location.lng},${alternative.location.lat}`
                          : `${altLng},${altLat}`,
                        category: alternative.category,
                        typecode: alternative.typecode,
                        address: alternative.address,
                        rating: alternative.rating,
                        avg_cost: alternative.avg_cost,
                        photo_url: alternative.photo_url,
                        photo_source: alternative.photo_source,
                        poiData: alternative,
                      },
                    }));
                    // v6: Panel mutation — replace route POI
                    import('@/utils/panelPoiReorder').then(({ applyPanelPoiMutation }) => {
                      const state = useRouteStore.getState();
                      const newPoi: PanelPoi = {
                        order: 0,
                        name: alternative.name,
                        kind: 'anchor_internal',
                        day_index: markerSnapshot.day_index || 1,
                        slot: markerSnapshot.display_slot || '',
                        location: alternative.location
                          ? `${alternative.location.lng},${alternative.location.lat}`
                          : `${altLng},${altLat}`,
                        is_start: false,
                        transport_text: '',
                        recommend_reason: '',
                        photo_url: alternative.photo_url || '',
                        rating: alternative.rating ?? null,
                        address: alternative.address || '',
                        parent_anchor: '',
                        poi_id: alternative.poi_id,
                        gaode_poi_id: alternative.gaode_poi_id,
                        typecode: alternative.typecode,
                        category: alternative.category,
                      } as any;
                      const next = applyPanelPoiMutation(state.panelDays, {
                        action: 'replaceRoutePoi',
                        poiKey: oldId,
                        newPoi,
                      });
                      if (next) useRouteStore.getState().setPanelDays(next);
                    });
                    if (infoWindowRef.current) {
                      infoWindowRef.current.close();
                    }
                    onPoiAction?.({ type: 'replace', poiId: oldId, replacementPoi: alternative });
                  }}
                  onAlternativeLike={(alternative, liked) => {
                    recordPoiPreference({
                      poi_id: alternative.poi_id,
                      poi_name: alternative.name,
                      poi_type: alternative.category || alternative.typecode || '',
                      action: liked ? 'like' : 'dislike',
                    });
                  }}
                  onClick={(data) => {
                    console.log('[Map] 点击POI弹窗:', data.nameEn);
                    // 关闭弹窗并打开详情弹窗
                    setPoiPopupVisible(false);
                    if (infoWindowRef.current) {
                      infoWindowRef.current.close();
                    }
                    setPoiDetailModal({
                      isOpen: true,
                      poiName: data.nameEn,
                      poiId: data.poiId || markerSnapshot.location,
                      location: markerSnapshot.location,
                      poi: markerSnapshot.poiData,
                    });
                  }}
                />
              );
            }
          };

          renderPopup(poiData);

          // 创建高德 InfoWindow (使用 any 类型绕过类型检查)
          const infoWindowOptions: any = {
            content: popupContainer,
            isCustom: true,
            offset: new window.AMap.Pixel(0, -30),
          };
          infoWindowRef.current = new window.AMap.InfoWindow(infoWindowOptions);

          // 打开 InfoWindow
          infoWindowRef.current.open(map, [lng, lat]);

          if (!poiData.imageUrl || poiData.hasRating === false || !poiData.address) {
            const detailPoiId = marker.gaode_poi_id || (poiId && !poiId.includes(':') && !poiId.includes(',') ? poiId : '');
            getPoiDetail({
              poi_id: detailPoiId,
              poi_name: marker.name,
              location: marker.location,
              category: marker.typecode || marker.category || marker.type,
            }).then((detail) => {
              if (!detail || !infoWindowRef.current) return;
              mergePoiDetailIntoMarker(marker, detail);
              patchGuestFavoritePoiDetail(marker, detail);
              const enrichedPoiData = mergePoiDetailIntoPopup(poiData, detail, marker.name, marker.location);
              setPoiPopupData(enrichedPoiData);
              renderPopup(enrichedPoiData);
              console.log('[Map] POI详情已补全:', {
                name: marker.name,
                hasPhoto: !!enrichedPoiData.imageUrl,
                hasRating: enrichedPoiData.hasRating,
                hasAddress: !!enrichedPoiData.address,
              });
            });
          }

          // 监听 InfoWindow 关闭事件
          infoWindowRef.current.on('close', () => {
            setPoiPopupVisible(false);
            setPoiPopupData(null);
            setPoiPopupPosition(null);
            // Clean up React root
            if (popupRootRef.current) {
              popupRootRef.current.unmount();
              popupRootRef.current = null;
            }
            infoWindowRef.current = null;
          });
        });

        // v6: Register marker in refs (key by name, poi_id, gaode_poi_id, name:location)
        const pid = marker.poi_id || marker.gaode_poi_id || '';
        const name = marker.name || '';
        const loc = marker.location || '';
        if (name) newMarkerObjects.set(name, markerObj);
        if (pid) newMarkerObjects.set(pid, markerObj);
        if (name && loc) newMarkerObjects.set(`${name}:${loc}`, markerObj);
        if (name) newMarkerData.set(name, marker);
        if (pid) newMarkerData.set(pid, marker);
        if (name && loc) newMarkerData.set(`${name}:${loc}`, marker);

        map.add(markerObj);
        drawnCount++;
      } catch (e) {
        console.error(`[Map] marker ${marker.name} 绘制失败`, e);
      }
    });

    console.log(`[Map] 标记点绘制完成: ${drawnCount} 个`);

    // v6: Update refs
    markerObjectRefs.current = newMarkerObjects;
    markerDataRefs.current = newMarkerData;

  }, [getMarkerPoiId, isMapReady, onPoiAction, onCandidateAction, visibleMarkers, removedPoiIds, promotedCandidateIds, removedCandidatePoiIds]);

  // Step 6: 数据变化时重绘 polylines
  useEffect(() => {
    drawPolylines();
  }, [drawPolylines]);

  // Step 7: 数据变化时重绘 markers
  useEffect(() => {
    drawMarkers();
  }, [drawMarkers]);

  // v6 Step 7a: 外部 POI 焦点 — 定位并可选打开弹窗
  useEffect(() => {
    if (!focusPoiRequest || !isMapReady || !mapInstanceRef.current) return;

    const poiName = focusPoiRequest.poiName;
    const behavior = focusPoiRequest.behavior;
    console.log('[Map] focusPoiRequest:', poiName, behavior);

    // Find marker data by exact name match first, then poi_id, then name:location
    const markerDataMap = markerDataRefs.current;
    const markerObjMap = markerObjectRefs.current;

    let targetMarkerData: MarkerData | undefined = markerDataMap.get(poiName);
    if (!targetMarkerData) {
      // Try finding by scanning keys for poi_id match
      for (const [key, md] of markerDataMap.entries()) {
        if (md.poi_id === poiName || md.gaode_poi_id === poiName) {
          targetMarkerData = md;
          break;
        }
      }
    }
    if (!targetMarkerData) {
      console.warn('[Map] focusPoiRequest: marker not found for', poiName);
      return;
    }

    // Parse location
    const locStr = targetMarkerData.location;
    if (!locStr || typeof locStr !== 'string') return;
    const parts = locStr.split(',');
    if (parts.length !== 2) return;
    const lng = Number(parts[0]);
    const lat = Number(parts[1]);
    if (isNaN(lng) || isNaN(lat)) return;

    // Center map
    const map = mapInstanceRef.current;
    map.setZoomAndCenter(16, [lng, lat]);

    if (behavior === 'openPopup') {
      // Find the AMap marker object and simulate click
      let markerObj = markerObjMap.get(targetMarkerData.name || '');
      if (!markerObj) {
        const pid = targetMarkerData.poi_id || targetMarkerData.gaode_poi_id || '';
        markerObj = markerObjMap.get(pid);
      }
      if (!markerObj) {
        const nameLoc = `${targetMarkerData.name || ''}:${targetMarkerData.location || ''}`;
        markerObj = markerObjMap.get(nameLoc);
      }
      if (!markerObj) {
        // Fallback: find any marker object by iterating
        for (const [key, obj] of markerObjMap.entries()) {
          if (obj.getTitle?.() === targetMarkerData.name || obj.getExtData?.()?.name === targetMarkerData.name) {
            markerObj = obj;
            break;
          }
        }
      }
      if (markerObj && typeof markerObj.emit === 'function') {
        // Simulate click on the marker object
        markerObj.emit('click', { target: markerObj });
      } else {
        console.warn('[Map] focusPoiRequest: AMap marker object not found, cannot open popup');
      }
    }
  }, [focusPoiRequest, isMapReady]);

  // Step 8: 切换 2D/3D 视图
  const toggleViewMode = useCallback(() => {
    if (!mapInstanceRef.current) return;

    const newMode = viewMode === '2D' ? '3D' : '2D';
    setViewMode(newMode);
    mapInstanceRef.current.setViewMode(newMode);
    console.log(`[Map] 切换视图模式: ${newMode}`);
  }, [viewMode]);

  // Step 9: 切换地图样式（标准/卫星）
  const toggleMapStyle = useCallback(() => {
    if (!mapInstanceRef.current) return;

    const newStyle = mapStyle === 'standard' ? 'satellite' : 'standard';
    setMapStyle(newStyle);

    if (newStyle === 'satellite') {
      // 使用 MapType 控件切换卫星图
      const mapType = new window.AMap.MapType({});
      mapInstanceRef.current.addControl(mapType);
      mapInstanceRef.current.setMapStyle('amap://styles/satellite');
    } else {
      mapInstanceRef.current.setMapStyle('amap://styles/normal');
    }
    console.log(`[Map] 切换地图样式: ${newStyle}`);
  }, [mapStyle]);

  // Step 10: 切换交通路况
  const toggleTraffic = useCallback(() => {
    if (!mapInstanceRef.current) return;

    const newEnabled = !trafficEnabled;
    setTrafficEnabled(newEnabled);

    if (newEnabled) {
      const trafficLayer = new window.AMap.TileLayer.Traffic({
        zIndex: 10
      });
      mapInstanceRef.current.add(trafficLayer);
    } else {
      const layers = mapInstanceRef.current.getLayers();
      layers.forEach((layer: any) => {
        if (layer.CLASS_NAME === 'AMap.TileLayer.Traffic') {
          mapInstanceRef.current.remove(layer);
        }
      });
    }
    console.log(`[Map] 交通路况: ${newEnabled ? '开启' : '关闭'}`);
  }, [trafficEnabled]);

  // Step 11: 定位当前位置
  const locateCurrentPosition = useCallback(() => {
    if (!mapInstanceRef.current) return;

    // 使用浏览器原生定位 API
    if (navigator.geolocation) {
      navigator.geolocation.getCurrentPosition(
        (position) => {
          const { longitude, latitude } = position.coords;
          console.log('[Map] 定位成功:', [longitude, latitude]);
          mapInstanceRef.current.setCenter([longitude, latitude]);
          mapInstanceRef.current.setZoom(15);
        },
        (error) => {
          console.error('[Map] 定位失败:', error.message);
        },
        {
          enableHighAccuracy: true,
          timeout: 10000
        }
      );
    } else {
      console.error('[Map] 浏览器不支持定位');
    }
  }, []);

  // Step 12: 缩放控制
  const zoomIn = useCallback(() => {
    if (mapInstanceRef.current) {
      mapInstanceRef.current.zoomIn();
    }
  }, []);

  const zoomOut = useCallback(() => {
    if (mapInstanceRef.current) {
      mapInstanceRef.current.zoomOut();
    }
  }, []);

  // 暴露方法给父组件
  useEffect(() => {
    if (mapInstanceRef.current) {
      (window as any).__mapInstance = mapInstanceRef.current;
    }
    return () => {
      delete (window as any).__mapInstance;
    };
  }, [isMapReady]);

  // 关闭POI详情弹窗
  const closePoiDetailModal = useCallback(() => {
    setPoiDetailModal(prev => ({ ...prev, isOpen: false }));
  }, []);

  return (
    <div className={styles.container}>
      <div
        id={containerId}
        ref={mapRef}
        className={styles.map}
        style={{
          width: '100%',
          height: '100%',
          minHeight: '500px',
          position: 'absolute',
          top: 0,
          left: 0,
          right: 0,
          bottom: 0
        }}
      />

      {/* 加载状态 */}
      {!isMapReady && !error && (
        <div className={styles.loading}>
          <div className={styles.spinner} />
          <span>{scriptLoaded ? '地图初始化中...' : '加载高德地图...'}</span>
        </div>
      )}

      {/* 错误状态 */}
      {error && (
        <div className={styles.error}>
          <span>⚠️ {error}</span>
        </div>
      )}

      {/* 自定义控件 - 右侧竖排 - 禁用状态 */}
      {isMapReady && (
        <div className={styles.customControls}>
          <button
            className={`${styles.controlButton} ${viewMode === '3D' ? styles.active : ''}`}
            disabled
            title="3D视图"
          >
            3D
          </button>
          <button
            className={`${styles.controlButton} ${mapStyle === 'satellite' ? styles.active : ''}`}
            disabled
            title={mapStyle === 'standard' ? '切换到卫星' : '切换到标准'}
          >
            {mapStyle === 'standard' ? '🛰️' : '🗺️'}
          </button>
          <button
            className={`${styles.controlButton} ${trafficEnabled ? styles.active : ''}`}
            disabled
            title="交通路况"
          >
            🚦
          </button>
          <button
            className={styles.controlButton}
            disabled
            title="定位"
          >
            🧭
          </button>
        </div>
      )}

      {/* 缩放控件 - 右下角 - 禁用状态 */}
      {isMapReady && (
        <div className={styles.zoomControls}>
          <button className={styles.zoomButton} disabled title="放大">
            +
          </button>
          <button className={styles.zoomButton} disabled title="缩小">
            −
          </button>
        </div>
      )}

      {/* POI详情弹窗 */}
      <POIDetailModal
        isOpen={poiDetailModal.isOpen}
        onClose={closePoiDetailModal}
        poiName={poiDetailModal.poiName}
        poiId={poiDetailModal.poiId}
        location={poiDetailModal.location}
      />
    </div>
  );
}
