/**
 * v28: Unified route tag context for left-panel "命中/偏好" and right-panel per-POI tags.
 * Left panel uses matchedKeywords + preferenceTags as the label pool.
 * Right panel filters each tag per-POI based on matched_facets, POI type, and corpus evidence.
 */

export interface RouteTagContext {
  /** Left-panel "命中" — keywords from user input + parsed intent + theme facets */
  matchedKeywords: string[];
  /** Left-panel "偏好" — user profile preference labels */
  preferenceTags: string[];
  /** Theme facet IDs for route-level matching */
  themeFacets: string[];
  /** Raw user input text */
  rawText: string;
}

// v28: Keywords mapped from parsed intent fields
const INTENT_KEYWORD_SOURCES = [
  'raw_keywords',
  'micro_keywords',
  'micro_poi_keywords',
  'search_keywords',
  'theme_label',
  'primary_query',
  'activity_facet',
  'food_pref_keywords',
  'meal_search_keywords',
];

// v28: User profile preference label mappings (same as ChatPanel.tsx)
const PREF_ID_TO_LABEL: Record<string, string> = {
  history: '历史文化', food: '美食探店', nature: '自然风光',
  shopping: '购物娱乐', art: '艺术展览', photography: '拍照打卡',
  family: '亲子游玩', adventure: '户外探险', citywalk: '城市漫游',
};

const ACTIVITY_TAG_TO_LABEL: Record<string, string> = {
  '历史文化': '历史文化', '美食': '美食探店', '自然风光': '自然风光', '购物娱乐': '购物娱乐',
  '文艺': '艺术展览', '夜生活': '夜生活', '拍照': '拍照打卡', '亲子': '亲子游玩',
  '户外': '户外探险', '城市漫游': '城市漫游', '本地特色': '在地市井', '康养疗愈': '康养疗愈',
};

// v28: Extract explicit targets from user input (places + food)
const PLACE_PATTERNS = [
  '北海公园', '三里河公园', '景山公园', '天安门', '故宫', '颐和园',
  '798', '什刹海', '亮马河', '外滩', '豫园', '望京', '恭王府',
];
const FOOD_PATTERNS = [
  '烤鸭', '川菜', '北京菜', '咖啡馆', '咖啡店', '日料', '火锅',
  '清淡', '涮羊肉', '炸酱面', '小吃',
];
const KW_PATTERNS = [
  '下班路上', '下班', '顺便', '买水果', '简单吃晚饭', '简单晚饭',
  '咖啡', '日料', '地铁', '步行', '不绕路', '附近', '预算',
  '安静', '人少', '夜景', '拍照', '亲子', '情侣',
  '本地生活', '免费', '室内', '户外', '一日游', '半天',
  '轻松', '不赶', '约会', '朋友', '带娃', '老人',
  '火锅', '烧烤', '素食', '清淡', '重辣', '小吃',
  '看展', '逛街', '购物', '爬山', '骑车', '跑步',
];
const DISPLAY_TAG_RULES = [
  { tag: '适合拍照', keywords: ['拍照', '出片', '打卡', '摄影'] },
  { tag: '文艺路线', keywords: ['文艺', '艺术', '展览', '小众'] },
  { tag: '咖啡馆', keywords: ['咖啡', '咖啡馆', '咖啡店'] },
  { tag: '特色小店', keywords: ['特色小店', '小店', '买手店', '杂货店'] },
  { tag: '节奏轻松', keywords: ['节奏轻松', '轻松一点', '慢一点', '不赶', '散散步', '逛逛', '散步'] },
  { tag: '地道北京菜', keywords: ['北京菜', '地道', '烤鸭', '涮羊肉'] },
  { tag: '看日落', keywords: ['日落', '夕阳'] },
  { tag: '口味兼容', keywords: ['不吃辣', '川菜', '两边都能接受', '清淡'] },
  { tag: '夜景', keywords: ['夜景', '拍夜景'] },
  { tag: '河边散步', keywords: ['河边', '走走'] },
  { tag: '附近', keywords: ['附近', '附近逛逛'] },
  { tag: '好吃的', keywords: ['好吃的', '吃顿', '找一家', '餐厅'] },
];

