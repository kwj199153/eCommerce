<template>
  <!-- 确认框：批准 / 驳回 / 核准 / 登记回执都是人的不可逆动作 -->
  <a-modal
    v-model:open="confirmOpen"
    :width="WINDOW_W.md"
    :title="confirmTitle"
    :confirm-loading="acting"
    @ok="emit('act')"
    @cancel="confirmOpen = false"
  >
    <p class="rd-confirm-text">
      {{ confirmText }}
    </p>
    <a-textarea
      v-if="pendingAct === 'reject'"
      v-model:value="rejectNotes"
      :rows="3"
      placeholder="驳回原因（可选，会追加进处置备注）"
    />
    <template v-if="pendingAct === 'receipt'">
      <a-input
        v-model:value="receiptRef"
        class="rd-receipt-input"
        placeholder="平台侧凭证号：退款单号 / 券码 / case id（拿不到就留空）"
      />
      <a-textarea
        v-model:value="receiptNote"
        :rows="3"
        placeholder="回执备注：做了什么、在哪做的（可选）"
      />
    </template>
  </a-modal>

  <!-- ============================ 补偿规则编辑器（第 304 轮后半）============================ -->
  <!-- ★ 这是「要调金额请去改规则表」那句负指令缺失的落点：新建 / 编辑一条规则。
       `code` 在编辑态只读（它是主键的一部分，后端也不接受改）。 -->
  <a-modal
    v-model:open="ruleEditorOpen"
    :width="WINDOW_W.md"
    :title="editingRule ? `编辑补偿规则 · ${editingRule.code}` : '新建补偿规则'"
    :confirm-loading="ruleEditorLoading"
    @ok="emit('rule-ok')"
    @cancel="ruleEditorOpen = false"
  >
    <div class="rd-rule-form">
      <div class="rd-rule-field">
        <span class="rd-rule-label">规则代号（code）</span>
        <a-input
          v-model:value="ruleForm.code"
          :disabled="!!editingRule"
          placeholder="小写字母 / 数字 / 连字符，如 packaging-damage-standard"
        />
      </div>
      <div class="rd-rule-field">
        <span class="rd-rule-label">名称</span>
        <a-input
          v-model:value="ruleForm.name"
          placeholder="留空用 code"
        />
      </div>
      <div class="rd-rule-field">
        <span class="rd-rule-label">针对归因</span>
        <a-select
          v-model:value="ruleForm.cause"
          :options="CAUSE_OPTIONS"
          style="width: 100%"
        />
      </div>
      <div class="rd-rule-field">
        <span class="rd-rule-label">优先级（小者先）</span>
        <a-input-number
          v-model:value="ruleForm.priority"
          :min="0"
          style="width: 100%"
        />
      </div>
      <div class="rd-rule-field">
        <span class="rd-rule-label">命中条件</span>
        <div class="rd-rule-cond-grid">
          <span class="rd-rule-cond-item">
            星级 ≤ <a-input-number
              v-model:value="ruleForm.max_rating"
              :min="1"
              :max="5"
              placeholder="不限"
            />
          </span>
          <span class="rd-rule-cond-item">
            延迟 ≥ <a-input-number
              v-model:value="ruleForm.min_delay_days"
              :min="0"
              placeholder="不限"
            /> 天
          </span>
          <span class="rd-rule-cond-item">
            <a-checkbox v-model:checked="ruleForm.verified_purchase">仅已购</a-checkbox>
          </span>
        </div>
      </div>
      <div class="rd-rule-field">
        <span class="rd-rule-label">补偿方案</span>
        <div class="rd-rule-action-grid">
          <a-select
            v-model:value="ruleForm.action_type"
            :options="ACTION_TYPE_OPTIONS"
            style="width: 160px"
          />
          <a-input-number
            v-if="ruleForm.action_type !== 'none'"
            v-model:value="ruleForm.amount"
            :min="0"
            placeholder="金额"
          />
          <a-select
            v-if="ruleForm.action_type !== 'none'"
            v-model:value="ruleForm.currency"
            :options="CURRENCY_OPTIONS"
            style="width: 100px"
          />
        </div>
      </div>
      <div class="rd-rule-field">
        <span class="rd-rule-label">单笔硬上限（≤0 未设）</span>
        <a-input-number
          v-model:value="ruleForm.budget_cap"
          :min="0"
          style="width: 100%"
        />
      </div>
      <div class="rd-rule-field">
        <span class="rd-rule-label">启用</span>
        <a-switch v-model:checked="ruleForm.enabled" />
      </div>
      <div class="rd-rule-field">
        <span class="rd-rule-label">备注</span>
        <a-textarea
          v-model:value="ruleForm.notes"
          :rows="2"
          placeholder="可选"
        />
      </div>
      <div class="rd-tip">
        ★ 金额由这里唯一算出：处置草稿按「归因 + 命中规则」现算，改了这里下次生成才生效。
        条件键只认 <code>max_rating</code> / <code>min_delay_days</code> / <code>verified_purchase</code>，
        写别的键会静默失效（后端会拒掉）。
      </div>
    </div>
  </a-modal>

  <!-- ============================ 补归因抽屉（第 304 轮后半）============================ -->
  <!-- ★ 判不出归因（unknown）的差评永远进不了处置链；这里给手工出口。
       `primary_cause` 不接受 unknown（那不是可选项）。 -->
  <a-modal
    v-model:open="attrOpen"
    :width="WINDOW_W.md"
    title="补归因 · 手工指定成因"
    :confirm-loading="attrLoading"
    @ok="emit('attr-ok')"
    @cancel="attrOpen = false"
  >
    <div
      v-if="attrTarget"
      class="rd-attr-form"
    >
      <div class="rd-body-full">
        {{ attrTarget.body || '（无正文）' }}
      </div>
      <div class="rd-rule-field">
        <span class="rd-rule-label">主要成因</span>
        <a-select
          v-model:value="attrCause"
          :options="CAUSE_OPTIONS"
          style="width: 100%"
        />
      </div>
      <div class="rd-rule-field">
        <span class="rd-rule-label">依据 / 备注</span>
        <a-textarea
          v-model:value="attrNotes"
          :rows="3"
          placeholder="例如：买家说晚到了 5 天，属物流延迟"
        />
      </div>
      <div class="rd-tip">
        ★ 落 <code>method=manual</code>：自动同步**不会**把它冲回「未判定」。
        补完后这条差评就会进入处置链（点「生成待处置」或单条生成草稿）。
      </div>
    </div>
  </a-modal>
