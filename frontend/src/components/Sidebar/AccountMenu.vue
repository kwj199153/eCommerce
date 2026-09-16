<template>
  <!-- 底部账户入口：头像 + 用户名 → 点击弹出功能菜单（上拉） -->
  <div class="account-entry">
    <a-dropdown
      v-model:open="menuOpen"
      :trigger="['click']"
      placement="topLeft"
      :overlayStyle="{ width: '240px' }"
    >
      <!-- 触发器：头像 + 用户名 + 右侧 chevron -->
      <div class="user-trigger" :class="{ open: menuOpen }" @click.prevent>
        <div class="avatar">{{ avatarLetter }}</div>
        <div v-if="!sidebarCollapsed" class="user-meta">
          <span class="username">{{ displayName }}</span>
          <span class="user-role">{{ userRoleLabel }}</span>
        </div>
        <DownOutlined v-if="!sidebarCollapsed" class="caret" />
      </div>

      <template #overlay>
        <div class="account-overlay">
          <!-- 顶部身份头：头像 + 名字 + 复制按钮（参考 workbuddy） -->
          <div class="menu-header">
            <div class="mh-avatar">{{ avatarLetter }}</div>
            <div class="mh-info">
              <div class="mh-name-row">
                <span class="mh-name">{{ displayName }}</span>
                <button
                  class="copy-id-btn"
                  title="复制账号"
                  @click.stop="copyAccountId"
                >
                  <CopyOutlined />
                </button>
              </div>
              <div class="mh-role">{{ userRoleLabel }}</div>
            </div>
          </div>
          <a-divider :margin="0" />

          <a-menu class="account-menu" :selectedKeys="[]">
            <!-- 1. 设置 -->
            <a-menu-item key="settings" @click="openSettings">
              <span class="mi-icon"><SettingOutlined /></span>
              <span class="mi-label">设置</span>
              <span class="mi-extra"></span>
            </a-menu-item>

            <!-- 1.5 订阅与计费 -->
            <a-menu-item key="subscription" @click="openSubscription">
              <span class="mi-icon"><CrownOutlined /></span>
              <span class="mi-label">订阅与计费</span>
              <span class="mi-extra"></span>
            </a-menu-item>

            <!-- 2. 记忆与进化 -->
            <a-menu-item key="memory" @click="openMemoryDrawer">
              <span class="mi-icon"><ExperimentOutlined /></span>
              <span class="mi-label">记忆与进化</span>
              <span class="mi-extra"></span>
            </a-menu-item>

            <!-- 2.5 团队成员（★ 第 100 轮：接上后端 9 个此前零调用的 /accounts 端点） -->
            <a-menu-item key="team" @click="openTeam">
              <span class="mi-icon"><TeamOutlined /></span>
              <span class="mi-label">团队成员</span>
              <span class="mi-extra"></span>
            </a-menu-item>

            <!-- 3. 外观（子菜单：主题切换） -->
            <a-sub-menu key="appearance">
              <template #icon><span class="mi-icon"><BgColorsOutlined /></span></template>
              <template #title>
                <span class="mi-label">外观</span>
                <span class="mi-extra">{{ modeLabel }} ›</span>
              </template>
              <a-menu-item
                v-for="opt in themeOptions"
                :key="opt.value"
                @click="themeStore.setMode(opt.value)"
              >
                <span class="theme-icon">{{ opt.icon }}</span>
                <span
                  class="mi-label"
                  :class="{ 'theme-active': themeStore.mode === opt.value }"
                >{{ opt.label }}</span>
                <CheckOutlined
                  v-if="themeStore.mode === opt.value"
                  class="theme-check"
                />
              </a-menu-item>
            </a-sub-menu>

            <a-divider :margin="0" />

            <!-- 4. 帮助与反馈 -->
            <a-menu-item key="help" @click="handleHelpFeedback">
              <span class="mi-icon"><QuestionCircleOutlined /></span>
              <span class="mi-label">帮助与反馈</span>
              <span class="mi-extra"></span>
            </a-menu-item>

            <!-- 5. 检查更新 -->
            <a-menu-item key="update" @click="checkUpdate">
              <span class="mi-icon"><ReloadOutlined /></span>
              <span class="mi-label">检查更新</span>
              <span class="version-tag">v0.7.0</span>
            </a-menu-item>

            <a-divider :margin="0" />

            <!-- 6. 登录 / 退出登录 -->
            <!-- ★ 未真实登录时必须给「登录」入口：否则用户在演示模式下点了
                 需要身份的功能（如团队成员），既看到"请先登录"，又在界面上
                 找不到任何能登录的地方 —— 这正是"提示要登录可是没有入口"。 -->
            <a-menu-item v-if="isRealLogin" key="logout" @click="handleLogout" class="logout-item">
              <span class="mi-icon"><LogoutOutlined /></span>
              <span class="mi-label">退出登录</span>
              <span class="mi-extra"></span>
            </a-menu-item>
            <a-menu-item v-else key="login" @click="goLogin" class="login-item">
              <span class="mi-icon"><LoginOutlined /></span>
              <span class="mi-label">登录</span>
              <span class="mi-extra"></span>
            </a-menu-item>
          </a-menu>
        </div>
      </template>
    </a-dropdown>
  </div>
