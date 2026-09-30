<template>
  <!--
    聚光遮罩：整屏变暗 + 在目标位置挖一个洞。
    ★ 为什么用 SVG mask 而不是「四个 div 拼出来的框」：后者在目标带圆角、
      目标跨滚动容器、目标宽高为 0 这几种情况下，四条边会互相压不住 / 露白边，
      而 mask 是"先画满整屏、再挖掉一块"，天然不存在这些接缝问题。
    ★ 洞比目标元素**大一圈**（pad）：紧贴边缘会让高亮看起来像被裁了一半，
      尤其是目标自身带边框的时候。
  -->
  <div v-if="rect" class="tour-overlay">
    <svg
      class="tour-mask-svg"
      :width="vw"
      :height="vh"
      :viewBox="`0 0 ${vw} ${vh}`"
      preserveAspectRatio="none"
    >
      <defs>
        <mask :id="maskId" maskUnits="userSpaceOnUse">
          <!-- 白 = 保留遮罩，黑 = 挖掉 -->
          <rect x="0" y="0" :width="vw" :height="vh" fill="#fff" />
          <rect
            :x="hole.x"
            :y="hole.y"
            :width="hole.w"
            :height="hole.h"
            :rx="radius"
            :ry="radius"
            fill="#000"
          />
        </mask>
      </defs>
      <rect
        x="0"
        y="0"
        :width="vw"
        :height="vh"
        fill="rgba(0, 0, 0, 0.58)"
        :mask="`url(#${maskId})`"
      />
    </svg>

    <!-- 高亮描边：ring 单独一层，方便加呼吸感的 box-shadow 而不影响 mask 的几何 -->
    <div class="tour-ring" :style="ringStyle" />
  </div>
</template>

<script setup lang="ts">
import { computed, onMounted, onUnmounted, ref } from 'vue'

export interface BoxRect {
  top: number
  left: number
  width: number
  height: number
}

const props = withDefaults(
  defineProps<{
    rect: BoxRect | null
    /** 挖洞时的外扩留白，让高亮元素不贴着洞口边缘 */
    pad?: number
    radius?: number
  }>(),
  { pad: 6, radius: 10 },
)

// ★ mask 的 id 是**文档级**的：两个实例用同一个 id，后一个会把前一个的洞抢走。
//   这里 `<script setup>` 的块体每个实例都会重跑一遍，模块级自增没有意义
//   （每次都从 0 起）——唯一性交给随机后缀。
const maskId = `tour-hole-${Math.random().toString(36).slice(2, 10)}`

const vw = ref(typeof window === 'undefined' ? 1920 : window.innerWidth)
const vh = ref(typeof window === 'undefined' ? 1080 : window.innerHeight)

const onResize = () => {
  vw.value = window.innerWidth
  vh.value = window.innerHeight
}
onMounted(() => window.addEventListener('resize', onResize))
onUnmounted(() => window.removeEventListener('resize', onResize))

const hole = computed(() => {
  const r = props.rect
  const pad = props.pad
  if (!r) return { x: 0, y: 0, w: 0, h: 0 }
  return {
    x: Math.max(0, r.left - pad),
    y: Math.max(0, r.top - pad),
    w: Math.max(0, r.width + pad * 2),
    h: Math.max(0, r.height + pad * 2),
  }
})

const ringStyle = computed(() => ({
  top: `${hole.value.y}px`,
  left: `${hole.value.x}px`,
  width: `${hole.value.w}px`,
  height: `${hole.value.h}px`,
  borderRadius: `${props.radius}px`,
}))
</script>

<style scoped>
.tour-overlay {
  position: fixed;
  inset: 0;
  z-index: 1900;
  /* ★ 刻意吃掉整屏点击：MVP 的 7 步都是"看与听"，没有任何一步要求用户去点高亮元素。
     不挡住的反而是坑 —— 用户在讲解期间误点到背景，界面切走了而引导还在讲上一块。 */
  pointer-events: auto;
}

.tour-mask-svg {
  position: absolute;
  inset: 0;
  display: block;
}

.tour-ring {
  position: absolute;
  pointer-events: none;
  box-shadow:
    0 0 0 2px var(--primary),
    0 0 0 6px rgba(24, 144, 255, 0.18);
  transition:
    top 0.22s cubic-bezier(0.645, 0.045, 0.355, 1),
    left 0.22s cubic-bezier(0.645, 0.045, 0.355, 1),
    width 0.22s cubic-bezier(0.645, 0.045, 0.355, 1),
    height 0.22s cubic-bezier(0.645, 0.045, 0.355, 1);
}
</style>
