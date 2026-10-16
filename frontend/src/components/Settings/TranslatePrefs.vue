<template>
  <a-card
    :bordered="false"
    class="translate-prefs"
  >
    <div class="pref-section">
      <h4>翻译</h4>
      <div class="pref-item">
        <div class="pref-text">
          <span class="pref-title">选中文字后自动弹出翻译</span>
          <p class="pref-desc">
            在平台任意页面选中文字即自动翻译并弹出译文（中英文均可）。方向<b>一律译成中文</b>：
            原文已是中文时后端不调用模型，浮层显示「已是中文」并给一个「译为英文」的入口。
            关闭后不再自动弹窗，仍可点击商品标题旁的「译」按钮手动翻译。
          </p>
        </div>
        <a-switch v-model:checked="autoTranslate" />
      </div>

      <div class="pref-item">
        <div class="pref-text">
          <span class="pref-title">鼠标悬停时自动翻译</span>
          <p class="pref-desc">
            <b>默认关闭</b>。打开后鼠标在文字上停住约 0.3 秒即自动翻译并弹出译文 ——
            只对<b>含拉丁字母（英文等）</b>的文字块生效，已经是中文的内容不会被触发，
            鼠标只是扫过也不会弹。正在编辑的输入框内一律不触发，避免与打字打架。
          </p>
        </div>
        <a-switch v-model:checked="hoverTranslate" />
      </div>

      <div class="pref-item">
        <div class="pref-text">
          <span class="pref-title">译文显示方式</span>
          <p class="pref-desc">
            浮层里要不要同时显示原文。<b>双语</b>便于核对有没有翻对；
            <b>仅译文</b>更省地方，适合只看结果。
          </p>
        </div>
        <a-radio-group
          v-model:value="displayModeLocal"
          size="small"
        >
          <a-radio-button value="bilingual">
            双语
          </a-radio-button>
          <a-radio-button value="target">
            仅译文
          </a-radio-button>
        </a-radio-group>
      </div>

      <!-- ============================================================
           ★ 店铺术语表（第 369 轮 P0）

           为什么这块必须存在：后端的通用惯例（`prompts.py` 第 5 条）覆盖不到
           「本店自己怎么叫」，症状是同一批文案里同一个词两种译法。术语表就是
           给这个洞打补丁 —— 用户在设置页写死 `原文=译文`，划词时随请求带上。

           为什么要有下面那行统计：后端的解析是**刻意宽松**的（非法行静默跳过
           不报错，这是对的 —— 用户的笔误不该升级成故障）。但对设置页来说，
           只靠后端就等于「打错一行没有任何反馈」。所以这里把「实际会被识别成
           几条 / 几行没生效 / 有没有触上限」如实算出来给用户看。
           ============================================================ -->
      <div class="pref-block">
        <span class="pref-title">店铺术语表</span>
        <p class="pref-desc">
          每行一条 <code>原文=译文</code>，划词翻译时优先于通用惯例
          （例：<code>Noise Cancelling=主动降噪</code>）；以 <code>#</code> 开头的行是注释。
          <b>按店铺分别保存</b> —— 切换店铺后，这里会跟着换成那一家店的表。
        </p>
        <a-textarea
          v-model:value="glossaryDraft"
          :rows="6"
          class="glossary-input"
          placeholder="Noise Cancelling=主动降噪&#10;Gift Box＝礼盒装"
        />
        <p
          class="glossary-stat"
          :class="{ 'is-warn': glossaryNeedsAttention }"
        >
          {{ glossaryStatText }}
        </p>
        <!-- ★ 失败路径必须回写界面：术语表是「改完立即落本机」，写失败还装作存上了，
             下次进来就是一场无声的丢失。 -->
        <p
          v-if="glossarySaveFailed"
          class="glossary-stat is-warn"
        >
          本机存储不可用，这次的修改不会被保留（隐私模式或被策略禁用时会这样）。
        </p>
      </div>
    </div>
  </a-card>
</template>

<script setup lang="ts">
/**
 * 交互偏好 · 翻译分区（第 369 轮 P0 建，第 370 轮从 `views/Settings.vue` 抽出）
 *
 * 抽出来的直接原因是体量棘轮：`Settings.vue` 已越过 800 行阈值并被冻结在 1315 行，
 * P0 加术语表后涨到 1475 ⇒ `test_source_size_ratchet.py` 的 R2「恶化」转红。
 * 处置**不抬棘轮值**（那是把悄悄长大祝福成基线），而是把这块整段外迁 ——
 * 顺带给 P1（悬停翻译 / 双语切换）与 P2（设置页重排）一个真正的落点。
 *
 * 边界：本组件只负责「翻译」这一个分区，不含通知偏好（那是 Tab 3 的
 * `.notification-card` / `.notify-item`，仍留在 Settings.vue）。
 */
