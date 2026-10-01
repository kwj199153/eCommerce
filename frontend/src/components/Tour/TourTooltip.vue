<template>
  <div
    v-if="rect"
    ref="cardRef"
    class="tour-tooltip"
    :style="style"
    role="dialog"
    aria-modal="false"
    :aria-label="`新手引导 ${progress}`"
  >
    <div class="tt-head">
      <span class="tt-progress">{{ progress }}</span>
      <span class="tt-title">{{ step.title }}</span>
      <span class="tt-spacer" />
      <!-- 静音开关：**只有同一个开关**，声音与文字是同一份内容的两条通道 -->
      <button
        class="tt-mute"
        type="button"
        :title="muted ? '开启语音解说' : '静音'"
        @click="$emit('toggle-mute')"
      >
        <span class="tt-mute-icon">{{ muted ? '🔇' : '🔊' }}</span>
      </button>
      <button
        class="tt-close"
        type="button"
        title="退出引导（Esc）"
        @click="$emit('skip')"
      >
        ×
      </button>
    </div>

    <div class="tt-body">
      {{ step.body }}
    </div>

    <!-- 谁在念。★ 降级不许静默：克隆音色不可用时这里会写明「系统语音（原因）」，
         否则用户听到一个陌生嗓门，只会以为功能坏了。 -->
    <div
      v-if="channelLabel"
      class="tt-voice"
    >
      {{ channelLabel }}
    </div>

    <!-- 语音不可用时的**显式说明**。
         ★ 不留空 / 不静默置灰：用户点过「播报」却没声音又毫无线索，
           是最难归因的一类问题（看着像功能坏了，其实是系统没装语音包）。 -->
    <div
      v-if="reason"
      class="tt-reason"
    >
      ⚠️ {{ reason }}
    </div>

    <div class="tt-foot">
      <button
        class="tt-btn tt-ghost"
        type="button"
        @click="$emit('skip')"
      >
        跳过
      </button>
      <span class="tt-spacer" />
      <button
        class="tt-btn"
        type="button"
        :disabled="!canPrev"
        @click="$emit('prev')"
      >
        上一步
      </button>
      <button
        class="tt-btn tt-primary"
        type="button"
        @click="$emit('next')"
      >
        {{ isLast ? '完成' : '下一步' }}
      </button>
    </div>
  </div>
</template>

<script setup lang="ts">
import { computed, nextTick, onMounted, ref, watch } from 'vue'
import type { TourStep } from '@/config/tourSteps'

interface BoxRect {
  top: number
  left: number
  width: number
  height: number
}

const props = defineProps<{
  step: TourStep
  rect: BoxRect | null
  progress: string
  canPrev: boolean
  isLast: boolean
  muted: boolean
  /** 语音不可用的原因（空串表示可用） */
  reason: string
  /** 当前实际发声通道的一句话说明（含「为什么不是另一条」）；静音时为「已静音」 */
  channelLabel: string
}>()

defineEmits<{
  (e: 'prev'): void
  (e: 'next'): void
  (e: 'skip'): void
  (e: 'toggle-mute'): void
}>()

/** 卡片自身的实际尺寸：定位要靠它做翻转与贴边修正，写死一个值会在长文案时飘出屏幕 */
const cardRef = ref<HTMLElement | null>(null)
const size = ref({ w: 320, h: 200 })
const GAP = 14
const MARGIN = 12

const CARD_W = 320

async function measure() {
  await nextTick()
  const el = cardRef.value
  if (!el) return
  const r = el.getBoundingClientRect()
  if (r.width > 0 && r.height > 0) size.value = { w: r.width, h: r.height }
}

onMounted(measure)
watch(() => props.step.id, measure)
watch(() => props.rect, measure)

const style = computed(() => {
  const r = props.rect
  if (!r) return { display: 'none' }
  const vw = typeof window === 'undefined' ? 1920 : window.innerWidth
  const vh = typeof window === 'undefined' ? 1080 : window.innerHeight
  const { w, h } = size.value

  /** 候选位置：首选 ringPlace，放不下就依次回退 —— 保证卡片永远完整可见 */
  const order = [props.step.place || 'right', 'left', 'bottom', 'top'] as const
  for (const place of [...new Set(order)]) {
    let left = 0
    let top = 0
    if (place === 'right') {
      left = r.left + r.width + GAP
      top = r.top + r.height / 2 - h / 2
    } else if (place === 'left') {
      left = r.left - w - GAP
      top = r.top + r.height / 2 - h / 2
    } else if (place === 'bottom') {
      left = r.left + r.width / 2 - w / 2
      top = r.top + r.height + GAP
    } else {
      left = r.left + r.width / 2 - w / 2
      top = r.top - h - GAP
    }
    const fits =
      left >= MARGIN && top >= MARGIN && left + w <= vw - MARGIN && top + h <= vh - MARGIN
    if (fits) return { left: `${Math.round(left)}px`, top: `${Math.round(top)}px` }
  }

  // 全放不下（极小窗口）：贴到右下角，宁可压住内容也不要出屏
  return {
    left: `${Math.max(MARGIN, vw - w - MARGIN)}px`,
    top: `${Math.max(MARGIN, vh - h - MARGIN)}px`,
  }
})
</script>