</template>

<script setup lang="ts">
import { ref, computed } from 'vue'
import { useRouter } from 'vue-router'
import { message } from 'ant-design-vue'
import {
  SettingOutlined, ExperimentOutlined, BgColorsOutlined,
  QuestionCircleOutlined, ReloadOutlined, LogoutOutlined, LoginOutlined,
  DownOutlined, CheckOutlined, CopyOutlined, CrownOutlined, TeamOutlined,
} from '@ant-design/icons-vue'
import { useUserStore } from '@/stores/user'
import { useThemeStore } from '@/stores/theme'
import { THEME_OPTIONS, themeModeLabel } from '@/theme/presets'
import { isDemoToken } from '@/config/demoMode'

const props = defineProps<{
  sidebarCollapsed?: boolean
}>()

const router = useRouter()
const userStore = useUserStore()
const themeStore = useThemeStore()

const menuOpen = ref(false)
const displayName = computed(() => {
  if (userStore.user?.name) return userStore.user.name
  if (userStore.user?.email) {
    const email = userStore.user.email
    return email.includes('@') ? email.split('@')[0] : email
  }
  return '用户'
})
const avatarLetter = computed(() => displayName.value.charAt(0).toUpperCase())

/**
 * 是否**真实登录**（而不是演示模式的临时身份）。
 *
 * ★ 为什么不能只看 `userStore.token`：演示模式会往 localStorage 写
 *   `demo-token`，它不是 JWT、后端不认。旧实现把这个字符串当成了"已登录"，
 *   于是菜单里只显示「退出登录」—— 用户想真登录却**找不到入口**。
 */
const isRealLogin = computed(
  () => !!userStore.token && !isDemoToken(userStore.token) && !!userStore.user
)

const userRoleLabel = computed(() => {
  if (!isRealLogin.value) return '未登录 · 演示模式'
  const role = userStore.user?.role
  const map: Record<string, string> = { admin: '管理员', operator: '运营', viewer: '只读' }
  return map[role || ''] || '运营账号'
})

const modeLabel = computed(() => themeModeLabel(themeStore.mode))

// 主题选项（外观子菜单）—— 从预设表派生：加第三套主题时本文件零改动
const themeOptions = THEME_OPTIONS

const openSettings = () => {
  menuOpen.value = false
  window.dispatchEvent(new CustomEvent('open-settings-drawer'))
}

const openSubscription = () => {
  menuOpen.value = false
  router.push('/subscription')
}

const openTeam = () => {
  menuOpen.value = false
  router.push('/team')
}

const openMemoryDrawer = () => {
  menuOpen.value = false
  window.dispatchEvent(new CustomEvent('open-memory-drawer'))
}

const handleHelpFeedback = () => {
  menuOpen.value = false
  message.info('帮助与反馈：请联系项目维护者或提交 Issue')
}

const checkUpdate = () => {
  message.loading({ content: '正在检查更新…', duration: 1.2 })
  setTimeout(() => {
    message.success('已是最新版本 v0.7.0')
  }, 1200)
}

const handleLogout = () => {
  // 不 await：logout() 内部第一步就发出了撤销请求，随后立即跳转，
  // 不必让用户等一个网络往返（撤销失败也会清本地）。
  void userStore.logout()
  router.push('/login')
}

/**
 * 去登录（未真实登录时的入口）。
 *
 * ★ 先 `clearAuth()` 把演示模式的 demo token 清掉：
 *   路由守卫按"是不是真身份"决定要不要放行登录页，清干净状态
 *   才能保证后续每一步（登录、回跳、401 处理）看到的是同一个事实。
 */
const goLogin = () => {
  menuOpen.value = false
  userStore.clearAuth()
  router.push({
    name: 'Login',
    query: { redirect: router.currentRoute.value.fullPath },
  })
}

const copyAccountId = async () => {
  const id =
    userStore.user?.email ||
    userStore.user?.name ||
    displayName.value
  try {
    await navigator.clipboard.writeText(id)
    message.success('账号已复制')
  } catch {
    message.warning('当前浏览器不支持复制，请手动复制：' + id)
  }
}
</script>

<style scoped>
/* 底部触发器条 */
.account-entry {
  padding: var(--space-8) var(--space-12);
  border-top: 1px solid var(--border-base);
  margin-top: auto;
  flex-shrink: 0;
}

.user-trigger {
  display: flex;
  align-items: center;
  gap: var(--space-10);
  padding: var(--space-6) var(--space-8);
  border-radius: var(--radius-8);
  cursor: pointer;
  transition: background 0.2s;
  position: relative;
  color: var(--text-primary);
}
.user-trigger:hover,
.user-trigger.open { background: var(--bg-hover-light); }


