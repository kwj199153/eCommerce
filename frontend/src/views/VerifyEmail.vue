<template>
  <div class="auth-page">
    <div class="auth-card">
      <!-- ===== 校验中 ===== -->
      <a-spin
        v-if="phase === 'verifying'"
        size="large"
        tip="正在验证邮箱…"
      >
        <div class="spin-holder" />
      </a-spin>

      <!-- ===== 成功 ===== -->
      <a-result
        v-else-if="phase === 'ok'"
        status="success"
        title="邮箱已验证"
        :sub-title="message || '该邮箱已通过验证'"
      >
        <template #extra>
          <a-button
            type="primary"
            size="large"
            @click="goNext"
          >
            {{ userStore.isLoggedIn ? '返回工作台' : '去登录' }}
          </a-button>
        </template>
      </a-result>

      <!-- ===== 失败 / 缺 token ===== -->
      <template v-else>
        <div class="brand">
          <h1>邮箱验证</h1>
          <p>点开的是注册时那封验证邮件里的链接</p>
        </div>

        <a-alert
          type="error"
          show-icon
          class="auth-alert"
          :message="message || '验证链接无效或已过期'"
          :description="failHint"
        />

        <!--
          ★ 重发按钮只有在**已登录**时才出现。
            后端 `/auth/verify-email/resend` 的收件人来自 `get_current_user`，
            匿名调用会 401 —— 与其给一个必然失败的按钮，不如说清代价与出路。
        -->
        <template v-if="userStore.isLoggedIn">
          <a-button
            type="primary"
            block
            size="large"
            :loading="resending"
            @click="resend"
          >
            重新发送验证邮件
          </a-button>
          <p
            v-if="resendNote"
            class="note"
          >
            {{ resendNote }}
          </p>
        </template>
        <template v-else>
          <a-alert
            type="info"
            show-icon
            class="auth-alert"
            message="登录后才能重发验证邮件"
            description="验证邮件的收件人由服务端从你的登录态里取，所以需要先登录。登录后在「账号设置 → 安全设置」也可以重发。"
          />
          <a-button
            type="primary"
            block
            size="large"
            @click="goLogin"
          >
            去登录
          </a-button>
        </template>

        <p class="foot">
          <a-button
            type="link"
            size="small"
            @click="goLogin"
          >
            返回登录
          </a-button>
        </p>
      </template>
    </div>
  </div>
</template>

<script setup lang="ts">
/**
 * 邮箱验证落地页（台账 #1153）
 *
 * ============================================================================
 * ★ 与 ResetPassword.vue 同源的问题：邮件链接指向一个不存在的路由
 * ============================================================================
 * `core/identity/email_tokens.py::send_verify_email()` 发的链接是
 *   `_link("/verify-email", raw)` ⇒ `{PUBLIC_SITE_URL}/verify-email?token=…`
 * 而 `router/index.ts` 此前**没有 `/verify-email`** ⇒ 点开是**空白页**。
 *
 * ★ 为什么必须 `requiresAuth: false`：
 *   注册后用户**尚未**登录就可能去收信（甚至换个浏览器/手机点开）。
 *
 * ============================================================================
 * ★ 这个页面唯一容易写错的地方：把"没抛异常"当成"发出去了"
 * ============================================================================
 * 后端 `/auth/verify-email/resend` 即使**发信失败也回 HTTP 200**
 * （"你已登录"这件事成功了，失败的是邮件），结果在 `email_sent` 里。
 * ⇒ 只看 `await` 没抛就弹"已发送"，等于对用户说谎 ——
 *   他会去收件箱白等，而系统里其实早就记了一条 ERROR。
 *   所以下面 resend() 必须读 `email_sent` 再决定说什么。
 */
import { computed, onMounted, ref } from 'vue'
import { useRoute, useRouter } from 'vue-router'

import { resendVerifyEmail, verifyEmail } from '@/api/auth'
import { useUserStore } from '@/stores/user'

const route = useRoute()
const router = useRouter()
const userStore = useUserStore()

type Phase = 'verifying' | 'ok' | 'failed'
const phase = ref<Phase>('verifying')
/** 展示给用户的一句话（成功来自后端 message；失败来自后端 detail 或前端兜底） */
const message = ref('')

const resending = ref(false)
const resendNote = ref('')

const failHint = computed(() =>
  '验证链接是一次性的，用过或超过有效期都会失效。重新发送一封即可。'
)

onMounted(async () => {
  const raw = route.query.token
  const token = typeof raw === 'string' ? raw.trim() : ''

  if (!token) {
    phase.value = 'failed'
    message.value = '这条链接里没有验证代码'
    return
  }

  try {
    // ★ silentError：本页自己有常驻错误面
    const res = await verifyEmail(token, { silentError: true })
    phase.value = 'ok'
    message.value = res?.message || ''
    // ★ 若此刻处于登录态，把 /auth/me 的缓存拉一次 ——
    //   否则界面上会一直显示「邮箱未验证」，和后端状态不一致。
    if (userStore.isLoggedIn) await userStore.fetchUserInfo()
  } catch (err) {
    const e = err as { response?: { data?: { detail?: unknown } } }
    const d = e?.response?.data?.detail
    phase.value = 'failed'
    message.value = typeof d === 'string' ? d : ''
  }
})

async function resend() {
  resending.value = true
  resendNote.value = ''
  try {
    const res = await resendVerifyEmail({ silentError: true })
    // ★ 必须读 email_sent：200 不代表信发出去了
    if (res?.email_sent) {
      resendNote.value = '已重新发送，请查收（含垃圾邮件箱）。'
      message.value = res?.message || message.value
    } else if (res?.email_sent_already) {
      resendNote.value = '这个邮箱已经验证过了，无需重复发送。'
    } else {
      resendNote.value = res?.message || '发送失败：邮件服务当前不可用，请联系管理员。'
    }
  } catch (err) {
    const e = err as { response?: { data?: { detail?: unknown } } }
    const d = e?.response?.data?.detail
    resendNote.value = typeof d === 'string' ? d : '发送失败，请稍后重试。'
  } finally {
    resending.value = false
  }
}

function goLogin() {
  router.replace({ name: 'Login' })
}

function goNext() {
  router.replace(userStore.isLoggedIn ? { name: 'Workspace' } : { name: 'Login' })
}
</script>

<style scoped>
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

.spin-holder {
  height: 120px;
}

.note {
  margin: 12px 0 0;
  font-size: 13px;
  color: var(--text-secondary);
}

.foot {
  margin: 12px 0 0;
  text-align: center;
}
</style>
