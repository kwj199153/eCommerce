<template>
  <!-- 单行详情抽屉：点击行尾「详情」右侧滑出完整数据 -->
  <a-drawer
    v-model:open="open"
    :width="460"
    placement="right"
    :closable="true"
    :title="record ? `${record.asin} 完整档案` : '商品档案'"
  >
    <template v-if="record">
      <!-- 头部：图 + 标题 + 直达 -->
      <div class="detail-hero">
        <img
          v-if="record.main_image || record.image"
          class="detail-hero-img"
          :src="record.main_image || record.image"
          alt=""
          loading="lazy"
          @error="onImgError"
        />
        <span v-else class="detail-hero-ph">🖼️</span>
        <div class="detail-hero-info">
          <div class="detail-hero-title">{{ record.title }}</div>
          <div class="detail-hero-sub">
            <span class="detail-brand">{{ record.brand || '-' }}</span>
            <a
              class="detail-link"
              :href="listingUrl(record.asin, record.marketplace)"
              target="_blank"
              rel="noopener"
            >🔗 打开亚马逊 Listing ↗</a>
          </div>
        </div>
      </div>

      <!-- 综合指标头图 -->
      <div class="detail-kpis">
        <div class="dkpi">
          <div class="dkpi-label">蓝海评分</div>
          <div class="dkpi-val" :style="{ color: getScoreColor(record.blue_ocean_score) }">{{ record.blue_ocean_score }}</div>
        </div>
        <div class="dkpi">
          <div class="dkpi-label">售价</div>
          <div class="dkpi-val mono">${{ money(record.price) }}</div>
        </div>
        <div class="dkpi">
          <div class="dkpi-label">月销</div>
          <div class="dkpi-val mono">{{ record.estimated_monthly_sales ? Number(record.estimated_monthly_sales).toLocaleString() : '-' }}</div>
        </div>
        <div class="dkpi">
          <div class="dkpi-label">ROI</div>
          <div class="dkpi-val" :class="roiClass(record.roi_estimated)">{{ record.roi_estimated }}%</div>
        </div>
      </div>

      <!-- 合规 / 风险标签 -->
      <div class="detail-section">
        <div class="detail-section-title">🏷️ 判定标签</div>
        <div class="detail-tags">
          <a-tag v-for="(t, i) in complianceTags(record)" :key="i" :color="t.type">{{ t.text }}</a-tag>
        </div>
      </div>

      <!-- AI 洞察 -->
      <div class="detail-section">
        <div class="detail-section-title">🤖 AI 洞察</div>
        <div class="detail-insight">{{ aiInsight(record) }}</div>
      </div>

      <!-- 基本信息 -->
      <div class="detail-section">
        <div class="detail-section-title">📋 基本信息</div>
        <div class="detail-rows">
          <div class="drow"><span>站点</span><b>{{ record.marketplace || 'Amazon US' }}</b></div>
          <div class="drow"><span>完整类目</span><b>{{ (record.category_path || []).join(' › ') || record.category_l2 || '-' }}</b></div>
          <div class="drow"><span>上架时间</span><b>{{ record.listed_date || '-' }}</b></div>
          <div class="drow"><span>上架时长</span><b>{{ listedAge(record) }}</b></div>
          <div class="drow"><span>重量 / 尺寸</span><b>{{ record.weight_lbs ? record.weight_lbs + ' lb' : '-' }} / {{ record.dimensions || '-' }} in</b></div>
          <div class="drow"><span>卖家数</span><b>{{ record.seller_count ?? '-' }}</b></div>
        </div>
      </div>

      <!-- 市场指标 -->
      <div class="detail-section">
        <div class="detail-section-title">📈 市场指标</div>
        <div class="detail-rows">
          <div class="drow"><span>BSR 排名</span><b>#{{ record.bsr_rank ? Number(record.bsr_rank).toLocaleString() : '-' }} <span class="muted">{{ record.bsr_category || '' }}</span></b></div>
          <div class="drow"><span>商品星级</span><b :class="ratingClass(record.rating)">★ {{ record.rating ? Number(record.rating).toFixed(1) : '-' }}</b></div>
          <div class="drow"><span>评论数</span><b>{{ record.review_count ? Number(record.review_count).toLocaleString() : '-' }}</b></div>
          <div class="drow"><span>变体数量</span><b>{{ record.variation_count ?? 1 }}</b></div>
          <div class="drow"><span>30天价格波动</span><b :class="(record.price_trend_30d ?? 0) >= 0 ? 'trend-up' : 'trend-down'">{{ record.price_trend_30d ?? 0 }}%</b></div>
          <div class="drow"><span>30天销量波动</span><b :class="(record.sales_trend_30d ?? 0) >= 0 ? 'trend-up' : 'trend-down'">{{ record.sales_trend_30d ?? 0 }}%</b></div>
        </div>
      </div>

      <!-- 成本拆解 -->
      <div class="detail-section">
        <div class="detail-section-title">💰 成本拆解（单件）</div>
        <div class="cost-box">
          <div class="cost-row"><span>售价</span><b>${{ money(record.price) }}</b></div>
          <div class="cost-row"><span>采购成本</span><b>${{ money(record.cost_price) }}</b></div>
          <div class="cost-row"><span>头程物流</span><b>${{ money(record.freight_cost ?? estFreight(record)) }}</b></div>
          <div class="cost-row"><span>平台佣金</span><b>${{ money(commission(record)) }}</b></div>
          <div class="cost-row"><span>FBA 配送费</span><b>${{ money(record.fba_fees) }}</b></div>
          <div class="cost-divider"></div>
          <div class="cost-row net"><span>预估净利</span><b>${{ money(record.net_profit ?? estNet(record)) }}</b></div>
          <div class="cost-row total"><span>ROI</span><b :class="roiClass(record.roi_estimated)">{{ record.roi_estimated }}%</b></div>
        </div>
      </div>

      <!-- Listing 卖点 -->
      <div v-if="record.selling_points?.length" class="detail-section">
        <div class="detail-section-title">💡 核心卖点</div>
        <ul class="detail-points">
          <li v-for="(sp, i) in record.selling_points" :key="i">{{ sp }}</li>
        </ul>
      </div>

      <!-- Listing 质量评分 -->
      <div class="detail-section">
        <div class="detail-section-title">📊 Listing 质量</div>
        <div class="lq-rows">
          <div class="lq-row">
            <span>标题</span>
            <a-progress :percent="record.title_score" :stroke-color="getScoreColor(record.title_score)" size="small" />
          </div>
          <div class="lq-row">
            <span>五点</span>
            <a-progress :percent="record.bullet_score" :stroke-color="getScoreColor(record.bullet_score)" size="small" />
          </div>
          <div class="lq-row">
            <span>图片</span>
            <a-progress :percent="record.image_score" :stroke-color="getScoreColor(record.image_score)" size="small" />
          </div>
          <div class="lq-row">
            <span>综合</span>
            <a-progress :percent="record.overall_listing_score" :stroke-color="getScoreColor(record.overall_listing_score)" size="small" />
          </div>
        </div>
      </div>

      <!-- 底部操作 -->
      <div class="detail-actions">
        <a-button
          type="primary"
          block
          :disabled="saved"
          @click="onSave"
        >
          {{ saved ? '✓ 已加入选品库' : '➕ 保存到选品库' }}
        </a-button>
        <!-- 游离监控：蓝海随手盯，不归属任何项目，仅入统一监控池独立跟踪 -->
        <a-button
          block
          class="mon-btn"
          :type="isMonitored ? 'default' : 'dashed'"
          @click="onToggleMonitor"
        >
          <template v-if="isMonitored">
            <FundOutlined /> 已开启游离监控 · 查看走势 ›
          </template>
          <template v-else>
            <FundOutlined /> 🛰️ 开启游离监控（不归属，独立盯）
          </template>
        </a-button>
      </div>
    </template>
  </a-drawer>
