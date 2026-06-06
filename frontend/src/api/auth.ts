import { message } from 'antd';
import client from './client';

interface LoginResponse {
  token: string;
  user: {
    id: string;
    username: string;
    email: string;
    avatar?: string;
    gender?: string;
    birthday?: string;
    preferences?: string[];
    location?: Record<string, unknown>;
  };
}

interface RegisterData {
  username: string;
  email: string;
  password: string;
  gender?: string;
  birthday?: string;
  preferences?: string[];
  location?: Record<string, unknown>;
}

const getAuthHeaders = () => {
  const token = localStorage.getItem('token');
  return token ? { Authorization: `Bearer ${token}` } : {};
};

export const authApi = {
  login: async (email: string, password: string): Promise<{ data: LoginResponse }> => {
    try {
      const response = await client.post('/auth/login', {
        email,
        password,
      });
      return response;
    } catch (error: any) {
      const errorMsg = error.response?.data?.detail || '登录失败，请检查邮箱和密码';
      message.error(errorMsg);
      throw error;
    }
  },

  register: async (data: RegisterData): Promise<{ data: LoginResponse }> => {
    try {
      const response = await client.post('/auth/register', data);
      return response;
    } catch (error: any) {
      const errorMsg = error.response?.data?.detail || '注册失败，请稍后重试';
      message.error(errorMsg);
      throw error;
    }
  },

  getMe: async () => {
    try {
      const response = await client.get('/auth/me', {
        headers: getAuthHeaders(),
      });
      return response;
    } catch (error: any) {
      const errorMsg = error.response?.data?.detail || '获取用户信息失败';
      message.error(errorMsg);
      throw error;
    }
  },

  updatePrefs: async (prefs: string[]) => {
    try {
      const response = await client.put(
        '/auth/preferences',
        { preferences: prefs },
        { headers: getAuthHeaders() }
      );
      return response;
    } catch (error: any) {
      const errorMsg = error.response?.data?.detail || '更新偏好失败';
      message.error(errorMsg);
      throw error;
    }
  },

  forgotPassword: async (email: string) => {
    try {
      const response = await client.post('/auth/forgot-password', {
        email,
      });
      message.success('重置密码链接已发送到您的邮箱');
      return response;
    } catch (error: any) {
      const errorMsg = error.response?.data?.detail || '发送失败，请稍后重试';
      message.error(errorMsg);
      throw error;
    }
  },
};

export default authApi;
