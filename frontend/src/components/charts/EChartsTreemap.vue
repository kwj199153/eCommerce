<template>
  <div ref="wrapEl" class="et-wrap chart-root" role="img" :aria-label="title || '品类大盘云图'"></div>
</template>

<script setup lang="ts">
import { onMounted, onBeforeUnmount, ref, watch, computed } from 'vue'
import * as echarts from 'echarts/core'
import { TreemapChart } from 'echarts/charts'
import { TooltipComponent } from 'echarts/components'
import { CanvasRenderer } from 'echarts/renderers'
import { useThemeStore } from '@/stores/theme'

/**
 * ECharts Treemap 封装（第 306 轮 · 选品大盘云图换 ECharts）。
 *
 * 职责单一：把一棵 `TreemapCell[]` 渲染成两级 treemap（按 group 聚合成
 * 「一级类目组条 + 组内色块」，参考股票云图；面积=value，颜色=color，
 * label 显示类目名 + score），并向上抛点击事件。不关心数据从哪来、点完做什么。
 *
 * ★ 为什么按需引入（echarts/core + TreemapChart + TooltipComponent + CanvasRenderer）：
 *   项目此前**零图表库依赖**（Donut/Bar/Line 全自制 SVG），全量 `import * as echarts
 *   from 'echarts'` 会把整个包打进来。按需注册只需 treemap + tooltip，gzip 约 +150KB。
 *
 * ★ 生命周期：init → setOption → resize 观察 → dispose，避免 ECharts 实例泄漏
 *   （SFC 热更新/路由反复切面板时，不 dispose 会累积画布、内存只增不减）。
 *
 * ★ 主题自适应：读 useThemeStore().preset.isDark，切换明暗时重绘文字/边框颜色。
 *   文字颜色必须随主题（浅色黑字、深色浅字），否则深色下标签看不见。
 */

echarts.use([TreemapChart, TooltipComponent, CanvasRenderer])

/** 单个 treemap 色块（props.cells 的元素，父层按此形状传入即可，无需共享类型） */
interface TreemapCell {
  /** 唯一 key（点击回传用，如 `${site}|${category_path}`） */
  key: string
  /** 类目名（label 主文字） */
  name: string
  /** 面积值（搜索热度） */
  value: number
  /** 蓝海评分（label 副行数字） */
  score: number
  /** 色块语义色：blue=蓝海机会（primary）、red=红海拥挤（danger）。
   *  ★ 只收语义 key、不收 var(--x)：ECharts 画在 canvas 上不认 CSS 变量，
   *    真实 hex 由 palette 按当前主题给出（r307：var() 漏进 canvas = 灰块根因）。 */
  color: 'blue' | 'red'
  /** tooltip 附加行（可选，如 `月搜索 1.8M · 价格 $19.99~$299.99`） */
  extra?: string
  /** 分组名（可选，如 `Home & Kitchen`）：传了就按组聚合成两级树（组标题条 + 组内色块） */
  group?: string
}

const props = withDefaults(defineProps<{
  cells: TreemapCell[]
  title?: string
}>(), {
  title: '',
})

const emit = defineEmits<{
  (e: 'cell-click', key: string): void
}>()

const themeStore = useThemeStore()
const wrapEl = ref<HTMLElement | null>(null)

let chart: echarts.ECharts | null = null
let ro: ResizeObserver | null = null

/** 是否暗色（preset.isDark 诚实反映 <html>.dark 挂没挂） */
const isDark = computed(() => themeStore.preset.isDark)

/** 当前主题下的文字/边框/强调色（避免在 setOption 里反复散落 hex） */
const palette = computed(() => {
  if (isDark.value) {
    return {
      text: '#e6e6e6',
      sub: '#9aa0a6',
      border: '#2a2a2e',
      // 暗色 --primary / --danger（与 theme/presets.ts 暗色表一致）
      blue: '#177ddc',
      red: '#ff7875',
      // 组标题条底色（中性，让红蓝叶子更突出）
      groupBg: '#43454d',
    }
  }
  return {
    text: '#1f1f1f',
    sub: '#8c8c8c',
    border: '#ffffff',
    // 亮色 --primary / --danger（与 theme/presets.ts 亮色表一致）
    blue: '#1890ff',
    red: '#ff4d4f',
    groupBg: '#e2e6ec',
  }
})

