/**
 * 演示模式配置
 *
 * 集中管理 demo-token 直通逻辑，由环境变量 VITE_DEMO_MODE 控制：
 * - VITE_DEMO_MODE=true  ：演示模式，无 token 自动注入 demo-token（跳过登录）
 * - VITE_DEMO_MODE=false ：生产模式，强制真实登录（后端 AUTH_REQUIRED=true 时需此模式）
 * - 未设置              ：默认**关闭**（fail-closed，与后端 auth_required 默认 true 对齐）
 *
 * ★ P0-2 修复：此前「未设置即演示模式」，部署时漏配一个环境变量就会把鉴权整个旁路掉，
 *   且不会产生任何报错。现默认值翻转为 false，并在**生产构建**下强制关闭（双重兜底）。
 *   本地开发由 .env.development / .env.local 显式置 true，行为不变。
 *
 * 说明：此前 demo-token 直通是硬编码在 router/index.ts 和 Login.vue 里的，
 * 导致后端鉴权闭环被前端绕过。本次抽到此处，由环境变量统一控制。
 */

/** 是否生产构建（vite build 产物为 true） */
const IS_PROD_BUILD: boolean = import.meta.env.PROD

/**
 * 是否启用演示模式。
 * 必须**显式**设 VITE_DEMO_MODE=true 才开启；生产构建一律关闭。
 */
export const DEMO_MODE: boolean =
  !IS_PROD_BUILD && import.meta.env.VITE_DEMO_MODE === 'true'

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
