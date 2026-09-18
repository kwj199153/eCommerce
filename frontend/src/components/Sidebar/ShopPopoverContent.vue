<template>
  <div class="shop-popover">
    <!-- 头部 -->
    <div class="popover-header">
      <span class="popover-title">🏪 店铺群</span>
      <span class="popover-count">{{ shopList.length }} 个店铺</span>
      <a-button type="link" size="small" @click="openAddModal">
        <PlusOutlined /> 添加
      </a-button>
    </div>

    <!-- 当前归属（★ C 档 2026-09-17）
         列表按归属过滤后，"这是哪个归属下的店铺群"必须显示出来 ——
         否则用户切换后只看到列表变短，不知道发生了什么。
         ★ 标签用中性的「归属」而非「账户」：后端表名与 API 都还是 account，
           而"账户"这个词在界面上会被读成**登录账号**（同一处曾有三个所指）。 -->
    <div v-if="accounts.length > 0" class="popover-account">
      <span class="account-label">归属</span>
      <a-select
        :value="accountStore.currentAccountId ?? undefined"
        size="small"
        style="flex: 1"
        @change="onAccountChange"
      >
        <a-select-option v-for="a in accounts" :key="a.id" :value="a.id">
          {{ a.name }}
        </a-select-option>
      </a-select>
    </div>

    <!-- 店铺列表 -->
    <div class="popover-body">
      <div
        v-for="shop in shopList"
        :key="shop.id"
        class="popover-shop-item"
        :class="{ active: currentShopId === shop.id }"
        @click="handleSelectShop(shop)"
      >
        <div class="item-left">
          <span class="shop-name">{{ shop.name }}</span>
          <a-tag :color="platformColor(shop.platform)" size="small">{{ platformLabel(shop.platform) }}</a-tag>
        </div>
        <div class="item-right">
          <span :class="['status-dot', shop.is_connected ? 'connected' : 'disconnected']"></span>
          <a-tooltip title="编辑">
            <button class="icon-btn" @click.stop="openEditModal(shop)">
              <EditOutlined />
            </button>
          </a-tooltip>
          <a-popconfirm title="确定删除？" ok-text="删除" cancel-text="取消" @confirm="handleDelete(shop)">
            <a-tooltip title="删除">
              <button class="icon-btn danger" @click.stop>
                <DeleteOutlined />
              </button>
            </a-tooltip>
          </a-popconfirm>
        </div>
      </div>

      <!-- 空状态 -->
      <div v-if="shopList.length === 0" class="empty-state">
        <p>暂无店铺</p>
        <span>点击「添加」创建第一个店铺</span>
      </div>
    </div>

    <!-- 添加/编辑弹窗 -->
    <a-modal
      v-model:open="modalVisible"
      :title="isEditing ? '编辑店铺' : '添加店铺'"
      :confirm-loading="submitting"
      @ok="handleSubmit"
      width="480px"
      ok-text="保存"
      cancel-text="取消"
    >
      <a-form :model="formState" :label-col="{ span: 6 }" :wrapper-col="{ span: 16 }">
        <a-form-item label="名称" required>
          <a-input v-model:value="formState.name" placeholder="如：Amazon US Store" :maxlength="50" show-count />
        </a-form-item>
        <a-form-item label="平台" required>
          <a-select v-model:value="formState.platform" placeholder="选择平台站点" :disabled="isEditing" @change="handlePlatformChange">
            <a-select-opt-group label="Amazon">
              <a-select-option value="amazon_us">🇺🇸 Amazon US</a-select-option>
              <a-select-option value="amazon_uk">🇬🇧 Amazon UK</a-select-option>
              <a-select-option value="amazon_de">🇩🇪 Amazon DE</a-select-option>
              <a-select-option value="amazon_jp">🇯🇵 Amazon JP</a-select-option>
            </a-select-opt-group>
            <a-select-opt-group label="Shopee">
              <a-select-option value="shopee_my">🇲🇾 Shopee MY</a-select-option>
              <a-select-option value="shopee_tw">🇹🇼 Shopee TW</a-select-option>
              <a-select-option value="shopee_ph">🇵🇭 Shopee PH</a-select-option>
              <a-select-option value="shopee_th">🇹🇭 Shopee TH</a-select-option>
              <a-select-option value="shopee_sg">🇸🇬 Shopee SG</a-select-option>
              <a-select-option value="shopee_vn">🇻🇳 Shopee VN</a-select-option>
              <a-select-option value="shopee_id">🇮🇩 Shopee ID</a-select-option>
              <a-select-option value="shopee_br">🇧🇷 Shopee BR</a-select-option>
            </a-select-opt-group>
            <a-select-opt-group label="其他">
              <a-select-option value="tiktok">TikTok Shop</a-select-option>
              <a-select-option value="shopify">Shopify</a-select-option>
            </a-select-opt-group>
          </a-select>
        </a-form-item>
        <!-- ★ A 档 2026-09-17：建店 / 改归属都收在这一项里。
             新建：不选 ⇒ 后端建到你的**默认容器**
                   （判据：你名下最早创建的那个，见后端 `ensure_default_account`）。
             编辑：改选 ⇒ 保存后调**转移端点**（源侧 + 目标侧各一道能力门）。
             改造前这一项只在新建时出现，「转移」在界面上根本没有入口 ——
             于是"新建团队"又变回空壳（用户建完团队却搬不进店）。 -->
        <a-form-item v-if="accounts.length > 0" label="归属">
          <a-select
            v-model:value="formState.account_id"
            :placeholder="isEditing ? '不修改：保持原归属' : '默认：你最早的团队'"
            allow-clear
          >
            <a-select-option v-for="a in accounts" :key="a.id" :value="a.id">
              {{ a.name }}
            </a-select-option>
          </a-select>
          <div class="form-hint">
            {{ isEditing
              ? '改选后保存 = 把店铺转移过去（需源、目标两侧都有建店权限）'
              : '不选则建到默认团队；选其它团队需有建店权限' }}
          </div>
        </a-form-item>
        <a-form-item label="备注">
          <a-textarea v-model:value="formState.description" placeholder="可选" :rows="2" :maxlength="200" />
        </a-form-item>
      </a-form>
    </a-modal>
  </div>
