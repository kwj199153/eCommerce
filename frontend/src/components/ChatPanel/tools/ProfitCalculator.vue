<template>
  <div class="profit-calculator">
    <h2 class="sr-only">Dynamic Profit Calculator</h2>

    <!-- 店铺上下文栏（自动读取，不显示选择器） -->
    <div class="store-context-bar" :class="{ 'is-amazon': isAmazon, 'is-shopee': isShopee }">
      <ShopOutlined class="icon" />
      <span class="store-name">{{ currentStore?.name || '未选择店铺' }}</span>
      <a-tag v-if="currentStore" :color="platformColor" size="small">
        {{ platformLabel }}
      </a-tag>
      <span v-if="currentStore?.currency" class="currency">{{ currentStore.currency }}</span>
    </div>

    <a-form
      :model="formState"
      layout="vertical"
      @submit.prevent="handleCalculate"
    >
      <!-- ===== 通用字段 ===== -->
      <a-divider orientation="left" plain>基础成本</a-divider>

      <a-form-item label="产品成本" required>
        <a-input-number
          v-model:value="formState.product_cost"
          :min="0"
          :precision="2"
          style="width: 100%"
          placeholder="如: 55.00"
          addon-after="(元)"
        >
          <template #prefix>¥</template>
        </a-input-number>
      </a-form-item>

      <a-form-item label="广告费用">
        <a-input-number
          v-model:value="formState.ad_cost"
          :min="0"
          :precision="2"
          style="width: 100%"
          placeholder="0 = 不投广告"
        />
      </a-form-item>

      <!-- ===== Amazon 专属字段 ===== -->
      <template v-if="isAmazon">
        <a-divider orientation="left" plain>Amazon 费用配置</a-divider>

        <a-row :gutter="12">
          <a-col :span="12">
            <a-form-item label="佣金比例 (%)">
              <a-input-number
                v-model:value="feeConfig.referral_fee_pct"
                :min="0"
                :max="45"
                :step="0.5"
                style="width: 100%"
              />
            </a-form-item>
          </a-col>
          <a-col :span="12">
            <a-form-item label="FBA 配送费">
              <a-input-number
                v-model:value="feeConfig.fba_fulfillment_fee"
                :min="0"
                :precision="2"
                style="width: 100%"
              />
            </a-form-item>
          </a-col>
        </a-row>

        <a-row :gutter="12">
          <a-col :span="12">
            <a-form-item label="月仓储费">
              <a-input-number
                v-model:value="feeConfig.storage_fee_monthly"
                :min="0"
                :precision="2"
                style="width: 100%"
              />
            </a-form-item>
          </a-col>
          <a-col :span="12">
            <a-form-item label="VAT 税率 (%)">
              <a-input-number
                v-model:value="feeConfig.vat_rate"
                :min="0"
                :max="25"
                :step="1"
                style="width: 100%"
              />
            </a-form-item>
          </a-col>
        </a-row>

        <a-alert
          v-if="feeConfig.vat_rate > 0"
          type="info"
          show-icon
          message="注意：该站点已启用 VAT，将自动计入费用计算"
          style="margin-bottom: 12px"
        />
      </template>

      <!-- ===== Shopee 专属字段 ===== -->
      <template v-if="isShopee">
        <a-divider orientation="left" plain>Shopee 费用配置</a-divider>

        <a-row :gutter="12">
          <a-col :span="12">
            <a-form-item label="佣金比例 (%)">
              <a-input-number
                v-model:value="feeConfig.commission_pct"
                :min="0"
                :max="20"
                :step="0.1"
                style="width: 100%"
              />
            </a-form-item>
          </a-col>
          <a-col :span="12">
            <a-form-item label="交易费 (固定)">
              <a-input-number
                v-model:value="feeConfig.transaction_fee"
                :min="0"
                :precision="2"
                style="width: 100%"
              />
            </a-form-item>
          </a-col>
        </a-row>

        <a-row :gutter="12">
          <a-col :span="12">
            <a-form-item label="商业增长费 (%)">
              <a-tooltip title="Shopee 独有费用项">
                <a-input-number
                  v-model:value="feeConfig.growth_fee_pct"
                  :min="0"
                  :max="15"
                  :step="0.1"
                  style="width: 100%"
                />
              </a-tooltip>
            </a-form-item>
          </a-col>
          <a-col :span="12">
            <a-form-item label="基础设施费 (固定)">
              <a-tooltip title="Shopee 独有费用项">
                <a-input-number
                  v-model:value="feeConfig.infrastructure_fee"
                  :min="0"
                  :precision="2"
                  style="width: 100%"
                />
              </a-tooltip>
            </a-form-item>
          </a-col>
        </a-row>

        <a-row :gutter="12">
          <a-col :span="8">
            <a-form-item label="物流成本 (SLS)">
              <a-input-number
                v-model:value="feeConfig.logistics_cost"
                :min="0"
                :precision="2"
                style="width: 100%"
              />
            </a-form-item>
          </a-col>
          <a-col :span="8">
            <a-form-item label="VAT/税费 (%)">
              <a-input-number
                v-model:value="feeConfig.shopee_vat_rate"
                :min="0"
                :max="25"
                :step="0.5"
                style="width: 100%"
              />
            </a-form-item>
          </a-col>
          <a-col :span="8">
            <a-form-item label="提现手续费率 (%)">
              <a-input-number
                v-model:value="feeConfig.withdrawal_fee_rate"
                :min="0"
                :max="5"
                :step="0.1"
                style="width: 100%"
              />
            </a-form-item>
          </a-col>
        </a-row>

        <!-- Shopee 折扣设置 -->
        <a-divider orientation="left" plain>折扣策略（Shopee 多层折扣）</a-divider>

        <a-form-item label="优惠券 / 平台券折扣 (%)">
          <a-slider
            v-model:value="feeConfig.coupon_discount_pct"
            :min="0"
            :max="50"
            :marks="{ 0: '无', 10: '10%', 20: '20%' }"
          />
        </a-form-item>

        <a-form-item label="闪购 / 商品折扣 (%)">
          <a-slider
            v-model:value="feeConfig.flash_sale_discount_pct"
            :min="0"
            :max="70"
            :marks="{ 0: '无', 30: '30%', 45: '45%', 60: '60%' }"
          />
        </a-form-item>

        <a-alert
          type="info"
          show-icon
          :message="`成交价 = 原价 × ${100 - feeConfig.coupon_discount_pct}% × ${100 - feeConfig.flash_sale_discount_pct}%`"
          style="margin-bottom: 12px"
        />
      </template>

      <!-- ===== 计算模式切换 ===== -->
      <a-divider orientation="left" plain>计算模式</a-divider>

      <a-radio-group v-model:value="calcMode" button-style="solid" style="width: 100%">
        <a-radio-button value="forward" style="flex: 1; text-align: center">
          正向计算
          <br /><small>已知售价 → 算利润</small>
        </a-radio-button>
        <a-radio-button value="reverse" style="flex: 1; text-align: center">
          逆向定价
          <br /><small>已知利润 → 反推原价</small>
        </a-radio-button>
      </a-radio-group>

      <a-form-item v-if="calcMode === 'forward'" label="售价 / 原价" required>
        <a-input-number
          v-model:value="formState.listing_price"
          :min="0"
          :precision="2"
          style="width: 100%"
          placeholder="输入产品的售价或原价"
        />
      </a-form-item>

      <a-form-item v-else label="目标毛利" required>
        <a-input-number
          v-model:value="formState.target_profit"
          :min="0"
          :precision="2"
          style="width: 100%"
          placeholder="期望获得的毛利金额"
        />
      </a-form-item>

      <!-- 提交按钮 -->
      <a-button
        type="primary"
        block
        size="large"
        :loading="loading"
        :disabled="!canCalculate"
        @click="handleCalculate"
      >
        {{ calcMode === 'forward' ? '计算利润' : '反推定价' }}
      </a-button>
    </a-form>

    <!-- ===== 结果展示 ===== -->
    <div v-if="result" class="result-panel">
      <a-divider orientation="left">计算结果 ({{ result.currency }})</a-divider>

      <!-- 价格摘要 -->
      <div class="price-summary">
        <div class="price-main">
          <span class="label">原价 / 定价:</span>
          <span class="value primary">{{ result.listing_price }}</span>
        </div>
        <div v-if="result.discount_applied" class="price-final">
          <span class="label">成交价:</span>
          <span class="value warning">{{ result.final_price }}</span>
          <a-badge
            :count="`-${result.effective_discount_pct.toFixed(1)}%`"
            :number-style="{ backgroundColor: '#fa8c16' }"
          />
        </div>
      </div>

      <!-- 费用明细表 -->
      <a-table
        :columns="feeColumns"
        :data-source="feeDataSource"
        size="small"
        :pagination="false"
        :show-header="true"
        bordered
        row-key="name"
        style="margin-top: 12px"
      />

      <!-- 利润指标 -->
      <div class="profit-highlight">
        <div class="metric">
          <span class="label">毛利额</span>
          <strong class="value" :class="{ positive: result.gross_profit > 0, negative: result.gross_profit <= 0 }">
            {{ result.gross_profit > 0 ? '+' : '' }}{{ result.gross_profit }}
          </strong>
        </div>
        <div class="metric">
          <span class="label">毛利率</span>
          <strong>{{ result.profit_margin_pct }}%</strong>
        </div>
        <div class="metric">
          <span class="label">ROI</span>
          <strong>{{ result.roi }}%</strong>
        </div>
      </div>

      <!-- 公式说明 -->
      <a-alert
        v-if="result.formula_summary"
        type="success"
        show-icon
        :message="result.formula_summary"
        style="margin-top: 12px"
      />

      <!-- 计算模式标签 -->
      <div style="text-align: right; margin-top: 8px">
        <a-tag :color="result.calculation_mode === 'reverse' ? 'blue' : 'green'">
          {{ result.calculation_mode === 'reverse' ? '逆向定价' : '正向计算' }}
        </a-tag>
      </div>
    </div>
  </div>
