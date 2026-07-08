import React, { useMemo, useRef, useState } from 'react';
import { MapPin, Heart, Trash2, ArrowLeftRight, Plus, X, Bus, Car, Navigation } from 'lucide-react';
import { message } from 'antd';
import { getPoiAlternatives } from '@/api/poi';
import styles from './styles.module.css';

// ── types ──

interface PanelPoiData {
  order: number;
  name: string;
  kind: string;
  day_index: number;
  slot: string;
  location: string;
  is_start: boolean;
  transport_text: string;
  recommend_reason: string;
  photo_url?: string;
  rating?: string | number;
  address?: string;
  parent_anchor?: string;
  poi_id?: string;
  gaode_poi_id?: string;
  typecode?: string;
  category?: string;
  display_slot?: string;
  sub_anchor_name?: string;
  candidate_score?: number;
  // v21: Commerce action fields
  commerce_eligible?: boolean;
  commerce_action?: 'group_deal' | 'ticket' | '';
  deal_type?: string;
  meal_type?: string;
  meal?: string;
  time_slot?: string;
  ugc_review_summary?: string;
  ugc_source?: string;
  ugc_source_type?: string;
  ugc_source_url?: string;
  ugc_evidence_count?: number;
  ugc_match_confidence?: number;
  ugc_status?: 'verified' | 'not_found' | 'timeout' | string;
  ugc_scope?: 'poi' | 'parent_poi' | string;
  ugc_source_name?: string;
  ugc_label?: string;
}

// v21: Unified commerce action detection
type CommerceAction = 'group_deal' | 'ticket' | null;

function getCommerceAction(poi: PanelPoiData): CommerceAction {
  const explicitAction =
    poi.commerce_action ||
    poi.deal_type ||
    (poi.commerce_eligible ? 'group_deal' : '');
  if (explicitAction === 'group_deal') return 'group_deal';
  if (explicitAction === 'ticket') return 'ticket';

  const typecode = String(poi.typecode || '');
  const category = String(poi.category || '');
  const kind = String(poi.kind || '');
  const name = String(poi.name || '');

  const isDining =
    kind === 'meal' ||
    typecode.startsWith('05') ||
    /餐饮|美食|餐厅|饭店|咖啡|甜品|小吃|茶饮/.test(category);
  if (isDining) return 'group_deal';

  const isEntertainment =
    typecode.startsWith('08') ||
    typecode.startsWith('11') ||
    typecode.startsWith('14') ||
    /娱乐|休闲|影院|电影|剧场|运动|游乐|景区|博物馆|展览|演出/.test(category) ||
    /电影院|剧场|游乐园|景区|博物馆|展览馆/.test(name);
  if (isEntertainment) return 'ticket';

  return null;
}

type MealPeriodLabel = '早餐' | '午餐' | '晚餐' | null;

function getMealPeriodLabel(poi: PanelPoiData): MealPeriodLabel {
  // Meal-period badges must come from structured scheduling fields.  A
  // restaurant is not automatically lunch or dinner unless the route assigned
  // it to that period.
  const period = [
    poi.display_slot,
    poi.slot,
    poi.time_slot,
    poi.meal_type,
    poi.meal,
  ]
    .filter(Boolean)
    .join(' ')
    .toLowerCase();

  if (/breakfast|早餐|早饭|早间/.test(period)) return '早餐';
  if (/lunch|午餐|午饭|中餐|中午/.test(period)) return '午餐';
  if (/dinner|晚餐|晚饭|正餐|傍晚/.test(period)) return '晚餐';
  return null;
}

interface PanelSlotData {
  type: string;
  label: string;
  time_range: string;
  pois: PanelPoiData[];
}

interface PanelDayData {
  day_index: number;
  slots: PanelSlotData[];
}

