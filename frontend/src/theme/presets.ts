/**
 * 主题预设表 —— 主题系统的**唯一颜色真源**。
 *
 * ★ 为什么有这个文件（背景）
 *   改造前，同一套「深色颜色值」需要人工维护在 **3 个地方**：
 *     ① App.vue `:root`（亮色基线）
 *     ② App.vue `html.dark`（深色覆盖，53 行）
 *     ③ stores/theme.ts 的 `DARK_SEMANTIC`（给 antd 用的同名值）
 *   三者必须手工保持逐字一致，加第三套主题就要把 ①②③ 各复制一遍。
 *
 * ★ 现在（本文件）
 *   - `vars`   → 业务组件的 CSS 变量（由 `installThemeStyles()` 渲染成
 *                `html[data-theme="<name>"]{...}` 一张样式表注入 `<head>`）
 *   - `antd`   → antd 组件侧的 token / 算法 / 语义色钉
 *   一个主题 = 表中一个 entry。**加第三套主题 = 加一个 entry，前端其它文件零改动**
 *   （菜单项由 `THEME_OPTIONS` 从本表派生，见文件末尾）。
 *   实测（09-13 加「马卡龙」）：前端只有本文件 + `index.html` 首屏兜底要动；
 *   另有 **2 处「用嘴换主题」链路**必须同步 —— 后端 `navigation_tools.py` 的
 *   `ThemeMode` Literal 与前端 `api/secretary.ts` 的 `mode` 类型。
 *
 * ★ 与 App.vue 的分工（两条正交的轴）
 *   - **颜色轴**（主题）→ 本文件。随主题切换。
 *   - **外观维度轴**（圆角 / 间距 / 字号 / 控件高度 / 字体栈）→ 仍是 App.vue `:root`
 *     的静态变量（圆角 / 间距 / 字号 / 字体栈）+ 本文件的 `DIMENSIONS`（antd 侧数字）。与明暗无关，
 *     换「紧凑/宽松密度」「圆角风格」只动这两处，组件零改动。
 *
 * ★ 补丁层（App.vue 里 `html.dark .xxx { ... !important }` 那一段）
 *   它按 `html.dark` 类名匹配，**不是**本表的一部分。给新主题加补丁前请先确认
 *   它是否真的需要 —— 补丁层当前正在被逐块清空（那才是「加主题不再线性增长」的前提）。
 *
 * ⚠️ 维护规则
 *   1. 改色值 → 只改本文件，不要在 App.vue 里再加 `--xxx`。
 *   2. `pin` 里的值必须与同一 entry 的 `vars` 里同名语义色**逐字一致**
 *      （`--danger` ↔ `colorError` 等），否则会出现「自定义的红 ≠ antd 的红」。
 *   3. 新增主题时 `isDark` 必须诚实填写 —— 它决定 `<html>` 挂不挂 `dark` 类，
 *      而补丁层是按 `html.dark` 匹配的。
 *
 * 生成方式：本文件由 `App.vue` 的原 `:root` / `html.dark` 块**程序化抽取**而来
 * （见 docs/theme-presets.md 的验证章节），非人工抄写。
 */

import type { MappingAlgorithm, ThemeConfig } from 'ant-design-vue/es/config-provider/context'
import type { MapToken } from 'ant-design-vue/es/theme/interface'

export type ThemeName = 'light' | 'dark' | 'macaron'

/** 「跟随系统」不是预设，是模式；菜单里与预设并列展示。 */
export const SYSTEM_MODE = 'system' as const
export type ThemeMode = ThemeName | typeof SYSTEM_MODE

/** 预设表各形态共有的字段 */
interface ThemePresetCommon {
  name: ThemeName
  /** 菜单显示名 */
  label: string
  /** 菜单图标 */
  icon: string
  /** 深色族 = true → `<html>` 挂 `dark` 类（组件补丁层按 `html.dark` 匹配） */
  isDark: boolean
  /**
   * antd 组件侧配置 —— 复用 antd 官方 `ThemeConfig` 类型（`token` / `components` 原样透传，
   * 所以写错 token 名会被 `vue-tsc` 直接拦下），只把 `algorithm` 换成 'light' | 'dark' 简写
   * （由 store 映射到 `defaultAlgorithm` / `darkAlgorithm`，本文件因此不依赖 antd 运行时）。
   */
  antd: Omit<ThemeConfig, 'algorithm'> & {
    /** 用哪个算法打底（antd 会用算法派生整套 token，不能只手工设 token） */
    algorithm: 'light' | 'dark'
    /** 算法链第二段：把语义色**钉回**本表调色板（原因见下方 DARK pin 注释） */
    pin: Record<string, string>
  }
}

/**
 * 一个主题 = 表中一个 entry。**两种形态，用判别联合把「完整性」交给编译器**：
 *
 * ① **完整表**（不写 `basedOn`）—— `vars` 必须是 `ThemeVars`，**71 个键一个都不能少**，
 *    漏写即 `vue-tsc` 报错。这类预设是其它主题的**基线**。
 * ② **差异表**（写 `basedOn: 'light' | …`）—— `vars` 只写**与基线不同的那些**，
 *    其余在 `resolveVars()` 里从基线继承。**加一套新主题就写这一种，别抄 71 行。**
 *
 * 为什么必须让编译器管这件事（而不是运行时兜底）：`html[data-theme="x"]` **不会继承**
 * `html[data-theme="y"]`（两者是并列的独立选择器），而 `App.vue :root` 只剩 2 个颜色兜底
 * —— 所以漏写一个变量不是「回落到浅色」，而是**该变量未定义**，用到它的 `var(--x)`
 * 整条声明失效（页面某处突然没颜色，且不报错）。`Record<string, string>` 拦不住这种错。
 */
