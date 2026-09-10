<template>
  <div class="blue-ocean-config">
    <!-- 市场基础 -->
    <a-collapse v-model:activeKey="activeKeys" :bordered="false" default-active-key="1,2">
      <a-collapse-panel key="1" header="📍 市场基础">
        <div class="form-group">
          <label>目标站点</label>
          <a-select
            v-model:value="form.marketplace"
            placeholder="自动读取店铺站点"
            size="small"
            style="width: 100%"
          >
            <a-select-option value="us">🇺🇸 美国 (US)</a-select-option>
            <a-select-option value="uk">🇬🇧 英国 (UK)</a-select-option>
            <a-select-option value="de">🇩🇪 德国 (DE)</a-select-option>
            <a-select-option value="jp">🇯🇵 日本 (JP)</a-select-option>
          </a-select>
        </div>

        <div class="form-group">
          <label>目标类目</label>
          <a-cascader
            v-model:value="form.category"
            :options="categoryOptions"
            placeholder="选择商品类目"
            size="small"
            style="width: 100%"
            change-on-select
          />
        </div>
      </a-collapse-panel>

      <a-collapse-panel key="2" header="💰 价格区间">
        <div class="form-row">
          <div class="form-group flex-1">
            <label>最低售价 ($)</label>
            <a-input-number
              v-model:value="form.priceMin"
              placeholder="不限"
              :min="0"
              :precision="2"
              size="small"
              style="width: 100%"
            />
          </div>
          <span class="form-separator">~</span>
          <div class="form-group flex-1">
            <label>最高售价 ($)</label>
            <a-input-number
              v-model:value="form.priceMax"
              placeholder="不限"
              :min="0"
              :precision="2"
              size="small"
              style="width: 100%"
            />
          </div>
        </div>
      </a-collapse-panel>

      <a-collapse-panel key="3" header="🎯 竞争筛选（蓝海核心）">
        <div class="form-group">
          <label>评论数上限</label>
          <a-input-number
            v-model:value="form.maxReviews"
            placeholder="如：≤100"
            :min="0"
            size="small"
            style="width: 100%"
            addon-after="条"
          />
          <span class="form-hint">控制低竞争，越低越蓝海</span>
        </div>

        <div class="form-group">
          <label>最小月销量</label>
          <a-input-number
            v-model:value="form.minMonthlySales"
            placeholder="保证需求"
            :min="0"
            size="small"
            style="width: 100%"
            addon-after="件/月"
          />
          <span class="form-hint">过滤无市场需求的产品</span>
        </div>

        <div class="form-group">
          <label>最低目标 ROI (%)</label>
          <a-input-number
            v-model:value="form.minRoi"
            placeholder="过滤低利润"
            :min="0"
            :max="100"
            size="small"
            style="width: 100%"
            addon-after="%"
          />
        </div>
      </a-collapse-panel>

      <a-collapse-panel key="4" header="⚙️ 高级筛选" :show-arrow="false">
        <div class="checkbox-group">
          <a-checkbox v-model:checked="form.excludeSeasonal">
            🚫 排除季节性商品
          </a-checkbox>
          <a-checkbox v-model:checked="form.excludeBrandDominance">
            🚫 排除品牌垄断商品
          </a-checkbox>
          <a-checkbox v-model:checked="form.excludeHighRisk">
            🚫 排除侵权高危品类
          </a-checkbox>
        </div>
      </a-collapse-panel>
    </a-collapse>

    <!-- 操作按钮 -->
    <div class="action-bar">
      <a-button @click="handleReset" block>
        <ReloadOutlined /> 重置条件
      </a-button>
      <a-button type="primary" @click="handleSubmit" block :loading="loading">
        <SearchOutlined /> 开始挖掘分析
      </a-button>
    </div>
  </div>
</template>

<script setup lang="ts">
import { ref, reactive, onMounted } from 'vue'
import { ReloadOutlined, SearchOutlined } from '@ant-design/icons-vue'
import { message } from 'ant-design-vue'
import { useShopStore } from '@/stores/shop'

const emit = defineEmits<{
  (e: 'startAnalysis', params: any): void
}>()

const shopStore = useShopStore()
const loading = ref(false)
const activeKeys = ref(['1', '2', '3'])