</template>

<script setup lang="ts">
import { ref, reactive, computed, onMounted } from 'vue'
import { PlusOutlined, EditOutlined, DeleteOutlined } from '@ant-design/icons-vue'
import { message } from 'ant-design-vue'
import { useShopStore } from '@/stores/shop'
import { useAccountStore } from '@/stores/account'
import { createShop, fetchStores, updateShop as apiUpdateShop, deleteShop as apiDeleteShop, transferStore } from '@/api/stores'
import type { Shop } from '@/stores/shop'

const emit = defineEmits<{
  (e: 'close'): void
}>()

const shopStore = useShopStore()
const accountStore = useAccountStore()
const accounts = computed(() => accountStore.accounts)
const currentShopId = computed(() => shopStore.currentShop?.id || '')

// ★ C 档 2026-09-17：列表**按当前账户过滤**（真源在 account store）。
//   改造前这里是 `shopStore.shopList`（后端返回的全部可见店铺）——
//   于是切换账户后列表纹丝不动，「当前账户」在界面上完全不可感知。
//   ⚠️ 未选账户（含演示模式）时 `shopsOfCurrentAccount` 返回**全部**，
//      宁可不过滤也不误伤（见 account store 的注释）。
const shopList = computed(() => accountStore.shopsOfCurrentAccount)

/** 切换账户：account store 内部会把"当前店铺"校正到新账户内 */
const onAccountChange = (id: string) => accountStore.setCurrentAccount(id)

// Modal
const modalVisible = ref(false)
const isEditing = ref(false)
const submitting = ref(false)
const formState = reactive({ id: '', name: '', platform: '', currency: '', description: '', account_id: '' })

/**
 * 编辑开始时的归属（★ A 档）。
 *
 * 存在的理由：编辑弹窗里改选「归属」= **转移**，必须与「保持原样」区分开。
 * 若直接拿 `formState.account_id` 去比对，用户在编辑弹窗里"什么都没动"也会
 * 判定为变更；而且后端 transfer 虽然幂等，也没必要为一堆无操作发请求。
 */
const originalAccountId = ref('')

const PLATFORM_CURRENCY_MAP: Record<string, string> = {
  amazon_us: 'USD', amazon_uk: 'GBP', amazon_de: 'EUR', amazon_jp: 'JPY',
  shopee_my: 'MYR', shopee_tw: 'TWD', shopee_ph: 'PHP', shopee_th: 'THB',
  shopee_sg: 'SGD', shopee_vn: 'VND', shopee_id: 'IDR', shopee_br: 'BRL',
  tiktok: 'USD', shopify: 'USD',
}

