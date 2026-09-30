<template>
  <div class="blue-ocean-config" :class="{ 'data-mode': isDataMode }">
    <!-- 大屏模式：左表单 + 右产品清单结果窗口（第 312 轮对齐 AIGC 范式） -->
    <div class="bo-content" :class="{ 'data-layout': isDataMode }">
      <div class="bo-form">
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
              <span v-if="prefillHint" class="form-hint prefill-hint">{{ prefillHint }}</span>
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

      <!-- 大屏模式：右栏产品清单结果窗口（复用 BlueOceanResult，结果不进对话流） -->
      <div v-if="isDataMode" class="bo-result">
        <div v-if="isGenerating" class="preview-loading">
          <a-spin size="large" />
          <p class="preview-loading-title">正在挖掘蓝海产品…</p>
        </div>
        <BlueOceanResult
          v-else-if="latestResult"
          :data="latestResult"
          @close="latestResult = null"
        />
        <a-empty
          v-else
          description="暂无挖掘结果，点「开始挖掘分析」出产品清单"
          :image-style="{ height: '48px' }"
        />
      </div>
    </div>
  </div>
</template>

<script setup lang="ts">
import { ref, reactive, inject, watch, computed, type Ref } from 'vue'
import { ReloadOutlined, SearchOutlined } from '@ant-design/icons-vue'
import { message } from 'ant-design-vue'
import { useShopStore } from '@/stores/shop'
import { useProductResearchResultsStore } from '@/stores/productResearchResults'
import BlueOceanResult from '@/components/ChatPanel/results/BlueOceanResult.vue'
import { CATEGORY_TAXONOMY, isValidCategoryPath } from '@/config/categoryTaxonomy'

const emit = defineEmits<{
  (e: 'startAnalysis', params: any): void
}>()

// ====== 大屏/对话模式：读 Workspace 注入的 reviewMode（第 312 轮对齐 AIGC 双模式）======
// 大屏模式下「左表单右产品清单结果窗口」左右分栏；对话模式结果走对话流（不进这里）。
const reviewMode = inject<Ref<'chat' | 'data'>>('reviewMode', ref('chat') as Ref<'chat' | 'data'>)
const isDataMode = computed(() => reviewMode.value === 'data')

// ====== 大屏结果窗口（结果存在 store，切工具不丢，对齐 aigcResults）======
const BO_TOOL_ID = 'blue-ocean'
const productResults = useProductResearchResultsStore()
const latestResult = computed<any>({
  get: () => productResults.getResult(BO_TOOL_ID),
  set: (v: any) => (v ? productResults.setResult(BO_TOOL_ID, v) : productResults.clearResult(BO_TOOL_ID)),
})
const isGenerating = computed<boolean>({
  get: () => productResults.isGenerating(BO_TOOL_ID),
  set: (v: boolean) => productResults.setGenerating(BO_TOOL_ID, v),
})

// ====== 选品大盘 → 蓝海挖掘 预填通道（第 306 轮）======
// 点选品大盘色块时，父层 TaskConfigPanel 写入 blueOceanPrefill；
// 这里 watch 它，命中同一时间戳即消费，把类目/站点预填进表单。
// 色块是「类目」粒度，预填进来是让用户接着细化价格/竞争条件去挖产品，
// 不是把类目当产品塞进候选池。
interface BlueOceanPrefillPayload {
  categoryPath: string
  categoryName: string
  site: string
  ts: number
}
const blueOceanPrefill = inject<Ref<BlueOceanPrefillPayload | null>>('blueOceanPrefill', ref(null))
const prefillHint = ref<string>('')
let lastConsumedTs = 0

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

// ★ 记忆恢复必须在预填 watch（immediate）之前、且在 setup 同步阶段完成：
//   点色块跳转时 prefill watch 同步填入类目；若恢复放在 onMounted（晚于 watch），
//   Object.assign 会把预填类目覆盖回上次保存值——「提示已预填、cascader 却空」的断层根因（r307）。
//   语义：记忆做底、预填优先。
try {
  const saved = localStorage.getItem(STORAGE_KEY)
  if (saved) Object.assign(form, JSON.parse(saved))
} catch {
  // 忽略解析错误
}

// 类目选项：唯一真源 config/categoryTaxonomy（大盘组名/色块名/预填校验同源，r310）。
// 不再内联——内联过一份、大盘显示名另走一份，才有「大盘显示 Coffee Machines、
// cascader 只有 Kitchen & Dining」的子类目错位。
const categoryOptions = CATEGORY_TAXONOMY

