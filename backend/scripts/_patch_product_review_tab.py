# -*- coding: utf-8 -*-
"""一次性补丁（第 289 轮）：① api/trade 加两个 evaluates ② 产品详情抽屉加「差评」tab。

★ 走脚本而不是多个 Edit：同一条消息里多个 Edit 并发读同一份 src，
  后写覆盖先写（本仓判据）。
"""
from __future__ import annotations

from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
FRONTEND = ROOT / "frontend"
API = FRONTEND / "src" / "api" / "trade.ts"
VIEW = FRONTEND / "src" / "components" / "KnowledgeBase" / "ProductLibrary.vue"


def _read(p: Path) -> str:
    return p.read_bytes().decode("utf-8").replace("\r\n", "\n")


def _write(p: Path, s: str) -> None:
    p.write_bytes(s.encode("utf-8"))


def sub(src: str, old: str, new: str, label: str) -> str:
    n = src.count(old)
    assert n == 1, f"锚点命中 {n} 次（须为 1）：{label}"
    return src.replace(old, new, 1)


# ============================================================ api/trade.ts

api = _read(API)

api = sub(
    api,
    "/** 发放（人）—— 不可逆，只有这一步生成券码 */",
    '''// ==================================================================
// 产品 ↔ 差评 软关联（第 289 轮）
//
// ★ 为什么这套 API 要单独放着讲：差评的 `asin` / `sku` **没有外键**指向
//   产品库（平台侧标识符，不能因为本地少一行就让差评插不进来）。没有外键兜
//   ⇒ join 可能一行都匹配不上，而「匹配不上」有两种完全不同的语义：
//      · 这个产品确实没有差评       —— 正常结论
//      · 差评和产品**没能对上**     —— 数据缺口
//   所以 `empty_state` 必须由界面分别播报，不能统一显示成「暂无差评」
//   —— 那等于把缺口伪装成「产品没问题」。
// ==================================================================

/** 产品的关联差评（后端 `_review_to_dict` + 关联元数据） */
export interface ProductReview {
  id: string
  sku: string
  asin: string
  product_title: string
  rating: number
  title: string
  body: string
  review_at: string
  buyer_name: string
  status: string
  source: string
  /** 这条差评是靠什么对上产品的 —— 界面要显示「命中 ASIN / SKU 码」 */
  match_kind: 'asin' | 'sku_code' | 'unknown' | null
  matched_sku_id: string | null
}

/**
 * 空态种类 —— **界面必须逐种给不同文案**
 * - `no_reviews`：关联得上，确实没有符合条件的评价（正常结论，绿色）
 * - `no_sku` / `no_asin_binding`：**数据缺口**（SKU 没登记 ASIN ⇒ 差评再存在也对不上来）
 * - `not_found`：SPU 不存在 / 不属于本店
 */
export type ProductReviewsEmptyState =
  | 'not_found' | 'no_sku' | 'no_asin_binding' | 'no_reviews' | null

export interface ProductReviewsResult {
  found: boolean
  spu_id: string
  spu_title?: string
  reviews: ProductReview[]
  /** 真实条数（不受 limit 截断） */
  total: number
  asin_count: number
  sku_count: number
  empty_state: ProductReviewsEmptyState
}

export interface OrphanReviewsResult {
  items: ProductReview[]
  total: number
  empty_state: 'no_orphans' | null
}

/**
 * 某个 SPU 名下的差评 —— 产品详情「差评 tab」的数据源。
 *
 * ★ SPU 只是**聚合壳**：SPU 无 ASIN、不可售，真正的键在它名下 SKU 的
 *   ASIN 上（`spus.id → skus.spu_id → skus.asin`），且在 ASIN 缺失时退回 SKU 码。
 * ★ 同一个 ASIN 可能挂在多个 SKU 上 ⇒ 结果**已去重**，不会重复计数。
 */
export async function listReviewsBySpu(
  spuId: string,
  params?: { max_rating?: number; limit?: number; offset?: number },
): Promise<ProductReviewsResult> {
  return request.get(`/trade/reviews/by-spu/${encodeURIComponent(spuId)}`, { params })
}

/**
 * 关联不上产品的差评（孤儿兜底列表）。
 *
 * ★ 为什么要这一张表：软关联没有外键兜 ⇒ 关联不上的差评**不会出现在任何
 *   产品的差评 tab 里**，它们只是静默消失。没有它，「这个产品 0 条差评」
 *   这句话永远无法被证伪。
 */
export async function listOrphanReviews(params?: {
  max_rating?: number
  limit?: number
  offset?: number
}): Promise<OrphanReviewsResult> {
  return request.get('/trade/reviews/orphans', { params })
}

/** 发放（人）—— 不可逆，只有这一步生成券码 */''',
    "trade api 追加软关联两函数",
)