</template>

<script setup lang="ts">
import { computed } from 'vue'
import { FundOutlined } from '@ant-design/icons-vue'
import { message } from 'ant-design-vue'
import { useMonitorPoolStore } from '@/stores/monitorPool'

const props = defineProps<{
  record: any
  saved: boolean
}>()

const emit = defineEmits<{
  (e: 'navigateTo', view: string): void
  (e: 'save', record: any): void
}>()

const open = defineModel<boolean>('open', { required: true })

const monitorStore = useMonitorPoolStore()

// ====== 游离监控 ======
const isMonitored = computed(() =>
  props.record ? monitorStore.isAsinInPool(props.record.asin) : false
)

/** 切换游离监控：已入池则跳转竞品监控页定位；未入池则加入（无归属） */
function onToggleMonitor() {
  const record = props.record
  if (!record?.asin) return
  if (isMonitored.value) {
    monitorStore.setSelected([record.asin])
    monitorStore.selectGroup(null)
    monitorStore.selectOwnership('all')
    emit('navigateTo', 'monitor')
    message.success(`已定位到 ${record.asin} 的竞品监控`)
    return
  }
  const { added } = monitorStore.addFreeMonitor({
    asin: record.asin,
    title: record.title,
    brand: extractBrand(record.title),
    main_image: record.main_image || record.image,
    latest_price: parseFloat(record.price) || undefined,
    latest_bsr: record.bsr_rank || undefined,
    rating: parseFloat(record.rating) || undefined,
    review_count: parseInt(record.review_count) || undefined,
    est_monthly_sales: parseInt(record.estimated_monthly_sales) || undefined,
    bsr_category: record.bsr_category || undefined,
  })
  if (added) {
    message.success(`已将 ${record.asin} 加入监控池（游离监控，后台定时抓取价格/BSR/评论）`)
  } else {
    message.info(`${record.asin} 已在监控池中`)
  }
}

