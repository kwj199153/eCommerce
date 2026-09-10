<template>
  <div class="bl-sec">
    <div class="sec-head">
      <div>
        <div class="sec-title">五点描述 <a-tag class="mini-tag">{{ draft.bullets.length }} 条</a-tag></div>
        <div class="sec-sub">建议每条以【大写关键词】开头，250 字符内</div>
      </div>
      <a-button size="small" :loading="genLoading" :disabled="disabled" @click="$emit('gen')">生成五点</a-button>
    </div>

    <div class="bl-list">
      <div v-for="(b, i) in draft.bullets" :key="b.id" class="bl-card">
        <div class="bl-head">
          <span class="bl-idx">{{ i + 1 }}</span>
          <a-input v-model:value="b.title" size="small" placeholder="【关键词】开头" class="bl-title" />
          <a-button size="small" type="text" danger @click="draft.removeBullet(b.id)">删除</a-button>
        </div>
        <a-textarea v-model:value="b.content" :rows="3" placeholder="卖点描述" />
        <div class="bl-len">{{ b.content.length }} 字符</div>
      </div>
      <a-button size="small" block type="dashed" @click="draft.addBullet()">+ 新增一条</a-button>
    </div>
  </div>
</template>

<script setup lang="ts">
import { useListingDraftStore } from '@/stores/listingDraft'

defineProps<{ genLoading: boolean; disabled?: boolean }>()
defineEmits<{ (e: 'gen'): void }>()

const draft = useListingDraftStore()
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

.bl-list { display: flex; flex-direction: column; gap: 8px; margin-top: 10px; }
.bl-card {
  border: 1px solid var(--border-base);
  border-radius: 6px;
  padding: 8px;
  display: flex;
  flex-direction: column;
  gap: 6px;
  background: var(--bg-base);
}
.bl-head { display: flex; align-items: center; gap: 6px; }
.bl-idx {
  width: 18px;
  height: 18px;
  border-radius: 4px;
  background: var(--bg-hover-light);
  color: var(--text-secondary);
  font-size: 11px;
  display: flex;
  align-items: center;
  justify-content: center;
  flex-shrink: 0;
}
.bl-title { flex: 1; }
.bl-len { font-size: 11px; color: var(--text-tertiary); text-align: right; }
</style>