export type ThemePreset =
  | (ThemePresetCommon & { vars: ThemeVars; basedOn?: undefined })
  | (ThemePresetCommon & { vars: Partial<ThemeVars>; basedOn: ThemeName })

/**
 * ④ 外观维度层（antd 侧）—— 与 App.vue `:root` 的尺寸变量一一对应，明暗共用。
 *
 * antd token 是纯数字，CSS 变量带 px，两边必须各写一份（**这是唯一允许的双写**），
 * 映射关系固定为：
 *   borderRadius    ↔ --radius-6          borderRadiusXS  ↔ --radius-2
 *   borderRadiusSM  ↔ --radius-4          borderRadiusLG  ↔ --radius-8
 *   fontSize        ↔ --font-size-14      fontSizeSM      ↔ --font-size-12
 *   fontSizeLG      ↔ --font-size-16      fontSizeXL      ↔ --font-size-20
 *
 * 当前取值 = antd 各 token 的默认值，**显式声明不改变任何渲染结果**；
 * 目的是把「换圆角风格 / 改控件密度」的入口从 antd 内部默认值收敛到这一处。
 * 想整体换紧凑密度：这一组 + App.vue 的 --space-* 一并调小即可。
 *
 * ⚠️ `controlHeight*` 三项**只在 antd 侧存在**，App.vue 里**没有**对应的 CSS 变量：
 *    antd 组件读这三项；业务组件的高度由各自 class 决定（且多数是缩略图 /
 *    分隔线 / 列表项，不是「控件」）。曾经定义过 --control-height{,-sm,-lg} 但全库
 *    零 var() 引用 —— 已删，别再加回来。
 */
export const DIMENSIONS = {
  borderRadius: 6,
  borderRadiusXS: 2,
  borderRadiusSM: 4,
  borderRadiusLG: 8,
  fontSize: 14,
  fontSizeSM: 12,
  fontSizeLG: 16,
  fontSizeXL: 20,
  controlHeight: 32,
  controlHeightSM: 24,
  controlHeightLG: 40,
} as const

/**
 * 亮色基线（= 原 App.vue `:root` 的颜色变量，逐字迁移）。
 *
 * ⚠️ 刻意**去掉** `: Record<string, string>` 注解、改用 `as const`：
 *   这样键会被推断成**字面量联合**，下方的 `ThemeVars` 才能是闭集 ——
 *   于是「完整表漏写一个变量」在 `vue-tsc` 阶段就报错，而不是运行时静默失效。
 *   本表同时是**基线**：任何 `basedOn: 'light'` 的新主题都从它展开。
 */
