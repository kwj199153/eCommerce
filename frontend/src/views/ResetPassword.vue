<template>
  <div class="auth-page">
    <div class="auth-card">
      <div class="brand">
        <h1>重置密码</h1>
        <p v-if="!done">设置一个新密码，然后用它重新登录</p>
      </div>

      <!-- ===== 成功态 ===== -->
      <a-result
        v-if="done"
        status="success"
        title="密码已重置"
        :sub-title="doneMessage"
      >
        <template #extra>
          <a-button type="primary" size="large" @click="goLogin">用新密码登录</a-button>
        </template>
      </a-result>

      <!-- ===== 表单态 ===== -->
      <template v-else>
        <!--
          ★ 失败信息用**常驻** alert 而不是 toast。
            「重置链接无效或已过期，请重新申请」这句话如果只弹 3 秒就没了，
            用户回到这个页面时会以为"是不是我刚才点错了" —— 而他手里那条
            链接已经**永久**作废了，必须留在页面上告诉他下一步去哪。
        -->
        <a-alert
          v-if="errorText"
          type="error"
          show-icon
          :message="errorText"
          class="auth-alert"
        />

        <!--
          ★ 降级路径的承接点。
            后端 `email_tokens.py::_link()` 在**未配 `PUBLIC_SITE_URL`** 时返回空串，
            邮件正文随之降级为「请在应用内粘贴下面这串代码完成操作」。
            在此之前，前端**没有任何界面能接收这串代码** —— 那句话指向一个不存在的地方。
        -->
        <a-alert
          v-if="!hasLinkToken"
          type="info"
          show-icon
          class="auth-alert"
          message="这条链接里没有重置代码"
          description="请把邮件里那串代码粘贴到下方；若邮件已过期，回登录页重新申请一封。"
        />

        <a-form layout="vertical" class="auth-form" @finish="submit">
          <a-form-item v-if="!hasLinkToken" label="重置代码">
            <a-input
              v-model:value="typedToken"
              placeholder="粘贴邮件里的那串代码"
              size="large"
              allow-clear
            />
          </a-form-item>

          <a-form-item label="新密码">
            <a-input-password
              v-model:value="form.password"
              placeholder="至少 6 位"
              size="large"
            />
          </a-form-item>

          <a-form-item label="确认新密码">
            <a-input-password
              v-model:value="form.confirm"
              placeholder="再次输入新密码"
              size="large"
              @press-enter="submit"
            />
          </a-form-item>

          <a-button
            type="primary"
            html-type="submit"
            block
            size="large"
            :loading="submitting"
          >
            重置密码
          </a-button>
        </a-form>

        <p class="foot">
          <a-button type="link" size="small" @click="goLogin">返回登录</a-button>
          <span class="foot-sep" />
          <a-button type="link" size="small" @click="goForgot">重新申请一封</a-button>
        </p>
      </template>
    </div>
  </div>
</template>

<script setup lang="ts">
/**
 * 重置密码落地页（台账 #1152）
 *
 * ============================================================================
 * ★ 这个页面的存在理由：邮件链接此前**指向一个不存在的路由**
 * ============================================================================
 * `core/identity/email_tokens.py` 里 `send_reset_email()` 发出的链接是
 *   `_link("/reset-password", raw)` ⇒ `{PUBLIC_SITE_URL}/reset-password?token=…`
 * 而 `router/index.ts` 只有 6 条路由，**没有 `/reset-password`**。
 * ⇒ 用户在邮箱里点「重置密码」，浏览器打开的是**空白页**。
 *
 * ★ 为什么必须 `requiresAuth: false`（见 router 里的路由表）：
 *   点邮件的时候用户很可能**根本没登录**（这本来就是"登不上才用"的功能）。
 *
 * ============================================================================
 * ★ 三条与后端一一对应的行为约定
 * ============================================================================
 *  ① **不在前端复述后端话术**。`/reset-password` 的失败文案
 *     （`_RESET_INVALID_DETAIL`）由后端给定，本页只负责把它显示出来；
 *     前端再写一份，早晚会和后端分叉。
 *  ② **成功后不自动登录**。后端刻意如此（重置密码往往是"账号可能已失窃"），
 *     所以这里只引导去登录页，不替用户做登录这件事。
 *  ③ **密码下限取 6 位**，与后端 `Field(..., min_length=6)` 及注册表单一致。
 *     取 8 会造成"前端拒绝了一个后端本会接受的值"——
 *     这类"前端比后端更严"的错配，用户看到的是"明明能用的密码说我不合法"。
 */
