<template>
  <div class="bc-wrap chart-root">
    <div v-if="legend && groups.length > 1" class="bc-legend">
      <span v-for="g in groups" :key="g.name" class="bc-legend-item">
        <i class="bc-dot" :style="{ background: g.color }"></i>{{ g.name }}
      </span>
    </div>
    <div ref="plotEl" class="bc-plot">
    <svg :viewBox="`0 0 ${VB_W} ${VB_H}`" class="bc-svg" role="img" :aria-label="title">
      <title v-if="title">{{ title }}</title>
      <line
        v-for="g in gridLines"
        :key="g.y"
        :x1="PAD_L"
        :y1="g.y"
        :x2="VB_W - PAD_R"
        :y2="g.y"
        class="bc-grid"
      />
      <text
        v-for="g in gridLines"
        :key="'t' + g.y"
        :x="PAD_L - 6"
        :y="g.y + 4"
        class="bc-y-label"
      >{{ g.label }}</text>

      <!-- 每类目下的一组柱子 -->
      <g v-for="(cat, ci) in categories" :key="cat">
        <rect
          v-for="(g, gi) in groups"
          :key="gi"
          :x="barX(ci, gi)"
          :y="barY(g.data[ci])"
          :width="barW"
          :height="Math.max(0, PAD_T + PLOT_H - barY(g.data[ci]))"
          :fill="g.color"
          rx="2"
          class="bc-bar"
        >
          <title>{{ g.name }} · {{ cat }}：{{ g.data[ci] }}</title>
        </rect>
        <text
          v-if="showCategoryLabel"
          :x="catX(ci)"
          :y="VB_H - 8"
          class="bc-x-label"
        >{{ cat }}</text>
      </g>
    </svg>
    </div>
  </div>
</template>

<script setup lang="ts">
import { computed, ref } from 'vue'
import { useElementSize } from './useElementSize'

interface BcGroup { name: string; color: string; data: number[] }

const props = withDefaults(defineProps<{
  /** 分组柱状；单组 data 长度 = 类目数 */
  groups: BcGroup[]
  categories?: string[]
  showCategoryLabel?: boolean
  legend?: boolean
  title?: string
}>(), {
  categories: () => [],
  showCategoryLabel: true,
  legend: true,
  title: '',
})

// 自适应：按容器实际像素绘制，避免在宽容器里被等比放大撑破布局
const plotEl = ref<HTMLElement | null>(null)
const { width, height } = useElementSize(plotEl, 600, 220)

const VB_W = computed(() => Math.max(280, width.value))
const VB_H = computed(() => Math.max(120, height.value))
const PAD_L = 46
const PAD_R = 12
const PAD_T = 16
const PAD_B = 30
const PLOT_W = computed(() => VB_W.value - PAD_L - PAD_R)
const PLOT_H = computed(() => VB_H.value - PAD_T - PAD_B)

const categories = computed(() => {
  const len = props.groups[0]?.data.length || 0
  return props.categories.length === len
    ? props.categories
    : Array.from({ length: len }, (_, i) => String(i + 1))
})
const gCount = computed(() => props.groups.length)
const catCount = computed(() => categories.value.length)

const allVals = computed(() => {
  const arr: number[] = []
  props.groups.forEach((g) => g.data.forEach((d) => arr.push(d)))
  return arr
})
const max = computed(() => {
  const m = Math.max(...allVals.value, 0)
  return m === 0 ? 1 : m
})

const gridLines = computed(() => {
  const steps = 4
  const rows: { y: number; label: string }[] = []
  for (let i = 0; i <= steps; i++) {
    const val = (max.value / steps) * i
    rows.push({ y: yPos(val), label: fmt(val) })
  }
  return rows
})
function fmt(v: number): string {
  const a = Math.abs(v)
  if (a >= 10000) return (v / 1000).toFixed(0) + 'k'
  if (a >= 1000) return (v / 1000).toFixed(1) + 'k'
  return String(Math.round(v))
}
function yPos(v: number): number {
  return PAD_T + PLOT_H.value - (v / max.value) * PLOT_H.value
}
/** 每个类目的槽宽（含间隙） */
const slotW = computed(() => (catCount.value ? PLOT_W.value / catCount.value : PLOT_W.value))
const barW = computed(() => {
  const w = (slotW.value / gCount.value) * 0.6
  return Math.max(2, Math.min(w, 40))
})
function catX(ci: number): number {
  return PAD_L + slotW.value * ci + slotW.value / 2
}
function barX(ci: number, gi: number): number {
  const gW = slotW.value / gCount.value
  return PAD_L + slotW.value * ci + gW * gi + (gW - barW.value) / 2
}
function barY(v: number): number {
  return yPos(Math.max(0, v))
}
</script>

<style scoped>
/* 填满父级给定空间（父级未给高度时退化为 130px 兜底，绝不撑大布局） */
.bc-wrap { width: 100%; height: 100%; min-height: 130px; display: flex; flex-direction: column; }
.bc-legend { display: flex; flex-wrap: wrap; gap: 12px; margin-bottom: 6px; flex-shrink: 0; }
.bc-legend-item { display: inline-flex; align-items: center; gap: 5px; font-size: 11px; color: var(--text-secondary); }
.bc-dot { width: 8px; height: 8px; border-radius: 2px; display: inline-block; }
.bc-plot { position: relative; flex: 1; min-height: 0; }
.bc-svg { position: absolute; inset: 0; width: 100%; height: 100%; display: block; }
.bc-grid { stroke: var(--border-base); stroke-width: 1; stroke-dasharray: 3 4; }
.bc-y-label { font-size: 9px; fill: var(--text-tertiary); text-anchor: end; }
.bc-x-label { font-size: 9px; fill: var(--text-tertiary); text-anchor: middle; }
.bc-bar { transition: opacity 0.15s; }
.bc-bar:hover { opacity: 0.85; }
</style>