const LIGHT_VARS = {
  '--bg-base': '#f5f7fa',
  '--bg-elevated': '#ffffff',  // 主面板/卡片背景
  '--bg-toolbar': '#ffffff',  // header / 顶部栏
  '--bg-hover-light': '#f5f5f5',  // light 模式 hover
  '--bg-hover-dark': 'rgba(255, 255, 255, 0.06)',
  '--bg-active-light': '#e6f7ff',
  '--bg-active-dark': 'rgba(22, 119, 255, 0.18)',
  '--bg-sidebar': '#fafafa',
  '--bg-card-pill': '#f0f0f0',  // 小徽标/标签
  '--border-base': '#f0f0f0',
  '--border-strong': '#d9d9d9',
  '--text-primary': '#262626',
  '--text-secondary': '#595959',
  '--text-tertiary': '#8c8c8c',
  '--text-disabled': '#bfbfbf',
  '--text-inverse': '#ffffff',
  '--primary': '#1890ff',
  '--primary-hover': '#40a9ff',
  '--danger': '#ff4d4f',
  '--success': '#389e0d',
  '--warning': '#ad6800',
  '--purple': '#722ed1',
  /* 浅色状态底色（载入、选中 chip 等用） */
  '--success-bg': '#f6ffed',
  '--success-border': '#b7eb8f',
  '--info-bg': '#e6f7ff',
  '--info-border': '#91d5ff',
  '--purple-bg': '#f9f0ff',
  '--purple-border': '#efdbff',
  '--warning-bg': '#fffbe6',
  '--warning-border': '#ffe58f',
  '--danger-bg': '#fff1f0',  // red-1；此前被 var(--danger-bg) 引用却从未定义 → 该处底色一直是透明
  '--danger-border': '#ffccc7',  // red-2
  '--primary-strong': '#0958d9',  // blue-7
  '--warning-strong': '#d48806',  // gold-7
  '--danger-strong': '#cf1322',  // red-7；⚠️ 深档文字**不要**用 --danger(#ff4d4f)，白底仅 3.3:1
  '--danger-border-strong': '#ffa39e',  // red-3，风险区边框
  '--orange-bg': '#fff7e6',  // orange-1
  '--orange-bg-2': '#ffe7ba',  // orange-2
  '--orange-border': '#ffd591',  // orange-3
  '--orange-strong': '#d46b08',  // orange-7，暖色强调**文字**（白底可读；比 --warning-strong 更偏橙）
  '--info-bg-2': '#d6e4ff',  // blue-2，渐变第二档
  '--success-bg-2': '#d9f7be',  // green-2
  '--bg-raised': '#ffffff',  // 比 --bg-elevated 再浮起一档的卡片底（深色下 = #262626）
  '--shadow-overlay': '0 8px 28px rgba(0, 0, 0, 0.14)',
  '--shadow-card': 'none',  // 深色下结果卡才有投影，浅色保持无
  '--danger-hover-bg': 'rgba(255, 77, 79, 0.08)',
  '--accent-pink': '#f5576c',  // 主强调：左边条 / 序号球 / 强调文字
  '--accent-pink-2': '#f093fb',  // 头部渐变起点（紫粉）
  '--accent-pink-soft': 'rgba(245, 87, 108, 0.1)',  // focus 光圈
  '--bo-header-bg': 'linear-gradient(135deg, #667eea 0%, #764ba2 100%)',
  '--bo-header-shadow': 'none',
  '--surface-ring': 'none',  // 深色下才用的 1px 内描边（浅色保持无）
  '--stat-bar-opacity': '0',

  /* ===== 业务语义色（与 utils/colorSemantics.ts 的语义名一一对应）===== */
  '--cyan': '#08979c',          // 青 —— 平台 / 渠道分类（cyan-7，白底达 AA）
  '--gold': '#d48806',          // 金 —— 星级 / 排名第一（gold-7）
  /* 下面两组是「antd Tag 色名映射层」（styles/antd-tag-tokens.css）需要的三元组：
     项目原本只有 --cyan / 只有 gold 系，缺「底 + 边框」两档。
     浅色值取 antd 原色板（cyan-1/3、geekblue-1/3/7），**故浅色零变化**。 */
  '--cyan-bg': '#e6fffb',       // cyan-1
  '--cyan-border': '#87e8de',   // cyan-3
  '--geekblue': '#1d39c4',      // geekblue-7 —— 店铺/账号类标签
  '--geekblue-bg': '#f0f5ff',   // geekblue-1
  '--geekblue-border': '#adc6ff', // geekblue-3

  /* ===== 图表调色板（多序列区分色，8 档；深色档整体提亮）===== */
  '--chart-1': '#5b8ff9',       // 蓝
  '--chart-2': '#5ad8a6',       // 绿
  '--chart-3': '#f6bd16',       // 黄
  '--chart-4': '#e8684a',       // 橙红
  '--chart-5': '#9270ca',       // 紫
  '--chart-6': '#269a99',       // 青
  '--chart-7': '#eb2f96',       // 品红
  '--chart-8': '#fa8c16',       // 橙

  /* ===== 排名 / 奖牌色（金银铜，物质色不随主题明暗翻转）===== */
  '--rank-1': '#faad14',        // 金
  '--rank-2': '#d9d9d9',        // 银
  '--rank-3': '#cd7f32',        // 铜
} as const

/** 变量名闭集 —— 由基线表推导，所以「漏一个」是**编译错误**而非运行时静默失效 */
export type ThemeVarName = keyof typeof LIGHT_VARS
/** 一套**完整**的主题变量表（71 个键，一个都不能少） */
export type ThemeVars = Record<ThemeVarName, string>