export function buildRouteTagContext(
  rawText: string,
  parsedIntent: any,
  user: any,
): RouteTagContext {
  const matchedKeywords: string[] = [];
  const seen = new Set<string>();

  // 1. Explicit place/food names from rawText
  for (const p of PLACE_PATTERNS) {
    if (rawText.includes(p)) { matchedKeywords.push(p); seen.add(p); }
  }
  for (const f of FOOD_PATTERNS) {
    if (rawText.includes(f)) { matchedKeywords.push(f); seen.add(f); }
  }
  // 2. Generic keyword patterns
  for (const kw of KW_PATTERNS) {
    if (rawText.includes(kw) && !seen.has(kw)) { matchedKeywords.push(kw); seen.add(kw); }
  }
  // 3. Display tags
  for (const rule of DISPLAY_TAG_RULES) {
    if (rule.keywords.some(kw => rawText.includes(kw)) && !seen.has(rule.tag)) {
      matchedKeywords.push(rule.tag);
      seen.add(rule.tag);
    }
  }
  // 4. From parsed intent
  if (parsedIntent) {
    for (const field of INTENT_KEYWORD_SOURCES) {
      const val = parsedIntent[field];
      if (!val) continue;
      const arr = Array.isArray(val) ? val : [val];
      for (const item of arr) {
        const s = typeof item === 'string' ? item : (item?.id || item?.label || String(item));
        if (s && s.length < 30 && !seen.has(s)) {
          matchedKeywords.push(s);
          seen.add(s);
        }
      }
    }
    const facets = parsedIntent.theme_facets || [];
    for (const f of facets) {
      const id = typeof f === 'string' ? f : f?.id;
      if (id && !seen.has(id)) { matchedKeywords.push(id); seen.add(id); }
    }
  }

  // Theme facet IDs
  const themeFacets: string[] = [];
  if (parsedIntent?.theme_facets) {
    for (const f of parsedIntent.theme_facets) {
      const id = typeof f === 'string' ? f : f?.id;
      if (id) themeFacets.push(id);
    }
  }

  // Preference tags from user profile
  const preferenceTags: string[] = [];
  if (user) {
    (user.preferences || []).forEach((id: string) => {
      const label = PREF_ID_TO_LABEL[id];
      if (label) preferenceTags.push(label);
    });
    (user.activity_pref_tag || []).forEach((tag: string) => {
      const label = ACTIVITY_TAG_TO_LABEL[tag];
      if (label) preferenceTags.push(label);
    });
    (user.food_preferences || []).forEach((fp: string) => { preferenceTags.push(fp); });
  }

  return {
    matchedKeywords: [...new Set(matchedKeywords)].slice(0, 12),
    preferenceTags: [...new Set(preferenceTags)].slice(0, 8),
    themeFacets,
    rawText,
  };
}

/**
 * Per-POI tag generation — filters routeTagContext tags based on POI evidence.
 */
