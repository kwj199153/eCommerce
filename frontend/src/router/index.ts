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
