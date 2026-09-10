<template>
  <div v-if="data && data.per_asin && data.per_asin.length" class="cie-box">
    <div class="cie-head">
      <span class="cie-title">📊 分析证据（来自统一竞品池 · 池内共 {{ data.pool_total }} 个）</span>
      <a-tag color="default" style="margin-left: auto">{{ intentLabel }}</a-tag>
    </div>

    <a-table
      :data-source="data.per_asin"
      :columns="columns"
      :pagination="false"
      size="small"
      row-key="asin"
      :scroll="{ x: 1150 }"
    >
      <template #bodyCell="{ column, record }">
        <!-- 竞品 -->
        <template v-if="column.key === 'cmp'">
          <div class="cie-cmp">
            <b class="cie-brand">{{ record.brand }}</b>
            <span class="cie-asin">{{ record.asin }}</span>
          </div>
        </template>

        <!-- 价格 -->
        <template v-else-if="column.key === 'price'">
          <span>{{ money(record.latest_price) }}&nbsp;</span>
          <span :class="['cie-d', record.price_change_7d < 0 ? 'cie-down' : record.price_change_7d > 0 ? 'cie-up' : '']">
            {{ pct(record.price_change_7d) }}
          </span>
        </template>

        <!-- BSR -->
        <template v-else-if="column.key === 'bsr'">
          <span>#{{ record.latest_bsr }}&nbsp;</span>
          <span :class="['cie-d', record.bsr_trend_30d > 100 ? 'cie-down' : record.bsr_trend_30d < -100 ? 'cie-up' : '']">
            {{ record.bsr_trend_30d >= 0 ? '↓' : '↑' }}{{ Math.abs(record.bsr_trend_30d) }}
          </span>
        </template>

        <!-- 评分 -->
        <template v-else-if="column.key === 'rating'">
          <span :style="{ color: record.rating < 4 ? '#fa541c' : '#52c41a' }">★ {{ Number(record.rating).toFixed(1) }}</span>
        </template>

        <!-- 评论 -->
        <template v-else-if="column.key === 'review'">
          <span>+{{ record.reviews_added_7d }}</span>
          <a-tag v-if="record.negative_7d > 0" color="red" style="margin-left: 4px">差评{{ record.negative_7d }}</a-tag>
        </template>

        <!-- 促销天数 -->
        <template v-else-if="column.key === 'promo'">
          <span>{{ record.promo_days_30d }} 天</span>
        </template>

        <!-- 变体数 -->
        <template v-else-if="column.key === 'variation'">
          <span>{{ record.variation_count }}</span>
        </template>

        <!-- Listing 改动 -->
        <template v-else-if="column.key === 'listing'">
          <span v-if="record.listing_changes && record.listing_changes.length">
            {{ record.listing_changes.map((c: any) => c.field).join('、') }}
          </span>
          <span v-else class="cie-muted">无</span>
        </template>

        <!-- 库存 -->
        <template v-else-if="column.key === 'stock'">
          <a-tag :color="stockColor(record.stock_status)">{{ stockLabel(record.stock_status) }}</a-tag>
        </template>

        <!-- 预估月销 -->
        <template v-else-if="column.key === 'sales'">
          <span>{{ Number(record.est_monthly_sales || 0).toLocaleString() }}</span>
        </template>
      </template>
    </a-table>
  </div>
</template>

<script setup lang="ts">
import { computed } from 'vue'

const props = defineProps<{ data: any }>()

const intentLabelMap: Record<string, string> = {
  price: '价格/促销',
  bsr: 'BSR 排名',
  review: '评论/星级',
  variation: '变体',
  listing: 'Listing 快照',
  stock: '库存/断货',
  anomaly: '异动洞察',
  weekly: '周报总结',
  general: '综合',
  strategy: '策略推演',
}
const intentLabel = computed(() => intentLabelMap[props.data?.intent] || '综合')

function money(n: number) {
  return '$' + (Number.isFinite(n) ? n.toFixed(2) : '0.00')
}
function pct(n: number) {
  if (n == null) return '-'
  return (n > 0 ? '+' : '') + n + '%'
}
function stockLabel(s: string) {
  return s === 'in_stock' ? '充足' : s === 'low_stock' ? '低库存' : '已断货'
}
function stockColor(s: string) {
  return s === 'in_stock' ? 'green' : s === 'low_stock' ? 'orange' : 'red'
}

const columns: any[] = [
  { title: '竞品', key: 'cmp', width: 170, fixed: 'left' },
  { title: '现价 / 7日', key: 'price', width: 120 },
  { title: 'BSR / 30日', key: 'bsr', width: 120 },
  { title: '评分', key: 'rating', width: 76 },
  { title: '评论(7日/差评)', key: 'review', width: 140 },
  { title: '促销(30日)', key: 'promo', width: 96 },
  { title: '变体', key: 'variation', width: 64 },
  { title: 'Listing 改动', key: 'listing', width: 150 },
  { title: '库存', key: 'stock', width: 90 },
  { title: '预估月销', key: 'sales', width: 100 },
]
</script>

<style scoped>
.cie-box {
  margin-top: 10px;
  border: 1px solid #d9f7be;
  border-radius: 8px;
  padding: 10px 12px;
  background: linear-gradient(180deg, #fcfff5, #ffffff);
}
.cie-head {
  display: flex;
  align-items: center;
  gap: 8px;
  margin-bottom: 8px;
}
.cie-title {
  font-size: 13px;
  font-weight: 600;
  color: #237804;
}
.cie-cmp {
  display: flex;
  flex-direction: column;
}
.cie-brand {
  font-size: 12px;
  line-height: 1.3;
}
.cie-asin {
  font-size: 10px;
  color: #8c8c8c;
  font-family: monospace;
}
.cie-muted {
  color: #bbb;
}
.cie-d {
  font-size: 11px;
}
.cie-up {
  color: #52c41a;
}
.cie-down {
  color: #f5222d;
}
</style>
