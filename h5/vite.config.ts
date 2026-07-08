import { defineConfig } from 'vite'
import react from '@vitejs/plugin-react'

// 开发时把 /api、/webhook 代理到 Service（:8001 REST / :8002 webhook）
export default defineConfig({
  plugins: [react()],
  server: {
    port: 5173,
    proxy: {
      '/api': { target: 'http://localhost:8001', changeOrigin: true },
      '/webhook': { target: 'http://localhost:8002', changeOrigin: true },
      '/health': { target: 'http://localhost:8001', changeOrigin: true },
    },
  },
})