/** 从详情抽屉保存单个候选：通知父组件执行（父组件持 mapToCandidate + addItem 逻辑） */
function onSave() {
  const record = props.record
  if (!record) return
  emit('save', record)
}

/** 从标题提取品牌名（简单启发式） */
function extractBrand(title: string): string {
  const words = title.split(/\s+/)
  if (words.length >= 2) return words[0]
  return ''
}

// ====== 工具函数 ======
const getScoreColor = (score: number): string => {
  if (score >= 70) return '#52c41a'
  if (score >= 40) return '#faad14'
  return '#ff4d4f'
}

/** 金额格式化：保留 2 位小数，去掉多余 0 尾 */
const money = (v: any): string => {
  const n = parseFloat(v)
  if (isNaN(n)) return '0.00'
  return n.toFixed(2)
}

/** ROI 着色 */
const roiClass = (roi: any): string => {
  const r = parseFloat(roi) || 0
  if (r >= 30) return 'roi-high'
  if (r >= 15) return 'roi-mid'
  return 'roi-low'
}

/** 平台佣金（售价 × 佣金率） */
const commission = (record: any): number => {
  const price = parseFloat(record.price) || 0
  const pct = parseFloat(record.referral_fee_pct)
  return isNaN(pct) ? price * 0.15 : (price * pct) / 100
}

/** 头程估算（若 mock 未带 freight_cost，按重量粗估） */
const estFreight = (record: any): number => {
  const w = parseFloat(record.weight_lbs)
  if (isNaN(w)) return 1.5
  return Math.max(Math.round((w * 2.6 + 1.2) * 100) / 100, 1.2)
}

/** 净利估算：售价 - 采购 - 头程 - 佣金 - FBA */
const estNet = (record: any): number => {
  const price = parseFloat(record.price) || 0
  const cost = parseFloat(record.cost_price) || 0
  const fba = parseFloat(record.fba_fees) || 0
  const freight = parseFloat(record.freight_cost) || estFreight(record)
  return Math.round((price - cost - freight - commission(record) - fba) * 100) / 100
}

/** 亚马逊 Listing 跳转链接（默认 US 站，按 marketplace 拼站） */
function listingUrl(asin: string, marketplace?: string): string {
  const hostMap: Record<string, string> = {
    us: 'www.amazon.com',
    uk: 'www.amazon.co.uk',
    de: 'www.amazon.de',
    fr: 'www.amazon.fr',
    jp: 'www.amazon.co.jp',
    ca: 'www.amazon.ca',
    au: 'www.amazon.com.au',
  }
  const mk = (marketplace || 'us').toLowerCase()
  const host = hostMap[mk] || 'www.amazon.com'
  return `https://${host}/dp/${asin}`
}

/** 综合评分跳色：星级、蓝海分通用 */
function ratingClass(r: number): string {
  if (r >= 4.2) return 'good'
  if (r >= 3.8) return ''
  return 'warn'
}

/** 图片加载失败隐藏破图 */
const onImgError = (e: Event) => {
  ;(e.target as HTMLImageElement).style.display = 'none'
}

