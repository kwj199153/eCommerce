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
          @click="goChoosePlan"
        >
          更换套餐
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
        <a-button type="primary" size="large" @click="goChoosePlan">
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
    <a-card ref="plansCardRef" title="选择套餐" :bordered="false" class="plans-card">
      <a-spin :spinning="plansLoading">
        <!-- ★ 读失败时不得静默空白（改前是 catch 灌 mockPlans ⇒ 3 个假套餐、
             假价格、「选择此套餐」还能点）。空状态优于虚构默认。 -->
        <AsyncEmpty
          v-if="!plansLoading && plans.length === 0"
          :error="plansError"
          label="套餐"
          empty-description="暂无可选套餐"
          @retry="loadPlans"
        />
        <div v-else class="plans-grid">
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
              <!-- ★ 月价 0（免费版）时 `1 - 0/(0*12)` = NaN ⇒ 曾显示「省 NaN%」。
                   算不出节省比例时如实说「永久免费」，不要给一个坏数字。 -->
              <template v-if="planYearlySaving(plan) !== null">
                年付 ¥{{ plan.price_yearly }}/年（省 {{ planYearlySaving(plan) }}%）
              </template>
              <template v-else>永久免费</template>
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
        <!-- ★ 只留**一个**空态：antd 表格自带的「暂无数据」会与我们的失败说明并存，
             两句摆在一起是自相矛盾的（不是"暂无"，而是没加载出来）。
             用 emptyText 插槽把它换掉，文案随失败与否切换。 -->
        <template #emptyText>
          <AsyncEmpty
            :error="invoicesError"
            label="账单"
            empty-description="暂无账单记录"
            @retry="loadInvoices"
          />
        </template>
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
                :loading="payChecking"
                @click="openPayFromInvoice(record)"
              >去支付</a-button>
            </a-space>
          </template>
        </template>
      </a-table>

      <!-- ★ 失败态已挪进表格的 emptyText 插槽（见上）—— 这里原本另有一个 a-empty，
           与表格自带的「暂无数据」**并存**，两句摆在一起自相矛盾。 -->
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

      <!-- ★ 空态如实说明（第 282 轮）：本产品走「扫码一次性付款」，不保存任何卡信息。
           原先那句「添加信用卡或借记卡用于自动续费」同时说了两件不成立的事 ——
             ① 没有卡：支付宝当面付是扫码，不落卡信息；
             ② 没有自动续费：当面付是**一次性收款**，不做代扣（周期扣款尚未签约）。
           配套的「添加支付方式」按钮点了只弹一句 toast（死按钮），一并去掉。
           ★ 文案只写「支付宝」是因为当前**只有**支付宝接好了；接入微信支付时
             必须回来同步这一句，否则这里就成了新的谎。
           若后端将来真接入可保存的支付方式，再把添加入口加回来。 -->
      <a-empty v-else description="无需绑定银行卡">
        <p class="payment-hint">
          支付时用「支付宝」扫码完成，按所选周期一次性付款，不保存卡信息。
        </p>
      </a-empty>
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
    <a-modal :width="WINDOW_W.md"
      v-model:open="showUpgradeModal"
      :title="upgradeModalTitle"
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
            <div v-if="yearlySaving !== null" class="cycle-badge">省 {{ yearlySaving }}%</div>
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
          确认{{ switchVerb }}
        </a-button>
      </div>
    </a-modal>

    <!-- ====== 支付宝扫码支付弹窗 ====== -->
    <!--
      ★ 这个弹窗只服务**真实用户**。
        演示身份在后端是**同步直通**（`charged=true`，
        响应里根本不会出现 `requires_confirmation`）——
        所以"演示用户无需扫码、点一下即开通"这条硬要求不受本弹窗影响。
    -->
    <a-modal
      v-model:open="showPayModal"
      title="支付宝扫码支付"
      :footer="null"
      :width="WINDOW_W.sm"
      :mask-closable="false"
      @cancel="stopPayPolling"
    >
      <div v-if="payPayment" class="pay-dialog">
        <div class="pay-summary">
          <span class="pay-plan">{{ payPlanLabel }}</span>
          <span class="pay-amount">{{ payCurrencySymbol }}{{ payPayment.amount.toFixed(2) }}</span>
        </div>
        <div class="pay-order">订单号：{{ payPayment.number }}</div>

        <div class="pay-qr-area">
          <a-spin :spinning="payQrLoading">
            <img
              v-if="payQr"
              :src="payQr"
              alt="支付宝收款二维码"
              class="pay-qr-img"
            />
            <div v-else class="pay-qr-placeholder">
              <a-alert
                v-if="payQrFailed"
                type="error"
                show-icon
                :message="payQrFailed"
              />
              <span v-else>二维码加载中…</span>
            </div>
          </a-spin>
        </div>

        <!--
          ★ 倒计时与"已过期"是**互斥**的两个状态，不要合成一句
            "剩余 -00:01" —— 负数的倒计时在用户眼里就是产品坏了。
        -->
        <div v-if="payExpired" class="pay-status pay-status-expired">
          <ExclamationCircleOutlined /> 二维码已过期，请重新生成订单
        </div>
        <div v-else class="pay-status">
          请在 <strong>{{ payRemainingText }}</strong> 内扫码完成支付
        </div>

        <!-- 轮询抖动时**如实**告知，而不是让界面看起来一切正常 -->
        <div v-if="payPollHint" class="pay-poll-hint">{{ payPollHint }}</div>

        <div class="pay-actions">
          <a-button
            block
            size="large"
            :loading="payChecking"
            :disabled="payExpired || !!payQrFailed"
            @click="pollOnce"
          >
            我已完成支付
          </a-button>
          <a-button v-if="payExpired" block type="primary" @click="regenerateOrder">
            重新生成订单
          </a-button>
          <a-button block type="text" @click="closePayModal">稍后再付</a-button>
        </div>

        <div class="pay-tip">
          支付成功后本窗口会自动关闭，套餐立即生效。
          也可以先关掉这一页，稍后从「账单历史」的待支付记录回来继续扫码。
        </div>
      </div>
    </a-modal>
  </div>
