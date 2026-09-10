<template>
  <div class="lc-wrap chart-root">
    <div v-if="legend" class="lc-legend">
      <span v-for="s in series" :key="s.name" class="lc-legend-item">
        <i class="lc-dot" :style="{ background: s.color }"></i>{{ s.name }}
      </span>
    </div>
    <div ref="plotEl" class="lc-plot">
    <svg :viewBox="`0 0 ${VB_W} ${VB_H}`" class="lc-svg" role="img" :aria-label="title">
      <title v-if="title">{{ title }}</title>
      <!-- 横向网格线 -->
      <line
        v-for="g in gridLines"
        :key="g.y"
        :x1="PAD_L"
        :y1="g.y"
        :x2="VB_W - PAD_R"
        :y2="g.y"
        class="lc-grid"
      />
      <text
        v-for="g in gridLines"
        :key="'t' + g.y"
        :x="PAD_L - 6"
        :y="g.y + 4"
        class="lc-y-label"
      >{{ g.label }}</text>

      <!-- 数据系列折线 -->
      <g v-for="(s, si) in renderedSeries" :key="s.name">
        <polyline
          :points="s.points"
          fill="none"
          :stroke="s.color"
          stroke-width="2"
          stroke-linejoin="round"
          stroke-linecap="round"
          class="lc-line"
        />
        <circle
          v-for="pt in s.pts"
          :key="pt.x + '-' + si"
          :cx="pt.x"
          :cy="pt.y"
          r="3"
          :fill="s.color"
          class="lc-point"
        />
      </g>

      <!-- 底部类目刻度 -->
      <text
        v-for="c in xTicks"
        :key="'x' + c.x"
        :x="c.x"
        :y="VB_H - 8"
        class="lc-x-label"
      >{{ c.text }}</text>
    </svg>
    </div>
  </div>
</template>

<script setup lang="ts">
import { computed, ref } from 'vue'
import { useElementSize } from './useElementSize'

interface LcSeries { name: string; color: string; data: number[] }

const props = withDefaults(defineProps<{
  /** 多系列数据，各系列 data 长度须一致 */
  series: LcSeries[]
  /** 底部类目文字（横轴刻度） */
  labels?: string[]
  legend?: boolean
  title?: string
}>(), {
  labels: () => [],
  legend: true,
  title: '',
})

// 自适应：按容器实际像素绘制，避免在宽容器里被等比放大撑破布局
const plotEl = ref<HTMLElement | null>(null)
const { width, height } = useElementSize(plotEl, 600, 220)

const VB_W = computed(() => Math.max(280, width.value))
const VB_H = computed(() => Math.max(120, height.value))
const PAD_L = 46
const PAD_R = 14
const PAD_T = 16
const PAD_B = 28
const PLOT_W = computed(() => VB_W.value - PAD_L - PAD_R)
const PLOT_H = computed(() => VB_H.value - PAD_T - PAD_B)

const n = computed(() => (props.series[0]?.data.length || 0))
const allVals = computed<number[]>(() => {
  const arr: number[] = []
  props.series.forEach((s) => s.data.forEach((d) => arr.push(d)))
  return arr
})
const min = computed(() => Math.min(0, ...allVals.value))
const max = computed(() => {
  const m = Math.max(...allVals.value)
  return m === 0 ? 1 : m
})
const span = computed(() => max.value - min.value || 1)

function xPos(i: number): number {
  if (n.value <= 1) return PAD_L + PLOT_W.value / 2
  return PAD_L + (i / (n.value - 1)) * PLOT_W.value
}
function yPos(v: number): number {
  return PAD_T + PLOT_H.value - ((v - min.value) / span.value) * PLOT_H.value
}
function fmt(v: number): string {
  const a = Math.abs(v)
  if (a >= 10000) return (v / 1000).toFixed(0) + 'k'
  if (a >= 1000) return (v / 1000).toFixed(1) + 'k'
  return String(Math.round(v))
}

const gridLines = computed(() => {
  const steps = 4
  const rows: { y: number; label: string }[] = []
  for (let i = 0; i <= steps; i++) {
    const val = min.value + (span.value / steps) * i
    const y = PAD_T + PLOT_H.value - ((val - min.value) / span.value) * PLOT_H.value
    rows.push({ y, label: fmt(val) })
  }
  return rows
})

const xTicks = computed(() => {
  const out: { x: number; text: string }[] = []
  if (!n.value) return out
  const total = Math.max(props.labels.length, 1)
  const step = Math.max(1, Math.ceil(n.value / Math.min(total, 8)))
  for (let i = 0; i < n.value; i += step) {
    const text = props.labels[i] ?? String(i + 1)
    out.push({ x: xPos(i), text })
  }
  const lastText = props.labels[n.value - 1] ?? String(n.value)
  if (!out.length || out[out.length - 1].text !== lastText) {
    out.push({ x: xPos(n.value - 1), text: lastText })
  }
  return out
})

const renderedSeries = computed(() =>
  props.series.map((s) => {
    const pts = s.data.map((v, i) => ({ x: xPos(i), y: yPos(v) }))
    const points = pts.map((p) => `${p.x},${p.y}`).join(' ')
    return { name: s.name, color: s.color, points, pts }
  })
)
</script>

<style scoped>
/* 填满父级给定空间（父级未给高度时退化为 130px 兜底，绝不撑大布局） */
.lc-wrap { width: 100%; height: 100%; min-height: 130px; display: flex; flex-direction: column; }
.lc-legend { display: flex; flex-wrap: wrap; gap: 12px; margin-bottom: 6px; flex-shrink: 0; }
.lc-legend-item { display: inline-flex; align-items: center; gap: 5px; font-size: 11px; color: var(--text-secondary); }
.lc-dot { width: 8px; height: 8px; border-radius: 50%; display: inline-block; }
.lc-plot { position: relative; flex: 1; min-height: 0; }
.lc-svg { position: absolute; inset: 0; width: 100%; height: 100%; display: block; }
.lc-grid { stroke: var(--border-base); stroke-width: 1; stroke-dasharray: 3 4; }
.lc-y-label { font-size: 9px; fill: var(--text-tertiary); text-anchor: end; }
.lc-x-label { font-size: 9px; fill: var(--text-tertiary); text-anchor: middle; }
.lc-point { opacity: 0; }
.lc-wrap:hover .lc-point { opacity: 0.9; }
</style>
