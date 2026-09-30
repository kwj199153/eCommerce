<template>
  <a-drawer
    :open="drawerOpen"
    @update:open="handleOpenChange"
    title="账号设置"
    placement="right"
    :width="WINDOW_W.xxl"
    :body-style="{ padding: '0', overflow: 'auto' }"
    :destroyOnClose="false"
  >
    <a-tabs v-model:activeKey="activeTab" type="card" class="settings-tabs" style="padding: var(--space-16) var(--space-20)">
      <!-- ====== Tab 1: 个人资料 ====== -->
      <a-tab-pane key="profile" tab="个人资料">
        <a-card :bordered="false" class="profile-card">
          <!-- 头像区域 -->
          <div class="avatar-section">
            <a-avatar :size="80" class="user-avatar">
              {{ userStore.userName?.charAt(0)?.toUpperCase() || 'U' }}
            </a-avatar>
            <div class="avatar-actions">
              <a-button size="small" @click="handleAvatarClick">更换头像</a-button>
              <input
                ref="avatarInputRef"
                type="file"
                accept="image/*"
                style="display: none"
                @change="handleAvatarChange"
              />
            </div>
          </div>

          <a-divider style="margin: var(--space-16) 0" />

          <a-form
            :model="profileForm"
            layout="vertical"
            :style="{ maxWidth: '480px' }"
          >
            <a-form-item label="用户名">
              <a-input v-model:value="profileForm.name" placeholder="输入用户名" />
            </a-form-item>

            <a-form-item label="邮箱地址">
              <a-input v-model:value="profileForm.email" disabled>
                <template #prefix><MailOutlined /></template>
              </a-input>
              <div class="form-hint">邮箱不可修改，如需变更请联系客服</div>
            </a-form-item>

            <a-form-item label="手机号码">
              <a-input v-model:value="profileForm.phone" placeholder="选填">
                <template #prefix><PhoneOutlined /></template>
              </a-input>
            </a-form-item>

            <a-form-item label="公司名称">
              <a-input v-model:value="profileForm.company" placeholder="选填，用于发票开具">
                <template #prefix><BankOutlined /></template>
              </a-input>
            </a-form-item>

            <a-form-item>
              <a-space>
                <a-button type="primary" :loading="savingProfile" @click="handleSaveProfile">
                  保存修改
                </a-button>
                <a-button @click="resetProfileForm">重置</a-button>
              </a-space>
            </a-form-item>
          </a-form>
        </a-card>
      </a-tab-pane>

      <!-- ====== Tab 2: 安全设置 ====== -->
      <a-tab-pane key="security" tab="安全设置">
        <a-card :bordered="false" title="修改密码" class="security-card">
          <a-form layout="vertical" :style="{ maxWidth: '400px' }">
            <a-form-item label="当前密码">
              <a-input-password v-model:value="passwordForm.current" placeholder="输入当前密码" />
            </a-form-item>
            <a-form-item label="新密码">
              <a-input-password v-model:value="passwordForm.newPwd" placeholder="至少8位，含字母和数字" />
            </a-form-item>
            <a-form-item label="确认新密码">
              <a-input-password v-model:value="passwordForm.confirm" placeholder="再次输入新密码" />
            </a-form-item>
            <a-form-item>
              <a-button type="primary" :loading="changingPassword" @click="handleChangePassword">
                修改密码
              </a-button>
            </a-form-item>
          </a-form>
        </a-card>

        <a-card :bordered="false" title="API 密钥" class="security-card" style="margin-top: 16px">
          <a-alert
            type="info"
            show-icon
            message="API 密钥用于调用系统接口，请妥善保管，不要泄露给他人"
            style="margin-bottom: 16px"
          />

          <div v-if="apiKeys.length > 0" class="api-key-list">
            <div v-for="key in apiKeys" :key="key.id" class="api-key-item">
              <div class="key-info">
                <strong>{{ key.name }}</strong>
                <code class="key-value">{{ key.key }}</code>
                <a-tag :color="key.is_active ? 'green' : 'default'">
                  {{ key.is_active ? '活跃' : '已禁用' }}
                </a-tag>
              </div>
              <div class="key-meta">
                <span>创建于 {{ formatDate(key.created_at) }}</span>
                <span>最后使用：{{ key.last_used_at ? formatDate(key.last_used_at) : '从未' }}</span>
              </div>
              <div class="key-actions">
                <!-- ★ 列表里不再提供"复制"：后端只存 sha256，列表返回的是掩码串，
                     复制一串掩码没有意义。完整 key 只在**创建那一刻**的弹窗里给一次。 -->
                <a-popconfirm title="确定要删除此密钥吗？" @confirm="handleDeleteKey(key.id)">
                  <a-button size="small" danger type="link">删除</a-button>
                </a-popconfirm>
              </div>
            </div>
          </div>

          <a-empty v-else description="暂无 API 密钥">
            <a-button type="primary" @click="showCreateKeyModal = true">创建 API 密钥</a-button>
          </a-empty>

          <a-button
            v-if="apiKeys.length > 0"
            type="primary"
            style="margin-top: 12px"
            @click="showCreateKeyModal = true"
          >
            + 创建新密钥
          </a-button>
        </a-card>

        <a-card :bordered="false" title="登录会话" class="security-card" style="margin-top: 16px">
          <a-descriptions :column="1" size="small">
            <a-descriptions-item label="当前设备">
              <!-- ★ 台账 #1154：这个标签原来写死「本机 - Chrome / Windows」——
                   在 Safari / Mac / 手机上它是一句**假话**，而这张卡的作用
                   恰恰是让用户判断"哪些登录是我的"。假话在这里的代价不是
                   难看，是**误判**（以为自己被盗号）。改成按 UA 粗分类。 -->
              <a-tag color="blue">{{ currentDeviceLabel }}</a-tag>
            </a-descriptions-item>
            <a-descriptions-item label="最后登录时间">
              {{ userStore.user?.last_login_at ? formatTime(userStore.user.last_login_at) : '-' }}
            </a-descriptions-item>
          </a-descriptions>

          <!-- ★ 按钮文案不能写「退出所有**其他**设备」。
               后端走的是 `token_version += 1`，本机这枚 token **也一样失效**
               （与 `/auth/change-password` 的后半段同一机制）。
               按错误文案理解，用户会以为"本机不受影响"，结果下一个请求
               就被踢出去 —— 看起来像"莫名其妙掉线"，而真正的原因
               是他自己刚点的这个按钮。 -->
          <a-popconfirm
            title="退出所有设备？包含本机在内，全部登录都会失效，需要重新登录。"
            ok-text="退出所有设备"
            cancel-text="取消"
            @confirm="handleLogoutAll"
          >
            <a-button danger size="small" style="margin-top: 8px" :loading="loggingOutAll">
              退出所有设备（含本机）
            </a-button>
          </a-popconfirm>

          <p class="session-note">
            本机凭据会被服务端作废。当「退出登录」因服务异常没生效时，用这个可以强制下线。
          </p>
        </a-card>
      </a-tab-pane>

      <!-- ====== Tab 3: 通知偏好 ====== -->
      <a-tab-pane key="notifications" tab="通知偏好">
        <a-card :bordered="false" class="notification-card">
          <a-form layout="vertical">
            <div class="notify-section">
              <h4>邮件通知</h4>
              <div class="notify-item">
                <span>用量预警（达到 80% 时提醒）</span>
                <a-switch v-model:checked="notifForm.usageAlert" />
              </div>
              <div class="notify-item">
                <span>账单通知（扣款/到期前提醒）</span>
                <a-switch v-model:checked="notifForm.billingAlert" />
              </div>
              <div class="notify-item">
                <span>产品动态报告（每周摘要）</span>
                <a-switch v-model:checked="notifForm.weeklyReport" />
              </div>
              <div class="notify-item">
                <span>系统更新公告</span>
                <a-switch v-model:checked="notifForm.systemUpdate" />
              </div>
            </div>

            <a-divider />

            <div class="notify-section">
              <h4>站内消息</h4>
              <div class="notify-item">
                <span>任务完成通知</span>
                <a-switch v-model:checked="notifForm.taskComplete" />
              </div>
              <div class="notify-item">
                <span>Agent 对话异常告警</span>
                <a-switch v-model:checked="notifForm.agentError" />
              </div>
            </div>

            <a-form-item style="margin-top: 20px">
              <a-button type="primary" :loading="savingNotif" @click="handleSaveNotifications">
                保存偏好设置
              </a-button>
            </a-form-item>
          </a-form>
        </a-card>
      </a-tab-pane>

      <!-- ====== Tab 4: 交互偏好 ====== -->
      <a-tab-pane key="preferences" tab="交互偏好">
        <a-card :bordered="false" class="notification-card">
          <div class="notify-section">
            <h4>翻译</h4>
            <div class="pref-item">
              <div class="pref-text">
                <span class="pref-title">选中文字后自动弹出翻译</span>
                <p class="pref-desc">
                  在平台任意页面选中英文内容即自动翻译并弹出译文。关闭后不再自动弹窗，
                  仍可点击商品标题旁的「译」按钮手动翻译。
                </p>
              </div>
              <a-switch v-model:checked="autoTranslate" />
            </div>
          </div>
        </a-card>
      </a-tab-pane>

      <!-- ====== Tab 5: 店铺管理 ====== -->
      <a-tab-pane key="shops" tab="店铺管理">
        <a-card :bordered="false" title="我的店铺">
          <template #extra>
            <a-button type="primary" @click="showAddShop = true">
              <PlusOutlined /> 添加店铺
            </a-button>
          </template>

          <a-list :data-source="shops" :loading="shopsLoading">
            <template #renderItem="{ item }">
              <a-list-item>
                <a-list-item-meta :title="item.name" :description="getPlatformLabel(item.platform)">
                  <template #avatar>
                    <a-avatar :style="{ backgroundColor: getPlatformColor(item.platform) }">
                      {{ getPlatformIcon(item.platform) }}
                    </a-avatar>
                  </template>
                </a-list-item-meta>
                <template #actions>
                  <!-- ★ 第 318 轮：状态从「两态」改成「三态」。
                       改造前是 `item.is_connected ? '已连接' : '未连接'`，而这个字段
                       后端**根本没返回**（普通 @property 不进 model_dump）
                       ⇒ 永远渲染「未连接」，用户以为界面坏了。 -->
                  <a-tag :color="connectTagColor(item)" :title="connectHint(item)">
                    {{ connectLabel(item) }}
                  </a-tag>
                  <a-button size="small" @click="openConnect(item)">
                    {{ isConnected(item) ? '重新配置' : '连接平台' }}
                  </a-button>
                  <a-popconfirm
                    v-if="isConnected(item) || hasCredentials(item)"
                    title="断开连接会同时清除已保存的凭据，确定吗？"
                    @confirm="handleDisconnect(item.id)"
                  >
                    <a-button size="small" type="text" danger>断开</a-button>
                  </a-popconfirm>
                  <a-popconfirm title="确定删除此店铺？" @confirm="handleDeleteShop(item.id)">
                    <a-button size="small" type="text" danger>删除</a-button>
                  </a-popconfirm>
                </template>
              </a-list-item>
            </template>
          </a-list>

          <a-empty v-if="!shopsLoading && shops.length === 0" description="还没有添加店铺">
            <a-button type="primary" @click="showAddShop = true">立即添加</a-button>
          </a-empty>
        </a-card>

        <!-- 平台连接弹窗（★ 第 318 轮）：一套通用组件吃下全部平台，
             表单字段由后端 `GET /stores/{id}/connect/schema` 驱动。 -->
        <ShopConnectModal
          v-model:open="showConnect"
          :shop="connectTarget"
          @connected="loadShops"
        />
      </a-tab-pane>

      <!-- ====== Tab 6: 客服语音（附加模块，可插拔）======
           由总开关控制：前端 VITE_VOICE_CLONE_ENABLED + 后端 VOICE_CLONE_ENABLED。
           关闭时本 Tab **整个不渲染**（不是渲染后显示空态）—— 让「拔掉」在前端也真成立：
           用户不会看到一个点进去是空的入口。
           开启方式：frontend/.env.local 设 VITE_VOICE_CLONE_ENABLED=true，
           同时 backend/.env 设 VOICE_CLONE_ENABLED=true 与 PUBLIC_BASE_URL。 -->
      <a-tab-pane v-if="VOICE_CLONE_ENABLED" key="voice" tab="客服语音">
        <VoiceClonePanel />
      </a-tab-pane>
    </a-tabs>

    <!-- ====== 创建 API Key 弹窗 ====== -->
    <a-modal :width="WINDOW_W.md"
      v-model:open="showCreateKeyModal"
      title="创建 API 密钥"
      @ok="handleCreateKey"
      :confirm-loading="creatingKey"
    >
      <a-form layout="vertical">
        <a-form-item label="密钥名称" required>
          <a-input v-model:value="newKeyName" placeholder="如：生产环境、测试环境" />
        </a-form-item>
        <a-alert type="warning" show-icon message="创建后请立即复制密钥，之后无法再查看完整值" />
      </a-form>
    </a-modal>

    <!-- ====== 创建后显示完整密钥弹窗 ====== -->
    <a-modal :width="WINDOW_W.md"
      v-model:open="showNewKeyModal"
      title="API 密钥已创建"
      :footer="null"
    >
      <a-alert type="success" show-icon message="请立即复制以下密钥，关闭后将无法再次查看" />
      <a-input :value="newKeyValue" readonly style="margin-top: 12px">
        <template #addonAfter>
          <a-button type="link" size="small" @click="copyToClipboard(newKeyValue)">复制</a-button>
        </template>
      </a-input>
    </a-modal>

    <!-- ====== 添加店铺弹窗 ====== -->
    <a-modal :width="WINDOW_W.md"
      v-model:open="showAddShop"
      title="添加店铺"
      @ok="handleAddShop"
    >
      <a-form layout="vertical">
        <a-form-item label="店铺名称" required>
          <a-input v-model:value="shopForm.name" placeholder="如：Amazon 美国店" />
        </a-form-item>
        <a-form-item label="平台类型" required>
          <a-select v-model:value="shopForm.platform" placeholder="选择平台">
            <a-select-opt-group label="Amazon">
              <a-select-option value="amazon_us">Amazon 美国</a-select-option>
              <a-select-option value="amazon_uk">Amazon 英国</a-select-option>
              <a-select-option value="amazon_de">Amazon 德国</a-select-option>
              <a-select-option value="amazon_jp">Amazon 日本</a-select-option>
            </a-select-opt-group>
            <a-select-opt-group label="Shopee">
              <a-select-option value="shopee_my">Shopee 马来西亚</a-select-option>
              <a-select-option value="shopee_tw">Shopee 台湾</a-select-option>
              <a-select-option value="shopee_ph">Shopee 菲律宾</a-select-option>
              <a-select-option value="shopee_th">Shopee 泰国</a-select-option>
              <a-select-option value="shopee_sg">Shopee 新加坡</a-select-option>
              <a-select-option value="shopee_vn">Shopee 越南</a-select-option>
              <a-select-option value="shopee_id">Shopee 印尼</a-select-option>
              <a-select-option value="shopee_br">Shopee 巴西</a-select-option>
            </a-select-opt-group>
            <a-select-opt-group label="其他">
              <a-select-option value="tiktok">TikTok Shop</a-select-option>
              <a-select-option value="shopify">Shopify 独立站</a-select-option>
            </a-select-opt-group>
          </a-select>
        </a-form-item>
      </a-form>
    </a-modal>
  </a-drawer>
