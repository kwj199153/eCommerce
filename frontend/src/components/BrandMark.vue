<template>
  <!--
    店管管 图形标识 ——「店招」。

    几何（48×48 网格，**全仓唯一真源**）：
      檐  M11.7 8.4 H36.3 Q37.9 8.4 38.7 10.5 L41 15.4
          a5.667 3.3 0 0 1 -11.333 0 a5.667 3.3 0 0 1 -11.333 0
          a5.667 3.3 0 0 1 -11.333 0 L9.3 10.5 Q10.1 8.4 11.7 8.4 Z
                                                              fill · 大圆角梯形 + 3 瓣波浪下摆
      体  M10.5 21 V36.8 Q10.5 39.4 13 39.4 H35 Q37.5 39.4 37.5 36.8 V21
                                                              stroke-width 3.4 · U 形墙
      笑  M17.3 27.6 A6.7 4.2 0 0 0 30.7 27.6
                                                              stroke-width 3.6 · 圆头笑脸弧

    ★★ `currentColor`：本组件**只画笔画、不管底色**。底色由外层容器给
       （`background: var(--brand-ink)`，L1 品牌层），文字色给 `#fff`。

    ★★ 为什么底色必须取 L1 而不是 L2（`var(--primary)`）：
       标识是**品牌资产**，定义就是"不管在哪儿都是这个色"。
       本轮之前 `.logo-avatar` 取了 `var(--primary)`（L2 主题主色），
       于是切到马卡龙档时标识变成玫红 `#c33a76` —— 那是**主题色**，不是品牌色。
       L1 住在 `presets.ts` 的 `BRAND_VARS`，**不进任何一张主题表**，
       注入在 `:root`（不带 `[data-theme]` 限定）⇒ 切主题在**结构上**碰不到它。

    ★★ 几何必须逐字一致：本文件 · `public/favicon.svg` · `site/assets/favicon.svg`。
       其中两处 favicon 是**删掉「笑」这一条 path 的严格子集**（16px 下笑脸会与底边
       糊成一体 —— 48 网格里画不出 16px 还留 1px 间隔的笑脸，是**结构性下限**）。
       判据 `scripts/check-brand-mark.cjs` 的 B1/B2/B3 会核对（不一致就报红）。

    ★ 为什么是自绘几何而不是图标字体 / 位图：
       零字体依赖（同一标识在任何设备上长得一样，而 favicon 正是"最小尺寸 + 跨设备"
       的极端场景）、零授权风险、任意尺寸不糊。详见
       `docs/图形标识设计稿-r373b.html` 与 `docs/品牌标识与品牌色-r373.md`。
  -->
  <svg
    class="brand-glyph"
    viewBox="0 0 48 48"
    aria-hidden="true"
    focusable="false"
  >
    <path
      d="M11.7 8.4 H36.3 Q37.9 8.4 38.7 10.5 L41 15.4 a5.667 3.3 0 0 1 -11.333 0 a5.667 3.3 0 0 1 -11.333 0 a5.667 3.3 0 0 1 -11.333 0 L9.3 10.5 Q10.1 8.4 11.7 8.4 Z"
      fill="currentColor"
    />
    <path
      d="M10.5 21 V36.8 Q10.5 39.4 13 39.4 H35 Q37.5 39.4 37.5 36.8 V21"
      fill="none"
      stroke="currentColor"
      stroke-width="3.4"
      stroke-linecap="round"
    />
    <path
      d="M17.3 27.6 A6.7 4.2 0 0 0 30.7 27.6"
      fill="none"
      stroke="currentColor"
      stroke-width="3.6"
      stroke-linecap="round"
    />
  </svg>
</template>

<script setup lang="ts">
/**
 * 品牌标识 —— 纯 SVG，无字体依赖、无外部请求、无 props。
 *
 * 用法：**外层容器**加 `data-brand-mark` 属性（它是「这是一处品牌标识」的机器可读标记，
 * 判据 `scripts/check-brand-mark.cjs` 按它枚举全仓标识点），容器负责
 * `background`（`var(--brand-ink)`）与 `color`（`#fff`）；本组件填满父容器。
 *
 * ★ 本注释**刻意不写"容器标签名 + class + 属性"的字面示例** —— 那会被文本判据
 *   当成一个真实存在的标识元素枚举进去（它只认属性，不认注释）。
 */
</script>

<style scoped>
.brand-glyph {
  display: block;
  width: 100%;
  height: 100%;
}
</style>