_write(API, api)

# ============================================================ ProductLibrary.vue

v = _read(VIEW)

v = sub(
    v,
    "import { ref, computed, onMounted } from 'vue'",
    "import { ref, computed, onMounted, watch } from 'vue'",
    "vue import 加 watch",
)

v = sub(
    v,
    "import { bandOf } from '@/theme/bands'",
    "import { bandOf } from '@/theme/bands'\n"
    "import {\n"
    "  listReviewsBySpu,\n"
    "  type ProductReviewsResult,\n"
    "} from '@/api/trade'",
    "import 差评 api",
)

v = sub(
    v,
    "  AppstoreOutlined,\n  UnorderedListOutlined,\n} from '@ant-design/icons-vue'",
    "  AppstoreOutlined,\n  UnorderedListOutlined,\n  ReloadOutlined,\n"
    "} from '@ant-design/icons-vue'",
    "icons 加 ReloadOutlined",
)

# ---------------- 模板：包 tab + 差评 pane

v = sub(
    v,
    '      <template v-if="currentDetail">\n        <!-- 主图 -->',
    '''      <template v-if="currentDetail">
        <!-- ★ 详情 / 差评 双 tab（第 289 轮 P0）：默认停在「详情」，
             不打扰既有阅读路径；差评 tab 上有条数 / 缺口角标。 -->
        <a-tabs v-model:activeKey="detailTab" size="small" class="pl-detail-tabs">
          <a-tab-pane key="detail">
            <template #tab><span>🗂 详情</span></template>
        <!-- 主图 -->''',
    "模板 tab 开头",
)

v = sub(
    v,
    '''          <a-table
            :columns="variationColumns"
            :data-source="detailSkus"
            :pagination="false"
            size="small"
            row-key="asin"
          />
        </div>
      </template>
    </a-drawer>''',
    '''          <a-table
            :columns="variationColumns"
            :data-source="detailSkus"
            :pagination="false"
            size="small"
            row-key="asin"
          />
        </div>
          </a-tab-pane>

          <!-- ★ 差评 tab：SPU 只是聚合壳，真正的键在 SKU 的 ASIN 上 -->
          <a-tab-pane key="reviews">
            <template #tab>
              <span>
                📉 差评
                <span v-if="reviewResult?.total" class="pl-tab-count">{{ reviewResult.total }}</span>
                <span
                  v-else-if="reviewResult && reviewResult.empty_state && reviewResult.empty_state !== 'no_reviews'"
                  class="pl-tab-warn"
                  title="关联有缺口，进去看说明"
                >!</span>
              </span>
            </template>

            <div class="pl-review-bar">
              <a-switch v-model:checked="reviewOnlyNegative" size="small" @change="reloadProductReviews" />
              <span class="pl-review-bar-label">只看中差评（≤3 星）</span>
              <a-button size="small" type="text" :loading="reviewLoading" @click="reloadProductReviews">
                <ReloadOutlined /> 刷新
              </a-button>
            </div>

            <div v-if="reviewResult" class="pl-review-scope">
              关联口径：{{ currentDetail.is_spu ? '本 SPU' : '所属 SPU' }}名下
              <b>{{ reviewResult.sku_count }}</b> 个 SKU /
              <b>{{ reviewResult.asin_count }}</b> 个 ASIN（按 SKU 的 ASIN
              <template v-if="reviewResult.asin_count === 0">，为空时</template>匹配）
            </div>

            <a-alert
              v-if="reviewError"
              type="error"
              show-icon
              :message="reviewError"
              class="pl-review-alert"
            />

            <div v-else-if="reviewLoading && !reviewResult" class="pl-review-empty">
              <a-spin size="small" /> 正在按 SKU 的 ASIN 关联差评…
            </div>

            <div v-else-if="reviewEmpty" :class="['pl-review-empty', reviewEmpty.tone]">
              <div class="pl-review-empty-icon">{{ reviewEmpty.icon }}</div>
              <div class="pl-review-empty-title">{{ reviewEmpty.title }}</div>
              <div class="pl-review-empty-desc">{{ reviewEmpty.desc }}</div>
            </div>

            <div v-else class="pl-review-list">
              <div v-for="r in reviewResult?.reviews ?? []" :key="r.id" class="pl-review-item">
                <div class="pl-review-top">
                  <span class="pl-review-stars">{{ '★'.repeat(Math.max(0, r.rating)) }}<span class="pl-stars-dim">{{ '★'.repeat(Math.max(0, 5 - (r.rating || 0))) }}</span></span>
                  <span class="pl-review-date">{{ (r.review_at || '').slice(0, 10) || '-' }}</span>
                  <a-tag v-if="r.source === 'mock_seed'" color="orange" size="small">演示数据</a-tag>
                </div>
                <div class="pl-review-title-line">{{ r.title || '（无标题）' }}</div>
                <div class="pl-review-body">{{ r.body || '—' }}</div>
                <div class="pl-review-meta">
                  <span>{{ r.buyer_name || '匿名买家' }}</span>
                  <span>·</span>
                  <span>{{ REVIEW_STATUS_LABELS[r.status] || r.status || '未处理' }}</span>
                  <template v-if="r.match_kind === 'asin'">
                    <span>·</span><span>命中 ASIN <code>{{ r.asin }}</code></span>
                  </template>
                  <template v-else-if="r.match_kind === 'sku_code'">
                    <span>·</span><span>命中 SKU 码 <code>{{ r.sku }}</code></span>
                  </template>
                </div>
              </div>
            </div>
          </a-tab-pane>
        </a-tabs>
      </template>
    </a-drawer>''',
    "模板 tab 结尾 + 差评 pane",
)

