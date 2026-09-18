<template>
  <!-- 底部账户入口：头像 + 用户名 → 点击弹出功能菜单（上拉） -->
  <div class="account-entry">
    <a-dropdown
      v-model:open="menuOpen"
      :trigger="['click']"
      placement="topLeft"
      :overlayStyle="{ width: '240px' }"
    >
      <!-- 触发器：头像 + 用户名 + 切换账号 + 右侧 chevron -->
      <div class="user-trigger" :class="{ open: menuOpen }" @click.prevent>
        <div class="avatar">{{ avatarLetter }}</div>
        <div v-if="!sidebarCollapsed" class="user-meta">
          <span class="username">{{ displayName }}</span>
          <span class="user-role">{{ userRoleLabel }}</span>
        </div>

        <!-- ★ 第 113 轮：切换账号（在「用户名旁边」，不是藏在菜单里）
             · 必须 @click.stop —— 否则点击会冒泡到 .user-trigger，
               把上面的功能菜单一起打开，两个浮层同时出现。
             · 折叠态不渲染：侧栏收起后只有 80px（内容区约 56px），
               32px 头像 + 22px 按钮已经放不下，会挤成溢出。
               折叠态改从菜单里的「切换账号」进入 —— 两者**互斥**，
               任一时刻恰好一个可见（见下方菜单项注释与门禁）。 -->
        <a-popover
          v-if="isRealLogin && !sidebarCollapsed"
          v-model:open="switchOpen"
          trigger="click"
          placement="topRight"
          :overlayStyle="{ width: '272px' }"
        >
          <template #content>
            <div class="switch-panel">
              <div class="sp-title">
                <span>切换账号</span>
                <span class="sp-count">{{ knownAccounts.length }}/{{ MAX_KNOWN_ACCOUNTS }}</span>
              </div>

              <div v-if="!knownAccounts.length" class="sp-empty">
                还没有登录记录。同一个浏览器登录过的账号会出现在这里。
              </div>
              <ul v-else class="sp-list">
                <li
                  v-for="a in knownAccounts"
                  :key="a.id"
                  class="sp-item"
                  :class="{ 'is-current': isCurrent(a) }"
                >
                  <button
                    class="sp-main"
                    :disabled="isCurrent(a) || switchingTo === a.id"
                    :title="switchTitle(a)"
                    @click.stop="switchToAccount(a)"
                  >
                    <span class="sp-avatar">{{ (a.name || a.email).charAt(0).toUpperCase() }}</span>
                    <span class="sp-meta">
                      <span class="sp-name">
                        {{ a.name }}
                        <span v-if="isCurrent(a)" class="sp-badge">当前</span>
                      </span>
                      <span class="sp-mail">{{ a.email }}</span>
                    </span>
                    <!-- ★ 第 120 轮：两类账号必须一眼可分。
                         原来只有「免密」一个徽标，未免密的账号**什么都不显示** ——
                         用户于是以为列表里每个账号都能免密，点下去才发现要输密码，
                         而界面上没有任何线索解释为什么。 -->
                    <span v-if="!isCurrent(a) && hasCred(a)" class="sp-freed">免密</span>
                    <span v-else-if="!isCurrent(a)" class="sp-first">需密码</span>
                    <span v-if="!isCurrent(a)" class="sp-time">{{ formatLastLogin(a.last_login_at) }}</span>
                  </button>
                  <button
                    class="sp-del"
                    title="只从本机移除这个快捷入口（不影响账号本身）"
                    @click.stop="removeKnown(a)"
                  >
                    <DeleteOutlined />
                  </button>
                </li>
              </ul>

              <!-- ★ 第 120 轮：这行说明原本写成 `v-if="rememberedCount"`，
                   于是「一个都没记住」时它整块消失 —— 而恰恰是那种情况下
                   用户最需要知道为什么。现在只要列表非空就显示，
                   并把「需密码 → 免密」的路径写清楚。

                   ★ 为什么必须写「用密码登录一次后即可免密」：
                     免密的门槛是「这台机器上曾经用密码成功登录过这个账号」——
                     服务端只能拿到登录后签发的凭据，拿不到密码本身，
                     所以**第一次不可能免密**。这是固有语义，
                     不说明白，用户就只会认为「这个功能没用」。 -->
              <div v-if="knownAccounts.length" class="sp-note">
                <template v-if="rememberedCount">
                  已记住 {{ rememberedCount }} 个账号的登录状态，可直接免密切换。
                </template>
                标「需密码」的账号，用密码登录一次后即可免密（凭据加密存于服务端）；共用设备请点「清空记录」。
              </div>

              <div class="sp-foot">
                <button class="sp-foot-btn" @click.stop="goLoginPage()">
                  <PlusOutlined /> 登录其它账号
                </button>
                <button
                  v-if="knownAccounts.length"
                  class="sp-foot-btn sp-foot-danger"
                  title="清空本机记住的账号列表"
                  @click.stop="clearKnown"
                >
                  清空记录
                </button>
              </div>
            </div>
          </template>

          <button class="switch-btn" title="切换账号" @click.stop>
            <UserSwitchOutlined />
          </button>
        </a-popover>

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

            <!-- 6. 切换账号 / 退出登录 / 登录 -->
            <!-- ★★★ 第 121 轮：这一项**只在侧栏折叠时**渲染，与行内图标互斥。
                 · 老板的原话：「左侧边栏右下角已有图标，取消用户头像下拉列表中的
                   【切换账号】」—— 展开态下用户名的右边就是那个图标
                   （`.switch-btn`），下拉里再来一项就是**同一个动作的第二个
                   入口**，两处都在只会让人怀疑它们行为不同。
                 · 但换来的前提是「那个图标一直都在」—— 它**不是**：
                   CDP 实测折叠后侧栏只剩 80px，头像 32px + 按钮 22px 放不下，
                   行内图标直接不渲染（`hasSwitchBtn = false`）。
                   所以这里必须保留一个，否则侧栏一收起就再也切不了账号
                   —— 正是本项目反复防过的「提示要登录可是没有入口」那一类。
                 · ⇒ 两个入口**互补**：任一时刻恰好一个可见。
                   门禁 `check-auth-vault.cjs` 的「切换入口互斥」一条钉住了
                   这一点（含反向注入），改任何一边的折叠条件都会红。 -->
            <a-menu-item
              v-if="isRealLogin && sidebarCollapsed"
              key="switch"
              @click="goLoginPage()"
            >
              <span class="mi-icon"><UserSwitchOutlined /></span>
              <span class="mi-label">切换账号</span>
              <span class="mi-extra"></span>
            </a-menu-item>

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
import { ref, computed, watch } from 'vue'
import { useRouter } from 'vue-router'
import { message } from 'ant-design-vue'
import {
  SettingOutlined, ExperimentOutlined, BgColorsOutlined,
  QuestionCircleOutlined, ReloadOutlined, LogoutOutlined, LoginOutlined,
  DownOutlined, CheckOutlined, CopyOutlined, CrownOutlined, TeamOutlined,
  UserSwitchOutlined, PlusOutlined, DeleteOutlined,
} from '@ant-design/icons-vue'
import { useUserStore } from '@/stores/user'
import { useThemeStore } from '@/stores/theme'
import { THEME_OPTIONS, themeModeLabel } from '@/theme/presets'
import { isDemoToken } from '@/config/demoMode'
import {
  useKnownAccounts, forgetAccount, forgetAllAccounts,
  MAX_KNOWN_ACCOUNTS, type KnownAccount,
} from '@/config/knownAccounts'
import {
  isRemembered, forgetRemembered, clearRemembered, rememberedAccountCount,
} from '@/config/authVault'
import { resetSessionContext } from '@/utils/sessionContext'

