<template>
  <div class="blue-ocean-result">
    <!-- 结果头部 -->
    <div class="result-header">
      <div class="header-left">
        <span class="result-icon">🌊</span>
        <span class="result-title">蓝海挖掘结果</span>
        <a-tag color="blue">{{ data.products?.length || 0 }} 个候选</a-tag>
      </div>
      <div class="header-right">
        <!-- 批量保存到选品库（始终可见，勾选数为 0 时降级为非主按钮 + 点击提示） -->
        <a-button
          :type="selectedRowKeys.length > 0 ? 'primary' : 'default'"
          size="small"
          @click="handleBatchSave"
        >
          <SaveOutlined /> 保存到选品库{{ selectedRowKeys.length > 0 ? ` (${selectedRowKeys.length})` : '' }}
        </a-button>
        <a-button type="text" size="small" @click="$emit('close')">
          <CloseOutlined />
        </a-button>
      </div>
    </div>

    <!-- 统计概览 -->
    <div class="stats-row">
      <div class="stat-card stat-excellent">
        <div class="stat-value">{{ data.summary?.high_potential || 0 }}</div>
        <div class="stat-label">优质蓝海</div>
      </div>
      <div class="stat-card stat-medium">
        <div class="stat-value">{{ data.summary?.medium_potential || 0 }}</div>
        <div class="stat-label">一般潜力</div>
      </div>
      <div class="stat-card stat-poor">
        <div class="stat-value">{{ data.summary?.high_competition || 0 }}</div>
        <div class="stat-label">高竞争</div>
      </div>
      <div class="stat-card stat-saved">
        <div class="stat-value">{{ savedCount }}</div>
        <div class="stat-label">已保存</div>
      </div>
    </div>

    <!-- 商品表格（首页精简视图：6 列 + 复选框，次要指标行 hover 悬浮查看） -->
    <div class="table-wrap">
      <a-table
        :dataSource="data.products"
        :columns="tableColumns"
        :pagination="{ pageSize: 8, size: 'small' }"
        size="small"
        :scroll="{ y: 280 }"
        rowKey="asin"
        :row-selection="rowSelection"
        :customRow="onRow"
      >
        <!-- 各列自定义渲染 -->
        <template #bodyCell="{ column, record }">
          <!-- 商品列：缩略图 + 短标题(🔗 新窗口) + ASIN(🔗) -->
          <template v-if="column.key === 'title'">
            <div class="title-cell">
              <img
                v-if="record.main_image || record.image"
                class="title-thumb"
                :src="record.main_image || record.image"
                alt=""
                loading="lazy"
                @error="onImgError"
              />
              <span class="title-thumb-ph" v-else>🖼️</span>
              <div class="title-main">
                <a-tooltip :title="record.title">
                  <a
                    class="title-link"
                    :href="listingUrl(record.asin, record.marketplace)"
                    target="_blank"
                    rel="noopener"
                    @click.stop
                  >{{ record.title.slice(0, 40) }}{{ record.title.length > 40 ? '…' : '' }}</a>
                </a-tooltip>
                <a
                  class="title-asin"
                  :href="listingUrl(record.asin, record.marketplace)"
                  target="_blank"
                  rel="noopener"
                  @click.stop
                >{{ record.asin }} ↗</a>
              </div>
            </div>
          </template>

          <!-- 售价 -->
          <template v-else-if="column.key === 'price'">
            <span class="mono">${{ money(record.price) }}</span>
          </template>

          <!-- 月销 -->
          <template v-else-if="column.key === 'estimated_monthly_sales'">
            <span class="mono">{{ record.estimated_monthly_sales ? Number(record.estimated_monthly_sales).toLocaleString() : '-' }}</span>
          </template>

          <!-- ROI 列：悬浮展示成本明细 -->
          <template v-else-if="column.key === 'roi_estimated'">
            <a-tooltip placement="topLeft">
              <template #title>
                <div class="roi-tip">
                  <div class="roi-tip-title">📊 成本 & ROI 明细</div>
                  <div class="roi-tip-row"><span>售价</span><b>${{ money(record.price) }}</b></div>
                  <div class="roi-tip-row"><span>采购成本</span><b>${{ money(record.cost_price) }}</b></div>
                  <div class="roi-tip-row"><span>头程物流</span><b>${{ money(record.freight_cost ?? estFreight(record)) }}</b></div>
                  <div class="roi-tip-row"><span>平台佣金</span><b>${{ money(commission(record)) }}</b></div>
                  <div class="roi-tip-row"><span>FBA 配送费</span><b>${{ money(record.fba_fees) }}</b></div>
                  <div class="roi-tip-divider"></div>
                  <div class="roi-tip-row net"><span>预估净利</span><b>${{ money(record.net_profit ?? estNet(record)) }}</b></div>
                  <div class="roi-tip-row total"><span>ROI</span><b :class="roiClass(record.roi_estimated)">{{ record.roi_estimated }}%</b></div>
                </div>
              </template>
              <span :class="['roi-val', roiClass(record.roi_estimated)]">{{ record.roi_estimated }}%</span>
            </a-tooltip>
          </template>

          <!-- 蓝海评分列 -->
          <template v-else-if="column.key === 'blue_ocean_score'">
            <div class="score-cell">
              <a-progress
                :percent="record.blue_ocean_score"
                :stroke-color="getScoreColor(record.blue_ocean_score)"
                :show-info="false"
                size="small"
              />
              <span class="score-value" :style="{ color: getScoreColor(record.blue_ocean_score) }">
                {{ record.blue_ocean_score }}
              </span>
            </div>
          </template>

          <!-- 操作列：详情（直达亚马逊/维护对标竞品集合入口已收敛到自有产品库详情页） -->
          <template v-else-if="column.key === 'action'">
            <div class="action-cell">
              <a-button type="link" size="small" class="detail-btn" @click.stop="openDetail(record)">
                详情
              </a-button>
            </div>
          </template>
        </template>
      </a-table>

      <!-- 行 hover 悬浮卡：展示次要指标（类目/星级/变体/BSR/评论），无需横向拖滚动条 -->
      <div
        v-if="hoverCard"
        class="row-hover-card"
        :style="{ left: hoverCard.x + 16 + 'px', top: hoverCard.y - 20 + 'px' }"
      >
        <div class="hover-card-title">
          <span class="hover-card-asin">{{ hoverCard.record.asin }}</span>
          <span class="hover-card-tag">{{ hoverCard.record.blue_ocean_score }} 分</span>
        </div>
        <div class="hover-card-grid">
          <div v-for="it in secondaryItems(hoverCard.record)" :key="it.label" class="hover-card-item">
            <span class="hc-label">{{ it.label }}</span>
            <span class="hc-value" :class="it.cls">{{ it.value }}</span>
          </div>
        </div>
        <div class="hover-card-foot" @mouseenter.stop @click.stop="openDetail(hoverCard.record)">
          🔍 查看完整数据 <b>›</b>
        </div>
      </div>
    </div>

    <!-- AI 分析报告摘要 -->
    <div v-if="data.report" class="report-summary">
      <div class="report-title">📊 AI 分析洞察</div>
      <div class="report-content" v-html="renderMarkdown(data.report)"></div>
    </div>

    <!-- 保存成功弹窗 -->
    <a-modal
      v-model:open="successModalVisible"
      title="📦 已加入选品库"
      :footer="null"
      :width="420"
      centered
    >
      <div class="success-modal-body">
        <a-result
          status="success"
          :title="`成功保存 ${lastSavedCount} 个候选到选品库`"
          sub-title="候选已以待评审状态存入选品库（草稿池），评审通过后将迁移到自有产品库"
        >
          <template #extra>
            <a-space>
              <a-button @click="successModalVisible = false">继续选品</a-button>
              <a-button type="primary" @click="goToProductLibrary">
                <ExportOutlined /> 去选品库评审
              </a-button>
            </a-space>
          </template>
        </a-result>

        <div v-if="lastSavedProducts.length > 0" class="saved-list">
          <div class="saved-list-title">本次保存的候选：</div>
          <div v-for="p in lastSavedProducts" :key="p.asin" class="saved-item">
            <a-tag color="blue">{{ p.asin }}</a-tag>
            <span class="saved-item-title">{{ p.title.slice(0, 40) }}...</span>
            <a-tag color="blue">待评审</a-tag>
          </div>
        </div>
      </div>
    </a-modal>

    <!-- 保存到选品库（选分组）弹窗 -->
    <a-modal
      v-model:open="poolModalVisible"
      title="📦 保存到选品库"
      :width="520"
      centered
    >
      <div class="pool-modal-body">
        <div class="pool-selected-tip">
          已勾选 <b>{{ selectedRowKeys.length }}</b> 个候选，将存入选品库（待评审状态），可选择加入的分组（可多选，一个候选可归入多个分组）：
        </div>

        <a-tabs v-model:activeKey="poolTab" size="small">
          <!-- 已有分组 -->
          <a-tab-pane key="existing" tab="已有分组">
            <div v-if="candidateStore.groups.length === 0" class="pool-empty">
              暂无分组，可到「新建分组」页签创建，或不选分组直接保存。
            </div>
            <div v-else class="pool-group-list">
              <div
                v-for="g in candidateStore.groups"
                :key="g.id"
                class="pool-group-item"
                :class="{ selected: selectedGroupIds.includes(g.id) }"
                @click="toggleGroupSelect(g.id)"
              >
                <span class="pool-color-dot" :style="{ background: g.color }"></span>
                <span class="pool-group-name">{{ g.name }}</span>
                <span class="pool-group-count">{{ candidateStore.groupProductCount[g.id] || 0 }} 个候选</span>
                <a-checkbox :checked="selectedGroupIds.includes(g.id)" @click.stop="toggleGroupSelect(g.id)" />
              </div>
            </div>
          </a-tab-pane>

          <!-- 新建分组 -->
          <a-tab-pane key="new" tab="新建分组">
            <div class="pool-new-form">
              <a-form layout="vertical">
                <a-form-item label="分组名称">
                  <a-input v-model:value="newGroupName" placeholder="如：高利润小家电、潜力赛道 Q4" @pressEnter="handleCreateGroup" />
                </a-form-item>
                <a-form-item label="标签颜色">
                  <div class="pool-color-picker">
                    <span
                      v-for="c in GROUP_COLORS"
                      :key="c"
                      class="pool-color-swatch"
                      :class="{ active: newGroupColor === c }"
                      :style="{ background: c }"
                      @click="newGroupColor = c"
                    ></span>
                  </div>
                </a-form-item>
              </a-form>
              <a-button block type="dashed" @click="handleCreateGroup">
                <PlusOutlined /> 新建并选中此分组
              </a-button>
            </div>
          </a-tab-pane>
        </a-tabs>
      </div>

      <template #footer>
        <a-button @click="poolModalVisible = false">取消</a-button>
        <a-button
          type="primary"
          :loading="poolSaving"
          @click="handleConfirmSaveWithGroups"
        >
          {{ selectedGroupIds.length > 0 ? `确认保存（加入 ${selectedGroupIds.length} 个分组）` : '直接保存（不分组）' }}
        </a-button>
      </template>
    </a-modal>
  </div>

  <!-- 单行详情抽屉：点击行尾「详情」右侧滑出完整数据 -->
  <a-drawer
    v-model:open="detailVisible"
    :width="460"
    placement="right"
    :closable="true"
    :title="detailRecord ? `${detailRecord.asin} 完整档案` : '商品档案'"
  >
    <template v-if="detailRecord">
      <!-- 头部：图 + 标题 + 直达 -->
      <div class="detail-hero">
        <img
          v-if="detailRecord.main_image || detailRecord.image"
          class="detail-hero-img"
          :src="detailRecord.main_image || detailRecord.image"
          alt=""
          loading="lazy"
          @error="onImgError"
        />
        <span v-else class="detail-hero-ph">🖼️</span>
        <div class="detail-hero-info">
          <div class="detail-hero-title">{{ detailRecord.title }}</div>
          <div class="detail-hero-sub">
            <span class="detail-brand">{{ detailRecord.brand || '-' }}</span>
            <a
              class="detail-link"
              :href="listingUrl(detailRecord.asin, detailRecord.marketplace)"
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
          <div class="dkpi-val" :style="{ color: getScoreColor(detailRecord.blue_ocean_score) }">{{ detailRecord.blue_ocean_score }}</div>
        </div>
        <div class="dkpi">
          <div class="dkpi-label">售价</div>
          <div class="dkpi-val mono">${{ money(detailRecord.price) }}</div>
        </div>
        <div class="dkpi">
          <div class="dkpi-label">月销</div>
          <div class="dkpi-val mono">{{ detailRecord.estimated_monthly_sales ? Number(detailRecord.estimated_monthly_sales).toLocaleString() : '-' }}</div>
        </div>
        <div class="dkpi">
          <div class="dkpi-label">ROI</div>
          <div class="dkpi-val" :class="roiClass(detailRecord.roi_estimated)">{{ detailRecord.roi_estimated }}%</div>
        </div>
      </div>

      <!-- 合规 / 风险标签 -->
      <div class="detail-section">
        <div class="detail-section-title">🏷️ 判定标签</div>
        <div class="detail-tags">
          <a-tag v-for="(t, i) in complianceTags(detailRecord)" :key="i" :color="t.type">{{ t.text }}</a-tag>
        </div>
      </div>

      <!-- AI 洞察 -->
      <div class="detail-section">
        <div class="detail-section-title">🤖 AI 洞察</div>
        <div class="detail-insight">{{ aiInsight(detailRecord) }}</div>
      </div>

      <!-- 基本信息 -->
      <div class="detail-section">
        <div class="detail-section-title">📋 基本信息</div>
        <div class="detail-rows">
          <div class="drow"><span>站点</span><b>{{ detailRecord.marketplace || 'Amazon US' }}</b></div>
          <div class="drow"><span>完整类目</span><b>{{ (detailRecord.category_path || []).join(' › ') || detailRecord.category_l2 || '-' }}</b></div>
          <div class="drow"><span>上架时间</span><b>{{ detailRecord.listed_date || '-' }}</b></div>
          <div class="drow"><span>上架时长</span><b>{{ listedAge(detailRecord) }}</b></div>
          <div class="drow"><span>重量 / 尺寸</span><b>{{ detailRecord.weight_lbs ? detailRecord.weight_lbs + ' lb' : '-' }} / {{ detailRecord.dimensions || '-' }} in</b></div>
          <div class="drow"><span>卖家数</span><b>{{ detailRecord.seller_count ?? '-' }}</b></div>
        </div>
      </div>

      <!-- 市场指标 -->
      <div class="detail-section">
        <div class="detail-section-title">📈 市场指标</div>
        <div class="detail-rows">
          <div class="drow"><span>BSR 排名</span><b>#{{ detailRecord.bsr_rank ? Number(detailRecord.bsr_rank).toLocaleString() : '-' }} <span class="muted">{{ detailRecord.bsr_category || '' }}</span></b></div>
          <div class="drow"><span>商品星级</span><b :class="ratingClass(detailRecord.rating)">★ {{ detailRecord.rating ? Number(detailRecord.rating).toFixed(1) : '-' }}</b></div>
          <div class="drow"><span>评论数</span><b>{{ detailRecord.review_count ? Number(detailRecord.review_count).toLocaleString() : '-' }}</b></div>
          <div class="drow"><span>变体数量</span><b>{{ detailRecord.variation_count ?? 1 }}</b></div>
          <div class="drow"><span>30天价格波动</span><b :class="(detailRecord.price_trend_30d ?? 0) >= 0 ? 'trend-up' : 'trend-down'">{{ detailRecord.price_trend_30d ?? 0 }}%</b></div>
          <div class="drow"><span>30天销量波动</span><b :class="(detailRecord.sales_trend_30d ?? 0) >= 0 ? 'trend-up' : 'trend-down'">{{ detailRecord.sales_trend_30d ?? 0 }}%</b></div>
        </div>
      </div>

      <!-- 成本拆解 -->
      <div class="detail-section">
        <div class="detail-section-title">💰 成本拆解（单件）</div>
        <div class="cost-box">
          <div class="cost-row"><span>售价</span><b>${{ money(detailRecord.price) }}</b></div>
          <div class="cost-row"><span>采购成本</span><b>${{ money(detailRecord.cost_price) }}</b></div>
          <div class="cost-row"><span>头程物流</span><b>${{ money(detailRecord.freight_cost ?? estFreight(detailRecord)) }}</b></div>
          <div class="cost-row"><span>平台佣金</span><b>${{ money(commission(detailRecord)) }}</b></div>
          <div class="cost-row"><span>FBA 配送费</span><b>${{ money(detailRecord.fba_fees) }}</b></div>
          <div class="cost-divider"></div>
          <div class="cost-row net"><span>预估净利</span><b>${{ money(detailRecord.net_profit ?? estNet(detailRecord)) }}</b></div>
          <div class="cost-row total"><span>ROI</span><b :class="roiClass(detailRecord.roi_estimated)">{{ detailRecord.roi_estimated }}%</b></div>
        </div>
      </div>

      <!-- Listing 卖点 -->
      <div v-if="detailRecord.selling_points?.length" class="detail-section">
        <div class="detail-section-title">💡 核心卖点</div>
        <ul class="detail-points">
          <li v-for="(sp, i) in detailRecord.selling_points" :key="i">{{ sp }}</li>
        </ul>
      </div>

      <!-- Listing 质量评分 -->
      <div class="detail-section">
        <div class="detail-section-title">📊 Listing 质量</div>
        <div class="lq-rows">
          <div class="lq-row">
            <span>标题</span>
            <a-progress :percent="detailRecord.title_score" :stroke-color="getScoreColor(detailRecord.title_score)" size="small" />
          </div>
          <div class="lq-row">
            <span>五点</span>
            <a-progress :percent="detailRecord.bullet_score" :stroke-color="getScoreColor(detailRecord.bullet_score)" size="small" />
          </div>
          <div class="lq-row">
            <span>图片</span>
            <a-progress :percent="detailRecord.image_score" :stroke-color="getScoreColor(detailRecord.image_score)" size="small" />
          </div>
          <div class="lq-row">
            <span>综合</span>
            <a-progress :percent="detailRecord.overall_listing_score" :stroke-color="getScoreColor(detailRecord.overall_listing_score)" size="small" />
          </div>
        </div>
      </div>

      <!-- 底部操作 -->
      <div class="detail-actions">
        <a-button
          type="primary"
          block
          :disabled="savedAsins.has(detailRecord.asin)"
          @click="saveOne(detailRecord)"
        >
          {{ savedAsins.has(detailRecord.asin) ? '✓ 已加入选品库' : '➕ 保存到选品库' }}
        </a-button>
        <!-- 游离监控：蓝海随手盯，不归属任何项目，仅入统一监控池独立跟踪 -->
        <a-button
          block
          class="mon-btn"
          :type="isDetailMonitored ? 'default' : 'dashed'"
          @click="toggleFreeMonitor(detailRecord)"
        >
          <template v-if="isDetailMonitored">
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
import { ref, computed } from 'vue'
import { CloseOutlined, SaveOutlined, ExportOutlined, PlusOutlined, FundOutlined } from '@ant-design/icons-vue'
import { message } from 'ant-design-vue'
import MarkdownIt from 'markdown-it'
import { useCandidateLibraryStore, type CandidateItem } from '@/stores/candidateLibrary'
import { GROUP_COLORS } from '@/stores/productLibrary'
import { useMonitorPoolStore } from '@/stores/monitorPool'

