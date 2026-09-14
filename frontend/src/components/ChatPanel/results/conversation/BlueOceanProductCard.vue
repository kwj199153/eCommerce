<template>
  <ConversationCard
    icon="🌊"
    title="蓝海商品候选"
    :badge="products.length ? `${products.length} 个候选` : `${items.length} 个方向`"
    badge-color="blue"
    :note="scopeNote"
  >
    <!-- ===== 主列表：商品 ===== -->
    <div v-if="products.length" class="bo-list">
      <div v-for="(p, i) in products" :key="p.asin || i" class="bo-item">
        <div class="bo-line">
          <span class="bo-rank">{{ i + 1 }}</span>
          <span class="bo-name">{{ p.title }}</span>
          <button
            class="bo-translate-btn"
            type="button"
            title="翻译标题"
            data-stl-trigger=""
            @click.stop="translateFromEvent(p.title || '', $event)"
          >译</button>
          <span class="bo-roi" :class="roiClass(p.roi ?? p.roi_estimated)">
            ROI {{ pct1(p.roi ?? p.roi_estimated) }}
          </span>
        </div>

        <div class="bo-metrics">
          <a
            v-if="p.asin"
            class="bo-asin"
            :href="`https://www.amazon.com/dp/${p.asin}`"
            target="_blank"
            rel="noopener"
            @click.stop
          >{{ p.asin }} ↗</a>
          <span v-if="p.price != null"><span class="bo-sep">·</span>售价 {{ money(p.price) }}</span>
          <span><span class="bo-sep">·</span>月销 {{ num(p.estimated_monthly_sales) }}</span>
          <span><span class="bo-sep">·</span>评论 {{ num(p.review_count) }}</span>
          <span v-if="p.rating"><span class="bo-sep">·</span>评分 {{ Number(p.rating).toFixed(1) }}</span>
        </div>

        <!-- 市场层：词不再是独立卡片，而是商品的来源标注 -->
        <div v-if="p.source_keyword" class="bo-src">
          来源词 <b>{{ p.source_keyword }}</b>
          <span><span class="bo-sep">·</span>月搜索 {{ num(p.keyword_search_volume) }}</span>
          <span :class="compClass(p.keyword_competition)">
            <span class="bo-sep">·</span>竞争度 {{ pct(p.keyword_competition) }}
          </span>
          <span :class="trendClass(p.keyword_trend)">
            <span class="bo-sep">·</span>{{ trendLabel(p.keyword_trend) }}
          </span>
        </div>
      </div>
    </div>

    <!-- ===== 降级：商品池无匹配，只能给词方向 ===== -->
    <div v-else-if="items.length" class="bo-list">
      <div class="bo-fallback">商品池暂无匹配商品，以下是识别到的蓝海方向：</div>
      <div v-for="(opp, i) in items" :key="`${opp.category}-${i}`" class="bo-item">
        <div class="bo-line">
          <span class="bo-rank">{{ i + 1 }}</span>
          <span class="bo-name">{{ opp.category }}</span>
          <span class="bo-score" :class="scoreClass(opp.opportunity_score)">
            {{ Math.round(Number(opp.opportunity_score) || 0) }} 分
          </span>
        </div>
        <div class="bo-metrics">
          <span>月搜索 {{ num(opp.search_volume) }}</span>
          <span :class="compClass(opp.competition)"><span class="bo-sep">·</span>竞争度 {{ pct(opp.competition) }}</span>
          <span :class="trendClass(opp.trend)"><span class="bo-sep">·</span>{{ trendLabel(opp.trend) }}</span>
        </div>
        <div v-if="opp.reason" class="bo-reason">{{ opp.reason }}</div>
      </div>
    </div>

    <div v-else class="bo-empty">{{ summary || '本次没有评分达标的蓝海机会。' }}</div>
  </ConversationCard>
</template>

<script setup lang="ts">
import { computed } from 'vue'
import ConversationCard from './ConversationCard.vue'
import { translateFromEvent } from '@/composables/useSelectionTranslate'
import { num, money, pct, trendLabel } from './format'

const props = defineProps<{ data: any }>()

/**
 * 主列表 = 商品（products）；词（opportunities）降级为商品的来源标注。
 *
 * 为什么词不再是主列表：词没有 ASIN，既存不进选品库（候选库以 asin 为核心标识），
 * 也无法横向比价/比 ROI。词作为中间产物保留在 payload 里，仅在没有匹配商品时兜底展示。
 */
