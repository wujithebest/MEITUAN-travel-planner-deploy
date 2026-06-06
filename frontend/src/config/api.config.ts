// ============================================
// API 配置中心
// ============================================

/**
 * 获取API基础URL
 */
function getApiBaseUrl(): string {
  const envUrl = import.meta.env.VITE_API_BASE_URL;

  if (!envUrl) {
    console.warn('[API Config] VITE_API_BASE_URL 未设置，使用默认值: http://localhost:8002');
    return 'http://localhost:8002';
  }

  // 相对路径通过Vite代理
  if (envUrl.startsWith('/')) {
    console.log(`[API Config] 使用相对路径 API: ${envUrl} (通过 Vite 代理)`);
    return envUrl;
  }

  // 验证URL格式
  try {
    new URL(envUrl);
    console.log(`[API Config] 使用完整 URL API: ${envUrl}`);
    return envUrl;
  } catch {
    console.error(`[API Config] 无效的 API URL: ${envUrl}，使用默认值`);
    return 'http://localhost:8002';
  }
}

/**
 * 是否使用Mock数据
 */
function getUseMock(): boolean {
  const useMock = import.meta.env.VITE_USE_MOCK;
  const result = useMock === 'true';
  console.log(`[API Config] VITE_USE_MOCK: ${result}`);
  return result;
}

// API配置对象
export const API_CONFIG = {
  /** API基础URL */
  BASE_URL: getApiBaseUrl(),
  /** 请求超时时间（毫秒） */
  TIMEOUT: 30000,
  /** 是否使用Mock数据 */
  USE_MOCK: getUseMock(),
};

console.log('[API Config] 当前配置:', API_CONFIG);

/**
 * 构建完整的 API URL，避免在 Vercel 生产环境出现相对路径请求。
 *
 * 规则：
 * - 如果 VITE_API_BASE_URL 已以 /api 结尾（如 Render 回调），则：
 *   buildApiUrl('/route/generate') → https://<host>/api/route/generate
 *   buildApiUrl('/api/meituan/chat/stream') → https://<host>/api/meituan/chat/stream
 * - 如果 VITE_API_BASE_URL 不以 /api 结尾（如 http://localhost:8002），则自动追加 /api。
 * - 避免 /api/api 重复。
 */
export function buildApiUrl(path: string): string {
  const base = API_CONFIG.BASE_URL.replace(/\/+$/, '');
  const normalizedPath = path.startsWith('/') ? path : `/${path}`;

  if (normalizedPath.startsWith('/api/')) {
    const pathWithoutApi = normalizedPath.slice(4); // 去掉 '/api' 前缀
    return base.endsWith('/api')
      ? `${base}${pathWithoutApi}`
      : `${base}${normalizedPath}`;
  }

  return base.endsWith('/api')
    ? `${base}${normalizedPath}`
    : `${base}/api${normalizedPath}`;
}