// 站点 slug → 表单 marketplace 值（seed 用 amazon_us / amazon_uk / shopee_sg）
const SITE_MAP: Record<string, string> = {
  amazon_us: 'us',
  amazon_uk: 'uk',
  amazon_de: 'de',
  amazon_jp: 'jp',
}

/**
 * 把大盘色块的 category_path 映射到蓝海表单的 cascader 值（top/mid 两级）。
 * ★ 真源 = config/categoryTaxonomy（r310）：path 前两级必须在类目体系内才映射，
 *   否则返回 null —— 不猜、留空 + 出提示（fail-closed），不静默乱填。
 */
function mapCategoryPath(path: string): string[] | null {
  const parts = (path || '').split('/').filter(Boolean)
  if (parts.length < 2) return null
  const top = parts[0] ?? ''
  const mid = parts[1] ?? ''
  return isValidCategoryPath(top, mid) ? [top, mid] : null
}

// 预填消费：同一时间戳只消费一次，避免 watch 重复触发 / 组件重建后重放
watch(
  blueOceanPrefill,
  (payload) => {
    if (!payload || payload.ts === lastConsumedTs) return
    lastConsumedTs = payload.ts

    // 站点：映射得到的填，映射不到的保留当前值 + 提示
    const site = SITE_MAP[payload.site]
    if (site) form.marketplace = site

    // 类目：映射得到的填进 cascader；映射不到的不猜，出提示并清空旧选择
    const mapped = mapCategoryPath(payload.categoryPath)
    if (mapped) {
      form.category = mapped
      prefillHint.value = `已按「${payload.categoryName}」预填类目，可继续细化价格/竞争条件`
    } else {
      form.category = []
      prefillHint.value = `「${payload.categoryName}」暂无对应类目选项，请手动选择类目`
    }
    // 展开市场基础面板，让用户看到预填结果
    if (!activeKeys.value.includes('1')) activeKeys.value.push('1')
  },
  { immediate: true }
)

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
  gap: var(--space-12);
  height: 100%;
  min-height: 0;
}

/* 大屏模式：左表单 + 右结果窗口左右分栏 */
.bo-content {
  display: flex;
  flex-direction: column;
  gap: var(--space-12);
  min-height: 0;
  flex: 1;
}
.bo-content.data-layout {
  display: grid;
  grid-template-columns: minmax(280px, 1fr) minmax(280px, 1.3fr);
  gap: var(--space-12);
  overflow: hidden;
}
.bo-form {
  min-height: 0;
  overflow-y: auto;
}
.bo-result {
  min-height: 0;
  overflow-y: auto;
  border-left: 1px solid var(--border-base);
  padding-left: var(--space-10);
  display: flex;
  flex-direction: column;
}

/* 大屏结果窗口 loading（对齐 AIGC preview-loading） */
.preview-loading {
  flex: 1;
  display: flex;
  flex-direction: column;
  align-items: center;
  justify-content: center;
  gap: var(--space-10);
  padding: var(--space-40) var(--space-16);
  color: var(--text-secondary);
}
.preview-loading-title {
  margin: 0;
  font-size: var(--font-size-13);
  font-weight: 600;
  color: var(--text-primary);
}

.form-group {
  margin-bottom: var(--space-10);
}

.form-group > label {
  display: block;
  font-size: var(--font-size-12);
  color: var(--text-secondary);
  margin-bottom: var(--space-4);
  font-weight: 500;
}

.form-hint {
  display: block;
  font-size: var(--font-size-11);
  color: var(--text-tertiary);
  margin-top: var(--space-2);
}

/* 选品大盘跳转过来的预填提示（比普通 hint 更醒目，用 primary 色） */
.prefill-hint {
  color: var(--primary);
}

.form-row {
  display: flex;
  align-items: flex-start;
  gap: var(--space-8);
}

.flex-1 {
  flex: 1;
}

.form-separator {
  padding-top: var(--space-22);
  color: var(--text-tertiary);
}

.checkbox-group {
  display: flex;
  flex-direction: column;
  gap: var(--space-8);
}

.action-bar {
  display: flex;
  flex-direction: column;
  gap: var(--space-8);
  margin-top: var(--space-12);
  padding-top: var(--space-12);
  border-top: 1px solid var(--border-base);
}

/* 覆盖 ant-design 样式 */
:deep(.ant-collapse-header) {
  font-size: var(--font-size-13) !important;
  font-weight: 600 !important;
  padding: var(--space-8) 0 !important;
}

:deep(.ant-collapse-content-box) {
  padding: var(--space-12) 0 !important;
}
</style>