</template>

<script setup lang="ts">
import { WINDOW_W } from '@/config/layout'
import AsyncEmpty from '@/components/common/AsyncEmpty.vue'
import { bandColor } from '@/theme/bands'
import { ref, computed, watch, onMounted, onUnmounted } from 'vue'
import { useRouter } from 'vue-router'
import { message } from 'ant-design-vue'
import {
  CrownFilled,
  CrownOutlined,
  CheckCircleOutlined,
  CreditCardOutlined,
  ExclamationCircleOutlined,
} from '@ant-design/icons-vue'
import {
  fetchSubscription,
  fetchPlans,
  changePlan,
  fetchPendingPayment,
  fetchPaymentQr,
  fetchPaymentStatus,
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
  type PendingPayment,
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
// ★ 读失败的**原因** —— 模板据它区分「暂无」与「加载失败」。
//   这两个列表原先在 catch 里灌 mockPlans / mockInvoices：用户会看到 3 个后端
//   根本不存在的套餐（假价格，「选择此套餐」还能点、点下去真的会拿一个不存在的
//   plan_id 去下单）和 3 条不存在的已支付账单。空状态优于虚构默认 ⇒ 置空 + 记原因。
const plansError = ref('')
const invoicesError = ref('')

// 操作状态
const switchingPlanId = ref<string | null>(null)
const cancelling = ref(false)
const resuming = ref(false)

// UI 状态
const showUpgradeModal = ref(false)
const selectedPlanForUpgrade = ref<SubscriptionPlan | null>(null)
const billingCycle = ref<'monthly' | 'yearly'>('yearly')
const invoiceFilter = ref<'all' | 'paid' | 'pending'>('all')
/**
 * 套餐对比区的锚点 —— banner 的「更换套餐」与空态的「选择套餐」滚到它。
 * ★ a-card 是组件，ref 拿到的是实例，真实 DOM 在 `$el` 上；取不到时按 class 兜底。
 */
const plansCardRef = ref<{ $el?: HTMLElement } | null>(null)

// ====== 扫码支付状态（支付宝当面付的**第二段**）======
//
// ★ 与「演示身份」的关系：演示身份在后端同步直通（charged=true，
//   响应里没有 requires_confirmation）⇒ 永远走不到这里。
//   这一组状态只服务真实用户。
const showPayModal = ref(false)
/** 当前正在支付的那张单（下单响应 / 恢复待支付单 / 账单列表进入 —— 三个入口共用） */
const payPayment = ref<PendingPayment | null>(null)
const payQr = ref('')
const payQrLoading = ref(false)
/** 二维码加载失败的原因（**常驻**在弹窗里 —— 所以 api 层要 silentError） */
const payQrFailed = ref('')
/** 任意"正在问后端一次"的过程（手动查、进入时查） */
const payChecking = ref(false)
const payExpired = ref(false)
/** 剩余秒数。★ 每次都由 `expires_at` **现算**，不做自减计数 */
const payRemaining = ref(0)
/** 轮询连续失败时给用户的解释（空串 = 一切正常） */
const payPollHint = ref('')

let pollTimer: number | null = null
let tickTimer: number | null = null
/** 轮询连续失败次数 —— 偶发抖动不打扰用户，持续失败必须说出来 */
let pollFailStreak = 0

/** 轮询节奏。★ 3 秒是"用户刚在支付宝里点完，切回来几乎立刻看到生效"与
 *  "不要给后端压力"之间的折中；不要为了"更快"把它调到 1 秒以内。 */
const PAY_POLL_MS = 3000
const PAY_POLL_HINT_AFTER = 3

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

/** 年付节省百分比（null = 算不出，模板据此隐藏角标而不是显示 NaN） */
const yearlySaving = computed(() => {
  if (!selectedPlanForUpgrade.value) return null
  return planYearlySaving(selectedPlanForUpgrade.value)
})

/**
 * 计费周期弹窗的标题 —— 必须点出**是哪个套餐**。
 *
 * ★ 改前写死「选择计费周期」：这个弹窗只在「用户已经选定某个套餐」时才说得通
 *   （正文只有月付/年付两个价 + 一个确认按钮），标题却不说是哪个套餐 ——
 *   等于让用户凭记忆确认自己要买什么。
 */
const upgradeModalTitle = computed(() =>
  selectedPlanForUpgrade.value
    ? `${selectedPlanForUpgrade.value.display_name} · 选择计费周期`
    : '选择计费周期'
)

/**
 * 确认按钮的动词 —— 升级 / 降级 / 续费 / 切换，按**档位**如实说。
 *
 * ★ 改前只判 `id 相等 ? '续费' : '升级'` ⇒ 选一个**更便宜**的套餐也显示
 *   「确认升级」。后端 `modules/billing/router.py:260` 自己写的是
 *   「升级 / 切换 / 续费套餐」，它既不区分方向也不拦降级 ——
 *   方向是前端该说清楚的事。
 * ★ 为什么要有「切换」这一支：两档月价相同时（活动价 / 定制档），
 *   叫「升级」或「降级」都是编的，如实说「切换」。
 */
const switchVerb = computed(() => {
  const target = selectedPlanForUpgrade.value
  if (!target) return '确认'
  const cur = subscription.value?.plan
  if (!cur || target.id === cur.id) return '续费'
  if (target.price_monthly > cur.price_monthly) return '升级'
  if (target.price_monthly < cur.price_monthly) return '降级'
  return '切换'
})

/** 过滤后的账单 */
const filteredInvoices = computed(() => {
  if (invoiceFilter.value === 'all') return invoices.value
  return invoices.value.filter(inv => inv.status === invoiceFilter.value)
})

/**
 * 待支付单对应的套餐名 —— 用 `plans` 反查。
 *
 * ★ 为什么不是后端给：`pending_payment_payload` 只给 `plan_id`
 *   （它是**账单**的序列化，不该耦合套餐展示名）。
 * ★ 反查不到不算异常：套餐可能已被下架，此时退回周期文案，
 *   而不是在用户面前显示"未知套餐"。
 */
const payPlanLabel = computed(() => {
  const pay = payPayment.value
  if (!pay) return ''
  const cycle = pay.billing_cycle === 'yearly' ? '年付' : '月付'
  const name = plans.value.find(x => x.id === pay.plan_id)?.display_name
  if (name) return `${name} · ${cycle}`
  // ★ 套餐列表**没加载出来**时不能沿用「已下架」那条退化 —— 那是把加载失败
  //   说成后端的结论。此时明确说明，免得用户对着一个不知名的套餐付款。
  return plansError.value ? '套餐信息未加载' : cycle
})

/** 货币符号 —— 目前后端只出 CNY，写在这里是为了不在模板里散布硬编码 */
const payCurrencySymbol = computed(() =>
  (payPayment.value?.currency || 'CNY') === 'CNY' ? '¥' : (payPayment.value?.currency || '') + ' '
)

/** 倒计时文案 mm:ss */
const payRemainingText = computed(() => {
  const t = Math.max(0, payRemaining.value)
  const mm = String(Math.floor(t / 60)).padStart(2, '0')
  const ss = String(t % 60).padStart(2, '0')
  return `${mm}:${ss}`
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

/**
 * 年付比月付省多少（%）。**算不出来就返回 null**，由模板换一句说法。
 *
 * ★ 为什么不是直接返回 0：月价为 0 的免费版会算出 `1 - 0/(0*12)` = **NaN**，
 *   界面显示成「省 NaN%」（老板截图实锤）。0 与「无法计算」是两件事，
 *   塌成一个值必然在某一侧说谎。
 */
function planYearlySaving(p: SubscriptionPlan): number | null {
  const monthlyTotal = p.price_monthly * 12
  if (!(monthlyTotal > 0)) return null
  // 年付不比月付便宜（含同价、倒挂）时不宣称「省」
  if (!(p.price_yearly < monthlyTotal)) return null
  return Math.round((1 - p.price_yearly / monthlyTotal) * 100)
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
  plansError.value = ''
  try {
    const res = await fetchPlans()
    plans.value = res.plans
  } catch (e) {
    console.error('加载套餐失败:', e)
    // ★ 不得回退 mockPlans：假套餐带假价格，且卡片上的「选择此套餐」可点 ⇒
    //   点下去会拿一个后端不存在的 plan_id 真的去下单。
    //   空状态优于虚构默认 ⇒ 置空 + 记原因，由模板显示「加载失败 + 重试」。
    plans.value = []
    plansError.value = (e as Error)?.message || '套餐加载失败'
  } finally {
    plansLoading.value = false
  }
}

/** 加载账单历史 */
async function loadInvoices() {
  invoicesLoading.value = true
  invoicesError.value = ''
  try {
    const res = await fetchInvoices()
    invoices.value = res.invoices
  } catch (e) {
    console.error('加载账单失败:', e)
    // ★ 不得回退 mockInvoices：用户会看到 3 条**根本不存在的已支付账单**
    //   （编号形态与真账单同形，还都带「下载发票」）。空状态优于虚构默认。
    invoices.value = []
    invoicesError.value = (e as Error)?.message || '账单加载失败'
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

/**
 * 「更换套餐 / 选择套餐」入口 —— 滚到套餐对比区，**不开弹窗**。
 *
 * ★ 为什么改前那个弹窗是坏的（本轮的起因）：两处入口只写
 *   `showUpgradeModal = true`，而弹窗正文是 `v-if="selectedPlanForUpgrade"`；
 *   这个 ref 只在「点套餐卡片」和「二维码过期重下单」时被赋值，且**关窗不清空**。
 *   于是：第一次点 ⇒ **空白弹窗**；之后点 ⇒ 显示**上一次残留**的套餐 ——
 *   最坏那一次正是用户**当前已经在用**的那个（按钮会写「确认续费」）。
 *   用户在「升级」的入口里，从头到尾看不到任何可升级的套餐。
 *
 * ★ 为什么是滚动、而不是把套餐列表也塞进弹窗：本页**已经有**整套套餐对比
 *   （推荐角标 / 当前角标 / 年付省钱 / 功能清单 / 五项限额 / 当前套餐置灰）。
 *   在弹窗里再渲染一份就是**第二份实现**，必然与它漂移 ——
 *   本仓的既定处理是「收唯一真源」，不是复制一份。
 */
function goChoosePlan() {
  const el = plansCardRef.value?.$el || document.querySelector('.plans-card')
  el?.scrollIntoView({ behavior: 'smooth', block: 'start' })
}

/**
 * 切换套餐：套餐卡片上的「选择此套餐」→ 打开**计费周期**弹窗。
 * ★ 弹窗只服务这一件事（正文只有月付 / 年付两个价 + 一个确认按钮）。
 */
function handleSwitchPlan(plan: SubscriptionPlan) {
  selectedPlanForUpgrade.value = plan
  // ★ 每次都回到默认（年付）再打开。`billingCycle` 是**粘性**的 ——
  //   不重置的话，用户上次点了月付、下次打开会「莫名其妙」停在月付，
  //   而年付才是本页一直在推荐的那一个（带折扣角标）。
  //   ★ 这一句**可观测**：探针 J9 验「切月付 → 关 → 再开 ⇒ 回年付」。
  billingCycle.value = 'yearly'
  showUpgradeModal.value = true
}

/**
 * 弹窗一关就清场 —— 这是「上次残留」那个缺陷的解药。
 *
 * ★ 为什么挂在开关上、而不是 a-modal 的 `@after-close`：
 *   关闭的路径不止一条（右上角 X / ESC / 点遮罩 / 确认成功 / 支付弹窗接棒），
 *   依赖某个具体事件就必然漏掉其中一类。**开关落回 false 就是唯一真源。**
 *   ★ `billingCycle` 的重置**不在这里** —— 它收在 `handleSwitchPlan`（打开处）。
 *     反向注入实测：这里原本也有一份同义的 `billingCycle.value = 'yearly'`，
 *     而它**覆盖**了打开处那一份 ⇒ 探针 J9b 咬住的其实是**这里**，
 *     `handleSwitchPlan` 里那句成了「删掉也不会有任何判据变红」的冗余实现
 *     （同一判定两份实现，必有一份测不到）。收唯一真源后留下
 *     「打开时设初值」——语义更直接，且现在真被 J9b 咬住。
 *   ★★ 如实说明：这段清场的**主要**效果（`selectedPlanForUpgrade = null`）
 *     在当前 UI 下**没有独立可观测判据** —— 「只开弹窗、不设套餐」的入口
 *     已经被 `goChoosePlan` 消灭了，没有任何一条用户路径能再打开一个
 *     「没有套餐的弹窗」。它是**结构性防御**（保证 `showUpgradeModal=true`
 *     时正文必有内容）：反向注入把这一段整块删掉，探针**不会**变红。
 *     留着它的理由是「下一个入口」；若哪天发现它成了纯负担，可以放心删。
 */
watch(showUpgradeModal, (open) => {
  if (!open) {
    selectedPlanForUpgrade.value = null
  }
})

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
    // ★ 200 不等于已收款，必须逐个分支看 charged / requires_confirmation：
    //   把三者混成一句"已切换套餐"，最坏的一支会让用户以为**没付钱就买到了**。
    if (res.charged) {
      // 同步形态（**演示身份**恒走这支**：点一下即开通，无需扫码）
      message.success(
        billingCycle.value === 'yearly' ? '已切换为年付套餐' : '已切换为月付套餐'
      )
      showUpgradeModal.value = false
      await loadSubscription()
    } else if (res.requires_confirmation && res.payment) {
      // 异步形态：**权益尚未生效**（后端刻意不动订阅，用户还没付钱）。
      // ⇒ 这里绝对不能提示"已切换套餐"，必须把二维码交到用户手上。
      showUpgradeModal.value = false
      if (res.already_pending) {
        // 后端把**原来那张**码又给了一次（同一个套餐同一周期，没有重复下单）
        message.info(res.message || '已有一笔待支付的订单，请继续扫码完成支付')
      }
      await openPayModal(res.payment)
    } else if (res.already_subscribed) {
      message.info(res.message || '当前已在所选套餐的有效周期内，未重复扣款')
      showUpgradeModal.value = false
      await loadSubscription()
    } else if (res.skipped_reason) {
      message.info(res.skipped_reason)
      showUpgradeModal.value = false
      await loadSubscription()
    } else {
      // ★ 走到这里说明后端的返回形态变了（既没扣款、也没下单、也没说明原因）。
      //   旧代码在这一支会提示"无需支付，套餐已更新"—— 那是**猜的**。
      //   如实说"请刷新确认"，比给一个可能是假的结论好。
      message.warning('未收到明确的支付结果，请刷新页面确认订阅状态')
      showUpgradeModal.value = false
      await loadSubscription()
    }
  } catch (err: any) {
    // ★ 这里是**唯一**的报告出口（api 层已声明 silentError）——
    //   否则后端每个 4xx/5xx 都会"拦截器弹一条 + 这里再弹一条"。
    message.error(err?.response?.data?.detail || '操作失败')
  } finally {
    switchingPlanId.value = null
  }
}

// ====== 支付宝扫码支付流程 ======
//
// 三个入口共用同一套状态与流程：
//   ① 下单响应带回 payment（真实用户点升级/续费）
//   ② 页面加载时发现有未支付的单（`/payment/pending`）—— **刷新后恢复二维码**
//   ③ 账单历史里点「去支付」
// ★ 三条路径都收口到 openPayModal，绝不各拼一份渲染逻辑（会漂移）。

/**
 * 打开支付弹窗（**唯一入口**）。
 *
 * ★ `resetPayState` 放在最前面：上一张码的失败提示 / 过期标记不能漏到新单上，
 *   否则用户会看到"新二维码 + 上一张的错误文案"。
 */
async function openPayModal(payment: PendingPayment) {
  resetPayState()
  payPayment.value = payment
  showPayModal.value = true
  await loadPayQr(payment.invoice_id)
  startPayPolling()
}

/** 清掉与"上一张单"绑定的瞬时状态 */
function resetPayState() {
  stopPayPolling()
  payQr.value = ''
  payQrFailed.value = ''
  payExpired.value = false
  payRemaining.value = 0
  payPollHint.value = ''
  pollFailStreak = 0
}

/**
 * 取二维码。
 *
 * ★ **409 不是错误**：后端用它表示「这张账单**已经付过了**」。
 *   把它当"加载失败"会让用户对着一个"支付其实已经成功、却提示二维码加载失败"
 *   的窗口发呆，然后去重新下单 —— 于是真的付两次。
 *   ⇒ 409 一律按「支付成功」处理。
 */
async function loadPayQr(invoiceId: string) {
  payQrLoading.value = true
  payQrFailed.value = ''
  try {
    const res = await fetchPaymentQr(invoiceId)
    payQr.value = res.qr_svg
  } catch (err: any) {
    if (err?.response?.status === 409) {
      await onPaySucceeded()
      return
    }
    // ★ 失败必须**上屏**（常驻错误面）：否则弹窗中央是一块空白，
    //   用户会以为"码还没出来"而一直等。api 层已声明 silentError，
    //   所以这里是**唯一**的报告出口，不会与拦截器的 toast 重复。
    payQrFailed.value = err?.response?.data?.detail || '二维码加载失败，请点「重新生成订单」重试'
  } finally {
    payQrLoading.value = false
  }
}

/** 倒计时：**每秒从 expires_at 现算**，不做自减。 */
function tick() {
  const exp = payPayment.value?.expires_at
  if (!exp) {
    // 后端没给 expires_at（老数据 / 字段缺失）：不显示倒计时，也不假装"已过期"。
    // ★ 拿不到权威值 ≠ 值为 0 —— 猜一个会让用户白丢一张还能付的单。
    payRemaining.value = 0
    return
  }
  const ms = new Date(exp).getTime() - Date.now()
  payRemaining.value = Math.max(0, Math.floor(ms / 1000))
  if (payRemaining.value <= 0) payExpired.value = true
}

/**
 * 启动轮询 + 倒计时。
 *
 * ★ 为什么倒计时用 `setInterval(tick, 1000)` 现算、而不是每轮 -1：
 *   支付页最常见的动作就是「切到支付宝 App → 付完 → 切回来」，
 *   而后台标签页的定时器会被浏览器**节流**（Chrome 可降到 1 分钟一次）。
 *   自减计数在这种场景下必然越走越慢（显示还剩 20 分钟，实际已过期）。
 *   现算则天然免疫 —— 切回来的那一瞬间就是对的。
 */
function startPayPolling() {
  stopPayPolling()
  tick()
  pollTimer = window.setInterval(pollOnce, PAY_POLL_MS)
  tickTimer = window.setInterval(tick, 1000)
}

/** 停掉两个定时器。★ 组件卸载与弹窗关闭都必须调它，否则定时器会一直跑。 */
function stopPayPolling() {
  if (pollTimer !== null) {
    window.clearInterval(pollTimer)
    pollTimer = null
  }
  if (tickTimer !== null) {
    window.clearInterval(tickTimer)
    tickTimer = null
  }
}

/** 问一次后端：这笔付了没有。 */
async function pollOnce() {
  const id = payPayment.value?.invoice_id
  if (!id || payExpired.value || payChecking.value) return
  payChecking.value = true
  try {
    const res = await fetchPaymentStatus(id)
    payPayment.value = res.payment
    pollFailStreak = 0
    payPollHint.value = ''
    if (res.payment.status === 'paid') {
      await onPaySucceeded()
      return
    }
    // 后端判过期（可能与本地倒计时差几秒）：以后端为准，别让用户扫一张死码。
    if (res.payment.status === 'expired' || res.payment.status === 'failed') {
      payExpired.value = true
    }
  } catch (err: any) {
    // ★ 轮询失败**不打断**用户（网络抖动是常态，下一轮自己会好），
    //   但也**不能装作没发生**：连续失败到一定次数就把实情说出来，
    //   并保底给出「我已完成支付」这个手动出口 —— 用户可以自己再问一次。
    pollFailStreak += 1
    if (pollFailStreak >= PAY_POLL_HINT_AFTER) {
      payPollHint.value =
        `已连续 ${pollFailStreak} 次没能确认支付状态（${err?.response?.data?.detail || '网络异常'}）。` +
        `如果支付宝已扣款，请点「我已完成支付」重试，或刷新页面。`
    }
  } finally {
    payChecking.value = false
  }
}

/**
 * 支付成功的**统一收口**。
 *
 * ★ 为什么要统一：成功这件事有四条发现路径（轮询、手动查、取码撞 409、
 *   以及未来可能的其它），各写一遍必然有一条忘了关弹窗 / 忘了刷新订阅 ——
 *   而忘掉的那条会让用户看到"付完了但套餐没变"。
 */
async function onPaySucceeded() {
  resetPayState()
  showPayModal.value = false
  message.success('支付成功，套餐已生效')
  await Promise.all([loadSubscription(), loadInvoices()])
}

/** 关闭弹窗（用户主动"稍后再付"） */
function closePayModal() {
  stopPayPolling()
  showPayModal.value = false
}

/** 二维码过期 → 用**同一个套餐、同一个周期**重新下单 */
async function regenerateOrder() {
  const pay = payPayment.value
  closePayModal()
  if (!pay?.plan_id) {
    message.warning('请重新选择套餐')
    return
  }
  const plan = plans.value.find(x => x.id === pay.plan_id)
  if (!plan) {
    // ★ 两种「找不到」必须分开说：套餐列表**没加载出来**时报「已下架」
    //   是在替后端下一个它从没给过的结论（文案字面为真、暗示为假）。
    message.warning(
      plansError.value || plans.value.length === 0
        ? '套餐信息未加载成功，请刷新页面后重试'
        : '该套餐已下架，请重新选择',
    )
    return
  }
  selectedPlanForUpgrade.value = plan
  billingCycle.value = pay.billing_cycle
  await confirmSwitchPlan()
}

/**
 * 从账单历史的「去支付」进入同一套扫码流程。
 *
 * ★ 为什么不直接拿列表项的字段拼一个 payload：列表项与 `PendingPayment`
 *   **不是同一套字段**（少了 expires_at / payment_channel，多了 description /
 *   pdf_url）。照它拼就是第二份契约，必然与后端漂移。
 *   这里只拿 `record.id` 去问**权威来源**。
 */
async function openPayFromInvoice(record: Invoice) {
  payChecking.value = true
  try {
    const res = await fetchPaymentStatus(record.id)
    if (res.payment.status !== 'pending') {
      // 别人刚把它付掉了 / 它已过期：如实告知，别把用户带进一个死码里
      const why = res.payment.status === 'paid' ? '该账单已完成支付' : '该账单已失效'
      message.info(why)
      await loadInvoices()
      return
    }
    await openPayModal(res.payment)
  } catch (err: any) {
    message.error(err?.response?.data?.detail || '无法打开支付页面')
  } finally {
    payChecking.value = false
  }
}

/**
 * 页面加载时恢复未支付的二维码。
 *
 * ★ 没有这一步，"下单后刷新页面"就再也找不到那张码了 —— 用户只能重新下单，
 *   而支付宝侧可能已经有两张待付单，他很可能只付了其中一张
 *   ⇒ "付了钱没到账"的投诉。
 *
 * ★ 失败时**不**打开弹窗（拿不到权威状态就别猜），让拦截器正常报错。
 *   兜底出口是账单历史的「去支付」—— 那条是用户可以主动走的。
 */
async function restorePendingPayment() {
  try {
    const res = await fetchPendingPayment()
    if (res.payment) await openPayModal(res.payment)
  } catch (e) {
    // 拦截器已经报过了；这里只留诊断痕迹（不重复弹）
    console.warn('恢复待支付订单失败:', e)
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

// ====== 生命周期 ======
onMounted(async () => {
  await Promise.all([
    loadSubscription(),
    loadPlans(),
    loadInvoices(),
    loadPaymentMethods(),
  ])
  // ★ 放在 Promise.all **之后**：恢复二维码会用到 `plans`（反查套餐名），
  //   放在并行组里可能抢在套餐列表之前渲染出一个空名字。
  await restorePendingPayment()
})

// ★ 必须卸载定时器：离开订阅页后它还每 3 秒打一次后端（用户完全看不见），
//   而轮询的分数与内存会一直涨。
onUnmounted(stopPayPolling)
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
  /* ★ 底色必须走主题变量：横幅里的文字用的是 --text-primary / --text-tertiary，
     深色下它们是**白与半透明白** —— 硬编码浅绿底会让白字压浅绿底（实测 1.02:1，
     = 完全看不见）。浅色侧取值与原先逐字相同（#f6ffed → #e6fffb），零视觉变化。 */
  background: linear-gradient(135deg, var(--success-bg) 0%, var(--cyan-bg) 100%);
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
  color: var(--text-secondary);
}

/* ★ 本页的辅助文字（`/月`、`当前周期`、额度单位、支付说明…）统一用**二级**文字色：
   `--text-tertiary` 深色下是 0.45 alpha 的灰白，压在深底上只有 4.24:1、浅色下
   (#8c8c8c 压白底) 3.2:1 —— 两侧都不到 AA 的 4.5:1，正是「灰的很浅看不清」。
   全站 token 是否整体提亮属于另一件事（75 个文件在用），本页先局部达标。 */
.period-text {
  font-size: var(--font-size-13);
  color: var(--text-secondary);
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
  color: var(--text-secondary);
}

/* ====== 套餐网格 ====== */
.plans-card {
  margin-bottom: var(--space-24);
  /* ★ 它同时是「更换套餐」的滚动锚点：落位时顶部留一档余量，
     否则卡片标题会紧贴页面上沿，看着像被截掉了半行。 */
  scroll-margin-top: var(--space-16);
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
  /* ★ 底色是固定暖橙（物质色，不随主题翻）⇒ 字也必须是固定深色。
     写 #fff 时两侧都只有 1.9:1（浅色下同样不达标）。 */
  color: rgba(0, 0, 0, 0.85);
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
  /* ★ 底色是主题变量（深色下 = 亮绿 #73d13d），字也必须反色 ——
     写死 #fff 在深色下只有 1.92:1。 */
  color: var(--text-inverse);
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
  color: var(--text-secondary);
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
  /* ★ 不能硬编码深灰：深色主题下 #434343 压在 #1f1f1f 卡片底上只有 1.35:1
     （老板原话「字颜色灰的很浅看不清」）。走 --text-secondary，两侧都成立。 */
  color: var(--text-secondary);
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
/* 空态里的一句说明。★ 用主题变量而不是硬编码 #8c8c8c ——
   硬编码色在深色主题下会变成「深灰字压深底」（第 244 轮同类缺陷，
   `check-theme-var-refs.py` 管的正是这个）。 */
.payment-hint {
  font-size: var(--font-size-12);
  color: var(--text-secondary);
  margin-bottom: 0;
}

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
  color: var(--text-secondary);
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
  /* ★ 同「当前」徽标：--warning 深色下 = 亮黄 #ffc53d，白字立不住。 */
  color: var(--text-inverse);
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
  color: var(--text-secondary);
}
/* ====== 扫码支付弹窗 ====== */
.pay-dialog {
  text-align: center;
}

.pay-summary {
  display: flex;
  justify-content: space-between;
  align-items: baseline;
  padding-bottom: var(--space-8);
  border-bottom: 1px solid var(--border-base);
}

.pay-plan {
  font-size: var(--font-size-14);
  color: var(--text-secondary);
}

.pay-amount {
  font-size: var(--font-size-24);
  font-weight: 700;
  color: var(--text-primary);
}

.pay-order {
  margin-top: var(--space-8);
  font-size: var(--font-size-12);
  color: var(--text-secondary);
  word-break: break-all;
}

.pay-qr-area {
  display: flex;
  align-items: center;
  justify-content: center;
  min-height: 220px;
  margin: var(--space-16) 0;
}

.pay-qr-img {
  width: 200px;
  height: 200px;
  /* 白底是给二维码**本身**的：它是黑白点阵，深色主题下直接铺在暗背景上
     会因对比度反转而扫不出来。这里不是"没做深色适配"，是必要的。 */
  background: #fff;
  padding: var(--space-8);
  border-radius: var(--radius-8);
}

.pay-qr-placeholder {
  width: 200px;
  height: 200px;
  display: flex;
  align-items: center;
  justify-content: center;
  font-size: var(--font-size-13);
  color: var(--text-secondary);
  border: 1px dashed var(--border-base);
  border-radius: var(--radius-8);
}

.pay-status {
  font-size: var(--font-size-13);
  color: var(--text-secondary);
}

.pay-status strong {
  color: var(--primary);
  font-variant-numeric: tabular-nums;
}

.pay-status-expired {
  /* ★ `--danger` 而不是 `--error` —— 本仓的语义 token 里**没有** `--error`。
     写错的名字不会报错，只会让 color 落回继承值（灰的），
     "二维码已过期"于是看起来像一句普通说明，用户不会意识到要点重新生成。
     由 `scripts/check-theme-var-refs.py` 兜住（见本轮记录）。 */
  color: var(--danger);
}

.pay-poll-hint {
  margin-top: var(--space-8);
  padding: var(--space-8) var(--space-12);
  font-size: var(--font-size-12);
  line-height: 1.6;
  color: var(--warning);
  background: var(--warning-bg);
  border-radius: var(--radius-8);
  text-align: left;
}

.pay-actions {
  margin-top: var(--space-16);
  display: flex;
  flex-direction: column;
  gap: var(--space-8);
}

.pay-tip {
  margin-top: var(--space-12);
  font-size: var(--font-size-12);
  line-height: 1.6;
  color: var(--text-secondary);
}
</style>