</template>

<script setup lang="ts">
import { WINDOW_W } from '@/config/layout'
import { SEM } from '@/theme/semantic'
import { VOICE_CLONE_ENABLED } from '@/config/featureFlags'
import { ref, reactive, computed, onMounted } from 'vue'
import { message } from 'ant-design-vue'
import {
  MailOutlined,
  PhoneOutlined,
  BankOutlined,
  PlusOutlined,
} from '@ant-design/icons-vue'
import { useUserStore } from '@/stores/user'
import { useShopStore } from '@/stores/shop'
import { get, post, put, del } from '@/api/request'
import { useRouter } from 'vue-router'
import { logoutAll } from '@/api/auth'
import { resetSessionContext } from '@/utils/sessionContext'
import {
  fetchStores,
  createShop,
  deleteShop as apiDeleteShop,
  disconnectPlatform,
  shopConnectState,
} from '@/api/stores'
import { useSelectionTranslate } from '@/composables/useSelectionTranslate'
// 附加模块：客服语音（可插拔，宿主只加这一行 import + 一个 tab-pane）
import VoiceClonePanel from '@/components/Settings/VoiceClonePanel.vue'
import ShopConnectModal from '@/components/Settings/ShopConnectModal.vue'

/**
 * ★★ 「路由模式」（第 323 轮）：本组件既是 Workspace 里的抽屉，又是 `/settings` 页面。
 *    判定依据是 **`open` 是否缺席**：传了 ⇒ 受控抽屉；没传 ⇒ 路由页面，自行打开。
 *
 *    ⚠️ 坑（本轮实测踩到）：`defineProps<{ open?: boolean }>()` 这种**纯类型声明**，
 *    编译出的运行时 prop 类型是 `Boolean`，而 Vue 对 Boolean prop 有一条
 *    **缺席强制转换**：没传、又没写默认值 ⇒ 值被写成 `false`，**不是 `undefined`**。
 *    ⇒ `props.open === undefined` 恒假、`props.open ?? true` 恒为 `false`，
 *      「没传就自行打开」这层意图**永远不会生效**（`/memory` 此前就是这么白屏的）。
 *    解法：`withDefaults(..., { open: undefined })` 显式给一个 `undefined` 默认值 ——
 *    Vue 只在 `!hasOwn(prop, 'default')` 时才做那条转换，给了默认值就跳过。
 */
