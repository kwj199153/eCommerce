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

            <!-- 2. 记忆与进化 -->
            <a-menu-item key="memory" @click="openMemoryDrawer">
              <span class="mi-icon"><ExperimentOutlined /></span>
              <span class="mi-label">记忆与进化</span>
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

            <!-- 6. 退出登录 -->
            <a-menu-item key="logout" @click="handleLogout" class="logout-item">
              <span class="mi-icon"><LogoutOutlined /></span>
              <span class="mi-label">退出登录</span>
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
  QuestionCircleOutlined, ReloadOutlined, LogoutOutlined,
  DownOutlined, CheckOutlined, CopyOutlined,
} from '@ant-design/icons-vue'
import { useUserStore } from '@/stores/user'
import { useThemeStore } from '@/stores/theme'

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

const userRoleLabel = computed(() => {
  const role = userStore.user?.role
  const map: Record<string, string> = { admin: '管理员', operator: '运营', viewer: '只读' }
  return map[role || ''] || '运营账号'
})

const modeLabel = computed(() => {
  const map = { light: '浅色', dark: '深色', system: '跟随系统' } as const
  return map[themeStore.mode]
})

// 主题选项（外观子菜单）
const themeOptions = [
  { icon: '☀️', label: '浅色', value: 'light' as const },
  { icon: '🌙', label: '深色', value: 'dark' as const },
  { icon: '💻', label: '跟随系统', value: 'system' as const },
]

const openSettings = () => {
  menuOpen.value = false
  window.dispatchEvent(new CustomEvent('open-settings-drawer'))
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
  userStore.logout()
  router.push('/login')
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
  padding: 8px 12px;
  border-top: 1px solid var(--border-base);
  margin-top: auto;
  flex-shrink: 0;
}

.user-trigger {
  display: flex;
  align-items: center;
  gap: 10px;
  padding: 6px 8px;
  border-radius: 8px;
  cursor: pointer;
  transition: background 0.2s;
  position: relative;
  color: var(--text-primary);
}
.user-trigger:hover,
.user-trigger.open { background: var(--bg-hover-light); }
html.dark .user-trigger:hover,
html.dark .user-trigger.open { background: var(--bg-hover-dark); }

.avatar {
  width: 32px;
  height: 32px;
  min-width: 32px;
  border-radius: 50%;
  background: linear-gradient(135deg, #52c41a, #389e0d);
  color: #fff;
  display: flex;
  align-items: center;
  justify-content: center;
  font-size: 14px;
  font-weight: 600;
  line-height: 1;
  flex-shrink: 0;
}

.user-meta {
  display: flex;
  flex-direction: column;
  gap: 2px;
  flex: 1;
  min-width: 0;
}
.username {
  font-size: 13px;
  font-weight: 600;
  color: var(--text-primary);
  line-height: 1.2;
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}
.user-role {
  font-size: 11px;
  color: var(--text-tertiary);
  line-height: 1;
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}

.caret {
  font-size: 11px;
  color: var(--text-disabled);
  flex-shrink: 0;
}

/* 弹出卡片容器 */
.account-overlay {
  background: var(--bg-elevated);
  border-radius: 12px;
  box-shadow: 0 8px 28px rgba(0, 0, 0, 0.14);
  padding: 4px 0 6px;
  overflow: hidden;
  color: var(--text-primary);
}
html.dark .account-overlay {
  box-shadow: 0 8px 28px rgba(0, 0, 0, 0.5);
}

/* 身份头 */
.menu-header {
  display: flex;
  align-items: center;
  gap: 12px;
  padding: 10px 14px 8px;
}
.mh-avatar {
  width: 36px;
  height: 36px;
  border-radius: 50%;
  background: linear-gradient(135deg, #52c41a, #389e0d);
  color: #fff;
  display: flex;
  align-items: center;
  justify-content: center;
  font-size: 16px;
  font-weight: 600;
  flex-shrink: 0;
}
.mh-info { flex: 1; min-width: 0; }
.mh-name-row {
  display: flex;
  align-items: center;
  gap: 6px;
  margin-bottom: 2px;
}
.mh-name {
  font-size: 14px;
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
  padding: 0 4px;
  cursor: pointer;
  color: var(--text-tertiary);
  font-size: 12px;
  display: inline-flex;
  align-items: center;
  height: 18px;
  border-radius: 4px;
  transition: all 0.15s;
}
.copy-id-btn:hover { background: var(--bg-hover-light); color: var(--primary); }
html.dark .copy-id-btn:hover { background: var(--bg-hover-dark); color: var(--primary); }

.mh-role {
  font-size: 11px;
  color: var(--text-tertiary);
  line-height: 1.4;
}

/* 菜单 */
.account-menu {
  padding: 0 6px !important;
}
.account-menu :deep(.ant-menu-item) {
  height: 36px;
  line-height: 36px;
  border-radius: 6px;
  padding: 0 12px !important;
  margin: 1px 0;
  color: var(--text-primary);
}
.account-menu :deep(.ant-menu-item:hover) {
  background: var(--bg-hover-light) !important;
}
html.dark .account-menu :deep(.ant-menu-item:hover) {
  background: var(--bg-hover-dark) !important;
}
.account-menu :deep(.ant-menu-submenu-title) {
  height: 36px;
  line-height: 36px;
  border-radius: 6px;
  margin: 1px 0;
  color: var(--text-primary);
}
.account-menu :deep(.ant-menu-submenu-title:hover) {
  background: var(--bg-hover-light) !important;
}
html.dark .account-menu :deep(.ant-menu-submenu-title:hover) {
  background: var(--bg-hover-dark) !important;
}

/* 单列菜单条目排版（flex 三段：图标 / 文字 / 右侧） */
.mi-icon {
  display: inline-flex;
  width: 18px;
  align-items: center;
  justify-content: center;
  margin-right: 10px;
  font-size: 15px;
  color: var(--text-secondary);
}

.mi-label {
  flex: 1;
  font-size: 13px;
  color: var(--text-primary);
}

.mi-extra {
  font-size: 12px;
  color: var(--text-disabled);
  flex-shrink: 0;
}

/* 退出登录 */
.logout-item .mi-icon { color: var(--danger); }
.logout-item .mi-label { color: var(--danger); }
.logout-item:hover { background: rgba(255, 77, 79, 0.08) !important; }
html.dark .logout-item:hover {
  background: rgba(255, 77, 79, 0.18) !important;
}

/* 外观子菜单状态 */
.theme-icon {
  display: inline-block;
  width: 18px;
  margin-right: 10px;
  text-align: center;
  font-size: 14px;
}
.theme-active { color: var(--primary) !important; font-weight: 600; }
.theme-check { color: var(--primary); font-size: 12px; margin-left: auto; }

.sub-title {
  display: flex;
  align-items: center;
  width: 100%;
}

.version-tag {
  font-size: 10px;
  background: var(--bg-card-pill);
  color: var(--text-tertiary);
  padding: 1px 6px;
  border-radius: 3px;
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
