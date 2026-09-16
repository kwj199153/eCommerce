<template>
  <div class="team-page">
    <div class="team-head">
      <div>
        <h1 class="team-title">团队成员</h1>
        <p class="team-sub">
          账户是「团队」这一层：一个账户下可以有多名成员，成员按角色共享该账户的店铺。
        </p>
      </div>
      <a-space>
        <a-select
          v-if="accounts.length > 0"
          v-model:value="currentAccountId"
          style="min-width: 200px"
          @change="onAccountChange"
        >
          <a-select-option v-for="a in accounts" :key="a.id" :value="a.id">
            {{ a.name }}（{{ roleLabel(a.role) }}）
          </a-select-option>
        </a-select>
        <a-button :disabled="needsLogin" @click="showCreateAccount = true">新建账户</a-button>
      </a-space>
    </div>

    <!-- ★ 未登录态：把**可执行的入口**摆在页面上，而不是只弹一句 toast 就结束。
         账户/成员是身份数据，演示模式的临时身份不适用（后端必然 401），
         所以这里必须直接告诉用户"去哪登录"。 -->
    <a-alert
      v-if="needsLogin"
      type="warning"
      show-icon
      class="team-alert"
      message="需要登录后才能管理团队成员"
      description="账户与成员属于身份数据，必须绑定真实账号。当前是演示模式的临时身份（后端不认），请先登录后再试。"
    />
    <div v-if="needsLogin" class="team-login-row">
      <a-button type="primary" @click="goLogin">去登录</a-button>
      <span class="team-login-hint">登录后会回到本页并重新加载。</span>
    </div>

    <a-spin :spinning="loading">
      <a-empty
        v-if="!loading && accounts.length === 0"
        :description="needsLogin ? '登录后这里会显示你的账户' : '暂无可见账户'"
      />

      <template v-else-if="currentAccount">
        <a-card :bordered="false" class="team-card">
          <a-descriptions :column="4" size="small">
            <a-descriptions-item label="账户名称">
              {{ currentAccount.name }}
            </a-descriptions-item>
            <a-descriptions-item label="我的角色">
              <a-tag :color="roleColor(currentAccount.role)">
                {{ roleLabel(currentAccount.role) }}
              </a-tag>
              <a-tag v-if="currentAccount.is_platform_admin" color="red">平台超管</a-tag>
            </a-descriptions-item>
            <a-descriptions-item label="店铺数">
              {{ currentAccount.store_count }}
            </a-descriptions-item>
            <a-descriptions-item label="成员数">
              {{ currentAccount.member_count }}
            </a-descriptions-item>
          </a-descriptions>
        </a-card>

        <a-card :bordered="false" class="team-card" title="成员列表">
          <template #extra>
            <a-space>
              <a-checkbox v-model:checked="includeRemoved" @change="loadMembers">
                含已移除
              </a-checkbox>
              <a-button
                type="primary"
                :disabled="!canManage"
                @click="openInvite"
              >
                邀请成员
              </a-button>
            </a-space>
          </template>

          <a-alert
            v-if="!canManage"
            type="info"
            show-icon
            message="你的角色不能管理成员"
            description="只有账户所有者与管理员可以邀请、调整或移除成员。"
            style="margin-bottom: 16px"
          />

          <a-table
            :data-source="members"
            :columns="columns"
            :pagination="false"
            row-key="id"
            size="middle"
          >
            <template #bodyCell="{ column, record }">
              <template v-if="column.key === 'member'">
                <div class="member-cell">
                  <strong>{{ record.name || record.email?.split('@')[0] || '成员' }}</strong>
                  <span class="member-email">{{ record.email || '—' }}</span>
                </div>
              </template>

              <template v-else-if="column.key === 'role'">
                <a-select
                  v-if="canManage && !record.is_owner && record.status === 'active'"
                  :value="record.role"
                  size="small"
                  style="min-width: 110px"
                  :loading="busyId === record.id"
                  @change="(v: any) => onChangeRole(record, v)"
                >
                  <a-select-option v-for="r in ASSIGNABLE_ROLES" :key="r.value" :value="r.value">
                    {{ r.label }}
                  </a-select-option>
                </a-select>
                <a-tooltip v-else :title="record.is_owner ? '账户所有者不可变更角色' : ''">
                  <a-tag :color="roleColor(record.role)">{{ roleLabel(record.role) }}</a-tag>
                </a-tooltip>
              </template>

              <template v-else-if="column.key === 'status'">
                <a-tag :color="record.status === 'active' ? 'green' : 'default'">
                  {{ record.status === 'active' ? '已加入' : '已移除' }}
                </a-tag>
              </template>

              <template v-else-if="column.key === 'joined'">
                {{ record.joined_at ? formatDate(record.joined_at) : '—' }}
              </template>

              <template v-else-if="column.key === 'action'">
                <a-popconfirm
                  v-if="canManage && !record.is_owner && record.status === 'active'"
                  title="确定移除该成员吗？移除后他将无法访问本账户的店铺。"
                  ok-text="移除"
                  cancel-text="取消"
                  @confirm="onRemove(record)"
                >
                  <a-button size="small" danger type="link">移除</a-button>
                </a-popconfirm>
                <a-tooltip v-else-if="record.is_owner" title="账户必须有所有者，不能移除">
                  <span class="muted">—</span>
                </a-tooltip>
              </template>
            </template>
          </a-table>

          <a-empty v-if="!loading && members.length === 0" description="还没有其他成员" />
        </a-card>
      </template>
    </a-spin>

    <a-modal
      v-model:open="showInvite"
      title="邀请成员"
      :confirm-loading="inviting"
      @ok="onInvite"
    >
      <a-form layout="vertical">
        <a-form-item label="对方邮箱">
          <a-input v-model:value="inviteForm.email" placeholder="teammate@example.com" />
          <div class="form-hint">
            对方需已注册本站账号；按邮箱邀请，不需要（也不应该）知道对方的用户 ID。
          </div>
        </a-form-item>
        <a-form-item label="角色">
          <a-select v-model:value="inviteForm.role" style="width: 100%">
            <a-select-option v-for="r in ASSIGNABLE_ROLES" :key="r.value" :value="r.value">
              {{ r.label }} —— {{ r.desc }}
            </a-select-option>
          </a-select>
          <div class="form-hint">「所有者」不可分配：账户只能有一个所有者。</div>
        </a-form-item>
      </a-form>
    </a-modal>

    <a-modal
      v-model:open="showCreateAccount"
      title="新建账户"
      :confirm-loading="creatingAccount"
      @ok="onCreateAccount"
    >
      <a-form layout="vertical">
        <a-form-item label="账户名称">
          <a-input v-model:value="newAccountName" placeholder="例如：跨境一组" />
        </a-form-item>
      </a-form>
      <div class="form-hint">你将成为该账户的所有者。</div>
    </a-modal>
  </div>
