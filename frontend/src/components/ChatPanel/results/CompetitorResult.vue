<template>
  <div class="competitor-result">
    <div class="result-header">
      <div class="header-left">
        <span class="result-icon">⚔️</span>
        <span class="result-title">竞品对比结果</span>
        <a-tag color="blue">{{ data.competitors?.length || 0 }} 个竞品</a-tag>
      </div>
      <a-button type="text" size="small" @click="$emit('close')">
        <CloseOutlined />
      </a-button>
    </div>

    <!-- 概览 -->
    <div class="overview-bar">
      <span v-if="data.price_range">💰 ${{ data.price_range.min }} - ${{ data.price_range.max }}</span>
      <span v-else>💰 价格区间：后端未返回</span>
      <span>⭐ {{ data.avg_rating != null ? data.avg_rating.toFixed(1) : '-' }}</span>
      <span>👑 {{ leaderBrand }}</span>
    </div>

    <!-- 对比表格 -->
    <a-table
      :dataSource="data.competitors"
      :columns="columns"
      size="small"
      :pagination="false"
      :scroll="{ y: 220 }"
      rowKey="asin"
    >
      <template #bodyCell="{ column, record }">
        <!-- 性价比：后端 comparison.value_score 真值。★ 该分数量纲不是 0–100
             （= 评分×20/价格×100），所以**不**当百分比进度条用，直接给数值。 -->
        <template v-if="column.key === 'value_score'">
          <span class="value-score">
            {{ record.value_score != null ? Number(record.value_score).toFixed(1) : '-' }}
          </span>
        </template>
        <!-- 综合排名：后端 comparison.overall_ranking[].rank 真值 -->
        <template v-else-if="column.key === 'rank'">
          <a-tag
            v-if="record.rank != null"
            :color="record.rank === 1 ? 'gold' : 'default'"
            size="small"
          >
            #{{ record.rank }}
          </a-tag>
          <span v-else>-</span>
        </template>
      </template>
    </a-table>

    <!-- 结论（后端 comparison.recommendations，含 LLM 生成的竞争结论） -->
    <div v-if="data.recommendation" class="conclusion">
      <div class="conclusion-title">📋 分析结论</div>
      <p>{{ data.recommendation }}</p>
    </div>

    <!-- 差异化分析（后端 comparison.differentiation_analysis 真值） -->
    <div v-if="differentiationText" class="conclusion">
      <div class="conclusion-title">🔍 差异化分析</div>
      <p>{{ differentiationText }}</p>
    </div>
  </div>
</template>

<script setup lang="ts">
import { computed } from 'vue'
import { CloseOutlined } from '@ant-design/icons-vue'

const props = defineProps<{ data: any }>()
defineEmits<{ (e: 'close'): void }>()

const columns = [
  { title: '商品', dataIndex: 'title', key: 'title', ellipsis: true },
  { title: '价格', dataIndex: 'price', key: 'price', width: 65, align: 'right' },
  { title: '评分', dataIndex: 'rating', key: 'rating', width: 50, align: 'center' },
  { title: '评论', dataIndex: 'review_count', key: 'review_count', width: 55, align: 'center' },
  { title: '性价比', dataIndex: 'value_score', key: 'value_score', width: 70, align: 'right' },
  { title: '排名', dataIndex: 'rank', key: 'rank', width: 55, align: 'center' },
]

const leaderBrand = computed(() => {
  const leader = props.data.competitors?.find((c: any) => c.asin === props.data.market_leader)
  return leader?.brand || '-'
})

// ★ 原 getPositionColor / getPositionLabel 已删：它们服务的 `price_positioning`
//   是前端自造字段，后端 /competitor/compare 从不算它 —— 保留就是留一列永远空白的假 UI。
//   后端真算出来的是 value_score（性价比）与 overall_ranking（排名），已在表格中展示。

/**
 * 差异化分析文本。
 *
 * ★ 展平逻辑已下沉到适配层 `utils/toolResultAdapters.ts::flattenDifferentiation`
 *   （唯一实现）—— 放在组件 computed 里**门禁测不到**。组件只负责渲染。
 * ★ 原实现读的是 `key_differentiators` / `differentiators`，这两个键后端**不存在**
 *   ⇒ 恒返回 '' ⇒ 本区块永远不渲染（真数据接线进来却看不见，已修）。
 */
const differentiationText = computed<string>(() => props.data?.differentiation_text || '')
</script>

<style scoped>
.competitor-result {
  background: var(--bg-elevated);
  border-radius: var(--radius-8);
  border: 1px solid var(--border-base);
  margin: var(--space-12) var(--space-16);
}
.result-header {
  display: flex; justify-content: space-between; align-items: center;
  padding: var(--space-10) var(--space-16);
  background: linear-gradient(135deg, #4facfe 0%, #00f2fe 100%);
  color: #fff;
}
.header-left { display: flex; gap: var(--space-8); align-items: center; }
.result-icon { font-size: var(--font-size-18); }
.result-title { font-weight: 600; }

.overview-bar {
  display: flex; gap: var(--space-20); padding: var(--space-10) var(--space-16);
  font-size: var(--font-size-12); border-bottom: 1px solid var(--border-base);
  background: var(--bg-base);
}

.conclusion {
  padding: var(--space-12) var(--space-16); border-top: 1px solid var(--border-base);
}
.conclusion-title { font-weight: 600; margin-bottom: var(--space-6); }
.conclusion p { margin: 0; font-size: var(--font-size-12); line-height: 1.6; color: var(--text-secondary); }
</style>