const platformLabel = (p: string) => ({ amazon_us: 'US', amazon_uk: 'UK', amazon_de: 'DE', amazon_jp: 'JP', shopee_my: 'MY', shopee_tw: 'TW', shopee_ph: 'PH', shopee_th: 'TH', shopee_sg: 'SG', shopee_vn: 'VN', shopee_id: 'ID', shopee_br: 'BR', tiktok: 'TK', shopify: 'SF' }[p] || p)
const platformColor = (p: string) => p.startsWith('amazon') ? 'orange' : p.startsWith('shopee') ? 'green' : p === 'tiktok' ? 'blue' : 'purple'

const handleSelectShop = (shop: Shop) => { shopStore.setCurrentShop(shop) }

const openAddModal = () => { isEditing.value = false; resetForm(); modalVisible.value = true }
const openEditModal = (shop: Shop) => {
  isEditing.value = true
  formState.id = shop.id; formState.name = shop.name; formState.platform = shop.platform
  formState.currency = shop.currency || PLATFORM_CURRENCY_MAP[shop.platform] || ''
  formState.description = (shop as any).description || ''
  // ★ A 档：回填当前归属，并记下原值用于判断"这次到底改没改归属"
  formState.account_id = shop.account_id || ''
  originalAccountId.value = shop.account_id || ''
  modalVisible.value = true
}
const resetForm = () => {
  formState.id = ''; formState.name = ''; formState.platform = ''
  formState.currency = ''; formState.description = ''
  // ★ A 档：默认留空 = 建到你的**默认容器**（而不是预填当前选中项 ——
  //   预填会让"切到某个团队后随手建的店"静默落进那个团队）。
  formState.account_id = ''
  originalAccountId.value = ''
}
const handlePlatformChange = (v: string) => { formState.currency = PLATFORM_CURRENCY_MAP[v] || 'USD' }

const handleSubmit = async () => {
  if (!formState.name.trim()) return message.warning('请输入店铺名称')
  if (!formState.platform) return message.warning('请选择平台')
  submitting.value = true
  try {
    const payload = {
      name: formState.name.trim(),
      platform: formState.platform,
      currency: formState.currency,
      description: formState.description.trim() || undefined,
      // ★ A 档：仅在**新建**时携带；编辑不改归属（转移走独立端点 + 两道门）
      account_id: isEditing.value ? undefined : (formState.account_id || undefined),
    }
    if (isEditing.value && formState.id) {
      await apiUpdateShop(formState.id, payload)
      // ★ A 档：编辑弹窗里改选账户 ⇒ 调**转移端点**。
      //   刻意**不**把 account_id 塞进 updateShop 的 payload（上面已置 undefined）：
      //   归属变更带两道能力门（源侧 + 目标侧），只有 `/transfer` 会校验；
      //   混进 update 就等于把门禁绕过去了。
      const target = formState.account_id || ''
      if (target && target !== originalAccountId.value) {
        await transferStore(formState.id, target)
      }
      message.success('已更新')
    } else {
      const res = await createShop(payload)
      message.success(`"${(res as any).name}" 已创建`)
      const newShop = shopList.value.find(s => s.name === formState.name)
      if (newShop) {
        shopStore.setCurrentShop(newShop)
      } else {
        // ★ A 档：建到了**其它**归属 ⇒ 当前列表按归属过滤，看不见它。
        //   必须显式说一声，否则用户以为创建失败（本轮教训：不要静默）。
        //   ★ 第 110 轮（重要）：落点**直接读建店响应里的 `account_id`**，
        //     不在前端推算"默认容器"。推算 = 后端 `ensure_default_account()`
        //     判据的第二份实现，而「同一判定两份实现 ⇒ 至少一份永远测不到」
        //     是本项目吃过亏的形态。响应里有真值就别猜。
        const landedId =
          (res as { account_id?: string | null }).account_id || formState.account_id
        const landed = accounts.value.find(a => a.id === landedId)
        message.info(`已建在「${landed?.name || '其它归属'}」下，切换后即可看到`)
      }
    }
    await refreshShopList()
    modalVisible.value = false
  } catch (e: any) {
    message.error(e?.response?.data?.detail || e?.message || '操作失败')
  } finally { submitting.value = false }
}