</template>

<script setup lang="ts">
/**
 * 团队成员管理页
 *
 * 接的是后端 `core/auth/accounts_router.py` 那 9 个此前**零前端调用**的端点
 * （账户列表 / 成员列表 / 邀请 / 改角色 / 移除）。
 *
 * ★ 页面上的禁用与隐藏都只是**提示**，真正的授权判定在后端
 *   （`require_account_permission`）—— 前端从不替后端做结论。
 */
import { ref, computed, onMounted } from 'vue'
import { useRouter } from 'vue-router'
import { message } from 'ant-design-vue'
import dayjs from 'dayjs'
import { useUserStore } from '@/stores/user'
import {
  listAccounts,
  listMembers,
  inviteMember,
  updateMember,
  removeMember,
  createAccount,
  canManageMembers,
  roleLabel,
  roleColor,
  ASSIGNABLE_ROLES,
  type AccountInfo,
  type AccountMember,
  type AccountRoleValue,
} from '@/api/accounts'

const router = useRouter()
const userStore = useUserStore()

const loading = ref(false)
/**
 * 后端返回 401 ⇒ 需要**真实**登录。
 *
 * 账户与成员是身份数据，演示模式的 `demo-token` 不是 JWT、后端不认，
 * 所以本页在演示模式下必然 401。此时页面必须给出登录入口 ——
 * 否则用户看着一句"请先登录"，界面上却找不到登录的地方。
 */
const needsLogin = ref(false)
const accounts = ref<AccountInfo[]>([])
const currentAccountId = ref<string | undefined>(undefined)
const members = ref<AccountMember[]>([])
const includeRemoved = ref(false)
const busyId = ref<string | null>(null)

const showInvite = ref(false)
const inviting = ref(false)
const inviteForm = ref<{ email: string; role: AccountRoleValue }>({
  email: '',
  role: 'member',
})

const showCreateAccount = ref(false)
const creatingAccount = ref(false)
const newAccountName = ref('')

const currentAccount = computed(
  () => accounts.value.find((a) => a.id === currentAccountId.value) || null
)
const canManage = computed(() => canManageMembers(currentAccount.value))

const columns = [
  { title: '成员', key: 'member', width: 240 },
  { title: '角色', key: 'role', width: 160 },
  { title: '状态', key: 'status', width: 100 },
  { title: '加入时间', key: 'joined', width: 170 },
  { title: '操作', key: 'action', width: 100 },
]

function formatDate(v: string | null): string {
  return v ? dayjs(v).format('YYYY-MM-DD HH:mm') : '—'
}

