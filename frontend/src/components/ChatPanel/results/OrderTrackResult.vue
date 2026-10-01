<template>
  <div
    v-if="data"
    class="order-track-result"
  >
    <!-- 订单头部 -->
    <div
      class="order-header"
      :class="'status-' + view.header.tone"
    >
      <span class="status-icon">{{ view.header.icon }}</span>
      <div class="header-info">
        <h3>订单 {{ view.header.orderId }}</h3>
        <span class="status-text">{{ view.header.statusText }}</span>
      </div>
    </div>

    <!-- 订单详情
         ★ 第 292 轮：字段清单收归 `utils/orderTracking.ts` —— 此前本组件硬编码
           一份、对话通道（`replies/customerService.ts`）另有一份、结果摘要
           （`composables/chat/resultSummary.ts`）还有第三份，三份靠人肉同步。
           现在本模板只负责**摆版面**，「有哪些字段、标签叫什么」全在真源里。 -->
    <div class="order-details">
      <div class="detail-grid">
        <div
          v-for="f in view.base"
          :key="f.key"
          class="detail-item"
        >
          <span class="label">{{ f.label }}</span>
          <span
            class="value"
            :class="{ amount: f.key === 'total_text', 'product-name': f.key === 'product_name' }"
          >{{ f.value }}</span>
        </div>
      </div>
    </div>

    <!-- 物流信息
         ★ 原实现用 `tracking_number` 当唯一开关 —— 真数据里它可能为空 ⇒ 整段
           （连「预计送达」）一起被吞掉。现在由真源决定「物流组里有没有行」，
           有任一项就整块出现；运单号/承运商/轨迹**只在后端给了值时才渲染**，绝不编造。 -->
    <div
      v-if="view.hasLogistics"
      class="logistics-section"
    >
      <h4>🚚 物流信息</h4>
      <div class="logistics-card">
        <div
          v-for="f in view.logistics"
          :key="f.key"
          class="log-row"
        >
          <span class="log-label">{{ f.label }}</span>
          <code
            v-if="f.mono"
            class="log-value tracking-code"
          >{{ f.value }}</code>
          <span
            v-else
            class="log-value"
            :class="{ 'delivery-date': f.emphasis }"
          >{{ f.value }}</span>
        </div>
      </div>
    </div>

    <!-- 数据来源：演示数据不得冒充真实订单 -->
    <div
      v-if="sourceNote"
      class="source-note"
    >
      {{ sourceNote }}
    </div>

    <!-- 操作提示 -->
    <div class="action-hints">
      <p>💡 还有其他关于这个订单的问题吗？可以直接在对话框中继续提问。</p>
    </div>

    <div class="result-footer">
      <a-button
        size="small"
        @click="$emit('close')"
      >
        关闭
      </a-button>
    </div>
  </div>
</template>

<script setup lang="ts">
import { computed } from 'vue'
import { buildOrderTrackingView, orderSourceNote } from '@/utils/orderTracking'

const props = defineProps<{ data: any }>()
defineEmits<{ (e: 'close'): void }>()

/**
 * ★ 第 292 轮：状态三态 / 图标 / 金额文案 / 字段清单**全部收归**
 *   `utils/orderTracking.ts`。本组件此前自己维护一份 `TONE_OF` + 一份硬编码
 *   字段清单，与对话通道那份对不上（这边有运单号、那边连运单号都没进模板；
 *   两边都没渲染轨迹）⇒ 同一判定两份实现的经典形态。现在只消费不复制。
 */
const view = computed(() => buildOrderTrackingView(props.data))
const sourceNote = computed(() => orderSourceNote(view.value))
</script>

<style scoped>
.source-note {
  margin-bottom: var(--space-14); padding: var(--space-8) var(--space-12);
  background: var(--warning-bg); border: 1px solid var(--warning-border);
  border-radius: var(--radius-8); font-size: var(--font-size-12); color: var(--warning);
}
.order-track-result { padding: var(--space-16); background: var(--bg-elevated); border-radius: var(--radius-8); }

.order-header {
  display: flex; align-items: center; gap: var(--space-14);
  padding: var(--space-16) var(--space-20); border-radius: var(--radius-12); margin-bottom: var(--space-14);
}
.status-delivered { background: var(--success-bg); border: 1px solid var(--success-border); }
.status-shipped { background: var(--info-bg); border: 1px solid var(--info-border); }
.status-processing { background: var(--warning-bg); border: 1px solid var(--warning-border); }
.status-unknown { background: var(--bg-base); border: 1px solid var(--border-base); }

.status-icon { font-size: var(--font-size-32); }
.header-info h3 { margin: 0; font-size: var(--font-size-16); color: var(--text-primary); font-family: monospace; }
.status-text { font-size: var(--font-size-13); font-weight: 500; margin-top: var(--space-2); }
.status-delivered .status-text { color: var(--success); }
.status-shipped .status-text { color: var(--primary); }
.status-processing .status-text { color: var(--warning); }

.order-details { margin-bottom: var(--space-14); }
.detail-grid { display: grid; grid-template-columns: 1fr 1fr; gap: var(--space-10); }
.detail-item {
  padding: var(--space-10) var(--space-12); background: var(--bg-base); border-radius: var(--radius-8);
}
.detail-item .label { display: block; font-size: var(--font-size-11); color: var(--text-tertiary); margin-bottom: var(--space-3); }
.detail-item .value { font-size: var(--font-size-13-5); color: var(--text-primary); font-weight: 500; }
.product-name { font-weight: 600; }
.amount { font-size: var(--font-size-17) !important; font-weight: 700; color: var(--primary); }

.logistics-section { margin-bottom: var(--space-14); }
.logistics-section h4 { font-size: var(--font-size-14); font-weight: 600; color: var(--text-primary); margin-bottom: var(--space-8); padding-bottom: var(--space-6); border-bottom: 1px solid var(--border-base); }
.logistics-card { padding: var(--space-14); background: var(--info-bg); border-radius: var(--radius-8); border: 1px solid var(--info-border); }
.log-row { display: flex; justify-content: space-between; align-items: center; margin-bottom: var(--space-8); }
.log-row:last-of-type { margin-bottom: 0; }
.log-label { font-size: var(--font-size-12); color: var(--text-secondary); }
.log-value { font-size: var(--font-size-13); color: var(--text-primary); font-weight: 500; }
.tracking-code { font-family: monospace; background: var(--bg-elevated); padding: var(--space-2) var(--space-6); border-radius: var(--radius-4); font-size: var(--font-size-12-5); }
.delivery-date { color: var(--primary); font-weight: 600; }

.action-hints { padding: var(--space-10) var(--space-14); background: var(--bg-base); border-radius: var(--radius-8); font-size: var(--font-size-12-5); color: var(--text-secondary); line-height: 1.5; }

.result-footer { text-align: center; padding-top: var(--space-12); border-top: 1px solid var(--border-base); }
</style>