/** 深色覆盖（= 原 App.vue `html.dark` 的颜色变量，逐字迁移） */
const DARK_VARS: ThemeVars = {
  '--bg-base': '#141414',
  '--bg-elevated': '#1f1f1f',
  '--bg-toolbar': '#141414',
  '--bg-hover-light': 'rgba(255, 255, 255, 0.06)',
  '--bg-hover-dark': 'rgba(255, 255, 255, 0.06)',
  '--bg-active-light': 'rgba(22, 119, 255, 0.18)',
  '--bg-active-dark': 'rgba(22, 119, 255, 0.18)',
  '--bg-sidebar': '#141414',
  '--bg-card-pill': '#262626',
  '--border-base': '#303030',
  '--border-strong': '#434343',
  '--text-primary': 'rgba(255, 255, 255, 0.92)',
  '--text-secondary': 'rgba(255, 255, 255, 0.65)',
  '--text-tertiary': 'rgba(255, 255, 255, 0.45)',
  '--text-disabled': 'rgba(255, 255, 255, 0.25)',
  '--text-inverse': '#1f1f1f',
  '--primary': '#177ddc',
  '--primary-hover': '#3d9be6',
  '--danger': '#ff7875',
  '--success': '#73d13d',
  '--warning': '#ffc53d',
  '--purple': '#b37feb',
  /* 深色状态底色（半透明品牌色，深底自然融合） */
  '--success-bg': 'rgba(82, 196, 26, 0.12)',
  '--success-border': 'rgba(82, 196, 26, 0.4)',
  '--info-bg': 'rgba(24, 144, 255, 0.12)',
  '--info-border': 'rgba(24, 144, 255, 0.4)',
  '--purple-bg': 'rgba(114, 46, 209, 0.12)',
  '--purple-border': 'rgba(114, 46, 209, 0.4)',
  '--warning-bg': 'rgba(250, 173, 20, 0.12)',
  '--warning-border': 'rgba(250, 173, 20, 0.4)',
  '--danger-bg': 'rgba(255, 77, 79, 0.12)',
  '--danger-border': 'rgba(255, 77, 79, 0.4)',
  '--primary-strong': '#3d9be6',
  '--warning-strong': '#ffc53d',
  '--danger-strong': '#ff7875',
  '--orange-strong': '#ffa940',
  '--danger-border-strong': 'rgba(255, 77, 79, 0.45)',
  '--orange-bg': 'rgba(250, 173, 20, 0.16)',
  '--orange-bg-2': 'rgba(250, 173, 20, 0.05)',
  '--orange-border': 'rgba(250, 173, 20, 0.4)',
  '--info-bg-2': 'rgba(24, 144, 255, 0.05)',
  '--success-bg-2': 'rgba(82, 196, 26, 0.05)',
  '--bg-raised': '#262626',
  '--shadow-overlay': '0 8px 28px rgba(0, 0, 0, 0.5)',
  '--shadow-card': '0 4px 16px rgba(0, 0, 0, 0.5)',
  '--danger-hover-bg': 'rgba(255, 77, 79, 0.18)',
  '--accent-pink': '#ff7a90',
  '--accent-pink-2': '#f093fb',
  '--accent-pink-soft': 'rgba(245, 87, 108, 0.18)',
  '--bo-header-bg': 'linear-gradient(135deg, #4338a6 0%, #6b21a8 50%, #7c3aed 100%)',
  '--bo-header-shadow': '0 2px 12px rgba(124, 58, 237, 0.25)',
  '--surface-ring': 'inset 0 0 0 1px rgba(255, 255, 255, 0.04)',
  '--stat-bar-opacity': '1',

  /* ===== 业务语义色 ===== */
  '--cyan': '#5cdbd3',          // 青（cyan-4，深底提亮）
  '--gold': '#ffc53d',          // 金（gold-5）
  /* 与浅色同名（同样是 Tag 色名映射层用的三元组）：半透明底 + 边框，文字用提亮档 */
  '--cyan-bg': 'rgba(19, 194, 194, 0.12)',      // cyan-6 半透明
  '--cyan-border': 'rgba(19, 194, 194, 0.4)',
  '--geekblue': '#85a5ff',      // geekblue-5（深底提亮）
  '--geekblue-bg': 'rgba(29, 57, 196, 0.12)',   // geekblue-6 半透明
  '--geekblue-border': 'rgba(29, 57, 196, 0.4)',

  /* ===== 图表调色板（深色档：整体提亮 1-2 档，解决深底对比度不足）===== */
  '--chart-1': '#7db3ff',
  '--chart-2': '#7ee0c0',
  '--chart-3': '#ffd666',
  '--chart-4': '#ff9d7a',
  '--chart-5': '#b79bf0',
  '--chart-6': '#5cdbd3',
  '--chart-7': '#ff85c0',
  '--chart-8': '#ffb066',

  /* ===== 排名 / 奖牌色（深色下金档提亮，银铜保持物质色）===== */
  '--rank-1': '#ffc53d',
  '--rank-2': '#d9d9d9',
  '--rank-3': '#cd7f32',
}

/**
 * 深色语义色钉住层 —— 让「antd 组件的颜色」与「自定义 CSS 的 CSS 变量」是同一套值。
 *
 * 为什么需要它（antd 的一个坑，源码级）：
 *   seed token 里的 `colorPrimary / colorSuccess / colorWarning / colorError / colorInfo /
 *   colorBgBase / colorTextBase`（+ 13 个预置色名）**无法通过 `theme.token` 覆盖**。
 *   `theme/util/alias.js` 的 `formatToken()` 会把用户 token 里的 seed key 全部 delete 掉：
 *     Object.keys(seedToken).forEach(k => delete overrideTokens[k])
 *   也就是说 seed 只当**算法输入**、不当覆盖项 —— 于是 darkAlgorithm 会把
 *   `#177ddc` 重新派生成更深的 `#176dbe`、`#ff7875` → `#dc4446`、`#73d13d` → `#49aa19`、
 *   `#ffc53d` → `#d89614`（v5 暗色盘）。
 *   而本表 dark 的 `--primary/--danger/--success/--warning` 是另一套（v4 暗色盘 =
 *   亮色盘的中间步，专为深底可读性选的）。两套并存就会出现「自定义的红 ≠ antd 的红」
 *   —— radio 选中、输入框聚焦边框、表单报错文字等 6 处微差。
 *
 * 解法（antd 官方支持的算法链）：
 *   `algorithm` 接受**数组**，前一个算法的输出会喂给后一个
 *   （`Theme.getDerivativeToken` = `derivatives.reduce((r, d) => d(token, r))`），
 *   且算法**返回值**不受上面的 seed 删除影响。所以把语义色钉回本表调色板即可。
 *
 * ⚠️ 下面的值必须与本表 `vars` 里的同名 CSS 变量**逐字一致**（`--danger` ↔ `colorError`）。
 *    方向说明：本项目采用「深底可读」的调色板（v4 暗色盘），例如 `--danger: #ff7875`
 *    在 #1f1f1f 上对比度约 7:1；若改成 antd 派生的 #dc4446 会掉到约 4.3:1（低于 AA）。
 */

