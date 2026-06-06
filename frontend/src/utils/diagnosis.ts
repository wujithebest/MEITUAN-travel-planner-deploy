// ============================================
// 网络诊断工具 - 用于检测前端与后端的连接问题
// 更新：改为检测普通HTTP连接（非SSE流式）
// 新增：多路径探测，支持检测重复前缀问题
// ============================================

import { API_CONFIG } from '../config/api.config';

const API_BASE = API_CONFIG.BASE_URL;

/** 诊断结果 */
export interface DiagnosisResult {
  backendAddress: string;
  connectionStatus: 'success' | 'failed' | 'unknown';
  connectionLatency?: number;
  corsStatus: 'success' | 'failed' | 'unknown';
  httpStatus: 'success' | 'failed' | 'unknown';
  httpError?: string;
  routePath?: string;  // 探测到的正确路径
  suggestions: string[];
}

/** API路径探测结果 */
export interface PathProbeResult {
  path: string;
  success: boolean;
  status: number;
  latency: number;
  error?: string;
}

/**
 * 探测单个API路径
 */
async function probePath(path: string, testBody: any): Promise<PathProbeResult> {
  const fullUrl = `${API_BASE}${path}`;
  const startTime = Date.now();
  
  try {
    const response = await fetch(fullUrl, {
      method: 'POST',
      headers: {
        'Content-Type': 'application/json',
        'Accept': 'application/json',
      },
      body: JSON.stringify(testBody),
      signal: AbortSignal.timeout(10000),
    });

    const latency = Date.now() - startTime;

    // 2xx 或 4xx（业务错误）都算路径存在
    if (response.ok || (response.status >= 400 && response.status < 500)) {
      // 检查是否是业务错误（说明路径正确）
      const errorData = await response.json().catch(() => null);
      const errorMessage = errorData?.message || '';
      
      // 业务错误说明路径是对的
      if (errorMessage.includes('OUT_OF_SHANGHAI') || 
          errorMessage.includes('INSUFFICIENT_POI') ||
          errorMessage.includes('INVALID_INPUT')) {
        return {
          path,
          success: true,
          status: response.status,
          latency,
        };
      }

      // 2xx 成功
      if (response.ok) {
        return {
          path,
          success: true,
          status: response.status,
          latency,
        };
      }
    }

    // 404 路径不存在
    if (response.status === 404) {
      return {
        path,
        success: false,
        status: 404,
        latency,
        error: '路径不存在 (404)',
      };
    }

    // 其他错误
    const errorData = await response.json().catch(() => null);
    return {
      path,
      success: false,
      status: response.status,
      latency,
      error: errorData?.message || `HTTP ${response.status}`,
    };
  } catch (error: any) {
    const latency = Date.now() - startTime;
    return {
      path,
      success: false,
      status: 0,
      latency,
      error: error.message || '请求失败',
    };
  }
}

/**
 * 多路径探测 - 检测正确的API路径
 * 先尝试 /api/route/generate，404时再尝试 /api/api/route/generate
 */
export async function probeApiPaths(): Promise<{
  results: PathProbeResult[];
  workingPath: string | null;
  hasDuplicatePrefix: boolean;
}> {
  const testBody = {
    query: '测试连接',
    transport_mode: 'driving',
    consider_weather: false,
  };

  const results: PathProbeResult[] = [];
  let workingPath: string | null = null;
  let hasDuplicatePrefix = false;

  console.log('[诊断] 开始多路径探测...');

  // 路径1: 标准路径 /api/route/generate
  console.log('[诊断] 探测路径1: /api/route/generate');
  const result1 = await probePath('/api/route/generate', testBody);
  results.push(result1);
  console.log(`[诊断] 路径1结果: ${result1.success ? '✅ 成功' : '❌ 失败'} (${result1.status})`);

  if (result1.success) {
    workingPath = '/api/route/generate';
  } else if (result1.status === 404) {
    // 路径2: 重复前缀路径 /api/api/route/generate
    console.log('[诊断] 探测路径2: /api/api/route/generate (检测重复前缀)');
    const result2 = await probePath('/api/api/route/generate', testBody);
    results.push(result2);
    console.log(`[诊断] 路径2结果: ${result2.success ? '✅ 成功' : '❌ 失败'} (${result2.status})`);

    if (result2.success) {
      workingPath = '/api/api/route/generate';
      hasDuplicatePrefix = true;
      console.warn('[诊断] ⚠️ 检测到后端路由重复前缀问题！');
      console.warn('[诊断] 建议修复：检查 main.py 和 route.py 的路由配置');
    }
  }

  return { results, workingPath, hasDuplicatePrefix };
}

