/**
 * 运行时 API 基址 —— 浏览器 / 桌面壳 / 平板 APK 共用同一份前端源码
 * ================================================================
 *
 * ★★★ 为什么需要这一层（这是"打包能成功但用不了"的第一个断点）
 * ---------------------------------------------------------------------------
 * 打包后 `request.ts` 里写死的 `baseURL: '/api/v1'` 是一条**相对路径**，它在 Web 上
 * 之所以能用，是因为背后有两样东西：
 *   · 开发态：Vite dev server 的 proxy（`vite.config.ts` 把 `/api` 转到 :8000）；
 *   · 生产态：nginx 把 `/api/`、`/static/` 反代到后端（`docs/产品侧上线契约.md` §3.4）。
 * 而**壳里这两样都不存在** —— Tauri 的自定义协议只会去内嵌产物里找文件，
 * 找不到时按 SPA 规则回落到 `index.html`。于是症状不是 404，而是
 * **200 + text/html** ⇒ 前端拿到一段 HTML 当 JSON 解析 ⇒ `Unexpected token '<'`，
 * 追查方向会跑到 axios / 拦截器 / 序列化上，而真因是"这条请求根本没出 webview"。
 *
 * ⇒ 唯一修法：壳在**页面脚本之前**注入 `window.__ECOM_API_ORIGIN__`
 *   （`desktop/src-tauri/src/lib.rs::init_script`），前端所有出站请求都从本文件取基址。
 *
 * ★★★ 对 Web 端必须**逐字不变**
 * ---------------------------------------------------------------------------
 * 浏览器里 `__ECOM_API_ORIGIN__` 不存在 ⇒ `API_ORIGIN === ''` ⇒ `apiBaseUrl()`
 * 拼出来就是原来的 `'/api/v1'`。这不是"顺手兼容"，而是硬要求：
 * 同一份产物要同时喂 Web 与壳，任何一处漂移都会让线上出现跨域或 404。
 * 判据：`frontend/scripts/check-desktop-wiring.cjs` 的 W 组（`API_ORIGIN === ''` 时
 * `apiBaseUrl()` 必须精确等于 `'/api/v1'`）。
 */

declare global {
  interface Window {
    /** 壳注入的后端 origin（不含 `/api` 后缀、不含尾斜杠）；浏览器里恒为 undefined */
    __ECOM_API_ORIGIN__?: string
    /**
     * 壳注入的存盘函数：把字节交给原生「另存为」。
     * 返回**绝对路径**；用户取消返回 `null`；失败抛错。
     */
    __ECOM_SAVE_FILE__?: (filename: string, base64: string) => Promise<string | null>
  }
}

/**
 * 后端 origin。**浏览器里是空串**，这是刻意设计的"零影响"形态。
 *
 * ★ 只读一次、不在运行时反复读 `window`：壳是在页面脚本之前注入的，
 *   之后不会变；反复读只会在测试里制造"注入与否"的分叉。
 */
export const API_ORIGIN: string =
  (typeof window !== 'undefined' && window.__ECOM_API_ORIGIN__) || ''

/** axios 的 baseURL。空 origin 时与历史行为逐字相同。 */
export function apiBaseUrl(): string {
  return `${API_ORIGIN}/api/v1`
}

/**
 * 把后端返回的**站内路径**补成壳里可用的绝对地址。
 *
 * 覆盖面：`/static/**`（AIGC 素材图、语音 TTS 的转存音频）。
 * ★ 已经在 Web 端工作的原因：同源。而壳的 origin 是 `tauri.localhost`，
 *   `/static/x.mp3` 会打到自己身上 ⇒ 命中 SPA 回落 ⇒ 拿到 HTML 当音频解码 ⇒
 *   播放静默失败（解码失败的 catch 把错误吞成一条 console.warn）。
 *
 * ★ 已经是绝对地址（http/https/data:/blob:）时**原样返回**：
 *   后端有些字段是外部直链（万相临时链接），前缀拼上去就废了。
 */
export function assetUrl(url: string | null | undefined): string {
  if (!url) return ''
  if (/^(https?:|data:|blob:|file:)/i.test(url)) return url
  // 留一条兜底：万一拿到的是协议相对地址（//host/x），也要能补齐
  if (url.startsWith('//')) return `http:${url}`
  return `${API_ORIGIN}${url.startsWith('/') ? '' : '/'}${url}`
}
