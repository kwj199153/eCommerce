<template>
  <a-modal
    :open="open"
    title="🛰️ 开启竞品监控"
    :width="520"
    centered
    :footer="null"
    @cancel="close"
  >
    <!-- 待监控 ASIN 清单 -->
    <div class="atm-summary">
      <div class="atm-label">本次将开启定时采集的候选（{{ items.length }} 条）</div>
      <div class="atm-asins">
        <a-tag v-for="a in items" :key="a.asin" color="blue">{{ a.asin }}</a-tag>
      </div>
      <div class="atm-note">
        开启监控 ≠ 进入选品库；仅把该 ASIN 纳入监控池，由后台定时抓取
        <b>价格 / BSR / 评论</b> 时序，并开启降价/差评告警。
      </div>
    </div>

    <!-- 分组选择 -->
    <div class="atm-group">
      <div class="atm-label">归入监控分组</div>
      <!-- 快捷创建预设组 -->
      <div class="atm-quick">
        <span class="atm-q-label">快捷分组：</span>
        <a-button v-for="p in QUICK_PRESETS" :key="p.name" size="small" @click="usePreset(p)">
          {{ p.emoji }} {{ p.name }}
        </a-button>
      </div>
      <!-- 已有分组单选 -->
      <a-select
        v-model:value="chosenGroupId"
        placeholder="选择一个已有分组（可跳过，稍后自建）"
        allow-clear
        style="width: 100%"
        class="atm-select"
      >
        <a-select-option v-for="g in pool.groups" :key="g.id" :value="g.id">
          <span class="gdot" :style="{ background: g.color }"></span>{{ g.name }}
        </a-select-option>
      </a-select>
      <!-- 就地新建分组 -->
      <div class="atm-create">
        <a-input
          v-model:value="newGroupName"
          placeholder="或就地新建分组，如：待评估候选"
          style="flex: 1"
          @pressEnter="createNewGroup"
        />
        <a-button type="primary" ghost :disabled="!newGroupName.trim()" @click="createNewGroup">
          <PlusOutlined /> 新建并归入
        </a-button>
      </div>
    </div>

    <div v-if="pool.quotaReached" class="atm-quota">
      ⚠️ 已监控 {{ pool.monitoringCount }}/{{ pool.monitorQuota }}，接近额度上限；超额后需升级套餐（本轮为提示，不拦截）。
    </div>

    <div class="atm-footer">
      <a-space>
        <a-button @click="close">取消</a-button>
        <a-button type="primary" :loading="submitting" @click="confirm">
          <FundOutlined /> 开始监控
        </a-button>
      </a-space>
    </div>
  </a-modal>
</template>

<script setup lang="ts">
import { ref, watch } from 'vue'
import { message } from 'ant-design-vue'
import { PlusOutlined, FundOutlined } from '@ant-design/icons-vue'
import { useMonitorPoolStore, type MonitorFromCandidateInput } from '@/stores/monitorPool'

const props = defineProps<{
  open: boolean
  /** 待监控的候选快照 */
  items: MonitorFromCandidateInput[]
}>()
const emit = defineEmits<{
  (e: 'update:open', v: boolean): void
  (e: 'added', payload: { added: number; existing: number; groupId?: string }): void
}>()

const pool = useMonitorPoolStore()

const QUICK_PRESETS = [
  { name: '待评估候选', emoji: '🧪', kind: 'custom' as const },
  { name: '对标核心竞品', emoji: '🎯', kind: 'product' as const },
  { name: '类目头部标杆', emoji: '🏆', kind: 'brand' as const },
]

const chosenGroupId = ref<string | undefined>(undefined)
const newGroupName = ref('')
const submitting = ref(false)

watch(() => props.open, (v) => {
  if (v) {
    chosenGroupId.value = undefined
    newGroupName.value = ''
  }
})

function close() { emit('update:open', false) }

function usePreset(p: { name: string; kind: 'custom' | 'product' | 'brand' }) {
  const g = pool.groups.find(x => x.name === p.name)
  if (g) { chosenGroupId.value = g.id; return }
  const created = pool.createGroup({ name: p.name, kind: p.kind })
  chosenGroupId.value = created.id
  message.success(`已创建分组「${p.name}」`)
}

function createNewGroup() {
  if (!newGroupName.value.trim()) return
  const g = pool.createGroup({ name: newGroupName.value.trim(), kind: 'custom' })
  chosenGroupId.value = g.id
  newGroupName.value = ''
  message.success(`已创建分组「${g.name}」并选中`)
}

function confirm() {
  const groupId = chosenGroupId.value
  submitting.value = true
  try {
    // 注入当前选择的分组，逐个入池
    const inputs = props.items.map(i => ({ ...i, groupId: groupId ?? null }))
    const res = pool.addManyFromCandidates(inputs)
    emit('added', { added: res.added, existing: res.existing, groupId })
    close()
  } finally {
    submitting.value = false
  }
}
</script>

<style scoped>
.atm-summary, .atm-group { margin-bottom: 16px; }
.atm-label { font-size: 12px; font-weight: 600; color: #262626; margin-bottom: 8px; }
.atm-asins { display: flex; flex-wrap: wrap; gap: 4px; margin-bottom: 6px; }
.atm-note { font-size: 11.5px; color: #8c8c8c; line-height: 1.6; background: #fafafa; border-radius: 6px; padding: 8px 10px; }
.atm-note b { color: #595959; }
.atm-quick { display: flex; align-items: center; gap: 6px; flex-wrap: wrap; margin-bottom: 8px; }
.atm-q-label { font-size: 12px; color: #8c8c8c; }
.atm-select { margin-bottom: 8px; }
.gdot { display: inline-block; width: 8px; height: 8px; border-radius: 50%; margin-right: 6px; }
.atm-create { display: flex; gap: 8px; }
.atm-quota { font-size: 12px; color: #ad6800; background: #fffbe6; border: 1px solid #ffe58f; border-radius: 6px; padding: 8px 10px; margin-bottom: 12px; }
.atm-footer { display: flex; justify-content: flex-end; }
</style>