const handleDelete = async (shop: Shop) => {
  try {
    await apiDeleteShop(shop.id)
    message.success('已删除')
    await refreshShopList()
  } catch (e: any) { message.error(e?.response?.data?.detail || e?.message || '删除失败') }
}

/**
 * 刷新店铺列表。
 *
 * 用途：**增 / 删 / 改店铺后**让列表跟上（打开弹层时也顺手刷新一次）。
 *
 * 注：启动期的首次加载已由 `Workspace.vue` 的 `shopStore.ensureShopsLoaded()` 负责，
 *     这里不再是唯一填充点。此前的写法 `res.shops || res.stores` 是笔误 ——
 *     `fetchStores()` 只返回 `{ stores, total }`，没有 `shops` 字段（恒 undefined）。
 */
const refreshShopList = async () => {
  try {
    const res = await fetchStores()
    if (res?.stores) shopStore.setShopList(res.stores)
  } catch (e) { console.error('刷新店铺列表失败:', e) }
}

onMounted(async () => { await refreshShopList() })
</script>

<style scoped>
.shop-popover { display: flex; flex-direction: column; gap: 0; }

.popover-header {
  display: flex; align-items: center; gap: var(--space-8);
  padding-bottom: var(--space-10); border-bottom: 1px solid var(--border-base);
}
.popover-title { font-size: var(--font-size-14); font-weight: 600; color: var(--text-primary); }
.popover-count { font-size: var(--font-size-11); color: var(--text-tertiary); background: var(--bg-base); padding: var(--space-1) var(--space-6); border-radius: var(--radius-8); }
.popover-header :deep(.ant-btn-link) { padding: 0 var(--space-4); font-size: var(--font-size-12); margin-left: auto; }

/* ★ C 档：当前账户切换行 */
.popover-account {
  display: flex; align-items: center; gap: var(--space-8);
  padding: var(--space-8) 0 var(--space-6); border-bottom: 1px solid var(--border-base);
}
.popover-account .account-label { font-size: var(--font-size-12); color: var(--text-tertiary); flex-shrink: 0; }

/* 表单里的补充说明（不占 label 列） */
.form-hint { font-size: var(--font-size-11); color: var(--text-tertiary); margin-top: var(--space-2); line-height: 1.4; }

.popover-body { max-height: 320px; overflow-y: auto; padding: var(--space-4) 0; }
.popover-shop-item {
  display: flex; align-items: center; justify-content: space-between;
  padding: var(--space-8) var(--space-10); border-radius: var(--radius-6); cursor: pointer;
  transition: all 0.15s; border: 1px solid transparent; margin-bottom: var(--space-2);
}
.popover-shop-item:hover { background: var(--bg-hover-light); }
.popover-shop-item.active { background: rgba(24, 144, 255, 0.12); border-color: var(--primary); }

.item-left { display: flex; align-items: center; gap: var(--space-6); min-width: 0; flex: 1; overflow: hidden; }
.shop-name { font-size: var(--font-size-13); font-weight: 500; color: var(--text-primary); white-space: nowrap; overflow: hidden; text-overflow: ellipsis; }
.item-right { display: flex; align-items: center; gap: var(--space-4); flex-shrink: 0; }

.status-dot { width: 6px; height: 6px; border-radius: var(--radius-circle); flex-shrink: 0; }
.status-dot.connected { background: var(--success); }
.status-dot.disconnected { background: #d9d9d9; }

.icon-btn { width: 24px; height: 24px; border: none; background: transparent; cursor: pointer; color: var(--text-tertiary); border-radius: var(--radius-4); display: inline-flex; align-items: center; justify-content: center; font-size: var(--font-size-12); padding: 0; }
.icon-btn:hover { background: var(--bg-hover-light); color: var(--primary); }
.icon-btn.danger:hover { color: var(--danger); background: rgba(255, 77, 79, 0.1); }

.empty-state { display: flex; flex-direction: column; align-items: center; padding: 30px var(--space-16); color: var(--text-tertiary); gap: var(--space-6); }
.empty-state p { margin: 0; font-size: var(--font-size-13); }
.empty-state span { font-size: var(--font-size-12); color: var(--text-disabled); }
</style>