const DARK_PIN: Record<string, string> = {
  colorPrimary: '#177ddc', // = vars --primary
  colorPrimaryHover: '#3d9be6', // = vars --primary-hover
  colorPrimaryText: '#177ddc',
  colorPrimaryTextHover: '#3d9be6',
  colorError: '#ff7875', // = vars --danger
  colorErrorText: '#ff7875',
  colorErrorHover: '#ff7875',
  colorSuccess: '#73d13d', // = vars --success
  colorSuccessText: '#73d13d',
  colorWarning: '#ffc53d', // = vars --warning
  colorWarningText: '#ffc53d',
  // ⚠️ 唯一连带项：`alias.js:55` 里 colorHighlight = colorError，
  // 所以上面对 colorError 的钉住会顺带把「Cascader 搜索命中文字」的红色也换成 --danger。
  // 该 token 全局只被 cascader 的 `&-keyword { color }` 用到，变亮 = 更易读，故有意保留。
}

/**
 * 亮色语义色钉住层 —— 与 dark 同一机制、同一方向（把 antd 钉回本项目调色板）。
 *
 * 亮色下只有 success / warning 两家需要钉（实测 defaultAlgorithm 输出 vs `:root` 变量）：
 *   primary  : antd `colorPrimary`        = #1890ff = `--primary`        ✓ 本来就一致
 *   hover    : antd `colorPrimaryHover`   = #40a9ff = `--primary-hover`  ✓ 本来就一致
 *   danger   : antd `colorError`          = #ff4d4f = `--danger`         ✓ 本来就一致
 *   success  : antd `colorSuccess`        = #52c41a ≠ `--success` #389e0d ✗
 *   warning  : antd `colorWarning`        = #faad14 ≠ `--warning` #ad6800 ✗
 * （antd seed 默认 primary 其实是 #1677ff，而本项目把 seed 设成 #1890ff，
 *   这才让 primary 家族恰好落在 v4 蓝色盘上 —— 属于巧合式的对齐，钉子没覆盖，改动时注意。）
 *
 * 为什么是「钉 antd」而不是「改 CSS 变量」：`--success #389e0d`(green-7) / `--warning #ad6800`(gold-7)
 * 是**刻意为白底文字选的深一档**。对比度实测：green-7 3.5:1 vs antd green-6 仅 2.3:1；
 * gold-7 4.5:1（达 AA）vs antd gold-6 仅 1.9:1。且 `--success`/`--warning` 被大量业务 CSS
 * 当**文字色**用（`.num.up`、评分色、FAQ 状态等），倒向 antd 会让全局文字变浅、更难读；
 * 而 antd 侧的影响面只有「alert 图标 / badge 圆点 / form 校验文字 / message 图标 /
 * 日期与输入框警告边框」这几处**前景色**。
 *
 * ⚠️ 故意**不**钉 `colorSuccessHover/WarningHover`：那两个槽位在 antd-vue 里无任何组件使用，
 *    但若钉住会与 base 同值、丢掉 hover 层次；`colorSuccessText/WarningText` 虽同样无人使用，
 *    为与 dark 保持结构对称而一并钉住（零副作用）。
 */

/**
 * 马卡龙配色 —— **差异表**（`basedOn: 'light'`），只写与亮色基线**不同**的键，
 * 其余（状态**字色** / 分类色字色 / 奖牌色 / 反白色 / 深色语境色）全部继承 `LIGHT_VARS`。
 * 这是 `basedOn` 机制的**第一个真实用户**：没有它就得把这 71 行抄一遍。
 *
 * ★ 设计取向：马卡龙的「甜」来自**大面积暖粉底 + 柔化的粉彩状态底 + 树莓主色**。
 *   因此本表**刻意不动状态字色**（`--success` / `--danger` / `--warning` / `--*-strong`）——
 *   那些是「功能色」，柔化会直接掉对比度（`--success #389e0d` 在白底 3.5:1 已是为可读性
 *   刻意选的深一档，见 LIGHT_PIN 上方注释）。**改底不改字**：观感甜了，可读性不降。
 *
 * ★ `--primary` 取值有硬约束：它是 antd 的 `colorPrimary` seed → **主按钮底色 + 白字**。
 *   马卡龙粉色若选得过浅（如 #f5a3c7）白字对比只有 1.9:1，主按钮会糊。
 *   故取 **树莓 #c9407c（白字 4.66:1 ✅ AA）**，仍属马卡龙色域，但可承载文字。
 *
 * ★ `--primary-strong` 故意**不覆盖**：它与 `--primary` 是**两条链路** ——
 *   `--primary-strong` 是「蓝底 tag 的文字」（`styles/antd-tag-tokens.css` 里
 *   `.ant-tag-blue` 的 color），配的是 `--info-bg`。本表只把 blue 的**底/边**柔化成
 *   粉彩蓝，字仍是继承来的 `#0958d9`。若连字一起改粉 → 粉字配蓝底。
 */