import { ref, computed, watch } from 'vue'
import { useShopStore } from '@/stores/shop'
import {
  useSelectionTranslate,
  type TranslateDisplayMode,
} from '@/composables/useSelectionTranslate'
// 店铺术语表：解析/存取/预览口径的唯一真源（纯叶子，与后端 glossary.py 同口径）
import {
  MAX_GLOSSARY_CHARS,
  MAX_GLOSSARY_ENTRIES,
  loadGlossary,
  saveGlossary,
  summarizeGlossary,
} from '@/utils/glossary'

const shopStore = useShopStore()

// 开关状态是模块级单例（在 useSelectionTranslate 里），浮层组件读的是同一份，
// 所以这里改完立即生效，不需要「保存」按钮。
const {
  autoEnabled,
  setAutoEnabled,
  hoverEnabled,
  setHoverEnabled,
  displayMode,
  setDisplayMode,
} = useSelectionTranslate()

/**
 * 不直接把 autoEnabled 绑到 a-switch：必须走 setAutoEnabled，
 * 否则「关掉时收起已开浮层」和「写入 localStorage」两步都会丢。
 */
const autoTranslate = computed({
  get: () => autoEnabled.value,
  set: (v: boolean) => setAutoEnabled(v),
})

/**
 * 悬停开关。与上面同口径：**必须走 setter** —— `setHoverEnabled` 除了写 ref 和
 * localStorage，还要取消已经排上队的那一个待触发定时器（否则「刚关掉又弹一个」）。
 */
const hoverTranslate = computed({
  get: () => hoverEnabled.value,
  set: (v: boolean) => setHoverEnabled(v),
})

/**
 * 译文显示方式（双语 / 仅译文）。
 *
 * 同样只做中继：状态真源在 `useSelectionTranslate`（浮层读的是同一份），
 * 这里自己存一份就会出现「设置页说仅译文、浮层还显示原文」的分叉。
 */
const displayModeLocal = computed<TranslateDisplayMode>({
  get: () => displayMode.value,
  set: (v: TranslateDisplayMode) => setDisplayMode(v),
})

// ====== 店铺术语表（第 369 轮 P0）======
// 存储与解析口径全部住在 `@/utils/glossary`，这里只做「草稿 ↔ 当前店铺」的接线。
// 与上面的开关同口径：**无保存按钮**，改完立即落本机（localStorage 写是同步的、零成本）。
// 但术语表不像开关只有两态 —— 后端的解析是**宽松跳错**的，所以这里必须多给一行读数，
// 否则用户「打错一行没有任何反馈」。
const glossaryDraft = ref('')
const glossarySaveFailed = ref(false)

/**
 * ★ 这里**刻意不显示店铺名**（第 369 轮实测踩到，别顺手加回去）。
 *
 * 原本想在标题下写「当前编辑的是：XX 店」。写完 `check-chat-domain-split.cjs` 就红了 ——
 * 它的 A9 判据要求全前端 `shopStore.currentShop.name` 的消费点**恰好为 1**（第 190 轮裁决）：
 * 本仓数据作用域**只有一层**（`X-Shop-ID → store_id`），多一处读取就等于「给同一层起了第二个
 * 名字」，用户会据此推断出并不存在的层级（历史上复盘写「店铺：X」、广告写「广告账户：X」，
 * 读的却是同一个字段）。
 *
 * 处置是**不绕、不放宽**：把店名从界面上拿掉，改用文案说清「按店铺分别保存、切店铺会跟着切」。
 * 术语表按 `shop_id` 分键是**存储行为**，不需要把店名再渲染一遍。
 * （真要让用户看见归属，该先想清楚怎么把 A9 的语义一并收紧，而不是换一种写法取同一个字段 ——
 *   那正是该判据存在的理由。）
 */

const glossarySummary = computed(() => summarizeGlossary(glossaryDraft.value))

/**
 * 统计文案。刻意把「几行没生效 / 触上限 / 超字数」都说出来 ——
 * 这三件事在后端**全是静默的**（跳过不报错，那是对的），只有在这里才第一次可见。
 */
