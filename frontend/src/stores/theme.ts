/**
 * 主题切换 store（明/暗/跟随系统）
 *
 * 设计要点：
 * - 主题模式：light / dark / system
 * - effective 实际生效主题：根据 mode + 系统偏好解析
 * - 主题应用：与 App.vue a-config-provider 联动切换 token，并切换 html.dark 类
 *
 * 持久化：localStorage 存 mode；系统模式读 matchMedia。
 */

import { defineStore } from 'pinia'
import { ref, computed, onMounted, onUnmounted, watch } from 'vue'

export type ThemeMode = 'light' | 'dark' | 'system'
export type EffectiveTheme = 'light' | 'dark'

const STORAGE_KEY = 'theme_mode'

export const useThemeStore = defineStore('theme', () => {
  // 用户意图模式
  const mode = ref<ThemeMode>((localStorage.getItem(STORAGE_KEY) as ThemeMode) || 'light')

  // 系统主题
  const systemTheme = ref<EffectiveTheme>(
    window.matchMedia?.('(prefers-color-scheme: dark)').matches ? 'dark' : 'light'
  )

  // 监听系统主题变化
  let mql: MediaQueryList | null = null
  const onSystemChange = (e: MediaQueryListEvent) => {
    systemTheme.value = e.matches ? 'dark' : 'light'
  }

  onMounted(() => {
    if (window.matchMedia) {
      mql = window.matchMedia('(prefers-color-scheme: dark)')
      mql.addEventListener('change', onSystemChange)
    }
  })
  onUnmounted(() => {
    mql?.removeEventListener('change', onSystemChange)
  })

  // 实际生效主题
  const effective = computed<EffectiveTheme>(() => {
    if (mode.value === 'system') return systemTheme.value
    return mode.value
  })

  // ant-design-vue 主题 token（最小集，覆盖关键颜色，避免大面积重构）
  const antdTheme = computed(() => {
    if (effective.value === 'dark') {
      return {
        token: {
          colorPrimary: '#177ddc',
          colorBgBase: '#141414',
          colorBgContainer: '#1f1f1f',
          colorBgLayout: '#000000',
          colorText: 'rgba(255,255,255,0.85)',
          colorTextSecondary: 'rgba(255,255,255,0.65)',
          colorBorder: '#303030',
          colorBorderSecondary: '#303030',
        },
      }
    }
    return {
      token: {
        colorPrimary: '#1890ff',
      },
    }
  })

  // mode → 持久化
  watch(mode, (v) => {
    localStorage.setItem(STORAGE_KEY, v)
  })

  // effective → 切换 body.dark 类
  watch(
    effective,
    (v) => {
      document.documentElement.classList.toggle('dark', v === 'dark')
      document.documentElement.dataset.theme = v
    },
    { immediate: true }
  )

  const setMode = (m: ThemeMode) => {
    mode.value = m
  }

  return {
    mode,
    systemTheme,
    effective,
    antdTheme,
    setMode,
  }
})
