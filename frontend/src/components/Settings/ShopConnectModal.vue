<!--
  店铺平台连接弹窗（★ 第 318 轮）。

  ★★★ 为什么只有一个组件（而不是每个平台一个）

    表单长什么样**由后端下发**（`GET /stores/{id}/connect/schema` 的 `spec.fields`），
    本组件只认识 `CredentialField` 这个结构，不认识 `amazon` / `shopee`：
    加平台 = 后端加几条声明，**本文件零改动**。
    一旦这里出现 `if (platform === 'amazon')`，那份「每个平台写一套」就开始了。

  ★★★ 敏感字段「留空」的语义（别想当然）

    已配置的敏感字段回显是 `••••••`（后端绝不回明文），用户**必须重新填写**
    才能真正改它 —— 前端不会、也无法把掩码提交回去。
    留空提交会得到后端的「缺少必填字段」400，这是**有意的**：
    本项目不做「留空即保持原值」的部分更新，因为那会让新旧凭据静默混用
    （旧 client_secret + 新 refresh_token ⇒ 平台侧签名/授权对不上，
      而现场离「哪几个值是新填的」已经很远）。

  ★ 非敏感字段相反：已配置时回显原值并**沿用**，避免用户不填就把
    `region` 之类静默改回默认值。
-->
<template>
  <a-modal
    :open="open"
    :width="WINDOW_W.md"
    :title="title"
    :confirm-loading="submitting"
    :ok-text="schema?.verify_supported === false ? '保存凭据' : '连接并验证'"
    cancel-text="取消"
    @ok="handleSubmit"
    @cancel="handleCancel"
  >
    <a-spin :spinning="loading">
      <!-- ===== 加载失败（平台未登记 / 凭据存储异常）===== -->
      <a-alert
        v-if="loadError"
        type="warning"
        show-icon
        :message="loadError"
        style="margin-bottom: 12px"
      >
        <template
          v-if="supportedPlatforms.length"
          #description
        >
          当前支持连接的平台：{{ supportedPlatforms.join(' / ') }}
        </template>
      </a-alert>

      <template v-if="schema && !loadError">
        <!-- ===== 平台说明 ===== -->
        <a-alert
          v-if="schema.verify_supported === false"
          type="info"
          show-icon
          style="margin-bottom: 12px"
          message="本平台暂未接入自动校验"
          description="凭据会加密保存，但不会标记为「已验证」—— 列表里会显示「已配置（未验证）」。"
        />
        <div
          v-if="schema.docs_url"
          class="docs-line"
        >
          <a
            :href="schema.docs_url"
            target="_blank"
            rel="noopener"
          >
            去哪拿这些凭据？官方文档
          </a>
        </div>
        <ul
          v-if="schema.notes.length"
          class="notes"
        >
          <li
            v-for="(n, i) in schema.notes"
            :key="i"
          >
            {{ n }}
          </li>
        </ul>

        <!-- ===== 通用表单：三支控件吃下全部平台 ===== -->
        <a-form
          layout="vertical"
          style="margin-top: 8px"
        >
          <a-form-item
            v-for="f in schema.fields"
            :key="f.key"
            :required="f.required"
          >
            <template #label>
              <span>{{ f.label }}</span>
              <a-tag
                v-if="isConfigured(f.key)"
                color="blue"
                style="margin-left: 6px"
              >
                已配置
              </a-tag>
            </template>

            <a-select
              v-if="f.type === 'select'"
              v-model:value="form[f.key]"
              :options="f.options"
              :placeholder="f.placeholder || '请选择'"
            />
            <a-input-password
              v-else-if="f.type === 'password'"
              v-model:value="form[f.key]"
              :placeholder="placeholderFor(f)"
              autocomplete="new-password"
            />
            <a-input
              v-else
              v-model:value="form[f.key]"
              :placeholder="f.placeholder"
              allow-clear
            />

            <div
              v-if="f.help"
              class="field-help"
            >
              {{ f.help }}
            </div>
          </a-form-item>
        </a-form>

        <!-- ===== 验证失败的逐步骤明细 ===== -->
        <a-alert
          v-if="failure"
          type="error"
          show-icon
          :message="failure.message"
          style="margin-top: 4px"
        >
          <template
            v-if="failure.checks.length"
            #description
          >
            <div
              v-for="(c, i) in failure.checks"
              :key="i"
              class="check-line"
            >
              <span :class="c.ok ? 'ok' : 'bad'">{{ c.ok ? '✓' : '✗' }}</span>
              <strong>{{ c.name }}</strong>
              <span v-if="c.message">：{{ c.message }}</span>
            </div>
          </template>
        </a-alert>
      </template>
    </a-spin>
  </a-modal>
</template>

<script setup lang="ts">
import { computed, reactive, ref, watch } from 'vue'
import { message } from 'ant-design-vue'
import { WINDOW_W } from '@/config/layout'
import {
  connectPlatform,
  fetchConnectSchemas,
  fetchStoreConnectSpec,
  type CredentialField,
  type Store,
  type StoreConnectResult,
  type StoreConnectSpec,
  type VerifyCheck,
} from '@/api/stores'

const props = defineProps<{
  open: boolean
  shop: Store | null
}>()

const emit = defineEmits<{
  (e: 'update:open', v: boolean): void
  /** 连接动作完成（凭据已保存）—— 父组件据此刷新列表 */
  (e: 'connected', r: StoreConnectResult): void
}>()

