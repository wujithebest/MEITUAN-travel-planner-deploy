/**
 * panelPoiReorder — 本地面板 POI 重排工具
 *
 * 提供纯函数 applyPanelPoiMutation，在不请求后端的情况下
 * 对 panelDays 执行 addCandidate / replaceWithCandidate /
 * deleteRoutePoi / replaceRoutePoi 操作并重新编号。
 */

export interface PanelPoi {
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
}

export interface PanelSlot {
  type: string;
  label: string;
  time_range: string;
  pois: PanelPoi[];
  recommend_reason?: string;
}

export interface PanelDay {
  day_index: number;
  slots: PanelSlot[];
}

export interface MutationAddCandidate {
  action: 'addCandidate';
  candidate: PanelPoi & { display_slot?: string; parent_anchor?: string; sub_anchor_name?: string; candidate_score?: number };
}

export interface MutationReplaceWithCandidate {
  action: 'replaceWithCandidate';
  candidate: PanelPoi & { display_slot?: string; parent_anchor?: string; sub_anchor_name?: string };
  replacedPoiKey: string;
}

export interface MutationDeleteRoutePoi {
  action: 'deleteRoutePoi';
  poiKey: string;
}

export interface MutationReplaceRoutePoi {
  action: 'replaceRoutePoi';
  poiKey: string;
  newPoi: PanelPoi;
}

export interface MutationAddCandidateAfterPoi {
  action: 'addCandidateAfterPoi';
  afterPoiKey: string;
  candidate: PanelPoi & { display_slot?: string; parent_anchor?: string; sub_anchor_name?: string; candidate_score?: number };
}

export type PanelMutation =
  | MutationAddCandidate
  | MutationReplaceWithCandidate
  | MutationDeleteRoutePoi
  | MutationReplaceRoutePoi
  | MutationAddCandidateAfterPoi;

const SLOT_ORDER: Record<string, number> = {
  half_day: 1, morning: 1, lunch: 2, afternoon: 3, dinner: 4, evening: 5,
};

const NON_MEAL_SLOTS = new Set(['morning', 'afternoon', 'half_day', 'evening']);

function poiKey(poi: PanelPoi | { name?: string; poi_id?: string; gaode_poi_id?: string; location?: string }): string {
  return (poi as any).poi_id
    || (poi as any).gaode_poi_id
    || (poi.name && (poi as any).location ? `${poi.name}:${(poi as any).location}` : '')
    || (poi as any).name
    || '';
}

function deepClone(obj: any): any {
  return JSON.parse(JSON.stringify(obj));
}

function renumberPanelDays(panelDays: PanelDay[]): PanelDay[] {
  const result = deepClone(panelDays) as PanelDay[];
  let globalOrder = 0;
  for (const day of result.sort((a, b) => a.day_index - b.day_index)) {
    day.slots.sort((a, b) => (SLOT_ORDER[a.type] || 99) - (SLOT_ORDER[b.type] || 99));
    for (const slot of day.slots) {
      const sorted = [...slot.pois].sort((a, b) => (a.order || 0) - (b.order || 0));
      slot.pois = sorted.map((poi) => {
        globalOrder += 1;
        return { ...poi, order: globalOrder };
      });
    }
  }
  return result;
}

/**
 * 找到指定 key 的 POI 在 panelDays 中的位置
 */
function findPoi(panelDays: PanelDay[], key: string): {
  dayIdx: number; slotIdx: number; poiIdx: number; day: PanelDay; slot: PanelSlot; poi: PanelPoi;
} | null {
  for (let di = 0; di < panelDays.length; di++) {
    const day = panelDays[di];
    for (let si = 0; si < day.slots.length; si++) {
      const slot = day.slots[si];
      for (let pi = 0; pi < slot.pois.length; pi++) {
        const poi = slot.pois[pi];
        const candidateKeys = new Set([
          poiKey(poi),
          poi.poi_id || '',
          poi.gaode_poi_id || '',
          poi.name || '',
          poi.name && poi.location ? `${poi.name}:${poi.location}` : '',
        ].filter(Boolean));
        if (candidateKeys.has(key)) {
          return { dayIdx: di, slotIdx: si, poiIdx: pi, day, slot, poi: slot.pois[pi] };
        }
      }
    }
  }
  return null;
}

/**
 * 根据候选点信息找到一个合适的 slot 来插入
 */
