/**
 * 示例数据 - 北京一日游
 * 用于界面展示和调试
 */

import type {
  POI,
  EnroutePOI,
  DailyRoute,
  RouteSummary,
  WeatherInfo,
  TrafficSegment,
  LocationInput,
} from '@/api/types';

// ============================================
// POI 数据
// ============================================

/** 故宫 */
export const forbiddenCityPOI: POI = {
  id: 'poi_001',
  name: '故宫博物院',
  address: '北京市东城区景山前街4号',
  location: '116.397428,39.918058',
  city: '北京',
  district: '东城区',
  type: '历史文化',
  rating: 4.9,
  open_time: '08:30',
  close_time: '17:00',
  ambiguity: false,
  duration_minutes: 180,
  metro_hint: '地铁1号线天安门东站',
  photos: [
    { title: '午门', url: 'https://example.com/photos/wumen.jpg' },
    { title: '太和殿', url: 'https://example.com/photos/taihedian.jpg' },
  ],
  price: '60',
  tel: '010-85007421',
  website: 'https://www.dpm.org.cn',
  biz_type: '景点',
  tag: ['世界文化遗产', '5A级景区', '皇家建筑', '博物馆'],
  indoor: false,
  navi_poiid: 'nav_001',
  entr_location: '116.397428,39.918058',
  exit_location: '116.391234,39.916789',
  groupbuynum: 156,
  discountnum: 23,
  event: '特展：紫禁城六百年',
  children: [
    {
      id: 'child_001',
      name: '故宫文创旗舰店',
      location: '116.397428,39.918058',
      address: '故宫博物院内',
      type: '文创商店',
      rating: 4.7,
    },
  ],
};

/** 八达岭长城 */
export const greatWallPOI: POI = {
  id: 'poi_002',
  name: '八达岭长城',
  address: '北京市延庆区八达岭镇',
  location: '116.016693,40.356038',
  city: '北京',
  district: '延庆区',
  type: '历史文化',
  rating: 4.8,
  open_time: '06:30',
  close_time: '19:00',
  ambiguity: false,
  duration_minutes: 240,
  metro_hint: 'S2线八达岭站',
  photos: [
    { title: '北八楼', url: 'https://example.com/photos/beibalou.jpg' },
    { title: '好汉坡', url: 'https://example.com/photos/haohanpo.jpg' },
  ],
  price: '40',
  tel: '010-69121383',
  website: 'https://www.badaling.cn',
  biz_type: '景点',
  tag: ['世界文化遗产', '5A级景区', '万里长城', '登山'],
  indoor: false,
  navi_poiid: 'nav_002',
  entr_location: '116.016693,40.356038',
  exit_location: '116.020123,40.358456',
  groupbuynum: 89,
  discountnum: 12,
  event: '夜游长城活动',
  children: [],
};

/** 三里屯 */
export const sanlitunPOI: POI = {
  id: 'poi_003',
  name: '三里屯太古里',
  address: '北京市朝阳区三里屯路19号',
  location: '116.455105,39.936485',
  city: '北京',
  district: '朝阳区',
  type: '购物娱乐',
  rating: 4.6,
  open_time: '10:00',
  close_time: '22:00',
  ambiguity: false,
  duration_minutes: 120,
  metro_hint: '地铁10号线团结湖站',
  photos: [
    { title: '南区和北区', url: 'https://example.com/photos/sanlitun.jpg' },
    { title: '太古里夜景', url: 'https://example.com/photos/night.jpg' },
  ],
  price: '免费',
  tel: '010-64173333',
  website: 'https://www.sanlitun.com',
  biz_type: '商圈',
  tag: ['购物', '美食', '夜生活', '时尚'],
  indoor: true,
  navi_poiid: 'nav_003',
  entr_location: '116.455105,39.936485',
  exit_location: '116.458234,39.934567',
  groupbuynum: 234,
  discountnum: 56,
  event: '周年庆活动',
  children: [
    {
      id: 'child_002',
      name: 'Apple Store',
      location: '116.455105,39.936485',
      address: '三里屯太古里南区',
      type: '数码',
      rating: 4.8,
    },
    {
      id: 'child_003',
      name: '% Arabica',
      location: '116.456789,39.937012',
      address: '三里屯太古里北区',
      type: '咖啡厅',
      rating: 4.5,
    },
  ],
};