</template>

<script setup lang="ts">
import { ref, computed, watch, onMounted } from 'vue'
import { message } from 'ant-design-vue'
import { ShopOutlined } from '@ant-design/icons-vue'

import { useShopStore } from '@/stores/shop'
import {
  calculateProfit,
  fetchFeeTemplate,
  type ProfitResult,
  type FeeBreakdownItem,
} from '@/api/stores'

const shopStore = useShopStore()

// ====== 自动读取当前选中店铺 ======
const currentStore = computed(() => shopStore.currentShop)

const isAmazon = computed(() =>
  currentStore.value?.platform?.startsWith('amazon') ?? false
)
const isShopee = computed(() =>
  currentStore.value?.platform?.startsWith('shopee') ?? false
)

const platformColor = computed(() => {
  if (isAmazon.value) return 'orange'
  if (isShopee.value) return 'green'
  return 'default'
})

const platformLabel = computed(() => {
  if (!currentStore.value) return ''
  const p = currentStore.value.platform
  const labels: Record<string, string> = {
    amazon_us: 'Amazon US', amazon_uk: 'Amazon UK',
    shopee_my: 'Shopee MY', shopee_tw: 'Shopee TW',
  }
  return labels[p] || p.replace('_', ' ').toUpperCase()
})

// ====== 表单状态 ======
const formState = ref({
  product_cost: 55.00,
  ad_cost: 0,
  listing_price: null as number | null,
  target_profit: null as number | null,
})

