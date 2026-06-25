import { create } from 'zustand';
import { persist } from 'zustand/middleware';
import { authApi } from '../api/auth';
import { userApi } from '../api/user';
import { FALLBACK_HOME_ADDRESS, FALLBACK_HOME_LOCATION } from '@/utils/locationDefaults';

export interface HomeAddress {
  name: string;
  full_address: string;
  lng: number | null;
  lat: number | null;
}

export interface UserLocation {
  city?: string;
  district?: string;
  address?: string;
  latitude?: number;
  longitude?: number;
  home_address?: HomeAddress;
}

export interface User {
  id: string;
  username: string;
  email: string;
  avatar?: string;
  city?: string;
  gender?: string;
  birthday?: string;
  preferences?: string[];
  createdAt?: string;
  location?: UserLocation;
  age?: number;
  food_preferences?: string[];
  budget_per_capita?: number;
  activity_pref_tag?: string[];
  /** v6: 常住地址（用于路线规划 home_location），格式 { lat, lng, label } */
  home_location?: { lat: number; lng: number; label: string } | null;
}

export interface RegisterData {
  username: string;
  email: string;
  password: string;
  gender?: string;
  birthday?: string;
  preferences?: string[];
  location?: Record<string, unknown>;
  home_location?: { lat: number; lng: number; label: string } | null;
}

interface UserState {
  user: User | null;
  token: string | null;
  isLoggedIn: boolean;
  isGuest: boolean;
  isLoading: boolean;
  error: string | null;

  login: (email: string, password: string) => Promise<void>;
  register: (data: RegisterData) => Promise<void>;
  logout: () => void;
  guestLogin: () => void;
  /** v18: 幂等保障 — 确保当前是游客会话，补齐缺失字段，不覆盖已有偏好 */
  ensureGuestSession: () => void;
  updateUser: (user: User) => void;
  updatePreferences: (prefs: string[]) => Promise<void>;
  updateGuestProfile: (data: Partial<User>) => void;
  fetchUserProfile: () => Promise<void>;
  clearError: () => void;
}

// 验证 token 格式是否为有效的 JWT
function isValidJWT(token: string): boolean {
  if (!token) return false;
  const parts = token.split('.');
  if (parts.length !== 3) return false;
  
  // 验证每个部分都是有效的 base64
  try {
    parts.forEach(part => {
      // 尝试解码，如果失败则说明格式不正确
      atob(part.replace(/-/g, '+').replace(/_/g, '/'));
    });
    return true;
  } catch {
    return false;
  }
}

// 检查 token 是否过期
function isTokenExpired(token: string): boolean {
  try {
    const parts = token.split('.');
    if (parts.length !== 3) return true;
    
    // 解码 payload
    const payload = JSON.parse(atob(parts[1].replace(/-/g, '+').replace(/_/g, '/')));
    const exp = payload.exp;
    
    if (!exp) return false;
    
    // 检查是否过期（exp 是秒级时间戳）
    const now = Math.floor(Date.now() / 1000);
    return now > exp;
  } catch {
    return true;
  }
}

