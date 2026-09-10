<template>
  <div class="intruder-result" v-if="data">
    <!-- 概览头部 -->
    <div class="result-header" :class="hasHighThreat ? 'alert-mode' : ''">
      <h3>🚨 入侵者检测报告</h3>
      <a-tag :color="hasHighThreat ? 'red' : data.new_competitors?.length > 0 ? 'orange' : 'green'">
        {{ data.new_competitors?.length || 0 }} 个新竞争者
      </a-tag>
    </div>

    <!-- 威胁摘要 -->
    <div v-if="data.threat_summary" class="threat-summary">
      <div class="threat-stat threat-high">
        <span class="ts-label">🔴 高威胁</span>
        <span class="ts-value">{{ data.threat_summary.high || 0 }}</span>
      </div>
      <div class="threat-stat threat-medium">
        <span class="ts-label">🟡 中威胁</span>
        <span class="ts-value">{{ data.threat_summary.medium || 0 }}</span>
      </div>
      <div class="threat-stat threat-low">
        <span class="ts-label">🟢 低威胁</span>
        <span class="ts-value">{{ data.threat_summary.low || 0 }}</span>
      </div>
    </div>

    <!-- 新竞争者列表 -->
    <div v-if="data.new_competitors?.length" class="intruder-list">
      <h4>🔍 发现的新进入者</h4>
      <div
        v-for="(item, i) in data.new_competitors"
        :key="item.asin"
        class="intruder-card"
        :class="'threat-' + item.threat_level"
      >
        <div class="card-header">
          <span class="threat-badge" :class="'badge-' + item.threat_level">
            {{ threatLabel(item.threat_level) }}
          </span>
          <span class="entry-date">入驻: {{ item.entry_date }}</span>
        </div>
        <div class="card-body">
          <strong>{{ item.brand }} — {{ item.title }}</strong>
          <span class="asin-text">{{ item.asin }}</span>
          <span class="price-text">${{ item.price?.toFixed(2) }}</span>
          <span v-if="item.our_product_affected" class="affected-tag">⚠️ 影响我方产品</span>
        </div>
        <ul class="reason-list">
          <li v-for="(r, j) in item.reasons" :key="j">{{ r }}</li>
        </ul>
      </div>
    </div>

    <!-- 应对策略 -->
    <div v-if="data.response_strategies?.length" class="strategy-section">
      <h4>🛡️ 应对策略建议</h4>
      <div v-for="(s, i) in data.response_strategies" :key="i" class="strategy-item" :class="'prio-' + s.priority.toLowerCase()">
        <div class="strat-header">
          <a-tag :color="s.priority === 'P0' ? 'red' : s.priority === 'P1' ? 'orange' : 'blue'" style="font-size: 11px;">{{ s.priority }}</a-tag>
          <strong>{{ s.target }}</strong>
          <span class="strat-type">{{ s.strategy }}</span>
        </div>
        <ul class="action-steps">
          <li v-for="(a, j) in s.actions" :key="j">{{ a }}</li>
        </ul>
      </div>
    </div>

    <div class="result-footer">
      <a-button size="small" @click="$emit('close')">关闭</a-button>
    </div>
  </div>
</template>

<script setup lang="ts">
import { computed } from 'vue'

const props = defineProps<{ data: any }>()
defineEmits<{ (e: 'close'): void }>()

const hasHighThreat = computed(() => {
  return props.data.new_competitors?.some((c: any) => c.threat_level === 'high') || false
})

const threatLabel = (level: string) => ({ high: '高威胁', medium: '中威胁', low: '低威胁' }[level] || level)
</script>

<style scoped>
.intruder-result { padding: 16px; background: #fff; border-radius: 8px; }
.result-header { display: flex; align-items: center; justify-content: space-between; margin-bottom: 14px; }
.result-header.alert-mode { background: #fff1f0; margin: -16px -16px 14px; padding: 12px 16px; border-radius: 8px 8px 0 0; }
.result-header h3 { margin: 0; font-size: 16px; }
.threat-summary { display: grid; grid-template-columns: repeat(3, 1fr); gap: 10px; margin-bottom: 14px; }
.threat-stat { text-align: center; padding: 10px; border-radius: 8px; }
.ts-label { display: block; font-size: 11.5px; margin-bottom: 2px; }
.ts-value { font-size: 24px; font-weight: 700; }
.threat-high { background: #fff1f0; }
.threat-high .ts-value { color: #cf1322; }
.threat-medium { background: #fffbe6; }
.threat-medium .ts-value { color: #d46b08; }
.threat-low { background: #f6ffed; }
.threat-low .ts-value { color: #389e0d; }
.intruder-list h4 { margin: 0 0 10px; font-size: 13px; color: #262626; }
.intruder-card { padding: 12px; border-radius: 8px; margin-bottom: 10px; border-left: 4px solid; }
.intruder-card.threat-high { background: #fff1f0; border-color: #ff4d4f; }
.intruder-card.threat-medium { background: #fffbe6; border-color: #faad14; }
.intruder-card.threat-low { background: #f6ffed; border-color: #52c41a; }
.card-header { display: flex; justify-content: space-between; align-items: center; margin-bottom: 6px; }
.threat-badge { font-size: 11px; font-weight: 600; padding: 2px 8px; border-radius: 10px; }
.badge-high { background: #ff4d4f; color: #fff; }
.badge-medium { background: #faad14; color: #fff; }
.badge-low { background: #52c41a; color: #fff; }
.entry-date { font-size: 11px; color: #8c8c8c; }
.card-body { font-size: 13px; margin-bottom: 6px; }
.asin-text { font-family: monospace; color: #8c8c8c; font-size: 11.5px; margin-left: 8px; }
.price-text { font-weight: 600; color: #1890ff; margin-left: 8px; }
.affected-tag { margin-left: 8px; font-size: 11.5px; }
.reason-list { margin: 4px 0 0; padding-left: 18px; font-size: 11.5px; line-height: 1.5; color: #595959; }
.strategy-section { margin-top: 16px; padding: 14px; background: #e6f7ff; border-radius: 8px; }
.strategy-section h4 { margin: 0 0 10px; font-size: 13px; }
.strategy-item { padding: 10px; background: #fff; border-radius: 6px; margin-bottom: 8px; }
.strat-header { display: flex; align-items: center; gap: 8px; margin-bottom: 6px; }
.strat-type { font-size: 11px; color: #8c8c8c; }
.action-steps { margin: 0; padding-left: 20px; font-size: 12px; line-height: 1.6; }
.result-footer { text-align: center; padding-top: 12px; border-top: 1px solid #f0f0f0; margin-top: 12px; }
</style>
