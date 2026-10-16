/**
 * 演示模式配置
 *
 * 集中管理 demo-token 直通逻辑，由环境变量 VITE_DEMO_MODE 控制：
 * - VITE_DEMO_MODE=true  ：演示模式，无 token 自动注入 demo-token（跳过登录）
 * - VITE_DEMO_MODE=false ：生产模式，强制真实登录（后端 AUTH_REQUIRED=true 时需此模式）
 * - 未设置              ：默认**关闭**（fail-closed，与后端 auth_required 默认 true 对齐）
 *
 * ★ P0-2 修复：此前「未设置即演示模式」，部署时漏配一个环境变量就会把鉴权整个旁路掉，
 *   且不会产生任何报错。现默认值翻转为 false（未设置 = 关闭，fail-closed）。
 *   本地开发由 .env.development / .env.local 显式置 true，行为不变。
 *
 * ★ 2026-10-15 调整：去掉 `!IS_PROD_BUILD` 硬闸（生产构建强制关闭）。
 *   原因：部署到自有服务器后，页面市场洞察等模块依赖演示身份的 mock 数据源，
 *   硬闸导致线上永远「暂无数据」。改为「显式 VITE_DEMO_MODE=true 即生效」，
 *   fail-closed 语义保留：不设置仍然默认关闭，漏配依旧安全。
 *   后端 DEMO_MODE 才是真正的鉴权闸门（后端关了前端开也没用）。
 *
 * 说明：此前 demo-token 直通是硬编码在 router/index.ts 和 Login.vue 里的，
 * 导致后端鉴权闭环被前端绕过。本次抽到此处，由环境变量统一控制。
 */

/**
 * 是否启用演示模式。
 * 必须显式设 VITE_DEMO_MODE=true 才开启；未设置一律关闭（fail-closed）。
 */
export const DEMO_MODE: boolean =
  import.meta.env.VITE_DEMO_MODE === 'true'

/** demo 账号常量 */
export const DEMO_TOKEN = 'demo-token'
export const DEMO_REFRESH_TOKEN = 'demo-refresh-token'
export const DEMO_USER = {
  id: 'demo-user-001',
  email: 'demo@ecommerce.ai',
  name: '演示用户',
  role: 'admin' as const,
  is_active: true,
  is_verified: false,
}

/**
 * 判断一个 token 是否为 demo token。
 * 演示模式关闭时恒为 false —— 避免历史遗留的 demo-token 残留在 localStorage 里
 * 继续被 request.ts 当成有效凭据复用。
 */
export function isDemoToken(token: string | null | undefined): boolean {
  if (!DEMO_MODE) return false
  return token === DEMO_TOKEN || !!token?.startsWith('demo-')
}
