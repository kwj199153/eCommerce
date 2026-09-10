import { ref, onMounted, onBeforeUnmount, type Ref } from 'vue'

/**
 * 测量容器实际像素尺寸，供轻量 SVG 图表自适应 viewBox 使用。
 *
 * 背景：图表若用固定 viewBox（如 0 0 600 250）+ width:100%/height:auto，
 * 在很宽的容器里会被等比放大（1200px 宽 → 500px 高），直接把看板撑出滚动条。
 * 改为按容器实际像素 1:1 绘制（viewBox = 实测宽高），图表就会「填满给定空间」
 * 而不是等比膨胀，从而保证整个看板在一屏内显示。
 */
export function useElementSize(
  target: Ref<HTMLElement | null>,
  fallbackW = 600,
  fallbackH = 220
) {
  const width = ref(fallbackW)
  const height = ref(fallbackH)
  let ro: ResizeObserver | null = null

  onMounted(() => {
    const el = target.value
    if (!el || typeof ResizeObserver === 'undefined') return
    ro = new ResizeObserver((entries) => {
      const rect = entries[0]?.contentRect
      if (!rect) return
      if (rect.width > 0) width.value = Math.round(rect.width)
      if (rect.height > 0) height.value = Math.round(rect.height)
    })
    ro.observe(el)
  })

  onBeforeUnmount(() => {
    ro?.disconnect()
    ro = null
  })

  return { width, height }
}