const props = defineProps<{
  sidebarCollapsed?: boolean
}>()

const router = useRouter()
const userStore = useUserStore()
const themeStore = useThemeStore()

const menuOpen = ref(false)
/** 「切换账号」浮层开关（与上方功能菜单是两个独立浮层） */
const switchOpen = ref(false)
/** 正在免密切换到哪个账号（用于禁用按钮 + 防重复点击） */
const switchingTo = ref<string | null>(null)
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
 *
 * ★ 「切换账号」也以它为闸门：演示身份没有"另一个账号"可切，
 *   菜单里已经给了「登录」（见模板），不构成死路。
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

// ====== 账号历史（★ 第 113 轮）======
// 数据与写入都归 `config/knownAccounts.ts`（唯一真源）；这里只读。
// 模块导入时已从 localStorage 自举，所以刷新页面后列表也在。
const knownAccounts = useKnownAccounts()

/** 本机已记住几个账号的登录状态（供底部提示与「免密」标记） */
const rememberedCount = rememberedAccountCount

/**
 * 本机是否记住了这个账号的登录状态（决定切换时要不要输密码）。
 *
 * ★ 第 119 轮：判定源从「localStorage 里有没有那枚凭据」换成
 *   「**服务端**记不记得本机」—— 本地只剩一份 `string[]` 索引，
 *   凭据本身已搬去服务端加密托管（见 `config/authVault.ts` 文件头）。
 * ★ `void rememberedCount.value` 不是为了取数，而是建立响应式依赖：
 *   `isRemembered()` 读的是模块内那份 ref，模板里的函数调用不会自动
 *   被追踪，不显式读一下，「免密」标记就会停在旧值上。
 */