const props = withDefaults(defineProps<{ open?: boolean }>(), { open: undefined })
const emit = defineEmits<{
  (e: 'update:open', val: boolean): void
}>()

const ROUTE_MODE = props.open === undefined
/** 路由模式下由本组件自己持有开关（没有父组件可接管）。 */
const innerOpen = ref(ROUTE_MODE)
const drawerOpen = computed(() => (ROUTE_MODE ? innerOpen.value : !!props.open))

/**
 * 关闭语义分两路：
 *   · 抽屉模式：照旧把 `update:open` 抛给 `Workspace.vue`；
 *   · 路由模式：**退回工作台**。停在原地的话，用户会落在一条只剩背景色的
 *     空白路由上 —— 那正是第 323 轮修掉的东西。
 */
function handleOpenChange(val: boolean) {
  if (ROUTE_MODE) {
    if (!val) {
      router.push('/')
      return
    }
    innerOpen.value = val
    return
  }
  emit('update:open', val)
}

const userStore = useUserStore()
const shopStore = useShopStore()

// ====== Tab 控制 ======
const activeTab = ref('profile')

// ====== 交互偏好 ======
// 开关状态是模块级单例（在 useSelectionTranslate 里），浮层组件读的是同一份，
// 所以这里改完立即生效，不需要「保存」按钮。
const { autoEnabled, setAutoEnabled } = useSelectionTranslate()