const products = computed<any[]>(() => props.data?.products || [])
const items = computed<any[]>(() => props.data?.opportunities || [])
const summary = computed(() => props.data?.summary || '')
const scopeNote = computed(() =>
  props.data?.category && props.data.category !== 'all' ? `类目：${props.data.category}` : '全类目扫描',
)

/** ROI 百分比（一位小数） */
function pct1(n: any): string {
  const v = Number(n)
  return Number.isFinite(v) ? `${v.toFixed(1)}%` : '—'
}

/** 预估 ROI：越高越好 */
function roiClass(n: any): string {
  const v = Number(n) || 0
  if (v >= 25) return 'is-good'
  if (v >= 15) return 'is-warn'
  return 'is-bad'
}

/** 机会分：越高越是好机会 */
function scoreClass(score: number): string {
  const s = Number(score) || 0
  if (s >= 70) return 'is-good'
  if (s >= 50) return 'is-mid'
  return 'is-low'
}

/** 竞争度：低 = 好进入（绿），高 = 红海（红） */
function compClass(competition: any): string {
  const c = Number(competition)
  if (!Number.isFinite(c)) return 'is-muted'
  if (c < 0.4) return 'is-good'
  if (c < 0.6) return 'is-warn'
  return 'is-bad'
}

function trendClass(trend?: string): string {
  if (trend === 'rising') return 'is-good'
  if (trend === 'declining' || trend === 'falling') return 'is-bad'
  return 'is-muted'
}
</script>

<style scoped>
.bo-item {
  padding: var(--space-8) 0;
  border-top: 1px dashed var(--border-base);
}
.bo-item:first-child {
  border-top: none;
  padding-top: 0;
}
.bo-line {
  display: flex;
  align-items: flex-start;
  gap: var(--space-6);
}
.bo-rank {
  flex: none;
  width: 16px;
  height: 16px;
  margin-top: var(--space-1);
  border-radius: var(--radius-circle);
  background: var(--bg-card-pill);
  color: var(--text-secondary);
  font-size: var(--font-size-10);
  line-height: 16px;
  text-align: center;
}
.bo-name {
  font-weight: 600;
  color: var(--text-primary);
  line-height: 1.45;
  word-break: break-word;
}
.bo-translate-btn {
  flex: none;
  height: 17px;
  margin-top: var(--space-2);
  padding: 0 var(--space-5);
  border: 1px solid var(--border-strong);
  border-radius: var(--radius-4);
  background: transparent;
  color: var(--text-tertiary);
  font-size: var(--font-size-11);
  line-height: 15px;
  cursor: pointer;
}
.bo-translate-btn:hover {
  color: var(--primary);
  border-color: var(--primary);
}
.bo-roi,
.bo-score {
  margin-left: auto;
  flex: none;
  font-weight: 600;
  white-space: nowrap;
}
.bo-metrics,
.bo-src {
  margin-top: var(--space-3);
  padding-left: var(--space-22);
  font-size: var(--font-size-11);
  color: var(--text-tertiary);
  line-height: 1.6;
}
.bo-src b {
  color: var(--text-secondary);
  font-weight: 600;
}
.bo-asin {
  font-family: var(--font-mono, monospace);
  color: var(--text-secondary);
}
.bo-asin:hover {
  color: var(--primary);
}
.bo-sep {
  margin: 0 var(--space-4);
}
.bo-reason {
  margin-top: var(--space-3);
  padding-left: var(--space-22);
  font-size: var(--font-size-11);
  color: var(--text-secondary);
  line-height: 1.5;
}
.bo-fallback {
  margin-bottom: var(--space-6);
  font-size: var(--font-size-11);
  color: var(--text-tertiary);
}
.bo-empty {
  color: var(--text-tertiary);
  line-height: 1.6;
}
/* 颜色语义：绿=有利（高 ROI/低竞争/上升），红=不利，橙=中间态，灰=中性 */
.is-good {
  color: var(--success);
}
.is-warn {
  color: var(--warning);
}
.is-bad {
  color: var(--danger);
}
.is-mid {
  color: var(--primary);
}
.is-low {
  color: var(--text-tertiary);
}
.is-muted {
  color: var(--text-tertiary);
}
</style>
