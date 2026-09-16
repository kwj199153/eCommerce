<template>
  <div class="subscription-container">
    <a-page-header title="订阅 & 计费" @back="router.back()" />

    <!-- ====== 当前套餐状态卡片 ====== -->
    <div v-if="subscription" class="current-plan-banner" :class="planStatusClass">
      <div class="banner-left">
        <div class="plan-badge">
          <CrownFilled v-if="isPremiumPlan" style="color: var(--gold)" />
          <CrownOutlined v-else />
          <span>{{ subscription.plan.display_name }}</span>
        </div>
        <div class="plan-price">
          ¥{{ subscription.plan.price_monthly }}<span class="period">/月</span>
          <a-tag v-if="subscription.status === 'trialing'" color="orange">试用中</a-tag>
          <a-tag v-else-if="subscription.cancel_at_period_end" color="orange">即将到期</a-tag>
          <a-tag v-else-if="subscription.status === 'active'" color="green">正常</a-tag>
          <a-tag v-else color="red">{{ statusLabel }}</a-tag>
        </div>
        <div class="period-text">
          当前周期: {{ formatDate(subscription.period.start) }} ~
          {{ formatDate(subscription.period.end) || '永久有效' }}
        </div>
      </div>
      <div class="banner-right">
        <a-button
          v-if="!subscription.cancel_at_period_end && subscription.status !== 'cancelled'"
          type="primary"
          ghost
          @click="showUpgradeModal = true"
        >
          升级套餐
        </a-button>
        <a-button
          v-if="subscription.cancel_at_period_end"
          type="primary"
          ghost
          :loading="resuming"
          @click="handleResume"
        >
          恢复订阅
        </a-button>
      </div>
    </div>

    <!-- 无订阅时的提示 -->
    <a-result
      v-else
      title="尚未订阅任何套餐"
      sub-title="选择一个适合你的方案开始使用全部功能"
      style="margin-bottom: var(--space-24)"
    >
      <template #extra>
        <a-button type="primary" size="large" @click="showUpgradeModal = true">
          选择套餐
        </a-button>
      </template>
    </a-result>

    <!-- ====== 用量仪表盘 ====== -->
    <a-card title="本月用量" :bordered="false" class="usage-card">
      <a-row :gutter="[16, 16]">
        <a-col :xs="24" :sm="12" :md="6">
          <div class="usage-metric">
            <div class="metric-label">API 调用</div>
            <a-progress
              type="dashboard"
              :percent="usagePct('api_calls')"
              :stroke-color="usageColor('api_calls')"
              :format="() => `${used('api_calls')}/${limit('api_calls')}`"
            />
          </div>
        </a-col>
        <a-col :xs="24" :sm="12" :md="6">
          <div class="usage-metric">
            <div class="metric-label">Agent 对话</div>
            <a-progress
              type="dashboard"
              :percent="usagePct('agent_chats')"
              :stroke-color="usageColor('agent_chats')"
              :format="() => `${used('agent_chats')}/${limit('agent_chats')}`"
            />
          </div>
        </a-col>
        <a-col :xs="24" :sm="12" :md="6">
          <div class="usage-metric">
            <div class="metric-label">AI 生成次数</div>
            <a-progress
              type="dashboard"
              :percent="usagePct('ai_gen')"
              :stroke-color="usageColor('ai_gen')"
              :format="() => `${used('ai_gen')}/${limit('ai_gen')}`"
            />
          </div>
        </a-col>
        <a-col :xs="24" :sm="12" :md="6">
          <div class="usage-metric">
            <div class="metric-label">绑定店铺数</div>
            <div class="simple-metric">
              <span class="big-num">{{ shopCount }}</span>
              <span class="metric-limit">/ {{ subscription?.plan.limits.shops_limit || 1 }}</span>
            </div>
          </div>
        </a-col>
      </a-row>
    </a-card>

    <!-- ====== 套餐对比 & 选择 ====== -->
    <a-card title="选择套餐" :bordered="false" class="plans-card">
      <a-spin :spinning="plansLoading">
        <div class="plans-grid">
          <div
            v-for="plan in plans"
            :key="plan.id"
            class="plan-card"
            :class="{ 'is-current': plan.id === subscription?.plan.id, 'recommended': plan.recommended }"
          >
            <div v-if="plan.recommended" class="recommend-badge">推荐</div>
            <div v-if="plan.id === subscription?.plan.id" class="current-badge">当前</div>

            <h3 class="plan-name">{{ plan.display_name }}</h3>
            <div class="plan-pricing">
              <span class="price-monthly">¥{{ plan.price_monthly }}</span>
              <span class="price-unit">/月</span>
            </div>
            <div class="plan-yearly-hint">
              年付 ¥{{ plan.price_yearly }}/年（省 {{ Math.round((1 - plan.price_yearly / (plan.price_monthly * 12)) * 100) }}%）
            </div>

            <ul class="plan-features">
              <li v-for="(feature, idx) in plan.features" :key="idx">
                <CheckCircleOutlined class="feature-check" /> {{ feature }}
              </li>
            </ul>

            <ul class="plan-limits">
              <li>API 调用: <strong>{{ formatNumber(plan.limits.api_calls_per_month) }}/月</strong></li>
              <li>Agent 对话: <strong>{{ formatNumber(plan.limits.agent_chats_per_month) }}/月</strong></li>
              <li>AI 生成: <strong>{{ formatNumber(plan.limits.ai_generations) }}/月</strong></li>
              <li>店铺数: <strong>{{ plan.limits.shops_limit }} 个</strong></li>
              <li>团队成员: <strong>{{ plan.limits.team_members }} 人</strong></li>
            </ul>

            <a-button
              block
              :type="plan.id === subscription?.plan.id ? 'default' : 'primary'"
              :disabled="plan.id === subscription?.plan.id"
              :loading="switchingPlanId === plan.id"
              @click="handleSwitchPlan(plan)"
            >
              {{ plan.id === subscription?.plan.id ? '当前套餐' : '选择此套餐' }}
            </a-button>
          </div>
        </div>
      </a-spin>
    </a-card>

    <!-- ====== 账单历史 ====== -->
    <a-card title="账单历史" :bordered="false" class="invoices-card">
      <template #extra>
        <a-radio-group v-model:value="invoiceFilter" size="small" button-style="solid">
          <a-radio-button value="all">全部</a-radio-button>
          <a-radio-button value="paid">已支付</a-radio-button>
          <a-radio-button value="pending">待支付</a-radio-button>
        </a-radio-group>
      </template>

      <a-table
        :columns="invoiceColumns"
        :data-source="filteredInvoices"
        :loading="invoicesLoading"
        :pagination="{ pageSize: 8, size: 'small' }"
        row-key="id"
        size="middle"
      >
        <template #bodyCell="{ column, record }">
          <template v-if="column.dataIndex === 'amount'">
            <span :class="{ 'amount-negative': record.amount < 0 }">
              {{ record.amount >= 0 ? '+' : '' }}¥{{ Math.abs(record.amount).toFixed(2) }}
            </span>
          </template>
          <template v-if="column.dataIndex === 'status'">
            <a-tag :color="invoiceStatusColor(record.status)">
              {{ invoiceStatusLabel(record.status) }}
            </a-tag>
          </template>
          <template v-if="column.dataIndex === 'actions'">
            <a-space>
              <a-button
                v-if="record.pdf_url"
                size="small"
                type="link"
                @click="openInvoice(record.pdf_url)"
              >下载发票</a-button>
              <a-button
                v-if="record.status === 'pending'"
                size="small"
                type="link"
                danger
              >去支付</a-button>
            </a-space>
          </template>
        </template>
      </a-table>

      <a-empty v-if="!invoicesLoading && filteredInvoices.length === 0" description="暂无账单记录" />
    </a-card>

    <!-- ====== 支付方式 ====== -->
    <a-card title="支付方式" :bordered="false" class="payment-card">
      <div v-if="paymentMethods.length > 0" class="payment-methods">
        <div
          v-for="pm in paymentMethods"
          :key="pm.id"
          class="payment-item"
          :class="{ 'is-default': pm.is_default }"
        >
          <div class="pm-icon">
            <CreditCardOutlined style="font-size: 24px; color: var(--primary)" />
          </div>
          <div class="pm-info">
            <strong>{{ pm.brand.toUpperCase() }} **** {{ pm.last4 }}</strong>
            <span>有效期 {{ String(pm.exp_month).padStart(2, '0') }}/{{ pm.exp_year }}</span>
          </div>
          <div class="pm-badges">
            <a-tag v-if="pm.is_default" color="blue" size="small">默认</a-tag>
          </div>
          <div class="pm-actions">
            <a-button
              v-if="!pm.is_default"
              size="small"
              type="link"
              @click="handleSetDefault(pm.id)"
            >设为默认</a-button>
            <a-popconfirm
              v-if="paymentMethods.length > 1"
              title="确定删除此支付方式？"
              @confirm="handleRemovePayment(pm.id)"
            >
              <a-button size="small" type="link" danger>删除</a-button>
            </a-popconfirm>
          </div>
        </div>
      </div>

      <a-empty v-else description="暂无支付方式">
        <p style="color: #8c8c8c; font-size: 12px; margin-bottom: 12px">
          添加信用卡或借记卡用于自动续费
        </p>
      </a-empty>

      <a-button type="dashed" style="margin-top: 12px" @click="handleAddPayment">
        <PlusOutlined /> 添加支付方式
      </a-button>
    </a-card>

    <!-- ====== 取消订阅区域 ====== -->
    <a-card
      v-if="subscription && subscription.status === 'active' && !subscription.cancel_at_period_end"
      title="危险操作"
      :bordered="false"
      class="danger-card"
    >
      <a-alert
        type="warning"
        show-icon
        message="取消订阅后，当前计费周期结束前仍可正常使用。到期后数据将保留30天，之后可能被清理。"
        style="margin-bottom: 16px"
      />
      <a-popconfirm
        title="确定要取消订阅吗？"
        ok-text="确认取消"
        cancel-text="再想想"
        ok-type="danger"
        @confirm="handleCancelSubscription"
      >
        <a-button danger :loading="cancelling">取消订阅</a-button>
      </a-popconfirm>
    </a-card>

    <!-- ====== 升级/切换套餐弹窗 ====== -->
    <a-modal
      v-model:open="showUpgradeModal"
      title="选择计费周期"
      :footer="null"
    >
      <div v-if="selectedPlanForUpgrade" class="upgrade-confirm">
        <h3 style="text-align: center; margin-bottom: 16px">
          {{ selectedPlanForUpgrade.display_name }}
        </h3>
        <div class="billing-cycle-options">
          <div
            class="cycle-option"
            :class="{ active: billingCycle === 'monthly' }"
            @click="billingCycle = 'monthly'"
          >
            <div class="cycle-price">¥{{ selectedPlanForUpgrade.price_monthly }}</div>
            <div class="cycle-period">按月付费</div>
          </div>
          <div
            class="cycle-option recommended-cycle"
            :class="{ active: billingCycle === 'yearly' }"
            @click="billingCycle = 'yearly'"
          >
            <div class="cycle-badge">省 {{ yearlySaving }}%</div>
            <div class="cycle-price">¥{{ selectedPlanForUpgrade.price_yearly }}</div>
            <div class="cycle-period">按年付费</div>
          </div>
        </div>
        <a-button
          type="primary"
          block
          size="large"
          :loading="switchingPlanId !== null"
          @click="confirmSwitchPlan"
        >
          确认{{ selectedPlanForUpgrade.id === subscription?.plan.id ? '续费' : '升级' }}
        </a-button>
      </div>
    </a-modal>
  </div>