/**
 * 检查后端HTTP连接状态
 * 使用普通HTTP请求（非SSE）
 */
export async function checkBackendConnection(): Promise<{
  reachable: boolean;
  status: number;
  latency: number;
  error?: string;
}> {
  const startTime = Date.now();
  try {
    // 尝试访问 /api/health 端点
    const response = await fetch(`${API_BASE}/api/health`, {
      method: 'GET',
      headers: {
        'Accept': 'application/json',
      },
      signal: AbortSignal.timeout(5000),
    });

    const latency = Date.now() - startTime;

    if (response.ok) {
      return { reachable: true, status: response.status, latency };
    }

    // 尝试备用端点 /api/docs
    const docsResponse = await fetch(`${API_BASE}/api/docs`, {
      method: 'GET',
      signal: AbortSignal.timeout(5000),
    });

    const docsLatency = Date.now() - startTime;

    return {
      reachable: docsResponse.ok,
      status: docsResponse.status,
      latency: docsLatency,
    };
  } catch (error: any) {
    const latency = Date.now() - startTime;
    return {
      reachable: false,
      status: 0,
      latency,
      error: error.message || '连接失败',
    };
  }
}

/**
 * 测试路线生成API（使用探测到的正确路径）
 */
export async function testRouteAPI(preferredPath?: string): Promise<{
  success: boolean;
  status: number;
  latency: number;
  error?: string;
  logs: string[];
}> {
  const logs: string[] = [];
  const startTime = Date.now();

  // 如果提供了首选路径，先尝试
  const pathsToTry = preferredPath 
    ? [preferredPath, preferredPath === '/api/route/generate' ? '/api/api/route/generate' : '/api/route/generate']
    : ['/api/route/generate', '/api/api/route/generate'];

  for (const path of pathsToTry) {
    const fullUrl = `${API_BASE}${path}`;
    logs.push(`[HTTP测试] 尝试路径: ${path}`);

    try {
      const response = await fetch(fullUrl, {
        method: 'POST',
        headers: {
          'Content-Type': 'application/json',
          'Accept': 'application/json',
        },
        body: JSON.stringify({
          query: '测试连接',
          transport_mode: 'driving',
          consider_weather: false,
        }),
        signal: AbortSignal.timeout(10000),
      });

      const latency = Date.now() - startTime;

      if (response.ok) {
        const data = await response.json();
        logs.push(`[HTTP测试] ✅ API响应成功，路径: ${path}，状态码: ${response.status}`);
        logs.push(`[HTTP测试] 响应数据: ${JSON.stringify(data).substring(0, 200)}...`);

        return {
          success: true,
          status: response.status,
          latency,
          logs,
        };
      }

      // 检查是否是业务错误（如OUT_OF_SHANGHAI）
      const errorData = await response.json().catch(() => null);
      const errorMessage = errorData?.message || `HTTP ${response.status}`;

      logs.push(`[HTTP测试] ⚠️ 路径 ${path} 返回错误: ${errorMessage}`);

      // 如果是业务错误，说明API本身是通的
      if (errorMessage.includes('OUT_OF_SHANGHAI') || errorMessage.includes('INSUFFICIENT_POI')) {
        logs.push(`[HTTP测试] ✅ API连接正常（业务错误说明API可达）`);
        return {
          success: true,
          status: response.status,
          latency,
          logs,
        };
      }

      // 404 继续尝试下一个路径
      if (response.status === 404) {
        logs.push(`[HTTP测试] 路径 ${path} 不存在 (404)，尝试备用路径...`);
        continue;
      }

      return {
        success: false,
        status: response.status,
        latency,
        error: errorMessage,
        logs,
      };
    } catch (error: any) {
      logs.push(`[HTTP测试] ❌ 路径 ${path} 请求失败: ${error.message}`);
      
      // 如果是最后一个路径，返回错误
      if (path === pathsToTry[pathsToTry.length - 1]) {
        const latency = Date.now() - startTime;
        return {
          success: false,
          status: 0,
          latency,
          error: error.message || '请求失败',
          logs,
        };
      }
    }
  }

  const latency = Date.now() - startTime;
  logs.push(`[HTTP测试] ❌ 所有路径均失败`);
  return {
    success: false,
    status: 0,
    latency,
    error: '所有路径均失败',
    logs,
  };
}

