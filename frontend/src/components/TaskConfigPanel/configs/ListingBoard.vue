<template>
  <div class="lb-config">
    <!-- ====== 顶部：产品上下文 ====== -->
    <div class="lb-head">
      <div class="lb-prod">
        <span class="lb-prod-icon">🧩</span>
        <div class="lb-prod-main">
          <div class="lb-prod-name">
            {{ draft.productName || '未载入产品' }}
            <a-tag
              v-if="draft.variationValue"
              color="purple"
              class="mini-tag"
            >
              规格：{{ draft.variationValue }}
            </a-tag>
            <a-tag
              v-if="draft.sourceMode === 'product'"
              color="blue"
              class="mini-tag"
            >
              已载入
            </a-tag>
            <a-tag
              v-else
              color="orange"
              class="mini-tag"
            >
              请先载入
            </a-tag>
          </div>
          <div class="lb-prod-sub">
            <template v-if="noProduct">
              💡 请先从顶部「载入产品」选定商品，再生成 / 保存文案
            </template>
            <template v-else>
              <span
                v-if="draft.asin"
                class="lb-prod-asin"
              >{{ draft.asin }}</span>
              已填 {{ draft.filledCount }} 个模块<template v-if="isDataMode">
                · 顶部 4 个按钮可一键跳转编辑
              </template><template v-else>
                · 点顶部工具栏工具切换模块
              </template>
            </template>
          </div>
        </div>
      </div>

      <!-- 文案模式：顶部加回 4 个模块按钮 -->
      <div
        v-if="isDataMode"
        class="lb-tabs"
      >
        <button
          v-for="m in MODULES"
          :key="m.key"
          class="lb-tab"
          :class="{ active: activeModule === m.key, filled: draft.moduleFilled[m.key] }"
          @click="jumpToModule(m.key)"
        >
          <span class="lb-tab-icon">{{ m.icon }}</span>
          <span>{{ m.label }}</span>
          <span
            v-if="draft.moduleFilled[m.key]"
            class="lb-dot"
          />
        </button>
      </div>
    </div>

    <!-- ====== 全局文案指令（第 273 轮） ====== -->
    <div class="lb-global-prompt">
      <div class="gp-label">
        🌐 全局文案指令 <span class="gp-sub">作用于四个模块；模块内「自定义 prompt」可覆盖对应部分</span>
      </div>
      <a-textarea
        v-model:value="draft.globalInstruction"
        :rows="2"
        placeholder="例如：整体面向欧美户外人群，语气专业但不生硬，避免过度营销词"
      />
    </div>

    <!--
      生成失败：内联**常驻**出口。
      HTTP 错误拦截器已经弹过一次 toast（内容是后端 detail），但 toast 会消失；
      这里留一条不消失的记录，避免「点了没反应 / 只闪了一下」。
      ★ 因此本组件**不再重复** message.error，避免同一次失败弹两条。
    -->
    <div
      v-if="boardError"
      class="lb-error"
    >
      <span class="lb-error-msg">{{ boardError }}</span>
      <a-button
        size="small"
        type="text"
        @click="boardError = ''"
      >
        关闭
      </a-button>
    </div>

    <!-- ====== 对话模式：仅显示当前工具对应模块 ====== -->
    <div
      v-if="!isDataMode"
      class="lb-pane lb-pane-single"
    >
      <KeywordsSection
        v-if="activeModule === 'keywords'"
        :gen-loading="genLoading === 'keywords'"
        :disabled="noProduct"
        @gen="genOne('keywords')"
      />
      <TitleSection
        v-else-if="activeModule === 'title'"
        :gen-loading="genLoading === 'title'"
        :disabled="noProduct"
        @gen="genOne('title')"
      />
      <BulletsSection
        v-else-if="activeModule === 'bullets'"
        :gen-loading="genLoading === 'bullets'"
        :disabled="noProduct"
        @gen="genOne('bullets')"
      />
      <AplusSection
        v-else
        :gen-loading="genLoading === 'aplus'"
        :disabled="noProduct"
        @gen="genOne('aplus')"
      />
    </div>

    <!-- ====== 文案模式：完整工作区（4 模块平铺 + 滚动定位高亮） ====== -->
    <div
      v-else
      ref="paneRef"
      class="lb-pane lb-pane-all"
    >
      <section
        id="lb-mod-keywords"
        class="lb-section"
        :class="{ 'lb-mod-flash': flashingModule === 'keywords' }"
      >
        <KeywordsSection
          :gen-loading="genLoading === 'keywords'"
          :disabled="noProduct"
          @gen="genOne('keywords')"
        />
      </section>

      <section
        id="lb-mod-title"
        class="lb-section"
        :class="{ 'lb-mod-flash': flashingModule === 'title' }"
      >
        <TitleSection
          :gen-loading="genLoading === 'title'"
          :disabled="noProduct"
          @gen="genOne('title')"
        />
      </section>

      <section
        id="lb-mod-bullets"
        class="lb-section"
        :class="{ 'lb-mod-flash': flashingModule === 'bullets' }"
      >
        <BulletsSection
          :gen-loading="genLoading === 'bullets'"
          :disabled="noProduct"
          @gen="genOne('bullets')"
        />
      </section>

      <section
        id="lb-mod-aplus"
        class="lb-section"
        :class="{ 'lb-mod-flash': flashingModule === 'aplus' }"
      >
        <AplusSection
          :gen-loading="genLoading === 'aplus'"
          :disabled="noProduct"
          @gen="genOne('aplus')"
        />
      </section>
    </div>

    <!-- ====== 底部统一操作 ====== -->
    <div class="lb-actions">
      <a-button
        size="small"
        type="primary"
        :loading="allLoading"
        :disabled="noProduct"
        @click="genAllModules"
      >
        ⚡ 一键生成全部
      </a-button>
      <a-button
        size="small"
        :loading="saving"
        :disabled="noProduct"
        @click="saveAll"
      >
        💾 保存全部
      </a-button>
      <a-button
        size="small"
        type="text"
        @click="clearAll"
      >
        清空
      </a-button>
    </div>
  </div>
