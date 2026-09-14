<template>
  <Teleport to="body">
    <div
      v-if="state.visible"
      ref="layerRef"
      class="stl-layer"
      data-stl-layer=""
      :style="{ left: `${pos.left}px`, top: `${pos.top}px` }"
      @mousedown="setSuppressHide(true)"
      @mouseup="setSuppressHide(false)"
    >
      <div class="stl-head">
        <span class="stl-badge">{{ badgeText }}</span>
        <span class="stl-spacer" />
        <button
          class="stl-btn"
          type="button"
          title="复制译文"
          :disabled="!state.translation"
          @click="onCopy"
        >
          复制
        </button>
        <button class="stl-btn" type="button" title="关闭（Esc）" @click="hide">关闭</button>
      </div>

      <div class="stl-src">{{ state.original }}</div>
      <div class="stl-sep" />
      <div class="stl-dst" :class="{ 'is-error': !!state.error }">
        <template v-if="state.loading">
          <span class="stl-spin" />正在翻译…
        </template>
        <template v-else-if="state.error">{{ state.error }}</template>
        <template v-else>{{ state.translation }}</template>
      </div>
    </div>
  </Teleport>
</template>

<script setup lang="ts">
/**
 * 划词翻译浮层（SaaS 内建）
 * =========================
 * 挂在 Workspace 上，全站生效。逻辑全在 useSelectionTranslate，
 * 这里只做两件事：渲染 + 定位（以及把全局选区监听的装载/卸载挂在生命周期上）。
 *
 * 用 Teleport 到 body：避免被祖先元素的 `overflow: hidden` 裁掉，
 * 也避免受祖先 `transform`/`filter` 影响 fixed 定位。
 *
 * 样式 scoped 即可生效 —— Teleport 只搬 DOM，元素上的 data-v 属性还在，
 * 所以「teleport 出去 scoped 就够不着」只对**第三方组件内部**的元素成立，
 * 自家模板的元素没问题。
 */
import { computed, nextTick, onMounted, onUnmounted, reactive, ref, watch } from 'vue'
import { message } from 'ant-design-vue'
import { useSelectionTranslate } from '@/composables/useSelectionTranslate'

const { state, hide, setSuppressHide, startSelectionWatcher } = useSelectionTranslate()

const layerRef = ref<HTMLElement | null>(null)
const pos = reactive({ left: 0, top: 0 })

const LANG_LABEL: Record<string, string> = {
  zh: '中文',
  en: '英文',
  ja: '日文',
  ko: '韩文',
  de: '德文',
  es: '西文',
  fr: '法文',
  it: '意文',
  pt: '葡文',
}

const badgeText = computed(() => {
  if (state.loading) return '翻译中'
  if (state.error) return '翻译失败'
  const from = LANG_LABEL[state.sourceLang] || '原文'
  const to = LANG_LABEL[state.targetLang] || state.targetLang
  return to ? `${from} → ${to}` : from
})

/** 定位：优先浮在选区上方，上方不够落下方，左右夹进视口。 */
function reposition() {
  const el = layerRef.value
  if (!el) return
  const w = el.offsetWidth
  const h = el.offsetHeight
  const gap = 8
  const a = state.anchor

  // 没有锚点（「译」按钮拿不到元素时）→ 视口底部居中
  if (!a) {
    pos.left = Math.round((window.innerWidth - w) / 2)
    pos.top = Math.round(Math.max(8, window.innerHeight - h - 24))
    return
  }

  let left = a.left + a.width / 2 - w / 2
  left = Math.min(Math.max(left, 8), Math.max(8, window.innerWidth - w - 8))

  let top = a.top - h - gap
  if (top < 8) top = a.bottom + gap
  if (top + h > window.innerHeight - 8) top = Math.max(8, window.innerHeight - h - 8)

  pos.left = Math.round(left)
  pos.top = Math.round(top)
}

// 内容或锚点变化都要重新量尺寸（译文长度不同，浮层高度会变）
watch(
  () => [state.visible, state.loading, state.translation, state.error, state.anchor] as const,
  async () => {
    await nextTick()
    reposition()
  },
  { deep: true, immediate: true },
)

async function onCopy() {
  const text = state.translation
  if (!text) return
  try {
    await navigator.clipboard.writeText(text)
    message.success('已复制译文')
  } catch {
    message.warning('复制失败，请手动选中译文')
  }
}

let stopWatcher: (() => void) | null = null

onMounted(() => {
  stopWatcher = startSelectionWatcher()
})

onUnmounted(() => {
  stopWatcher?.()
  stopWatcher = null
})
</script>

<style scoped>
.stl-layer {
  position: fixed;
  /* 高于 Ant Design 的 modal(1000)/message(1010)/tooltip(1070)：弹窗里选词也要能看到 */
  z-index: 2000;
  width: 360px;
  max-width: calc(100vw - 16px);
  box-sizing: border-box;
  padding: var(--space-10) var(--space-12) var(--space-12);
  background: var(--bg-elevated);
  border: 1px solid var(--border-strong);
  border-radius: var(--radius-10);
  box-shadow: 0 6px 20px rgba(0, 0, 0, 0.16);
  font-size: var(--font-size-13);
  line-height: 1.6;
  color: var(--text-primary);
}

.stl-head {
  display: flex;
  align-items: center;
  gap: var(--space-8);
  margin-bottom: var(--space-6);
}

.stl-badge {
  padding: 0 var(--space-6);
  border-radius: var(--radius-4);
  background: var(--bg-card-pill);
  color: var(--text-secondary);
  font-size: var(--font-size-11);
  line-height: 18px;
  white-space: nowrap;
}

.stl-spacer {
  flex: 1;
}

.stl-btn {
  padding: 0 var(--space-8);
  height: 22px;
  border: 1px solid var(--border-base);
  border-radius: var(--radius-6);
  background: transparent;
  color: var(--text-secondary);
  font-size: var(--font-size-12);
  line-height: 1;
  cursor: pointer;
}

.stl-btn:hover:not(:disabled) {
  color: var(--primary);
  border-color: var(--primary);
}

.stl-btn:disabled {
  color: var(--text-disabled);
  cursor: not-allowed;
}

.stl-src {
  display: -webkit-box;
  -webkit-line-clamp: 3;
  -webkit-box-orient: vertical;
  overflow: hidden;
  color: var(--text-tertiary);
  font-size: var(--font-size-12);
  word-break: break-word;
  user-select: text;
}

.stl-sep {
  height: 1px;
  margin: var(--space-8) 0;
  background: var(--border-base);
}

.stl-dst {
  max-height: 240px;
  overflow: auto;
  white-space: pre-wrap;
  word-break: break-word;
  user-select: text;
}

.stl-dst.is-error {
  color: var(--danger);
}

.stl-spin {
  display: inline-block;
  width: 11px;
  height: 11px;
  margin-right: var(--space-6);
  vertical-align: -1px;
  border: 2px solid var(--border-strong);
  border-top-color: var(--primary);
  border-radius: var(--radius-circle);
  animation: stl-spin 0.7s linear infinite;
}

@keyframes stl-spin {
  to {
    transform: rotate(360deg);
  }
}
</style>