.avatar {
  width: 32px;
  height: 32px;
  min-width: 32px;
  border-radius: var(--radius-circle);
  background: linear-gradient(135deg, #52c41a, #389e0d);
  color: #fff;
  display: flex;
  align-items: center;
  justify-content: center;
  font-size: var(--font-size-14);
  font-weight: 600;
  line-height: 1;
  flex-shrink: 0;
}

.user-meta {
  display: flex;
  flex-direction: column;
  gap: var(--space-2);
  flex: 1;
  min-width: 0;
}
.username {
  font-size: var(--font-size-13);
  font-weight: 600;
  color: var(--text-primary);
  line-height: 1.2;
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}
.user-role {
  font-size: var(--font-size-11);
  color: var(--text-tertiary);
  line-height: 1;
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}

.caret {
  font-size: var(--font-size-11);
  color: var(--text-disabled);
  flex-shrink: 0;
}

/* 弹出卡片容器 */
.account-overlay {
  background: var(--bg-elevated);
  border-radius: var(--radius-12);
  box-shadow: var(--shadow-overlay);
  padding: var(--space-4) 0 var(--space-6);
  overflow: hidden;
  color: var(--text-primary);
}


/* 身份头 */
.menu-header {
  display: flex;
  align-items: center;
  gap: var(--space-12);
  padding: var(--space-10) var(--space-14) var(--space-8);
}
.mh-avatar {
  width: 36px;
  height: 36px;
  border-radius: var(--radius-circle);
  background: linear-gradient(135deg, #52c41a, #389e0d);
  color: #fff;
  display: flex;
  align-items: center;
  justify-content: center;
  font-size: var(--font-size-16);
  font-weight: 600;
  flex-shrink: 0;
}
.mh-info { flex: 1; min-width: 0; }
.mh-name-row {
  display: flex;
  align-items: center;
  gap: var(--space-6);
  margin-bottom: var(--space-2);
}
.mh-name {
  font-size: var(--font-size-14);
  font-weight: 600;
  color: var(--text-primary);
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
  max-width: 140px;
}

.copy-id-btn {
  background: transparent;
  border: 0;
  padding: 0 var(--space-4);
  cursor: pointer;
  color: var(--text-tertiary);
  font-size: var(--font-size-12);
  display: inline-flex;
  align-items: center;
  height: 18px;
  border-radius: var(--radius-4);
  transition: all 0.15s;
}
.copy-id-btn:hover { background: var(--bg-hover-light); color: var(--primary); }


.mh-role {
  font-size: var(--font-size-11);
  color: var(--text-tertiary);
  line-height: 1.4;
}

/* 菜单 */
.account-menu {
  padding: 0 var(--space-6) !important;
}
.account-menu :deep(.ant-menu-item) {
  height: 36px;
  line-height: 36px;
  border-radius: var(--radius-6);
  padding: 0 var(--space-12) !important;
  margin: var(--space-1) 0;
  color: var(--text-primary);
}
.account-menu :deep(.ant-menu-item:hover) {
  background: var(--bg-hover-light) !important;
}

.account-menu :deep(.ant-menu-submenu-title) {
  height: 36px;
  line-height: 36px;
  border-radius: var(--radius-6);
  margin: var(--space-1) 0;
  color: var(--text-primary);
}
.account-menu :deep(.ant-menu-submenu-title:hover) {
  background: var(--bg-hover-light) !important;
}


/* 单列菜单条目排版（flex 三段：图标 / 文字 / 右侧） */
.mi-icon {
  display: inline-flex;
  width: 18px;
  align-items: center;
  justify-content: center;
  margin-right: var(--space-10);
  font-size: var(--font-size-15);
  color: var(--text-secondary);
}

.mi-label {
  flex: 1;
  font-size: var(--font-size-13);
  color: var(--text-primary);
}

.mi-extra {
  font-size: var(--font-size-12);
  color: var(--text-disabled);
  flex-shrink: 0;
}

/* 退出登录 */
.logout-item .mi-icon { color: var(--danger); }
.logout-item .mi-label { color: var(--danger); }
.logout-item:hover { background: var(--danger-hover-bg) !important; }

/* 登录（未登录态）—— 用主色，与"退出登录"的危险色形成对照 */
.login-item .mi-icon { color: var(--primary); }
.login-item .mi-label { color: var(--primary); font-weight: 600; }


/* 外观子菜单状态 */
.theme-icon {
  display: inline-block;
  width: 18px;
  margin-right: var(--space-10);
  text-align: center;
  font-size: var(--font-size-14);
}
.theme-active { color: var(--primary) !important; font-weight: 600; }
.theme-check { color: var(--primary); font-size: var(--font-size-12); margin-left: auto; }

.sub-title {
  display: flex;
  align-items: center;
  width: 100%;
}

.version-tag {
  font-size: var(--font-size-10);
  background: var(--bg-card-pill);
  color: var(--text-tertiary);
  padding: var(--space-1) var(--space-6);
  border-radius: var(--radius-3);
  line-height: 16px;
  flex-shrink: 0;
}

/* popup 内 divider 轻量 */
.account-overlay :deep(.ant-divider) {
  margin: 0 !important;
  border-color: var(--border-base) !important;
  min-width: 0;
}
</style>