</template>

<script setup lang="ts">
/**
 * Listing 统一工作区
 *
 * ★ 第 169 轮 #738：原先四个模块的文案全部来自 `@/mock/listingBoard` 的
 *   `genAll()`（一次同步调用吐一份写死的「手摇咖啡磨」文案），现在改调后端
 *   `/api/v1/listing/*`。四个模块各自走最贴的端点，不为了省往返去生成用不到的东西：
 *
 *   | 模块 | 端点 | 说明 |
 *   |---|---|---|
 *   | 关键词 | `POST /generate/keywords` | **Search Terms**，参数走 body |
 *   | 标题 | `POST /optimize/title` | 唯一能单独出标题的端点 |
 *   | 五点 | `POST /generate/bullets` | |
 *   | 长描述 | `POST /generate/description` | |
 *   | 一键全部 | `POST /generate` | 一次往返拿全四个模块 |
 *
 * ★ 三处「后端确实没有」的地方，一律**如实呈现，不补数**：
 *   1. 搜索量 / 竞争度 / 相关度：Search Terms 端点不提供 ⇒ 渲染 «—»（不是 0）。
 *   2. 备选标题：`ListingTitle` 没有 variants 字段 ⇒ 该区块自动隐藏。
 *   3. SEO 诊断：面板不生成（`/analyze/seo` 本机实测 500），走对话编排器那条链。
 *
 * ★ 提示归属：成功提示由本组件自己给（`message.success('已生成，可直接修改')`）——
 *   拦截器自第 267 轮起**不再**自动弹成功提示，所以这里不需要任何开关；
 *   失败提示交给拦截器（它带 detail），本组件另外补一条常驻横幅 `boardError`。
 *   ★ 为什么**不**声明 `silentError`：本模块的端点是 `listing_generator`，
 *     失败走 4xx/5xx（该模块全仓没有一处 `success=False`）⇒ 新补的业务失败
 *     补判不会在这里触发；错误 toast 也就没有「两处报」的问题。
 */
import { ref, computed, watch, inject, onMounted, nextTick, type Ref } from 'vue'
import { message, Modal } from 'ant-design-vue'
import { useListingDraftStore } from '@/stores/listingDraft'
import {
  generateListing,
  generateBullets,
  generateDescription,
  generateKeywords,
  optimizeTitle,
} from '@/api/listingGenerator'
import KeywordsSection from './listingSections/KeywordsSection.vue'
import TitleSection from './listingSections/TitleSection.vue'
import BulletsSection from './listingSections/BulletsSection.vue'
import AplusSection from './listingSections/AplusSection.vue'