// ====== 派生合规标签 & AI 洞察（UI 层规则推导，非底层虚构数据） ======
/** 合规 / 风险标签：基于竞争结构、变体、评分推导的确定性标签 */
function complianceTags(record: any): Array<{ text: string; type: 'success' | 'warning' | 'danger' | 'default' | 'processing' }> {
  const tags: Array<{ text: string; type: any }> = []
  const score = record.blue_ocean_score || 0
  if (record.is_amazon_owned) tags.push({ text: '⚠️ 亚马逊自营占位', type: 'danger' })
  else if ((record.seller_count ?? 4) <= 2) tags.push({ text: '卖家少·真蓝海', type: 'success' })
  else if ((record.seller_count ?? 4) >= 6) tags.push({ text: '卖家多·竞争激烈', type: 'warning' })

  const variation = record.variation_count ?? 1
  if (variation <= 3) tags.push({ text: '少变体·开发省心', type: 'success' })
  else if (variation >= 7) tags.push({ text: '多变体·开发成本高', type: 'warning' })

  if ((record.rating ?? 0) < 3.8) tags.push({ text: '差评率高·谨慎', type: 'danger' })
  if (score >= 70) tags.push({ text: '高潜蓝海', type: 'success' })
  else if (score >= 40) tags.push({ text: '中等潜力', type: 'processing' })
  else tags.push({ text: '竞争红海', type: 'warning' })

  if (tags.length === 0) tags.push({ text: '常规候选', type: 'default' })
  return tags.slice(0, 5)
}

/** AI 洞察：综合各指标给出一段决策建议 */
function aiInsight(record: any): string {
  const score = record.blue_ocean_score || 0
  const roi = record.roi_estimated || 0
  const sales = record.estimated_monthly_sales || 0
  const rating = record.rating || 0
  const variation = record.variation_count ?? 1
  const sellers = record.seller_count ?? 4
  const price = parseFloat(record.price) || 0

  const parts: string[] = []

  if (score >= 70) {
    parts.push('综合属于**高潜蓝海**：销量可观且竞争结构健康，适合作为首推立项候选。')
  } else if (score >= 40) {
    parts.push('处于**中等潜力**区间：有一定需求，但竞争或利润未拉开明显差距，建议先小批量测款。')
  } else {
    parts.push('竞争已较**红海**或利润偏薄，优先级靠后，除非有强差异化切入点否则不建议投入。')
  }

  if (roi >= 30) parts.push(`预估 ROI 达 **${roi}%**，净利空间充足，广告预算容错度高。`)
  else if (roi >= 15) parts.push(`ROI 约 **${roi}%**，尚可覆盖广告成本，需控制 CPC。`)
  else parts.push(`ROI 仅 **${roi}%**，利润薄，广告稍高即亏损，需谨慎。`)

  if (rating >= 4.4) parts.push(`评分 **${rating}** 高，信任度基础好，新链接更容易起步。`)
  else if (rating < 4.0) parts.push(`评分 **${rating}** 偏低，切入时可在痛点（差评）上做针对性改进。`)

  if (variation <= 3) parts.push(`变体仅 ${variation} 个，开发与备货简单，可快速上线。`)
  if (sellers <= 2) parts.push(`在售卖家仅 ${sellers} 家，独占性强。`)
  if (price >= 25) parts.push(`定价 $${money(price)}，毛利空间与退货缓冲较充足。`)
  else parts.push(`客单价 $${money(price)} 偏低，需靠走量摊薄固定成本。`)

  if (sales >= 2000) parts.push(`月销约 ${Number(sales).toLocaleString()} 件，需求基数大，但也是多数卖家盯上的标的市场。`)
  else if (sales < 500) parts.push(`月销约 ${Number(sales).toLocaleString()} 件，盘子偏小，需评估是否支撑稳定盈利。`)

  return parts.join(' ')
}

/** 上架距今月数 / 新品判断文案 */
function listedAge(record: any): string {
  if (!record.listed_date) return '-'
  const t = new Date(record.listed_date + 'T00:00:00').getTime()
  if (isNaN(t)) return record.listed_date
  const months = Math.floor((Date.now() - t) / (30 * 24 * 3600 * 1000))
  if (months < 1) return '不足 1 个月'
  if (months < 12) return `${months} 个月（新品窗口期）`
  return `${Math.floor(months / 12)} 年 ${months % 12} 个月`
}
</script>