/** 把 cells 映射成 ECharts treemap series data（两级树：组条 + 组内色块；label = 类目名 + score） */
function buildOption() {
  const pal = palette.value
  const leaf = (c: TreemapCell) => ({
    name: c.name,
    value: c.value || 1,
    itemStyle: { color: pal[c.color] },
    // 点击回传用：把 key 塞进原始数据，点击回调里 data.key 拿回（组节点没有 key ⇒ 点组不回传）
    key: c.key,
    score: c.score,
    extra: c.extra ?? '',
  })

  // 按 group 聚合成两级树（组标题条 + 组内色块，参考股票云图）；无 group 的保持扁平叶子
  const grouped = new Map<string, TreemapCell[]>()
  const flat: TreemapCell[] = []
  for (const c of props.cells) {
    if (c.group) {
      const arr = grouped.get(c.group)
      if (arr) arr.push(c)
      else grouped.set(c.group, [c])
    } else {
      flat.push(c)
    }
  }
  const data = [
    ...[...grouped.entries()].map(([name, children]) => ({ name, children: children.map(leaf) })),
    ...flat.map(leaf),
  ]

  return {
    tooltip: {
      // 小屏（对话模式窄面板）下 tooltip 超出容器会被裁掉，confine 强制收进图表区域内（r308）
      confine: true,
      backgroundColor: pal.border,
      borderColor: isDark.value ? '#3a3a3f' : '#e8e8e8',
      textStyle: { color: pal.text },
      formatter: (info: any) => {
        const d = info.data ?? {}
        // 组节点/根节点没有 key：只显示节点名。★取 info.name 而非 d.name——
        // 上层节点的 info.data 字段不可靠（r309 tooltip 显示 undefined 的根因）
        if (!d.key) return `<b>${String(info.name ?? '')}</b>`
        const extra = d.extra ? `<br/>${d.extra}` : ''
        return `<b>${d.name}</b><br/>蓝海评分 ${d.score}${extra}`
      },
    },
    series: [
      {
        type: 'treemap' as const,
        roam: false,
        nodeClick: false,
        breadcrumb: { show: false },
        // ★ label/rich 只配在叶子层（levels[2]）：series 级 formatter 会被组节点/根节点
        //   复用但 rich 不跟随 ⇒ 输出 {name|xxx} 原文（r309 事故根因）；上层 label 显式关闭。
        // 组标题条（两级树第一层：Home & Kitchen 等，参考股票云图的行业分组条）
        upperLabel: {
          show: true,
          height: 20,
          formatter: '{b}',
          color: pal.text,
          fontWeight: 500,
          fontSize: 11,
          padding: [0, 6],
        },
        levels: [
          {
            // 根层：隐式根没有 name，绝不能让它吃叶子 formatter（r309 顶部 {score} 空壳条根因）
            label: { show: false },
            upperLabel: { show: false },
          },
          {
            // 组层：中性底色（upperLabel 条背景即此色）；组名走 upperLabel，块内不重复显示
            label: { show: false },
            itemStyle: {
              color: pal.groupBg,
              borderColor: pal.border,
              borderWidth: 2,
              gapWidth: 2,
            },
          },
          {
            // 叶子层：色块颜色来自 data item 的 itemStyle.color（blue/red 语义色）
            itemStyle: { borderColor: pal.border, borderWidth: 1, gapWidth: 1 },
            label: {
              show: true,
              color: '#ffffff',
              // 两行：类目名（主）+ 蓝海评分（副）。rich 只在叶子层定义（r309 下沉）
              formatter: (p: any) => {
                const d = p.data ?? {}
                const name = String(d.name ?? '')
                // 二级子类目名可能较长（Storage & Organization · US），超长截断防溢出色块；
                // 全名在 tooltip 始终可见
                const shown = name.length > 22 ? `${name.slice(0, 21)}…` : name
                return shown ? `{name|${shown}}\n{score|${d.score ?? ''}}` : `{score|${d.score ?? ''}}`
              },
              rich: {
                name: { fontSize: 11, fontWeight: 500, color: 'rgba(255,255,255,0.92)', lineHeight: 16 },
                score: { fontSize: 15, fontWeight: 700, color: '#ffffff', lineHeight: 21 },
              },
            },
          },
        ],
        itemStyle: {
          borderColor: pal.border,
          borderWidth: 2,
          gapWidth: 2,
        },
        emphasis: {
          label: { show: true, fontWeight: 700 },
          itemStyle: { borderColor: pal.text, borderWidth: 2 },
        },
        data,
      },
    ],
  }
}

function render() {
  if (!chart) return
  chart.setOption(buildOption(), true)
}

function handleResize() {
  chart?.resize()
}

onMounted(() => {
  const el = wrapEl.value
  if (!el) return

  chart = echarts.init(el)
  chart.on('click', (params: any) => {
    const key = params?.data?.key
    if (key) emit('cell-click', key)
  })
  render()

  if (typeof ResizeObserver !== 'undefined') {
    ro = new ResizeObserver(handleResize)
    ro.observe(el)
  }
})

// 数据或主题变化 → 重绘
watch(() => props.cells, render, { deep: true })
watch(isDark, render)

onBeforeUnmount(() => {
  ro?.disconnect()
  ro = null
  chart?.dispose()
  chart = null
})
</script>

<style scoped>
.et-wrap {
  width: 100%;
  height: 100%;
  min-height: 180px;
}
</style>
