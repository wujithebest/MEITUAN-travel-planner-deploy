/**
 * 规划历史服务
 * - 注册用户：调用后端 API（MongoDB 持久化）
 * - 游客模式：使用浏览器 localStorage
 */

import { userApi } from '@/api/user';
import type { ChatMessage } from '@/hooks/useChat';

const STORAGE_KEY = 'travel-planner-route-histories-v1';
const MAX_GUEST_HISTORIES = 50;

export interface RouteHistory {
  history_id: string;
  title: string;
  destination: string;
  days: number;
  created_at: string;
  updated_at: string;
  request_id?: string;
  user_input?: string;
  messages: ChatMessage[];
  complete_plan: any;
  route_data: any;
  panel_days: any;
  map_route_data: any;
  poi_details: Record<string, any>;
  summary?: { poi_count: number; distance: number; duration: number };
}

function generateId(): string {
  return `hist_${Date.now()}_${Math.random().toString(36).substr(2, 9)}`;
}

function getLocalHistories(): RouteHistory[] {
  try {
    const raw = localStorage.getItem(STORAGE_KEY);
    return raw ? JSON.parse(raw) : [];
  } catch {
    return [];
  }
}

function setLocalHistories(histories: RouteHistory[]): void {
  localStorage.setItem(STORAGE_KEY, JSON.stringify(histories));
}

export const routeHistoryService = {
  /** 列出所有规划历史（按创建时间倒序） */
  async listHistories(isGuest: boolean): Promise<RouteHistory[]> {
    if (isGuest) {
      return getLocalHistories().sort(
        (a, b) => new Date(b.created_at).getTime() - new Date(a.created_at).getTime()
      );
    }
    try {
      const res = await userApi.getRouteHistories();
      const innerData = res?.data?.data || res?.data || [];
      return (Array.isArray(innerData) ? innerData : []) as RouteHistory[];
    } catch {
      return [];
    }
  },

  /** 保存规划历史（每次成功规划都新增一条，不去重） */
  async saveHistory(isGuest: boolean, payload: Omit<RouteHistory, 'history_id' | 'created_at' | 'updated_at'>): Promise<RouteHistory> {
    if (isGuest) {
      const histories = getLocalHistories();
      const now = new Date().toISOString();
      const history: RouteHistory = {
        ...payload,
        history_id: generateId(),
        created_at: now,
        updated_at: now,
      } as RouteHistory;
      histories.push(history);
      // 最多保留 50 条
      if (histories.length > MAX_GUEST_HISTORIES) {
        histories.splice(0, histories.length - MAX_GUEST_HISTORIES);
      }
      setLocalHistories(histories);
      return history;
    }

    try {
      const res = await userApi.createRouteHistory(payload);
      return (res?.data?.data || res?.data) as RouteHistory;
    } catch {
      throw new Error('保存规划历史失败');
    }
  },

  /** 删除规划历史 */
  async deleteHistory(isGuest: boolean, historyId: string): Promise<void> {
    if (isGuest) {
      const histories = getLocalHistories().filter(
        h => h.history_id !== historyId
      );
      setLocalHistories(histories);
      return;
    }
    await userApi.deleteRouteHistory(historyId);
  },

  /** 清空所有历史 */
  async clearHistories(isGuest: boolean): Promise<void> {
    if (isGuest) {
      setLocalHistories([]);
      return;
    }
    await userApi.clearRouteHistories();
  },
};

export default routeHistoryService;