const MACARON_VARS: Partial<ThemeVars> = {
  /* —— 背景层：暖粉奶油白（马卡龙的暖调来自底色，不在纯白上做文章）—— */
  '--bg-base': '#fdf6f8',       // 页面底：极淡粉白
  '--bg-toolbar': '#fffbfc',    // 顶栏：比页面底再亮半档
  '--bg-sidebar': '#faf0f4',    // 侧栏：粉调最明显的一层
  '--bg-card-pill': '#f7e9ef',  // 小徽标/标签底
  '--bg-hover-light': '#f9edf2',// hover 底（原冷灰 #f5f5f5 → 暖粉灰）
  '--bg-active-light': '#fce4ee', // 选中态底（原淡蓝 #e6f7ff → 粉，与主色同族）

  /* —— 边框：粉调灰（原 #f0f0f0/#d9d9d9 是中性灰，会与暖底「脏」在一起）—— */
  '--border-base': '#f3e3ea',
  '--border-strong': '#e6d2dc',

  /* —— 文字：暖褐（关键一笔）——
     冷灰 #262626 放在粉底上会显脏；换成同明度的暖褐，整体才「甜」而不「灰」。
     对比度实测：#4a3b42 on #fdf6f8 ≈ 8.6:1 ✅ AAA；#7d6a72 ≈ 4.6:1 ✅ AA。 */
  '--text-primary': '#4a3b42',
  '--text-secondary': '#7d6a72',
  '--text-tertiary': '#a8949c',
  '--text-disabled': '#cfc0c6',

  /* —— 主色：树莓 ——
     ⚠️ 取值有**两条**对比度硬约束（实测）：
       · 对白字 ≥4.5:1 —— antd 主按钮底色是它，白字要看得见；
       · 对页面底（--bg-base）≥4.5:1 —— 它同时是链接/强调**文字色**。
     #c9407c 只满足第一条（白字 4.66 ✅ / 对底 4.37 ✗），故加深到
     #c33a76：白字 5.01:1 ✅ / 对底 4.71:1 ✅，两条都过 AA。 */
  '--primary': '#c33a76',
  '--primary-hover': '#d85f91',

  /* —— 强调 / 装饰 —— */
  '--accent-pink': '#e86a9a',                    // 左边条 / 序号球：更亮的马卡龙粉
  '--accent-pink-2': '#c9a7f0',                  // 头部渐变起点：改薰衣草（原 #f093fb 偏艳）
  '--accent-pink-soft': 'rgba(232, 106, 154, 0.12)', // focus 光圈
  '--bo-header-bg': 'linear-gradient(135deg, #f5a3c7 0%, #b58ce0 100%)', // 蓝海结果卡头：粉→薰衣草
  '--shadow-overlay': '0 8px 28px rgba(186, 106, 145, 0.18)', // 阴影带粉调（中性黑阴影在粉底上发灰）

  /* —— 状态底 / 边框：全部粉彩化（字色不动，见文件头「设计取向」）—— */
  '--success-bg': '#eefaf1',
  '--success-border': '#bfe6c8',
  '--success-bg-2': '#d6f2de',
  '--info-bg': '#eef3fd',        // 柔化蓝（原 #e6f7ff 偏饱和）
  '--info-border': '#c9d4f5',
  '--info-bg-2': '#dde5fa',
  '--purple-bg': '#f5eefd',
  '--purple-border': '#dcc7f5',
  '--warning-bg': '#fff9ea',
  '--warning-border': '#ffe3a8',
  '--danger-bg': '#fdeef2',
  '--danger-border': '#f7c7d4',
  '--orange-bg': '#fff6ee',
  '--orange-bg-2': '#ffe5d1',
  '--orange-border': '#ffd2ab',

  /* —— 分类色底（cyan=平台 / geekblue=店铺账号；字色继承）—— */
  '--cyan-bg': '#eafaf8',
  '--cyan-border': '#b3e4de',
  '--geekblue-bg': '#eff0fd',
  '--geekblue-border': '#c6cbf0',

  /* —— 图表调色板：8 色整体降饱和提亮（原色板是数据可视化常用的中饱和色，
     放在马卡龙底上会「吵」；换粉彩系后多序列仍可区分 —— 相邻色相间隔 ≥ 40°）—— */
  '--chart-1': '#7ba7f7',  // 柔天蓝
  '--chart-2': '#7ed6a5',  // 薄荷
  '--chart-3': '#f5c95c',  // 奶油黄
  '--chart-4': '#f79a86',  // 珊瑚
  '--chart-5': '#a78bda',  // 薰衣草
  '--chart-6': '#6cc5c6',  // 柔青
  '--chart-7': '#ef8cba',  // 樱花粉
  '--chart-8': '#f7b26a',  // 杏橙
}

const LIGHT_PIN: Record<string, string> = {
  colorSuccess: '#389e0d', // = vars --success
  colorSuccessText: '#389e0d',
  colorWarning: '#ad6800', // = vars --warning
  colorWarningText: '#ad6800',
}

