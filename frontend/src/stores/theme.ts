/**
 * 主题切换 store（明 / 暗 / 跟随系统）
 *
 * ★ 本文件**不含任何色值** —— 颜色真源是 `@/theme/presets` 的预设表。
 *   这里只做三件事：解析模式 → 应用预设（改 `<html>` 属性/类）→ 把 antd 配置交给
 *   App.vue 的 `a-config-provider`。
 *
 * 应用一次主题包含两个动作（都是 `effective` 变化时触发）：
 *   ① `documentElement.dataset.theme = <预设名>` → 命中 `html[data-theme="x"]{...}`
 *      （变量表由 `installThemeStyles()` 注入，见 presets.ts）
 *   ② `documentElement.classList.toggle('dark', preset.isDark)`
 *      → 组件补丁层（App.vue 的 `html.dark .xxx !important`）按它匹配。
 *      ⚠️ 补丁层是待清空项；它清空后，② 只剩「给浏览器/第三方库看的语义标记」作用。
 *
 * 持久化：localStorage 存 mode（键名 `theme_mode`）；system 模式读 matchMedia。
 *
 * ★ 加第三套主题：只在 `@/theme/presets` 加一个 entry（菜单项由 THEME_OPTIONS 派生），
 *   本文件零改动。前提是新主题**不要**再依赖补丁层。
 */

import { defineStore } from 'pinia'
import { ref, computed, onMounted, onUnmounted, watch } from 'vue'
import { theme as antdThemeConfig } from 'ant-design-vue'
import {
  DEFAULT_THEME,
  SYSTEM_MODE,
  THEME_PRESETS,
  installThemeStyles,
  makePinAlgorithm,
  type ThemeMode,
  type ThemeName,
} from '@/theme/presets'

export type { ThemeMode }
/** 生效主题（「跟随系统」被解析后的结果）—— 保留旧名以免影响既有引用 */
export type EffectiveTheme = ThemeName

const STORAGE_KEY = 'theme_mode'

/** 预设里的算法简写 → antd 算法函数 */
const ALGORITHMS = {
  light: antdThemeConfig.defaultAlgorithm,
  dark: antdThemeConfig.darkAlgorithm,
} as const

const isThemeName = (v: unknown): v is ThemeName =>
  typeof v === 'string' && Object.prototype.hasOwnProperty.call(THEME_PRESETS, v)

const isThemeMode = (v: unknown): v is ThemeMode => v === SYSTEM_MODE || isThemeName(v)

// 变量样式表在模块加载时就注入（早于 app.mount → 首帧即有颜色，不依赖组件挂载顺序）。
// 幂等：presets.ts 内按 id 去重。非浏览器环境（SSR / 单测）跳过。
if (typeof document !== 'undefined') installThemeStyles()

export const useThemeStore = defineStore('theme', () => {
  // 用户意图模式（含「跟随系统」）；存了个不认识的值就回落到默认预设
  const stored = typeof localStorage !== 'undefined' ? localStorage.getItem(STORAGE_KEY) : null
  const mode = ref<ThemeMode>(isThemeMode(stored) ? stored : DEFAULT_THEME)

  // 系统主题
  const systemTheme = ref<ThemeName>(
    window.matchMedia?.('(prefers-color-scheme: dark)').matches ? 'dark' : 'light'
  )

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

  /** 实际生效的预设名（「跟随系统」在这里被解析成 light / dark） */
  const effective = computed<ThemeName>(() =>
    mode.value === SYSTEM_MODE ? systemTheme.value : mode.value
  )

  /** 当前生效的预设（色值 / antd 配置都在里面） */
  const preset = computed(() => THEME_PRESETS[effective.value])

  /**
   * ant-design-vue 主题。
   *
   * ⚠️ 关键：深色必须挂 `algorithm`，不能只手工设 token。
   * 只设 token 的话，antd 只会改这几项，其余数百个派生 token（各组件背景/边框/文字/
   * hover/填充/禁用态）全落在浅色默认值上 —— 于是不得不用 `html.dark .ant-* !important`
   * 去硬补（那些补丁的对手是 antd 的默认浅色，不是业务代码）。挂上 darkAlgorithm 后
   * antd 自己按算法派生整套深色 token，补丁层才可能逐块拆除。
   *
   * 算法链 = [ 打底算法, 语义色钉 ]，两段都来自预设表：
   *   第一段 `defaultAlgorithm` / `darkAlgorithm` 派生整套 token；
   *   第二段把语义色钉回本项目调色板（antd 的 seed token 无法当覆盖项用，只能这么绕，
   *   源码级原因见 presets.ts 的 DARK_PIN 注释）。
   */
  const antdTheme = computed(() => {
    const p = preset.value
    return {
      algorithm: [ALGORITHMS[p.antd.algorithm], makePinAlgorithm(p.antd.pin)],
      token: { ...p.antd.token },
      ...(p.antd.components ? { components: { ...p.antd.components } } : {}),
    }
  })

  // mode → 持久化
  watch(mode, (v) => {
    localStorage.setItem(STORAGE_KEY, v)
  })

  // effective → 应用预设到 <html>
  watch(
    effective,
    (v) => {
      const p = THEME_PRESETS[v]
      installThemeStyles() // 幂等兜底（HMR 重建样式表时也能恢复）
      document.documentElement.dataset.theme = v // → html[data-theme=x]{} 生效
      document.documentElement.classList.toggle('dark', p.isDark) // → 组件补丁层匹配
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
    preset,
    antdTheme,
    setMode,
  }
})
