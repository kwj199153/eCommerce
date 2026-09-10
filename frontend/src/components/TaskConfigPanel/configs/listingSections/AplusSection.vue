<template>
  <div class="ap-sec">
    <div class="sec-head">
      <div>
        <div class="sec-title">长描述 <a-tag class="mini-tag">{{ draft.aplusModules.length }} 个模块</a-tag></div>
        <div class="sec-sub">按模块编辑，保存时整体写回产品（A+ / 商品详情）</div>
      </div>
      <a-button size="small" :loading="genLoading" :disabled="disabled" @click="$emit('gen')">生成长描述</a-button>
    </div>

    <div class="ap-list">
      <div v-for="m in draft.aplusModules" :key="m.id" class="ap-card">
        <div class="ap-head">
          <a-tag class="mini-tag">{{ apTypeLabel(m.type) }}</a-tag>
          <a-input v-model:value="m.heading" size="small" placeholder="模块标题" class="ap-heading" />
          <a-button size="small" type="text" danger @click="draft.removeAPlusModule(m.id)">删除</a-button>
        </div>
        <a-textarea
          v-if="m.type === 'text'"
          v-model:value="m.content"
          :rows="3"
          placeholder="模块正文"
        />
        <template v-else-if="m.type === 'image-text'">
          <a-textarea
            v-for="(p, pi) in m.paragraphs || []"
            :key="pi"
            v-model:value="(m.paragraphs as string[])[pi]"
            :rows="2"
            placeholder="段落"
            class="ap-para"
          />
        </template>
        <template v-else-if="m.type === 'highlights'">
          <div v-for="(it, ii) in m.items || []" :key="ii" class="ap-item">
            <a-input v-model:value="it.title" size="small" placeholder="亮点" class="ap-item-title" />
            <a-input v-model:value="it.desc" size="small" placeholder="说明" />
          </div>
        </template>
      </div>
      <div class="ap-add">
        <a-button size="small" type="dashed" @click="draft.addAPlusModule('text')">+ 文本模块</a-button>
        <a-button size="small" type="dashed" @click="draft.addAPlusModule('highlights')">+ 亮点模块</a-button>
        <a-button size="small" type="dashed" @click="draft.addAPlusModule('image-text')">+ 图文模块</a-button>
      </div>
    </div>
  </div>
</template>

<script setup lang="ts">
import { useListingDraftStore } from '@/stores/listingDraft'

defineProps<{ genLoading: boolean; disabled?: boolean }>()
defineEmits<{ (e: 'gen'): void }>()

const draft = useListingDraftStore()

function apTypeLabel(t: string) {
  return ({ text: '文本', 'image-text': '图文', highlights: '亮点', comparison: '对比' } as Record<string, string>)[t] || t
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

.ap-list { display: flex; flex-direction: column; gap: 8px; margin-top: 10px; }
.ap-card {
  border: 1px solid var(--border-base);
  border-radius: 6px;
  padding: 8px;
  display: flex;
  flex-direction: column;
  gap: 6px;
  background: var(--bg-base);
}
.ap-head { display: flex; align-items: center; gap: 6px; }
.ap-heading { flex: 1; }
.ap-para { margin-bottom: 4px; }
.ap-item { display: flex; gap: 6px; }
.ap-item-title { max-width: 40%; }
.ap-add { display: flex; gap: 6px; flex-wrap: wrap; }
</style>