const props = defineProps<{ currentToolId?: string }>()

// 顶部工具栏工具 → 模块映射
const TOOL_MODULE_MAP: Record<string, string> = {
  'keyword-miner': 'keywords',
  'title-gen': 'title',
  'bullet-gen': 'bullets',
  'desc-gen': 'aplus',
}

// 文案模式下的 4 个模块按钮
const MODULES = [
  { key: 'keywords', label: '关键词', icon: '🔑' },
  { key: 'title', label: '标题', icon: '📝' },
  { key: 'bullets', label: '五点', icon: '✨' },
  { key: 'aplus', label: '长描述', icon: '📄' },
] as const

const draft = useListingDraftStore()

// 当前载入的产品（Workspace provide）
const workingProduct = inject<Ref<any>>('workingProduct', ref(null))
// 当前「对话/文案」模式（Workspace provide）
const reviewMode = inject<Ref<'chat' | 'data'>>('reviewMode', ref('chat') as Ref<'chat' | 'data'>)
const isDataMode = computed(() => reviewMode.value === 'data')

const paneRef = ref<HTMLElement | null>(null)
const activeModule = ref<string>('title')
const flashingModule = ref<string | null>(null)
const genLoading = ref<string | null>(null)
const allLoading = ref(false)
const saving = ref(false)
/** 常驻失败原因（toast 会消失，这个不会） */
const boardError = ref('')

// 是否未载入产品（未载入则禁止生成/保存）
const noProduct = computed(() => draft.sourceMode !== 'product')

watch(
  () => props.currentToolId,
  (tid) => {
    const m = TOOL_MODULE_MAP[tid || '']
    if (m) {
      activeModule.value = m
      // 文案模式下还要滚动定位 + 高亮
      if (isDataMode.value) jumpToModule(m)
    }
  }
)

// 载入产品 → 预填草稿
watch(
  () => workingProduct.value,
  (p) => { if (p) draft.loadFromProduct(p) },
  { immediate: true }
)
onMounted(() => {
  if (workingProduct.value) draft.loadFromProduct(workingProduct.value)
})

// 文案模式：点顶部按钮 → 设激活态 + 滚动定位 + 高亮闪烁
function jumpToModule(key: string) {
  activeModule.value = key
  flashModule(key)
  nextTick(() => {
    const el = document.getElementById(`lb-mod-${key}`)
    if (el && paneRef.value) {
      const paneTop = paneRef.value.getBoundingClientRect().top
      const elTop = el.getBoundingClientRect().top
      paneRef.value.scrollTo({ top: paneRef.value.scrollTop + (elTop - paneTop) - 8, behavior: 'smooth' })
    }
  })
}

let flashTimer: any = null
function flashModule(key: string) {
  flashingModule.value = key
  if (flashTimer) clearTimeout(flashTimer)
  flashTimer = setTimeout(() => { flashingModule.value = null }, 1400)
}

// ====== 请求前的守卫与入参整理 ======

/** 未载入产品 → 拦截，提示先载入（与其他 Agent 一致） */
function ensureProduct(): boolean {
  if (draft.sourceMode === 'product') return true
  message.warning('请先从顶部「载入产品」选定商品，再生成文案')
  return false
}

/** 用户填的「核心卖点」是一个用 | ， 、 换行 分隔的长串 → 拆成数组给后端 */
function featureList(): string[] {
  return (draft.sellingPoints || '')
    .split(/[|，,、\n]/)
    .map(s => s.trim())
    .filter(Boolean)
    .slice(0, 8)
}

/**
 * `/optimize/title` 的 `current_title` 是必填且 `min_length=5`。
 * 工作区可能还没写过标题 ⇒ 用产品名当种子；产品名也短就补一个中性后缀
 * —— 它只是给模型的**上下文**，不是产物，所以补词不影响数据真实性。
 */
function titleSeed(): string {
  const base = (draft.title || draft.productName || '').trim()
  return base.length >= 5 ? base : `${base || 'Untitled'} Product`
}