function hasCred(a: KnownAccount): boolean {
  void rememberedCount.value
  return isRemembered(a.id)
}

/** 悬停提示：把「点了会怎样」提前说清楚 */
function switchTitle(a: KnownAccount): string {
  if (isCurrent(a)) return '当前正在使用的账号'
  // ★ 第 120 轮：原来只说「（需要输入密码）」，读起来像**每次都**要输。
  //   实测反馈正是这句话背后的困惑：「现在切换账号还是要重新输入密码」。
  //   事实上服务端在这第一次认证之后就会把它记进本机容器，
  //   此后这个方向一直是免密的 —— 必须把这一点说出来。
  return hasCred(a)
    ? `免密切换到 ${a.email}`
    : `首次切换到 ${a.email} 需输入一次密码，之后即可免密`
}

/** 当前正在使用的身份，不该被当成"要切过去的目标" */
function isCurrent(a: KnownAccount): boolean {
  const me = userStore.user
  if (!me) return false
  return a.id === me.id || a.email === me.email
}

/**
 * 打开「切换账号」面板时，向服务端要一次**权威清单**。
 *
 * ★ 为什么需要：本地索引只是"首屏不闪"的缓存，可能已经过期
 *   （在别的设备上被撤销 / 已过期 / 服务端换了密钥解不开）。
 *   只信本地就会出现「界面挂着免密、点下去却是登录页」。
 * ★ 为什么放在 watch 而不是 onMounted：这个浮层首屏并不渲染列表，
 *   没人打开过就不该产生网络往返。
 * ★ 用 void 调用：它只是刷新一下显示，失败不该影响打开面板本身。
 */
watch(switchOpen, (open) => {
  if (open && isRealLogin.value) void userStore.fetchRememberedAccounts()
})

/** 相对时间：切换账号时用户最想知道的是"哪个是最新的" */
function formatLastLogin(iso: string): string {
  if (!iso) return ''
  const t = new Date(iso).getTime()
  if (Number.isNaN(t)) return ''
  const min = Math.floor((Date.now() - t) / 60000)
  if (min < 1) return '刚刚'
  if (min < 60) return `${min} 分钟前`
  const hr = Math.floor(min / 60)
  if (hr < 24) return `${hr} 小时前`
  const day = Math.floor(hr / 24)
  if (day < 30) return `${day} 天前`
  return new Date(t).toLocaleDateString()
}