export const THEME_PRESETS: Record<ThemeName, ThemePreset> = {
  light: {
    name: 'light',
    label: '浅色',
    icon: '☀️',
    isDark: false,
    vars: LIGHT_VARS,
    antd: {
      algorithm: 'light',
      pin: LIGHT_PIN,
      token: {
        // ④ 尺寸层：圆角 / 字号 / 控件高度（明暗同值，改密度只需动这一处）
        ...DIMENSIONS,
        // ⚠️ 这是 **seed**：只作 defaultAlgorithm 的输入（派生 colorPrimaryBg/Border/Active 等色阶）。
        // 本项目用 v4 蓝 #1890ff（antd 默认 seed 是 v5 蓝 #1677ff），因此整个 primary 色阶
        // 都落在 v4 蓝色盘上，正好等于 `:root --primary` / `--primary-hover`，无需钉住。
        colorPrimary: '#1890ff',
      },
    },
  },
  dark: {
    name: 'dark',
    label: '深色',
    icon: '🌙',
    isDark: true,
    vars: DARK_VARS,
    antd: {
      // ★ 算法链：darkAlgorithm 先派生整套暗色 token，再用 DARK_PIN
      // 把 4 个语义色钉回本项目调色板（原因见 DARK_PIN 上方注释）。
      algorithm: 'dark',
      pin: DARK_PIN,
      token: {
        // ④ 尺寸层：圆角 / 字号 / 控件高度（明暗同值，改密度只需动这一处）
        ...DIMENSIONS,
        // ⚠️ 这是 **seed**：只作 darkAlgorithm 的输入（派生 colorPrimaryBg/Border/Active 等色阶），
        // 它本身**不会**成为渲染值（seed key 会被 formatToken 从覆盖项里删掉）。
        // 最终渲染的 colorPrimary 由 DARK_PIN 钉住 = #177ddc。
        colorPrimary: '#177ddc',
        colorBgBase: '#141414',
        colorBgContainer: '#1f1f1f',
        colorBgLayout: '#1f1f1f', // 原 #000000；对齐 .ant-layout 补丁的 #1f1f1f
        colorBgElevated: '#1f1f1f', // 派生默认 #333333；对齐浮层类补丁（下拉/弹窗/抽屉/气泡/Tooltip 底）
        colorBgMask: 'rgba(0, 0, 0, 0.65)', // 派生默认 0.45；对齐 Modal/Drawer 遮罩补丁
        colorText: 'rgba(255, 255, 255, 0.92)', // 原 0.85；对齐 App.vue 的 --text-primary，消掉约 18 处文字色差异
        colorTextSecondary: 'rgba(255, 255, 255, 0.65)',
        colorTextTertiary: 'rgba(255, 255, 255, 0.45)',
        colorTextPlaceholder: 'rgba(255, 255, 255, 0.45)', // 派生默认 0.25；对齐 placeholder/占位图标补丁
        colorBorder: '#303030',
        colorBorderSecondary: '#303030',
        colorSplit: '#303030', // 派生默认 rgba(244,244,244,0.08)；对齐 Divider / Picker 分隔线补丁
        // 选中态 / hover 态底色：与 App.vue 的 --bg-active-dark / --bg-hover-dark 对齐
        // （派生默认 controlItemBgActive 是比浮层更暗的 #111b26，选中项几乎看不出来）
        controlItemBgActive: 'rgba(22, 119, 255, 0.18)',
        controlItemBgHover: 'rgba(255, 255, 255, 0.06)',
      },
      components: {
        Layout: {
          colorBgHeader: '#1f1f1f', // antd Layout 默认硬编码 #001529（深蓝），深色下必须显式改
          colorBgBody: '#1f1f1f',
        },
        // 以下是把原补丁层的「刻意设计值」搬进 token，保持视觉不变（如不认可可整条删除）
        Input: { colorBgContainer: '#262626' }, // 输入框底比面板亮一档，保证输入区有可辨识度
        Button: { colorTextDisabled: 'rgba(255, 255, 255, 0.65)' }, // 深色下原生 disabled 文字太暗（0.25）
        Typography: { colorText: 'rgba(255, 255, 255, 0.65)' },
      },
    },
  },
  macaron: {
    name: 'macaron',
    label: '马卡龙',
    icon: '🧁',
    // 浅色族 → 不挂 `dark` 类 → 不命中 App.vue 的 `html.dark .xxx !important` 补丁层。
    // ⚠️ 新主题接入时**第一件**要确认的就是这行：写错会让整套浅色配色被深色补丁覆盖。
    isDark: false,
    // ★ 差异表的关键一行：写它 = `vars` 只写差异、其余从 light 继承（否则 vue-tsc 报
    //   TS2322「Property 'basedOn' is missing」—— 本行曾被漏写并当场被编译器拦下）。
    basedOn: 'light',
    vars: MACARON_VARS,
    antd: {
      // 与 light 同算法（都是浅色族），差异全在下面的 token。
      algorithm: 'light',
      // 语义色钉**原样复用** LIGHT_PIN —— 本表没改 `--success` / `--warning`
      // （它们是功能色，见 MACARON_VARS 上方注释），复用才能保证
      // 「自定义色的绿/黄」与「antd 的绿/黄」继续逐字一致（presets.ts 维护规则 2）。
      pin: LIGHT_PIN,
      token: {
        ...DIMENSIONS,
        // seed token：派生整套粉色阶（hover / active / bg / border），
        // 最终渲染的 colorPrimary 就等于它 = vars `--primary`（**必须逐字一致**）。
        colorPrimary: '#c33a76',
        // 区域底色 —— 与 vars 的背景层逐字对齐（否则 antd 组件会露出中性灰底）
        colorBgLayout: '#fdf6f8', // = --bg-base
        colorBgContainer: '#ffffff', // = --bg-elevated
        colorBgElevated: '#ffffff', // = --bg-raised
        // 文字 —— 与 vars 文字层对齐（antd 默认是冷灰 #262626 系，在粉底上显脏）
        colorText: '#4a3b42', // = --text-primary
        colorTextSecondary: '#7d6a72', // = --text-secondary
        colorTextTertiary: '#a8949c', // = --text-tertiary
        colorTextPlaceholder: '#a8949c',
        // 边框 / 分隔线 —— 与 vars 边框层对齐
        colorBorder: '#e6d2dc', // = --border-strong
        colorBorderSecondary: '#f3e3ea', // = --border-base
        colorSplit: '#f3e3ea', // 派生默认是中性灰；对齐 Divider / Picker 分隔线
        // 选中 / hover 底 —— 与 vars 同族（派生默认是蓝色系，与粉主色不搭）
        controlItemBgActive: '#fce4ee', // = --bg-active-light
        controlItemBgHover: '#f9edf2', // = --bg-hover-light
        colorLink: '#c33a76', // 链接跟随主色（派生默认取 colorPrimary，显式化以免将来算法变动）
      },
      components: {
        // antd Layout 的 header 默认硬编码 #001529（深蓝），任何非默认主题都要显式改
        Layout: { colorBgHeader: '#fffbfc', colorBgBody: '#fdf6f8' },
      },
    },
  },
}

