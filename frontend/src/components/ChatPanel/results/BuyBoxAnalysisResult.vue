<template>
  <div class="buybox-result" v-if="data">
    <!-- 概览头部 -->
    <div class="result-header">
      <h3>🛒 Buy Box 竞争分析</h3>
      <a-tag color="blue">{{ data.analyzed_count || 0 }} 个产品</a-tag>
    </div>

    <!-- 产品分析卡片 -->
    <div v-for="(item, idx) in data.analyses" :key="item.asin" class="buybox-card">
      <div class="card-header">
        <span class="product-name">{{ item.brand }} — {{ item.product }}</span>
        <span class="asin-text">{{ item.asin }}</span>
        <a-progress
          :percent="Math.round(item.competitiveness_score || 0)"
          size="small"
          :stroke-color="scoreColor(item.competitiveness_score)"
          :width="70"
        />
      </div>

      <!-- Buy Box 详情 -->
      <div v-if="item.buy_box_analysis" class="bb-details">
        <!-- 赢家列表 -->
        <div class="sellers-section">
          <h5>Buy Box 卖家列表</h5>
          <a-table
            :dataSource="item.buy_box_analysis.sellers || []"
            :columns="sellerColumns"
            size="small"
            row-key="seller_name"
            :pagination="false"
          >
            <template #bodyCell="{ column, record }">
              <template v-if="column.key === 'price'">
                <strong>${{ record.price?.toFixed(2) }}</strong>
              </template>
              <template v-else-if="column.key === 'status'">
                <a-badge :status="record.in_stock ? 'success' : 'error'" :text="record.in_stock ? '有货' : '缺货'" />
              </template>
              <template v-else-if="column.key === 'winner'">
                <a-tag v-if="record.is_winner" color="gold">👑 赢家</a-tag>
                <span v-else style="color: var(--text-disabled);">-</span>
              </template>
            </template>
          </a-table>
        </div>

        <!-- 关键因素 -->
        <div v-if="item.buy_box_analysis.factors" class="factors-section">
          <h5>关键影响因素</h5>
          <div class="factors-grid">
            <div
              v-for="(f, k) in item.buy_box_analysis.factors"
              :key="k"
              class="factor-item"
            >
              <span class="factor-name">{{ factorLabel(k) }}</span>
              <a-progress
                :percent="f.score || 50"
                size="small"
                :stroke-color="factorColor(f.status)"
                :show-info="false"
                style="flex: 1;"
              />
              <span class="factor-status">{{ f.status || '-' }}</span>
            </div>
          </div>
        </div>
      </div>
    </div>

    <!-- 最佳实践 -->
    <div v-if="data.best_practices?.length" class="practices-box">
      <p><strong>💡 提升 Buy Box 赢取率建议：</strong></p>
      <ul>
        <li v-for="(bp, i) in data.best_practices" :key="i">{{ bp }}</li>
      </ul>
    </div>

    <div class="result-footer">
      <a-button size="small" @click="$emit('close')">关闭</a-button>
    </div>
  </div>
</template>

<script setup lang="ts">
defineProps<{ data: any }>()
defineEmits<{ (e: 'close'): void }>()

const sellerColumns = [
  { title: '卖家', dataIndex: 'seller_name', key: 'seller_name', width: 140 },
  { title: '价格', key: 'price', width: 80 },
  { title: '运费', dataIndex: 'shipping', key: 'shipping', width: 65 },
  { title: '库存', key: 'status', width: 60 },
  { title: '赢家', key: 'winner', width: 65 },
]

const scoreColor = (score: number) => {
  if (score >= 75) return '#52c41a'
  if (score >= 50) return '#faad14'
  return '#ff4d4f'
}

const factorColor = (status: string) => ({
  excellent: '#52c41a',
  good: '#1890ff',
  fair: '#faad14',
  poor: '#ff4d4f',
}[status] || '#d9d9d9')

const factorLabel = (key: string | number) => ({
  price_competitiveness: '价格竞争力',
  shipping_speed: '配送速度',
  seller_rating: '卖家评分',
  fulfillment_method: '履约方式',
  availability: '可用性',
  feedback_quality: '反馈质量',
}[key] || key)
</script>

<style scoped>
.buybox-result { padding: 16px; background: var(--bg-elevated); border-radius: 8px; }
.result-header { display: flex; align-items: center; justify-content: space-between; margin-bottom: 14px; }
.result-header h3 { margin: 0; font-size: 16px; }
.buybox-card { background: var(--bg-base); border-radius: 10px; padding: 14px; margin-bottom: 12px; border: 1px solid #f0f0f0; }
.card-header { display: flex; align-items: center; gap: 10px; margin-bottom: 12px; flex-wrap: wrap; }
.product-name { font-weight: 600; font-size: 13.5px; }
.asin-text { font-family: monospace; font-size: 11.5px; color: var(--text-tertiary); }
.sellers-section h5, .factors-section h5 { margin: 0 0 8px; font-size: 12.5px; color: var(--text-secondary); }
.sellers-section { margin-bottom: 12px; }
.factors-section { padding-top: 8px; border-top: 1px solid #eee; }
.factors-grid { display: flex; flex-direction: column; gap: 6px; }
.factor-item { display: flex; align-items: center; gap: 8px; font-size: 11.5px; }
.factor-name { min-width: 85px; color: var(--text-secondary); }
.factor-status { min-width: 40px; text-align: right; font-weight: 600; font-size: 11px; }
.practices-box { padding: 12px; background: #fcffe6; border-radius: 8px; font-size: 12.5px; line-height: 1.7; }
.practices-box p { margin: 0 0 6px; }
.practices-box ul { margin: 0; padding-left: 18px; }
.result-footer { text-align: center; padding-top: 12px; border-top: 1px solid #f0f0f0; margin-top: 12px; }
</style>
