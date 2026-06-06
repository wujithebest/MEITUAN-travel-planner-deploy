// ============================================
// Mock 路线数据 - 上海外滩夜景美食游
// 用于开发和测试，当 VITE_USE_MOCK=true 时使用
// ============================================

import type { LocationInput, RouteResponse, POI, DailyRoute, WeatherInfo } from './types';

// 上海外滩默认POI数据
const SHANGHAI_BUND_POIS: POI[] = [
  {
    id: 'poi_001',
    name: '外滩观景台',
    location: '121.4906,31.2397',
    address: '中山东一路',
    poi_type: 'main',
    category: '景点',
    rating: 4.9,
    open_time: '全天',
    suggested_duration: 120,
    best_visit_time: '夜间',
    description: '百年建筑博览群，上海地标',
    photos: [],
    tags: ['夜景', '拍照', '历史建筑'],
  },
  {
    id: 'poi_002',
    name: '东方明珠广播电视塔',
    location: '121.4998,31.2397',
    address: '世纪大道1号',
    poi_type: 'main',
    category: '景点',
    rating: 4.7,
    open_time: '08:00-21:30',
    suggested_duration: 180,
    best_visit_time: '白天',
    description: '468米高空俯瞰上海',
    photos: [],
    tags: ['地标', '观光', '城市全景'],
  },
  {
    id: 'poi_003',
    name: '外白渡桥',
    location: '121.4880,31.2420',
    address: '北苏州路111号',
    poi_type: 'main',
    category: '景点',
    rating: 4.6,
    open_time: '全天',
    suggested_duration: 30,
    best_visit_time: '傍晚',
    description: '百年铁桥，情深深雨濛濛取景地',
    photos: [],
    tags: ['历史', '拍照', '江景'],
  },
  {
    id: 'poi_004',
    name: '老正兴菜馆',
    location: '121.4856,31.2356',
    address: '福州路556号',
    poi_type: 'main',
    category: '餐饮',
    rating: 4.5,
    open_time: '11:00-14:00, 17:00-21:00',
    suggested_duration: 90,
    best_visit_time: '晚餐',
    description: '百年本帮菜老字号，人均98元',
    price: 98,
    photos: [],
    tags: ['本帮菜', '老字号', '美食'],
  },
  {
    id: 'poi_005',
    name: '南京路步行街',
    location: '121.4750,31.2350',
    address: '南京东路',
    poi_type: 'main',
    category: '购物',
    rating: 4.4,
    open_time: '全天',
    suggested_duration: 60,
    best_visit_time: '晚上',
    description: '中华商业第一街',
    photos: [],
    tags: ['购物', '美食', '商业街'],
  },
];

// 默认天气数据
const DEFAULT_WEATHER: WeatherInfo = {
  temp_high: 26,
  temp_low: 19,
  condition: '晴',
  rain_probability: 0,
  aqi: 45,
  suggestion: '天气晴朗，适合夜游',
};

/**
 * 生成上海外滩Mock路线数据
 */
