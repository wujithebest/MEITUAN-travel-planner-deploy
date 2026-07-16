/**
 * PlannerPage - 主规划页面
 * 
 * 布局：
 * - 顶部导航栏
 * - 左侧：ChatPanel (AI 旅游助手聊天框，320px，美团黄背景)
 * - 中间：MapContainer (地图)
 * - 右侧：ItinerarySidebar (行程详情栏，动态弹出)
 * 
 * 数据流：
 * 用户输入 → ChatPanel → 调用 /api/chat → 返回 {reply, route}
 * → 左侧渲染聊天文本（高亮关键字）→ 中间地图解析 route 渲染路线
 * → 规划完成后右侧栏滑入显示行程详情
 */

import React, { useState, useMemo, useCallback, useEffect, useRef } from 'react';
import { useNavigate } from 'react-router-dom';
import { BookOpen, User, Settings, LogOut, ChevronDown, Heart, Clock3, HelpCircle } from 'lucide-react';
import { Avatar, message } from 'antd';
import favoriteRoutesService, { routeHash } from '@/services/favoriteRoutes';
import ChatPanel from '@/components/ChatPanel/ChatPanel';
import HeaderWeather from '@/components/HeaderWeather';
import MapContainer, { MarkerData } from '@/components/MapContainer/MapContainer';
import ItinerarySidebar from '@/components/ItinerarySidebar';
import { useItinerary } from '@/hooks/useItinerary';
import { useChat } from '@/hooks/useChat';
import { useUserStore } from '@/store/userStore';
import { useRouteStore } from '@/store/routeStore';
import { buildRouteTagContext } from '@/utils/routePreferenceTags';
import { getFixedRoute } from '@/api/fixedRoutes';
import ProfileModal from '@/components/ProfileModal';
import SettingsModal from '@/components/SettingsModal';
import RouteHistoryModal from '@/components/RouteHistoryModal';
import FeatureGuide from '@/components/FeatureGuide';
import routeHistoryService, { type RouteHistory } from '@/services/routeHistory';
import {
  getUserDepartureLabel,
  getUserDepartureCoords,
  makeDeviceHomeAddress,
  makeLocationPayload,
  shouldAutoLocateDeparture,
} from '@/utils/locationDefaults';
import { applyPanelPoiMutation } from '@/utils/panelPoiReorder';
import axios from 'axios';
import { buildApiUrl } from '@/config/api.config';
import styles from './PlannerPage.module.css';

/** v20: Strict coordinate normalization. Rejects 0,0, NaN, out-of-range. */
function normalizePoiPayload(alt: any) {
  let loc: { lat: number; lng: number } | null = null;

  if (typeof alt.location === 'string' && alt.location.includes(',')) {
    const [lng, lat] = alt.location.split(',').map(Number);
    loc = { lat, lng };
  } else if (Array.isArray(alt.location) && alt.location.length >= 2) {
    loc = { lng: Number(alt.location[0]), lat: Number(alt.location[1]) };
  } else if (alt.location && typeof alt.location === 'object') {
    const rawLat = Number(alt.location.lat ?? alt.location.latitude);
    const rawLng = Number(alt.location.lng ?? alt.location.longitude);
    if (Number.isFinite(rawLat) && Number.isFinite(rawLng)) {
      loc = { lat: rawLat, lng: rawLng };
    }
  }

  // Validate: reject 0,0, out-of-range, NaN
  if (!loc || !Number.isFinite(loc.lat) || !Number.isFinite(loc.lng)) {
    console.error('[PlannerPage] Invalid POI coordinates', { name: alt.name, location: alt.location });
    return null;
  }
  if (loc.lat === 0 && loc.lng === 0) {
    console.error('[PlannerPage] POI coordinates are 0,0 — rejecting', { name: alt.name });
    return null;
  }
  if (loc.lng < -180 || loc.lng > 180 || loc.lat < -90 || loc.lat > 90) {
    console.error('[PlannerPage] POI coordinates out of range', { name: alt.name, loc });
    return null;
  }

  return {
    poi_id: alt.poi_id || alt.gaode_poi_id || '',
    gaode_poi_id: alt.gaode_poi_id || alt.poi_id || '',
    name: alt.name || '',
    location: loc,
    category: alt.category || '',
    typecode: alt.typecode || '',
    address: alt.address || '',
    rating: alt.rating ?? null,
    avg_cost: alt.avg_cost ?? null,
    photo_url: alt.photo_url || '',
    photo_source: alt.photo_source || '',
  };
}

/** Normalize candidate to map marker */
function normalizeCandidateToMarker(c: any): any | null {
  if (!c) return null;
  const locStr = typeof c.location === 'string'
    ? c.location
    : (c.location ? `${c.location.lng},${c.location.lat}` : '');
  return {
    type: 'candidate_preview',
    name: c.name || '',
    location: locStr,
    poi_id: c.poi_id || c.gaode_poi_id || '',
    gaode_poi_id: c.gaode_poi_id || c.poi_id || '',
    photo_url: c.photo_url || '',
    rating: c.rating,
    category: c.category || '',
    typecode: c.typecode || '',
    address: c.address || '',
  };
}

