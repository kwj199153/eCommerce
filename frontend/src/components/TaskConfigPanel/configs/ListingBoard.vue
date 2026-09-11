<template>
  <div class="lb-config">
    <!-- ====== 顶部：产品上下文 ====== -->
    <div class="lb-head">
      <div class="lb-prod">
        <span class="lb-prod-icon">🧩</span>
        <div class="lb-prod-main">
          <div class="lb-prod-name">
            {{ draft.productName || '未载入产品' }}
            <a-tag v-if="draft.variationValue" color="purple" class="mini-tag">规格：{{ draft.variationValue }}</a-tag>
            <a-tag v-if="draft.sourceMode === 'product'" color="blue" class="mini-tag">已载入</a-tag>
            <a-tag v-else color="orange" class="mini-tag">请先载入</a-tag>
          </div>
          <div class="lb-prod-sub">
            <template v-if="noProduct">💡 请先从顶部「载入产品」选定商品，再生成 / 保存文案</template>
            <template v-else>
              <span v-if="draft.asin" class="lb-prod-asin">{{ draft.asin }}</span>
              已填 {{ draft.filledCount }} 个模块<template v-if="isDataMode"> · 顶部 4 个按钮可一键跳转编辑</template><template v-else> · 点顶部工具栏工具切换模块</template>
            </template>
          </div>
        </div>
      </div>

      <!-- 文案模式：顶部加回 4 个模块按钮 -->
      <div v-if="isDataMode" class="lb-tabs">
        <button
          v-for="m in MODULES"
          :key="m.key"
          class="lb-tab"
          :class="{ active: activeModule === m.key, filled: draft.moduleFilled[m.key] }"
          @click="jumpToModule(m.key)"
        >
          <span class="lb-tab-icon">{{ m.icon }}</span>
          <span>{{ m.label }}</span>
          <span v-if="draft.moduleFilled[m.key]" class="lb-dot" />
        </button>
      </div>
    </div>

    <!-- ====== 对话模式：仅显示当前工具对应模块 ====== -->
    <div v-if="!isDataMode" class="lb-pane lb-pane-single">
      <KeywordsSection v-if="activeModule === 'keywords'" :gen-loading="genLoading === 'keywords'" :disabled="noProduct" @gen="genOne('keywords')" />
      <TitleSection v-else-if="activeModule === 'title'" :gen-loading="genLoading === 'title'" :disabled="noProduct" @gen="genOne('title')" />
      <BulletsSection v-else-if="activeModule === 'bullets'" :gen-loading="genLoading === 'bullets'" :disabled="noProduct" @gen="genOne('bullets')" />
      <AplusSection v-else :gen-loading="genLoading === 'aplus'" :disabled="noProduct" @gen="genOne('aplus')" />
    </div>

    <!-- ====== 文案模式：完整工作区（4 模块平铺 + 滚动定位高亮） ====== -->
    <div v-else ref="paneRef" class="lb-pane lb-pane-all">
      <section
        id="lb-mod-keywords"
        class="lb-section"
        :class="{ 'lb-mod-flash': flashingModule === 'keywords' }"
      >
        <KeywordsSection :gen-loading="genLoading === 'keywords'" :disabled="noProduct" @gen="genOne('keywords')" />
      </section>

      <section
        id="lb-mod-title"
        class="lb-section"
        :class="{ 'lb-mod-flash': flashingModule === 'title' }"
      >
        <TitleSection :gen-loading="genLoading === 'title'" :disabled="noProduct" @gen="genOne('title')" />
      </section>

      <section
        id="lb-mod-bullets"
        class="lb-section"
        :class="{ 'lb-mod-flash': flashingModule === 'bullets' }"
      >
        <BulletsSection :gen-loading="genLoading === 'bullets'" :disabled="noProduct" @gen="genOne('bullets')" />
      </section>

      <section
        id="lb-mod-aplus"
        class="lb-section"
        :class="{ 'lb-mod-flash': flashingModule === 'aplus' }"
      >
        <AplusSection :gen-loading="genLoading === 'aplus'" :disabled="noProduct" @gen="genOne('aplus')" />
      </section>
    </div>

    <!-- ====== 底部统一操作 ====== -->
    <div class="lb-actions">
      <a-button size="small" type="primary" :loading="allLoading" :disabled="noProduct" @click="genAllModules">
        ⚡ 一键生成全部
      </a-button>
      <a-button size="small" :loading="saving" :disabled="noProduct" @click="saveAll">
        💾 保存全部
      </a-button>
      <a-button size="small" type="text" @click="clearAll">清空</a-button>
    </div>
  </div>
