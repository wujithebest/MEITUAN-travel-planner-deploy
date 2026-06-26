/**
 * 旅游行程侧边栏主容器组件
 * 
 * 功能：
 * 1. 显示解析后的行程数据
 * 2. 支持滑入/滑出动画（从右侧）
 * 3. 支持 SSE 流式更新
 * 
 * 交互流程：
 * - 规划完成后从右侧滑入
 * - 点击返回按钮滑出
 * - 重新规划时先滑出再滑入
 */

import React, { useState, useEffect, useCallback } from 'react';
import { MoreHorizontal, Star } from 'lucide-react';
import { RoutePlacesList } from './RoutePlacesList';
import { useRouteStore } from '@/store/routeStore';
import { useUserStore } from '@/store/userStore';
import favoriteRoutesService, { routeHash } from '@/services/favoriteRoutes';
import { message, Tooltip } from 'antd';
import styles from './styles.module.css';

interface ItinerarySidebarProps {
  /** 是否显示侧边栏 */
  isVisible?: boolean;
  /** 原始文本数据（用于 SSE 流式更新） */
  rawText?: string;
  /** 已解析的行程数据 */
  data?: ParsedItinerary | null;
  /** CompletePlan 数据（来自 routeStore） */
  completePlan?: CompletePlan | null;
  /** 关闭回调 */
  onClose?: () => void;
  /** POI 点击回调（兼容旧版） */
  onPOIClick?: (name: string) => void;
  /** 行程 tab POI 点击 → 打开弹窗 */
  onItineraryPOIClick?: (name: string) => void;
  /** 地点 tab POI 点击 → 只定位不弹窗 */
  onLocationPOIClick?: (name: string) => void;
  /** 路线 tab 点击 → 进入单段路线显示 */
  onRouteClick?: (segment: any) => void;
  /** 切换出"路线"tab 时清空单段路线选择 */
  onRouteSelectionClear?: () => void;
  /** 交通方式点击回调 */
  onTransportClick?: (from: string, to: string, transport: string) => void;
  /** 地图路径点击回调 */
  onMapClick?: (path: string) => void;
  /** 是否收起 */
  collapsed?: boolean;
  /** 收起状态变化回调 */
  onToggleCollapse?: () => void;
  /** 规划模式 */
  planMode?: 'exploratory' | 'planned' | null;
  /** v18: POI 操作回调 */
  onPoiAction?: (action: any) => void;
  /** v18: 候选点预览回调 */
  onCandidatePreview?: (candidate: any | null) => void;
}

