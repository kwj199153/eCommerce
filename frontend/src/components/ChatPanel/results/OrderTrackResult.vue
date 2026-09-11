<template>
  <div class="order-track-result" v-if="data">
    <!-- 订单头部 -->
    <div class="order-header" :class="'status-' + (data.order?.status || 'unknown')">
      <span class="status-icon">{{ statusIcon(data.order?.status) }}</span>
      <div class="header-info">
        <h3>订单 {{ data.order?.order_id || '-' }}</h3>
        <span class="status-text">{{ data.order?.status_text || '未知状态' }}</span>
      </div>
    </div>

    <!-- 订单详情 -->
    <div class="order-details">
      <div class="detail-grid">
        <div class="detail-item">
          <span class="label">下单时间</span>
          <span class="value">{{ data.order?.created_at || '-' }}</span>
        </div>
        <div class="detail-item">
          <span class="label">商品</span>
          <span class="value product-name">{{ data.order?.product_name || '-' }}</span>
        </div>
        <div class="detail-item">
          <span class="label">数量</span>
          <span class="value">{{ data.order?.quantity || 1 }} 件</span>
        </div>
        <div class="detail-item">
          <span class="label">金额</span>
          <span class="value amount">${{ Number(data.order?.total || 0).toFixed(2) }}</span>
        </div>
      </div>
    </div>

    <!-- 物流信息（已发货时显示） -->
    <div v-if="data.order?.tracking_number" class="logistics-section">
      <h4>🚚 物流信息</h4>
      <div class="logistics-card">
        <div class="log-row">
          <span class="log-label">快递单号</span>
          <code class="log-value tracking-code">{{ data.order.tracking_number }}</code>
        </div>
        <div class="log-row">
          <span class="log-label">承运商</span>
          <span class="log-value">{{ data.order.carrier || '-' }}</span>
        </div>
        <div class="log-row">
          <span class="log-label">预计送达</span>
          <span class="log-value delivery-date">{{ data.order.estimated_delivery || '-' }}</span>
        </div>
        <a-button type="link" size="small" style="padding: 0;">查看详细物流轨迹 →</a-button>
      </div>
    </div>

    <!-- 操作提示 -->
    <div class="action-hints">
      <p>💡 还有其他关于这个订单的问题吗？可以直接在对话框中继续提问。</p>
    </div>

    <div class="result-footer">
      <a-button size="small" @click="$emit('close')">关闭</a-button>
    </div>
  </div>
</template>

<script setup lang="ts">
defineProps<{ data: any }>()
defineEmits<{ (e: 'close'): void }>()

const statusIcon = (s: string) => ({
  delivered: '✅',
  shipped: '🚚',
  processing: '⏳',
}[s] || '📦')
</script>

<style scoped>
.order-track-result { padding: 16px; background: var(--bg-elevated); border-radius: 8px; }

.order-header {
  display: flex; align-items: center; gap: 14px;
  padding: 16px 20px; border-radius: 12px; margin-bottom: 14px;
}
.status-delivered { background: #f6ffed; border: 1px solid #b7eb8f; }
.status-shipped { background: #e6f7ff; border: 1px solid #91d5ff; }
.status-processing { background: var(--bg-elevated)be6; border: 1px solid #ffe58f; }
.status-unknown { background: var(--bg-base); border: 1px solid #f0f0f0; }

.status-icon { font-size: 32px; }
.header-info h3 { margin: 0; font-size: 16px; color: var(--text-primary); font-family: monospace; }
.status-text { font-size: 13px; font-weight: 500; margin-top: 2px; }
.status-delivered .status-text { color: #52c41a; }
.status-shipped .status-text { color: #1890ff; }
.status-processing .status-text { color: #faad14; }

.order-details { margin-bottom: 14px; }
.detail-grid { display: grid; grid-template-columns: 1fr 1fr; gap: 10px; }
.detail-item {
  padding: 10px 12px; background: var(--bg-base); border-radius: 8px;
}
.detail-item .label { display: block; font-size: 11px; color: var(--text-tertiary); margin-bottom: 3px; }
.detail-item .value { font-size: 13.5px; color: var(--text-primary); font-weight: 500; }
.product-name { font-weight: 600; }
.amount { font-size: 17px !important; font-weight: 700; color: #1890ff; }

.logistics-section { margin-bottom: 14px; }
.logistics-section h4 { font-size: 14px; font-weight: 600; color: var(--text-primary); margin-bottom: 8px; padding-bottom: 6px; border-bottom: 1px solid #f0f0f0; }
.logistics-card { padding: 14px; background: #e6f7ff; border-radius: 8px; border: 1px solid #91d5ff; }
.log-row { display: flex; justify-content: space-between; align-items: center; margin-bottom: 8px; }
.log-row:last-of-type { margin-bottom: 0; }
.log-label { font-size: 12px; color: var(--text-secondary); }
.log-value { font-size: 13px; color: var(--text-primary); font-weight: 500; }
.tracking-code { font-family: monospace; background: var(--bg-elevated); padding: 2px 6px; border-radius: 4px; font-size: 12.5px; }
.delivery-date { color: #1890ff; font-weight: 600; }

.action-hints { padding: 10px 14px; background: var(--bg-base); border-radius: 8px; font-size: 12.5px; color: var(--text-secondary); line-height: 1.5; }

.result-footer { text-align: center; padding-top: 12px; border-top: 1px solid #f0f0f0; }
</style>
