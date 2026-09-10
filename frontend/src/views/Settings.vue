<template>
  <a-drawer
    :open="open"
    @update:open="(val: boolean) => $emit('update:open', val)"
    title="账户设置"
    placement="right"
    :width="680"
    :body-style="{ padding: '0', overflow: 'auto' }"
    :destroyOnClose="false"
  >
    <a-tabs v-model:activeKey="activeTab" type="card" class="settings-tabs" style="padding: 16px 20px">
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

          <a-divider style="margin: 16px 0" />

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
                <code class="key-value">{{ maskApiKey(key.key) }}</code>
                <a-tag :color="key.is_active ? 'green' : 'default'">
                  {{ key.is_active ? '活跃' : '已禁用' }}
                </a-tag>
              </div>
              <div class="key-meta">
                <span>创建于 {{ formatDate(key.created_at) }}</span>
                <span>最后使用：{{ key.last_used_at ? formatDate(key.last_used_at) : '从未' }}</span>
              </div>
              <div class="key-actions">
                <a-button size="small" type="link" @click="handleCopyKey(key.key)">复制</a-button>
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
              <a-tag color="blue">本机 - Chrome / Windows</a-tag>
            </a-descriptions-item>
            <a-descriptions-item label="最后登录时间">
              {{ userStore.user?.last_login_at ? formatTime(userStore.user.last_login_at) : '-' }}
            </a-descriptions-item>
          </a-descriptions>
          <a-button danger size="small" style="margin-top: 8px">
            退出所有其他设备
          </a-button>
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
                <a-switch v-model:checked="notifForm.systemUpdate" checked />
              </div>
            </div>

            <a-divider />

            <div class="notify-section">
              <h4>站内消息</h4>
              <div class="notify-item">
                <span>任务完成通知</span>
                <a-switch v-model:checked="notifForm.taskComplete" checked />
              </div>
              <div class="notify-item">
                <span>Agent 对话异常告警</span>
                <a-switch v-model:checked="notifForm.agentError" checked />
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

      <!-- ====== Tab 4: 店铺管理 ====== -->
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
                  <a-tag :color="item.is_connected ? 'green' : 'default'">
                    {{ item.is_connected ? '已连接' : '未连接' }}
                  </a-tag>
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
      </a-tab-pane>
    </a-tabs>

    <!-- ====== 创建 API Key 弹窗 ====== -->
    <a-modal
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
    <a-modal
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
    <a-modal
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
import { ref, reactive, onMounted } from 'vue'
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
import { fetchStores, createShop, deleteShop as apiDeleteShop } from '@/api/stores'

defineProps<{
  open: boolean
}>()
defineEmits<{
  (e: 'update:open', val: boolean): void
}>()

const userStore = useUserStore()
const shopStore = useShopStore()

// ====== Tab 控制 ======
const activeTab = ref('profile')

// ====== 个人资料 ======
const savingProfile = ref(false)
const profileForm = reactive({
  name: userStore.userName || '',
  email: userStore.userEmail || '',
  phone: '',
  company: '',
})

const avatarInputRef = ref<HTMLInputElement | null>(null)

function resetProfileForm() {
  profileForm.name = userStore.userName || ''
  profileForm.phone = ''
  profileForm.company = ''
}

async function handleSaveProfile() {
  if (!profileForm.name.trim()) {
    message.warning('用户名不能为空')
    return
  }
  savingProfile.value = true
  try {
    await put('/users/profile', {
      name: profileForm.name,
      phone: profileForm.phone,
      company: profileForm.company,
    })
    message.success('资料更新成功')
    // 更新 store
    userStore.updateUserName(profileForm.name)
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
    await post('/users/change-password', {
      current_password: passwordForm.current,
      new_password: passwordForm.newPwd,
    })
    message.success('密码修改成功')
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

function maskApiKey(key: string): string {
  if (key.length <= 8) return '****'
  return key.slice(0, 4) + '****' + key.slice(-4)
}

function handleCopyKey(key: string) {
  copyToClipboard(key)
}

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
    console.warn('[Demo Mode] 加载 API Keys 失败，使用 Mock 数据')
    // Mock 数据兜底
    apiKeys.value = [
      {
        id: 'key-demo-001',
        name: '生产环境',
        key: 'sk-demo-xxxx-xxxx-xxxx-xxxxxxxxxxxx',
        is_active: true,
        created_at: '2026-08-15T10:00:00Z',
        last_used_at: '2026-09-01T08:30:00Z',
      },
    ]
  }
}

// ====== 通知偏好 ======
const savingNotif = ref(false)
const notifForm = reactive({
  usageAlert: true,
  billingAlert: true,
  weeklyReport: false,
  systemUpdate: true,
  taskComplete: true,
  agentError: true,
})

async function handleSaveNotifications() {
  savingNotif.value = true
  try {
    await put('/users/notifications', notifForm)
    message.success('偏好设置已保存')
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
  return colors[platform] || '#1890ff'
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
</script>

<style scoped>
.settings-tabs {
  background: transparent;
}

.settings-tabs :deep(.ant-tabs-nav) {
  margin-bottom: 20px;
}

.settings-tabs :deep(.ant-tabs-tab) {
  padding: 8px 20px;
}

/* 个人资料 */
.profile-card {
  max-width: 560px;
}

.avatar-section {
  display: flex;
  align-items: center;
  gap: 16px;
}

.user-avatar {
  background-color: #1890ff;
  font-size: 32px;
  flex-shrink: 0;
}

.form-hint {
  font-size: 11px;
  color: #8c8c8c;
  margin-top: 2px;
}

/* 安全设置 */
.security-card {
  max-width: 600px;
}

.api-key-list {
  display: flex;
  flex-direction: column;
  gap: 12px;
}

.api-key-item {
  border: 1px solid #f0f0f0;
  border-radius: 6px;
  padding: 12px;
}

.key-info {
  display: flex;
  align-items: center;
  gap: 10px;
  margin-bottom: 6px;
}

.key-value {
  background: #f5f5f5;
  padding: 2px 8px;
  border-radius: 4px;
  font-size: 12px;
  color: #595959;
}

.key-meta {
  display: flex;
  gap: 16px;
  font-size: 11px;
  color: #8c8c8c;
  margin-bottom: 6px;
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
  margin-bottom: 12px;
  font-size: 14px;
}

.notify-item {
  display: flex;
  justify-content: space-between;
  align-items: center;
  padding: 10px 0;
  border-bottom: 1px solid #f5f5f5;
}

.notify-item:last-child {
  border-bottom: none;
}
</style>