</template>

<script setup lang="ts">
import { ref, computed, watch, inject, onMounted, nextTick, type Ref } from 'vue'
import { message, Modal } from 'ant-design-vue'
import { useListingDraftStore } from '@/stores/listingDraft'
import { genAll, type BoardGenContext } from '@/mock/listingBoard'
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

// ====== 生成 ======
const genCtx = computed<BoardGenContext>(() => ({
  productName: draft.productName,
  brand: draft.brand,
  sellingPoints: draft.sellingPoints,
  category: draft.category,
  site: draft.site,
}))

function applyGenerated(data: ReturnType<typeof genAll>) {
  draft.setKeywords(data.keywords)
  draft.setTitle(data.title.main, data.title.variants)
  draft.setBullets(data.bullets)
  draft.setAPlus(data.aplus)
}

function genOne(mod: string) {
  // 未载入产品 → 拦截，提示先载入（与其他 Agent 一致）
  if (draft.sourceMode !== 'product') {
    message.warning('请先从顶部「载入产品」选定商品，再生成文案')
    return
  }
  genLoading.value = mod
  const data = genAll(genCtx.value)
  setTimeout(() => {
    if (mod === 'keywords') draft.setKeywords(data.keywords)
    else if (mod === 'title') draft.setTitle(data.title.main, data.title.variants)
    else if (mod === 'bullets') draft.setBullets(data.bullets)
    else if (mod === 'aplus') draft.setAPlus(data.aplus)
    genLoading.value = null
    message.success('已生成，可直接修改')
  }, 600)
}

function genAllModules() {
  // 未载入产品 → 拦截，提示先载入
  if (draft.sourceMode !== 'product') {
    message.warning('请先从顶部「载入产品」选定商品，再生成文案')
    return
  }
  allLoading.value = true
  setTimeout(() => {
    applyGenerated(genAll(genCtx.value))
    allLoading.value = false
    message.success('四个模块已全部生成')
  }, 900)
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
  padding: 10px 12px 8px;
  border-bottom: 1px solid var(--border-base);
}

.lb-prod {
  display: flex;
  gap: 8px;
  align-items: center;
}
.lb-prod-icon { font-size: 18px; }
.lb-prod-main { min-width: 0; flex: 1; }
.lb-prod-name {
  font-size: 13px;
  font-weight: 600;
  color: var(--text-primary);
  white-space: nowrap;
  overflow: hidden;
  text-overflow: ellipsis;
}
.lb-prod-sub { font-size: 11px; color: var(--text-tertiary); margin-top: 2px; }
.lb-prod-asin { font-family: monospace; font-size: 11px; color: var(--primary); margin-right: 6px; }
.mini-tag { transform: scale(0.85); margin-left: 4px; }

.lb-tabs {
  display: flex;
  gap: 6px;
  margin-top: 8px;
}
.lb-tab {
  position: relative;
  display: flex;
  align-items: center;
  gap: 4px;
  padding: 5px 14px;
  font-size: 12px;
  border: 1px solid var(--border-base);
  border-radius: 6px;
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
.lb-tab-icon { font-size: 12px; }
.lb-dot {
  width: 5px;
  height: 5px;
  border-radius: 50%;
  background: #52c41a;
}
.lb-tab.active .lb-dot { background: #fff; }

/* 内容页容器 */
.lb-pane {
  flex: 1;
  min-height: 0;
  overflow-y: auto;
  padding: 12px;
}
.lb-pane-single {
  display: flex;
  flex-direction: column;
}
.lb-pane-all {
  display: flex;
  flex-direction: column;
  gap: 20px;
  scroll-behavior: smooth;
}

/* 文案模式的模块卡片 */
.lb-section {
  display: flex;
  flex-direction: column;
  gap: 10px;
  padding: 12px;
  border: 1px solid var(--border-base);
  border-radius: 8px;
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
  gap: 8px;
  padding: 8px 12px;
  border-top: 1px solid var(--border-base);
}
</style>