async function loadAccounts() {
  loading.value = true
  try {
    const res = await listAccounts()
    accounts.value = res.accounts || []
    needsLogin.value = false
    if (!currentAccountId.value && accounts.value.length > 0) {
      // 默认选「我自己的」账户（is_owner 优先），否则第一个
      const own = accounts.value.find((a) => a.is_owner)
      currentAccountId.value = (own || accounts.value[0]).id
    }
    if (currentAccountId.value) await loadMembers()
  } catch (e: any) {
    // 不喂 Mock：账户是身份数据，编不出来（空状态优于虚构默认）
    const status = e?.response?.status
    if (status === 401) {
      // 401 已由 request 拦截器统一提示一次并跳转登录页，
      // 这里只负责**页面内联引导** —— 再弹一次用户会看到两条一样的提示。
      needsLogin.value = true
    } else {
      message.error(e?.response?.data?.detail || '加载账户失败')
    }
    accounts.value = []
  } finally {
    loading.value = false
  }
}

async function loadMembers() {
  if (!currentAccountId.value) return
  try {
    const res = await listMembers(currentAccountId.value, includeRemoved.value)
    members.value = res.members || []
  } catch (e: any) {
    // 无权查看时后端返回 404（刻意不用 403，避免暴露账户是否存在）
    members.value = []
    if (e?.response?.status === 401) {
      needsLogin.value = true
    } else {
      message.error(e?.response?.data?.detail || '加载成员失败')
    }
  }
}

async function onAccountChange() {
  members.value = []
  await loadMembers()
}

function openInvite() {
  inviteForm.value = { email: '', role: 'member' }
  showInvite.value = true
}

async function onInvite() {
  const email = inviteForm.value.email.trim()
  if (!email || !email.includes('@')) {
    message.warning('请输入有效的邮箱地址')
    return
  }
  if (!currentAccountId.value) return

  inviting.value = true
  try {
    await inviteMember(currentAccountId.value, email, inviteForm.value.role)
    message.success('成员已加入')
    showInvite.value = false
    await loadMembers()
    await loadAccounts()
  } catch (e: any) {
    message.error(e?.response?.data?.detail || '邀请失败')
  } finally {
    inviting.value = false
  }
}

async function onChangeRole(record: AccountMember, role: AccountRoleValue) {
  if (!currentAccountId.value || role === record.role) return
  busyId.value = record.id
  try {
    await updateMember(currentAccountId.value, record.id, { role })
    record.role = role
    message.success(`已将 ${record.email || '该成员'} 设为${roleLabel(role)}`)
  } catch (e: any) {
    message.error(e?.response?.data?.detail || '修改角色失败')
  } finally {
    busyId.value = null
  }
}

async function onRemove(record: AccountMember) {
  if (!currentAccountId.value) return
  busyId.value = record.id
  try {
    await removeMember(currentAccountId.value, record.id)
    message.success('成员已移除')
    await loadMembers()
    await loadAccounts()
  } catch (e: any) {
    message.error(e?.response?.data?.detail || '移除失败')
  } finally {
    busyId.value = null
  }
}

async function onCreateAccount() {
  const name = newAccountName.value.trim()
  if (!name) {
    message.warning('请输入账户名称')
    return
  }
  creatingAccount.value = true
  try {
    const res: any = await createAccount(name)
    message.success('账户已创建')
    showCreateAccount.value = false
    newAccountName.value = ''
    await loadAccounts()
    if (res?.id) {
      currentAccountId.value = res.id
      await loadMembers()
    }
  } catch (e: any) {
    message.error(e?.response?.data?.detail || '创建失败')
  } finally {
    creatingAccount.value = false
  }
}

/**
 * 去登录（本页被拒时的唯一出口）
 *
 * ★ 先清掉演示模式的 demo token：路由守卫按"是不是真身份"判断，
 *   清干净状态才能保证登录、回跳、后续请求看到的是同一个事实。
 */
function goLogin() {
  userStore.clearAuth()
  router.push({ name: 'Login', query: { redirect: '/team' } })
}

onMounted(loadAccounts)
</script>

<style scoped>
.team-page {
  padding: 24px;
  max-width: 1100px;
  margin: 0 auto;
}
.team-head {
  display: flex;
  align-items: flex-start;
  justify-content: space-between;
  gap: 16px;
  margin-bottom: 16px;
}
.team-title {
  font-size: 20px;
  font-weight: 500;
  margin: 0 0 4px;
}
.team-sub {
  margin: 0;
  font-size: 13px;
  opacity: 0.65;
}
.team-card {
  margin-bottom: 16px;
}
.member-cell {
  display: flex;
  flex-direction: column;
  line-height: 1.4;
}
.member-email {
  font-size: 12px;
  opacity: 0.6;
}
.form-hint {
  font-size: 12px;
  opacity: 0.6;
  margin-top: 4px;
}
.muted {
  opacity: 0.4;
}
/* 未登录引导：提示 + 明确的下一步 */
.team-alert {
  margin-bottom: 12px;
}
.team-login-row {
  display: flex;
  align-items: center;
  gap: 12px;
  margin-bottom: 16px;
}
.team-login-hint {
  font-size: 12px;
  opacity: 0.6;
}
</style>
