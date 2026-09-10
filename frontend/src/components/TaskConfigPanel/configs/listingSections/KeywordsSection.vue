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

defineProps<{ genLoading: boolean; disabled?: boolean }>()
defineEmits<{ (e: 'gen'): void }>()

const draft = useListingDraftStore()

function relClass(r: number) {
  return r >= 90 ? 'r-high' : r >= 80 ? 'r-mid' : 'r-low'
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

.kw-list { display: flex; flex-direction: column; gap: 6px; margin-top: 10px; }
.kw-row {
  display: grid;
  grid-template-columns: auto 1fr 84px 76px 32px auto;
  gap: 6px;
  align-items: center;
}
.kw-num { width: 84px; }
.kw-comp { width: 76px; }
.kw-rel {
  font-size: 11px;
  text-align: center;
  font-weight: 600;
}
.r-high { color: #52c41a; }
.r-mid { color: #fa8c16; }
.r-low { color: var(--text-tertiary); }
</style>
