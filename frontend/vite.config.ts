import { defineConfig } from 'vite'
import vue from '@vitejs/plugin-vue'
import { resolve } from 'path'

// https://vitejs.dev/config/
export default defineConfig({
  plugins: [vue()],
  resolve: {
    alias: {
      '@': resolve(__dirname, 'src'),
    },
  },
  server: {
    host: '0.0.0.0',  // 强制绑定 IPv4，解决 Windows localhost 访问问题
    strictPort: false,  // 端口被占用时自动尝试下一个
    port: 5173,
    proxy: {
      '/api': {
        target: 'http://localhost:8000',
        changeOrigin: true,
      },
      // 后端把 uploads 挂到 /static（AIGC 素材图：万相临时链接 24h 过期，故出图后转存本地）。
      // 不代理的话，前端 <img src="/static/..."> 会打到 5173 上 404。
      '/static': {
        target: 'http://localhost:8000',
        changeOrigin: true,
      },
    },
  },
})