</template>

<script setup lang="ts">
/**
 * 差评工作台「弹窗层」（第 347 轮第五刀，从 `ReviewDeskConfig.vue` 拆出）。
 *
 * ★ 为什么这三块能搬、而抽屉 / 列表不能：
 *   六道门禁把一批**调用点**钉死在 `ReviewDeskConfig.vue` ——
 *     · 风险链路（`showRiskEvidence` / `riskListKey` / `clearRisk` / `listKeyOf`）
 *       → `check-review-risk-view.cjs`
 *     · 对话出口（`window.dispatchEvent` 恰好 1 处 + `rd-act-chat` / `rd-item-chat`
 *       / `sendToChat` 锚点）→ `check-review-chat-entries.cjs`
 *     · 通道真源（`CHANNEL_META` / `ALL_CHANNELS`）
 *       → `check-disposition-execution-honesty.cjs`
 *   它们全在**抽屉与列表**里 ⇒ 不能搬。三个弹窗只消费表单态，可以搬。
 *
 * ★ 写门禁（`check-disposition-write-exit.cjs` C1/C2）要求写 API 的 `.vue` 出口
 *   唯一且在本面板 ⇒ 本组件**不 import 任何 api**，只把「确认」emit 回父组件：
 *     · `act`     → 父侧 `runAct`（批准 / 驳回 / 核准 / 登记回执）
 *     · `rule-ok` → 父侧 `saveRule`
 *     · `attr-ok` → 父侧 `submitAttribution`
 *
 * ★ 双向绑定一律走 `defineModel`，而不是 prop + 手写事件：
 *   实测 `vue/no-mutating-props` 会把 `props.form.code = x` 判为 error（嵌套也判），
 *   而 `defineModel` 的 ref 允许直接改写 ⇒ 表单字段可在子组件内 `v-model`。
 *
 * ★ 样式：`<style scoped src="./rdModals.css">` —— 只搬**本组件用到**的 11 个类，
 *   它们经实测在 `reviewDesk.css` 里**只有弹窗用**，故整体迁走、不留第二份。
 */
import { WINDOW_W } from '@/config/layout'
import type { AttributionCause, CompensationRule, ProductReview } from '@/api/trade'
import { ACTION_TYPE_OPTIONS, CAUSE_OPTIONS, CURRENCY_OPTIONS, type RuleForm } from './reviewDeskVocabulary'

defineProps<{
  /** 确认框标题 / 正文（父组件按 `pendingAct` 算好） */
  confirmTitle: string
  confirmText: string
  /** 当前待确认的动作；'' = 没在确认 */
  pendingAct: 'approve' | 'reject' | 'issue' | 'receipt' | ''
  acting: boolean
  ruleEditorLoading: boolean
  /** null = 新建 */
  editingRule: CompensationRule | null
  attrLoading: boolean
  attrTarget: ProductReview | null
}>()

const emit = defineEmits<{
  (e: 'act'): void
  (e: 'rule-ok'): void
  (e: 'attr-ok'): void
}>()

// 双向绑定（父组件对应 `v-model:xxx`）
const confirmOpen = defineModel<boolean>('confirmOpen', { required: true })
const rejectNotes = defineModel<string>('rejectNotes', { required: true })
const receiptRef = defineModel<string>('receiptRef', { required: true })
const receiptNote = defineModel<string>('receiptNote', { required: true })
const ruleEditorOpen = defineModel<boolean>('ruleEditorOpen', { required: true })
const ruleForm = defineModel<RuleForm>('ruleForm', { required: true })
const attrOpen = defineModel<boolean>('attrOpen', { required: true })
const attrCause = defineModel<AttributionCause>('attrCause', { required: true })
const attrNotes = defineModel<string>('attrNotes', { required: true })
</script>

<style scoped src="./rdModals.css"></style>