interface RoutePlacesListProps {
  panelDays: PanelDayData[] | null;
  points: any[];
  segments: any[];
  candidatePoints?: any[];
  onPOIClick: (name: string) => void;
  onRouteClick?: (segment: any) => void;
  onPoiAction?: (action: any) => void;
  onCandidatePreview?: (candidate: any | null) => void;
}

// ── helpers ──

const TYPECODE_CATEGORY: Record<string, string> = {
  '05': '餐饮', '06': '购物', '07': '生活服务', '08': '体育休闲',
  '10': '住宿', '11': '风景名胜', '14': '科教文化', '15': '交通设施',
  '16': '金融', '17': '公司企业', '18': '道路附属', '19': '地名地址',
};

function categoryLabel(kind: string, typecode: string): string {
  const prefix = String(typecode || '').slice(0, 2);
  if (TYPECODE_CATEGORY[prefix]) return TYPECODE_CATEGORY[prefix];
  const k = String(kind || '').toLowerCase();
  if (k === 'meal' || k === 'restaurant') return '餐饮';
  if (k === 'anchor' || k === 'anchor_internal') return '景点';
  if (k === 'start' || k === 'origin') return '起点';
  return '地点';
}

function parseLocation(raw: any): { lat: number; lng: number } | null {
  if (!raw) return null;
  if (typeof raw === 'string') {
    const parts = raw.split(',');
    const lng = parseFloat(parts[0]);
    const lat = parseFloat(parts[1]);
    if (!isNaN(lat) && !isNaN(lng)) return { lat, lng };
    return null;
  }
  if (Array.isArray(raw) && raw.length >= 2) {
    return { lng: Number(raw[0]), lat: Number(raw[1]) };
  }
  const lat = Number(raw.lat);
  const lng = Number(raw.lng);
  if (!isNaN(lat) && !isNaN(lng)) return { lat, lng };
  return null;
}

function haversineKm(a: { lat: number; lng: number }, b: { lat: number; lng: number }): number {
  const R = 6371;
  const dLat = ((b.lat - a.lat) * Math.PI) / 180;
  const dLng = ((b.lng - a.lng) * Math.PI) / 180;
  const la1 = (a.lat * Math.PI) / 180;
  const la2 = (b.lat * Math.PI) / 180;
  const x = Math.sin(dLat / 2) ** 2 + Math.cos(la1) * Math.cos(la2) * Math.sin(dLng / 2) ** 2;
  return R * 2 * Math.atan2(Math.sqrt(x), Math.sqrt(1 - x));
}

function formatDist(km: number): string {
  if (km >= 1) return `${km.toFixed(1)}km`;
  return `${Math.round(km * 1000)}m`;
}

function formatDuration(min: number): string {
  if (min >= 60) {
    const h = Math.floor(min / 60);
    const m = Math.round(min % 60);
    return m > 0 ? `${h}小时${m}分钟` : `${h}小时`;
  }
  return `${Math.round(min)}分钟`;
}

function formatDistance(km: number): string {
  if (km >= 1) return `${km.toFixed(1)}km`;
  return `${Math.round(km * 1000)}m`;
}

const TRANSPORT_ICON: Record<string, string> = {
  '步行': '🚶', '骑行': '🚴', '自驾': '🚗',
  '地铁/公交': '🚇', '公交': '🚌', '驾车': '🚗',
};

// ── component ──