# ---------------- script：状态 / 计算 / 加载

v = sub(
    v,
    "/** 详情抽屉里 SPU 的 SKU 列表：始终取真实 SKU（不受 treeItems 单品隐藏 children 影响） */",
    '''// ============================================================ 差评 tab
//
// ★ 差评与产品是**软关联**：`customer_reviews.asin` 没有外键指到 `skus`
//   （平台侧标识符，不能因为本地少一行就让差评插不进来）。没有外键兜 ⇒
//   join 可能一行都匹配不上，而「匹配不上」有两种语义完全不同的"空"：
//     · 这个产品确实没有差评       —— 正常结论
//     · 差评和产品**没能对上**     —— 数据缺口
//   下面把这两种分别播报（见 `reviewEmpty`）—— 混成一个「暂无差评」
//   等于把缺口伪装成「产品没问题」。
//
// ★ SPU 只当聚合壳：SPU 无 ASIN、不可售 ⇒ 由后端按
//   `spus.id → skus.spu_id → skus.asin` 解出 ASIN 集合再去匹配，并去重
//   （同一个 ASIN 可能挂在多个 SKU 上，真库实测一个 ASIN → 4 SKU / 4 SPU）。

/** 详情抽屉当前 tab；换产品时回到「详情」（差评是新信息，不是默认视图） */
const detailTab = ref<'detail' | 'reviews'>('detail')
const reviewLoading = ref(false)
const reviewResult = ref<ProductReviewsResult | null>(null)
const reviewError = ref('')
const reviewOnlyNegative = ref(true)

/** 差评状态中文名（后端 `status` 取值：new / triaged / replied / closed） */
const REVIEW_STATUS_LABELS: Record<string, string> = {
  new: '待处理',
  triaged: '已归因',
  replied: '已回复',
  closed: '已结案',
}

/** 差评要挂到哪个 SPU 上：SPU 详情用自己，SKU 详情用它的父 SPU */
const reviewOwnerId = computed<string>(() => {
  const p = currentDetail.value
  if (!p) return ''
  return p.is_spu ? p.id : (p.spu_id || '')
})

async function loadProductReviews() {
  const spuId = reviewOwnerId.value
  reviewResult.value = null
  reviewError.value = ''
  // ★ 拿不到归属就明确报错，不放空列表：「挂不到 SPU 上」不是「没有差评」
  if (!spuId) {
    reviewError.value = '这个 SKU 没有归属 SPU，差评无法按产品聚合（差评是按 SPU 名下 SKU 的 ASIN 关联的）'
    return
  }
  reviewLoading.value = true
  try {
    reviewResult.value = await listReviewsBySpu(spuId, {
      max_rating: reviewOnlyNegative.value ? 3 : undefined,
      limit: 50,
    })
  } catch (e: any) {
    reviewError.value = e?.response?.data?.detail || e?.message || '差评加载失败'
  } finally {
    reviewLoading.value = false
  }
}

function reloadProductReviews() {
  void loadProductReviews()
}

/** 打开抽屉 / 换产品就重新拉：抽屉里没有「手动刷新」才是合格的默认行为 */
watch([drawerVisible, () => currentDetail.value?.id], ([open, _id]) => {
  detailTab.value = 'detail'
  reviewResult.value = null
  reviewError.value = ''
  if (open) void loadProductReviews()
})

/** 空态文案 —— 两种「空」必须字面不同 */
const reviewEmpty = computed(() => {
  if (reviewError.value) return null
  const r = reviewResult.value
  if (!r) return null
  const scope = `已登记 ${r.sku_count} 个 SKU / ${r.asin_count} 个 ASIN`
  switch (r.empty_state) {
    case 'not_found':
      return {
        tone: 'warn', icon: '🔒',
        title: '这个产品在所选店铺下查不到',
        desc: '可能已被删除，或不属于当前店铺 —— 与「没有差评」是两件事。',
      }
    case 'no_sku':
      return {
        tone: 'warn', icon: '🧩',
        title: '这个 SPU 下还没有登记任何 SKU',
        desc: '差评是按 SKU 的 ASIN 关联的；没有 SKU 就无从关联。这不是「没有差评」。',
      }
    case 'no_asin_binding':
      return {
        tone: 'warn', icon: '🔗',
        title: 'SKU 登记了，但 ASIN / SKU 码都是空的',
        desc: scope + ' ⇒ 差评再怎么存在也对不上来。这是数据缺口，先去补 SKU 的 ASIN 再回来看。',
      }
    case 'no_reviews':
      return {
        tone: 'ok', icon: '✅',
        title: reviewOnlyNegative.value ? '未见中差评' : '暂无评价',
        desc: scope + '，关联得上，且确实没有符合条件的评价。',
      }
    default:
      return null
  }
})

/** 详情抽屉里 SPU 的 SKU 列表：始终取真实 SKU（不受 treeItems 单品隐藏 children 影响） */''',
    "script 加差评状态与加载",
)