/* ==========================================================================
 * 「去登录页」的唯一出口
 *
 * ★ 为什么收敛成一个函数：三个入口（切换账号 / 登录其它账号 / 未登录时的
 *   「登录」）都要做同一串动作 —— 关浮层 → 处理当前凭据 → 清身份上下文 →
 *   跳登录页。散成三份就一定会漂移（本项目有过太多次这种教训）。
 * ★ `revoke` 的语义：当前若持有**真实**凭据，必须先让服务端撤销
 *   refresh token；只清 localStorage 不叫登出（那枚 token 在有效期内仍可用）。
 *   演示态没有可撤销的东西，走后一个分支。
 * ========================================================================== */
function goLoginPage(opts: { revoke?: boolean; email?: string } = {}) {
  switchOpen.value = false
  menuOpen.value = false

  if (opts.revoke) {
    // 不 await：logout() 内部第一步就发出了撤销请求，随后立即跳转，
    // 不必让用户等一个网络往返（撤销失败也会清本地）。
    void userStore.logout()
  } else {
    userStore.clearAuth()
  }

  // ★ 清掉属于**上一个身份**的团队 / 店铺上下文。
  //   不清的后果：新账号登录后，店铺列表加载完成之前发出去的请求
  //   已经带着旧账号的 X-Shop-ID 了（详见 utils/sessionContext.ts）。
  resetSessionContext()

  const query: Record<string, string> = {
    redirect: router.currentRoute.value.fullPath,
  }
  if (opts.email) query.email = opts.email
  router.push({ name: 'Login', query })
}

/**
 * 切到历史里的另一个账号（★ 第 119 轮改为**服务端托管凭据**的免密切换）。
 *
 * 规则：
 *   · 服务端记着本机（`auth:device:<device_id>`，Fernet 加密）且那枚凭据仍有效
 *     ⇒ 后端校验通过后一次回一对新凭据 + user，不打扰用户；
 *   · 没记住过、或那枚凭据已被撤销 / 过期 / 因改密失效
 *     ⇒ 后端返回 401 并顺手删掉坏凭据，这里带着邮箱去登录页。
 *
 * ★ 为什么切换时**不撤销**当前账号：当前那枚凭据还要留着，以便「切回来」
 *   时仍可免密；撤销它等于每切一次都要重输密码 —— 与免密的目的直接冲突。
 *   撤销只发生在「退出登录」（`userStore.logout()`）那一条路上。
 *
 * ★ 为什么前端**不再**自己判断凭据有效性：判定的唯一真源已在后端
 *   （`core/identity/device_router.py`，逐条复刻 `/auth/refresh` 的四道门）。
 *   前端若也判一遍，就是同一判定两份实现 —— 迟早漂移，且其中一份必然测不到。
 */
async function switchToAccount(a: KnownAccount) {
  if (isCurrent(a)) return
  if (switchingTo.value) return

  switchOpen.value = false
  menuOpen.value = false
  switchingTo.value = a.id
  try {
    const info = await userStore.switchToAccount(a.id)
    if (info) {
      // ★ 换身份成功后必须清掉属于上一个身份的团队 / 店铺上下文
      resetSessionContext()
      message.success(`已切换到「${info.name || a.name}」`)
      // ★ 身份变了 ⇒ 页面上所有数据都变了。整页重载是唯一能保证
      //   「界面与身份同源」的做法（局部刷新一定会漏掉某个 store）。
      //   延迟一下让上面的提示先渲染出来，否则 reload 会直接打断它。
      setTimeout(() => window.location.reload(), 350)
      return
    }

    // 走到这里有两类原因，对用户是同一个动作：
    //   · 服务端没记住它（本机索引过期 / 从来就没记住过）
    //   · 那枚凭据已被撤销 / 已过期 / 因改密导致 tv 不匹配
    // 后端在这两种情况下都会顺手把坏凭据从容器里删掉，所以这里只需要
    // 把本地标记也去掉（否则一直顶着「免密」标记骗人），再带邮箱去登录页。
    forgetRemembered(a.id)
    goLoginPage({ email: a.email })
  } finally {
    switchingTo.value = null
  }
}