function generateShanghaiBundRoute(input: LocationInput): RouteResponse {
  const query = input.text || '';

  // 根据用户输入选择相关POI
  let selectedPois = [...SHANGHAI_BUND_POIS];

  // 关键词匹配，调整POI顺序
  if (query.includes('夜景') || query.includes('拍照')) {
    // 夜景优先：外滩观景台排第一
    selectedPois = [
      SHANGHAI_BUND_POIS[0], // 外滩观景台
      SHANGHAI_BUND_POIS[2], // 外白渡桥
      SHANGHAI_BUND_POIS[3], // 老正兴菜馆
      SHANGHAI_BUND_POIS[1], // 东方明珠
      SHANGHAI_BUND_POIS[4], // 南京路
    ];
  } else if (query.includes('本帮菜') || query.includes('美食')) {
    // 美食优先：老正兴排前面
    selectedPois = [
      SHANGHAI_BUND_POIS[3], // 老正兴菜馆
      SHANGHAI_BUND_POIS[0], // 外滩观景台
      SHANGHAI_BUND_POIS[2], // 外白渡桥
      SHANGHAI_BUND_POIS[4], // 南京路
      SHANGHAI_BUND_POIS[1], // 东方明珠
    ];
  }

  // 构建每日路线
  const dailyRoute: DailyRoute = {
    day: 1,
    day_index: 0,
    date: input.start_date || '2026-06-01',
    points: [
      {
        poi: selectedPois[1], // 东方明珠
        arrival_time: '14:00',
        departure_time: '17:00',
        transport_from_prev: { mode: '地铁', duration: 30, distance: 8000 },
      },
      {
        poi: selectedPois[2], // 外白渡桥
        arrival_time: '17:30',
        departure_time: '18:00',
        transport_from_prev: { mode: '步行', duration: 10, distance: 800 },
      },
      {
        poi: selectedPois[3], // 老正兴菜馆
        arrival_time: '18:30',
        departure_time: '20:00',
        transport_from_prev: { mode: '步行', duration: 5, distance: 300 },
      },
      {
        poi: selectedPois[0], // 外滩观景台
        arrival_time: '20:30',
        departure_time: '22:00',
        transport_from_prev: { mode: '步行', duration: 8, distance: 500 },
      },
      {
        poi: selectedPois[4], // 南京路步行街
        arrival_time: '22:15',
        departure_time: '23:00',
        transport_from_prev: { mode: '步行', duration: 10, distance: 600 },
      },
    ],
    pois: selectedPois,
    polyline: '121.4737,31.2304;121.4998,31.2397;121.4880,31.2420;121.4856,31.2356;121.4906,31.2397;121.4750,31.2350',
    distance: 10200,
    duration: 540,
    total_distance: 10200,
    total_duration: 540,
    weather: DEFAULT_WEATHER,
  };

  // 构建路线响应
  const response: RouteResponse = {
    success: true,
    message: '路线生成成功',
    intent: {
      area: '外滩',
      days: 1,
      keywords: extractKeywords(query),
      plan_mode: 'exploratory',
    },
    main_pois: selectedPois,
    enroute_pois: [],
    daily_routes: [dailyRoute],
    summary: {
      total_distance: 10200,
      total_duration: 540,
      total_pois: selectedPois.length,
      main_pois: selectedPois.length,
      enroute_pois: 0,
      days: 1,
    },
    map_config: {
      center: '121.4906,31.2397',
      zoom: 13,
      markers: selectedPois.map((poi, index) => ({
        id: poi.id,
        name: poi.name,
        location: poi.location,
        type: 'main',
        day: 0,
      })),
      daily_polylines: [
        {
          day: 0,
          polyline: dailyRoute.polyline || '',
          color: '#1677ff',
        },
      ],
    },
    weather: [DEFAULT_WEATHER],
    reviews: [],
  };

  return response;
}

/**
 * 从用户输入中提取关键词
 */
function extractKeywords(query: string): string[] {
  const keywords: string[] = [];
  const keywordMap: Record<string, string[]> = {
    '夜景': ['夜景', '拍照', '灯光'],
    '本帮菜': ['本帮菜', '美食', '餐厅'],
    '外滩': ['外滩', '黄浦江', '建筑群'],
    '东方明珠': ['东方明珠', '地标', '观光'],
  };

  for (const [key, values] of Object.entries(keywordMap)) {
    if (query.includes(key)) {
      keywords.push(...values);
    }
  }

  return [...new Set(keywords)].slice(0, 5);
}

/**
 * 模拟路线生成（带延迟）
 * 用于开发测试，模拟网络请求延迟
 */
export async function mockGenerateRoute(input: LocationInput): Promise<RouteResponse> {
  console.log('[MockRoute] 使用Mock数据生成路线', { query: input.text });

  // 模拟网络延迟 1-3秒
  const delay = 1000 + Math.random() * 2000;
  await new Promise(resolve => setTimeout(resolve, delay));

  const response = generateShanghaiBundRoute(input);

  console.log('[MockRoute] Mock路线生成成功', {
    daily_routes: response.daily_routes.length,
    total_pois: response.summary.total_pois,
  });

  return response;
}

/**
 * 检查是否应该使用Mock数据
 */
export function shouldUseMock(): boolean {
  return import.meta.env.VITE_USE_MOCK === 'true';
}