# ---------------- style

v = sub(
    v,
    ".pc-bullet-row {\n  display: flex;\n  gap: var(--space-8);\n  align-items: center;\n  margin-bottom: var(--space-8);\n}",
    """.pc-bullet-row {
  display: flex;
  gap: var(--space-8);
  align-items: center;
  margin-bottom: var(--space-8);
}

/* ===== 差评 tab（第 289 轮） ===== */
.pl-detail-tabs {
  margin-top: calc(-1 * var(--space-8));
}
.pl-tab-count {
  margin-left: var(--space-4);
  padding: 0 var(--space-6);
  border-radius: var(--radius-6);
  background: var(--bg-elevated);
  color: var(--text-secondary);
  font-size: var(--font-size-12);
}
.pl-tab-warn {
  margin-left: var(--space-4);
  color: var(--color-warning, #d46b08);
  font-weight: 600;
}
.pl-review-bar {
  display: flex;
  align-items: center;
  gap: var(--space-8);
  margin-bottom: var(--space-8);
}
.pl-review-bar-label {
  font-size: var(--font-size-12);
  color: var(--text-secondary);
}
.pl-review-scope {
  font-size: var(--font-size-12);
  color: var(--text-secondary);
  padding: var(--space-6) var(--space-8);
  border: 1px dashed var(--border-base);
  border-radius: var(--radius-6);
  margin-bottom: var(--space-8);
}
.pl-review-alert {
  margin-bottom: var(--space-8);
}
.pl-review-empty {
  padding: var(--space-16);
  text-align: center;
  color: var(--text-secondary);
  border: 1px dashed var(--border-base);
  border-radius: var(--radius-6);
}
.pl-review-empty.warn {
  border-color: var(--color-warning, #d46b08);
  background: var(--bg-elevated);
}
.pl-review-empty.ok {
  color: var(--text-disabled);
}
.pl-review-empty-icon {
  font-size: 22px;
  margin-bottom: var(--space-6);
}
.pl-review-empty-title {
  font-weight: 600;
  margin-bottom: var(--space-4);
}
.pl-review-empty-desc {
  font-size: var(--font-size-12);
  color: var(--text-secondary);
}
.pl-review-item {
  padding: var(--space-8);
  border: 1px solid var(--border-base);
  border-radius: var(--radius-6);
  margin-bottom: var(--space-8);
}
.pl-review-top {
  display: flex;
  align-items: center;
  gap: var(--space-8);
  margin-bottom: var(--space-4);
}
.pl-review-stars {
  color: #faad14;
  letter-spacing: 1px;
}
.pl-stars-dim {
  color: var(--text-disabled);
}
.pl-review-date {
  font-size: var(--font-size-12);
  color: var(--text-disabled);
  margin-left: auto;
}
.pl-review-title-line {
  font-weight: 600;
  margin-bottom: var(--space-2);
}
.pl-review-body {
  font-size: var(--font-size-12);
  color: var(--text-secondary);
  margin-bottom: var(--space-4);
}
.pl-review-meta {
  display: flex;
  flex-wrap: wrap;
  gap: var(--space-4);
  font-size: var(--font-size-12);
  color: var(--text-disabled);
}""",
    "追加差评 tab 样式",
)

_write(VIEW, v)

print("patched: api/trade.ts, ProductLibrary.vue")