const loading = ref(false)
const submitting = ref(false)
const spec = ref<StoreConnectSpec | null>(null)
const loadError = ref('')
const supportedPlatforms = ref<string[]>([])
const failure = ref<{ message: string; checks: VerifyCheck[] } | null>(null)
const form = reactive<Record<string, string>>({})

const schema = computed(() => spec.value?.spec ?? null)
const title = computed(() =>
  props.shop ? `连接平台 · ${props.shop.name}` : '连接平台',
)

const isConfigured = (key: string) => !!spec.value?.configured?.[key]

/**
 * 敏感字段的占位提示。
 *
 * ★ 已配置时**必须**明确告诉用户「得重填」：输入框是空的（后端不回明文），
 *   而用户在列表里刚看到「已配置」，很容易以为这里也会自动带出来。
 */
function placeholderFor(f: CredentialField): string {
  if (f.secret && isConfigured(f.key)) return '已配置 · 重新填写以更新'
  return f.placeholder || ''
}

function detailOf(err: any): string {
  const d = err?.response?.data?.detail
  if (typeof d === 'string') return d
  if (d && typeof d === 'object' && typeof d.message === 'string') return d.message
  return err?.message || '加载失败'
}

async function load() {
  if (!props.shop) return
  loading.value = true
  loadError.value = ''
  failure.value = null
  spec.value = null
  supportedPlatforms.value = []
  Object.keys(form).forEach((k) => delete form[k])

  try {
    const s = await fetchStoreConnectSpec(props.shop.id)
    spec.value = s
    // 预填：非敏感字段沿用回显原值；敏感字段一律留空（后端不回明文）
    for (const f of s.spec.fields) {
      const echo = s.values?.[f.key]
      form[f.key] = !f.secret && echo != null ? String(echo) : ''
    }
  } catch (err: any) {
    loadError.value = detailOf(err)
    // 错误路径的增强：如果这家店的平台压根没登记连接器，
    // 把「当前支持哪些平台」直接摆出来，用户不必去猜 / 翻文档。
    try {
      const all = await fetchConnectSchemas()
      supportedPlatforms.value = all.map((x) => x.display_name || x.platform)
    } catch {
      /* 兜底失败就只显示原始错误 */
    }
  } finally {
    loading.value = false
  }
}

watch(() => props.open, (v) => { if (v) load() })

/**
 * 组装提交体。
 *
 * ★ 三条规则，每条都对应一个真实的坏结果：
 *   ① 敏感字段留空 ⇒ **不提交**（详见文件头注释：本项目不做部分更新）；
 *   ② 非敏感字段留空但**库里已有** ⇒ 沿用回显原值（否则 region 会被静默改回默认）；
 *   ③ 非敏感字段留空且库里没有 ⇒ 用后端声明的 default（如 us-east-1 / 生产）。
 */
function buildPayload(): Record<string, string> {
  const out: Record<string, string> = {}
  for (const f of schema.value?.fields ?? []) {
    const v = (form[f.key] ?? '').toString().trim()
    if (v) { out[f.key] = v; continue }
    if (f.secret) continue
    const echo = spec.value?.values?.[f.key]
    if (isConfigured(f.key) && echo != null) out[f.key] = String(echo)
    else if (f.default) out[f.key] = f.default
  }
  return out
}

async function handleSubmit() {
  if (!props.shop || !schema.value) return
  submitting.value = true
  failure.value = null
  try {
    const r = await connectPlatform(props.shop.id, buildPayload())
    if (r.verify?.ok) {
      message.success(r.message || '连接成功')
    } else {
      // unreachable / unsupported：凭据**已保存**，只是没被标记「已验证」。
      // 这里刻意用 warning 而不是 error —— 报错会让用户以为白填了。
      message.warning(r.message || '凭据已保存，但未能完成验证')
    }
    emit('connected', r)
    emit('update:open', false)
  } catch (err: any) {
    const d = err?.response?.data?.detail
    if (d && typeof d === 'object' && Array.isArray(d.checks)) {
      // 凭据被平台明确拒绝 ⇒ 留在弹窗里，把「哪一步断了」摊开
      failure.value = { message: d.message || '凭据未通过平台校验', checks: d.checks }
      return
    }
    const text = detailOf(err)
    if (err?.response?.status === 400 && typeof d === 'string') {
      message.error(text + '（已配置的字段需要一并提交，本项目不做部分更新）')
    } else {
      message.error(text)
    }
  } finally {
    submitting.value = false
  }
}

function handleCancel() {
  emit('update:open', false)
}
</script>

<style scoped>
.docs-line {
  margin-bottom: 6px;
  font-size: 13px;
}
.notes {
  margin: 0 0 4px 0;
  padding-left: 18px;
  font-size: 12px;
  color: var(--text-secondary, #8c8c8c);
}
.notes li {
  margin-bottom: 2px;
}
.field-help {
  margin-top: 4px;
  font-size: 12px;
  color: var(--text-secondary, #8c8c8c);
}
.check-line {
  font-size: 12px;
  line-height: 1.7;
}
.check-line .ok {
  color: #52c41a;
  margin-right: 4px;
}
.check-line .bad {
  color: #ff4d4f;
  margin-right: 4px;
}
</style>
