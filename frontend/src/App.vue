<template>
  <a-config-provider :locale="zhCN" :theme="themeStore.antdTheme">
    <router-view />
  </a-config-provider>
</template>

<script setup lang="ts">
import zhCN from 'ant-design-vue/es/locale/zh_CN'
import { useThemeStore } from '@/stores/theme'

const themeStore = useThemeStore()
</script>

<style>
/* 全局样式 */
* {
  margin: 0;
  padding: 0;
  box-sizing: border-box;
}

html, body, #app {
  width: 100%;
  height: 100%;
  font-family: var(--font-sans);
  background-color: var(--bg-base);
  color: var(--text-primary);
  transition: background-color 0.2s, color 0.2s;
}

/* ====== 全局 CSS 变量 ==========================================================
   本文件**只保留两类**变量：
     ① 首屏兜底（2 个）—— JS 注入预设表之前的第一帧用，避免白闪；
     ② 外观维度层（圆角 / 间距 / 字号 / 字体栈）—— 与明暗无关。

   ★ 颜色轴（随主题切换的那 53 个）已迁到唯一真源 **src/theme/presets.ts**，
     由 themeStore 运行时注入 `html[data-theme="light|dark"] { ... }`。
     ⚠️ 不要在下面再写颜色变量 —— 那会让「加一套主题要改 N 处」的老问题复活。
     改色值 → 改 presets.ts；换圆角/密度/字号 → 改本文件的 ②。
   ============================================================================ */
:root {
  /* ---- ① 首屏兜底：JS 注入预设表前，第一帧按浅色基线渲染（完整色值见 src/theme/presets.ts）---- */
  --bg-base: #f5f7fa;
  --text-primary: #262626;

  /* ================================================================
     ④ 外观维度层（圆角 / 间距 / 字号 / 控件高度 / 字体栈）
     命名规则：**后缀数字 = 像素值**，`--radius-8` 就是 8px，便于脚本按字面量批量收敛。
     换「圆角风格」「紧凑 / 宽松密度」只改这一组，组件侧无需改动；
     与 antd 的对应关系见 src/theme/presets.ts 的 DIMENSIONS（borderRadius / fontSize 等）。
     本层与颜色无关，故只在 :root 定义一次，不随明暗切换。
     ================================================================ */
  /* 圆角 */
  --radius-2: 2px;   --radius-3: 3px;   --radius-4: 4px;   --radius-6: 6px;
  --radius-8: 8px;   --radius-10: 10px; --radius-12: 12px; --radius-14: 14px;
  --radius-16: 16px; --radius-20: 20px;
  --radius-15: 15px;       /* 非 2 倍数档：项目已在用（ChatPanel 主容器），保留原值 */
  --radius-circle: 50%;    /* 正圆（仅「无限大圆角」这一种语义；曾经的 --radius-pill 全库零引用，已删）*/
  /* 间距（padding / margin / gap） */
  --space-1: 1px;    --space-2: 2px;    --space-3: 3px;    --space-4: 4px;
  --space-5: 5px;    --space-6: 6px;    --space-8: 8px;    --space-10: 10px;
  --space-12: 12px;  --space-14: 14px;  --space-16: 16px;  --space-18: 18px;
  --space-20: 20px;  --space-24: 24px;
  /* 非 4 倍数档：项目实测已在用的值，补进刻度以保证「脚本可全覆盖、零视觉变化」。
     后续若要收紧密度，这些是优先归并对象（7→8 / 9→8 / 11→12 / 13→12）。 */
  --space-7: 7px;    --space-9: 9px;    --space-11: 11px;  --space-13: 13px;
  --space-22: 22px;  --space-28: 28px;  --space-30: 30px;  --space-40: 40px;
  --space-44: 44px;
  /* 字号 */
  --font-size-9: 9px;      --font-size-10: 10px;   --font-size-10-5: 10.5px;
  --font-size-11: 11px;    --font-size-11-5: 11.5px;
  --font-size-12: 12px;    --font-size-12-5: 12.5px;
  --font-size-13: 13px;    --font-size-13-5: 13.5px;
  --font-size-14: 14px;    --font-size-15: 15px;   --font-size-16: 16px;
  --font-size-17: 17px;    --font-size-18: 18px;   --font-size-20: 20px;
  --font-size-22: 22px;    --font-size-24: 24px;   --font-size-26: 26px;
  --font-size-28: 28px;    --font-size-32: 32px;   --font-size-36: 36px;
  --font-size-48: 48px;    /* 空状态大图标 */
  /* 控件高度：**刻意不在此定义** —— 一律由 antd token 驱动
     （见 src/theme/presets.ts 的 DIMENSIONS）。
     曾经的 --control-height{,-sm,-lg} 全库零 var() 引用；而本项目 24/32/40px 的
     高度硬编码绝大多数语义是缩略图 / 分隔线 / 列表项（**不是「控件」**）
     —— 接进来只会让人误以为「改这个变量就能换密度」。别再加回来。 */
  /* 字体栈 */
  --font-sans: -apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto,
    'Helvetica Neue', Arial, 'Noto Sans', sans-serif, 'Apple Color Emoji',
    'Segoe UI Emoji', 'Segoe UI Symbol', 'Noto Color Emoji';
  --font-mono: ui-monospace, SFMono-Regular, 'SF Mono', Menlo, Consolas,
    'Liberation Mono', monospace;
}

html.dark,
html.dark body,
html.dark #app {
  background-color: var(--bg-base);
  color: var(--text-primary);
}

/* ====== 深色补丁层：已清空（P6，2026-09-13）===============================
   这里曾按 `html.dark <类名> { ... !important }` 覆盖各组件里写死的浅色值。
   随着组件侧全部改为 var() 语义 token，覆盖不再需要 —— 深色档由
   src/theme/presets.ts 提供（html[data-theme="dark"]），组件直接读自己的
   var()，颜色语义（红=风险 / 绿=利好 / 橙=预警 / 蓝=信息）在深色下同样成立。

   ★ 不要在这里再加规则。若深色下某处颜色不对，说明那个组件的样式没用
     var()，请去组件里改 —— 全局补丁会让「加一套新主题」的成本随主题数量
     线性增长（这正是本段被清空的原因）。
   ======================================================================== */

/* ====== 滚动条（全局，与主题无关；深色下 --border-strong 自动变浅） ====== */
::-webkit-scrollbar {
  width: 6px;
  height: 6px;
}

::-webkit-scrollbar-thumb {
  background-color: var(--border-strong);
  border-radius: var(--radius-3);
}

::-webkit-scrollbar-track {
  background-color: transparent;
}

</style>
