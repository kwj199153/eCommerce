<template>
  <ConversationCard
    icon="⚔️"
    title="竞品对比"
    :badge="items.length ? `${items.length} 个` : ''"
    badge-color="purple"
  >
    <div v-if="items.length" class="cp-list">
      <div v-for="(c, i) in items" :key="c.product?.product_id || i" class="cp-item">
        <div class="cp-head">
          <span class="cp-title">{{ c.product?.title || '未知商品' }}</span>
          <a-tag :color="positionColor(c.price_positioning)" class="cp-pos">
            {{ positionLabel(c.price_positioning) }}
          </a-tag>
        </div>
        <div class="cp-metrics">
          <span>{{ money(c.product?.price) }}</span>
          <span class="cp-sep">·</span>
          <span :class="ratingClass(c.product?.rating)">★ {{ rating(c.product?.rating) }}</span>
          <span class="cp-sep">·</span>
          <span>{{ num(c.product?.review_count) }} 评论</span>
          <span class="cp-sep">·</span>
          <span>Listing {{ Math.round(Number(c.listing_quality_score) || 0) }} 分</span>
        </div>
        <div v-if="c.strengths?.length" class="cp-row cp-pro">
          <b>优势</b>{{ c.strengths.join('；') }}
        </div>
        <div v-if="c.weaknesses?.length" class="cp-row cp-con">
          <b>劣势</b>{{ c.weaknesses.join('；') }}
        </div>
      </div>
    </div>
    <div v-else class="cp-empty">{{ summary || '平台未返回可对比的竞品数据。' }}</div>
  </ConversationCard>
</template>

<script setup lang="ts">
import { computed } from 'vue'
import ConversationCard from './ConversationCard.vue'
import { money, num } from './format'
import { bandIndex } from '@/theme/bands'

const props = defineProps<{ data: any }>()

const items = computed<any[]>(() => props.data?.competitors || [])
const summary = computed(() => props.data?.summary || '')

function rating(n: any): string {
  return (Number(n) || 0).toFixed(1)
}

/** 星级（0–5，口径见 bands.ts `rating`）：<4 分预警（橙），≥4 分良好（绿） */
function ratingClass(n: any): string {
  return bandIndex('rating', Number(n) || 0) === 0 ? 'is-good' : 'is-warn'
}

const POSITION_LABEL: Record<string, string> = {
  premium: '高端定价',
  budget: '低价策略',
  competitive: '性价比',
}

function positionLabel(p?: string): string {
  return POSITION_LABEL[p || ''] || '定价未知'
}

function positionColor(p?: string): string {
  if (p === 'premium') return 'gold'
  if (p === 'budget') return 'green'
  if (p === 'competitive') return 'blue'
  return 'default'
}
</script>

<style scoped>
.cp-item {
  padding: var(--space-8) 0;
  border-top: 1px dashed var(--border-base);
}
.cp-item:first-child {
  border-top: none;
  padding-top: 0;
}
.cp-head {
  display: flex;
  align-items: center;
  gap: var(--space-6);
}
.cp-title {
  font-weight: 600;
  color: var(--text-primary);
  word-break: break-word;
}
.cp-pos {
  margin-left: auto;
  flex: none;
}
.cp-metrics {
  margin-top: var(--space-3);
  font-size: var(--font-size-11);
  color: var(--text-tertiary);
}
.cp-sep {
  margin: 0 var(--space-4);
}
.cp-row {
  margin-top: var(--space-3);
  font-size: var(--font-size-11);
  line-height: 1.5;
}
.cp-row b {
  margin-right: var(--space-4);
}
.cp-pro {
  color: var(--success);
}
.cp-con {
  color: var(--danger);
}
.cp-empty {
  color: var(--text-tertiary);
  line-height: 1.6;
}
.is-good {
  color: var(--success);
}
.is-warn {
  color: var(--warning);
}
</style>