const props = defineProps<{
  data: any
}>()

const emit = defineEmits<{
  (e: 'close'): void
  (e: 'navigateTo', view: string): void
}>()

const md = new MarkdownIt()
const candidateStore = useCandidateLibraryStore()
const monitorStore = useMonitorPoolStore()

// ====== 选择状态 ======
const selectedRowKeys = ref<string[]>([])
const onSelectChange = (keys: string[]) => {
  selectedRowKeys.value = keys
}
const rowSelection = computed(() => ({
  selectedRowKeys: selectedRowKeys.value,
  onChange: onSelectChange,
}))
/** 绑定行 hover 事件（不绑定点击，整行点击不跳转，保留复选框流畅勾选） */
const onRow = (record: any) => ({
  onMouseenter: (e: MouseEvent) => onRowMouseEnter(record, e),
  onMousemove: (e: MouseEvent) => onRowMouseMove(e),
  onMouseleave: () => onRowMouseLeave(),
})

// ====== 保存状态 ======
const savedAsins = ref<Set<string>>(new Set())
const successModalVisible = ref(false)
const lastSavedCount = ref(0)
const lastSavedProducts = ref<CandidateItem[]>([])

// 已保存计数
const savedCount = computed(() => savedAsins.value.size)

// ====== 表格列定义 ======
/**
 * 首页精简视图：只保留「复选框 + 6 决策优先级最高列」，一屏放下无需横向滑动。
 * 商品列（含 🔗 ASIN/标题链接）+ 售价 + 月销 + ROI + 蓝海评分 + 操作（直达/详情）
 * 次要指标（星级/变体/BSR/完整类目）→ 行 hover 悬浮卡 + 单行详情抽屉。
 */
