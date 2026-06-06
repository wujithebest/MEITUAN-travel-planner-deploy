import { defineConfig } from 'vite';
import react from '@vitejs/plugin-react';
import { fileURLToPath, URL } from 'node:url';

export default defineConfig({
  define: {
    'process.env': {},
    'process.env.VITE_API_BASE_URL': JSON.stringify(process.env.VITE_API_BASE_URL || '/api'),
    'process.env.VITE_GAODE_JSAPI_KEY': JSON.stringify(process.env.VITE_GAODE_JSAPI_KEY || ''),
    'process.env.VITE_GAODE_SECURITY_CONFIG': JSON.stringify(process.env.VITE_GAODE_SECURITY_CONFIG || ''),
  },
  plugins: [react()],
  resolve: {
    alias: {
      '@': fileURLToPath(new URL('./src', import.meta.url)),
    },
  },
  server: {
    // 绑定到所有网络接口，允许外部 IP 访问
    host: '0.0.0.0',
    
    // 端口配置
    port: 3006,
    
    // 严格端口（如果被占用则报错，不自动切换）
    strictPort: true,
    
    // CORS 配置（允许所有来源访问）
    cors: true,
    
    // 热更新配置 - 允许外部访问
    hmr: {
      host: '0.0.0.0',
      port: 3006,
      protocol: 'ws',
    },
    
    // 允许的主机列表（可选，用于安全限制）
    // 如果设置，只有列出的主机可以访问
    // allowedHosts: ['localhost', '127.0.0.1', '100.72.47.69', '192.168.1.0/24'],
    
    // API 代理配置
    proxy: {
      '/api': {
        target: 'http://localhost:8002',
        changeOrigin: true,
        ws: true, // 启用 WebSocket 代理
      },
      // SSE 流式接口代理
      '/api/meituan/chat/stream': {
        target: 'http://localhost:8002',
        changeOrigin: true,
        ws: true,
        headers: {
          'Cache-Control': 'no-cache',
          'Connection': 'keep-alive',
        },
      },
    },
  },
});
