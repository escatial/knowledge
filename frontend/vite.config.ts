import { defineConfig } from 'vite'
import react from '@vitejs/plugin-react'

// 差异 #11：base 通过 VITE_BASE_PATH 环境变量配置
//   生产部署到子路径 /kb/ 时：VITE_BASE_PATH=/kb/ npm run build
//   部署到根路径：VITE_BASE_PATH=/ npm run build（默认）
// 差异 #12：HOST/PORT 可通过环境变量配置（dev 远程访问场景）
export default defineConfig({
  base: process.env.VITE_BASE_PATH || '/',
  plugins: [react()],
  server: {
    host: process.env.HOST || 'localhost',
    port: parseInt(process.env.PORT || '5173'),
    proxy: {
      '/api': {
        target: process.env.VITE_API_TARGET || 'http://localhost:8005',
        changeOrigin: true
      }
    }
  }
})
