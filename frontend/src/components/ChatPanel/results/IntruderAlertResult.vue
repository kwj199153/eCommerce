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
          <a-tag :color="s.priority === 'P0' ? 'red' : s.priority === 'P1' ? 'orange' : 'blue'" style="font-size: var(--font-size-11);">{{ s.priority }}</a-tag>
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
.intruder-result { padding: var(--space-16); background: var(--bg-elevated); border-radius: var(--radius-8); }
.result-header { display: flex; align-items: center; justify-content: space-between; margin-bottom: var(--space-14); }
.result-header.alert-mode { background: var(--danger-bg); margin: -16px -16px var(--space-14); padding: var(--space-12) var(--space-16); border-radius: var(--radius-8) var(--radius-8) 0 0; }
.result-header h3 { margin: 0; font-size: var(--font-size-16); }
.threat-summary { display: grid; grid-template-columns: repeat(3, 1fr); gap: var(--space-10); margin-bottom: var(--space-14); }
.threat-stat { text-align: center; padding: var(--space-10); border-radius: var(--radius-8); }
.ts-label { display: block; font-size: var(--font-size-11-5); margin-bottom: var(--space-2); }
.ts-value { font-size: var(--font-size-24); font-weight: 700; }
.threat-high { background: var(--danger-bg); }
.threat-high .ts-value { color: var(--danger-strong); }
.threat-medium { background: var(--warning-bg); }
.threat-medium .ts-value { color: var(--orange-strong); }
.threat-low { background: var(--success-bg); }
.threat-low .ts-value { color: var(--success); }
.intruder-list h4 { margin: 0 0 var(--space-10); font-size: var(--font-size-13); color: var(--text-primary); }
.intruder-card { padding: var(--space-12); border-radius: var(--radius-8); margin-bottom: var(--space-10); border-left: 4px solid; }
.intruder-card.threat-high { background: var(--danger-bg); border-color: var(--danger); }
.intruder-card.threat-medium { background: var(--warning-bg); border-color: var(--warning); }
.intruder-card.threat-low { background: var(--success-bg); border-color: var(--success); }
.card-header { display: flex; justify-content: space-between; align-items: center; margin-bottom: var(--space-6); }
.threat-badge { font-size: var(--font-size-11); font-weight: 600; padding: var(--space-2) var(--space-8); border-radius: var(--radius-10); }
.badge-high { background: var(--danger); color: #fff; }
.badge-medium { background: var(--warning); color: #fff; }
.badge-low { background: var(--success); color: #fff; }
.entry-date { font-size: var(--font-size-11); color: var(--text-tertiary); }
.card-body { font-size: var(--font-size-13); margin-bottom: var(--space-6); }
.asin-text { font-family: monospace; color: var(--text-tertiary); font-size: var(--font-size-11-5); margin-left: var(--space-8); }
.price-text { font-weight: 600; color: var(--primary); margin-left: var(--space-8); }
.affected-tag { margin-left: var(--space-8); font-size: var(--font-size-11-5); }
.reason-list { margin: var(--space-4) 0 0; padding-left: var(--space-18); font-size: var(--font-size-11-5); line-height: 1.5; color: var(--text-secondary); }
.strategy-section { margin-top: var(--space-16); padding: var(--space-14); background: var(--info-bg); border-radius: var(--radius-8); }
.strategy-section h4 { margin: 0 0 var(--space-10); font-size: var(--font-size-13); }
.strategy-item { padding: var(--space-10); background: var(--bg-elevated); border-radius: var(--radius-6); margin-bottom: var(--space-8); }
.strat-header { display: flex; align-items: center; gap: var(--space-8); margin-bottom: var(--space-6); }
.strat-type { font-size: var(--font-size-11); color: var(--text-tertiary); }
.action-steps { margin: 0; padding-left: var(--space-20); font-size: var(--font-size-12); line-height: 1.6; }
.result-footer { text-align: center; padding-top: var(--space-12); border-top: 1px solid var(--border-base); margin-top: var(--space-12); }
</style>