</template>

<script setup lang="ts">
import { bandColor } from '@/theme/bands'
import { ref, computed, onMounted } from 'vue'
import { useRouter } from 'vue-router'
import { message } from 'ant-design-vue'
import {
  CrownFilled,
  CrownOutlined,
  CheckCircleOutlined,
  CreditCardOutlined,
  PlusOutlined,
} from '@ant-design/icons-vue'
import {
  fetchSubscription,
  fetchPlans,
  changePlan,
  cancelSubscription,
  resumeSubscription,
  fetchInvoices,
  fetchPaymentMethods,
  addPaymentMethod,
  removePaymentMethod,
  setDefaultPaymentMethod,
  type Subscription,
  type SubscriptionPlan,
  type Invoice,
  type PaymentMethod,
} from '@/api/billing'
import { useShopStore } from '@/stores/shop'

const router = useRouter()
const shopStore = useShopStore()

// ====== 数据状态 ======
const subscription = ref<Subscription | null>(null)
const plans = ref<SubscriptionPlan[]>([])
const invoices = ref<Invoice[]>([])
const paymentMethods = ref<PaymentMethod[]>([])

const plansLoading = ref(false)
const invoicesLoading = ref(false)

// 操作状态
const switchingPlanId = ref<string | null>(null)
const cancelling = ref(false)
const resuming = ref(false)