/**
 * 不直接把 autoEnabled 绑到 a-switch：必须走 setAutoEnabled，
 * 否则「关掉时收起已开浮层」和「写入 localStorage」两步都会丢。
 */
const autoTranslate = computed({
  get: () => autoEnabled.value,
  set: (v: boolean) => setAutoEnabled(v),
})

// ====== 个人资料 ======
const savingProfile = ref(false)
const profileForm = reactive({
  name: userStore.userName || '',
  email: userStore.userEmail || '',
  // ★ 从后端带回的资料回填（此前恒为空字符串 ⇒ 即使后端存了也看不见）
  phone: userStore.user?.phone || '',
  company: userStore.user?.company || '',
})

const avatarInputRef = ref<HTMLInputElement | null>(null)

function resetProfileForm() {
  profileForm.name = userStore.userName || ''
  profileForm.phone = userStore.user?.phone || ''
  profileForm.company = userStore.user?.company || ''
}

async function handleSaveProfile() {
  if (!profileForm.name.trim()) {
    message.warning('用户名不能为空')
    return
  }
  savingProfile.value = true
  try {
    const res: any = await put('/users/profile', {
      name: profileForm.name,
      phone: profileForm.phone,
      company: profileForm.company,
    })
    message.success('资料更新成功')
    // ★ 用后端返回的**完整** user 覆盖 store（只改 name 会让 phone/company
    //   在界面上停留在旧值，看起来像没保存成功）
    if (res?.user) userStore.setUser(res.user)
  } catch (err: any) {
    message.error(err?.response?.data?.detail || '保存失败')
  } finally {
    savingProfile.value = false
  }
}