/**
 * 分类网络错误并提供修复建议
 */
export function categorizeNetworkError(error: any): {
  type: 'cors' | 'refused' | 'timeout' | 'server' | 'unknown';
  description: string;
  suggestions: string[];
} {
  const errorMessage = error?.message || String(error);
  const errorCode = error?.code || '';

  // CORS错误
  if (
    errorMessage.includes('CORS') ||
    errorMessage.includes('cross-origin') ||
    errorMessage.includes('Access-Control-Allow-Origin') ||
    (error?.name === 'TypeError' && errorMessage.includes('fetch'))
  ) {
    return {
      type: 'cors',
      description: '跨域资源共享(CORS)错误',
      suggestions: [
        '检查后端是否配置了CORS中间件',
        '确认后端允许前端域名访问',
        '检查 vite.config.ts 中的代理配置',
      ],
    };
  }

  // 连接拒绝
  if (
    errorMessage.includes('ECONNREFUSED') ||
    errorMessage.includes('Failed to fetch') ||
    errorMessage.includes('NetworkError') ||
    errorCode === 'ECONNREFUSED'
  ) {
    return {
      type: 'refused',
      description: '连接被拒绝，后端服务可能未运行',
      suggestions: [
        '检查后端服务是否已启动',
        '确认后端端口号是否正确（默认8002）',
        '检查防火墙设置',
        `尝试直接访问后端地址验证: ${API_BASE}`,
      ],
    };
  }

  // 超时
  if (
    errorMessage.includes('timeout') ||
    errorMessage.includes('Timeout') ||
    errorMessage.includes('ABORTED') ||
    errorCode === 'ECONNABORTED'
  ) {
    return {
      type: 'timeout',
      description: '请求超时',
      suggestions: [
        '检查网络连接是否稳定',
        '后端处理时间可能过长，考虑增加超时时间',
        '检查后端是否有性能问题',
      ],
    };
  }

  // 服务器错误
  if (
    errorMessage.includes('500') ||
    errorMessage.includes('502') ||
    errorMessage.includes('503') ||
    errorMessage.includes('Internal Server Error')
  ) {
    return {
      type: 'server',
      description: '服务器内部错误',
      suggestions: [
        '查看后端日志获取详细错误信息',
        '检查后端代码是否有异常',
        '确认后端依赖是否正常运行',
      ],
    };
  }

  // 未知错误
  return {
    type: 'unknown',
    description: `未知错误: ${errorMessage}`,
    suggestions: [
      '检查浏览器控制台获取更多信息',
      '尝试刷新页面重试',
      '检查网络连接',
    ],
  };
}

/**
 * 生成完整的诊断报告
 */