// UI 状态
const showUpgradeModal = ref(false)
const selectedPlanForUpgrade = ref<SubscriptionPlan | null>(null)
const billingCycle = ref<'monthly' | 'yearly'>('yearly')
const invoiceFilter = ref<'all' | 'paid' | 'pending'>('all')

// ====== 计算属性 ======

/** 是否高级套餐 */
const isPremiumPlan = computed(() => {
  const p = subscription.value?.plan?.name
  return p === 'pro' || p === 'enterprise' || p === 'team'
})

/** 套餐状态样式类 */
const planStatusClass = computed(() => {
  const s = subscription.value?.status
  if (s === 'active') return 'status-active'
  if (s === 'trialing') return 'status-trialing'
  if (s === 'past_due' || s === 'cancelled') return 'status-expired'
  return ''
})

/** 状态标签文字 */
const statusLabel = computed(() => {
  const labels: Record<string, string> = {
    active: '正常',
    trialing: '试用中',
    past_due: '逾期',
    cancelled: '已取消',
    expired: '已过期',
  }
  return labels[subscription.value?.status || ''] || '未知'
})

/** 用量百分比 */
function usagePct(type: string): number {
  if (!subscription.value) return 0
  const u = subscription.value.usage
  const used = type === 'api_calls' ? u.api_calls_used
    : type === 'agent_chats' ? u.agent_chats_used
    : u.ai_gen_used
  const limit = type === 'api_calls' ? u.api_calls_limit
    : type === 'agent_chats' ? u.agent_chat_limit
    : u.ai_gen_limit
  if (!limit) return 0
  return Math.min(Math.round((used / limit) * 100), 100)
}