function handleAvatarClick() {
  avatarInputRef.value?.click()
}

async function handleAvatarChange(e: Event) {
  const file = (e.target as HTMLInputElement).files?.[0]
  if (!file) return

  const formData = new FormData()
  formData.append('avatar', file)

  try {
    const res: any = await post('/users/avatar', formData, {
      headers: { 'Content-Type': 'multipart/form-data' },
    })
    message.success('头像更新成功')
    userStore.updateAvatar(res.avatar_url)
  } catch (err: any) {
    message.error(err?.response?.data?.detail || '上传失败')
  }
}

// ====== 安全设置 - 密码 ======
const changingPassword = ref(false)
const passwordForm = reactive({
  current: '',
  newPwd: '',
  confirm: '',
})

async function handleChangePassword() {
  if (!passwordForm.current || !passwordForm.newPwd || !passwordForm.confirm) {
    message.warning('请填写完整的密码信息')
    return
  }
  if (passwordForm.newPwd !== passwordForm.confirm) {
    message.error('两次输入的新密码不一致')
    return
  }
  if (passwordForm.newPwd.length < 8) {
    message.error('新密码至少需要8位')
    return
  }

  changingPassword.value = true
  try {
    // ★ 路径是 /auth/change-password（曾经写成 /users/change-password ⇒ 404 断链）
    // ★ silentError: true —— 本调用点**自己**负责全部回执：
    //   成功在下面弹「密码修改成功…」，失败在 catch 里弹 detail。
    //   不声明的话，同一个原因会被拦截器再弹一次
    //   （成功提示自第 267 轮起拦截器已不再自动弹）。
    const res: any = await post(
      '/auth/change-password',
      {
        current_password: passwordForm.current,
        new_password: passwordForm.newPwd,
      },
      { silentError: true }
    )
    // ★ 必须消费返回的新 token 对：改密会提升 token_version，
    //   当前这枚 token 同时失效；不换发的话用户改完密码立刻掉线。
    userStore.applyTokenPair(res?.access_token, res?.refresh_token)
    message.success('密码修改成功，其他设备的登录已失效')
    passwordForm.current = ''
    passwordForm.newPwd = ''
    passwordForm.confirm = ''
  } catch (err: any) {
    message.error(err?.response?.data?.detail || '修改失败')
  } finally {
    changingPassword.value = false
  }
}

// ====== 安全设置 - API Keys ======
interface ApiKey {
  id: string
  name: string
  key: string
  is_active: boolean
  created_at: string
  last_used_at: string | null
}

const apiKeys = ref<ApiKey[]>([])
const showCreateKeyModal = ref(false)
const showNewKeyModal = ref(false)
const creatingKey = ref(false)
const newKeyName = ref('')
const newKeyValue = ref('')

// ★ `maskApiKey` / `handleCopyKey` 已删除（第 100 轮）：
//   掩码由**后端**生成（库里只有 sha256，前端拿不到"前 7 位"这种信息），
//   列表直接回显 `key.key` 即可；复制掩码串没有意义。