export const RoutePlacesList: React.FC<RoutePlacesListProps> = ({
  panelDays,
  points,
  segments,
  candidatePoints = [],
  onPOIClick,
  onRouteClick,
  onPoiAction,
  onCandidatePreview,
}) => {
  const [candidateMode, setCandidateMode] = useState<{
    action: 'replace' | 'add';
    anchorPoi: any;
  } | null>(null);
  const [remoteCandidates, setRemoteCandidates] = useState<any[]>([]);
  const [candidateLoading, setCandidateLoading] = useState(false);
  const candidateRequestId = useRef(0);

  // Find origin point for distance calculation
  const origin = useMemo(() => {
    const startPt = points.find((p: any) =>
      p.kind === 'start' || p.kind === 'origin' || p.display_label === '起点'
    );
    if (startPt) return startPt;
    return points[0] || null;
  }, [points]);

  const originLoc = useMemo(() => parseLocation(origin?.location), [origin]);

  // Build enriched POI list from panelDays + points
  const flatPois = useMemo(() => {
    if (!panelDays || panelDays.length === 0) return [];
    const poiMap = new Map<string, any>();
    for (const pt of points) {
      const key = pt.name || pt.poi_id || '';
      if (key) poiMap.set(key, pt);
    }

    const result: any[] = [];
    for (const day of panelDays) {
      for (const slot of (day.slots || [])) {
        for (const poi of (slot.pois || [])) {
          const enriched = poiMap.get(poi.name) || {};
          result.push({
            ...poi,
            day_index: day.day_index,
            slot: slot.type,
            slotLabel: slot.label,
            photo_url: poi.photo_url || enriched.photo_url || '',
            rating: poi.rating ?? enriched.rating ?? enriched.gaode_rating ?? null,
            typecode: enriched.typecode || '',
            category: enriched.category || '',
            address: poi.address || enriched.address || '',
            recommend_reason: poi.recommend_reason || enriched.recommend_reason || '',
            location: poi.location || enriched.location || '',
            parent_anchor: poi.parent_anchor || enriched.parent_anchor || '',
            kind: poi.kind || enriched.kind || '',
            is_start: poi.is_start || false,
            poi_id: poi.poi_id || enriched.poi_id || '',
            gaode_poi_id: poi.gaode_poi_id || enriched.gaode_poi_id || '',
            display_slot: poi.display_slot || enriched.display_slot || slot.type,
            sub_anchor_name: poi.sub_anchor_name || enriched.sub_anchor_name || '',
            ugc_review_summary: poi.ugc_review_summary || enriched.ugc_review_summary || '',
            ugc_source: poi.ugc_source || enriched.ugc_source || '',
            ugc_source_type: poi.ugc_source_type || enriched.ugc_source_type || '',
            ugc_source_url: poi.ugc_source_url || enriched.ugc_source_url || '',
            ugc_evidence_count: poi.ugc_evidence_count ?? enriched.ugc_evidence_count ?? 0,
            ugc_match_confidence: poi.ugc_match_confidence ?? enriched.ugc_match_confidence ?? 0,
            ugc_status: poi.ugc_status || enriched.ugc_status || 'not_found',
            ugc_scope: poi.ugc_scope || enriched.ugc_scope || '',
            ugc_source_name: poi.ugc_source_name || enriched.ugc_source_name || '',
            ugc_label: poi.ugc_label || enriched.ugc_label || '大众点评搜索摘要',
          });
        }
      }
    }
    return result;
  }, [panelDays, points]);

  const availableCandidates = useMemo(() => {
    const unique = new Map<string, any>();
    for (const candidate of [...(candidatePoints || []), ...remoteCandidates]) {
      const key = candidate.poi_id
        || candidate.gaode_poi_id
        || `${candidate.name || ''}:${typeof candidate.location === 'string' ? candidate.location : JSON.stringify(candidate.location || '')}`;
      if (key) unique.set(String(key), candidate);
    }
    return [...unique.values()];
  }, [candidatePoints, remoteCandidates]);

  // Filter candidates by same day + slot as anchorPoi
  const filteredCandidates = useMemo(() => {
    if (!candidateMode) return [];
    const anchor = candidateMode.anchorPoi;
    const anchorDay = anchor.day_index;
    const anchorSlot = anchor.slot || anchor.display_slot || '';
    const anchorParent = anchor.parent_anchor || anchor.sub_anchor_name || '';

    let filtered = availableCandidates.filter((c: any) => {
      const cDay = c.day ?? c.day_index;
      const cSlot = c.display_slot || c.slot || c.period || '';
      if (cDay != null && cDay !== anchorDay) return false;
      if (anchorSlot && cSlot && cSlot !== anchorSlot) return false;
      return true;
    });

    // If too few, try matching by parent_anchor
    if (filtered.length === 0 && anchorParent) {
      filtered = availableCandidates.filter((c: any) => {
        const cParent = c.parent_name || c.parent_anchor || c.sub_anchor_name || '';
        if (cParent && anchorParent && !cParent.includes(anchorParent) && !anchorParent.includes(cParent)) return false;
        return true;
      });
    }
    return filtered;
  }, [candidateMode, availableCandidates]);

  const loadReplacementCandidates = async (poi: any) => {
    const requestId = ++candidateRequestId.current;
    setCandidateLoading(true);
    setRemoteCandidates([]);
    try {
      const location = typeof poi.location === 'string'
        ? poi.location
        : poi.location?.lng != null && poi.location?.lat != null
          ? `${poi.location.lng},${poi.location.lat}`
          : '';
      const alternatives = await getPoiAlternatives({
        poi_id: poi.gaode_poi_id || poi.poi_id || poi.name,
        poi_name: poi.name,
        location,
        category: poi.typecode || poi.category || '',
        limit: 8,
      });
      if (candidateRequestId.current !== requestId) return;
      setRemoteCandidates((alternatives || []).filter((item: any) =>
        item.name !== poi.name
        && (!poi.poi_id || item.poi_id !== poi.poi_id)
        && (!poi.gaode_poi_id || item.gaode_poi_id !== poi.gaode_poi_id)
      ));
    } catch (error) {
      if (candidateRequestId.current !== requestId) return;
      console.error('[RoutePlacesList] 加载替换候选失败:', error);
      message.error('加载备选地点失败，请稍后重试');
    } finally {
      if (candidateRequestId.current === requestId) setCandidateLoading(false);
    }
  };

  const handlePoiActionClick = (poi: any, actionType: string) => {
    if (actionType === 'delete') {
      const poiKey = poi.name;
      onPoiAction?.({ type: 'delete', poiId: poiKey, poi });
    } else if (actionType === 'replace') {
      setCandidateMode({ action: 'replace', anchorPoi: poi });
      void loadReplacementCandidates(poi);
    } else if (actionType === 'add') {
      setCandidateMode({ action: 'add', anchorPoi: poi });
    }
  };

  const handleCandidateSelect = (candidate: any) => {
    if (!candidateMode) return;
    const anchor = candidateMode.anchorPoi;
    const normalized = normalizeCandidate(candidate);
    if (candidateMode.action === 'replace') {
      onPoiAction?.({ type: 'replace', poiId: anchor.name, replacementPoi: normalized, poi: anchor });
    } else {
      onPoiAction?.({
        type: 'add',
        poiId: normalized.name || candidate.name,
        poi: normalized,
        afterPoiId: anchor.name,
        afterPoiName: anchor.name,
        afterPoiLocation: anchor.location,
      });
    }
    // Clear candidate mode and preview
    setCandidateMode(null);
    candidateRequestId.current += 1;
    setRemoteCandidates([]);
    setCandidateLoading(false);
    onCandidatePreview?.(null);
  };

  const clearCandidateMode = () => {
    setCandidateMode(null);
    candidateRequestId.current += 1;
    setRemoteCandidates([]);
    setCandidateLoading(false);
    onCandidatePreview?.(null);
  };

  // Match segment between two POIs
  const matchSegment = (fromName: string, toName: string, fromOrder: number, toOrder: number) => {
    return segments.find((s: any) => {
      if (s.from_display_order != null && s.to_display_order != null) {
        return s.from_display_order === fromOrder && s.to_display_order === toOrder;
      }
      return s.from_poi === fromName && s.to_poi === toName;
    });
  };

  if (!flatPois.length) {
    return (
      <div className={styles.emptyState}>
        <p>暂无路线地点数据</p>
      </div>
    );
  }

  // ── Candidate mode render ──
  if (candidateMode) {
    const anchor = candidateMode.anchorPoi;
    return (
      <div className={styles.routePlacesList}>
        <div className={styles.candidateHeader}>
          <span className={styles.candidateTitle}>
            {candidateMode.action === 'replace' ? `替换「${anchor.name}」` : `添加到「${anchor.name}」之后`}
          </span>
          <button type="button" className={styles.candidateCancelBtn} onClick={clearCandidateMode}>
            <X size={16} /> 取消
          </button>
        </div>
        {candidateLoading && filteredCandidates.length === 0 ? (
          <div className={styles.emptyState}><p>正在加载备选地点...</p></div>
        ) : filteredCandidates.length === 0 ? (
          <div className={styles.emptyState}><p>暂无可选备选点，请稍后重试</p></div>
        ) : (
          filteredCandidates.map((c: any, idx: number) => (
            <div
              key={c.name || idx}
              className={styles.routePlaceCard}
              onClick={() => onCandidatePreview?.(c)}
            >
              <div className={styles.routePlaceThumb}>
                {c.photo_url ? (
                  <img src={c.photo_url} alt={c.name} />
                ) : (
                  <div className={styles.routePlaceThumbPlaceholder}>
                    <MapPin size={22} color="#ccc" />
                  </div>
                )}
              </div>
              <div className={styles.routePlaceMain}>
                <span className={styles.routePlaceName}>{c.name}</span>
                <div className={styles.routePlaceMeta}>
                  <span className={styles.routePlaceRating}>
                    {c.rating ? `${Number(c.rating).toFixed(1)}星` : '暂无评分'}
                  </span>
                </div>
              </div>
              <button
                type="button"
                className={styles.candidateActionBtn}
                onClick={(e) => { e.stopPropagation(); handleCandidateSelect(c); }}
              >
                {candidateMode.action === 'replace' ? '替换为此点' : '添加到此处'}
              </button>
            </div>
          ))
        )}
      </div>
    );
  }

  // ── Normal list render ──
  // Group by day
  const days = new Map<number, any[]>();
  for (const poi of flatPois) {
    const d = poi.day_index || 1;
    if (!days.has(d)) days.set(d, []);
    days.get(d)!.push(poi);
  }

  return (
    <div className={styles.routePlacesList}>
      {[...days.entries()].map(([dayIdx, pois]) => (
        <div key={dayIdx} className={styles.routePlacesDay}>
          {days.size > 1 && (
            <div className={styles.routePlacesDayTitle}>第{dayIdx}天</div>
          )}
          {pois.map((poi, idx) => {
            const loc = parseLocation(poi.location);
            const distKm = originLoc && loc ? haversineKm(originLoc, loc) : null;
            const isStart = poi.is_start || poi.kind === 'start' || poi.kind === 'origin';
            const commerceAction = getCommerceAction(poi);
            const mealPeriodLabel = getMealPeriodLabel(poi);

            // Find segment after this POI
            const nextPoi = idx < pois.length - 1 ? pois[idx + 1] : null;
            const seg = nextPoi
              ? matchSegment(poi.name, nextPoi.name, poi.order ?? idx, nextPoi.order ?? idx + 1)
              : undefined;

            // Check for origin transport options
            const isOriginSeg = isStart && seg;

            return (
              <React.Fragment key={`${poi.name}-${idx}`}>
                {/* POI card */}
                {!isStart && (
                  <div className={styles.routePlaceRow}>
                    <div className={styles.routePlaceIndex}>{idx}</div>
                    <div className={[styles.routePlaceCardWrap, commerceAction ? styles.routePlaceCardCommerce : ''].filter(Boolean).join(' ')} data-commerce-poi={commerceAction ? 'true' : 'false'}>
                      {mealPeriodLabel && (
                        <span
                          className={styles.mealPeriodBadge}
                          aria-label={`餐段：${mealPeriodLabel}`}
                        >
                          {mealPeriodLabel}
                        </span>
                      )}
                      <div className={styles.routePlaceContent}>
                        <div className={styles.routePlaceMedia}>
                          <button type="button" className={styles.routePlaceThumbButton} onClick={() => onPOIClick(poi.name)}>
                            <div className={styles.routePlaceThumb}>
                              {poi.photo_url ? (
                                <img src={poi.photo_url} alt={poi.name} />
                              ) : (
                                <div className={styles.routePlaceThumbPlaceholder}>
                                  <MapPin size={22} color="#ccc" />
                                </div>
                              )}
                            </div>
                          </button>
                          {/* Commerce CTA — uses pre-computed commerceAction */}
                          {commerceAction === 'group_deal' && (
                            <button type="button" className={styles.poiCommerceBtn} onClick={(e) => { e.stopPropagation(); message.info('团购功能开发中'); }}>
                              团购优惠
                            </button>
                          )}
                          {commerceAction === 'ticket' && (
                            <button type="button" className={styles.poiCommerceBtn} onClick={(e) => { e.stopPropagation(); message.info('购票功能开发中'); }}>
                              点击购票
                            </button>
                          )}
                        </div>
                        <div className={styles.routePlaceInfo}>
                          <button type="button" className={styles.routePlaceTextButton} onClick={() => onPOIClick(poi.name)}>
                            <div className={styles.routePlaceMain}>
                              <div className={styles.routePlaceTitleRow}>
                                <span className={styles.routePlaceName}>{poi.name}</span>
                                {commerceAction && (
                                  <span className={styles.commerceBadge}>美团优惠</span>
                                )}
                                {distKm != null && (
                                  <span className={styles.routePlaceDistance}>{formatDist(distKm)}</span>
                                )}
                              </div>
                              <div className={styles.routePlaceMeta}>
                                <span className={styles.routePlaceRating}>
                                  {poi.rating ? `${Number(poi.rating).toFixed(1)}星` : '暂无评分'}
                                </span>
                                <span className={styles.routePlaceType}>
                                  {categoryLabel(poi.kind, poi.typecode)}
                                </span>
                                {poi.address && (
                                  <span className={styles.routePlaceAddress}>{poi.address}</span>
                                )}
                              </div>
                            </div>
                          </button>
                          {/* Action buttons — inside info column below text */}
                          <div className={styles.routePlaceActions}>
                            <button type="button" className={styles.poiActionBtn} title="收藏" onClick={() => message.info('收藏功能开发中')}>
                              <Heart size={15} />
                            </button>
                            <button type="button" className={styles.poiActionBtn} title="替换" onClick={() => handlePoiActionClick(poi, 'replace')}>
                              <ArrowLeftRight size={15} />
                            </button>
                            <button type="button" className={styles.poiActionBtn} title="增加" onClick={() => handlePoiActionClick(poi, 'add')}>
                              <Plus size={15} />
                            </button>
                            <button type="button" className={styles.poiActionBtn} title="删除" onClick={() => handlePoiActionClick(poi, 'delete')}>
                              <Trash2 size={15} />
                            </button>
                          </div>
                        </div>
                      </div>
                      <div className={styles.ugcReviewBlock} data-ugc-status={poi.ugc_status || 'not_found'}>
                        <div className={styles.ugcReviewHeader}>
                          <span>{poi.ugc_label || '大众点评搜索摘要'}</span>
                          {poi.ugc_status === 'verified' && poi.ugc_source_url && (
                            <a
                              className={styles.ugcReviewLink}
                              href={poi.ugc_source_url}
                              target="_blank"
                              rel="noopener noreferrer"
                              onClick={(event) => event.stopPropagation()}
                            >
                              查看来源
                            </a>
                          )}
                        </div>
                        <div className={styles.ugcReviewText}>
                          {poi.ugc_status === 'verified' && poi.ugc_review_summary?.trim()
                            ? poi.ugc_review_summary.trim()
                            : '暂未检索到可靠的大众点评摘要'}
                        </div>
                        {poi.ugc_status === 'verified' && (
                          <div className={styles.ugcReviewSource}>
                            来源：大众点评 · 博查搜索
                            {poi.ugc_scope === 'parent_poi' && poi.ugc_source_name
                              ? ` · ${poi.ugc_source_name}`
                              : ''}
                          </div>
                        )}
                      </div>
                    </div>
                  </div>
                )}

                {/* Transport connector */}
                {seg && !isOriginSeg && (
                  <div
                    className={styles.routeConnector}
                    onClick={() => onRouteClick?.(seg)}
                    role="button"
                    tabIndex={0}
                  >
                    <div className={styles.routeConnectorLine} />
                    <div className={styles.routeTransportPill}>
                      <span className={styles.routeTransportIcon}>
                        {TRANSPORT_ICON[seg.transport] || '🚶'}
                      </span>
                      <span className={styles.routeTransportText}>
                        {seg.transport || '步行'} {formatDistance(seg.distance_km || 0)} · {formatDuration(seg.duration_min || 0)}
                      </span>
                    </div>
                  </div>
                )}

                {/* Origin transport options */}
                {isOriginSeg && seg.transport_options?.length > 0 && (
                  <div
                    className={`${styles.routeConnector} ${styles.originRouteConnector}`}
                    onClick={() => onRouteClick?.(seg)}
                    role="button"
                    tabIndex={0}
                    onKeyDown={(e) => { if (e.key === 'Enter' || e.key === ' ') { e.stopPropagation(); onRouteClick?.(seg); } }}
                  >
                    <div className={styles.routeConnectorLine} />
                    <div className={styles.originTransportGroup}>
                      {seg.transport_options.map((opt: any, oidx: number) => (
                        <div key={oidx} className={styles.routeTransportPill}>
                          <span className={styles.routeTransportIcon}>
                            {opt.mode === 'transit' ? <Bus size={14} /> : <Car size={14} />}
                          </span>
                          <span className={styles.routeTransportText}>
                            {opt.label} {formatDistance(opt.distance_km)} · {formatDuration(opt.duration_min)}
                          </span>
                        </div>
                      ))}
                      {seg.transport_options.some((o: any) => o.estimated_fare_yuan) && (
                        <button
                          type="button"
                          className={styles.taxiBtn}
                          onClick={(e) => { e.stopPropagation(); message.success('已模拟发起打车'); }}
                        >
                          <Navigation size={14} />
                          <span>一键打车 ¥{seg.transport_options.find((o: any) => o.estimated_fare_yuan)?.estimated_fare_yuan}</span>
                        </button>
                      )}
                    </div>
                  </div>
                )}
              </React.Fragment>
            );
          })}
        </div>
      ))}
    </div>
  );
};

/** Normalize candidate location to consistent format */
function normalizeCandidate(c: any): any {
  const loc = c.location;
  let location: any = loc;
  if (typeof loc === 'string' && loc.includes(',')) {
    const [lng, lat] = loc.split(',').map(Number);
    location = { lng, lat };
  } else if (Array.isArray(loc)) {
    location = { lng: loc[0], lat: loc[1] };
  }
  return {
    ...c,
    name: c.name || '',
    location,
    typecode: c.typecode || '',
    category: c.category || '',
    photo_url: c.photo_url || '',
    rating: c.rating ?? null,
    address: c.address || '',
    poi_id: c.poi_id || c.gaode_poi_id || '',
    gaode_poi_id: c.gaode_poi_id || c.poi_id || '',
  };
}

export default RoutePlacesList;