const glossaryStatText = computed(() => {
  const s = glossarySummary.value
  const parts = [`已识别 ${s.entries.length} 条`]
  if (s.skipped > 0) parts.push(`${s.skipped} 行未生效（格式不完整，或与前面的原文重复）`)
  if (s.capped) parts.push(`已达 ${MAX_GLOSSARY_ENTRIES} 条上限，其后的行不会生效`)
  if (s.oversize) parts.push(`超出 ${MAX_GLOSSARY_CHARS} 字上限，超出部分不会随请求发出`)
  return parts.join('；')
})

/** 是否把统计行标成警示色（有没生效的行 / 触顶 / 超字数） */
const glossaryNeedsAttention = computed(() => {
  const s = glossarySummary.value
  return s.skipped > 0 || s.capped || s.oversize
})

/**
 * 载入「当前店铺」的术语表。
 *
 * ★ `immediate: true`：设置页有抽屉 / 路由两条入口，组件可能在店铺已选好之后才挂载，
 *   不立即跑一次就会读到空草稿（看起来像「术语表丢了」）。
 * ★ 用 `watch` 而不是 `onMounted`：店铺可以在侧栏随时切走，草稿必须跟着切 ——
 *   否则用户在 A 店写的术语表会被写进 B 店的键。
 */
watch(
  () => shopStore.currentShopId,
  (id) => {
    glossaryDraft.value = loadGlossary(id)
    glossarySaveFailed.value = false
  },
  { immediate: true },
)

/**
 * 草稿变化即落本机。
 *
 * ★ 切换店铺时本 watch 会跟着触发一次（草稿刚被换成新店铺的值）。那一次写的是
 *   **新店铺**（`currentShopId` 已是新值）⇒ 把新店铺的值原样写回自己，幂等无害。
 * ★ 写失败必须显式上屏：这是用户的显式操作，回一句「已保存」而实际没存上，
 *   下次进来术语表就没了 —— 典型的静默丢失。
 */
watch(glossaryDraft, (v) => {
  glossarySaveFailed.value = !saveGlossary(shopStore.currentShopId, v)
})
</script>

<style scoped>
/* 本组件自带容器约束：原来靠 Settings.vue 的 `.notification-card`（max-width: 560px），
   抽出来后自己声明一份同名视觉，避免跨文件 `.class` 依赖。 */
.translate-prefs {
  max-width: 560px;
}

.pref-section h4 {
  margin-bottom: var(--space-12);
  font-size: var(--font-size-14);
}

/* 交互偏好 —— 用主题变量，深色模式下也要能读 */
.pref-item {
  display: flex;
  justify-content: space-between;
  align-items: flex-start;
  gap: var(--space-24);
  padding: var(--space-10) 0;
}

.pref-text {
  display: flex;
  flex-direction: column;
  gap: var(--space-4);
}

.pref-title {
  font-size: var(--font-size-14);
}

.pref-desc {
  margin: 0;
  font-size: var(--font-size-12);
  line-height: 1.6;
  color: var(--text-tertiary);
}

.pref-item :deep(.ant-switch) {
  flex: 0 0 auto;
  margin-top: var(--space-2);
}

.pref-item :deep(.ant-radio-group) {
  flex: 0 0 auto;
  margin-top: var(--space-2);
}

/* 多个偏好项连续排列时给分隔线：三行「说明 + 控件」挨在一起会糊成一块 */
.pref-item + .pref-item {
  border-top: 1px solid var(--border-base);
}

/* ---- 店铺术语表（第 369 轮 P0）----
   与上面的开关同属「翻译」分区，但它需要整块宽度放文本框，所以不用 .pref-item
   （那是「左文字 + 右开关」的两栏布局，单元素进去会被挤成窄条）。 */
.pref-block {
  display: flex;
  flex-direction: column;
  gap: var(--space-8);
  margin-top: var(--space-16);
  padding-top: var(--space-16);
  border-top: 1px solid var(--border-base);
}

/* 说明文字里的 `原文=译文` 举例。用等宽字体，让人一眼看出「这不是正文」 */
.pref-block .pref-desc code {
  padding: 0 var(--space-4);
  border-radius: var(--radius-3);
  background: var(--bg-subtle);
  font-family: var(--font-mono);
}

.glossary-input {
  font-family: var(--font-mono);
  font-size: var(--font-size-12);
}

.glossary-stat {
  margin: 0;
  font-size: var(--font-size-12);
  line-height: 1.6;
  color: var(--text-tertiary);
}

/* 「有行没生效 / 触条数上限 / 超字数」—— 这三件事在后端**都是静默的**
   （宽松跳错是刻意设计），所以这里是它们第一次可见的地方，必须显眼。 */
.glossary-stat.is-warn {
  color: var(--warning-strong);
}
</style>
