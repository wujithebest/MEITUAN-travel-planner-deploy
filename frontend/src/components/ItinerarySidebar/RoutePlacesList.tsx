import React, { useMemo } from 'react';
import { MapPin } from 'lucide-react';
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
  onPOIClick: (name: string) => void;
  onRouteClick?: (segment: any) => void;
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
  onPOIClick,
  onRouteClick,
}) => {
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
          });
        }
      }
    }
    return result;
  }, [panelDays, points]);

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

            // Find segment after this POI
            const nextPoi = idx < pois.length - 1 ? pois[idx + 1] : null;
            const seg = nextPoi
              ? matchSegment(poi.name, nextPoi.name, poi.order ?? idx, nextPoi.order ?? idx + 1)
              : undefined;

            return (
              <React.Fragment key={`${poi.name}-${idx}`}>
                {/* POI card */}
                {!isStart && (
                  <div className={styles.routePlaceRow}>
                    <div className={styles.routePlaceIndex}>{idx}</div>
                    <button
                      type="button"
                      className={styles.routePlaceCard}
                      onClick={() => onPOIClick(poi.name)}
                    >
                      <div className={styles.routePlaceThumb}>
                        {poi.photo_url ? (
                          <img src={poi.photo_url} alt={poi.name} />
                        ) : (
                          <div className={styles.routePlaceThumbPlaceholder}>
                            <MapPin size={22} color="#ccc" />
                          </div>
                        )}
                      </div>
                      <div className={styles.routePlaceMain}>
                        <div className={styles.routePlaceTitleRow}>
                          <span className={styles.routePlaceName}>{poi.name}</span>
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
                        <div className={styles.routePlaceReason}>
                          {poi.recommend_reason || poi.address || '符合本次路线偏好'}
                        </div>
                      </div>
                    </button>
                  </div>
                )}

                {/* Transport connector */}
                {seg && (
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
              </React.Fragment>
            );
          })}
        </div>
      ))}
    </div>
  );
};

export default RoutePlacesList;