export async function runFullDiagnosis(): Promise<DiagnosisResult> {
  const result: DiagnosisResult = {
    backendAddress: API_BASE,
    connectionStatus: 'unknown',
    corsStatus: 'unknown',
    httpStatus: 'unknown',
    suggestions: [],
  };

  // 1. 检查后端连接
  console.log('[诊断] 正在检查后端HTTP连接...');
  const connectionResult = await checkBackendConnection();

  if (connectionResult.reachable) {
    result.connectionStatus = 'success';
    result.connectionLatency = connectionResult.latency;
    result.corsStatus = 'success';
    console.log(`[诊断] 后端连接正常，延迟: ${connectionResult.latency}ms`);
  } else {
    result.connectionStatus = 'failed';
    console.log(`[诊断] 后端连接失败: ${connectionResult.error}`);

    // 分类错误
    const errorInfo = categorizeNetworkError({ message: connectionResult.error });
    result.suggestions.push(...errorInfo.suggestions);

    // 如果是连接问题，HTTP也不需要测试了
    if (errorInfo.type === 'refused') {
      result.httpStatus = 'failed';
      result.httpError = '后端未运行，无法测试HTTP API';
      return result;
    }
  }

  // 2. 多路径探测
  console.log('[诊断] 开始多路径探测...');
  const probeResult = await probeApiPaths();

  // 输出探测日志
  probeResult.results.forEach(r => {
    console.log(`[诊断] 路径 ${r.path}: ${r.success ? '✅' : '❌'} (${r.status}) ${r.error || ''}`);
  });

  if (probeResult.hasDuplicatePrefix) {
    result.suggestions.push('');
    result.suggestions.push('⚠️ 检测到后端路由重复前缀问题！');
    result.suggestions.push('原因：main.py 中已添加 prefix="/api"，route.py 中又定义了 /api 前缀');
    result.suggestions.push('解决方案（二选一）：');
    result.suggestions.push('  方案A（推荐）：修改 main.py，移除 prefix="/api"');
    result.suggestions.push('  方案B：设置环境变量 VITE_API_ROUTE_PATH=/api/api/route/generate');
  }

  if (probeResult.workingPath) {
    result.routePath = probeResult.workingPath;
  }

  // 3. 测试HTTP API
  console.log('[诊断] 正在测试HTTP API...');
  const apiResult = await testRouteAPI(probeResult.workingPath || undefined);

  // 输出测试日志
  apiResult.logs.forEach(log => console.log(log));

  if (apiResult.success) {
    result.httpStatus = 'success';
    console.log('[诊断] HTTP API测试通过');
  } else {
    result.httpStatus = 'failed';
    result.httpError = apiResult.error;
    console.log(`[诊断] HTTP API失败: ${apiResult.error}`);
  }

  // 4. 生成总结建议
  if (result.connectionStatus === 'success' && result.httpStatus === 'success') {
    result.suggestions.push('✅ 所有检查通过！如果仍有问题，请检查:');
    result.suggestions.push('- 浏览器控制台是否有其他错误');
    result.suggestions.push('- 前端代码中的API调用路径是否正确');
    result.suggestions.push('- 认证token是否有效');
  } else if (result.connectionStatus === 'failed') {
    result.suggestions.push('');
    result.suggestions.push('🔧 首要修复步骤:');
    result.suggestions.push('1. 确保后端服务已启动');
    result.suggestions.push(`2. 在浏览器中直接访问: ${API_BASE}/api/health`);
    result.suggestions.push('3. 检查 vite.config.ts 中的代理配置');
  }

  return result;
}

/**
 * 格式化诊断报告为可读字符串
 */
export function formatDiagnosisReport(result: DiagnosisResult): string {
  const lines: string[] = [];

  lines.push('=== 网络诊断报告 ===');
  lines.push('');
  lines.push(`后端地址: ${result.backendAddress}`);
  lines.push(`连接状态: ${result.connectionStatus === 'success' ? '✅ 正常' : '❌ 无法连接'}${result.connectionLatency ? ` (${result.connectionLatency}ms)` : ''}`);
  lines.push(`CORS配置: ${result.corsStatus === 'success' ? '✅ 正常' : result.corsStatus === 'failed' ? '❌ 未配置' : '⚠️ 未测试'}`);
  lines.push(`HTTP API: ${result.httpStatus === 'success' ? '✅ 正常' : `❌ 失败 (${result.httpError || '未知错误'})`}`);
  
  if (result.routePath) {
    lines.push(`API路径: ${result.routePath}`);
    if (result.routePath.includes('/api/api/')) {
      lines.push('⚠️ 检测到重复前缀路径！');
    }
  }

  if (result.suggestions.length > 0) {
    lines.push('');
    lines.push('建议修复:');
    result.suggestions.forEach(s => lines.push(s));
  }

  return lines.join('\n');
}
