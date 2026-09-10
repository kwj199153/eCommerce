import { createRouter, createWebHistory } from 'vue-router'
import type { RouteRecordRaw } from 'vue-router'

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

// 路由守卫：未登录时自动进入演示模式（Mock 项目无需真实认证）
router.beforeEach((to, _from, next) => {
  let token = localStorage.getItem('access_token')

  // 演示模式：无 token 时自动注入 demo token，避免跳转登录页
  if (to.meta.requiresAuth && !token) {
    token = 'demo-token'
    localStorage.setItem('access_token', token)
    localStorage.setItem('refresh_token', 'demo-refresh')
    localStorage.setItem('user_info', JSON.stringify({
      id: 'demo-user-001',
      email: 'demo@ecommerce.ai',
      name: '演示用户',
      role: 'admin',
      is_active: true,
      is_verified: false,
      created_at: new Date().toISOString(),
      last_login_at: new Date().toISOString(),
    }))
  }

  if (to.name === 'Login' && token) {
    next({ name: 'Workspace' })
  } else {
    next()
  }
})

export default router