/** 用量颜色 —— **反向口径**：用得越多越危险（见 bands.ts `usage`） */
function usageColor(type: string): string {
  return bandColor('usage', usagePct(type))
}

function used(type: string): number {
  if (!subscription.value) return 0
  const u = subscription.value.usage
  return type === 'api_calls' ? u.api_calls_used
    : type === 'agent_chats' ? u.agent_chats_used
    : u.ai_gen_used
}

function limit(type: string): number {
  if (!subscription.value) return 0
  const u = subscription.value.usage
  return type === 'api_calls' ? u.api_calls_limit
    : type === 'agent_chats' ? u.agent_chat_limit
    : u.ai_gen_limit
}

/** 店铺数量 */
const shopCount = computed(() => shopStore.shops?.length || 0)

/** 年付节省百分比 */
const yearlySaving = computed(() => {
  if (!selectedPlanForUpgrade.value) return 0
  const p = selectedPlanForUpgrade.value
  return Math.round((1 - p.price_yearly / (p.price_monthly * 12)) * 100)
})

/** 过滤后的账单 */
const filteredInvoices = computed(() => {
  if (invoiceFilter.value === 'all') return invoices.value
  return invoices.value.filter(inv => inv.status === invoiceFilter.value)
})

// ====== 账单表格列 ======
const invoiceColumns = [
  { title: '账单号', dataIndex: 'number', width: 180 },
  { title: '描述', dataIndex: 'description' },
  { title: '金额', dataIndex: 'amount', align: 'right' as const },
  { title: '状态', dataIndex: 'status', width: 100 },
  { title: '日期', dataIndex: 'issued_at', width: 120 },
  { title: '操作', dataIndex: 'actions', width: 140 },
]