export function getMatchedPoiTags(
  poi: any,
  context: { routeTagContext?: RouteTagContext; parsedIntent?: any },
): string[] {
  const tags: string[] = [];
  const ctx = context.routeTagContext;
  if (!ctx) return tags;

  const poiCorpus = [
    poi.name || '',
    poi.category || '',
    poi.kind || '',
    poi.typecode || '',
    poi.address || '',
    poi.recommend_reason || '',
    poi.parent_anchor || '',
    poi.sub_anchor_name || '',
    poi.route_phase || '',
    poi.activity_facet || '',
    poi.display_slot || '',
    poi.time_slot || '',
    poi.best_visit_time || '',
    ...(poi.matched_facets || []),
    ...(poi.matched_keywords || []),
  ].filter(Boolean).join(' ').toLowerCase();

  const typecode = (poi.typecode || '').toString();
  const facets: string[] = poi.matched_facets || [];
  const isMeal = typecode.startsWith('05') || poi.kind === 'meal' || poi.kind === 'restaurant';
  const isCafe = facets.includes('cafe_stop') || poiCorpus.includes('咖啡') || typecode.startsWith('0504');
  const isShop = facets.includes('specialty_shop') || poiCorpus.includes('特色小店') || poiCorpus.includes('买手店') || poiCorpus.includes('文创');
  const isArt = facets.includes('art_culture_lifestyle') || ctx.themeFacets.includes('art_culture_lifestyle');
  const isRelaxed = ctx.themeFacets.includes('relaxed_pace');

  // v28: Art-visual POI — parks, plazas, art zones, galleries, creative parks, scenic anchors
  const isArtVisualPoi =
    facets.includes('art_culture_lifestyle') ||
    ['scenic', 'anchor_internal', 'park', 'plaza'].includes(poi.kind || '') ||
    typecode.startsWith('11') ||
    typecode.startsWith('14') ||
    poiCorpus.includes('公园') ||
    poiCorpus.includes('广场') ||
    poiCorpus.includes('艺术区') ||
    poiCorpus.includes('艺术馆') ||
    poiCorpus.includes('画廊') ||
    poiCorpus.includes('美术馆') ||
    poiCorpus.includes('创意园') ||
    poiCorpus.includes('文创') ||
    poiCorpus.includes('街区');

  // 1. matched_facets — highest priority
  if (facets.includes('cafe_stop')) { tags.push('咖啡', '咖啡馆'); }
  if (facets.includes('specialty_shop')) tags.push('特色小店');
  if (facets.includes('photo_checkin')) tags.push('拍照');
  if (facets.includes('art_culture_lifestyle')) tags.push('文艺路线');
  if (facets.includes('relaxed_pace')) tags.push('节奏轻松');

  // 2. Keyword-based: 拍照 → art-visual POIs + cafes + shops
  const hasPhotoKw = ctx.matchedKeywords.some(k => k === '拍照' || k === '适合拍照') || ctx.rawText.includes('拍照');
  if (hasPhotoKw && (isArtVisualPoi || isCafe || isShop)) tags.push('拍照');

  // 3. Keyword-based: 文艺路线 → art-visual POIs
  const hasArtKw = ctx.matchedKeywords.some(k => k === '文艺路线' || k === '文艺') || isArt;
  if (hasArtKw && isArtVisualPoi) tags.push('文艺路线');

  // 4. Keyword-based: 轻松/节奏轻松 → scenic/main-route POIs
  const hasRelaxedKw = ctx.matchedKeywords.some(k => k === '轻松' || k === '节奏轻松') || isRelaxed;
  if (hasRelaxedKw && (isArtVisualPoi || isCafe || isShop)) tags.push('轻松');

  // v28: River stroll + night view POI detection
  const isRiverPoi =
    facets.includes('river_stroll') ||
    poi.route_phase === 'river_stroll' ||
    poi.activity_facet === 'waterfront_walk' ||
    ['河边', '河畔', '滨水', '水岸', '沿江', '江边', '滨江', '码头', '亲水', '亮马河', '通惠河', '护城河', '桥'].some(k => poiCorpus.includes(k));

  const isNightViewPoi =
    facets.includes('night_view') ||
    poi.route_phase === 'night_view' ||
    poi.activity_facet === 'night_view' ||
    ['evening', 'night'].includes(String(poi.display_slot || poi.time_slot || '').toLowerCase()) ||
    ['夜景', '拍夜景', '夜游', '灯光', '灯光秀', '观景台', '观景平台', '天际线', '夜色'].some(k => poiCorpus.includes(k));

  const hasRiverKw = ctx.matchedKeywords.some(k => ['河边散步', '河边', '散步', '走走'].includes(k)) || ctx.rawText.includes('河边');
  const hasNightKw = ctx.matchedKeywords.some(k => ['夜景', '拍夜景'].includes(k)) || ctx.rawText.includes('夜景');

  if (hasRiverKw && isRiverPoi) tags.push('河边散步');
  if (hasNightKw && isNightViewPoi) tags.push('夜景');

  // 5. Keyword-based: 咖啡/咖啡馆 → only cafes
  if (ctx.matchedKeywords.some(k => k === '咖啡' || k === '咖啡馆')) {
    if (isCafe) tags.push('咖啡', '咖啡馆');
  }
  // 特色小店 → only shops
  if (ctx.matchedKeywords.some(k => k === '特色小店')) {
    if (isShop) tags.push('特色小店');
  }

  // 6. Preference tags with POI evidence
  for (const pref of ctx.preferenceTags) {
    if (pref === '美食探店') {
      if (isMeal) tags.push('美食探店');
    } else if (pref === '咖啡') {
      if (isCafe) tags.push('咖啡');
    } else if (pref === '艺术展览') {
      if (isArt || poiCorpus.includes('艺术') || poiCorpus.includes('画廊') || poiCorpus.includes('美术馆')) tags.push('艺术展览');
    } else if (pref === '拍照打卡') {
      if (isArtVisualPoi || isCafe) tags.push('拍照打卡');
    } else if (poiCorpus.includes(pref)) {
      tags.push(pref);
    }
  }

  // v28: Planned route explicit target tags — match by parent_anchor/sub_anchor_name/route_phase
  const parentText = [
    poi.parent_anchor || '',
    poi.sub_anchor_name || '',
    poi.route_phase || '',
    ...(poi.matched_keywords || []),
  ].join(' ').toLowerCase();

  const explicitTargets: [string, string[]][] = [
    ['北海公园', ['北海公园', '北海']],
    ['三里河公园', ['三里河公园', '三里河']],
    ['景山公园', ['景山公园', '景山']],
    ['天安门', ['天安门']],
    ['故宫', ['故宫']],
    ['烤鸭', ['烤鸭']],
    ['北京菜', ['北京菜', '地道北京菜', '京菜', '老北京菜']],
    ['看日落', ['日落', '看日落', '夕阳', '晚霞']],
  ];

  for (const [label, patterns] of explicitTargets) {
    if (parentText.includes(patterns[0]) || poiCorpus.split(' ').some(w => patterns.includes(w))) {
      tags.unshift(label);
    }
  }

  // Dedupe preserving order
  return [...new Set(tags)].slice(0, 8);
}