const tableColumns = [
  { title: '商品', dataIndex: 'title', key: 'title', width: 230 },
  { title: '售价', dataIndex: 'price', key: 'price', width: 76, align: 'right' },
  { title: '月销', dataIndex: 'estimated_monthly_sales', key: 'estimated_monthly_sales', width: 86, align: 'right' },
  { title: 'ROI', dataIndex: 'roi_estimated', key: 'roi_estimated', width: 84, align: 'right' },
  { title: '蓝海评分', dataIndex: 'blue_ocean_score', key: 'blue_ocean_score', width: 116 },
  { title: '操作', key: 'action', width: 80, align: 'center' },
]

// ====== 行 hover 悬浮次要指标卡 ======
const hoverCard = ref<{ record: any; x: number; y: number } | null>(null)
function onRowMouseEnter(record: any, e: MouseEvent) {
  hoverCard.value = { record, x: e.clientX, y: e.clientY }
}
function onRowMouseMove(e: MouseEvent) {
  if (hoverCard.value) {
    hoverCard.value.x = e.clientX
    hoverCard.value.y = e.clientY
  }
}
function onRowMouseLeave() {
  hoverCard.value = null
}

// ====== 单行详情抽屉 ======
const detailVisible = ref(false)
const detailRecord = ref<any>(null)
function openDetail(record: any) {
  detailRecord.value = record
  detailVisible.value = true
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

// ====== 核心逻辑：蓝海结果 → 选品库候选（草稿池） ======

/**
 * 将蓝海挖掘的商品数据转换为候选选品库格式（轻量字段 + 评审状态）
 */
function mapToCandidate(record: any, groupIds: string[] = []): Omit<CandidateItem, 'id' | 'created_at' | 'updated_at'> {
  const roi = record.roi_estimated || 20
  const price = parseFloat(record.price) || 0

  return {
    asin: record.asin || '',
    sku: `SKU-CAND-${record.asin?.replace('B0', '') || Date.now()}`,
    title: record.title || '未命名候选',
    brand: extractBrand(record.title) || '',
    category: guessCategory(record.title),
    sub_category: record.bsr_category || record.category_path?.[2] || '',
    price,
    currency: 'USD',
    site: record.marketplace || 'Amazon US',

    // 市场数据
    estimated_monthly_sales: parseInt(record.estimated_monthly_sales) || 0,
    review_count: parseInt(record.review_count) || 0,
    rating: parseFloat(record.rating) || 0,
    bsr: record.bsr_rank || null,
    bsr_category: record.bsr_category || '',
    listed_date: record.listed_date || '',

    // 蓝海评分核心
    roi_estimated: roi,
    margin: roi > 0 ? Math.round((price - price / (1 + roi / 100)) / price * 100) : 0,
    blue_ocean_score: record.blue_ocean_score || 0,
    overall_listing_score: record.overall_listing_score
      ?? Math.round(((record.title_score || 0) + (record.bullet_score || 0) + (record.image_score || 0)) / 3),

    // 关键词 / 竞品 / 卖点
    keywords: record.keywords || [],
    competitor_asins: record.competitor_asins || [],
    selling_points: record.selling_points?.join(' | ') || '',

    // 图片
    main_image: record.main_image || record.image || '',
    images: record.images || [],

    // 来源 + 评审状态（初始待评审）
    source: 'blue_ocean',
    review_status: 'pending',
    review_notes: '',
    reviewed_at: null,
    reviewed_by: null,
    monitor_data: null,
    last_monitored_at: null,

    // 元数据
    shop_id: '',
    tags: ['蓝海挖掘', `评分:${record.blue_ocean_score}`, `ROI:${roi}%`],
    notes: `来源：蓝海挖掘 | 评分：${record.blue_ocean_score} | 预估月销：${record.estimated_monthly_sales} | ROI：${roi}% | 上市：${record.listed_date}`,
    groups: groupIds,
  }
}

/** 从标题提取品牌名（简单启发式） */
function extractBrand(title: string): string {
  const words = title.split(/\s+/)
  if (words.length >= 2) return words[0]
  return ''
}

/** 根据标题猜测分类 */
function guessCategory(title: string): string {
  const t = title.toLowerCase()
  if (/耳机|音响|蓝牙|充电|线缆|键盘|鼠标|显示器|摄像头/i.test(t)) return 'electronics'
  if (/保温|厨|锅|杯|收纳|家居|灯|窗帘|地毯/i.test(t)) return 'home'
  if (/护肤|化妆|面膜|唇|防晒|洁面|护发/i.test(t)) return 'beauty'
  if (/瑜伽|健身|跑|球|泳|户外|露营|登山/i.test(t)) return 'sports'
  if (/恤|裤|裙|鞋|帽|袜|衣|外套|内衣/i.test(t)) return 'clothing'
  if (/玩具|婴儿|儿童|积木|拼图/i.test(t)) return 'toys'
  if (/车|车载|轮胎|机油|导航/i.test(t)) return 'automotive'
  return 'other'
}

// ====== 保存到选品库（支持选分组） ======
const poolModalVisible = ref(false)
const poolTab = ref('existing')
const poolSaving = ref(false)
const selectedGroupIds = ref<string[]>([])
const newGroupName = ref('')
const newGroupColor = ref(GROUP_COLORS[0])

/** 打开分组选择弹窗（批量） */
function handleBatchSave() {
  if (selectedRowKeys.value.length === 0) {
    message.warning('请先勾选要保存的商品')
    return
  }
  openPoolModal()
}

/** 打开分组弹窗 */
function openPoolModal() {
  selectedGroupIds.value = []
  newGroupName.value = ''
  poolTab.value = 'existing'
  poolModalVisible.value = true
}

/** 切换分组选中（多选） */
function toggleGroupSelect(groupId: string) {
  const idx = selectedGroupIds.value.indexOf(groupId)
  if (idx >= 0) {
    selectedGroupIds.value.splice(idx, 1)
  } else {
    selectedGroupIds.value.push(groupId)
  }
}

/** 新建分组并选中 */
async function handleCreateGroup() {
  const name = newGroupName.value.trim()
  if (!name) {
    message.warning('请输入分组名称')
    return
  }
  const group = await candidateStore.createGroup({ name, color: newGroupColor.value })
  if (!selectedGroupIds.value.includes(group.id)) {
    selectedGroupIds.value.push(group.id)
  }
  message.success(`分组「${group.name}」已创建并选中`)
  newGroupName.value = ''
  poolTab.value = 'existing'
}

/** 确认保存（带分组） */
async function handleConfirmSaveWithGroups() {
  poolSaving.value = true
  const groupIds = [...selectedGroupIds.value]
  try {
    await doSaveBatch(groupIds)
    poolModalVisible.value = false
  } catch (e) {
    message.error('保存失败，请重试')
  } finally {
    poolSaving.value = false
  }
}

/** 执行批量保存到选品库 */
async function doSaveBatch(groupIds: string[]) {
  const savedProducts: CandidateItem[] = []
  let successCount = 0

  for (const asin of selectedRowKeys.value) {
    const record = props.data.products?.find((p: any) => p.asin === asin)
    if (record && !savedAsins.value.has(asin)) {
      const candidateData = mapToCandidate(record, groupIds)
      const saved = await candidateStore.addItem(candidateData)
      savedProducts.push(saved)
      savedAsins.value = new Set([...savedAsins.value, asin])
      successCount++
    }
  }

  lastSavedCount.value = successCount
  lastSavedProducts.value = savedProducts
  successModalVisible.value = true
  selectedRowKeys.value = []
}

/** 从详情抽屉保存单个候选到选品库（直接加入，不带分组） */
async function saveOne(record: any) {
  if (savedAsins.value.has(record.asin)) return
  try {
    const candidateData = mapToCandidate(record, [])
    await candidateStore.addItem(candidateData)
    savedAsins.value = new Set([...savedAsins.value, record.asin])
    message.success('已加入选品库（待评审）')
  } catch (e) {
    message.error('保存失败，请重试')
  }
}

// ====== 游离监控（蓝海随手盯，不归属任何项目） ======

/** 当前详情 ASIN 是否已在统一监控池 */
const isDetailMonitored = computed(() =>
  detailRecord.value ? monitorStore.isAsinInPool(detailRecord.value.asin) : false
)

/** 切换游离监控：已入池则跳转竞品监控页定位；未入池则加入（无归属） */
function toggleFreeMonitor(record: any) {
  if (!record?.asin) return
  if (isDetailMonitored.value) {
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

// ====== 跳转选品库 ======
function goToProductLibrary() {
  successModalVisible.value = false
  emit('navigateTo', 'candidates')
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

/** 是否新品（上架距今 < 12 个月） */
const isNewListing = (date: string): boolean => {
  if (!date) return false
  const t = new Date(date + 'T00:00:00').getTime()
  if (isNaN(t)) return false
  return Date.now() - t < 365 * 24 * 3600 * 1000
}

/** 图片加载失败隐藏破图 */
const onImgError = (e: Event) => {
  ;(e.target as HTMLImageElement).style.display = 'none'
}

const renderMarkdown = (content: string) => md.render(content)

// ====== 详情抽屉：派生合规标签 & AI 洞察（UI 层规则推导，非底层虚构数据） ======
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

  // 需求与竞争判断
  if (score >= 70) {
    parts.push('综合属于**高潜蓝海**：销量可观且竞争结构健康，适合作为首推立项候选。')
  } else if (score >= 40) {
    parts.push('处于**中等潜力**区间：有一定需求，但竞争或利润未拉开明显差距，建议先小批量测款。')
  } else {
    parts.push('竞争已较**红海**或利润偏薄，优先级靠后，除非有强差异化切入点否则不建议投入。')
  }

  // 利润判断
  if (roi >= 30) parts.push(`预估 ROI 达 **${roi}%**，净利空间充足，广告预算容错度高。`)
  else if (roi >= 15) parts.push(`ROI 约 **${roi}%**，尚可覆盖广告成本，需控制 CPC。`)
  else parts.push(`ROI 仅 **${roi}%**，利润薄，广告稍高即亏损，需谨慎。`)

  // 评论/评分
  if (rating >= 4.4) parts.push(`评分 **${rating}** 高，信任度基础好，新链接更容易起步。`)
  else if (rating < 4.0) parts.push(`评分 **${rating}** 偏低，切入时可在痛点（差评）上做针对性改进。`)

  // 结构/竞争
  if (variation <= 3) parts.push(`变体仅 ${variation} 个，开发与备货简单，可快速上线。`)
  if (sellers <= 2) parts.push(`在售卖家仅 ${sellers} 家，独占性强。`)
  if (price >= 25) parts.push(`定价 $${money(price)}，毛利空间与退货缓冲较充足。`)
  else parts.push(`客单价 $${money(price)} 偏低，需靠走量摊薄固定成本。`)

  // 销量基数
  if (sales >= 2000) parts.push(`月销约 ${Number(sales).toLocaleString()} 件，需求基数大，但也是多数卖家盯上的标的市场。`)
  else if (sales < 500) parts.push(`月销约 ${Number(sales).toLocaleString()} 件，盘子偏小，需评估是否支撑稳定盈利。`)

  return parts.join(' ')
}

// ====== 悬浮次要指标卡 ======
function secondaryItems(record: any): Array<{ label: string; value: string; cls?: string }> {
  const path = record.category_path || []
  const l1 = record.category_l1 || path[0] || record.category || '-'
  const l2 = record.category_l2 || path[1] || ''
  const items: Array<{ label: string; value: string; cls?: string }> = [
    { label: '类目', value: l2 ? `${l1} › ${l2}` : l1 },
  ]
  const rating = record.rating ? Number(record.rating).toFixed(1) : '-'
  items.push({
    label: '星级',
    value: `★ ${rating}`,
    cls: ratingClass(record.rating || 0),
  })
  const variation = record.variation_count ?? 1
  items.push({
    label: '变体',
    value: `${variation} 个`,
    cls: variation <= 3 ? 'variation-few' : 'variation-many',
  })
  const bsr = record.bsr_rank ? Number(record.bsr_rank).toLocaleString() : '-'
  const review = record.review_count ? Number(record.review_count).toLocaleString() : '-'
  items.push({ label: 'BSR', value: `#${bsr}` })
  items.push({ label: '评论', value: review })
  return items
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

<style scoped>
.blue-ocean-result {
  background: var(--bg-elevated);
  border-radius: 8px;
  border: 1px solid #e8e8e8;
  margin: 12px 16px;
  overflow: hidden;
}

.result-header {
  display: flex;
  align-items: center;
  justify-content: space-between;
  padding: 12px 16px;
  background: var(--bo-header-bg, linear-gradient(135deg, #667eea 0%, #764ba2 100%));
  color: #fff;
}

.header-left {
  display: flex;
  align-items: center;
  gap: 8px;
}

.header-right {
  display: flex;
  align-items: center;
  gap: 8px;
}

.result-icon {
  font-size: 18px;
}

.result-title {
  font-size: 14px;
  font-weight: 600;
}

.stats-row {
  display: flex;
  gap: 12px;
  padding: 12px 16px;
  background: var(--bg-base);
  border-bottom: 1px solid var(--border-light, #f0f0f0);
}

.stat-card {
  flex: 1;
  text-align: center;
  padding: 8px;
  border-radius: 6px;
}

.stat-value {
  font-size: 20px;
  font-weight: 700;
}

.stat-label {
  font-size: 11px;
  color: #8c8c8c;
  margin-top: 2px;
}

.stat-excellent { background: rgba(82, 196, 26, 0.1); }
.stat-excellent .stat-value { color: #52c41a; }

.stat-medium { background: rgba(250, 173, 20, 0.12); }
.stat-medium .stat-value { color: #faad14; }

.stat-poor { background: rgba(255, 77, 79, 0.08); }
.stat-poor .stat-value { color: #ff4d4f; }

.stat-saved { background: rgba(24, 144, 255, 0.1); }
.stat-saved .stat-value { color: #1890ff; }

.score-cell {
  display: flex;
  align-items: center;
  gap: 8px;
}

.score-cell .ant-progress {
  flex: 1;
  max-width: 60px;
}

.score-value {
  font-weight: 600;
  min-width: 24px;
  text-align: right;
}

.roi-high {
  color: #52c41a;
  font-weight: 600;
}
.roi-mid {
  color: #d48806;
  font-weight: 600;
}
.roi-low {
  color: #cf1322;
  font-weight: 600;
}
.roi-val {
  cursor: default;
  font-weight: 600;
}

.title-text {
  cursor: default;
  display: block;
  line-height: 1.3;
  word-break: break-all;
}

/* 标题 / ASIN 超链接 */
.title-link {
  color: #1677ff;
  text-decoration: none;
  cursor: pointer;
  line-height: 1.3;
  display: block;
  word-break: break-all;
}
.title-link:hover {
  color: #0958d9;
  text-decoration: underline;
}
.title-asin {
  color: #1677ff !important;
  text-decoration: none;
  cursor: pointer;
  display: block;
  font-size: 11px;
  font-family: monospace;
  margin-top: 2px;
}
.title-asin:hover {
  color: #0958d9;
  text-decoration: underline;
}

.title-cell {
  display: flex;
  align-items: center;
  gap: 8px;
}
.title-main {
  min-width: 0;
}

.title-thumb {
  width: 40px;
  height: 40px;
  object-fit: cover;
  border-radius: 4px;
  border: 1px solid #f0f0f0;
  flex-shrink: 0;
  background: var(--bg-base);
}

.title-thumb-ph {
  width: 40px;
  height: 40px;
  flex-shrink: 0;
  display: flex;
  align-items: center;
  justify-content: center;
  font-size: 18px;
  border-radius: 4px;
  background: var(--bg-base);
  border: 1px solid #f0f0f0;
}

/* 类目（一级 / 二级） */
.cat-cell {
  display: flex;
  flex-direction: column;
  line-height: 1.3;
}
.cat-l1 {
  font-size: 12px;
  color: #262626;
}
.cat-l2 {
  font-size: 11px;
  color: #8c8c8c;
}

/* 星级 */
.rating-star {
  font-size: 13px;
}
.rating-star.good {
  color: #389e0d;
}
.rating-star.warn {
  color: #fa541c;
}

/* 变体数 */
.variation-cell {
  display: inline-block;
  min-width: 24px;
  padding: 1px 6px;
  border-radius: 10px;
  font-size: 12px;
  font-weight: 600;
  text-align: center;
}
.variation-cell.few {
  color: #389e0d;
  background: rgba(82, 196, 26, 0.1);
  border: 1px solid #b7eb8f;
}
.variation-cell.many {
  color: #d46b08;
  background: rgba(250, 140, 22, 0.1);
  border: 1px solid #ffd591;
}

/* BSR */
.bsr-cell {
  font-size: 12px;
  font-variant-numeric: tabular-nums;
}

/* 上架时间 */
.listed-cell {
  display: flex;
  align-items: center;
  justify-content: center;
  gap: 4px;
}
.listed-date {
  font-size: 12px;
  color: #595959;
}
.listed-date.new {
  color: #0958d9;
  font-weight: 600;
}
.listed-badge {
  font-size: 10px;
  color: #0958d9;
  background: rgba(24, 144, 255, 0.1);
  border: 1px solid #91caff;
  padding: 0 4px;
  border-radius: 3px;
}
.muted {
  color: #bfbfbf;
}

.report-summary {
  padding: 12px 16px;
  background: var(--bg-base);
  border-top: 1px solid #f0f0f0;
}

.report-title {
  font-size: 13px;
  font-weight: 600;
  margin-bottom: 8px;
  color: #262626;
}

.report-content {
  font-size: 12px;
  line-height: 1.6;
  color: #595959;
}

.report-content :deep(h2),
.report-content :deep(h3) {
  margin: 8px 0 4px;
  font-size: 13px;
}

.report-content :deep(ul) {
  padding-left: 16px;
  margin: 4px 0;
}

/* 成功弹窗 */
.success-modal-body {
  padding: 0 8px;
}

.saved-list {
  margin-top: 16px;
  padding-top: 16px;
  border-top: 1px solid #f0f0f0;
}

.saved-list-title {
  font-size: 12px;
  color: #8c8c8c;
  margin-bottom: 8px;
}

.saved-item {
  display: flex;
  align-items: center;
  gap: 8px;
  padding: 4px 0;
  font-size: 13px;
}

.saved-item-title {
  flex: 1;
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
  max-width: 260px;
}

/* ===== 商品观察池弹窗 ===== */
.pool-modal-body {
  padding: 4px 0;
}

.pool-selected-tip {
  font-size: 13px;
  color: #595959;
  margin-bottom: 12px;
  line-height: 1.6;
}

.pool-selected-tip b {
  color: #722ed1;
}

.pool-empty {
  text-align: center;
  color: #bfbfbf;
  padding: 24px 0;
  font-size: 13px;
}

.pool-group-list {
  max-height: 240px;
  overflow-y: auto;
}

.pool-group-item {
  display: flex;
  align-items: center;
  gap: 10px;
  padding: 10px 12px;
  border: 1px solid #f0f0f0;
  border-radius: 6px;
  margin-bottom: 8px;
  cursor: pointer;
  transition: all 0.2s;
}

.pool-group-item:hover {
  border-color: #722ed1;
  background: rgba(114, 46, 209, 0.08);
}

.pool-group-item.selected {
  border-color: #722ed1;
  background: rgba(114, 46, 209, 0.08);
}

.pool-color-dot {
  width: 12px;
  height: 12px;
  border-radius: 50%;
  flex-shrink: 0;
}

.pool-group-name {
  flex: 1;
  font-size: 13px;
  font-weight: 500;
  color: #262626;
}

.pool-group-count {
  font-size: 12px;
  color: #8c8c8c;
}

.pool-new-form {
  padding: 8px 0;
}

.pool-color-picker {
  display: flex;
  gap: 8px;
  flex-wrap: wrap;
}

.pool-color-swatch {
  width: 24px;
  height: 24px;
  border-radius: 50%;
  cursor: pointer;
  border: 2px solid transparent;
  transition: all 0.2s;
}

.pool-color-swatch.active {
  border-color: #262626;
  transform: scale(1.15);
}

/* ===== 精简表格 & 行操作 ===== */
.table-wrap {
  position: relative;
}
.mono {
  font-variant-numeric: tabular-nums;
  font-family: -apple-system, 'Segoe UI', Roboto, 'Helvetica Neue', Arial, monospace;
  font-weight: 500;
}
.action-cell {
  display: flex;
  align-items: center;
  justify-content: center;
  gap: 2px;
}
.link-icon-btn {
  font-size: 15px;
  line-height: 1;
  padding: 0 6px;
  color: #1677ff;
}
.link-icon-btn:hover {
  color: #0958d9;
}
.detail-btn {
  padding: 0 6px;
}

/* ===== 行 hover 悬浮次要指标卡 ===== */
.row-hover-card {
  position: fixed;
  z-index: 1080;
  min-width: 240px;
  max-width: 300px;
  background: var(--bg-elevated);
  border: 1px solid #e5e5e5;
  border-radius: 8px;
  box-shadow: 0 4px 16px rgba(0, 0, 0, 0.12);
  padding: 10px 12px;
  pointer-events: auto;
}
.hover-card-title {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 8px;
  padding-bottom: 6px;
  border-bottom: 1px dashed #f0f0f0;
  margin-bottom: 6px;
}
.hover-card-asin {
  font-family: monospace;
  font-size: 12px;
  font-weight: 600;
  color: #262626;
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}
.hover-card-tag {
  font-size: 11px;
  font-weight: 600;
  color: #722ed1;
  background: rgba(114, 46, 209, 0.08);
  border: 1px solid #d3adf7;
  border-radius: 10px;
  padding: 0 7px;
  flex-shrink: 0;
}
.hover-card-grid {
  display: grid;
  grid-template-columns: repeat(2, 1fr);
  gap: 4px 12px;
}
.hover-card-item {
  display: flex;
  justify-content: space-between;
  align-items: center;
  line-height: 1.9;
}
.hc-label {
  font-size: 11px;
  color: #8c8c8c;
}
.hc-value {
  font-size: 12px;
  font-weight: 600;
  color: #262626;
}
.hc-value.good { color: #389e0d; }
.hc-value.warn { color: #fa541c; }
.hc-value.variation-few { color: #389e0d; }
.hc-value.variation-many { color: #d46b08; }
.hover-card-foot {
  margin-top: 6px;
  padding-top: 6px;
  border-top: 1px dashed #f0f0f0;
  text-align: center;
  font-size: 12px;
  color: #722ed1;
  cursor: pointer;
  font-weight: 500;
}
.hover-card-foot:hover {
  color: #531dab;
}
.hover-card-foot b {
  color: #722ed1;
}

</style>