function invoiceStatusColor(status: string): string {
  const map: Record<string, string> = { paid: 'green', pending: 'orange', failed: 'red', refunded: 'default' }
  return map[status] || 'default'
}

function invoiceStatusLabel(status: string): string {
  const map: Record<string, string> = { paid: '已支付', pending: '待支付', failed: '支付失败', refunded: '已退款' }
  return map[status] || status
}

// ====== 方法 ======

function formatTime(time: string | null): string {
  if (!time) return '-'
  return new Date(time).toLocaleString('zh-CN')
}

function formatDate(time: string | null): string {
  if (!time) return ''
  return new Date(time).toLocaleDateString('zh-CN')
}

function formatNumber(n: number): string {
  if (n >= 10000) return (n / 10000).toFixed(1) + '万'
  return n.toLocaleString()
}

/** 加载订阅信息 */
async function loadSubscription() {
  try {
    const res = await fetchSubscription()
    subscription.value = res.subscription
  } catch (e) {
    console.error('加载订阅失败:', e)
  }
}

/** 加载套餐列表 */
async function loadPlans() {
  plansLoading.value = true
  try {
    const res = await fetchPlans()
    plans.value = res.plans
  } catch (e) {
    console.error('加载套餐失败:', e)
    // 使用 Mock 数据兜底
    plans.value = mockPlans
  } finally {
    plansLoading.value = false
  }
}

/** 加载账单历史 */
async function loadInvoices() {
  invoicesLoading.value = true
  try {
    const res = await fetchInvoices()
    invoices.value = res.invoices
  } catch (e) {
    console.error('加载账单失败:', e)
    invoices.value = mockInvoices
  } finally {
    invoicesLoading.value = false
  }
}

/** 加载支付方式 */
async function loadPaymentMethods() {
  try {
    const res = await fetchPaymentMethods()
    paymentMethods.value = res.payment_methods
  } catch (e) {
    console.error('加载支付方式失败:', e)
    paymentMethods.value = []
  }
}

/** 切换套餐 */
function handleSwitchPlan(plan: SubscriptionPlan) {
  selectedPlanForUpgrade.value = plan
  showUpgradeModal.value = true
}

/** 打开发票 PDF */
function openInvoice(url: string) {
  window.open(url, '_blank')
}

/** 确认切换套餐 */
async function confirmSwitchPlan() {
  if (!selectedPlanForUpgrade.value) return
  switchingPlanId.value = selectedPlanForUpgrade.value.id

  try {
    const res = await changePlan(selectedPlanForUpgrade.value.id, billingCycle.value)
    // ★ 200 不等于已扣款：charged=false 表示后端按幂等处理了（同套餐同周期重复提交，
    //   或金额为 0 无需支付）。此时若还提示「已切换」，用户会以为自己被重复扣了钱。
    if (res.charged) {
      message.success(
        billingCycle.value === 'yearly' ? '已切换为年付套餐' : '已切换为月付套餐'
      )
    } else if (res.already_subscribed) {
      message.info(res.message || '当前已在所选套餐的有效周期内，未重复扣款')
    } else {
      message.info(res.skipped_reason || '无需支付，套餐已更新')
    }
    showUpgradeModal.value = false
    await loadSubscription()
  } catch (err: any) {
    message.error(err?.response?.data?.detail || '操作失败')
  } finally {
    switchingPlanId.value = null
  }
}

/** 取消订阅 */
async function handleCancelSubscription() {
  cancelling.value = true
  try {
    const res = await cancelSubscription()
    subscription.value = res.subscription
    message.success('订阅将在当前周期结束后取消')
  } catch (err: any) {
    message.error(err?.response?.data?.detail || '操作失败')
  } finally {
    cancelling.value = false
  }
}