/** 全聚德烤鸭店（沿途POI） */
export const quanjudeEnroute: EnroutePOI = {
  ...forbiddenCityPOI,
  id: 'enroute_001',
  name: '全聚德烤鸭店（前门店）',
  address: '北京市西城区前门大街30号',
  location: '116.395645,39.901234',
  city: '北京',
  district: '西城区',
  type: '美食',
  rating: 4.5,
  open_time: '11:00',
  close_time: '21:00',
  ambiguity: false,
  duration_minutes: 90,
  metro_hint: '地铁2号线前门站',
  photos: [{ title: '烤鸭', url: 'https://example.com/photos/kaoya.jpg' }],
  price: '人均200',
  tel: '010-67026262',
  tag: ['老字号', '烤鸭', '北京特色'],
  indoor: true,
  children: [],
  distance_from_route: 500,
  reviews: [
    {
      id: 'review_001',
      user_id: 'user_001',
      username: '美食家小王',
      content: '烤鸭皮脆肉嫩，服务态度很好，值得推荐！',
      rating: 5,
      created_at: '2024-01-15T12:00:00Z',
      helpful_count: 128,
    },
    {
      id: 'review_002',
      user_id: 'user_002',
      username: '旅行达人',
      content: '环境不错，就是排队时间有点长。',
      rating: 4,
      created_at: '2024-01-10T18:30:00Z',
      helpful_count: 56,
    },
  ],
  insert_after_index: 1,
  discovery_reason: '热门老字号餐厅，距路线仅500米',
  poi_type: 'enroute',
};

/** 南锣鼓巷（沿途POI） */
export const nanluoguxiangEnroute: EnroutePOI = {
  ...forbiddenCityPOI,
  id: 'enroute_002',
  name: '南锣鼓巷',
  address: '北京市东城区南锣鼓巷',
  location: '116.403874,39.937191',
  city: '北京',
  district: '东城区',
  type: '文化街区',
  rating: 4.4,
  open_time: '全天',
  close_time: '22:00',
  ambiguity: false,
  duration_minutes: 60,
  metro_hint: '地铁6号线南锣鼓巷站',
  photos: [{ title: '胡同', url: 'https://example.com/photos/hutong.jpg' }],
  price: '免费',
  tag: ['胡同文化', '文艺小店', '小吃'],
  indoor: false,
  children: [],
  distance_from_route: 800,
  reviews: [
    {
      id: 'review_003',
      user_id: 'user_003',
      username: '文艺青年',
      content: '很有老北京特色，小店很多，适合拍照。',
      rating: 4,
      created_at: '2024-01-12T15:00:00Z',
      helpful_count: 89,
    },
  ],
  insert_after_index: 2,
  discovery_reason: '特色胡同街区，文艺气息浓厚',
  poi_type: 'enroute',
};

// ============================================
// 路线 Polyline（简化坐标）
// ============================================

/** 故宫 -> 全聚德 -> 南锣鼓巷 -> 三里屯 的简化 polyline */
export const beijingPolyline =
  '116.397428,39.918058;116.397500,39.917500;116.397800,39.916000;' +
  '116.398000,39.914500;116.397500,39.912000;116.396500,39.908000;' +
  '116.395645,39.901234;116.396000,39.905000;116.398000,39.915000;' +
  '116.400000,39.925000;116.403874,39.937191;116.410000,39.940000;' +
  '116.420000,39.942000;116.430000,39.940000;116.440000,39.938000;' +
  '116.450000,39.937000;116.455105,39.936485';

// ============================================
// 天气数据
// ============================================

export const beijingWeather: WeatherInfo = {
  forecast_date: '2024-03-15',
  city: '北京',
  text_day: '晴',
  text_night: '多云',
  temp_high: 18,
  temp_low: 5,
  wind_level: 3,
  wind_direction: '西北风',
  humidity: 35,
  rain_probability: 10,
  is_rainy: false,
  is_high_temp: false,
  is_strong_wind: false,
  indoor_recommended: false,
  weather_tip: '天气晴朗，适合出游，建议穿轻薄外套。',
};

// ============================================
// 交通数据
// ============================================

export const trafficSegments: TrafficSegment[] = [
  {
    start_index: 0,
    end_index: 5,
    status: 'smooth',
    road_name: '景山前街',
  },
  {
    start_index: 5,
    end_index: 10,
    status: 'slow',
    road_name: '前门大街',
  },
  {
    start_index: 10,
    end_index: 18,
    status: 'congested',
    road_name: '朝阳门外大街',
  },
];

// ============================================
// 完整路线数据
// ============================================

