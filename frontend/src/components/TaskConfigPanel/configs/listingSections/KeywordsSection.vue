<template>
  <div class="kw-sec">
    <div class="sec-head">
      <div>
        <div class="sec-title">关键词 <a-tag class="mini-tag">{{ draft.keywords.length }} 个</a-tag></div>
        <div class="sec-sub">
          勾选的词会随「保存全部」合并进产品关键词，可在此增删改。
          搜索量 / 竞争度 / 相关度由<strong>关键词挖掘</strong>提供 ——
          Search Terms 端点本身不带这三项，缺数据时显示 «—»
        </div>
      </div>
      <a-button size="small" :loading="genLoading" :disabled="disabled" @click="$emit('gen')">生成关键词</a-button>
    </div>

    <div class="kw-list">
      <div v-for="k in draft.keywords" :key="k.id" class="kw-row">
        <a-checkbox v-model:checked="k.selected" />
        <a-input v-model:value="k.word" size="small" placeholder="关键词" class="kw-word" />
        <!--
          ★ 三列指标是 null 感知的：`null` = 后端未提供（Search Terms 端点就不带），
            与「搜索量真的是 0」「相关度真的是 80」不是一回事 ⇒ 渲染 «—»。
            有值时才给编辑控件（关键词挖掘那条链会填真数据）。
        -->
        <a-input-number
          v-if="k.search_volume !== null"
          v-model:value="k.search_volume"
          size="small"
          :min="0"
          class="kw-num"
        />
        <span v-else class="kw-none" title="Search Terms 端点不提供月搜索量">—</span>
        <a-select v-if="k.competition" v-model:value="k.competition" size="small" class="kw-comp">
          <a-select-option value="high">高竞争</a-select-option>
          <a-select-option value="medium">中</a-select-option>
          <a-select-option value="low">低</a-select-option>
        </a-select>
        <span v-else class="kw-none">—</span>
        <span class="kw-rel" :class="relClass(k.relevance)">{{ k.relevance ?? '—' }}</span>
        <a-button size="small" type="text" danger @click="draft.removeKeyword(k.id)">删除</a-button>
      </div>
      <a-button v-if="!draft.keywords.length" size="small" block type="dashed" @click="draft.addKeyword('')">
        + 手动添加关键词
      </a-button>
      <a-button v-else size="small" block type="dashed" @click="draft.addKeyword('')">+ 添加一行</a-button>
    </div>

    <PromptTab v-model="draft.keywordPrompt" placeholder="例如：重点覆盖长尾词，包含拼写变体与场景词，控制在 250 字节内" />
  </div>
</template>

<script setup lang="ts">
import { useListingDraftStore } from '@/stores/listingDraft'
import { bandOf } from '@/theme/bands'
import PromptTab from './PromptTab.vue'

defineProps<{ genLoading: boolean; disabled?: boolean }>()
defineEmits<{ (e: 'gen'): void }>()

const draft = useListingDraftStore()

const REL_CLASS: Record<string, string> = { high: 'r-high', medium: 'r-mid', low: 'r-low' }

/**
 * 相关度 → 类名。**与关键词挖掘共用 `relevance` 口径**（原为 90/80，已统一到 90/75）。
 *
 * ★ `null` = 后端未提供该指标，走中性的 `r-none`。
 *   不能让它落进 `r-low`（那是「相关度确实很低」的语义），否则又是一次「未测量」
 *   被渲染成「测出来很低」。
 */
function relClass(r: number | null) {
  if (r === null || r === undefined) return 'r-none'
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
/* 指标缺失占位（与 r-low 区分：那是「真的很低」，这里是「没有这个数」） */
.r-none { color: var(--text-tertiary); opacity: 0.55; }
.kw-none {
  font-size: var(--font-size-11);
  text-align: center;
  color: var(--text-tertiary);
  opacity: 0.55;
}
</style>
