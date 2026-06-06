import axios from 'axios';
import { message } from 'antd';

const client = axios.create({
  baseURL: '/api',
});

const getAuthHeaders = () => {
  const token = localStorage.getItem('token');
  return token ? { Authorization: `Bearer ${token}` } : {};
};

export interface UpdateProfileData {
  username?: string;
  city?: string;
  preferences?: string[];
}

export interface UserProfile {
  id: string;
  username: string;
  email: string;
  avatar?: string;
  city?: string;
  gender?: string;
  birthday?: string;
  preferences?: string[];
  createdAt?: string;
}

export const userApi = {
  /**
   * 获取当前用户信息
   */
  getProfile: async (): Promise<{ data: UserProfile }> => {
    try {
      const response = await client.get('/user/profile', {
        headers: getAuthHeaders(),
      });
      return response;
    } catch (error: any) {
      const errorMsg = error.response?.data?.detail || '获取用户信息失败';
      message.error(errorMsg);
      throw error;
    }
  },

  /**
   * 更新用户资料
   */
  updateProfile: async (data: UpdateProfileData): Promise<{ data: UserProfile }> => {
    try {
      const response = await client.put('/user/profile', data, {
        headers: getAuthHeaders(),
      });
      return response;
    } catch (error: any) {
      const errorMsg = error.response?.data?.detail || '更新用户资料失败';
      message.error(errorMsg);
      throw error;
    }
  },

  /**
   * 更新用户名
   */
  updateUsername: async (username: string): Promise<{ data: UserProfile }> => {
    try {
      const response = await client.put(
        '/user/username',
        { username },
        { headers: getAuthHeaders() }
      );
      return response;
    } catch (error: any) {
      const errorMsg = error.response?.data?.detail || '更新用户名失败';
      message.error(errorMsg);
      throw error;
    }
  },

  /**
   * 更新常住城市
   */
  updateCity: async (city: string): Promise<{ data: UserProfile }> => {
    try {
      const response = await client.put(
        '/user/city',
        { city },
        { headers: getAuthHeaders() }
      );
      return response;
    } catch (error: any) {
      const errorMsg = error.response?.data?.detail || '更新城市失败';
      message.error(errorMsg);
      throw error;
    }
  },

  /**
   * 更新旅行偏好
   */
  updatePreferences: async (preferences: string[]): Promise<{ data: UserProfile }> => {
    try {
      const response = await client.put(
        '/user/preferences',
        { preferences },
        { headers: getAuthHeaders() }
      );
      return response;
    } catch (error: any) {
      const errorMsg = error.response?.data?.detail || '更新偏好失败';
      message.error(errorMsg);
      throw error;
    }
  },

  /**
   * 记录 POI 交互操作
   */
  recordPoiAction: async (poiName: string, poiType: string, action: string): Promise<void> => {
    try {
      await client.post(
        '/user/preferences/poi-action',
        { poi_name: poiName, poi_type: poiType, action },
        { headers: getAuthHeaders() }
      );
    } catch (error: any) {
      console.warn('[UserAPI] 记录 POI 交互失败:', error.message);
    }
  },

  /**
   * 获取用户收藏列表
   */
  getFavorites: async (): Promise<{ data: any[] }> => {
    try {
      const response = await client.get('/user/favorites', {
        headers: getAuthHeaders(),
      });
      return response;
    } catch (error: any) {
      const errorMsg = error.response?.data?.detail || '获取收藏列表失败';
      message.error(errorMsg);
      throw error;
    }
  },

  /**
   * 创建路线收藏
   */
  createFavorite: async (payload: any): Promise<{ data: any }> => {
    try {
      const response = await client.post('/user/favorites', payload, {
        headers: getAuthHeaders(),
      });
      return response;
    } catch (error: any) {
      const errorMsg = error.response?.data?.detail || '收藏失败';
      message.error(errorMsg);
      throw error;
    }
  },

  /**
   * 删除路线收藏
   */
  deleteFavorite: async (favoriteId: string): Promise<void> => {
    try {
      await client.delete(`/user/favorites/${favoriteId}`, {
        headers: getAuthHeaders(),
      });
    } catch (error: any) {
      const errorMsg = error.response?.data?.detail || '删除收藏失败';
      message.error(errorMsg);
      throw error;
    }
  },

  /**
   * 获取规划历史列表
   */
  getRouteHistories: async (): Promise<{ data: any[] }> => {
    try {
      const response = await client.get('/user/route-histories', {
        headers: getAuthHeaders(),
      });
      return response;
    } catch (error: any) {
      const errorMsg = error.response?.data?.detail || '获取规划历史失败';
      message.error(errorMsg);
      throw error;
    }
  },

  /**
   * 创建规划历史
   */
  createRouteHistory: async (payload: any): Promise<{ data: any }> => {
    try {
      const response = await client.post('/user/route-histories', payload, {
        headers: getAuthHeaders(),
      });
      return response;
    } catch (error: any) {
      const errorMsg = error.response?.data?.detail || '保存规划历史失败';
      message.error(errorMsg);
      throw error;
    }
  },

  /**
   * 删除规划历史
   */
  deleteRouteHistory: async (historyId: string): Promise<void> => {
    try {
      await client.delete(`/user/route-histories/${historyId}`, {
        headers: getAuthHeaders(),
      });
    } catch (error: any) {
      const errorMsg = error.response?.data?.detail || '删除规划历史失败';
      message.error(errorMsg);
      throw error;
    }
  },

  /**
   * 清空规划历史
   */
  clearRouteHistories: async (): Promise<void> => {
    try {
      await client.delete('/user/route-histories', {
        headers: getAuthHeaders(),
      });
    } catch (error: any) {
      const errorMsg = error.response?.data?.detail || '清空规划历史失败';
      message.error(errorMsg);
      throw error;
    }
  },

  /**
   * 获取历史行程列表（旧接口，保留兼容）
   */
  getHistoryTrips: async (): Promise<{ data: any[] }> => {
    try {
      const response = await client.get('/user/trips/history', {
        headers: getAuthHeaders(),
      });
      return response;
    } catch (error: any) {
      const errorMsg = error.response?.data?.detail || '获取历史行程失败';
      message.error(errorMsg);
      throw error;
    }
  },

  /**
   * 修改密码
   */
  changePassword: async (oldPassword: string, newPassword: string): Promise<void> => {
    try {
      await client.put(
        '/user/password',
        { oldPassword, newPassword },
        { headers: getAuthHeaders() }
      );
      message.success('密码修改成功');
    } catch (error: any) {
      const errorMsg = error.response?.data?.detail || '修改密码失败';
      message.error(errorMsg);
      throw error;
    }
  },

  /**
   * 注销账户
   */
  deleteAccount: async (): Promise<void> => {
    try {
      await client.delete('/user/account', {
        headers: getAuthHeaders(),
      });
      message.success('账户已注销');
    } catch (error: any) {
      const errorMsg = error.response?.data?.detail || '注销账户失败';
      message.error(errorMsg);
      throw error;
    }
  },
};

export default userApi;