export const useUserStore = create<UserState>()(
  persist(
    (set, get) => ({
      user: null,
      token: null,
      isLoggedIn: false,
      isGuest: false,
      isLoading: false,
      error: null,

      login: async (email: string, password: string) => {
        set({ isLoading: true, error: null });
        try {
          const response = await authApi.login(email, password);
          const { token, user } = response.data;
          
          // 验证 token 格式
          if (!isValidJWT(token)) {
            console.error('[UserStore] 无效的token格式:', token);
            throw new Error('服务器返回了无效的认证信息');
          }
          
          // 检查 token 是否已过期
          if (isTokenExpired(token)) {
            console.error('[UserStore] Token已过期');
            throw new Error('认证信息已过期，请重新登录');
          }
          
          // 先写 token，getProfile 的 Authorization header 需要从 localStorage 读取
          localStorage.setItem('token', token);

          // 登录成功后，调用API获取完整用户资料
          let fullUser = user;
          try {
            const profileRes = await userApi.getProfile();
            fullUser = profileRes.data;
          } catch (profileError) {
            console.warn('[UserStore] 获取用户资料失败，使用登录返回数据:', profileError);
          }

          set({
            user: fullUser,
            token,
            isLoggedIn: true,
            isGuest: false,
            isLoading: false,
          });
          console.log('[UserStore] 登录成功, token=', token.substring(0, 30) + '...');
        } catch (error: any) {
          const message = error.response?.data?.detail || error.message || '登录失败';
          console.error('[UserStore] 登录失败:', message);
          set({ error: message, isLoading: false });
          throw error;
        }
      },

      register: async (data: RegisterData) => {
        set({ isLoading: true, error: null });
        try {
          const response = await authApi.register(data);
          const { token, user } = response.data;
          
          // 验证 token 格式
          if (!isValidJWT(token)) {
            console.error('[UserStore] 无效的token格式:', token);
            throw new Error('服务器返回了无效的认证信息');
          }
          
          // 检查 token 是否已过期
          if (isTokenExpired(token)) {
            console.error('[UserStore] Token已过期');
            throw new Error('认证信息已过期，请重新登录');
          }
          
          localStorage.setItem('token', token);
          // 注册成功后，调用API获取完整用户资料
          let fullUser = user;
          try {
            const profileRes = await userApi.getProfile();
            fullUser = profileRes.data;
          } catch (profileError) {
            console.warn('[UserStore] 获取用户资料失败，使用注册返回数据:', profileError);
          }
          
          set({
            user: fullUser,
            token,
            isLoggedIn: true,
            isGuest: false,
            isLoading: false,
          });

          console.log('[UserStore] 注册成功, token=', token.substring(0, 30) + '...');
        } catch (error: any) {
          const message = error.response?.data?.detail || error.message || '注册失败';
          console.error('[UserStore] 注册失败:', message);
          set({ error: message, isLoading: false });
          throw error;
        }
      },

      logout: () => {
        localStorage.removeItem('token');
        set({
          user: null,
          token: null,
          isLoggedIn: false,
          isGuest: false,
        });
        console.log('[UserStore] 已登出');
      },

      guestLogin: () => {
        localStorage.removeItem('token');
        set({
          user: {
            id: 'guest',
            username: '游客',
            email: '',
            gender: '男',
            age: 30,
            preferences: ['cultural', 'food'],
            activity_pref_tag: ['文艺', '历史'],
            food_preferences: ['本帮菜', '咖啡'],
            budget_per_capita: 100,
            city: undefined,
            location: {
              latitude: FALLBACK_HOME_LOCATION.lat,
              longitude: FALLBACK_HOME_LOCATION.lng,
              home_address: FALLBACK_HOME_ADDRESS,
            },
            home_location: FALLBACK_HOME_LOCATION,
          },
          token: null,
          isLoggedIn: true,
          isGuest: true,
        });
        console.log('[UserStore] 游客模式（完整画像）');
      },

      /** v18: 幂等保障 — 确保当前是游客会话，补齐缺失字段，不覆盖已有偏好 */
      ensureGuestSession: () => {
        const current = get();
        // 如果不是游客或已登录，先清掉旧 token
        if (!current.isGuest || current.token) {
          localStorage.removeItem('token');
        }
        const existing = current.user;
        const merged: User = {
          id: 'guest',
          username: existing?.username || '游客',
          email: '',
          gender: existing?.gender || '男',
          age: existing?.age || 30,
          preferences: existing?.preferences?.length ? existing.preferences : ['cultural', 'food'],
          activity_pref_tag: existing?.activity_pref_tag?.length ? existing.activity_pref_tag : ['文艺', '历史'],
          food_preferences: existing?.food_preferences?.length ? existing.food_preferences : ['本帮菜', '咖啡'],
          budget_per_capita: existing?.budget_per_capita ?? 100,
          city: existing?.city || undefined,
          location: existing?.location?.home_address
            ? existing.location
            : {
                latitude: existing?.home_location?.lat ?? FALLBACK_HOME_LOCATION.lat,
                longitude: existing?.home_location?.lng ?? FALLBACK_HOME_LOCATION.lng,
                home_address: existing?.location?.home_address || FALLBACK_HOME_ADDRESS,
              },
          home_location: existing?.home_location || FALLBACK_HOME_LOCATION,
        };
        set({
          user: merged,
          token: null,
          isLoggedIn: true,
          isGuest: true,
        });
      },

      updateUser: (updatedUser: User) => {
        set({ user: updatedUser });
      },

      updatePreferences: async (prefs: string[]) => {
        const { isGuest, user } = get();
        if (isGuest) {
          if (user) {
            set({ user: { ...user, preferences: prefs } });
          }
          return;
        }
        try {
          await authApi.updatePrefs(prefs);
          const currentUser = get().user;
          if (currentUser) {
            set({ user: { ...currentUser, preferences: prefs } });
          }
        } catch (error: any) {
          set({ error: error.response?.data?.detail || '更新偏好失败' });
          throw error;
        }
      },

      updateGuestProfile: (data: Partial<User>) => {
        const { user, isGuest } = get();
        if (!isGuest || !user) return;
        set({ user: { ...user, ...data } });
        console.log('[UserStore] 游客画像已更新:', data);
      },

      fetchUserProfile: async () => {
        const { token } = get();
        if (!token) {
          console.warn('[UserStore] 无token，跳过获取用户资料');
          return;
        }

        try {
          const response = await userApi.getProfile();
          const profileUser = response.data;
          // v6: 从 location.home_address 兜底补上 home_location
          if (!(profileUser as any).home_location && profileUser?.location?.home_address) {
            const ha = profileUser.location.home_address;
            (profileUser as any).home_location = {
              lat: ha.lat || 31.2809,
              lng: ha.lng || 121.5011,
              label: ha.name || ha.full_address || '家',
            };
          }
          set({ user: profileUser });
          console.log('[UserStore] 用户资料已更新');
        } catch (error: any) {
          console.error('[UserStore] 获取用户资料失败:', error);
          throw error;
        }
      },

      clearError: () => set({ error: null }),
    }),
    {
      name: 'user-storage',
      partialize: (state) => ({
        user: state.user,
        token: state.token,
        isLoggedIn: state.isLoggedIn,
        isGuest: state.isGuest,
      }),
    }
  )
);

// 导出工具函数供其他模块使用
export { isValidJWT, isTokenExpired };
