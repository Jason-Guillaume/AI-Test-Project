import { defineConfig } from 'vite';
import react from '@vitejs/plugin-react';
import { fileURLToPath, URL } from 'node:url';

// 前端请求 /api/v1/* → 转发到后端，保留 /api 前缀（后端路由统一挂在 /api/v1）。
// 与旧项目「删除 /api 前缀」的做法不同，这里不再 rewrite，避免前后端前缀错位。
export default defineConfig({
  plugins: [react()],
  server: {
    port: 5173,
    host: true,
    proxy: {
      // 只匹配 /api 前缀，命中后原样转发到后端（不设 rewrite，前缀必须保留）
      '/api': {
        // 目标可用环境变量覆盖，默认指向本地后端 8001
        target: process.env.VITE_API_PROXY_TARGET || 'http://127.0.0.1:8001',
        // 改写成后端能识别的 Host，保证后端按本地地址处理请求
        changeOrigin: true,
      },
    },
  },
  resolve: {
    alias: {
      // '@' 指向 src，页面与 api 层统一用它做相对导入
      '@': fileURLToPath(new URL('./src', import.meta.url)),
    },
  },
  build: {
    outDir: 'dist',
    // 生产构建不出 sourcemap，避免源码路径与内部实现外泄
    sourcemap: false,
  },
});
