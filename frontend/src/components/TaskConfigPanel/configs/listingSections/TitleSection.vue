<template>
  <div class="title-sec">
    <div class="sec-head">
      <div>
        <div class="sec-title">标题 <a-tag class="mini-tag">{{ titleLen }} 字符</a-tag></div>
        <div class="sec-sub">推荐 150-200 字符，核心词前置；可直接改写后保存</div>
      </div>
      <a-button size="small" :loading="genLoading" :disabled="disabled" @click="$emit('gen')">生成标题</a-button>
    </div>

    <a-textarea
      v-model:value="draft.title"
      :rows="4"
      placeholder="生成或手动填写 Listing 标题"
      class="lb-title-input"
    />
    <div class="len-bar">
      <i class="len-fill" :class="lenClass" :style="{ width: lenPct + '%' }" />
    </div>

    <div v-if="draft.titleVariants.length" class="variant-box">
      <div class="variant-title">备选标题（点击采纳为主标题）</div>
      <div
        v-for="(v, i) in draft.titleVariants"
        :key="i"
        class="variant-row"
        @click="adoptVariant(v)"
      >
        <span class="variant-idx">{{ i + 1 }}</span>
        <span class="variant-text">{{ v }}</span>
      </div>
    </div>
  </div>
</template>

<script setup lang="ts">
import { computed } from 'vue'
import { message } from 'ant-design-vue'
import { useListingDraftStore } from '@/stores/listingDraft'

defineProps<{ genLoading: boolean; disabled?: boolean }>()
defineEmits<{ (e: 'gen'): void }>()

const draft = useListingDraftStore()

const titleLen = computed(() => draft.title.length)
const lenPct = computed(() => Math.min(100, (titleLen.value / 200) * 100))
const lenClass = computed(() => (titleLen.value < 120 ? 'short' : titleLen.value > 200 ? 'over' : 'ok'))

function adoptVariant(v: string) {
  const old = draft.title
  draft.title = v
  draft.titleVariants = draft.titleVariants.map(x => (x === v ? old : x)).filter(Boolean)
  message.success('已采纳为主标题')
}
</script>

<style scoped>
.sec-head {
  display: flex;
  align-items: flex-start;
  justify-content: space-between;
  gap: 8px;
}
.sec-title { font-size: 13px; font-weight: 600; color: var(--text-primary); }
.sec-sub { font-size: 11px; color: var(--text-tertiary); margin-top: 2px; }
.mini-tag { transform: scale(0.85); margin-left: 4px; }

.lb-title-input { font-size: 13px; margin-top: 10px; }
.len-bar {
  height: 4px;
  border-radius: 2px;
  background: var(--bg-hover-light);
  overflow: hidden;
}
.len-fill { display: block; height: 100%; transition: width 0.2s ease; }
.len-fill.ok { background: #52c41a; }
.len-fill.short { background: #fa8c16; }
.len-fill.over { background: #ff4d4f; }

.variant-box { margin-top: 4px; }
.variant-title { font-size: 11px; color: var(--text-tertiary); margin-bottom: 4px; }
.variant-row {
  display: flex;
  gap: 6px;
  padding: 5px 6px;
  border-radius: 4px;
  cursor: pointer;
  font-size: 12px;
  color: var(--text-secondary);
}
.variant-row:hover { background: var(--bg-hover-light); color: var(--primary); }
.variant-idx { color: var(--text-tertiary); flex-shrink: 0; }
.variant-text { line-height: 1.5; }
</style>