function findInsertSlot(panelDays: PanelDay[], candidate: MutationAddCandidate['candidate']): {
  dayIdx: number; slotIdx: number; day: PanelDay; slot: PanelSlot;
} | null {
  const candDay = candidate.day_index || 1;
  const candSlot = candidate.display_slot || candidate.slot || '';
  const candAnchor = candidate.parent_anchor || candidate.sub_anchor_name || '';

  // Find the right day
  let targetDay: PanelDay | undefined;
  for (const day of panelDays) {
    if (day.day_index === candDay) { targetDay = day; break; }
  }
  if (!targetDay && panelDays.length > 0) {
    targetDay = panelDays.find(d => d.day_index === candDay) || panelDays[0];
  }
  if (!targetDay) return null;

  // Try matching slot by type
  if (candSlot) {
    for (let si = 0; si < targetDay.slots.length; si++) {
      if (targetDay.slots[si].type === candSlot) {
        return { dayIdx: panelDays.indexOf(targetDay), slotIdx: si, day: targetDay, slot: targetDay.slots[si] };
      }
    }
  }

  // Try matching by parent anchor name in slot
  if (candAnchor) {
    for (let si = 0; si < targetDay.slots.length; si++) {
      const slot = targetDay.slots[si];
      for (const poi of slot.pois) {
        if (poi.parent_anchor === candAnchor || poi.name === candAnchor) {
          return { dayIdx: panelDays.indexOf(targetDay), slotIdx: si, day: targetDay, slot };
        }
      }
    }
  }

  // Fallback: first non-meal slot on the target day
  for (let si = 0; si < targetDay.slots.length; si++) {
    if (NON_MEAL_SLOTS.has(targetDay.slots[si].type)) {
      return { dayIdx: panelDays.indexOf(targetDay), slotIdx: si, day: targetDay, slot: targetDay.slots[si] };
    }
  }

  // Fallback: afternoon slot, or last slot
  for (let si = 0; si < targetDay.slots.length; si++) {
    if (targetDay.slots[si].type === 'afternoon') {
      return { dayIdx: panelDays.indexOf(targetDay), slotIdx: si, day: targetDay, slot: targetDay.slots[si] };
    }
  }

  const lastSlot = targetDay.slots[targetDay.slots.length - 1];
  if (lastSlot) {
    return { dayIdx: panelDays.indexOf(targetDay), slotIdx: targetDay.slots.length - 1, day: targetDay, slot: lastSlot };
  }

  return null;
}

/**
 * 核心函数：对 panelDays 应用一个 mutation 并返回新的 panelDays
 */
export function applyPanelPoiMutation(
  panelDays: PanelDay[] | null,
  mutation: PanelMutation,
): PanelDay[] | null {
  if (!panelDays || panelDays.length === 0) return panelDays;

  const cloned = deepClone(panelDays) as PanelDay[];

  switch (mutation.action) {
    case 'deleteRoutePoi': {
      const found = findPoi(cloned, mutation.poiKey);
      if (found) {
        found.slot.pois.splice(found.poiIdx, 1);
      }
      break;
    }

    case 'replaceRoutePoi':
    case 'replaceWithCandidate': {
      const key = mutation.action === 'replaceRoutePoi'
        ? mutation.poiKey
        : mutation.replacedPoiKey;
      const newPoiData = mutation.action === 'replaceRoutePoi'
        ? mutation.newPoi
        : mutation.candidate;

      const found = findPoi(cloned, key);
      if (found) {
        // Replace the poi at the found position
        found.slot.pois[found.poiIdx] = {
          ...newPoiData,
          order: found.poi.order,
          day_index: found.day.day_index,
          slot: found.slot.type,
          is_start: false,
          transport_text: found.poi.transport_text || '',
        } as PanelPoi;
      }
      break;
    }

    case 'addCandidate': {
      const insertInfo = findInsertSlot(cloned, mutation.candidate);
      if (insertInfo) {
        const nextOrder = insertInfo.slot.pois.reduce(
          (max, poi) => Math.max(max, Number(poi.order || 0)),
          0,
        ) + 1;
        const newPoi = {
          ...mutation.candidate,
          order: nextOrder,
          day_index: insertInfo.day.day_index,
          slot: insertInfo.slot.type,
          is_start: false,
          transport_text: '',
          kind: mutation.candidate.kind || 'anchor_internal',
        } as PanelPoi;
        insertInfo.slot.pois.push(newPoi);
      }
      break;
    }

    case 'addCandidateAfterPoi': {
      let inserted = false;
      for (const day of cloned) {
        for (const slot of day.slots) {
          const idx = slot.pois.findIndex(p => poiKey(p) === mutation.afterPoiKey);
          if (idx >= 0) {
            const newPoi = {
              ...mutation.candidate,
              order: Number(slot.pois[idx].order || idx + 1) + 0.5,
              day_index: day.day_index,
              slot: slot.type,
              is_start: false,
              transport_text: '',
              kind: mutation.candidate.kind || 'anchor_internal',
            } as PanelPoi;
            slot.pois.splice(idx + 1, 0, newPoi);
            inserted = true;
            break;
          }
        }
        if (inserted) break;
      }
      if (!inserted) {
        // fallback to old addCandidate behavior
        const insertInfo = findInsertSlot(cloned, mutation.candidate);
        if (insertInfo) {
          const nextOrder = insertInfo.slot.pois.reduce(
            (max, poi) => Math.max(max, Number(poi.order || 0)),
            0,
          ) + 1;
          const newPoi = {
            ...mutation.candidate,
            order: nextOrder,
            day_index: insertInfo.day.day_index,
            slot: insertInfo.slot.type,
            is_start: false,
            transport_text: '',
            kind: mutation.candidate.kind || 'anchor_internal',
          } as PanelPoi;
          insertInfo.slot.pois.push(newPoi);
        }
      }
      break;
    }
  }

  return renumberPanelDays(cloned);
}

/**
 * 根据 panelDays 重排结果，生成 marker 的 index/display_order 映射
 * 返回 Record<poiKey, { index, display_order, display_slot, day_index }>
 */
export function buildMarkerOrderMap(panelDays: PanelDay[]): Record<string, {
  index: number;
  display_order: number | null;
  display_slot: string;
  day_index: number;
  is_display_poi: boolean;
}> {
  const map: Record<string, any> = {};
  for (const day of panelDays) {
    for (const slot of day.slots) {
      for (const poi of slot.pois) {
        const key = poiKey(poi);
        if (key) {
          map[key] = {
            index: poi.order,
            display_order: poi.order,
            display_slot: slot.type,
            day_index: day.day_index,
            is_display_poi: true,
          };
        }
      }
    }
  }
  return map;
}