export const mockDailyRoute: DailyRoute = {
  day: 1,
  date: '2024-03-15',
  points: [
    {
      poi: forbiddenCityPOI,
      poi_type: 'main',
      arrival_time: '09:00',
      departure_time: '12:00',
      stay_minutes: 180,
      transport_from_prev: '步行',
      distance_from_prev: 0,
      duration_from_prev: 0,
      polyline: beijingPolyline,
      polyline_coords: [
        [116.397428, 39.918058],
        [116.395645, 39.901234],
        [116.403874, 39.937191],
        [116.455105, 39.936485],
      ],
      steps: ['从酒店出发', '步行至故宫', '游览故宫'],
      weather: beijingWeather,
      note: '建议提前预约门票',
      enroute_info: undefined,
    },
    {
      poi: quanjudeEnroute,
      poi_type: 'enroute',
      arrival_time: '12:30',
      departure_time: '14:00',
      stay_minutes: 90,
      transport_from_prev: '步行约10分钟',
      distance_from_prev: 500,
      duration_from_prev: 10,
      polyline: '116.397428,39.918058;116.395645,39.901234',
      polyline_coords: [
        [116.397428, 39.918058],
        [116.395645, 39.901234],
      ],
      steps: ['从故宫步行至全聚德'],
      weather: beijingWeather,
      note: '建议提前预约',
      enroute_info: {
        insert_after_index: 1,
        discovery_reason: '热门老字号餐厅，距路线仅500米',
        distance_from_route: 500,
      },
    },
    {
      poi: nanluoguxiangEnroute,
      poi_type: 'enroute',
      arrival_time: '14:30',
      departure_time: '15:30',
      stay_minutes: 60,
      transport_from_prev: '打车约15分钟',
      distance_from_prev: 800,
      duration_from_prev: 15,
      polyline: '116.395645,39.901234;116.403874,39.937191',
      polyline_coords: [
        [116.395645, 39.901234],
        [116.403874, 39.937191],
      ],
      steps: ['从全聚德打车至南锣鼓巷'],
      weather: beijingWeather,
      note: '适合拍照打卡',
      enroute_info: {
        insert_after_index: 2,
        discovery_reason: '特色胡同街区，文艺气息浓厚',
        distance_from_route: 800,
      },
    },
    {
      poi: sanlitunPOI,
      poi_type: 'main',
      arrival_time: '16:00',
      departure_time: '18:00',
      stay_minutes: 120,
      transport_from_prev: '地铁约20分钟',
      distance_from_prev: 5000,
      duration_from_prev: 20,
      polyline: '116.403874,39.937191;116.455105,39.936485',
      polyline_coords: [
        [116.403874, 39.937191],
        [116.455105, 39.936485],
      ],
      steps: ['从南锣鼓巷乘地铁至三里屯'],
      weather: beijingWeather,
      note: '可以购物和晚餐',
      enroute_info: undefined,
    },
  ],
  pois: [forbiddenCityPOI, quanjudeEnroute, nanluoguxiangEnroute, sanlitunPOI],
  main_pois: [forbiddenCityPOI, sanlitunPOI],
  enroute_pois: [quanjudeEnroute, nanluoguxiangEnroute],
  total_distance: 6300,
  total_duration: 540,
  total_transport_duration: 45,
  enroute_extra_duration: 30,
  weather_tip: '天气晴朗，适合出游',
  smoothness_score: 85,
  polyline: beijingPolyline,
  traffic_segments: trafficSegments,
};

export const mockRouteSummary: RouteSummary = {
  total_days: 1,
  total_distance: 6300,
  total_duration: 540,
  total_pois: 4,
  main_pois_count: 2,
  enroute_pois_count: 2,
  enroute_extra_duration: 30,
  plan_count: 1,
  transportation: '步行+地铁+打车',
  route_quality: 'excellent',
};

// ============================================
// 初始输入数据
// ============================================

export const mockLocationInput: LocationInput = {
  text: '北京一日游',
  plan_mode: 'intent',
  transport_mode: 'driving',
  start_date: '2024-03-15',
  days: 1,
  consider_weather: true,
};

// ============================================
// 完整的 mock 数据集合
// ============================================

export const mockRouteData = {
  routeId: 'route_mock_001',
  dailyRoutes: [mockDailyRoute],
  summary: mockRouteSummary,
  pois: [forbiddenCityPOI, sanlitunPOI],
  mainPOIs: [forbiddenCityPOI, sanlitunPOI],
  enroutePOIs: [quanjudeEnroute, nanluoguxiangEnroute],
  weatherData: {
    '2024-03-15': beijingWeather,
  },
  trafficSegments,
  overallTraffic: 'slow' as const,
  mapConfig: {
    center: [116.4074, 39.9042] as [number, number],
    zoom: 12,
    showTraffic: true,
    showWeather: true,
  },
};

// ============================================
// 辅助函数
// ============================================

/**
 * 初始化 mock 数据到 store
 */
export function initializeMockData(store: {
  setRoute: (routeId: string, dailyRoutes: DailyRoute[], summary: RouteSummary) => void;
  setMainPOIs: (pois: POI[]) => void;
  setEnroutePOIs: (pois: EnroutePOI[]) => void;
  setTrafficSegments: (segments: TrafficSegment[]) => void;
  setOverallTraffic: (status: 'smooth' | 'slow' | 'congested' | 'blocked') => void;
  setWeather: (date: string, weather: WeatherInfo) => void;
  setMapConfig: (config: Partial<{ center: [number, number]; zoom: number; showTraffic: boolean; showWeather: boolean }>) => void;
  setPlanMode: (mode: 'precise' | 'intent' | null) => void;
  setRecommendedReason: (reason: string | null) => void;
}) {
  store.setRoute(mockRouteData.routeId, mockRouteData.dailyRoutes, mockRouteData.summary);
  store.setMainPOIs(mockRouteData.mainPOIs);
  store.setEnroutePOIs(mockRouteData.enroutePOIs);
  store.setTrafficSegments(mockRouteData.trafficSegments);
  store.setOverallTraffic(mockRouteData.overallTraffic);
  store.setWeather('2024-03-15', beijingWeather);
  store.setMapConfig(mockRouteData.mapConfig);
  store.setPlanMode('intent');
  store.setRecommendedReason('根据您的偏好推荐：历史文化与现代都市完美结合');
}
