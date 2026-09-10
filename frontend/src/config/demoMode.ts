/**
 * 演示模式配置
 *
 * 集中管理 demo-token 直通逻辑，由环境变量 VITE_DEMO_MODE 控制：
 * - VITE_DEMO_MODE=true  ：演示模式，无 token 自动注入 demo-token（跳过登录）
 * - VITE_DEMO_MODE=false ：生产模式，强制真实登录（后端 AUTH_REQUIRED=true 时需此模式）
 * - 未设置              ：默认演示模式（兼容旧行为，便于本地演示）
 *
 * 说明：此前 demo-token 直通是硬编码在 router/index.ts 和 Login.vue 里的，
 * 导致后端鉴权闭环被前端绕过。本次抽到此处，由环境变量统一控制，
 * 生产部署时设 VITE_DEMO_MODE=false 即可关闭。
 */

/** 是否启用演示模式（读取环境变量，默认 true 兼容旧行为） */
export const DEMO_MODE: boolean =
  import.meta.env.VITE_DEMO_MODE !== 'false'

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

/** 判断一个 token 是否为 demo token */
export function isDemoToken(token: string | null | undefined): boolean {
  return token === DEMO_TOKEN || !!token?.startsWith('demo-')
}
