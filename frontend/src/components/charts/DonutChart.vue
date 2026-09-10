<template>
  <div class="dc-wrap chart-root" ref="wrapEl">
    <div class="dc-body">
      <svg
        :viewBox="`0 0 ${S} ${S}`"
        class="dc-svg"
        :style="{ width: ringSize + 'px', height: ringSize + 'px' }"
        role="img"
        :aria-label="title"
      >
        <title v-if="title">{{ title }}</title>
        <circle :cx="C" :cy="C" :r="R" fill="none" stroke="var(--bg-hover-light)" :stroke-width="SW" />
        <g v-for="seg in segments" :key="seg.name">
          <circle
            :cx="C"
            :cy="C"
            :r="R"
            fill="none"
            :stroke="seg.color"
            :stroke-width="SW"
            :stroke-dasharray="`${seg.len} ${perim - seg.len}`"
            :stroke-dashoffset="seg.offset"
            transform="rotate(-90 120 120)"
            class="dc-seg"
          >
            <title>{{ seg.name }}：{{ seg.pct }}%</title>
          </circle>
        </g>
        <text v-if="centerTitle" :x="C" :y="C - 2" class="dc-center-title" text-anchor="middle">{{ centerTitle }}</text>
        <text v-if="centerValue" :x="C" :y="C + 16" class="dc-center-value" text-anchor="middle">{{ centerValue }}</text>
      </svg>
      <ul v-if="showLegend" class="dc-legend">
        <li v-for="seg in segments" :key="seg.name" class="dc-li">
          <i class="dc-dot" :style="{ background: seg.color }"></i>
          <span class="dc-name">{{ seg.name }}</span>
          <span class="dc-val">{{ seg.valueText }}</span>
          <span class="dc-pct">{{ seg.pct }}%</span>
        </li>
      </ul>
    </div>
  </div>
</template>

<script setup lang="ts">
import { computed, ref } from 'vue'
import { useElementSize } from './useElementSize'

interface Seg { name: string; value: number; color: string; valueText?: string }

const props = withDefaults(defineProps<{
  segments: Seg[]
  centerTitle?: string
  centerValue?: string
  showLegend?: boolean
  title?: string
}>(), {
  centerTitle: '',
  centerValue: '',
  showLegend: true,
  title: '',
})

const S = 240
const C = 120
const R = 88
const SW = 30
const perim = 2 * Math.PI * R

// 自适应：环形按容器可用高度/宽度缩放（而非固定 200px），保证一屏内放得下
const wrapEl = ref<HTMLElement | null>(null)
const { width, height } = useElementSize(wrapEl, 400, 200)
const ringSize = computed(() => {
  const byH = height.value - 8
  const byW = width.value * 0.5
  return Math.max(88, Math.min(byH, byW, 200))
})

const total = computed(() => props.segments.reduce((a, s) => a + s.value, 0) || 1)

const segments = computed(() => {
  let acc = 0
  return props.segments.map((s) => {
    const pct = (s.value / total.value) * 100
    const len = (s.value / total.value) * perim
    // dashoffset 从上方顺时针累计
    const offset = -acc
    acc += len
    return {
      name: s.name,
      color: s.color,
      valueText: s.valueText ?? String(s.value),
      pct: pct.toFixed(1),
      len,
      offset,
    }
  })
})
</script>

<style scoped>
.dc-wrap { width: 100%; height: 100%; min-height: 120px; }
.dc-body { display: flex; align-items: center; gap: 16px; height: 100%; min-height: 0; }
.dc-svg { flex-shrink: 0; display: block; }
.dc-seg { transition: opacity 0.15s; }
.dc-seg:hover { opacity: 0.82; }
.dc-center-title { font-size: 11px; fill: var(--text-tertiary); }
.dc-center-value { font-size: 18px; font-weight: 600; fill: var(--text-primary); }
.dc-legend { list-style: none; margin: 0; padding: 0; flex: 1; min-width: 120px; display: flex; flex-direction: column; gap: 6px; }
.dc-li { display: flex; align-items: center; gap: 6px; font-size: 12px; }
.dc-dot { width: 9px; height: 9px; border-radius: 2px; flex-shrink: 0; }
.dc-name { color: var(--text-secondary); flex: 1; overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }
.dc-val { color: var(--text-primary); font-weight: 600; }
.dc-pct { color: var(--text-tertiary); font-size: 11px; width: 40px; text-align: right; }
</style>