const calcMode = ref<'forward' | 'reverse'>('forward')

// ====== 动态费率配置（根据平台切换）=====
const feeConfig = ref({
  // Amazon 字段
  referral_fee_pct: 15,
  fba_fulfillment_fee: 3.22,
  storage_fee_monthly: 0.87,
  vat_rate: 0,

  // Shopee 字段
  commission_pct: 5.5,
  transaction_fee: 4.74,
  growth_fee_pct: 6.41,
  infrastructure_fee: 1.07,
  logistics_cost: 12.5,
  shopee_vat_rate: 0,
  withdrawal_fee_rate: 1,

  // 折扣
  coupon_discount_pct: 10,
  flash_sale_discount_pct: 45,
})

// 监听店铺切换 → 自动加载对应费率模板
watch(currentStore, async (newStore) => {
  if (!newStore) return

  try {
    // 从后端加载该站点的默认费率
    const template = await fetchFeeTemplate(newStore.platform)
    if (template?.config) {
      Object.assign(feeConfig.value, template.config)
    }
  } catch {
    // 使用硬编码的默认值（已在上面初始化）
  }

  // 重置结果
  result.value = null
}, { immediate: true })

// ====== 计算逻辑 ======
const loading = ref(false)
const result = ref<ProfitResult | null>(null)

