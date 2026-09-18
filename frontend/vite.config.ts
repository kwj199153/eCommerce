import { defineConfig } from 'vite'
import vue from '@vitejs/plugin-vue'
import { resolve } from 'path'

// https://vitejs.dev/config/
export default defineConfig({
  plugins: [vue()],
  // ------------------------------------------------------------
  //  生产构建剥离调试日志（第 135 轮）
  //  ★ 只删 console.log / console.debug：
  //    全前端 120+ 处 console.warn/error 是 catch 块里的**有意诊断记录**，
  //    用 terser 的 drop_console（整体删 console）会连它们一起删掉，
  //    等于「出错时什么都看不到」。esbuild 的 pure 精确到函数名。
  //  ★ pure 只在结果未被使用时生效；dev 模式不剥离，本地调试不受影响。
  // ------------------------------------------------------------
  esbuild: {
    pure: ['console.log', 'console.debug'],
  },
  resolve: {
    alias: {
      '@': resolve(__dirname, 'src'),
    },
  },
  build: {
    // ============================================================
    //  体积治理（2026-09-15 建立基线）
    // ------------------------------------------------------------
    //  改前实测：index 1546 kB / Workspace 999 kB / xlsx 419 kB，
    //  且**没有任何 manualChunks** —— 所有第三方与业务代码挤在一个 index 里。
    //
    //  ★ 拆包不减少总字节，它解决的是另外两件事：
    //    1) 缓存粒度：业务代码改动时 vendor-* 的 hash 不变，
    //       用户只需重下 index（几十 kB），而不是 1.5 MB 整包；
    //    2) 首屏并行：浏览器对多 chunk 可并行下载与解析。
    //
    //  ★ xlsx 必须独占一组：它是动态 import（导出功能才用）。
    //    若与任何静态模块并到同组，该组会被提升为首屏静态加载
    //    ⇒ 419 kB 在首屏白等，反而比不拆更糟。
    //
    //  ⚠️ 未做（需老板拍板，改动面覆盖全部 107 个组件）：
    //    antd 由 `app.use(Antd)` 全量注册改为按需引入。模板里用到
    //    96 种 a-* 标签、几千处，改按需需要 unplugin-vue-components
    //    并对每个组件做浏览器冒烟，漏一个就是静默渲染失败。
    //    预期收益：index 可再降数百 kB（那才是真正的"总量"下降）。
    // ============================================================
    // 超过这个值就告警：让体积增长在 CI 输出里可见，而不是悄悄涨
    chunkSizeWarningLimit: 1000,
    rollupOptions: {
      output: {
        manualChunks(id: string) {
          if (!id.includes('node_modules')) return
          if (id.includes('/xlsx/')) return 'vendor-xlsx'
          if (id.includes('/ant-design-vue/') || id.includes('/@ant-design/')) return 'vendor-antd'
          if (
            id.includes('/vue/') ||
            id.includes('/vue-router/') ||
            id.includes('/pinia/') ||
            id.includes('/@vue/')
          ) return 'vendor-vue'
          // ★ 其余第三方**故意不分组**，交回 Rollup 默认策略。
          //
          // 这是实测踩出来的：第一版把 markdown-it / axios / dayjs 和其余
          // 第三方都归成 'vendor-*'，结果这些包里有一部分原本是躺在
          // Workspace（路由懒加载）chunk 里的，归组后被提到了**首屏静态
          // chunk**，首屏总字节反而从 1546 kB 涨到 1773 kB（+227 kB）。
          //
          // 教训：manualChunks 不是"分得越细越好"。它只决定模块归属哪个
          // chunk，但一旦把「懒加载才用的包」和「首屏必需包」归到同一组，
          // 整组都会被提升为首屏加载。**分包前必须先量首屏静态闭包。**
          return undefined
        },
      },
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
