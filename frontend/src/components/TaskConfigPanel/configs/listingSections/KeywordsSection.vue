<template>
  <div class="kw-sec">
    <div class="sec-head">
      <div>
        <div class="sec-title">关键词 <a-tag class="mini-tag">{{ draft.keywords.length }} 个</a-tag></div>
        <div class="sec-sub">勾选的词会随「保存全部」合并进产品关键词，可在此增删改</div>
      </div>
      <a-button size="small" :loading="genLoading" :disabled="disabled" @click="$emit('gen')">生成关键词</a-button>
    </div>

    <div class="kw-list">
      <div v-for="k in draft.keywords" :key="k.id" class="kw-row">
        <a-checkbox v-model:checked="k.selected" />
        <a-input v-model:value="k.word" size="small" placeholder="关键词" class="kw-word" />
        <a-input-number v-model:value="k.search_volume" size="small" :min="0" class="kw-num" />
        <a-select v-model:value="k.competition" size="small" class="kw-comp">
          <a-select-option value="high">高竞争</a-select-option>
          <a-select-option value="medium">中</a-select-option>
          <a-select-option value="low">低</a-select-option>
        </a-select>
        <span class="kw-rel" :class="relClass(k.relevance)">{{ k.relevance }}</span>
        <a-button size="small" type="text" danger @click="draft.removeKeyword(k.id)">删除</a-button>
      </div>
      <a-button v-if="!draft.keywords.length" size="small" block type="dashed" @click="draft.addKeyword('')">
        + 手动添加关键词
      </a-button>
      <a-button v-else size="small" block type="dashed" @click="draft.addKeyword('')">+ 添加一行</a-button>
    </div>
  </div>
</template>

<script setup lang="ts">
import { useListingDraftStore } from '@/stores/listingDraft'
import { bandOf } from '@/theme/bands'

defineProps<{ genLoading: boolean; disabled?: boolean }>()
defineEmits<{ (e: 'gen'): void }>()

const draft = useListingDraftStore()

/** 相关度 → 类名。**与关键词挖掘共用 `relevance` 口径**（原为 90/80，已统一到 90/75） */
const REL_CLASS: Record<string, string> = { high: 'r-high', medium: 'r-mid', low: 'r-low' }
function relClass(r: number) {
  return REL_CLASS[bandOf('relevance', r)] || 'r-low'
}
</script>

<style scoped>
.sec-head {
  display: flex;
  align-items: flex-start;
  justify-content: space-between;
  gap: var(--space-8);
}
.sec-title { font-size: var(--font-size-13); font-weight: 600; color: var(--text-primary); }
.sec-sub { font-size: var(--font-size-11); color: var(--text-tertiary); margin-top: var(--space-2); }
.mini-tag { transform: scale(0.85); margin-left: var(--space-4); }

.kw-list { display: flex; flex-direction: column; gap: var(--space-6); margin-top: var(--space-10); }
.kw-row {
  display: grid;
  grid-template-columns: auto 1fr 84px 76px 32px auto;
  gap: var(--space-6);
  align-items: center;
}
.kw-num { width: 84px; }
.kw-comp { width: 76px; }
.kw-rel {
  font-size: var(--font-size-11);
  text-align: center;
  font-weight: 600;
}
.r-high { color: var(--success); }
.r-mid { color: #fa8c16; }
.r-low { color: var(--text-tertiary); }
</style>