const canCalculate = computed(() => {
  if (!currentStore.value) return false
  if (formState.value.product_cost <= 0) return false
  if (calcMode.value === 'forward') {
    return formState.value.listing_price !== null && formState.value.listing_price > 0
  } else {
    return formState.value.target_profit !== null && formState.value.target_profit > 0
  }
})

async function handleCalculate() {
  if (!currentStore.value) {
    message.warning('请先在左侧选择一个店铺')
    return
  }

  loading.value = true
  try {
    result.value = await calculateProfit(
      {
        product_cost: formState.value.product_cost,
        listing_price: formState.value.listing_price,
        target_profit: formState.value.target_profit,
        ad_cost: formState.value.ad_cost || 0,
      },
      currentStore.value.id,
    )
    message.success('计算完成')
  } catch (err: any) {
    console.error('利润计算失败:', err)
    message.error(err?.response?.data?.detail || '计算失败，请检查输入参数')
  } finally {
    loading.value = false
  }
}

// ====== 结果表格列定义 ======
const feeColumns = [
  {
    title: '费用项目',
    dataIndex: 'name',
    key: 'name',
    width: '40%',
  },
  {
    title: '金额',
    key: 'amount',
    customRender: ({ record }: { record: FeeBreakdownItem }) => `${record.amount}`,
  },
  {
    title: '类型',
    key: 'type',
    width: '25%',
    customRender: ({ record }: { record: FeeBreakdownItem }) =>
      record.is_percentage
        ? `比例 (${record.percentage_value}%)`
        : '固定金额',
  },
]

const feeDataSource = computed<FeeBreakdownItem[]>(() =>
  result.value?.fee_breakdown || []
)
</script>

<style scoped>
.profit-calculator {
  padding: 4px;
}

.store-context-bar {
  display: flex;
  align-items: center;
  gap: 8px;
  padding: 10px 14px;
  border-radius: 8px;
  margin-bottom: 16px;
  background: var(--bg-hover-light);
  font-size: 13px;
}

.store-context-bar.is-amazon {
  background: rgba(250, 173, 20, 0.08);
  border: 1px solid rgba(250, 173, 20, 0.3);
}

.store-context-bar.is-shopee {
  background: rgba(82, 196, 26, 0.08);
  border: 1px solid rgba(82, 196, 26, 0.3);
}

.store-context-bar .icon {
  color: var(--primary);
}

.store-context-bar .store-name {
  font-weight: 500;
  flex: 1;
  color: var(--text-primary);
}

.store-context-bar .currency {
  font-size: 11px;
  color: var(--text-tertiary);
  font-weight: 500;
}

.result-panel {
  margin-top: 20px;
  padding: 16px;
  background: var(--bg-hover-light);
  border-radius: 8px;
  border: 1px solid var(--border-base);
}

.price-summary {
  display: flex;
  gap: 24px;
  align-items: baseline;
  flex-wrap: wrap;
}

.price-main,
.price-final {
  display: flex;
  align-items: baseline;
  gap: 6px;
}

.price-main .label,
.price-final .label {
  font-size: 13px;
  color: var(--text-secondary);
}

.value.primary {
  font-size: 22px;
  font-weight: 600;
  color: var(--text-primary);
}

.value.warning {
  font-size: 26px;
  font-weight: 700;
  color: var(--danger);
}

.profit-highlight {
  display: flex;
  justify-content: space-around;
  margin-top: 16px;
  padding: 14px;
  background: var(--bg-elevated);
  border-radius: 8px;
  border: 1px solid var(--border-base);
}

.metric {
  text-align: center;
}

.metric .label {
  display: block;
  font-size: 12px;
  color: var(--text-tertiary);
  margin-bottom: 4px;
}

.metric .value {
  font-size: 18px;
  color: var(--text-primary);
}

.metric .value.positive {
  color: #52c41a;
}

.metric .value.negative {
  color: #ff4d4f;
}
</style>