import { computed, onMounted, reactive, ref } from 'vue'
import { useRoute, useRouter } from 'vue-router'

import { resetPassword } from '@/api/auth'

const route = useRoute()
const router = useRouter()

/** 邮件链接带过来的 token（`?token=…`） */
const linkToken = ref('')
/** 手输/粘贴的 token（链接降级路径，见模板里的说明） */
const typedToken = ref('')

const form = reactive({ password: '', confirm: '' })
const submitting = ref(false)
/** 常驻错误面（不是 toast） */
const errorText = ref('')
const done = ref(false)
const doneMessage = ref('')

const hasLinkToken = computed(() => linkToken.value.length > 0)
const token = computed(() => linkToken.value || typedToken.value.trim())

onMounted(() => {
  const raw = route.query.token
  linkToken.value = typeof raw === 'string' ? raw.trim() : ''
})

/** 从 axios 错误里取后端 detail（拿不到就返回空串，由调用点给兜底文案） */
function backendDetail(err: unknown): string {
  const e = err as { response?: { data?: { detail?: unknown } } }
  const d = e?.response?.data?.detail
  return typeof d === 'string' ? d : ''
}

async function submit() {
  errorText.value = ''

  if (!token.value) {
    errorText.value = '缺少重置代码：请粘贴邮件里那串代码，或回登录页重新申请一封'
    return
  }
  if (!form.password) {
    errorText.value = '请填写新密码'
    return
  }
  if (form.password.length < 6) {
    errorText.value = '新密码至少 6 位'
    return
  }
  if (form.password !== form.confirm) {
    errorText.value = '两次输入的新密码不一致'
    return
  }

  submitting.value = true
  try {
    // ★ silentError：本页自己有常驻错误面，不能让拦截器再弹一次
    const res = await resetPassword(token.value, form.password, { silentError: true })
    done.value = true
    doneMessage.value = res?.message || '请用新密码登录'
    // ★ 不清空 token：万一用户想核对，页面重绘前它仍在；真正的失效由后端保证（一次性 token）
  } catch (err) {
    errorText.value = backendDetail(err) || '重置失败，请稍后重试'
  } finally {
    submitting.value = false
  }
}

function goLogin() {
  router.replace({ name: 'Login' })
}

/**
 * 「重新申请一封」——回到登录页并**直接把忘记密码弹窗打开**。
 *
 * ★ 用 query 而不是 router state：state 在刷新后丢失，且用户可能复制链接。
 *   Login.vue 读 `?forgot=1` 自动展开。
 */
function goForgot() {
  router.replace({ name: 'Login', query: { forgot: '1' } })
}
</script>

<style scoped>
/* ★ 只引用 presets.ts 里**确实存在**的主题变量（见 scripts/check-theme-var-refs.py）；
   几何尺度（间距 / 圆角）用 px，避免误用不存在的 --space-32 一类名字而静默失效。 */
.auth-page {
  min-height: 100vh;
  display: flex;
  align-items: center;
  justify-content: center;
  padding: 24px;
  background: var(--bg-base);
}

.auth-card {
  width: 100%;
  max-width: 420px;
  padding: 32px;
  border-radius: 12px;
  border: 1px solid var(--border-base);
  background: var(--bg-elevated);
}

.brand h1 {
  margin: 0 0 8px;
  font-size: 22px;
  font-weight: 600;
  color: var(--text-primary);
}

.brand p {
  margin: 0 0 20px;
  font-size: 13px;
  color: var(--text-secondary);
}

.auth-alert {
  margin-bottom: 16px;
  text-align: left;
}

.auth-form {
  margin-top: 4px;
}

.foot {
  margin: 12px 0 0;
  text-align: center;
}

.foot-sep {
  display: inline-block;
  width: 1px;
  height: 12px;
  margin: 0 8px;
  vertical-align: middle;
  background: var(--border-base);
}
</style>