function copyToClipboard(text: string) {
  navigator.clipboard.writeText(text).then(() => {
    message.success('已复制到剪贴板')
  }).catch(() => {
    message.error('复制失败')
  })
}

async function handleCreateKey() {
  if (!newKeyName.value.trim()) {
    message.warning('请输入密钥名称')
    return
  }

  creatingKey.value = true
  try {
    const res: any = await post('/users/api-keys', { name: newKeyName.value })
    newKeyValue.value = res.key
    showCreateKeyModal.value = false
    showNewKeyModal.value = true
    newKeyName.value = ''
    await loadApiKeys()
  } catch (err: any) {
    message.error(err?.response?.data?.detail || '创建失败')
  } finally {
    creatingKey.value = false
  }
}

async function handleDeleteKey(keyId: string) {
  try {
    await del(`/users/api-keys/${keyId}`)
    message.success('密钥已删除')
    await loadApiKeys()
  } catch (err: any) {
    message.error(err?.response?.data?.detail || '删除失败')
  }
}

async function loadApiKeys() {
  try {
    const res: any = await get('/users/api-keys')
    apiKeys.value = res.api_keys || []
  } catch (e) {
    // ★ 不喂 Mock 数据：虚构出一条"生产环境 sk-demo-…"会让用户以为
    //   自己真有这么一把密钥（老板铁律：空状态优于虚构默认）。
    console.warn('加载 API Keys 失败:', e)
    apiKeys.value = []
  }
}

// ====== 通知偏好 ======
const savingNotif = ref(false)
// ★ 初值取自后端带回的偏好，只在缺项时用默认值。
//   写死默认值的后果：用户关掉的开关，刷新页面后自己又打开了。
// ★ 用 `??` 而不是 `||` —— `||` 会把用户显式关掉的 `false` 当成"没值"再套上默认 `true`，
//   表现为"这个开关永远关不掉"（本项目已有同族判据：`x || 默认值` 把填 0 变默认）。
const _userPrefs = userStore.user?.notification_prefs || {}
const notifForm = reactive({
  usageAlert: _userPrefs.usageAlert ?? true,
  billingAlert: _userPrefs.billingAlert ?? true,
  weeklyReport: _userPrefs.weeklyReport ?? false,
  systemUpdate: _userPrefs.systemUpdate ?? true,
  taskComplete: _userPrefs.taskComplete ?? true,
  agentError: _userPrefs.agentError ?? true,
})

async function handleSaveNotifications() {
  savingNotif.value = true
  try {
    const res: any = await put('/users/notifications', notifForm)
    message.success('偏好设置已保存')
    // ★ 后端返回的是补齐后的**完整**六项 —— 用它与 store 对齐，
    //   下次进设置页时初值就是刚保存的这份。
    if (res?.prefs && userStore.user) {
      userStore.setUser({ ...userStore.user, notification_prefs: res.prefs })
    }
  } catch (err: any) {
    message.error(err?.response?.data?.detail || '保存失败')
  } finally {
    savingNotif.value = false
  }
}

// ====== 店铺管理（统一到 /api/v1/stores，与左侧「店铺群」共用数据源）======
const shops = ref<any[]>([])
const shopsLoading = ref(false)
const showAddShop = ref(false)
const shopForm = reactive({ name: '', platform: undefined as string | undefined })

function getPlatformLabel(platform: string): string {
  const labels: Record<string, string> = {
    amazon_us: 'Amazon 美国', amazon_uk: 'Amazon 英国', amazon_de: 'Amazon 德国', amazon_jp: 'Amazon 日本',
    shopee_my: 'Shopee 马来西亚', shopee_tw: 'Shopee 台湾', shopee_ph: 'Shopee 菲律宾',
    shopee_th: 'Shopee 泰国', shopee_sg: 'Shopee 新加坡', shopee_vn: 'Shopee 越南',
    shopee_id: 'Shopee 印尼', shopee_br: 'Shopee 巴西',
    temu: 'Temu', temu_us: 'Temu 美国', temu_uk: 'Temu 英国', temu_de: 'Temu 德国',
    tiktok: 'TikTok Shop', shopify: 'Shopify 独立站',
  }
  return labels[platform] || platform
}

function getPlatformColor(platform: string): string {
  const colors: Record<string, string> = {
    amazon_us: '#FF9900', amazon_uk: '#FF9900', amazon_de: '#FF9900', amazon_jp: '#FF9900',
    shopee_my: '#EE4D2D', shopee_tw: '#EE4D2D', shopee_ph: '#EE4D2D',
    shopee_th: '#EE4D2D', shopee_sg: '#EE4D2D', shopee_vn: '#EE4D2D',
    shopee_id: '#EE4D2D', shopee_br: '#EE4D2D',
    temu: '#FF5A00', temu_us: '#FF5A00', temu_uk: '#FF5A00', temu_de: '#FF5A00',
    tiktok: '#000000',
    shopify: '#95BF47',
  }
  return colors[platform] || SEM.primary
}

