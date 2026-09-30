import { createRouter, createWebHistory } from 'vue-router'
import type { RouteRecordRaw } from 'vue-router'
import {
  DEMO_MODE, DEMO_TOKEN, DEMO_REFRESH_TOKEN, DEMO_USER, isDemoToken,
} from '@/config/demoMode'

const routes: RouteRecordRaw[] = [
  {
    path: '/login',
    name: 'Login',
    component: () => import('@/views/Login.vue'),
    meta: { requiresAuth: false },
  },
  {
    path: '/',
    name: 'Workspace',
    component: () => import('@/views/Workspace.vue'),
    meta: { requiresAuth: true },
  },
  {
    path: '/team',
    name: 'Team',
    component: () => import('@/views/Team.vue'),
    meta: { requiresAuth: true },
  },
  {
    path: '/settings',
    name: 'Settings',
    component: () => import('@/views/Settings.vue'),
    meta: { requiresAuth: true },
  },
  {
    path: '/subscription',
    name: 'Subscription',
    component: () => import('@/views/Subscription.vue'),
    meta: { requiresAuth: true },
  },
  {
    path: '/memory',
    name: 'MemoryEvolution',
    component: () => import('@/views/MemoryEvolution.vue'),
    meta: { requiresAuth: true },
  },

  // ====== 邮件落地页（台账 #1154）======
  //
  // ★★★ 这两条路由不是"新增功能"，是**补上两条断链**。
  //
  //   后端 `core/identity/email_tokens.py::_link()` 生成的邮件链接是
  //     `{PUBLIC_SITE_URL}/reset-password?token=…`   （send_reset_email）
  //     `{PUBLIC_SITE_URL}/verify-email?token=…`     （send_verify_email）
  //   而本文件此前只有 6 条路由，**两条都不在其中** ⇒
  //   用户点开邮件看到的是**空白页**：链接是好的、token 是好的、后端也是好的，
  //   唯独没有页面去接它。
  //
  //   ⇒ 凡在本文件里增删路由，都要回头确认后端还在往哪些 path 发链接；
  //     `scripts/check-auth-frontend-wiring.cjs` 把这条对账钉成了门禁
  //     （它会从 email_tokens.py 里把 `_link("/…")` 全部抠出来，
  //      逐个要求这里存在同名路由）。
  //
  // ★ 必须 `requiresAuth: false`：点邮件的人**很可能根本没登录** ——
  //   "忘记密码"本身就是"登不上才用"的功能；邮箱验证更是注册后、
  //   首次登录前就要点。若要求登录，守卫会把用户弹去登录页，
  //   而他此刻恰恰进不去（这正是死锁的形状，见下方 beforeEach 的注释）。
  {
    path: '/reset-password',
    name: 'ResetPassword',
    component: () => import('@/views/ResetPassword.vue'),
    meta: { requiresAuth: false },
  },
  {
    path: '/verify-email',
    name: 'VerifyEmail',
    component: () => import('@/views/VerifyEmail.vue'),
    meta: { requiresAuth: false },
  },
]

const router = createRouter({
  history: createWebHistory(),
  routes,
})

// 路由守卫
//
// ★ 2026-09-16 修正（起因：老板反馈「提示要登录可是没有入口」）
//
//   旧逻辑只判断「有没有 token」，于是构成一个**死锁**：
//     * 有 demo token ⇒ 进 /login 会被弹回首页，想真登录也进不去；
//     * 那枚 token 被后端拒绝 ⇒ 对应 401 又被 `request.ts` 静默吞掉，
//       同样不会跳转。
//   两头都堵死，用户在中间**无路可走** —— 这就是"没有入口"。
//
//   现在按「**是不是真身份**」区分，而不是"有没有字符串"：
//     * demo token 不是身份 ⇒ 它**不**阻止用户进登录页真登录；
//     * 没有 token 且要进受保护页 ⇒ 去登录页，并记住来路（登录后回跳）。
router.beforeEach((to, _from, next) => {
  let token = localStorage.getItem('access_token')

  // 演示模式：无 token 时自动注入 demo token，避免演示时被登录页拦住
  if (DEMO_MODE && to.meta.requiresAuth && !token) {
    token = DEMO_TOKEN
    localStorage.setItem('access_token', token)
    localStorage.setItem('refresh_token', DEMO_REFRESH_TOKEN)
    localStorage.setItem('user_info', JSON.stringify({
      ...DEMO_USER,
      created_at: new Date().toISOString(),
      last_login_at: new Date().toISOString(),
    }))
  }

  // 登录页：只有**真实** token 才值得把用户弹回首页。
  // demo token 放行 —— 否则演示模式下用户永远无法改成真账号登录。
  if (to.name === 'Login') {
    if (token && !isDemoToken(token)) return next({ name: 'Workspace' })
    return next()
  }

  // 未登录进受保护页 → 去登录页，带上来路以便登录后回跳
  if (to.meta.requiresAuth && !token) {
    return next({ name: 'Login', query: { redirect: to.fullPath } })
  }

  next()
})

export default router
