import { createRouter, createWebHistory } from 'vue-router'
import type { RouteRecordRaw } from 'vue-router'
import { DEMO_MODE, DEMO_TOKEN, DEMO_REFRESH_TOKEN, DEMO_USER } from '@/config/demoMode'

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

// 路由守卫：未登录时，演示模式自动注入 demo token，生产模式跳转登录页
router.beforeEach((to, _from, next) => {
  let token = localStorage.getItem('access_token')

  // 演示模式：无 token 时自动注入 demo token，避免跳转登录页
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

  if (to.name === 'Login' && token) {
    next({ name: 'Workspace' })
  } else {
    next()
  }
})

export default router