/**
 * 把 `basedOn` 链展开成**完整**变量表（差异表 → 基线 + 自己的覆盖）。
 *
 * - 不写 `basedOn` 的预设直接返回自身 —— 现网的 light / dark 都走这条，**零行为变化**。
 * - 带 `basedOn` 的预设先递归取基线，再叠加自己的 `vars`。
 * - **循环检测**：`basedOn` 成环时抛错，而不是无限递归（配置错误要早暴露）。
 * - ⚠️ 消费端一律读本函数，**不要直读 `preset.vars`** —— 后者对差异表只是「差异部分」。
 */
export function resolveVars(name: ThemeName, _chain: ThemeName[] = []): ThemeVars {
  const preset = THEME_PRESETS[name]
  if (!preset.basedOn) return preset.vars
  if (_chain.includes(name)) {
    throw new Error(`[theme] basedOn 成环：${[..._chain, name].join(' → ')}`)
  }
  return { ...resolveVars(preset.basedOn, [..._chain, name]), ...preset.vars }
}

/** 默认主题（`localStorage` 无值或不认识时用它） */
export const DEFAULT_THEME: ThemeName = 'light'

/**
 * 菜单选项 —— **从预设表派生**，所以「加第三套主题」不用改任何 UI 文件。
 * AccountMenu.vue 直接 `v-for="opt in THEME_OPTIONS"`。
 */
export const THEME_OPTIONS: { icon: string; label: string; value: ThemeMode }[] = [
  ...Object.values(THEME_PRESETS).map((p) => ({ icon: p.icon, label: p.label, value: p.name })),
  { icon: '💻', label: '跟随系统', value: SYSTEM_MODE },
]

/** 模式 → 显示名（浅色 / 深色 / 马卡龙 / 跟随系统；预设名从表里取，只有「跟随系统」需硬写） */
export function themeModeLabel(mode: ThemeMode): string {
  if (mode === SYSTEM_MODE) return '跟随系统'
  return THEME_PRESETS[mode]?.label ?? mode
}

/** 把预设表里的 `pin` 变成 antd 算法链的第二段。 */
export function makePinAlgorithm(pin: Record<string, string>): MappingAlgorithm {
  return (_seedToken, mapToken) => ({
    ...((mapToken ?? {}) as MapToken),
    ...(pin as unknown as MapToken),
  })
}

/**
 * 生成并注入主题变量样式表：`html[data-theme="<name>"] { --x: y; ... }`
 *
 * 变量取自 **`resolveVars()`**（已展开 `basedOn`）—— 差异表主题也能注入完整的 71 个变量。
 *
 * 为什么用样式表而不是逐个 `style.setProperty`：
 *   - 与改造前 `html.dark { ... }` 的**特异性完全一致**（都是 (0,1,1)），
 *     且两个主题的选择器互斥 → 级联结果可逐字节预期，是「零视觉变化」的前提；
 *   - 切换主题只剩「改一个属性」（见 store），没有 53 次 DOM 写入。
 *
 * 特异性说明：`html[data-theme=x]` = (0,1,1) > `:root` = (0,1,0)，
 * 所以它与 App.vue 里静态 `:root` 的先后顺序**不影响**结果。
 *
 * @param doc 便于测试注入
 */
export const THEME_STYLE_ID = 'ai-theme-presets'

export function installThemeStyles(doc: Document = document): void {
  if (doc.getElementById(THEME_STYLE_ID)) return
  const css = Object.values(THEME_PRESETS)
    .map((p) => {
      const body = Object.entries(resolveVars(p.name))
        .map(([k, v]) => `  ${k}: ${v};`)
        .join('\n')
      return `html[data-theme="${p.name}"] {\n${body}\n}`
    })
    .join('\n\n')
  const el = doc.createElement('style')
  el.id = THEME_STYLE_ID
  el.dataset.source = 'src/theme/presets.ts'
  el.textContent = css
  doc.head.appendChild(el)
}