function getPlatformIcon(platform: string): string {
  const icons: Record<string, string> = {
    amazon_us: 'A', amazon_uk: 'A', amazon_de: 'A', amazon_jp: 'A',
    shopee_my: 'S', shopee_tw: 'S', shopee_ph: 'S', shopee_th: 'S',
    shopee_sg: 'S', shopee_vn: 'S', shopee_id: 'S', shopee_br: 'S',
    temu: 'T', temu_us: 'T', temu_uk: 'T', temu_de: 'T',
    tiktok: 'T',
    shopify: 'Sh',
  }
  return icons[platform] || '?'
}

async function loadShops() {
  shopsLoading.value = true
  try {
    const res = await fetchStores()
    shops.value = res.stores || []
    shopStore.setShopList(res.stores || [])
  } catch (e) {
    console.warn('[Demo Mode] 加载店铺失败，使用空列表', e)
    shops.value = []
  } finally {
    shopsLoading.value = false
  }
}

async function handleAddShop() {
  if (!shopForm.name || !shopForm.platform) {
    message.warning('请填写完整信息')
    return
  }
  try {
    await createShop({ name: shopForm.name, platform: shopForm.platform })
    message.success('店铺添加成功')
    showAddShop.value = false
    shopForm.name = ''
    shopForm.platform = undefined
    await loadShops()
  } catch (err: any) {
    message.error(err?.response?.data?.detail || '添加失败')
  }
}

async function handleDeleteShop(shopId: string) {
  try {
    await apiDeleteShop(shopId)
    message.success('店铺已删除')
    await loadShops()
  } catch (err: any) {
    message.error(err?.response?.data?.detail || '删除失败')
  }
}

// ====== 平台连接（★ 第 318 轮：从「没有入口」到「能连、能断、能看状态」）======
//
// ★★ 状态判定的**唯一真源**是 `shopConnectState()`（`@/api/stores`）。
//    它把后端的 `is_connected`（凭据已验证）与 `has_credentials`（库里有凭据）
//    收敛成一个三态。**不要**在模板里各写一个三元表达式 ——
//    同一个判定写两处，改一处漏一处时两个界面对同一家店显示不同状态，
//    而且两边都不报错。
const showConnect = ref(false)
const connectTarget = ref<any>(null)

const isConnected = (s: any) => shopConnectState(s) === 'connected'
const hasCredentials = (s: any) => !!s?.has_credentials

function connectLabel(s: any): string {
  switch (shopConnectState(s)) {
    case 'connected':
      return '已连接'
    case 'configured':
      return '已配置（未验证）'
    default:
      return '未连接'
  }
}

function connectTagColor(s: any): string {
  switch (shopConnectState(s)) {
    case 'connected':
      return 'green'
    case 'configured':
      return 'orange'
    default:
      return 'default'
  }
}

/**
 * 状态点的悬浮说明 —— 把「为什么不是已连接」讲清楚。
 *
 * ★ 「已配置（未验证）」这一档最容易被误解成"连接失败了，白填了"。
 *   它实际有两种成因，且都不是用户的错：网络/平台暂时不可达，或该平台
 *   尚未接入自动校验（如 TikTok）。用户需要知道凭据**已经存下来了**。
 */
function connectHint(s: any): string {
  switch (shopConnectState(s)) {
    case 'connected':
      return '凭据已通过平台校验'
    case 'configured':
      return '凭据已加密保存，但尚未通过平台校验（网络不通，或该平台暂未接入自动校验）。可点「连接平台」重试验证。'
    default:
      return '还没有配置平台凭据 —— 点「连接平台」填写'
  }
}

function openConnect(shop: any) {
  connectTarget.value = shop
  showConnect.value = true
}

async function handleDisconnect(shopId: string) {
  try {
    await disconnectPlatform(shopId)
    message.success('已断开连接，已保存的凭据已清除')
    await loadShops()
  } catch (err: any) {
    message.error(err?.response?.data?.detail || '断开失败')
  }
}

// ====== 工具函数 ======
function formatTime(time: string | null): string {
  if (!time) return '-'
  return new Date(time).toLocaleString('zh-CN')
}

function formatDate(time: string | null): string {
  if (!time) return '-'
  return new Date(time).toLocaleDateString('zh-CN')
}

// ====== 生命周期 ======
onMounted(async () => {
  await Promise.all([loadApiKeys(), loadShops()])
})

// ============================================================================
// 登录会话 —— 退出所有设备（★ 台账 #1154）
// ============================================================================

const router = useRouter()