/** 恢复订阅 */
async function handleResume() {
  resuming.value = true
  try {
    const res = await resumeSubscription()
    subscription.value = res.subscription
    message.success('订阅已恢复')
  } catch (err: any) {
    message.error(err?.response?.data?.detail || '操作失败')
  } finally {
    resuming.value = false
  }
}

/** 设为默认支付方式 */
async function handleSetDefault(methodId: string) {
  try {
    await setDefaultPaymentMethod(methodId)
    message.success('已设为默认支付方式')
    await loadPaymentMethods()
  } catch (err: any) {
    message.error(err?.response?.data?.detail || '操作失败')
  }
}

/** 删除支付方式 */
async function handleRemovePayment(methodId: string) {
  try {
    await removePaymentMethod(methodId)
    message.success('支付方式已删除')
    await loadPaymentMethods()
  } catch (err: any) {
    message.error(err?.response?.data?.detail || '操作失败')
  }
}

/** 添加支付方式（模拟跳转 Stripe） */
function handleAddPayment() {
  message.info('正在跳转至安全支付页面...')
  // 实际场景会跳转到 Stripe 的支付方式设置页面
}

// ====== Mock 数据（API 不可用时兜底）======
//
// ★ price_yearly 必须遵循与后端**同一口径**：年付 = 月付 × 10
//   （后端真源在 modules/billing/pricing.py，展示与收款共用同一个函数）。
//   这里原本写的是 999 / 2999，与月付 99 / 299 不成比例，
//   演示模式下会显示一个后端永远不会收的价，属于口径分叉的翻版。
const mockPlans: SubscriptionPlan[] = [
  {
    id: 'plan-free',
    name: 'free',
    display_name: '免费版',
    price_monthly: 0,
    price_yearly: 0,
    features: ['基础 Listing 生成', '1 个店铺绑定', '每月 50 次 API 调用', '社区支持'],
    limits: { api_calls_per_month: 50, agent_chats_per_month: 20, shops_limit: 1, team_members: 1, ai_generations: 10 },
  },
  {
    id: 'plan-pro',
    name: 'pro',
    display_name: '专业版',
    price_monthly: 99,
    price_yearly: 990,   // = 99 × 10（与后端 plan_amount 同口径）
    features: ['全部 AI 工具解锁', '5 个店铺绑定', '每月 5000 次 API 调用', '利润测算全功能', '优先技术支持'],
    limits: { api_calls_per_month: 5000, agent_chats_per_month: 500, shops_limit: 5, team_members: 3, ai_generations: 200 },
    recommended: true,
  },
  {
    id: 'plan-enterprise',
    name: 'enterprise',
    display_name: '企业版',
    price_monthly: 299,
    price_yearly: 2990,   // = 299 × 10（与后端 plan_amount 同口径）
    features: ['无限 API 调用', '无限店铺绑定', '专属客户成功经理', '自定义模型接入', 'SLA 保障', '私有化部署选项'],
    limits: { api_calls_per_month: 99999, agent_chats_per_month: 99999, shops_limit: 999, team_members: 50, ai_generations: 99999 },
  },
]

const mockInvoices: Invoice[] = [
  { id: 'inv-001', number: 'INV-20260901-001', amount: 999, currency: 'CNY', status: 'paid', description: '专业版年付', issued_at: '2026-09-01T00:00:00Z', paid_at: '2026-09-01T00:05:00Z', pdf_url: '#' },
  { id: 'inv-002', number: 'INV-20260801-001', amount: 99, currency: 'CNY', status: 'paid', description: '专业版月付', issued_at: '2026-08-01T00:00:00Z', paid_at: '2026-08-01T00:03:00Z', pdf_url: '#' },
  { id: 'inv-003', number: 'INV-20260701-001', amount: 99, currency: 'CNY', status: 'paid', description: '专业版月付', issued_at: '2026-07-01T00:00:00Z', paid_at: '2026-07-02T10:00:00Z', pdf_url: null },
]