/** 错误文案：后端 500 的 `detail` 是给用户看的中文原因，优先用它 */
function errText(e: any): string {
  return e?.response?.data?.detail || e?.message || '生成失败，请稍后重试'
}

/** 后端 `Search Terms`（扁平词表）→ 关键词行。★ 指标留给后端不提供的 null。 */
function termsToRows(terms: string[]) {
  return terms.map(w => ({ word: w }))
}

// ====== 生成 ======

async function genOne(mod: string) {
  if (!ensureProduct()) return
  genLoading.value = mod
  boardError.value = ''
  try {
    if (mod === 'keywords') {
      // ★ 第 273 轮：后端已改 body（Pydantic KeywordRequest），
      //   `custom_prompt` 也走 body。局部覆盖全局，均空则走默认词池。
      const res = await generateKeywords(
        {
          title: draft.title.trim() || draft.productName,
          category: draft.category || undefined,
          custom_prompt: draft.resolvePrompt(draft.keywordPrompt),
        }
      )
      draft.setKeywords(termsToRows(res.data.terms || []))
    } else if (mod === 'title') {
      const res = await optimizeTitle(
        {
          current_title: titleSeed(),
          product_name: draft.productName,
          main_keyword: undefined,
          custom_prompt: draft.resolvePrompt(draft.titlePrompt),
        }
      )
      // `ListingTitle` 没有备选标题字段 ⇒ variants 传空（TitleSection 会隐藏该区块）
      draft.setTitle(res.data.optimized_title || '', [])
    } else if (mod === 'bullets') {
      const res = await generateBullets(
        { product_name: draft.productName, features: featureList(), custom_prompt: draft.resolvePrompt(draft.bulletPrompt) }
      )
      draft.setBullets(res.data.bullets || [])
    } else if (mod === 'aplus') {
      const res = await generateDescription(
        { product_name: draft.productName, features: featureList(), custom_prompt: draft.resolvePrompt(draft.aplusPrompt) }
      )
      // `sections` 的 `type` 是语义枚举（intro/features/scenarios），
      // 到 A+ 版式类型的映射在 `stores/listingDraft.ts::normalizeModule` 里做
      draft.setAPlus(res.data.sections || [])
    }
    message.success('已生成，可直接修改')
  } catch (e: any) {
    boardError.value = errText(e)
  } finally {
    genLoading.value = null
  }
}

async function genAllModules() {
  if (!ensureProduct()) return
  allLoading.value = true
  boardError.value = ''
  try {
    const res = await generateListing(
      {
        product_name: draft.productName,
        brand: draft.brand || undefined,
        category: draft.category || undefined,
        features: featureList(),
      }
    )
    const d = res.data
    draft.setTitle(d.title?.title || '', [])
    draft.setBullets(d.bullet_points?.bullets || [])
    draft.setAPlus(d.description?.sections || [])
    draft.setKeywords(termsToRows(d.search_terms?.terms || []))
    // 注意：**不**写 SEO。面板不展示 SEO（`/analyze/seo` 实测 500），
    // SEO 诊断结果由对话编排器那条链写入草稿。
    message.success('四个模块已全部生成')
  } catch (e: any) {
    boardError.value = errText(e)
  } finally {
    allLoading.value = false
  }
}

// ====== 保存 / 清空 ======
async function saveAll() {
  saving.value = true
  try {
    const r = await draft.saveToProduct()
    r.ok ? message.success(r.msg) : message.warning(r.msg)
  } catch (e: any) {
    // 兜底：不让异常变成未处理的 rejection（那会表现为「点了没反应」）
    console.error('[ListingBoard] 保存失败', e)
    message.error(`保存失败：${e?.message || '未知错误'}`)
  } finally {
    saving.value = false
  }
}

function clearAll() {
  Modal.confirm({
    title: '清空当前草稿？',
    content: '仅清空面板内未保存的编辑内容，不会改动已保存的产品数据。',
    okText: '清空',
    cancelText: '取消',
    onOk: () => {
      draft.reset()
      if (workingProduct.value) draft.loadFromProduct(workingProduct.value)
    },
  })
}
</script>

<style scoped>
.lb-config {
  display: flex;
  flex-direction: column;
  height: 100%;
  min-height: 0;
}