async function removeKnown(a: KnownAccount) {
  forgetAccount(a.id)
  // ★ 标签和「本机免密」必须一起删：只删标签会让一枚**还有效的**凭据
  //   继续躺在服务端 —— 那是用户看不见的后门：他以为「移除了」，
  //   实际点一下还能直接进去。真正把凭据删掉的是服务端 `forget`。
  await userStore.forgetDeviceAccount(a.id)
  forgetRemembered(a.id)
  message.success(`已从本机移除「${a.name}」`)
}

async function clearKnown() {
  forgetAllAccounts()
  // ★ 顺序：先让**服务端**清（它是权威），成功后再清本地标记。
  //   反过来的话，服务端失败而本地已清 ⇒ 界面显示"没记住"，
  //   可那枚凭据还躺在 Redis 里，只是用户再也看不见它了 —— 比不删更糟。
  // ★ 这是用户手里唯一能把本机免密一次性清干净的入口。
  const cleared = await userStore.forgetDeviceAll()
  if (!cleared) {
    message.error('本机登录状态未能完全清除，请稍后重试')
    return
  }
  clearRemembered()
  message.success('已清空本机记住的账号和登录状态')
}

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

/**
 * 退出登录。
 *
 * ★ 与「切换账号」共用 `goLoginPage({ revoke: true })`：
 *   两者的差别只是"下一条登录的是不是同一个人"，动作完全相同。
 *   并且都会带上 `redirect` —— 重新登录后回到刚才所在的那一页，
 *   而不是被丢回首页。
 */
const handleLogout = () => {
  goLoginPage({ revoke: true })
}

/**
 * 去登录（未真实登录时的入口）。
 *
 * ★ 先 `clearAuth()` 把演示模式的 demo token 清掉：
 *   路由守卫按"是不是真身份"决定要不要放行登录页，清干净状态
 *   才能保证后续每一步（登录、回跳、401 处理）看到的是同一个事实。
 */
