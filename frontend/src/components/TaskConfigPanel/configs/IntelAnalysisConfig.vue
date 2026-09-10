<template>
  <div class="intel-analysis-config">
    <!-- 数据范围说明 -->
    <div class="scope-alert">
      <a-alert
        type="info"
        show-icon
        :message="`数据源：竞品监控池（在池 ${poolCount} 个 · 当前圈选 ${selectedCount} 个）`"
        :description="scopeDesc"
      />
    </div>

    <!-- 时间范围 -->
    <a-form layout="vertical" :model="formState" class="config-form">
      <a-form-item label="分析周期">
        <a-select v-model:value="formState.days" style="width: 100%">
          <a-select-option :value="7">近 7 天</a-select-option>
          <a-select-option :value="14">近 14 天</a-select-option>
          <a-select-option :value="30">近 30 天（默认）</a-select-option>
          <a-select-option :value="90">近 90 天</a-select-option>
        </a-select>
      </a-form-item>

      <!-- 智能问答：允许输入自由问题 -->
      <a-form-item v-if="toolId === 'intel-chat'" label="你的问题">
        <a-textarea
          v-model:value="formState.question"
          :rows="3"
          placeholder="例如：对比这3个竞品过去30天的调价策略，判断他们会不会继续降价冲销量？"
        />
        <div class="form-hint">支持：调价 / BSR排名 / 差评爆发 / 变体上新 / Listing改动 / 库存断货 / 综合判断</div>
      </a-form-item>

      <!-- 输出说明 -->
      <div class="quick-tips">
        <p class="tips-title">{{ tipsTitle }}</p>
        <ul>
          <li>一句话业务解读（而非只甩数据）</li>
          <li>AI 结论 + 竞品池证据表联动（评分/BSR/评论/库存/Listing改动）</li>
          <li>可直接继续追问</li>
        </ul>
      </div>

      <!-- 操作按钮 -->
      <div class="action-bar">
        <a-button type="primary" block @click="handleStart" :loading="loading">
          <PlayCircleOutlined /> {{ ctaLabel }}
        </a-button>
      </div>
    </a-form>
  </div>
</template>

<script setup lang="ts">
import { reactive, ref, computed, watch } from 'vue'
import { PlayCircleOutlined } from '@ant-design/icons-vue'
import { useMonitorPoolStore } from '@/stores/monitorPool'

const props = defineProps<{ currentToolId: string }>()

const emit = defineEmits<{
  (e: 'startAnalysis', params: any): void
}>()

const toolId = computed(() => props.currentToolId)
const pool = useMonitorPoolStore()
const poolCount = computed(() => pool.totalCount)
const selectedCount = computed(() => pool.selectedAsins.length)

const loading = ref(false)

const meta: Record<string, { cta: string; tips: string; question: string }> = {
  'intel-chat': {
    cta: '开始智能分析',
    tips: '💬 竞品智能问答将输出',
    question: '请基于监控池帮我综合分析竞品近期动作，给出运营建议。',
  },
  'intel-weekly': {
    cta: '生成竞品周报',
    tips: '📋 竞品周报将输出',
    question: '请生成本周期竞品周报：谁降价、谁爆发差评、谁改Listing抢流量、促销节奏如何。',
  },
  'intel-anomaly': {
    cta: '检测并解读异动',
    tips: '🚨 异动洞察将输出',
    question: '请检测监控池内近期的异动（BSR暴涨/差评激增/价格骤降/断货），并解释背后原因。',
  },
  'intel-strategy': {
    cta: '开始策略推演',
    tips: '🧠 策略推演将输出',
    question: '请基于监控池竞品动作，推演我方的反制与定价/上新/广告节奏建议。',
  },
}
const m = computed(() => meta[toolId.value] || meta['intel-chat'])
const ctaLabel = computed(() => m.value.cta)
const tipsTitle = computed(() => m.value.tips)

const scopeDesc = computed(() =>
  selectedCount.value
    ? `本次将基于你在监控池勾选的 ${selectedCount} 个竞品进行分析（也可在「竞品监控工作台」调整圈选）。`
    : `监控池当前未圈选竞品，将默认分析全部 ${poolCount.value} 个在池竞品；建议先在「竞品监控工作台」圈选目标竞品。`
)

const formState = reactive({
  days: 30,
  question: '',
})

// 切换工具时重置问题为预置提示
watch(toolId, () => {
  formState.days = 30
  formState.question = ''
})

const handleStart = () => {
  loading.value = true
  setTimeout(() => {
    emit('startAnalysis', {
      tool_id: toolId.value,
      days: formState.days,
      question: (formState.question && formState.question.trim()) || m.value.question,
      asins: pool.selectedAsins.length ? [...pool.selectedAsins] : [],
    })
    loading.value = false
  }, 300)
}
</script>

<style scoped>
.intel-analysis-config { padding: 4px 0; }
.scope-alert { margin-bottom: 14px; }
.scope-alert :deep(.ant-alert) { font-size: 12px; }
.config-form :deep(.ant-form-item) { margin-bottom: 14px; }
.config-form :deep(.ant-form-item-label) { font-size: 13px; font-weight: 500; }
.form-hint { font-size: 11px; color: #8c8c8c; margin-top: 4px; }
.action-bar { margin-top: 16px; padding-top: 12px; border-top: 1px solid #f0f0f0; }
.quick-tips { margin-top: 12px; padding: 12px; background: #f6ffed; border-radius: 8px; border: 1px solid #b7eb8f; }
.tips-title { font-size: 12px; font-weight: 600; color: #389e0d; margin-bottom: 6px; }
.quick-tips ul { margin: 0; padding-left: 18px; font-size: 11.5px; color: #595959; line-height: 1.7; }
</style>