const PlannerPage: React.FC = () => {
  const navigate = useNavigate();
  const { user, logout, isGuest, ensureGuestSession, updateUser, updateGuestProfile } = useUserStore();
  const autoLocateAttemptedRef = useRef(false);

  const [profileModalOpen, setProfileModalOpen] = useState(false);
  const [settingsModalOpen, setSettingsModalOpen] = useState(false);
  const [historyModalOpen, setHistoryModalOpen] = useState(false);
  const [dropdownOpen, setDropdownOpen] = useState(false);
  const [autoLocatingDeparture, setAutoLocatingDeparture] = useState(false);
  // v18: 单一发送状态，不再按模式隔离
  const [hasSentInSession, setHasSentInSession] = useState(false);

  // v18: 游客初始化标记 — 首次使用时自动弹出身份定制页
  const GUEST_INIT_KEY = 'guest-profile-initialized-v2';
  const [guestOnboardingOpen, setGuestOnboardingOpen] = useState(false);

  // v18: 页面挂载时保障游客会话
  useEffect(() => {
    ensureGuestSession();
  }, []); // eslint-disable-line react-hooks/exhaustive-deps

  useEffect(() => {
    if (!user) return;
    // v22: Hard protect — manual departure must never be overridden
    if ((user.home_location as any)?.source === 'manual') {
      console.log(`[DepartureAudit] skip_device_geolocation reason=manual_departure_exists label=${(user.home_location as any)?.label}`);
      return;
    }
    const ha = user.location?.home_address;
    if (ha && typeof ha === 'object' && (ha.name || ha.full_address || (ha as any).address)) {
      console.log(`[DepartureAudit] skip_device_geolocation reason=home_address_exists`);
      return;
    }
    if (autoLocateAttemptedRef.current) {
      console.log('[Departure] manual or saved location exists, skip auto locate');
      return;
    }
    if (!shouldAutoLocateDeparture(user)) return;

    console.log('[Departure] no saved location, auto locating device');
    autoLocateAttemptedRef.current = true;

    if (!navigator.geolocation) return;
    setAutoLocatingDeparture(true);
    navigator.geolocation.getCurrentPosition(
      async (position) => {
        const { latitude: lat, longitude: lng } = position.coords;
        let name = '当前设备位置';
        try {
          const res = await axios.get(buildApiUrl(`/address/reverse-geocode?lng=${lng}&lat=${lat}`));
          const addr = res.data?.data || res.data;
          name = addr?.address || addr?.formatted_address || name;
        } catch (err) {
          console.warn('[PlannerPage] 设备位置反查地址失败:', err);
        }
        const homeAddr = { ...makeDeviceHomeAddress(lat, lng), name, full_address: name, source: 'device' };
        const homeLocation = { ...makeLocationPayload(lat, lng, name), source: 'device' };
        const current = useUserStore.getState().user;
        if (!current) { setAutoLocatingDeparture(false); return; }
        // v22: Re-check — if manual departure was set during geolocation, abort
        const latest = useUserStore.getState().user;
        if ((latest?.home_location as any)?.source === 'manual') {
          console.log(`[DepartureAudit] device_location_ignored reason=manual_departure_created_during_request`);
          setAutoLocatingDeparture(false);
          return;
        }
        const nextLocation = { ...current.location, latitude: lat, longitude: lng, home_address: homeAddr };
        if (useUserStore.getState().isGuest) {
          updateGuestProfile({ location: nextLocation, home_location: homeLocation });
        } else {
          updateUser({ ...current, location: nextLocation, home_location: homeLocation });
        }
        setAutoLocatingDeparture(false);
      },
      (err) => {
        console.warn('[PlannerPage] 读取设备位置失败:', err);
        setAutoLocatingDeparture(false);
      },
      { timeout: 8000, enableHighAccuracy: false },
    );
  }, [user, updateGuestProfile, updateUser]);

  // ── 功能指引 → 游客偏好弹窗 顺序状态机 ──
  const GUIDE_STORAGE_KEY = 'local-life-route-feature-guide-seen-v2';
  const GUIDE_DELAY_MS = 600;
  const ONBOARDING_AFTER_GUIDE_DELAY_MS = 300;

  // Phase: 'checking' | 'showing' | 'done'
  const [guidePhase, setGuidePhase] = useState<'checking' | 'showing' | 'done'>(() =>
    localStorage.getItem(GUIDE_STORAGE_KEY) ? 'done' : 'checking'
  );

  // Phase → guideOpen 映射
  const guideOpen = guidePhase === 'showing';

  // Phase 1: checking → 延迟后 showing
  // Phase 2: done → 游客未初始化时弹出 onboarding
  useEffect(() => {
    if (guidePhase === 'checking') {
      const timer = window.setTimeout(() => setGuidePhase('showing'), GUIDE_DELAY_MS);
      return () => window.clearTimeout(timer);
    }
    if (guidePhase === 'done' && isGuest && !localStorage.getItem(GUEST_INIT_KEY)) {
      const timer = window.setTimeout(
        () => setGuestOnboardingOpen(true),
        ONBOARDING_AFTER_GUIDE_DELAY_MS
      );
      return () => window.clearTimeout(timer);
    }
  }, [guidePhase, isGuest]);

  // FeatureGuide 关闭：标记 seen → done → 自动触发 onboarding
  const closeFeatureGuide = useCallback(() => {
    localStorage.setItem(GUIDE_STORAGE_KEY, '1');
    setGuidePhase('done');
  }, []);

  // 手动打开 FeatureGuide：关闭 onboarding，强制进入 showing 阶段
  const openFeatureGuide = useCallback(() => {
    setGuestOnboardingOpen(false);
    setGuidePhase('showing');
  }, []);

  // 当 onboarding 打开时，自动关闭 guide（优先保证偏好弹窗可见）
  useEffect(() => {
    if (guestOnboardingOpen && guidePhase === 'showing') {
      localStorage.setItem(GUIDE_STORAGE_KEY, '1');
      setGuidePhase('done');
    }
  }, [guestOnboardingOpen, guidePhase]);

  const [recentHistories, setRecentHistories] = useState<RouteHistory[]>([]);

  // 行程侧边栏状态管理
  const itinerary = useItinerary();

  // 聊天状态管理（必须在 hasSentCurrentMode 之前初始化）
  const chat = useChat();
  const hasSentCurrentMode = hasSentInSession;
  
  // 从 routeStore 获取 CompletePlan 和 mapRouteData
  const currentPlan = useRouteStore(state => state.currentPlan);
  const storeMapRouteData = useRouteStore(state => state.mapRouteData);
  const replanPipelineRoute = useRouteStore(state => state.replanPipelineRoute);
  const isReplanning = useRouteStore(state => state.loading);

  // v28: Build unified route tag context for left-panel & right-sidebar POI tags
  const currentRequestText = useMemo(() => {
    if (currentPlan?.parsed_intent?.raw_text) return currentPlan.parsed_intent.raw_text;
    if (currentPlan?.request_text) return currentPlan.request_text;
    const msgs = chat.messages || [];
    const lastUser = [...msgs].reverse().find((m: any) => m.role === 'user');
    return lastUser?.content || '';
  }, [currentPlan, chat.messages]);

  const routeTagContext = useMemo(
    () => buildRouteTagContext(currentRequestText, currentPlan?.parsed_intent, user),
    [currentRequestText, currentPlan?.parsed_intent, user],
  );

  // 路线版本号（递增时触发 MapContainer 清除乐观 UI）
  const [routeVersion, setRouteVersion] = useState(0);

  // v6: 地图联动状态 — 右侧面板点击触发地图定位
  const [focusPoiRequest, setFocusPoiRequest] = useState<{
    requestId: number;
    poiName: string;
    behavior: 'openPopup' | 'centerOnly';
  } | null>(null);

  // v6: 单段路线显示 — 路线 tab 点击后只显示被选中的那一段
  const [selectedRouteSegment, setSelectedRouteSegment] = useState<any | null>(null);
  // v18: 候选点预览 marker
  const [previewCandidateMarker, setPreviewCandidateMarker] = useState<any | null>(null);

  // 地图路线数据状态（本地状态，优先使用 ChatPanel 传来的数据）
  const [localMapRouteData, setLocalMapRouteData] = useState<{
    polylines: Array<{ day_index: number; polyline: string; color: string }>;
    markers: Array<any>;
    center: [number, number] | null;
  } | null>(null);
  
  // 最终使用的 mapRouteData：优先使用本地状态，否则使用 store 中的数据
  const mapRouteData = localMapRouteData || storeMapRouteData;
  
  // 当 store 中的 mapRouteData 变化时，打印日志
  useEffect(() => {
    if (storeMapRouteData) {
      console.log('[PlannerPage] store.mapRouteData 变化:', {
        polylines: storeMapRouteData.polylines?.length,
        markers: storeMapRouteData.markers?.length,
      });
    }
  }, [storeMapRouteData]);
  
  // 注意：不要把 localMapRouteData 反向转换写回 routeStore。
  // useChat 已经把完整 backend route_data 写入 store；这里曾经只保留
  // name/location/kind/day，导致收藏保存前丢失 photo_url/rating/address。

  // 当前高亮的天数
  const [activeDay, setActiveDay] = useState<number | null>(null);

  const username = user?.username || '用户';

  // v6: 标准化路线段 polyline 为 "lng,lat;lng,lat" 格式
  // 后端 RouteSegment.polyline 为 Folium 格式 [[lat, lng], ...]，需转成 lng,lat
  const normalizeSegmentPolyline = (polyline: any): string => {
    if (!polyline) return '';
    if (typeof polyline === 'string') {
      // 已经是字符串，可能是 "lng,lat;lng,lat" 或 "lat,lng;lat,lng"
      // 检查第一个坐标对：如果第一个值 > 90（不是合法纬度）则是 lng 开头，直接返回
      const firstPair = polyline.split(';')[0];
      if (firstPair) {
        const parts = firstPair.split(',');
        if (parts.length === 2) {
          const v0 = Number(parts[0]);
          if (!isNaN(v0) && Math.abs(v0) <= 90) {
            // 可能是 lat,lng → 需要翻转为 lng,lat
            console.log('[PlannerPage] polyline string detected lat-first, converting...');
            return polyline.split(';').map(p => {
              const [a, b] = p.split(',');
              return `${b},${a}`;
            }).join(';');
          }
        }
      }
      return polyline;
    }
    if (Array.isArray(polyline) && polyline.length >= 2) {
      const first = polyline[0];
      if (Array.isArray(first) && first.length >= 2) {
        // 后端 RouteSegment.polyline 是 Folium 格式 [[lat, lng], ...]
        // 转成 MapContainer 期望的 "lng,lat;lng,lat"
        const result = polyline.map((c: number[]) => `${c[1]},${c[0]}`).join(';');
        console.log('[PlannerPage] normalizeSegmentPolyline array → string, points:', polyline.length, 'sample:', result.substring(0, 30));
        return result;
      }
    }
    console.warn('[PlannerPage] normalizeSegmentPolyline: unrecognized format, type:', typeof polyline);
    return '';
  };

  // 从 mapRouteData 计算地图 polylines（单段模式时只返回被选中段）
  const mapPolylines = useMemo(() => {
    if (selectedRouteSegment) {
      const polyStr = normalizeSegmentPolyline(selectedRouteSegment.polyline);
      console.log('[PlannerPage] single-segment mode, segment:', selectedRouteSegment.from_poi, '→', selectedRouteSegment.to_poi, 'polyStr len:', polyStr.length);
      if (!polyStr || polyStr.split(';').length < 2) {
        console.warn('[PlannerPage] selectedRouteSegment polyline invalid, fallback to full');
        return mapRouteData?.polylines || [];
      }
      return [{
        day_index: selectedRouteSegment.day_index || 1,
        polyline: polyStr,
        color: selectedRouteSegment.color || '#1677ff',
      }];
    }
    if (mapRouteData?.polylines?.length) {
      return mapRouteData.polylines;
    }
    return [];
  }, [mapRouteData, selectedRouteSegment]);

  // 从 mapRouteData 计算地图标记点
  const mapMarkers = useMemo((): MarkerData[] => {
    if (mapRouteData?.markers?.length) {
      return mapRouteData.markers.map((marker) => ({
        ...marker,
        name: marker.name,
        location: marker.location,
        type: marker.type === 'candidate' ? 'candidate' as any
          : marker.type === 'anchor' ? 'destination'
          : marker.type === 'start' ? 'origin'
          : marker.type === 'enroute' ? 'enroute'
          : 'waypoint',
        index: marker.display_order ?? marker.index,  // only display_order, no idx+1 fallback
      }));
    }
    return [];
  }, [mapRouteData]);

  // v18: 从"我的设置 → 路线出发地"获取保存坐标作为初始地图中心
  const savedDepartureLocation = useMemo<[number, number]>(() => {
    return getUserDepartureCoords(user);
  }, [user]);

  // 路线出发地 label：供 HeaderWeather 显示
  const savedDepartureLabel = useMemo(() => {
    return getUserDepartureLabel(user);
  }, [user]);

  // 计算地图中心点：路线数据优先 -> 保存的路线出发地 -> 兜底地址
  const mapCenter = useMemo<[number, number]>(() => {
    if (mapRouteData?.center) {
      return mapRouteData.center;
    }
    return savedDepartureLocation;
  }, [mapRouteData?.center, savedDepartureLocation]);

  // 处理 ChatPanel 路线数据变化
  const handleRouteChange = useCallback((routeData: {
    polylines?: Array<{ day_index: number; polyline: string; color: string }>;
    markers?: Array<any>;
    center?: [number, number] | null;
  } | null | undefined) => {
    // 防御：routeData 为 null/undefined
    if (!routeData) {
      console.warn('[PlannerPage] routeData is null/undefined');
      setLocalMapRouteData(null);
      return;
    }

    // 防御：确保 polylines 和 markers 是数组
    const polylines = Array.isArray(routeData.polylines) ? routeData.polylines : [];
    const markers = Array.isArray(routeData.markers) ? routeData.markers : [];
    const center = routeData.center || null;

    console.log('[PlannerPage] 路线数据更新:', {
      polylines: polylines.length,
      markers: markers.length,
    });

    setLocalMapRouteData({ polylines, markers, center });
    setSelectedRouteSegment(null);  // v6: 新路线数据到达，清除单段选择
  }, []);

  // 处理 ChatPanel 天数高亮变化
  const handleDayChange = useCallback((day: number | null) => {
    console.log('[PlannerPage] 高亮天数变化:', day);
    setActiveDay(day);
  }, []);

  const handleSetLocation = () => {
    setSettingsModalOpen(true);
  };

  // 删除规划历史
  const handleDeleteHistory = useCallback(async (historyId: string) => {
    try {
      await routeHistoryService.deleteHistory(isGuest, historyId);
      // Refresh list
      const list = await routeHistoryService.listHistories(isGuest);
      setRecentHistories(list);
    } catch {
      // ignore
    }
  }, [isGuest]);

  // 统一加载历史/收藏路线
  const handleLoadHistory = useCallback((history: any) => {
    console.log('[PlannerPage] 加载规划历史:', history.title);
    const msgs = history.messages || [];
    chat.replaceMessages(msgs);
    setLocalMapRouteData(null);
    setSelectedRouteSegment(null);  // v6: 加载历史时清除单段选择
    useRouteStore.getState().loadHistoryRoute(history);
    setRouteVersion(v => v + 1);
    itinerary.openSidebar();
  }, [chat, itinerary]);

  /** v18: 路线卡片点击 — 恢复对应路线的地图和行程 */
  const [activeRouteId, setActiveRouteId] = useState<string | null>(null);
  const [fixedRouteLoading, setFixedRouteLoading] = useState(false);

  /** v28: Fixed route select — fetch pre-generated JSON from backend */
  const handleFixedRouteSelect = useCallback(async (fixtureId: string) => {
    if (fixedRouteLoading) return;
    setFixedRouteLoading(true);
    try {
      // A previous SSE request must not be able to overwrite the fixed route.
      chat.resetForFixedRoute();
      const fixture = await getFixedRoute(fixtureId);
      setHasSentInSession(true);
      setLocalMapRouteData(null);
      setSelectedRouteSegment(null);

      const routeData = structuredClone(fixture.route_data || {});
      const mapRouteData = structuredClone(fixture.map_route_data || {});
      const panelDays = structuredClone(fixture.panel_days || []);
      const completePlan = structuredClone(fixture.complete_plan || {});
      const poiDetails = structuredClone(fixture.poi_details || {});
      const summary = structuredClone(fixture.summary || {});
      const fixedRoutePoints = Array.isArray(routeData.points) ? routeData.points : [];
      const fixedRouteReasons = fixedRoutePoints
        .filter((point: any) => point?.name && point.kind !== 'start')
        .map((point: any) => ({
          name: point.name,
          reason: point.recommend_reason || point.tags?.join('、') || '',
        }))
        .filter((item: any) => item.reason);
      const fixedRouteSnapshot = {
        title: fixture.title || fixture.prompt || '路线规划',
        user_input: fixture.prompt || '',
        complete_plan: completePlan,
        route_data: routeData,
        panel_days: panelDays,
        map_route_data: mapRouteData,
        poi_details: poiDetails,
        summary: {
          ...summary,
          poi_count: summary.poi_count || Math.max(fixedRoutePoints.length - 1, 0),
        },
      };
      // Fixed routes must use the same route-card message shape as normal plans.
      // Keeping assistant_message as plain text bypasses the title/reason card UI.
      const messages = [
        { id: `${fixtureId}-user`, role: 'user' as const, content: fixture.prompt || '', timestamp: Date.now() - 1000 },
        {
          id: `${fixtureId}-assistant`,
          role: 'assistant' as const,
          content: '__RECOMMEND_REASONS__',
          displayType: 'recommendReasons' as const,
          timestamp: Date.now(),
          routeData: {
            ...mapRouteData,
            route_recommend_reason: routeData.route_recommend_reason || '',
          },
          recommendReasons: fixedRouteReasons,
          routeCardTitle: fixedRouteSnapshot.title,
          routeSnapshot: fixedRouteSnapshot,
        },
      ];

      chat.replaceMessages(messages);
      useRouteStore.getState().loadHistoryRoute({
        title: fixture.title || fixture.prompt || '',
        complete_plan: completePlan,
        route_data: routeData,
        panel_days: panelDays,
        map_route_data: mapRouteData,
        poi_details: poiDetails,
        route_id: fixture.route_id || routeData?.route_id || fixtureId,
        summary,
        messages,
      });
      setRouteVersion(v => v + 1);
      itinerary.openSidebar();
    } catch (error: any) {
      console.error('[FixedRoute] load failed:', fixtureId, error);
      message.error(error?.message || '固定路线加载失败，请稍后重试');
    } finally {
      setFixedRouteLoading(false);
    }
  }, [chat, fixedRouteLoading, itinerary]);

  /** v18: 路线卡片点击 — 恢复对应路线的地图和行程 */

  const handleRouteCardSelect = useCallback((snapshot: any) => {
    if (!snapshot) return;
    const routeId = snapshot.__active_route_id || snapshot.route_hash || snapshot.title || '';
    setActiveRouteId(routeId);
    setLocalMapRouteData(null);
    setSelectedRouteSegment(null);
    useRouteStore.getState().loadHistoryRoute({
      title: snapshot.title || '路线规划',
      complete_plan: snapshot.complete_plan,
      route_data: snapshot.route_data,
      panel_days: snapshot.panel_days || [],
      map_route_data: snapshot.map_route_data,
      poi_details: snapshot.poi_details || {},
      summary: snapshot.summary || {},
    });
    setRouteVersion(v => v + 1);
    itinerary.openSidebar();
  }, [itinerary]);

  // 处理从收藏加载路线（唯一入口，ProfileModal 不直接调 store）
  const handleLoadFavorite = useCallback((favorite: any) => {
    // 清除本地路线数据，让 store.mapRouteData 生效
    setLocalMapRouteData(null);
    setSelectedRouteSegment(null);  // v6: 加载收藏时清除单段选择
    // 通过 store 恢复路线状态
    useRouteStore.getState().loadFavoriteRoute(favorite);
    // 版本号递增，触发 MapContainer 刷新
    setRouteVersion(v => v + 1);
    // 打开右侧行程面板
    itinerary.openSidebar();
  }, [itinerary]);

  // 处理 POI 操作（删除/替换/增加）—— 触发管线重规划
  const handlePoiAction = useCallback(async (action: {
    type: 'delete' | 'replace' | 'add';
    poiId: string;
    replacementPoi?: any;
    poi?: any;
    afterPoiId?: string;
    afterPoiName?: string;
    afterPoiLocation?: any;
  }) => {
    console.log('[PlannerPage] POI 操作:', action.type, action.poiId);

    const routeState = useRouteStore.getState();

    // v22: Prevent duplicate POI submissions
    if (action.type === 'add' && action.poi) {
      const rawPoints = (routeState.rawRouteData as any)?.points || [];
      const panelPoints = routeState.panelDays?.flatMap(d => d.slots?.flatMap(s => s.pois || [])) || [];
      const allPoints = [...rawPoints, ...panelPoints];
      const dup = allPoints.some((p: any) =>
        (action.poi.gaode_poi_id && p.gaode_poi_id === action.poi.gaode_poi_id) ||
        (action.poi.poi_id && p.poi_id === action.poi.poi_id) ||
        (action.poi.name && p.name === action.poi.name)
      );
      if (dup) {
        message.warning('这个地点已经在路线里了，换一个备选点吧');
        return;
      }
    }
    if (action.type === 'replace' && action.replacementPoi) {
      const rawPoints = (routeState.rawRouteData as any)?.points || [];
      const dup = rawPoints.some((p: any) =>
        p.name !== action.poiId && (
          (action.replacementPoi.gaode_poi_id && p.gaode_poi_id === action.replacementPoi.gaode_poi_id) ||
          (action.replacementPoi.poi_id && p.poi_id === action.replacementPoi.poi_id) ||
          (action.replacementPoi.name && p.name === action.replacementPoi.name)
        )
      );
      if (dup) {
        message.warning('这个地点已经在路线里了，不能重复替换');
        return;
      }
    }
    const allMarkers = routeState.mapRouteData?.markers || [];
    const marker = allMarkers.find(m => {
      return (
        (m.poi_id && m.poi_id === action.poiId) ||
        (m.gaode_poi_id && m.gaode_poi_id === action.poiId) ||
        (m.name && m.name === action.poiId) ||
        (m.name && m.location && `${m.name}:${m.location}` === action.poiId)
      );
    });

    const normalizeLoc = (loc: any): string | undefined => {
      if (!loc) return undefined;
      if (typeof loc === 'string') return loc;
      if (Array.isArray(loc)) return `${loc[0]},${loc[1]}`;
      if (loc.lng != null && loc.lat != null) return `${loc.lng},${loc.lat}`;
      return undefined;
    };

    const targetPoi = action.poi || marker || {};
    const targetLocation = normalizeLoc(targetPoi.location);
    const targetPoiKey = targetPoi.name
      || targetPoi.poi_id
      || targetPoi.gaode_poi_id
      || (targetPoi.name && targetLocation ? `${targetPoi.name}:${targetLocation}` : '')
      || action.poiId;
    const apiPoiId = marker?.poi_id
      || marker?.gaode_poi_id
      || targetPoi.poi_id
      || targetPoi.gaode_poi_id
      || action.poiId;

    const previousPanelDays = routeState.panelDays;
    let optimisticPanelDays = previousPanelDays;
    if (action.type === 'delete') {
      optimisticPanelDays = applyPanelPoiMutation(previousPanelDays, {
        action: 'deleteRoutePoi',
        poiKey: targetPoiKey,
      }) || previousPanelDays;
    } else if (action.type === 'replace' && action.replacementPoi) {
      optimisticPanelDays = applyPanelPoiMutation(previousPanelDays, {
        action: 'replaceRoutePoi',
        poiKey: targetPoiKey,
        newPoi: action.replacementPoi,
      }) || previousPanelDays;
    } else if (action.type === 'add' && action.poi) {
      const panelLocation = normalizeLoc(action.poi.location) || '';
      optimisticPanelDays = applyPanelPoiMutation(previousPanelDays, {
        action: 'addCandidateAfterPoi',
        afterPoiKey: action.afterPoiName || action.afterPoiId || '',
        candidate: {
          ...action.poi,
          order: 0,
          name: action.poi.name || action.poiId,
          kind: action.poi.kind || 'anchor_internal',
          day_index: Number(action.poi.day_index || action.poi.day || 1),
          slot: action.poi.display_slot || action.poi.slot || '',
          location: panelLocation,
          is_start: false,
          transport_text: '',
          recommend_reason: action.poi.recommend_reason || '',
        },
      }) || previousPanelDays;
    }
    if (optimisticPanelDays !== previousPanelDays) {
      routeState.setPanelDays(optimisticPanelDays);
    }

    const apiAction = action.type === 'delete' ? 'remove' : action.type;
    const ops: any[] = [{
      action: apiAction,
      poi_id: apiPoiId,
      gaode_poi_id: marker?.gaode_poi_id || targetPoi.gaode_poi_id || undefined,
      poi_name: marker?.name || targetPoi.name || action.poiId,
      poi_location: normalizeLoc(marker?.location || targetPoi.location),
    }];

    if (action.type === 'replace' && action.replacementPoi) {
      ops[0].poi = normalizePoiPayload(action.replacementPoi);
    }
    if (action.type === 'add' && action.poi) {
      ops[0].poi = { ...normalizePoiPayload(action.poi), location: normalizeLoc(action.poi.location) };
      ops[0].after_poi_id = action.afterPoiId;
      ops[0].after_poi_name = action.afterPoiName;
      ops[0].after_poi_location = normalizeLoc(action.afterPoiLocation);
    }
    try {
      await replanPipelineRoute(ops);
      if (action.type === 'add' && action.poi) {
        const committedState = useRouteStore.getState();
        const committedPoints = (committedState.rawRouteData as any)?.points || [];
        const targetId = action.poi.gaode_poi_id || action.poi.poi_id || '';
        const targetName = action.poi.name || action.poiId;
        const pointCommitted = committedPoints.some((point: any) =>
          (targetId && (point.gaode_poi_id === targetId || point.poi_id === targetId))
          || point.name === targetName
        );
        const panelCommitted = committedState.panelDays.some(day =>
          day.slots.some(slot => slot.pois.some((point: any) =>
            (targetId && (point.gaode_poi_id === targetId || point.poi_id === targetId))
            || point.name === targetName
          ))
        );
        if (!pointCommitted || !panelCommitted) {
          throw new Error(`添加地点未同步到完整路线: ${targetName}`);
        }
      }
      setLocalMapRouteData(null);
      setSelectedRouteSegment(null);
      setPreviewCandidateMarker(null);
      setRouteVersion(v => v + 1);
      message.success(
        action.type === 'delete' ? '你的修改让路线变得更顺畅了' :
        action.type === 'replace' ? '你的修改让路线变得更有趣了' :
        '你的修改让路线更丰富了'
      );
    } catch (error: any) {
      routeState.setPanelDays(previousPanelDays);
      console.error('[PlannerPage] POI 操作失败，已回滚:', error);
      const msg = error?.message || '';
      if (msg.includes('耗') || msg.includes('timeout') || msg.includes('超时')) {
        message.error('路线调整耗时较久，请稍后重试或换一个更近的备选点');
      } else if (msg.includes('已经在路线里') || msg.includes('重复') || msg.includes('DUPLICATE')) {
        message.warning(msg || '这个地点已经在路线里了，请换一个备选点');
      } else if (msg.includes('绕远') || msg.includes('过远') || msg.includes('太远')) {
        message.error('该地点会让路线绕远，请选择更近的备选点');
      } else {
        message.error('路线调整失败，请稍后重试');
      }
    }
  }, [replanPipelineRoute]);

  // v6: 候选 POI 操作回调（本地状态，不触发路线重算）
  // v20: Unified POI mutation handler — delegates to routeStore.executePoiMutation
  const handleCandidateAction = useCallback((action: {
    type: 'delete' | 'add' | 'replace';
    poiId: string;
    candidateMarker?: any;
    routePoiId?: string;
  }) => {
    console.log('[PlannerPage] 候选 POI 操作 (unified):', action.type, action.poiId);
    const { executePoiMutation, mutationStatus } = useRouteStore.getState();
    if (mutationStatus === 'pending') {
      message.warning('正在处理上一个操作，请稍候');
      return;
    }
    const cand = action.candidateMarker;
    if (action.type === 'add' && cand) {
      const norm = normalizePoiPayload(cand);
      if (!norm) { message.error('地点坐标无效，无法添加'); return; }
      executePoiMutation({
        action: 'add', poiId: action.poiId,
        candidate: norm, afterPoiId: action.routePoiId,
      }).catch((err: any) => message.error('添加失败: ' + err.message));
    } else if (action.type === 'replace' && cand) {
      const norm = normalizePoiPayload(cand);
      if (!norm) { message.error('地点坐标无效，无法替换'); return; }
      executePoiMutation({
        action: 'replace', poiId: action.routePoiId || action.poiId,
        candidate: norm,
      }).catch((err: any) => message.error('替换失败: ' + err.message));
    } else if (action.type === 'delete') {
      executePoiMutation({
        action: 'remove', poiId: action.poiId,
      }).catch((err: any) => message.error('删除失败: ' + err.message));
    }
  }, []);

  // v6: 行程 tab POI 点击 → 定位并打开弹窗
  const handleItineraryPOIClick = useCallback((poiName: string) => {
    console.log('[PlannerPage] 行程 POI 点击:', poiName);
    setFocusPoiRequest({
      requestId: Date.now(),
      poiName,
      behavior: 'openPopup',
    });
  }, []);

  // v6: 路线 tab 点击 → 进入单段路线显示
  const handleRouteSegmentClick = useCallback((segment: any) => {
    console.log('[PlannerPage] 路线段点击（单段模式）:', segment?.from_poi, '→', segment?.to_poi);
    setSelectedRouteSegment(segment);
  }, []);

  // v6: 清空单段路线选择 → 恢复完整路线
  const handleRouteSelectionClear = useCallback(() => {
    setSelectedRouteSegment(null);
  }, []);

  // v6: 地点 tab POI 点击 → 只定位不弹窗
  const handleLocationPOIClick = useCallback((poiName: string) => {
    console.log('[PlannerPage] 地点 POI 点击:', poiName);
    setFocusPoiRequest({
      requestId: Date.now(),
      poiName,
      behavior: 'centerOnly',
    });
  }, []);

  // 加载近期规划历史
  useEffect(() => {
    routeHistoryService.listHistories(isGuest).then(setRecentHistories).catch(() => {});
  }, [isGuest]);

  // 当 currentPlan 变化时，自动显示侧边栏
  useEffect(() => {
    if (currentPlan) {
      console.log('[PlannerPage] currentPlan 变化，自动显示侧边栏');
      // 延迟显示侧边栏，让用户看到"规划完成"的消息
      setTimeout(() => {
        itinerary.openSidebar();
      }, 500);
    }
  }, [currentPlan, itinerary]);

  return (
    <div className={styles.container}>
      {/* 顶部导航栏 */}
      <header className={styles.header}>
        <div className={styles.headerLeft}>
          <img src="/logo.png" alt="Logo" className={styles.logo} />
          <h1 className={styles.brandTitle}>
            <span className={styles.brandMain}>言途</span>
            <span className={styles.brandSub}>——本地生活路线规划</span>
          </h1>
        </div>

        <div className={styles.headerCenter}>
          <HeaderWeather
            location={{
              lng: savedDepartureLocation[0],
              lat: savedDepartureLocation[1],
              label: autoLocatingDeparture ? '正在定位...' : savedDepartureLabel,
            }}
            onSetLocationClick={handleSetLocation}
          />
        </div>

        <div className={styles.headerActions}>
          {/* 功能指引按钮 */}
          <button
            className={styles.guideBtn}
            type="button"
            onClick={openFeatureGuide}
            title="查看功能指引"
          >
            <HelpCircle size={16} />
            <span>功能指引</span>
          </button>

          {/* 旅行日记按钮 — 暂禁用 */}
          <button
            className={`${styles.diaryBtn} ${styles.diaryBtnDisabled}`}
            title="此功能待后续迭代开放……"
            aria-disabled="true"
            type="button"
            onClick={(event) => event.preventDefault()}
          >
            <BookOpen size={16} />
            <span>旅行日记</span>
          </button>

          {/* 用户下拉菜单 */}
          <div
            className={styles.userMenu}
            data-guide="user-menu"
            onClick={() => setDropdownOpen(!dropdownOpen)}
          >
            <Avatar size={32} style={{ background: '#FFD100', color: '#333' }}>
              {username.charAt(0).toUpperCase()}
            </Avatar>
            <span className={styles.username}>{username}</span>
            <ChevronDown size={14} className={styles.chevron} />
          </div>

          {/* 下拉菜单浮层 */}
          {dropdownOpen && (
            <div className={styles.dropdown}>
              <div className={styles.dropdownHeader}>
                <Avatar size={36} style={{ background: '#FFD100', color: '#333' }}>
                  {username.charAt(0).toUpperCase()}
                </Avatar>
                <div className={styles.dropdownUserInfo}>
                  <div className={styles.dropdownUsername}>{username}</div>
                  {user?.email && <div className={styles.dropdownEmail}>{user.email}</div>}
                </div>
              </div>
              <div className={styles.dropdownDivider} />
              <div
                className={styles.dropdownItem}
                onClick={() => {
                  setDropdownOpen(false);
                  setProfileModalOpen(true);
                }}
              >
                <Heart size={14} />
                <span>个人收藏</span>
              </div>
              <div
                className={styles.dropdownItem}
                onClick={() => {
                  setDropdownOpen(false);
                  setHistoryModalOpen(true);
                }}
              >
                <Clock3 size={14} />
                <span>规划历史</span>
              </div>
              <div
                className={styles.dropdownItem}
                onClick={() => {
                  setDropdownOpen(false);
                  setSettingsModalOpen(true);
                }}
              >
                <Settings size={14} />
                <span>我的设置</span>
              </div>
              <div className={styles.dropdownDivider} />
              <div
                className={`${styles.dropdownItem} ${styles.dropdownItemDanger}`}
                onClick={async () => {
                  setDropdownOpen(false);
                  await logout();
                  window.location.replace('/');
                }}
              >
                <LogOut size={14} />
                <span>退出登录</span>
              </div>
            </div>
          )}
        </div>
      </header>

      {/* 点击外部关闭下拉菜单 */}
      {dropdownOpen && (
        <div className={styles.dropdownOverlay} onClick={() => setDropdownOpen(false)} />
      )}

      <div className={styles.mainContent}>
        {/* 左侧面板 - AI旅游助手聊天框 */}
        <div className={styles.leftPanel}>
          <ChatPanel
            messages={chat.messages}
            isLoading={chat.isLoading}
            error={chat.error}
            currentPlanningStatus={chat.currentPlanningStatus}
            planningElapsedSeconds={chat.planningElapsedSeconds}
            isPlanningActive={chat.isPlanningActive}
            activeDay={chat.activeDay}
            sendMessage={chat.sendMessage}
            clearChat={() => { chat.clearChat(); setHasSentInSession(false); }}
            setActiveDay={chat.setActiveDay}
            onRouteChange={handleRouteChange}
            onDayChange={handleDayChange}
            onPlanningComplete={(resultText) => {
              console.log('[PlannerPage] 规划完成，触发行程侧边栏显示');
              setHasSentInSession(true);
              itinerary.completePlanning(resultText, []);
              // 刷新近期历史
              routeHistoryService.listHistories(isGuest).then(setRecentHistories).catch(() => {});
            }}
            onToggleSidebar={itinerary.toggleCollapse}
            isSidebarCollapsed={itinerary.collapsed}
            onLoadHistory={handleLoadHistory}
            onDeleteHistory={handleDeleteHistory}
            onSend={() => setHasSentInSession(true)}
            onRouteCardSelect={handleRouteCardSelect}
            activeRouteId={activeRouteId}
            onFixedRouteSelect={handleFixedRouteSelect}
            fixedRouteLoading={fixedRouteLoading}
            onRouteCardFavorite={async (snapshot) => {
              if (snapshot) {
                try {
                  const routeData = snapshot.route_data || {};
                  const completePlan = snapshot.complete_plan || null;
                  const title = snapshot.title || '路线规划';
                  const days = completePlan?.parsed_intent?.days || snapshot.summary?.days || 1;
                  const destination = completePlan?.parsed_intent?.destination || '上海';

                  const favData = {
                    title,
                    destination,
                    days,
                    route_id: routeData?.route_id || String(routeData?.route_id || ''),
                    route_hash: snapshot.route_hash || routeHash({
                      title,
                      days,
                      route_data: routeData,
                    }),
                    complete_plan: completePlan,
                    route_data: routeData,
                    panel_days: snapshot.panel_days || [],
                    map_route_data: snapshot.map_route_data || {},
                    poi_details: snapshot.poi_details || {},
                    summary: snapshot.summary || {
                      poi_count: snapshot.summary?.poi_count || 0,
                      distance: 0,
                      duration: 0,
                    },
                  };

                  await favoriteRoutesService.saveFavorite(isGuest, favData);
                  message.success('已收藏路线');
                } catch {
                  message.error('收藏失败');
                }
              }
            }}
            recentHistories={recentHistories}
            hasSentInSession={hasSentCurrentMode}
          />
        </div>
        
        {/* 中间地图区域 */}
        <div className={styles.mapWrapper} data-guide="map-area">
          {/* 路线重算加载提示 */}
          {isReplanning && (
            <div className={styles.routeLoadingBar}>
              <div className={styles.routeLoadingSpinner} />
              <div className={styles.routeLoadingDots}>
                <span className={styles.routeLoadingDot} />
                <span className={styles.routeLoadingDot} />
                <span className={styles.routeLoadingDot} />
              </div>
              <span className={styles.routeLoadingText}>正在重新优化路线</span>
            </div>
          )}
          <MapContainer
            containerId="gaode-map"
            center={mapCenter}
            zoom={mapRouteData?.center ? 12 : 15}
            dailyPolylines={mapPolylines}
            markers={mapMarkers}
            previewCandidateMarker={previewCandidateMarker}
            onPoiAction={handlePoiAction}
            onCandidateAction={handleCandidateAction}
            routeVersion={routeVersion}
            focusPoiRequest={focusPoiRequest}
          />
        </div>

        {/* 右侧天数高亮指示器 */}
        {activeDay !== null && (
          <div className={styles.dayIndicator}>
            <span className={styles.dayIndicatorText}>Day {activeDay}</span>
          </div>
        )}
      </div>

      {/* 右侧行程栏（动态弹出） */}
      <ItinerarySidebar
        isVisible={itinerary.isVisible || !!currentPlan}
        data={itinerary.data}
        completePlan={currentPlan}
        collapsed={itinerary.collapsed}
        planMode={chat.planMode}
        onToggleCollapse={itinerary.toggleCollapse}
        onClose={() => {
          itinerary.closeSidebar();
        }}
        onItineraryPOIClick={handleItineraryPOIClick}
        onLocationPOIClick={handleLocationPOIClick}
        onRouteClick={handleRouteSegmentClick}
        onRouteSelectionClear={handleRouteSelectionClear}
        onPOIClick={(name) => {
          console.log('[PlannerPage] POI 点击:', name);
        }}
        onTransportClick={(from, to, transport) => {
          console.log('[PlannerPage] 交通点击:', { from, to, transport });
        }}
        onMapClick={(path) => {
          console.log('[PlannerPage] 地图路径点击:', path);
        }}
        onPoiAction={handlePoiAction}
        onCandidatePreview={(candidate) => setPreviewCandidateMarker(candidate ? normalizeCandidateToMarker(candidate) : null)}
        requestText={currentRequestText}
        routeTagContext={routeTagContext}
      />

      {/* 规划历史弹窗 */}
      <RouteHistoryModal
        open={historyModalOpen}
        onClose={() => setHistoryModalOpen(false)}
        onLoadHistory={handleLoadHistory}
        onDeleteHistory={handleDeleteHistory}
      />

      {/* 个人收藏弹窗 */}
      <ProfileModal
        open={profileModalOpen}
        onClose={() => setProfileModalOpen(false)}
        onLoadFavorite={handleLoadFavorite}
      />

      {/* 设置弹窗 — 统一使用三步 onboarding 布局 */}
      <SettingsModal
        mode="onboarding"
        open={settingsModalOpen}
        onClose={() => setSettingsModalOpen(false)}
      />

      {/* v18: 游客首次身份定制（不可关闭/跳过）— 优先于功能指引 */}
      <SettingsModal
        mode="onboarding"
        open={guestOnboardingOpen}
        closable={false}
        onClose={() => setGuestOnboardingOpen(false)}
        onSaved={() => {
          localStorage.setItem(GUEST_INIT_KEY, '1');
          setGuestOnboardingOpen(false);
        }}
      />

      {/* 右侧行程锚点 — 始终存在，用于功能指引定位 */}
      <div className={styles.rightGuideAnchor} data-guide="itinerary-sidebar" aria-hidden="true" />

      {/* 功能指引覆盖层 */}
      <FeatureGuide open={guideOpen} onClose={closeFeatureGuide} />
    </div>
  );
};

export default PlannerPage;
