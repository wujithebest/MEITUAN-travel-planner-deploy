// ============================================
// Axios HTTP 客户端配置
// ============================================

import axios, { AxiosInstance, AxiosError, InternalAxiosRequestConfig } from 'axios';
import { message } from 'antd';
import { API_CONFIG } from '../config/api.config';

const API_BASE_URL = API_CONFIG.BASE_URL;

// 创建axios实例
const client: AxiosInstance = axios.create({
  baseURL: API_BASE_URL,
  timeout: API_CONFIG.TIMEOUT,
  headers: {
    'Content-Type': 'application/json',
    'Accept': 'application/json',
  },
});

// ============================================
// Token 验证工具函数
// ============================================

/** 验证token格式是否为有效的JWT */
function isValidJWT(token: string): boolean {
  if (!token) return false;
  const parts = token.split('.');
  if (parts.length !== 3) return false;
  
  try {
    parts.forEach(part => {
      atob(part.replace(/-/g, '+').replace(/_/g, '/'));
    });
    return true;
  } catch {
    return false;
  }
}

/** 检查token是否过期 */
function isTokenExpired(token: string): boolean {
  try {
    const parts = token.split('.');
    if (parts.length !== 3) return true;
    
    const payload = JSON.parse(atob(parts[1].replace(/-/g, '+').replace(/_/g, '/')));
    const exp = payload.exp;
    
    if (!exp) return false;
    
    const now = Math.floor(Date.now() / 1000);
    return now > exp;
  } catch {
    return true;
  }
}

// ============================================
// 请求拦截器
// ============================================

client.interceptors.request.use(
  (config: InternalAxiosRequestConfig) => {
    const startTime = Date.now();
    (config as any)._startTime = startTime;

    const token = localStorage.getItem('token');
    
    if (token) {
      // 验证token格式
      if (!isValidJWT(token)) {
        console.error('[API] Token格式错误，清除并跳转登录页');
        localStorage.removeItem('token');
        window.location.href = '/login';
        return Promise.reject(new Error('Token格式错误'));
      }
      
      // 检查token是否过期
      if (isTokenExpired(token)) {
        console.warn('[API] Token已过期，清除并跳转登录页');
        localStorage.removeItem('token');
        window.location.href = '/login';
        return Promise.reject(new Error('Token已过期'));
      }
      
      if (config.headers) {
        config.headers.Authorization = `Bearer ${token}`;
      }
    }

    // 增强请求日志：显示完整URL
    const fullUrl = `${config.baseURL || ''}${config.url || ''}`;
    console.log(`[Request] ${config.method?.toUpperCase()} ${fullUrl}`, {
      url: config.url,
      baseURL: config.baseURL,
      fullUrl: fullUrl,
      params: config.params,
      data: config.data ? JSON.stringify(config.data).substring(0, 200) : undefined,
      token: token ? `${token.substring(0, 20)}...` : 'none',
    });
    
    return config;
  },
  (error) => {
    console.error('[API Request Error]', error);
    return Promise.reject(error);
  }
);

// ============================================
// 响应拦截器
// ============================================

client.interceptors.response.use(
  (response) => {
    const startTime = (response.config as any)._startTime || Date.now();
    const duration = Date.now() - startTime;

    // 增强响应日志：显示完整URL和状态
    const fullUrl = `${response.config.baseURL || ''}${response.config.url || ''}`;
    console.log(`[Response] ${response.status} ${fullUrl}`, {
      status: response.status,
      statusText: response.statusText,
      duration: `${duration}ms`,
      url: response.config.url,
      fullUrl: fullUrl,
      data: JSON.stringify(response.data).substring(0, 300),
    });

    return response;
  },
  (error: AxiosError) => {
    const startTime = (error.config as any)?._startTime || Date.now();
    const duration = Date.now() - startTime;

    const fullUrl = `${error.config?.baseURL || ''}${error.config?.url || ''}`;
    
    console.error(`[Response Error] ${error.response?.status || 'N/A'} ${fullUrl}`, {
      message: error.message,
      code: error.code,
      status: error.response?.status,
      statusText: error.response?.statusText,
      duration: `${duration}ms`,
      url: error.config?.url,
      fullUrl: fullUrl,
      data: error.response?.data,
    });
    
    // 分类错误处理
    if (error.code === 'ECONNABORTED') {
      message.error('请求超时，请检查网络连接');
    } else if (!error.response) {
      // 网络错误或无响应
      if (error.message === 'Network Error' || error.message.includes('Failed to fetch')) {
        message.error('网络连接失败，请检查后端服务是否运行');
      } else {
        message.error('网络连接失败，请检查后端服务是否运行');
      }
    } else {
      const status = error.response.status;
      const data = error.response.data as any;
      
      // 401 未授权 - token过期或无效
      if (status === 401) {
        console.error('[API] 401未授权，清除token并跳转登录页');
        localStorage.removeItem('token');
        
        if (!window.location.pathname.includes('/login')) {
          message.error('登录已过期，请重新登录');
          window.location.href = '/login';
        }
      } else if (status === 404) {
        // 404 错误 - 接口路径错误
        console.error('[API] 404 接口路径错误:', fullUrl);
        const errorMessage = data?.message || data?.detail || '请求的资源不存在';
        message.error(`接口路径错误 (404)：${errorMessage}。实际路径可能与配置不符，请检查后端路由配置。`);
      } else {
        // 使用后端返回的错误信息
        const errorMessage = data?.message || data?.detail || `请求失败 (${status})`;
        message.error(errorMessage);
      }
    }
    
    return Promise.reject(error);
  }
);

export default client;
export { API_BASE_URL };