/* 头部：产品 + （文案模式）4 按钮 */
.lb-head {
  flex-shrink: 0;
  padding: var(--space-10) var(--space-12) var(--space-8);
  border-bottom: 1px solid var(--border-base);
}

/* 常驻失败横幅 */
.lb-error {
  flex-shrink: 0;
  display: flex;
  align-items: flex-start;
  gap: var(--space-8);
  padding: var(--space-8) var(--space-12);
  background: rgba(255, 77, 79, 0.08);
  border-bottom: 1px solid var(--border-base);
}
.lb-error-msg {
  flex: 1;
  font-size: var(--font-size-12);
  line-height: 1.5;
  color: var(--danger);
  word-break: break-word;
}

.lb-prod {
  display: flex;
  gap: var(--space-8);
  align-items: center;
}
.lb-prod-icon { font-size: var(--font-size-18); }
.lb-prod-main { min-width: 0; flex: 1; }
.lb-prod-name {
  font-size: var(--font-size-13);
  font-weight: 600;
  color: var(--text-primary);
  white-space: nowrap;
  overflow: hidden;
  text-overflow: ellipsis;
}
.lb-prod-sub { font-size: var(--font-size-11); color: var(--text-tertiary); margin-top: var(--space-2); }
.lb-prod-asin { font-family: monospace; font-size: var(--font-size-11); color: var(--primary); margin-right: var(--space-6); }
.mini-tag { transform: scale(0.85); margin-left: var(--space-4); }

/* 全局文案指令 */
.lb-global-prompt {
  flex-shrink: 0;
  padding: var(--space-8) var(--space-12);
  border-bottom: 1px solid var(--border-base);
  background: var(--bg-base);
}
.gp-label {
  font-size: var(--font-size-12);
  font-weight: 600;
  color: var(--text-primary);
  margin-bottom: var(--space-6);
}
.gp-sub {
  font-weight: 400;
  font-size: var(--font-size-11);
  color: var(--text-tertiary);
  margin-left: var(--space-4);
}

.lb-tabs {
  display: flex;
  gap: var(--space-6);
  margin-top: var(--space-8);
}
.lb-tab {
  position: relative;
  display: flex;
  align-items: center;
  gap: var(--space-4);
  padding: var(--space-5) var(--space-14);
  font-size: var(--font-size-12);
  border: 1px solid var(--border-base);
  border-radius: var(--radius-6);
  background: transparent;
  color: var(--text-secondary);
  cursor: pointer;
  transition: all 0.18s ease;
}
.lb-tab:hover { color: var(--primary); border-color: var(--primary); }
.lb-tab.active {
  background: var(--primary);
  border-color: var(--primary);
  color: #fff;
}
.lb-tab-icon { font-size: var(--font-size-12); }
.lb-dot {
  width: 5px;
  height: 5px;
  border-radius: var(--radius-circle);
  background: var(--success);
}
.lb-tab.active .lb-dot { background: var(--bg-elevated); }

/* 内容页容器 */
.lb-pane {
  flex: 1;
  min-height: 0;
  overflow-y: auto;
  padding: var(--space-12);
}
.lb-pane-single {
  display: flex;
  flex-direction: column;
}
.lb-pane-all {
  display: flex;
  flex-direction: column;
  gap: var(--space-20);
  scroll-behavior: smooth;
}

/* 文案模式的模块卡片 */
.lb-section {
  display: flex;
  flex-direction: column;
  gap: var(--space-10);
  padding: var(--space-12);
  border: 1px solid var(--border-base);
  border-radius: var(--radius-8);
  background: var(--bg-elevated);
  transition: box-shadow 0.3s ease, border-color 0.3s ease, background 0.3s ease;
}
.lb-section.lb-mod-flash {
  animation: lbModFlash 1.4s ease;
}
@keyframes lbModFlash {
  0% { box-shadow: 0 0 0 2px var(--primary); background: rgba(24, 144, 255, 0.08); }
  50% { box-shadow: 0 0 0 2px var(--primary); background: rgba(24, 144, 255, 0.04); }
  100% { box-shadow: none; background: var(--bg-elevated); }
}

/* 底部操作 */
.lb-actions {
  flex-shrink: 0;
  display: flex;
  align-items: center;
  gap: var(--space-8);
  padding: var(--space-8) var(--space-12);
  border-top: 1px solid var(--border-base);
}
</style>