// 表单数据（带记忆）
const STORAGE_KEY = 'blue_ocean_config'

const defaultForm = () => ({
  marketplace: shopStore.currentShop?.platform?.replace('amazon_', '') || 'us',
  category: [] as string[],
  priceMin: null as number | null,
  priceMax: null as number | null,
  maxReviews: 100,
  minMonthlySales: 200,
  minRoi: 20,
  excludeSeasonal: false,
  excludeBrandDominance: true,
  excludeHighRisk: true,
})

const form = reactive(defaultForm())

// 类目选项
const categoryOptions = [
  { value: 'home_kitchen', label: 'Home & Kitchen', children: [
    { value: 'kitchen_dining', label: 'Kitchen & Dining' },
    { value: 'home_decor', label: 'Home Decor' },
    { value: 'storage', label: 'Storage & Organization' },
  ]},
  { value: 'electronics', label: 'Electronics', children: [
    { value: 'accessories', label: 'Accessories' },
    { value: 'audio', label: 'Audio' },
    { value: 'camera', label: 'Camera & Photo' },
  ]},
  { value: 'sports', label: 'Sports & Outdoors', children: [
    { value: 'fitness', label: 'Fitness' },
    { value: 'camping', label: 'Camping & Hiking' },
    { value: 'team_sports', label: 'Team Sports' },
  ]},
  { value: 'beauty', label: 'Beauty & Personal Care', children: [
    { value: 'skincare', label: 'Skin Care' },
    { value: 'makeup', label: 'Makeup' },
    { value: 'hair_care', label: 'Hair Care' },
  ]},
  { value: 'toys', label: 'Toys & Games', children: [
    { value: 'educational', label: 'Learning & Education' },
    { value: 'outdoor_play', label: 'Outdoor Play' },
  ]},
  { value: 'pet', label: 'Pet Supplies', children: [
    { value: 'dog_supplies', label: 'Dog Supplies' },
    { value: 'cat_supplies', label: 'Cat Supplies' },
  ]},
]

// 加载保存的配置
onMounted(() => {
  try {
    const saved = localStorage.getItem(STORAGE_KEY)
    if (saved) {
      const parsed = JSON.parse(saved)
      Object.assign(form, parsed)
    }
  } catch (e) {
    // 忽略解析错误
  }
})

// 保存配置
const saveConfig = () => {
  localStorage.setItem(STORAGE_KEY, JSON.stringify(form))
}

// 提交分析
const handleSubmit = () => {
  // 基础校验
  if (!form.category.length && !form.priceMin && !form.maxReviews) {
    message.warning('请至少设置一个筛选条件')
    return
  }

  loading.value = true
  saveConfig()

  // 发送参数给父组件
  emit('startAnalysis', { ...form })

  // 模拟按钮加载状态（实际由父组件控制）
  setTimeout(() => {
    loading.value = false
  }, 500)
}

// 重置
const handleReset = () => {
  Object.assign(form, defaultForm())
  localStorage.removeItem(STORAGE_KEY)
  message.success('已重置筛选条件')
}
</script>

<style scoped>
.blue-ocean-config {
  display: flex;
  flex-direction: column;
  gap: 12px;
}

.form-group {
  margin-bottom: 10px;
}

.form-group > label {
  display: block;
  font-size: 12px;
  color: #595959;
  margin-bottom: 4px;
  font-weight: 500;
}

.form-hint {
  display: block;
  font-size: 11px;
  color: #8c8c8c;
  margin-top: 2px;
}

.form-row {
  display: flex;
  align-items: flex-start;
  gap: 8px;
}

.flex-1 {
  flex: 1;
}

.form-separator {
  padding-top: 22px;
  color: #8c8c8c;
}

.checkbox-group {
  display: flex;
  flex-direction: column;
  gap: 8px;
}

.action-bar {
  display: flex;
  flex-direction: column;
  gap: 8px;
  margin-top: 12px;
  padding-top: 12px;
  border-top: 1px solid #f0f0f0;
}

/* 覆盖 ant-design 样式 */
:deep(.ant-collapse-header) {
  font-size: 13px !important;
  font-weight: 600 !important;
  padding: 8px 0 !important;
}

:deep(.ant-collapse-content-box) {
  padding: 12px 0 !important;
}
</style>