const goLogin = () => {
  goLoginPage()
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

/* ★ 第 113 轮：切换账号按钮（行内、图标形，hover 才显形）
   默认淡出，避免与"点头像开菜单"的既有习惯抢注意力；
   hover 整个触发条或它自身时显形。 */
.switch-btn {
  width: 22px;
  height: 22px;
  flex-shrink: 0;
  display: inline-flex;
  align-items: center;
  justify-content: center;
  border: 0;
  padding: 0;
  border-radius: var(--radius-6);
  background: transparent;
  color: var(--text-tertiary);
  font-size: var(--font-size-14);
  cursor: pointer;
  transition: all 0.15s;
  opacity: 0.55;
}
.user-trigger:hover .switch-btn,
.switch-btn:hover {
  opacity: 1;
  color: var(--primary);
  background: var(--bg-hover-light);
}

.caret {
  font-size: var(--font-size-11);
  color: var(--text-disabled);
  flex-shrink: 0;
}

/* ===== 「切换账号」浮层内容 ===== */
.switch-panel {
  min-width: 240px;
}
.sp-title {
  display: flex;
  align-items: center;
  justify-content: space-between;
  font-size: var(--font-size-12);
  font-weight: 600;
  color: var(--text-secondary);
  margin-bottom: var(--space-6);
}
.sp-count {
  font-weight: 400;
  color: var(--text-disabled);
  font-variant-numeric: tabular-nums;
}
.sp-empty {
  font-size: var(--font-size-12);
  color: var(--text-tertiary);
  line-height: 1.7;
  padding: var(--space-6) 0;
}

.sp-list {
  list-style: none;
  margin: 0;
  padding: 0;
  max-height: 232px;
  overflow-y: auto;
}
.sp-item {
  display: flex;
  align-items: center;
  gap: var(--space-2);
  border-radius: var(--radius-6);
}
.sp-item:hover { background: var(--bg-hover-light); }
.sp-item.is-current { opacity: 0.7; }

.sp-main {
  flex: 1;
  min-width: 0;
  display: flex;
  align-items: center;
  gap: var(--space-8);
  border: 0;
  background: transparent;
  padding: var(--space-6) var(--space-6);
  border-radius: var(--radius-6);
  cursor: pointer;
  text-align: left;
  color: var(--text-primary);
}
.sp-main:disabled { cursor: default; }

.sp-avatar {
  width: 26px;
  height: 26px;
  min-width: 26px;
  border-radius: var(--radius-circle);
  background: var(--bg-card-pill);
  color: var(--text-secondary);
  display: inline-flex;
  align-items: center;
  justify-content: center;
  font-size: var(--font-size-12);
  font-weight: 600;
  flex-shrink: 0;
}
.sp-item.is-current .sp-avatar {
  background: linear-gradient(135deg, #52c41a, #389e0d);
  color: #fff;
}

.sp-meta {
  display: flex;
  flex-direction: column;
  min-width: 0;
  flex: 1;
  gap: 1px;
}
.sp-name {
  font-size: var(--font-size-12);
  font-weight: 600;
  color: var(--text-primary);
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}
.sp-badge {
  font-size: var(--font-size-10);
  font-weight: 400;
  color: var(--primary);
  border: 1px solid var(--primary);
  border-radius: var(--radius-3);
  padding: 0 var(--space-3);
  margin-left: var(--space-3);
  line-height: 14px;
  display: inline-block;
  vertical-align: 1px;
}
.sp-mail {
  font-size: var(--font-size-11);
  color: var(--text-tertiary);
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}
.sp-time {
  font-size: var(--font-size-10);
  color: var(--text-disabled);
  flex-shrink: 0;
  font-variant-numeric: tabular-nums;
}

/* 「免密」标记：点了不用输密码 */
.sp-freed {
  flex-shrink: 0;
  font-size: var(--font-size-10);
  color: var(--primary);
  border: 1px solid var(--primary);
  border-radius: var(--radius-3);
  padding: 0 var(--space-3);
  line-height: 14px;
}

/* 「需密码」标记（★ 第 120 轮）：中性灰。
   ★ 刻意**不用**主色/警示色：它不是错误状态，只是「这条路径要多一步」。
     用主色会和「免密」抢视觉权重，用警示色会让用户以为账号出了问题
     （实际上他只是还没在这台机器上登录过它）。 */
.sp-first {
  flex-shrink: 0;
  font-size: var(--font-size-10);
  color: var(--text-disabled);
  border: 1px solid var(--border-base);
  border-radius: var(--radius-3);
  padding: 0 var(--space-3);
  line-height: 14px;
}

/* 底部诚实提示：本机到底存了几个账号的登录状态 */
.sp-note {
  font-size: var(--font-size-10);
  color: var(--text-disabled);
  line-height: 1.6;
  margin-top: var(--space-8);
  padding-top: var(--space-6);
  border-top: 1px solid var(--border-base);
}

.sp-del {
  flex-shrink: 0;
  border: 0;
  background: transparent;
  color: var(--text-disabled);
  cursor: pointer;
  font-size: var(--font-size-12);
  padding: 0 var(--space-3);
  height: 20px;
  border-radius: var(--radius-4);
  visibility: hidden;
}
.sp-item:hover .sp-del { visibility: visible; }
.sp-del:hover { color: var(--danger); background: var(--danger-hover-bg); }

.sp-foot {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: var(--space-8);
  margin-top: var(--space-6);
  padding-top: var(--space-6);
  border-top: 1px solid var(--border-base);
}
.sp-foot-btn {
  display: inline-flex;
  align-items: center;
  gap: var(--space-4);
  border: 0;
  background: transparent;
  color: var(--primary);
  font-size: var(--font-size-12);
  cursor: pointer;
  padding: var(--space-3) var(--space-4);
  border-radius: var(--radius-4);
}
.sp-foot-btn:hover { background: var(--bg-hover-light); }
.sp-foot-danger { color: var(--text-tertiary); }
.sp-foot-danger:hover { color: var(--danger); }

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