<style scoped>
.tour-tooltip {
  position: fixed;
  z-index: 1901; /* 必须高于 TourOverlay 的 1900，否则会被自己的遮罩压住 */
  width: 320px;
  max-width: calc(100vw - 24px);
  max-height: calc(100vh - 24px);
  overflow-y: auto;
  padding: var(--space-14) var(--space-16) var(--space-12);
  background: var(--bg-elevated);
  border: 1px solid var(--border-base);
  border-radius: var(--radius-12);
  box-shadow: var(--shadow-overlay);
  color: var(--text-primary);
  transition:
    left 0.22s cubic-bezier(0.645, 0.045, 0.355, 1),
    top 0.22s cubic-bezier(0.645, 0.045, 0.355, 1);
}

.tt-head {
  display: flex;
  align-items: center;
  gap: var(--space-8);
  margin-bottom: var(--space-10);
}

.tt-progress {
  font-size: var(--font-size-11);
  color: var(--text-inverse, #fff);
  background: var(--primary);
  border-radius: var(--radius-8);
  padding: 0 var(--space-6);
  line-height: 18px;
  flex-shrink: 0;
  font-variant-numeric: tabular-nums;
}

.tt-title {
  font-size: var(--font-size-14);
  font-weight: 600;
  color: var(--text-primary);
  min-width: 0;
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}

.tt-spacer { flex: 1; }

.tt-mute,
.tt-close {
  flex-shrink: 0;
  border: 0;
  background: transparent;
  cursor: pointer;
  color: var(--text-tertiary);
  border-radius: var(--radius-6);
  line-height: 1;
}

.tt-mute {
  width: 24px;
  height: 24px;
  display: inline-flex;
  align-items: center;
  justify-content: center;
  font-size: var(--font-size-13);
}

.tt-close {
  width: 24px;
  height: 24px;
  font-size: var(--font-size-18);
}

.tt-mute:hover,
.tt-close:hover {
  background: var(--bg-hover-light);
  color: var(--primary);
}

.tt-body {
  font-size: var(--font-size-13);
  line-height: 1.75;
  color: var(--text-secondary);
  white-space: pre-line;
}

.tt-voice {
  margin-top: var(--space-8);
  font-size: var(--font-size-11);
  line-height: 1.6;
  color: var(--text-tertiary);
}

.tt-reason {
  margin-top: var(--space-10);
  font-size: var(--font-size-11);
  line-height: 1.6;
  color: var(--warning, #d46b08);
  background: var(--bg-base);
  border: 1px dashed var(--border-strong);
  border-radius: var(--radius-6);
  padding: var(--space-6) var(--space-8);
}

.tt-foot {
  display: flex;
  align-items: center;
  gap: var(--space-8);
  margin-top: var(--space-14);
}

.tt-btn {
  height: 30px;
  padding: 0 var(--space-14);
  font-size: var(--font-size-13);
  border: 1px solid var(--border-base);
  border-radius: var(--radius-8);
  background: var(--bg-elevated);
  color: var(--text-secondary);
  cursor: pointer;
  transition: all 0.16s ease;
}

.tt-btn:hover:not(:disabled) {
  color: var(--primary);
  border-color: var(--primary);
  background: var(--bg-active-light);
}

.tt-btn:disabled {
  opacity: 0.45;
  cursor: not-allowed;
}

.tt-btn.tt-primary {
  background: var(--primary);
  border-color: var(--primary);
  color: #fff;
  font-weight: 600;
}

.tt-btn.tt-primary:hover {
  background: var(--primary-hover);
  border-color: var(--primary-hover);
  color: #fff;
}

.tt-ghost {
  border-color: transparent;
  color: var(--text-disabled);
  padding: 0 var(--space-6);
}
</style>