// ====== 生命周期 ======
onMounted(async () => {
  await Promise.all([
    loadSubscription(),
    loadPlans(),
    loadInvoices(),
    loadPaymentMethods(),
  ])
})
</script>

<style scoped>
.subscription-container {
  max-width: 1100px;
  margin: 0 auto;
  padding: var(--space-24);
}

/* ====== 当前套餐横幅 ====== */
.current-plan-banner {
  display: flex;
  justify-content: space-between;
  align-items: center;
  padding: var(--space-20) var(--space-24);
  border-radius: var(--radius-10);
  margin-bottom: var(--space-24);
}

.current-plan-banner.status-active {
  background: linear-gradient(135deg, #f6ffed 0%, #e6fffb 100%);
  border: 1px solid var(--success-border);
}

.current-plan-banner.status-trialing {
  background: linear-gradient(135deg, var(--purple-bg) 0%, var(--purple-border) 100%);
  border: 1px solid #d3adf7;
}

.current-plan-banner.status-expired {
  background: linear-gradient(135deg, var(--danger-bg) 0%, var(--danger-border) 100%);
  border: 1px solid var(--danger-border-strong);
}

.banner-left .plan-badge {
  font-size: var(--font-size-18);
  font-weight: 700;
  display: flex;
  align-items: center;
  gap: var(--space-8);
  margin-bottom: var(--space-6);
}

.banner-left .plan-price {
  font-size: var(--font-size-28);
  font-weight: 800;
  color: var(--text-primary);
  display: flex;
  align-items: baseline;
  gap: var(--space-8);
}

.plan-price .period {
  font-size: var(--font-size-14);
  font-weight: 400;
  color: var(--text-tertiary);
}

.period-text {
  font-size: var(--font-size-13);
  color: var(--text-tertiary);
  margin-top: var(--space-4);
}

/* ====== 用量仪表盘 ====== */
.usage-card {
  margin-bottom: var(--space-24);
}

.usage-metric {
  text-align: center;
  padding: var(--space-12) 0;
}

.metric-label {
  font-size: var(--font-size-13);
  color: var(--text-secondary);
  margin-bottom: var(--space-8);
  font-weight: 500;
}

.simple-metric {
  padding: var(--space-20) 0;
}

.big-num {
  font-size: var(--font-size-32);
  font-weight: 700;
  color: var(--text-primary);
}

.metric-limit {
  font-size: var(--font-size-14);
  color: var(--text-tertiary);
}

/* ====== 套餐网格 ====== */
.plans-card {
  margin-bottom: var(--space-24);
}

.plans-grid {
  display: grid;
  grid-template-columns: repeat(auto-fit, minmax(260px, 1fr));
  gap: var(--space-20);
  padding: var(--space-8) 0;
}

.plan-card {
  border: 2px solid var(--border-base);
  border-radius: var(--radius-12);
  padding: var(--space-24) var(--space-20);
  position: relative;
  transition: all 0.25s ease;
  background: var(--bg-elevated);
}

.plan-card:hover {
  border-color: var(--primary);
  box-shadow: 0 4px 16px rgba(24, 144, 255, 0.12);
}

.plan-card.is-current {
  border-color: var(--success);
  background: var(--success-bg);
}

.plan-card.recommended {
  border-color: var(--warning);
}

.plan-card .recommend-badge {
  position: absolute;
  top: -10px;
  right: 20px;
  background: linear-gradient(135deg, #faad14, #ff7a45);
  color: #fff;
  padding: var(--space-3) var(--space-12);
  border-radius: var(--radius-10);
  font-size: var(--font-size-11);
  font-weight: 600;
}

.plan-card .current-badge {
  position: absolute;
  top: -10px;
  right: 20px;
  background: var(--success);
  color: #fff;
  padding: var(--space-3) var(--space-12);
  border-radius: var(--radius-10);
  font-size: var(--font-size-11);
  font-weight: 600;
}

.plan-name {
  text-align: center;
  font-size: var(--font-size-18);
  font-weight: 700;
  margin-bottom: var(--space-12);
}

.plan-pricing {
  text-align: center;
  margin-bottom: var(--space-4);
}

.price-monthly {
  font-size: var(--font-size-36);
  font-weight: 800;
  color: var(--text-primary);
}

.price-unit {
  font-size: var(--font-size-14);
  color: var(--text-tertiary);
}

.plan-yearly-hint {
  text-align: center;
  font-size: var(--font-size-12);
  color: var(--success);
  margin-bottom: var(--space-16);
}

.plan-features {
  list-style: none;
  padding: 0;
  margin: 0 0 var(--space-16);
}

.plan-features li {
  padding: var(--space-4) 0;
  font-size: var(--font-size-13);
  color: #434343;
  display: flex;
  align-items: center;
  gap: var(--space-6);
}

.feature-check {
  color: var(--success);
  font-size: var(--font-size-13);
}

.plan-limits {
  list-style: none;
  padding: var(--space-12);
  margin: 0 0 var(--space-20);
  background: var(--bg-sidebar);
  border-radius: var(--radius-8);
  font-size: var(--font-size-12);
  color: var(--text-secondary);
}

.plan-limits li {
  padding: var(--space-3) 0;
  display: flex;
  justify-content: space-between;
}

.plan-limits strong {
  color: var(--text-primary);
}

/* ====== 账单表格 ====== */
.invoices-card {
  margin-bottom: var(--space-24);
}

.amount-negative {
  color: var(--success);
}

/* ====== 支付方式 ====== */
.payment-card {
  margin-bottom: var(--space-24);
}

.payment-methods {
  display: flex;
  flex-direction: column;
  gap: var(--space-12);
}

.payment-item {
  display: flex;
  align-items: center;
  gap: var(--space-14);
  padding: var(--space-14) var(--space-16);
  border: 1px solid var(--border-base);
  border-radius: var(--radius-8);
  transition: all 0.2s;
}

.payment-item:hover {
  border-color: var(--border-strong);
  box-shadow: 0 2px 8px rgba(0, 0, 0, 0.06);
}

.payment-item.is-default {
  border-color: var(--info-border);
  background: var(--info-bg);
}

.pm-icon {
  flex-shrink: 0;
}

.pm-info {
  flex: 1;
  display: flex;
  flex-direction: column;
  gap: var(--space-2);
}

.pm-info span {
  font-size: var(--font-size-12);
  color: var(--text-tertiary);
}

.pm-actions {
  display: flex;
  gap: var(--space-4);
}

/* ====== 危险区域 ====== */
.danger-card {
  margin-bottom: var(--space-24);
  border-color: var(--danger-border-strong);
}

/* ====== 升级弹窗 - 计费周期选择 ====== */
.upgrade-confirm {
  padding: var(--space-12) 0;
}

.billing-cycle-options {
  display: grid;
  grid-template-columns: 1fr 1fr;
  gap: var(--space-16);
  margin-bottom: var(--space-24);
}

.cycle-option {
  border: 2px solid var(--border-base);
  border-radius: var(--radius-10);
  padding: var(--space-20);
  text-align: center;
  cursor: pointer;
  transition: all 0.2s;
  position: relative;
}

.cycle-option:hover {
  border-color: var(--primary);
}

.cycle-option.active {
  border-color: var(--primary);
  background: var(--info-bg);
}

.cycle-option.recommended-cycle.active {
  border-color: var(--warning);
  background: var(--warning-bg);
}

.cycle-badge {
  position: absolute;
  top: -10px;
  left: 50%;
  transform: translateX(-50%);
  background: var(--warning);
  color: #fff;
  padding: var(--space-2) var(--space-10);
  border-radius: var(--radius-8);
  font-size: var(--font-size-11);
  font-weight: 600;
}

.cycle-price {
  font-size: var(--font-size-28);
  font-weight: 800;
  color: var(--text-primary);
  margin-bottom: var(--space-4);
}

.cycle-period {
  font-size: var(--font-size-13);
  color: var(--text-tertiary);
}
</style>
