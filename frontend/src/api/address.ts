import axios from 'axios';

const client = axios.create({ baseURL: '/api' });

export interface DistrictNode {
  name: string;
  adcode: string;
  level: string;
  children?: DistrictNode[];
}

export interface AddressSearchResult {
  name: string;
  address: string;
  location: { lng: number; lat: number } | null;
  district: string;
}

export interface ReverseGeocodeResult {
  province: string;
  city: string;
  district: string;
  address: string;
  lng: number;
  lat: number;
}

export const addressApi = {
  getDistricts: async (keywords: string = '中国', subdistrict: number = 1): Promise<DistrictNode[]> => {
    const { data } = await client.get('/address/districts', { params: { keywords, subdistrict } });
    return data.data || [];
  },

  searchAddress: async (keyword: string, city?: string): Promise<AddressSearchResult[]> => {
    const { data } = await client.get('/address/search', { params: { keyword, city } });
    return data.data || [];
  },

  reverseGeocode: async (lng: number, lat: number): Promise<ReverseGeocodeResult | null> => {
    const { data } = await client.get('/address/reverse-geocode', { params: { lng, lat } });
    return data.data || null;
  },
};

export default addressApi;
