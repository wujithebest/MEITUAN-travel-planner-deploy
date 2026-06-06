import axios from 'axios';

// 高德地图 API Key（从环境变量获取，使用 VITE_GAODE_JSAPI_KEY）
const GAODE_KEY = import.meta.env.VITE_GAODE_JSAPI_KEY;

// 高德地图 API 基础 URL
const GAODE_BASE_URL = 'https://restapi.amap.com/v3';

/**
 * POI 搜索结果
 */
export interface GaodePOI {
  id: string;
  name: string;
  type: string;
  address: string;
  location: string; // "lng,lat"
  cityname: string;
  adname: string;
  tel?: string;
  rating?: number;
}

/**
 * 高德 /v3/place/text API 响应
 */
interface GaodeTextSearchResponse {
  status: string;
  info: string;
  count: string;
  suggestion?: {
    keywords: string[];
    cities: { name: string; adcode: string }[];
  };
  pois: GaodePOI[];
}

/**
 * 搜索 POI
 * @param keywords 搜索关键词
 * @param city 城市名称或城市编码
 * @param pageSize 每页结果数
 */
export async function searchPOI(
  keywords: string,
  city: string = '全国',
  pageSize: number = 10
): Promise<GaodePOI[]> {
  try {
    const response = await axios.get<GaodeTextSearchResponse>(
      `${GAODE_BASE_URL}/place/text`,
      {
        params: {
          key: GAODE_KEY,
          keywords,
          city,
          pageSize,
          page: 1,
          extensions: 'all', // 返回详细信息
          output: 'JSON',
        },
      }
    );

    if (response.data.status === '1') {
      return response.data.pois || [];
    } else {
      console.error('[Gaode API] 搜索失败:', response.data.info);
      return [];
    }
  } catch (error) {
    console.error('[Gaode API] 请求错误:', error);
    return [];
  }
}

/**
 * 从 location 字符串解析经纬度
 * @param location "lng,lat"
 */
export function parseLocation(location: string): { lng: number; lat: number } | null {
  if (!location) return null;
  const [lng, lat] = location.split(',').map(Number);
  if (isNaN(lng) || isNaN(lat)) return null;
  return { lng, lat };
}