/**
 * 当前设备标签。
 *
 * ★ 只做粗粒度识别：这里不需要精确到版本号，"不是我的浏览器 / 不是我的系统"
 *   才是用户在意的信号。
 * ★ 判定顺序不能换：Edge 的 UA 里含 `Chrome`、Chrome 的 UA 里含 `Safari`，
 *   所以必须先判 Edg / OPR，再判 Chrome，最后才轮到 Safari。
 */
const currentDeviceLabel = computed(() => {
  const ua = typeof navigator === 'undefined' ? '' : navigator.userAgent
  const browser = /Edg\//.test(ua)
    ? 'Edge'
    : /OPR\//.test(ua)
      ? 'Opera'
      : /Firefox\//.test(ua)
        ? 'Firefox'
        : /Chrome\//.test(ua)
          ? 'Chrome'
          : /Safari\//.test(ua)
            ? 'Safari'
            : '未知浏览器'
  const os = /Windows/.test(ua)
    ? 'Windows'
    : /Mac OS X/.test(ua)
      ? 'macOS'
      : /Android/.test(ua)
        ? 'Android'
        : /iPhone|iPad|iPod/.test(ua)
          ? 'iOS'
          : /Linux/.test(ua)
            ? 'Linux'
            : '未知系统'
  return `本机 - ${browser} / ${os}`
})

const loggingOutAll = ref(false)

/**
 * 退出所有设备。
 *
 * ★ 后端 `/auth/logout-all` 走 DB 的 `token_version`，**不依赖 Redis** ——
 *   它存在的意义就是"当 `/auth/logout` 因 Redis 故障回 503 时，
 *   给用户一条永远可用的出路"。
 * ★ 成功后本机这枚 token 也失效了，所以顺序不能反：
 *   先提示 → 再清本地 → 再清会话上下文 → 最后跳登录页。
 *   少清 `resetSessionContext()` 的后果：团队/店铺上下文被下一个身份继承。
 */
async function handleLogoutAll() {
  loggingOutAll.value = true
  try {
    const res = await logoutAll({ silentError: true })
    message.success(res?.message || '已登出所有设备，请重新登录')
    userStore.clearAuth()
    resetSessionContext()
    router.push('/login')
  } catch (err) {
    const e = err as { response?: { data?: { detail?: unknown } } }
    const detail = e?.response?.data?.detail
    // ★ 失败时**不清本地**：这次调用没成功，本机凭据在服务端仍然有效，
    //   假装已登出只会让用户以为安全了。
    message.error(typeof detail === 'string' && detail ? detail : '操作失败，请稍后重试')
  } finally {
    loggingOutAll.value = false
  }
}
</script>

<style scoped>
.settings-tabs {
  background: transparent;
}

.settings-tabs :deep(.ant-tabs-nav) {
  margin-bottom: var(--space-20);
}

.settings-tabs :deep(.ant-tabs-tab) {
  padding: var(--space-8) var(--space-20);
}

/* 个人资料 */
.profile-card {
  max-width: 560px;
}

.avatar-section {
  display: flex;
  align-items: center;
  gap: var(--space-16);
}

.user-avatar {
  background-color: var(--primary);
  font-size: var(--font-size-32);
  flex-shrink: 0;
}

.form-hint {
  font-size: var(--font-size-11);
  color: var(--text-tertiary);
  margin-top: var(--space-2);
}

/* 安全设置 */
.session-note {
  margin: var(--space-8) 0 0;
  font-size: var(--font-size-12);
  line-height: 1.5;
  color: var(--text-tertiary);
}

.security-card {
  max-width: 600px;
}

.api-key-list {
  display: flex;
  flex-direction: column;
  gap: var(--space-12);
}

.api-key-item {
  border: 1px solid var(--border-base);
  border-radius: var(--radius-6);
  padding: var(--space-12);
}

.key-info {
  display: flex;
  align-items: center;
  gap: var(--space-10);
  margin-bottom: var(--space-6);
}

.key-value {
  background: var(--bg-hover-light);
  padding: var(--space-2) var(--space-8);
  border-radius: var(--radius-4);
  font-size: var(--font-size-12);
  color: var(--text-secondary);
}

.key-meta {
  display: flex;
  gap: var(--space-16);
  font-size: var(--font-size-11);
  color: var(--text-tertiary);
  margin-bottom: var(--space-6);
}

.key-actions {
  display: flex;
  justify-content: flex-end;
}

/* 通知偏好 */
.notification-card {
  max-width: 560px;
}

.notify-section h4 {
  margin-bottom: var(--space-12);
  font-size: var(--font-size-14);
}

.notify-item {
  display: flex;
  justify-content: space-between;
  align-items: center;
  padding: var(--space-10) 0;
  border-bottom: 1px solid #f5f5f5;
}

.notify-item:last-child {
  border-bottom: none;
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
</style>