export const ItinerarySidebar: React.FC<ItinerarySidebarProps> = ({
  isVisible = false,
  rawText,
  data: initialData,
  completePlan = null,
  onClose,
  onPOIClick,
  onItineraryPOIClick,
  onLocationPOIClick,
  onRouteClick,
  onRouteSelectionClear,
  onTransportClick,
  onMapClick,
  collapsed = false,
  onToggleCollapse,
  planMode = null,
  onPoiAction,
  onCandidatePreview,
}) => {
  const [data, setData] = useState<ParsedItinerary | null>(initialData || null);
  const [textBuffer, setTextBuffer] = useState<string>('');
  const [isAnimating, setIsAnimating] = useState(false);

  // 从 routeStore 获取面板 POI 数据
  const panelDays = useRouteStore(state => state.panelDays);
  const currentPlanFromStore = useRouteStore(state => state.currentPlan);
  const rawRouteData = useRouteStore(state => state.rawRouteData);
  const mapRouteData = useRouteStore(state => state.mapRouteData);

  // 收藏状态
  const isGuest = useUserStore(state => state.isGuest);
  const [isFavorited, setIsFavorited] = useState(false);
  const [favoriteLoading, setFavoriteLoading] = useState(false);

  // 是否有可收藏的路线
  const hasRoute = !!(currentPlanFromStore && (panelDays?.length > 0 || rawRouteData));

  // 当前路线的 hash
  const currentRouteHash = hasRoute ? routeHash({
    title: `${currentPlanFromStore?.parsed_intent?.destination || '上海'} ${currentPlanFromStore?.parsed_intent?.days || 1}日游`,
    days: currentPlanFromStore?.parsed_intent?.days || 1,
    route_data: rawRouteData,
  }) : '';

  // 收藏/取消收藏
  const handleToggleFavorite = async () => {
    if (!currentPlanFromStore || favoriteLoading) return;
    setFavoriteLoading(true);
    try {
      if (isFavorited) {
        message.info('如需取消收藏，请在"个人收藏"中操作');
        setIsFavorited(false);
      } else {
        // 校验路线数据完整性
        const rpLen = rawRouteData?.points?.length || 0;
        const rsLen = rawRouteData?.segments?.length || 0;
        const mpLen = mapRouteData?.polylines?.length || 0;
        const mkLen = mapRouteData?.markers?.length || 0;
        console.log('[Favorite] save payload counts:', { routePoints: rpLen, routeSegments: rsLen, mapPolylines: mpLen, markers: mkLen, panelDays: panelDays?.length || 0 });
        if (rpLen === 0 || rsLen === 0 || mpLen === 0 || mkLen === 0) {
          message.warning('路线数据尚未准备完成，请稍后再收藏');
          setFavoriteLoading(false);
          return;
        }

        // 直接取 store 中最新的 mapRouteData（含正确的 color）
        const currentMapRouteData = useRouteStore.getState().mapRouteData;
        console.log('[Favorite] colors:', currentMapRouteData?.polylines?.map((p: any) => p.color));

        // 构建 poi_details 快照：从 rawRouteData.points + mapRouteData.markers + panelDays 聚合
        const poiDetails: Record<string, any> = {};
        const allPoints = rawRouteData?.points || [];
        const allMarkers = currentMapRouteData?.markers || [];
        const normalizeLocation = (loc: any): string => {
          if (!loc) return '';
          if (typeof loc === 'string') return loc;
          const lng = loc.lng ?? loc.longitude ?? '';
          const lat = loc.lat ?? loc.latitude ?? '';
          return lng !== '' && lat !== '' ? `${lng},${lat}` : '';
        };
        const detailKey = (item: any): string => {
          const name = item?.name || item?.nameEn || '';
          const loc = normalizeLocation(item?.location);
          return item?.poi_id || item?.gaode_poi_id || item?.poiId || item?.gaodePoiId || (name && loc ? `${name}:${loc}` : name);
        };
        const isFallbackPhoto = (url: string, source: string): boolean => {
          if (source === 'fallback') return true;
          if (!url) return false;
          const lowered = url.toLowerCase();
          return lowered.includes('/images/shanghai.jpg') || lowered.includes('unsplash.com/photo-1508804185872');
        };
        const firstPhotoUrl = (source: any): string => {
          if (!source) return '';
          const photoSource = source.photo_source || source.poiData?.photo_source || '';
          if (photoSource === 'fallback') return '';
          const direct = source.photo_url || source.imageUrl || source.photo || source.image || source.poiData?.photo_url || source.poiData?.imageUrl;
          if (direct && !isFallbackPhoto(direct, photoSource)) return direct;
          const photos = source.photos || source.poiData?.photos;
          if (Array.isArray(photos) && photos.length > 0) {
            const first = photos.find((p: any) => {
              const u = p?.url || p?.contentUrl;
              return u && !isFallbackPhoto(u, '');
            });
            return first?.url || first?.contentUrl || '';
          }
          return '';
        };
        const firstRating = (source: any): any => {
          if (!source) return null;
          return source.rating ?? source.gaode_rating ?? source.poiData?.rating ?? source.poiData?.gaode_rating ?? null;
        };
        const firstAddress = (source: any): string => {
          if (!source) return '';
          return source.address || source.formatted_address || source.poiData?.address || '';
        };
        const mergeValue = (next: any, prev: any) => {
          if (next === undefined || next === null || next === '') return prev;
          return next;
        };
        const upsertDetail = (source: any, extra: any = {}) => {
          const mergedSource = { ...extra, ...source };
          const key = detailKey(mergedSource);
          if (!key) return;
          const prev = poiDetails[key] || {};
          const name = mergedSource.name || mergedSource.nameEn || prev.name || '';
          const rawPhotoUrl = firstPhotoUrl(mergedSource);
          const rawPhotoSource = mergedSource.photo_source || mergedSource.photoSource || mergedSource.poiData?.photo_source || '';
          // Strip fallback: only keep photo if both URL and source are valid
          const safePhotoUrl = (rawPhotoUrl && !isFallbackPhoto(rawPhotoUrl, rawPhotoSource)) ? rawPhotoUrl : '';
          const safePhotoSource = safePhotoUrl ? (rawPhotoSource && rawPhotoSource !== 'fallback' ? rawPhotoSource : '') : '';
          const detail = {
            poi_id: mergeValue(mergedSource.poi_id || mergedSource.poiId, prev.poi_id || ''),
            gaode_poi_id: mergeValue(mergedSource.gaode_poi_id || mergedSource.gaodePoiId, prev.gaode_poi_id || ''),
            name,
            location: mergeValue(mergedSource.location, prev.location || ''),
            address: mergeValue(firstAddress(mergedSource), prev.address || ''),
            rating: mergeValue(firstRating(mergedSource), prev.rating ?? null),
            gaode_rating: mergeValue(mergedSource.gaode_rating || mergedSource.poiData?.gaode_rating, prev.gaode_rating ?? null),
            avg_cost: mergeValue(mergedSource.avg_cost || mergedSource.avgCost || mergedSource.poiData?.avg_cost, prev.avg_cost ?? null),
            photo_url: safePhotoUrl || prev.photo_url || '',
            photo_source: safePhotoUrl ? safePhotoSource : (prev.photo_url && !isFallbackPhoto(prev.photo_url, prev.photo_source || '') ? prev.photo_source || '' : ''),
            category: mergeValue(mergedSource.category || mergedSource.type || mergedSource.poiData?.category, prev.category || ''),
            typecode: mergeValue(mergedSource.typecode || mergedSource.poiData?.typecode, prev.typecode || ''),
            recommend_reason: mergeValue(mergedSource.recommend_reason || mergedSource.recommendReason, prev.recommend_reason || ''),
            visit_duration_min: mergeValue(mergedSource.visit_duration_min || mergedSource.visitDurationMin, prev.visit_duration_min ?? null),
            parent_anchor: mergeValue(mergedSource.parent_anchor || mergedSource.parent_name || mergedSource.parentAnchor, prev.parent_anchor || ''),
            reviewCount: mergeValue(mergedSource.reviewCount || mergedSource.poiData?.reviewCount, prev.reviewCount || 0),
            openHours: mergeValue(mergedSource.openHours || mergedSource.poiData?.openHours, prev.openHours || ''),
          };
          // Final safety: if the merged photo_url is a fallback, clear it
          if (detail.photo_url && isFallbackPhoto(detail.photo_url, detail.photo_source || '')) {
            detail.photo_url = '';
            detail.photo_source = '';
          }
          poiDetails[key] = detail;
          const idKey = detail.poi_id || detail.gaode_poi_id;
          if (idKey && !poiDetails[idKey]) {
            poiDetails[idKey] = detail;
          }
        };

        // 收集 panel POI 名称用于补充聚合
        const panelPoiMap: Record<string, any> = {};
        for (const day of (panelDays || [])) {
          for (const slot of (day.slots || [])) {
            for (const poi of (slot.pois || [])) {
              const key = poi.name || '';
              if (key) panelPoiMap[key] = poi;
              upsertDetail(poi);
            }
          }
        }
        for (const pt of allPoints) {
          const name = pt.name || '';
          const matchedMarker = allMarkers.find((m: any) =>
            (pt.poi_id && m.poi_id === pt.poi_id) ||
            (pt.gaode_poi_id && (m.gaode_poi_id === pt.gaode_poi_id || m.poi_id === pt.gaode_poi_id)) ||
            m.name === name
          );
          const panelPoi = panelPoiMap[name];
          upsertDetail(pt, matchedMarker || {});
          if (panelPoi) upsertDetail(pt, panelPoi);
        }
        for (const marker of allMarkers) {
          upsertDetail(marker, panelPoiMap[marker.name] || {});
        }

        const findDetailForItem = (item: any) => {
          const key = detailKey(item);
          if (key && poiDetails[key]) return poiDetails[key];
          const name = item?.name || item?.nameEn || '';
          const loc = normalizeLocation(item?.location);
          return Object.values(poiDetails).find((detail: any) => {
            if (!detail) return false;
            if (item?.poi_id && detail.poi_id === item.poi_id) return true;
            if (item?.gaode_poi_id && detail.gaode_poi_id === item.gaode_poi_id) return true;
            return detail.name === name && (!loc || normalizeLocation(detail.location) === loc);
          }) as any;
        };
        const applyDetail = (item: any) => {
          const detail = findDetailForItem(item);
          if (!detail) return item;
          return {
            ...item,
            poi_id: item.poi_id || detail.poi_id,
            gaode_poi_id: item.gaode_poi_id || detail.gaode_poi_id,
            address: item.address || detail.address,
            rating: item.rating ?? detail.rating,
            gaode_rating: item.gaode_rating ?? detail.gaode_rating ?? detail.rating,
            avg_cost: item.avg_cost ?? detail.avg_cost,
            photo_url: item.photo_url || detail.photo_url,
            photo_source: item.photo_source || detail.photo_source,
            category: item.category || detail.category,
            typecode: item.typecode || detail.typecode,
            recommend_reason: item.recommend_reason || detail.recommend_reason,
            parent_anchor: item.parent_anchor || detail.parent_anchor,
            reviewCount: item.reviewCount || detail.reviewCount,
            openHours: item.openHours || detail.openHours,
          };
        };
        const enrichedRouteData = rawRouteData
          ? { ...rawRouteData, points: (rawRouteData.points || []).map((pt: any) => applyDetail(pt)) }
          : rawRouteData;
        const enrichedMapRouteData = currentMapRouteData
          ? { ...currentMapRouteData, markers: (currentMapRouteData.markers || []).map((marker: any) => applyDetail(marker)) }
          : currentMapRouteData;
        const detailsWithPhoto = Object.values(poiDetails).filter((d: any) => d.photo_url).length;
        const detailsWithRating = Object.values(poiDetails).filter((d: any) => d.rating != null).length;
        const detailsWithAddress = Object.values(poiDetails).filter((d: any) => d.address).length;
        console.log('[Favorite] save poi meta counts:', {
          total: Object.keys(poiDetails).length,
          withPhoto: detailsWithPhoto,
          withRating: detailsWithRating,
          withAddress: detailsWithAddress,
          sample: Object.values(poiDetails).slice(0, 2).map((d: any) => ({ name: d.name, rating: d.rating, hasPhoto: !!d.photo_url })),
        });

        const favData = {
          title: `${currentPlanFromStore?.parsed_intent?.destination || '上海'} ${currentPlanFromStore?.parsed_intent?.days || 1}日游`,
          destination: currentPlanFromStore?.parsed_intent?.destination || '上海',
          days: currentPlanFromStore?.parsed_intent?.days || 1,
          route_id: rawRouteData?.route_id || String(rawRouteData?.route_id || ''),
          route_hash: currentRouteHash,
          complete_plan: currentPlanFromStore,
          route_data: enrichedRouteData,
          panel_days: panelDays,
          map_route_data: enrichedMapRouteData,
          poi_details: poiDetails,
          summary: {
            poi_count: panelDays?.reduce((sum, d) => sum + (d.slots?.reduce((s, slot) => s + (slot.pois?.length || 0), 0) || 0), 0) || 0,
            distance: 0,
            duration: 0,
          },
        };
        await favoriteRoutesService.saveFavorite(isGuest, favData);
        setIsFavorited(true);
        message.success('已收藏');
      }
    } catch {
      message.error('收藏操作失败');
    } finally {
      setFavoriteLoading(false);
    }
  };

  // 调试日志
  useEffect(() => {
    console.log('[ItineraryDebug] Sidebar panelDays:', panelDays?.length || 0, 'days');
    if (panelDays && panelDays.length > 0) {
      console.log('[ItineraryDebug] Sidebar rendering PoiRouteCard');
      panelDays.forEach(day => {
        day.slots.forEach(slot => {
          console.log(`[ItineraryDebug]   ${day.day_index} ${slot.label}: ${slot.pois?.length || 0} POIs`);
        });
      });
    } else {
      console.log('[ItineraryDebug] Sidebar NO panelDays, fallback to ItineraryTab');
      console.log('[ItineraryDebug] currentPlan days:', currentPlanFromStore?.days?.length || 0);
      if (currentPlanFromStore?.days) {
        currentPlanFromStore.days.forEach((d: any) => {
          console.log(`[ItineraryDebug]   day ${d.day_index}: ${d.time_slots?.length || 0} slots`);
        });
      }
    }
  }, [panelDays, currentPlanFromStore]);
  
  // 将 CompletePlan 转换为 ParsedItinerary 格式
  const convertCompletePlanToParsedItinerary = useCallback((plan: CompletePlan): ParsedItinerary => {
    const days = plan.days.map((day: DayPlan) => ({
      dayNumber: day.day_index,
      timeSlots: day.time_slots.map(slot => {
        const isMeal = slot.type === 'lunch' || slot.type === 'dinner';
        if (isMeal) {
          const names = slot.activities.map(a => a.poi.name);
          const firstActivity = slot.activities[0];
          return {
            type: 'meal' as const,
            period: slot.label,
            timeRange: slot.time_range,
            restaurantName: names.join('、'),
            distanceFromLast: firstActivity?.description || '',
            meta: {
              type: firstActivity?.poi?.type === 'restaurant' ? '正餐 POI' : '餐饮推荐',
              rating: firstActivity?.poi?.rating || 0,
              avgCost: firstActivity?.poi?.avg_price || 0,
            },
            routeSteps: [] as { from: string; to: string; transport: string; duration: string }[],
            walkInfo: firstActivity?.description || undefined,
          };
        }
        return {
          type: 'activity' as const,
          period: slot.label,
          timeRange: slot.time_range,
          title: slot.activities.map(a => a.poi.name).join('、'),
          routeSteps: [],
          recommendation: slot.activities[0] ? {
            highlights: slot.activities[0].poi.description || '',
            matchReason: '',
            advice: slot.activities[0].description || '',
            commuteTime: '',
          } : undefined,
        };
      })
      .sort((a, b) => {
        const getOrder = (s: { period?: string; type?: string }) => {
          const key = `${s.type || ''} ${s.period || ''}`;
          if (key.includes('半日') || key.includes('半天') || key.includes('half_day')) return 1;
          if (key.includes('上午') || key.includes('morning')) return 1;
          if (key.includes('午餐') || key.includes('lunch')) return 2;
          if (key.includes('下午') || key.includes('afternoon')) return 3;
          if (key.includes('晚餐') || key.includes('dinner')) return 4;
          if (key.includes('晚上') || key.includes('晚间') || key.includes('evening') || key.includes('night')) return 5;
          return 99;
        };
        return getOrder(a as any) - getOrder(b as any);
      }),
      alongTheWay: [],
      sameBuildingPOIs: [],
    }));
    
    return {
      summary: `${plan.parsed_intent.destination} ${plan.parsed_intent.days}日游`,
      days,
      anchorSummaries: [],
      mapPaths: [],
      // 初始化新的视图结构
      itinerary: {
        days: days.map(day => ({
          dayNumber: day.dayNumber,
          timeSlots: day.timeSlots,
        })),
      },
      locations: { anchors: [] },
      routes: { days: [], totalDistance: 0, totalDuration: 0 },
    };
  }, []);

  // 处理 SSE 流式文本更新
  useEffect(() => {
    if (rawText !== undefined) {
      setTextBuffer(rawText);
      const parsed = parseItinerary(rawText);
      setData(parsed);
    }
  }, [rawText]);

  // 当外部传入已解析数据时更新
  useEffect(() => {
    if (initialData) {
      setData(initialData);
    }
  }, [initialData]);

  // 当 completePlan 变化时，转换为 ParsedItinerary 格式
  useEffect(() => {
    if (completePlan) {
      const parsed = convertCompletePlanToParsedItinerary(completePlan);
      setData(parsed);
    }
  }, [completePlan, convertCompletePlanToParsedItinerary]);

  // 处理显示状态变化时的动画
  useEffect(() => {
    if (isVisible) {
      setIsAnimating(true);
    }
  }, [isVisible]);

  const handlePOIClick = useCallback((name: string) => {
    // Fallback: use old onPOIClick if new callbacks not provided
    onPOIClick?.(name);
  }, [onPOIClick]);

  const handleItineraryPOIClick = useCallback((name: string) => {
    if (onItineraryPOIClick) {
      onItineraryPOIClick(name);
    } else {
      onPOIClick?.(name);  // fallback
    }
  }, [onItineraryPOIClick, onPOIClick]);

  const handleLocationPOIClick = useCallback((name: string) => {
    if (onLocationPOIClick) {
      onLocationPOIClick(name);
    } else {
      onPOIClick?.(name);  // fallback
    }
  }, [onLocationPOIClick, onPOIClick]);

  const handleRouteClick = useCallback((segment: any) => {
    if (onRouteClick) {
      onRouteClick(segment);
    }
  }, [onRouteClick]);

  const handleTransportClick = useCallback((from: string, to: string, transport: string) => {
    onTransportClick?.(from, to, transport);
  }, [onTransportClick]);

  const handleMapClick = useCallback((path: string) => {
    onMapClick?.(path);
  }, [onMapClick]);

  const handleClose = useCallback(() => {
    onClose?.();
  }, [onClose]);

  // 折叠状态
  if (collapsed) {
    return (
      <aside data-guide="itinerary-sidebar" className={`${styles.sidebar} ${styles.collapsed} ${isVisible ? styles.sidebarVisible : ''}`}>
        <button className={styles.toggleBtn} onClick={onToggleCollapse} aria-label="展开行程">
          {'<'}
        </button>
      </aside>
    );
  }

  // 不可见时不渲染
  if (!isVisible && !isAnimating) {
    return null;
  }

  return (
    <aside
      data-guide="itinerary-sidebar"
      className={`${styles.sidebar} ${isVisible ? styles.sidebarVisible : styles.sidebarHidden}`}
      onTransitionEnd={() => {
        if (!isVisible) {
          setIsAnimating(false);
        }
      }}
    >
      {/* 头部 */}
      <header className={styles.header}>
        <button
          className={styles.collapsePanelBtn}
          onClick={onToggleCollapse}
          aria-label="收起行程面板"
          style={{
            width: 44,
            height: 44,
            flexShrink: 0,
            borderRadius: 0,
            background: '#fff',
            color: '#333',
            fontSize: 20,
            border: 'none',
            borderRight: '1px solid #f0f0f0',
            cursor: 'pointer',
          }}
          onMouseEnter={(e) => { (e.currentTarget as HTMLElement).style.background = '#f7f7f7'; }}
          onMouseLeave={(e) => { (e.currentTarget as HTMLElement).style.background = '#fff'; }}
        >
          {'>'}
        </button>
        <h2 className={styles.title}>路线地点</h2>
        <Tooltip title={!hasRoute ? '暂无可收藏路线' : isFavorited ? '已收藏' : '收藏路线'}>
          <button
            className={styles.starBtn}
            onClick={handleToggleFavorite}
            disabled={!hasRoute || favoriteLoading}
            aria-label={isFavorited ? '已收藏' : '收藏路线'}
            style={{
              width: 32,
              height: 32,
              display: 'flex',
              alignItems: 'center',
              justifyContent: 'center',
              border: 'none',
              background: 'transparent',
              borderRadius: 6,
              cursor: hasRoute ? 'pointer' : 'not-allowed',
              opacity: hasRoute ? 1 : 0.4,
            }}
            onMouseEnter={(e) => { if (hasRoute) (e.currentTarget as HTMLElement).style.background = '#f0f0f0'; }}
            onMouseLeave={(e) => { (e.currentTarget as HTMLElement).style.background = 'transparent'; }}
          >
            <Star
              size={20}
              color={isFavorited ? '#f5b400' : '#666'}
              fill={isFavorited ? '#FFD100' : 'none'}
            />
          </button>
        </Tooltip>
        <button className={styles.moreBtn} aria-label="更多选项">
          <MoreHorizontal size={20} />
        </button>
      </header>

      {/* 内容区域 */}
      <div className={styles.content}>
        {(!panelDays || panelDays.length === 0) && (!rawRouteData?.points?.length) ? (
          <div className={styles.emptyState}>
            <p>暂无行程数据</p>
            <p className={styles.emptyHint}>请在聊天中描述您的旅行需求</p>
          </div>
        ) : (
          <RoutePlacesList
            panelDays={panelDays}
            points={rawRouteData?.points || []}
            segments={rawRouteData?.segments || []}
            candidatePoints={rawRouteData?.candidate_points || []}
            onPOIClick={handleLocationPOIClick}
            onRouteClick={handleRouteClick}
            onPoiAction={onPoiAction}
            onCandidatePreview={onCandidatePreview}
          />
        )}
      </div>

    </aside>
  );
};

export default ItinerarySidebar;
