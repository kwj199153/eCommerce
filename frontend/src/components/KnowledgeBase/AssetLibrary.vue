<template>
  <div class="al-page">
    <!-- ===== 左侧分组栏（仿产品库） ===== -->
    <div class="al-sidebar">
      <div class="al-sidebar-header">
        <span class="al-sidebar-title">素材分组</span>
        <a-button type="text" size="small" @click="openCreateGroup">
          <PlusOutlined />
        </a-button>
      </div>

      <!-- 全部素材入口 -->
      <div
        class="al-group-item"
        :class="{ active: store.currentGroupId === null }"
        @click="store.selectGroup(null)"
      >
        <span class="al-color-dot" style="background: var(--text-disabled)"></span>
        <span class="al-group-name">全部素材</span>
        <span class="al-group-count">{{ store.totalCount }}</span>
      </div>

      <!-- 分组列表 -->
      <div
        v-for="g in store.groups"
        :key="g.id"
        class="al-group-item"
        :class="{ active: store.currentGroupId === g.id }"
        @click="store.selectGroup(g.id)"
      >
        <span class="al-color-dot" :style="{ background: g.color }"></span>
        <span class="al-group-name">{{ g.name }}</span>
        <span class="al-group-count">{{ store.groupCount[g.id] || 0 }}</span>
        <a-dropdown :trigger="['click']" @click.stop>
          <a-button type="text" size="small" class="al-group-more" @click.stop>
            <MoreOutlined />
          </a-button>
          <template #overlay>
            <a-menu @click="handleGroupMenuClick($event, g)">
              <a-menu-item key="rename">重命名</a-menu-item>
              <a-menu-item key="color">改颜色</a-menu-item>
              <a-menu-item key="up">上移</a-menu-item>
              <a-menu-item key="down">下移</a-menu-item>
              <a-menu-divider />
              <a-menu-item key="delete" style="color: var(--danger)">删除分组</a-menu-item>
            </a-menu>
          </template>
        </a-dropdown>
      </div>

      <div v-if="store.groups.length === 0" class="al-group-empty">
        暂无分组，点击右上角 + 新建
      </div>

      <!-- 未分组（虚拟分组，始终置底） -->
      <div
        v-if="store.ungroupedCount > 0"
        class="al-group-item al-group-item--ungrouped"
        :class="{ active: store.currentGroupId === '__ungrouped__' }"
        @click="store.selectGroup('__ungrouped__')"
      >
        <span class="al-color-dot" style="background: var(--text-disabled)"></span>
        <span class="al-group-name">未分组</span>
        <span class="al-group-count">{{ store.ungroupedCount }}</span>
      </div>

      <!-- 底部静态汇总 -->
      <div class="al-sidebar-summary">
        <div><PictureOutlined /> {{ store.imageCount }} 张图片</div>
        <div><VideoCameraOutlined /> {{ store.videoCount }} 个视频</div>
        <div><LinkOutlined /> {{ store.boundCount }} 个绑定产品</div>
      </div>
    </div>

    <!-- ===== 右侧内容区 ===== -->
    <div class="al-content">
      <!-- 统计卡片 -->
      <div class="stat-cards">
        <div class="stat-card">
          <div class="stat-value">{{ store.totalCount }}</div>
          <div class="stat-label">素材总数</div>
        </div>
        <div class="stat-card">
          <div class="stat-value">{{ store.imageCount }}</div>
          <div class="stat-label">图片素材</div>
        </div>
        <div class="stat-card">
          <div class="stat-value">{{ store.videoCount }}</div>
          <div class="stat-label">视频素材</div>
        </div>
        <div class="stat-card">
          <div class="stat-value green">{{ store.boundCount }}</div>
          <div class="stat-label">已绑定产品</div>
        </div>
      </div>

      <!-- 工具栏 -->
      <div class="al-toolbar">
        <div class="toolbar-left">
          <a-input-search
            v-model:value="store.searchQuery"
            placeholder="搜索素材名、产品名、ASIN、标签..."
            style="width: 260px"
            allow-clear
          >
            <template #prefix><SearchOutlined /></template>
          </a-input-search>
          <a-select
            v-model:value="store.filterKind"
            style="width: 110px"
            placeholder="全部媒体"
            allow-clear
          >
            <a-select-option value="image">🖼️ 图片</a-select-option>
            <a-select-option value="video">🎥 视频</a-select-option>
          </a-select>
          <a-select
            v-model:value="store.filterCategory"
            style="width: 140px"
            placeholder="全部类型"
            allow-clear
          >
            <a-select-option v-for="c in ASSET_CATEGORIES" :key="c.key" :value="c.key">
              {{ c.icon }} {{ c.label }}
              <span v-if="store.categoryStats[c.key]" class="cat-count">({{ store.categoryStats[c.key] }})</span>
            </a-select-option>
          </a-select>
        </div>
        <div class="toolbar-right">
          <a-button @click="openAddModal">
            <UploadOutlined /> 添加素材
          </a-button>
        </div>
      </div>

      <!-- 已应用的过滤条件（chip 行，一键清除） -->
      <div v-if="store.hasActiveFilters" class="active-filters">
        <span class="af-label">
          <FilterOutlined /> 已启用过滤 ({{ store.activeFilterCount }})
        </span>

        <!-- 当前分组 -->
        <a-tag
          v-if="store.currentGroupId"
          closable
          @close="store.selectGroup(null)"
          :color="currentGroupColor"
          class="af-chip"
        >
          {{ currentGroupLabel }}
        </a-tag>

        <!-- 媒体类型 -->
        <a-tag
          v-if="store.filterKind && store.filterKind !== 'all'"
          closable
          @close="store.filterKind = undefined"
          color="blue"
          class="af-chip"
        >
          媒体：{{ store.filterKind === 'image' ? '🖼️ 图片' : '🎥 视频' }}
        </a-tag>

        <!-- 素材类型 -->
        <a-tag
          v-if="store.filterCategory && store.filterCategory !== 'all'"
          closable
          @close="store.filterCategory = undefined"
          :color="COLOR_INFO"
          class="af-chip"
        >
          类型：{{ CATEGORY_ICON[store.filterCategory || ''] }} {{ CATEGORY_LABEL[store.filterCategory || ''] || store.filterCategory }}
        </a-tag>

        <!-- 搜索词 -->
        <a-tag
          v-if="store.searchQuery.trim()"
          closable
          @close="store.searchQuery = ''"
          :color="COLOR_INFO"
          class="af-chip"
        >
          搜索："{{ store.searchQuery }}"
        </a-tag>

        <!-- 一键清空 -->
        <a-button type="link" size="small" danger @click="store.clearAllFilters()">
          <ClearOutlined /> 清空全部
        </a-button>
      </div>

      <!-- 素材网格 -->
      <div v-if="store.filteredItems.length" class="asset-grid">
        <div v-for="item in store.filteredItems" :key="item.id" class="asset-card">
          <!-- 预览区 -->
          <div class="asset-thumb" @click="openPreview(item)">
            <img v-if="item.kind === 'video'" :src="item.thumbnail || item.url" alt="" loading="lazy" @error="onImgError" />
            <img v-else :src="item.url" alt="" loading="lazy" @error="onImgError" />
            <span v-if="item.kind === 'video'" class="video-badge"><PlayCircleFilled /></span>
            <span v-if="item.productId" class="bind-badge" title="已绑定产品"><LinkOutlined /></span>
          </div>

          <!-- 信息区 -->
          <div class="asset-info">
            <div class="asset-name-row">
              <span class="asset-name" :title="item.name">{{ item.name }}</span>
            </div>
            <div class="asset-tags">
              <a-tag size="small" :color="getKindColor(item.kind)">
                {{ item.kind === 'video' ? '🎥 视频' : '🖼️ 图片' }}
              </a-tag>
              <a-tag size="small">{{ CATEGORY_ICON[item.category] || '📦' }} {{ CATEGORY_LABEL[item.category] || item.category }}</a-tag>
            </div>
            <div v-if="item.productName" class="asset-product" :title="item.productName">
              📦 {{ truncate(item.productName, 18) }}
            </div>
            <div v-if="item.groups?.length" class="asset-groups">
              <span
                v-for="gid in item.groups"
                :key="gid"
                class="group-chip"
                :style="{ background: getGroupById(gid)?.color ? getGroupById(gid)!.color + '22' : 'var(--border-base)', color: getGroupById(gid)?.color || 'var(--text-secondary)' }"
              >
                {{ getGroupById(gid)?.name || '未知分组' }}
              </span>
            </div>

            <!-- 操作 -->
            <div class="asset-actions">
              <a-tooltip title="预览">
                <a-button type="text" size="small" @click="openPreview(item)"><EyeOutlined /></a-button>
              </a-tooltip>
              <a-tooltip title="编辑">
                <a-button type="text" size="small" @click="openEditModal(item)"><EditOutlined /></a-button>
              </a-tooltip>
              <a-popconfirm title="确定删除此素材？" @confirm="handleDelete(item.id)">
                <a-tooltip title="删除">
                  <a-button type="text" size="small" danger><DeleteOutlined /></a-button>
                </a-tooltip>
              </a-popconfirm>
            </div>
          </div>
        </div>
      </div>
      <div v-else class="al-empty">
        <a-empty :description="store.searchQuery || store.currentGroupId ? '没有匹配的素材' : '素材库为空，点击右上角添加素材'" />
      </div>
    </div>

    <!-- ===== 添加/编辑素材弹窗 ===== -->
    <a-modal
      v-model:open="modalVisible"
      :title="editingId ? '编辑素材' : '添加素材'"
      width="640px"
      @ok="handleSubmit"
      :okLoading="submitting"
      cancelText="取消"
    >
      <a-form :label-col="{ span: 5 }" :wrapper-col="{ span: 17 }">
        <a-form-item label="素材名称" required>
          <a-input v-model:value="form.name" placeholder="如：无线耳机 - 白底主图" />
        </a-form-item>
        <a-form-item label="媒体类型">
          <a-radio-group v-model:value="form.kind" :disabled="editingId !== null">
            <a-radio value="image">🖼️ 图片</a-radio>
            <a-radio value="video">🎥 视频</a-radio>
          </a-radio-group>
        </a-form-item>
        <a-form-item :label="form.kind === 'video' ? '封面/视频 URL' : '图片 URL'" required>
          <a-input v-model:value="form.url" :placeholder="form.kind === 'video' ? '视频封面图 URL' : 'https://...'">
            <template #addonAfter>
              <a-tooltip title="从产品库主图选取">
                <a-button type="text" size="small" @click="openProductPicker">
                  <DatabaseOutlined /> 产品库
                </a-button>
              </a-tooltip>
            </template>
          </a-input>
        </a-form-item>
        <a-form-item v-if="form.kind === 'video'" label="视频地址">
          <a-input v-model:value="form.videoUrl" placeholder="视频播放 URL（可选）" />
        </a-form-item>
        <a-form-item label="素材类型">
          <a-select v-model:value="form.category" style="width: 100%">
            <a-select-option v-for="c in ASSET_CATEGORIES" :key="c.key" :value="c.key">
              {{ c.icon }} {{ c.label }}
            </a-select-option>
          </a-select>
        </a-form-item>
        <a-form-item label="绑定产品">
          <div style="display: flex; gap: 6px; width: 100%">
            <a-select
              v-model:value="form.productId"
              style="flex: 1"
              placeholder="选择绑定产品（可选）"
              allow-clear
              show-search
              option-filter-prop="label"
              @change="handleProductChange"
            >
              <a-select-option v-for="p in productOptions" :key="p.value" :value="p.value">
                {{ p.label }}
              </a-select-option>
            </a-select>
          </div>
        </a-form-item>
        <a-form-item label="所属分组">
          <a-select
            v-model:value="form.groups"
            mode="multiple"
            placeholder="选择所属分组（可多选）"
            style="width: 100%"
            :options="store.groups.map(g => ({ label: g.name, value: g.id }))"
          />
        </a-form-item>
        <a-form-item label="标签">
          <a-select v-model:value="form.tags" mode="tags" placeholder="输入标签回车添加" style="width: 100%" />
        </a-form-item>
        <a-form-item label="备注">
          <a-textarea v-model:value="form.notes" placeholder="生成提示词 / 用途说明..." :rows="2" />
        </a-form-item>
      </a-form>
    </a-modal>

    <!-- ===== 预览大图弹窗 ===== -->
    <a-modal
      v-model:open="previewVisible"
      :title="previewItem?.name || '素材预览'"
      width="720px"
      :footer="null"
    >
      <div v-if="previewItem" class="preview-wrap">
        <div class="preview-media">
          <video
            v-if="previewItem.kind === 'video' && previewItem.videoUrl"
            :src="previewItem.videoUrl"
            controls
            style="width: 100%; max-height: 60vh"
          ></video>
          <img
            v-else
            :src="previewItem.url"
            alt=""
            style="width: 100%; max-height: 60vh; object-fit: contain"
            @error="onImgError"
          />
        </div>
        <a-descriptions :column="1" bordered size="small" style="margin-top: 12px">
          <a-descriptions-item label="类型">
            {{ CATEGORY_ICON[previewItem.category] || '📦' }} {{ CATEGORY_LABEL[previewItem.category] || previewItem.category }}
            <a-tag size="small" style="margin-left: 6px">{{ previewItem.kind === 'video' ? '视频' : '图片' }}</a-tag>
          </a-descriptions-item>
          <a-descriptions-item label="来源">{{ sourceLabel(previewItem.source) }}</a-descriptions-item>
          <a-descriptions-item label="绑定产品">
            {{ previewItem.productName || '-' }}
            <span v-if="previewItem.asin" class="text-muted">({{ previewItem.asin }})</span>
          </a-descriptions-item>
          <a-descriptions-item label="标签">
            <a-tag v-for="t in previewItem.tags" :key="t">{{ t }}</a-tag>
            <template v-if="!previewItem.tags?.length">-</template>
          </a-descriptions-item>
          <a-descriptions-item label="备注">{{ previewItem.notes || '-' }}</a-descriptions-item>
          <a-descriptions-item v-if="previewItem.prompt" label="提示词">
            <div class="prompt-text">{{ previewItem.prompt }}</div>
          </a-descriptions-item>
          <a-descriptions-item label="创建时间">{{ formatTime(previewItem.createdAt) }}</a-descriptions-item>
        </a-descriptions>
        <div class="preview-actions">
          <a-button type="primary" :href="previewItem.url" target="_blank" download>
            <DownloadOutlined /> 下载
          </a-button>
        </div>
      </div>
    </a-modal>

    <!-- ===== 产品库选图弹窗 ===== -->
    <a-modal
      v-model:open="productPickerVisible"
      title="从产品库选择主图作为素材"
      width="560px"
      :footer="null"
    >
      <div v-if="productOptions.length" class="product-picker-grid">
        <div
          v-for="p in productOptions"
          :key="p.value"
          class="picker-product"
          @click="pickProductImage(p.value)"
        >
          <img :src="p.img" alt="" loading="lazy" @error="onImgError" />
          <span class="picker-name">{{ p.label }}</span>
        </div>
      </div>
      <a-empty v-else description="产品库暂无产品" />
    </a-modal>

    <!-- ===== 分组弹窗 ===== -->
    <a-modal
      v-model:open="createGroupVisible"
      title="新建素材分组"
      :footer="null"
      :width="400"
      centered
    >
      <a-form layout="vertical">
        <a-form-item label="分组名称">
          <a-input
            v-model:value="createGroupName"
            placeholder="如：Q4 主图素材、A+ 配图"
            @pressEnter="submitCreateGroup"
          />
        </a-form-item>
        <a-form-item label="标签颜色">
          <div class="al-color-picker">
            <span
              v-for="c in ASSET_GROUP_COLORS"
              :key="c"
              class="al-color-swatch"
              :class="{ active: createGroupColor === c }"
              :style="{ background: c }"
              @click="createGroupColor = c"
            ></span>
          </div>
        </a-form-item>
      </a-form>
      <template #footer>
        <a-button @click="createGroupVisible = false">取消</a-button>
        <a-button type="primary" @click="submitCreateGroup">创建</a-button>
      </template>
    </a-modal>

    <!-- 重命名分组弹窗 -->
    <a-modal
      v-model:open="renameVisible"
      title="重命名分组"
      :footer="null"
      :width="400"
      centered
    >
      <a-input v-model:value="renameValue" placeholder="新分组名称" @pressEnter="submitRename" />
      <template #footer>
        <a-button @click="renameVisible = false">取消</a-button>
        <a-button type="primary" @click="submitRename">确定</a-button>
      </template>
    </a-modal>
  </div>
</template>

<script setup lang="ts">
import { ref, reactive, computed, onMounted } from 'vue'
import { message } from 'ant-design-vue'
import {
  PlusOutlined,
  UploadOutlined,
  SearchOutlined,
  EditOutlined,
  DeleteOutlined,
  EyeOutlined,
  MoreOutlined,
  DownloadOutlined,
  PictureOutlined,
  VideoCameraOutlined,
  PlayCircleFilled,
  LinkOutlined,
  DatabaseOutlined,
  FilterOutlined,
  ClearOutlined,
} from '@ant-design/icons-vue'
import {
  useAssetLibraryStore,
  ASSET_CATEGORIES,
  ASSET_GROUP_COLORS,
  CATEGORY_ICON,
  CATEGORY_LABEL,
  type AssetItem,
  type AssetGroup,
  type AssetKind,
} from '@/stores/assetLibrary'
import { useProductLibraryStore } from '@/stores/productLibrary'
import { COLOR_INFO } from '@/utils/colorSemantics'

const store = useAssetLibraryStore()
const productStore = useProductLibraryStore()

// ====== 当前分组的展示名/色（用于 chip） ======
const currentGroupLabel = computed(() => {
  const gid = store.currentGroupId
  if (!gid) return ''
  if (gid === '__ungrouped__') return '未分组'
  return store.groups.find(g => g.id === gid)?.name || ''
})
const currentGroupColor = computed(() => {
  const gid = store.currentGroupId
  if (!gid) return undefined
  if (gid === '__ungrouped__') return 'default'
  return store.groups.find(g => g.id === gid)?.color
})

// ====== 产品库下拉 ======
const productOptions = computed(() =>
  productStore.items.map(p => ({
    value: p.id,
    label: p.title.slice(0, 30) + (p.title.length > 30 ? '…' : ''),
    img: p.main_image || '',
  }))
)

function getGroupById(id: string): AssetGroup | undefined {
  return store.groups.find(g => g.id === id)
}

// ====== 弹窗表单 ======
const modalVisible = ref(false)
const editingId = ref<string | null>(null)
const submitting = ref(false)

const form = reactive({
  name: '',
  kind: 'image' as AssetKind,
  url: '',
  videoUrl: '',
  category: 'other',
  productId: undefined as string | undefined,
  groups: [] as string[],
  tags: [] as string[],
  notes: '',
})

function resetForm() {
  Object.assign(form, {
    name: '',
    kind: 'image' as AssetKind,
    url: '',
    videoUrl: '',
    category: 'other',
    productId: undefined as string | undefined,
    groups: [],
    tags: [],
    notes: '',
  })
}

function openAddModal() {
  resetForm()
  editingId.value = null
  modalVisible.value = true
}

function openEditModal(item: AssetItem) {
  editingId.value = item.id
  Object.assign(form, {
    name: item.name,
    kind: item.kind,
    url: item.url,
    videoUrl: item.videoUrl || '',
    category: item.category,
    productId: item.productId,
    groups: [...(item.groups || [])],
    tags: [...(item.tags || [])],
    notes: item.notes || '',
  })
  modalVisible.value = true
}

function handleProductChange() {
  const p = productStore.items.find(x => x.id === form.productId)
  // productId 已绑，无需额外操作（存 snapshot 在提交时处理）
  void p
}

async function handleSubmit() {
  if (!form.name.trim()) {
    message.warning('请填写素材名称')
    return
  }
  if (!form.url.trim()) {
    message.warning('请填写图片 / 封面 URL')
    return
  }
  submitting.value = true
  try {
    const bound = productStore.items.find(x => x.id === form.productId)
    const base = {
      name: form.name.trim(),
      kind: form.kind,
      url: form.url.trim(),
      videoUrl: form.videoUrl.trim() || undefined,
      category: form.category,
      productId: bound?.id,
      productName: bound?.title,
      asin: bound?.asin,
      groups: form.groups,
      tags: form.tags,
      notes: form.notes,
    }
    if (editingId.value) {
      store.updateItem(editingId.value, base)
      message.success('素材已更新')
    } else {
      store.addItem({ ...base, source: 'manual' })
      message.success('素材已添加')
    }
    modalVisible.value = false
  } finally {
    submitting.value = false
  }
}

async function handleDelete(id: string) {
  store.deleteItem(id)
  message.success('已删除')
}

// ====== 预览 ======
const previewVisible = ref(false)
const previewItem = ref<AssetItem | null>(null)

function openPreview(item: AssetItem) {
  previewItem.value = item
  previewVisible.value = true
}

// ====== 产品库选图 ======
const productPickerVisible = ref(false)

function openProductPicker() {
  productPickerVisible.value = true
}

function pickProductImage(productId: string) {
  const p = productStore.items.find(x => x.id === productId)
  if (p?.main_image) {
    form.url = p.main_image
    form.productId = p.id
    message.success(`已选取「${p.title.slice(0, 20)}」主图`)
    productPickerVisible.value = false
  } else {
    message.warning('该产品暂无主图')
  }
}

// ====== 分组操作 ======
const createGroupVisible = ref(false)
const createGroupName = ref('')
const createGroupColor = ref(ASSET_GROUP_COLORS[0])

function openCreateGroup() {
  createGroupName.value = ''
  createGroupColor.value = ASSET_GROUP_COLORS[store.groups.length % ASSET_GROUP_COLORS.length]
  createGroupVisible.value = true
}

function submitCreateGroup() {
  const name = createGroupName.value.trim()
  if (!name) {
    message.warning('请输入分组名称')
    return
  }
  const group = store.createGroup({ name, color: createGroupColor.value })
  store.selectGroup(group.id)
  message.success(`分组「${group.name}」已创建`)
  createGroupVisible.value = false
}

const renameVisible = ref(false)
const renameValue = ref('')
const renameTargetId = ref<string | null>(null)

function submitRename() {
  if (!renameTargetId.value || !renameValue.value.trim()) return
  store.renameGroup(renameTargetId.value, renameValue.value)
  message.success('已重命名')
  renameVisible.value = false
}

function handleGroupMenuClick(e: { key: string }, group: AssetGroup) {
  switch (e.key) {
    case 'rename':
      renameTargetId.value = group.id
      renameValue.value = group.name
      renameVisible.value = true
      break
    case 'color':
      const idx = ASSET_GROUP_COLORS.indexOf(group.color)
      const next = ASSET_GROUP_COLORS[(idx + 1) % ASSET_GROUP_COLORS.length]
      store.setGroupColor(group.id, next)
      break
    case 'up':
      store.moveGroup(group.id, 'up')
      break
    case 'down':
      store.moveGroup(group.id, 'down')
      break
    case 'delete':
      store.deleteGroup(group.id)
      message.success('分组已删除')
      break
  }
}

// ====== 辅助 ======
function getKindColor(kind: AssetKind): string {
  return kind === 'video' ? 'purple' : 'blue'
}

function sourceLabel(source: string): string {
  const map: Record<string, string> = {
    aigc: 'AI 素材生成',
    upload: '本地上传',
    'video-gen': 'AI 视频生成',
    manual: '手动添加',
  }
  return map[source] || source
}

function formatTime(t: string): string {
  const d = new Date(t)
  return d.toLocaleString('zh-CN', {
    year: 'numeric', month: '2-digit', day: '2-digit',
    hour: '2-digit', minute: '2-digit',
  })
}

function truncate(s: string, n: number): string {
  return s.length > n ? s.slice(0, n) + '…' : s
}

function onImgError(e: Event) {
  const el = e.target as HTMLImageElement
  el.style.opacity = '0.3'
  el.style.background = 'var(--bg-sidebar)'
}

onMounted(() => {
  store.fetchItems()
})
</script>

<style scoped>
.al-page {
  height: 100%;
  display: flex;
  overflow: hidden;
}

/* ===== 左侧分组栏 ===== */
.al-sidebar {
  width: 220px;
  flex-shrink: 0;
  border-right: 1px solid var(--border-base);
  display: flex;
  flex-direction: column;
  background: var(--bg-sidebar);
  overflow-y: auto;
}

.al-sidebar-header {
  display: flex;
  align-items: center;
  justify-content: space-between;
  padding: 16px 16px 8px;
}

.al-sidebar-title {
  font-size: 14px;
  font-weight: 600;
  color: var(--text-primary);
}

.al-group-item {
  display: flex;
  align-items: center;
  gap: 8px;
  padding: 9px 16px;
  cursor: pointer;
  transition: background 0.15s;
  font-size: 13px;
}

.al-group-item:hover {
  background: var(--border-base);
}

.al-group-item.active {
  background: var(--bg-active-light);
  border-right: 3px solid var(--primary);
}

.al-color-dot {
  width: 10px;
  height: 10px;
  border-radius: 50%;
  flex-shrink: 0;
}

.al-group-name {
  flex: 1;
  color: var(--text-primary);
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}

.al-group-count {
  font-size: 11px;
  color: var(--text-tertiary);
  background: var(--border-base);
  border-radius: 10px;
  padding: 0 8px;
}

.al-group-more {
  opacity: 0;
  transition: opacity 0.15s;
}

.al-group-item:hover .al-group-more {
  opacity: 1;
}

.al-group-empty {
  padding: 16px;
  font-size: 12px;
  color: var(--text-disabled);
  line-height: 1.6;
}

.al-group-item--ungrouped {
  margin-top: 8px;
  border-top: 1px dashed var(--border-strong);
  padding-top: 10px;
  opacity: 0.85;
}

.al-group-item--ungrouped:hover {
  opacity: 1;
}

.al-sidebar-summary {
  margin-top: auto;
  padding: 12px 16px;
  border-top: 1px solid var(--border-base);
  font-size: 12px;
  color: var(--text-tertiary);
  display: flex;
  flex-direction: column;
  gap: 6px;
}

/* ===== 右侧内容区 ===== */
.al-content {
  flex: 1;
  overflow: hidden;
  display: flex;
  flex-direction: column;
  padding: 16px 24px;
}

.stat-cards {
  display: grid;
  grid-template-columns: repeat(4, 1fr);
  gap: 12px;
  margin-bottom: 14px;
  flex-shrink: 0;
}

.stat-card {
  background: var(--bg-sidebar);
  border-radius: 8px;
  padding: 12px 16px;
  border: 1px solid var(--border-base);
}

.stat-value {
  font-size: 22px;
  font-weight: 700;
  color: var(--text-primary);
}

.stat-value.green {
  color: var(--success);
}

.stat-label {
  font-size: 12px;
  color: var(--text-tertiary);
  margin-top: 2px;
}

.al-toolbar {
  display: flex;
  align-items: center;
  justify-content: space-between;
  margin-bottom: 12px;
  flex-shrink: 0;
}

.toolbar-left {
  display: flex;
  align-items: center;
  gap: 10px;
}

.toolbar-right {
  display: flex;
  gap: 8px;
}

/* ===== 已应用过滤条件（chip 行） ===== */
.active-filters {
  display: flex;
  align-items: center;
  flex-wrap: wrap;
  gap: 6px;
  padding: 8px 12px;
  margin-bottom: 10px;
  background: var(--bg-sidebar);
  border: 1px dashed var(--border-strong);
  border-radius: 6px;
}
.af-label {
  font-size: 12px;
  color: var(--text-tertiary);
  font-weight: 500;
  margin-right: 4px;
}
.af-chip {
  font-size: 12px;
  padding: 2px 8px;
  border-radius: 10px;
}

.cat-count {
  color: var(--text-tertiary);
  font-size: 11px;
  margin-left: 4px;
}

/* ===== 素材网格 ===== */
.asset-grid {
  flex: 1;
  overflow-y: auto;
  display: grid;
  grid-template-columns: repeat(auto-fill, minmax(210px, 1fr));
  gap: 14px;
  align-content: start;
  padding-bottom: 12px;
}

.asset-card {
  border: 1px solid var(--border-base);
  border-radius: 10px;
  overflow: hidden;
  background: var(--bg-elevated);
  transition: box-shadow 0.2s, transform 0.2s;
  display: flex;
  flex-direction: column;
}

.asset-card:hover {
  box-shadow: 0 4px 12px rgba(0, 21, 41, 0.1);
  transform: translateY(-1px);
}

.asset-thumb {
  position: relative;
  aspect-ratio: 1 / 1;
  background: var(--bg-sidebar);
  cursor: zoom-in;
  overflow: hidden;
}

.asset-thumb img {
  width: 100%;
  height: 100%;
  object-fit: cover;
  display: block;
  transition: transform 0.25s;
}

.asset-card:hover .asset-thumb img {
  transform: scale(1.04);
}

.video-badge {
  position: absolute;
  left: 50%;
  top: 50%;
  transform: translate(-50%, -50%);
  font-size: 36px;
  color: rgba(255, 255, 255, 0.92);
  text-shadow: 0 2px 8px rgba(0, 0, 0, 0.35);
  pointer-events: none;
}

.bind-badge {
  position: absolute;
  top: 6px;
  right: 6px;
  width: 22px;
  height: 22px;
  border-radius: 50%;
  background: rgba(24, 144, 255, 0.9);
  color: #fff;
  display: flex;
  align-items: center;
  justify-content: center;
  font-size: 12px;
}

.asset-info {
  padding: 8px 10px 6px;
  display: flex;
  flex-direction: column;
  gap: 4px;
}

.asset-name-row {
  display: flex;
  align-items: center;
  gap: 4px;
}

.asset-name {
  font-size: 12px;
  font-weight: 500;
  color: var(--text-primary);
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
  flex: 1;
}

.asset-tags {
  display: flex;
  gap: 4px;
  flex-wrap: wrap;
}

.asset-product {
  font-size: 11px;
  color: var(--text-tertiary);
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}

.asset-groups {
  display: flex;
  gap: 4px;
  flex-wrap: wrap;
}

.group-chip {
  font-size: 10px;
  padding: 1px 6px;
  border-radius: 8px;
  line-height: 1.6;
}

.asset-actions {
  display: flex;
  justify-content: flex-end;
  gap: 0;
  border-top: 1px solid var(--bg-sidebar);
  padding-top: 2px;
}

.asset-actions :deep(.ant-btn) {
  font-size: 13px;
}

.al-empty {
  flex: 1;
  display: flex;
  align-items: center;
  justify-content: center;
}

/* 预览 */
.preview-wrap {
  display: flex;
  flex-direction: column;
}

.preview-media {
  background: var(--bg-sidebar);
  border-radius: 8px;
  overflow: hidden;
  display: flex;
  justify-content: center;
}

.preview-actions {
  margin-top: 14px;
  text-align: right;
}

.prompt-text {
  font-size: 12px;
  color: var(--text-secondary);
  line-height: 1.6;
  word-break: break-word;
  background: var(--bg-sidebar);
  padding: 6px 8px;
  border-radius: 4px;
}

.text-muted { color: var(--text-disabled); }

/* 产品库选图 */
.product-picker-grid {
  display: grid;
  grid-template-columns: repeat(3, 1fr);
  gap: 10px;
  max-height: 55vh;
  overflow-y: auto;
}

.picker-product {
  border: 1px solid var(--border-base);
  border-radius: 8px;
  overflow: hidden;
  cursor: pointer;
  transition: border-color 0.2s, box-shadow 0.2s;
}

.picker-product:hover {
  border-color: var(--primary);
  box-shadow: 0 2px 8px rgba(24, 144, 255, 0.15);
}

.picker-product img {
  width: 100%;
  aspect-ratio: 1 / 1;
  object-fit: cover;
  display: block;
}

.picker-name {
  display: block;
  padding: 6px 8px;
  font-size: 11px;
  color: var(--text-secondary);
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}

/* 颜色选择 */
.al-color-picker {
  display: flex;
  gap: 8px;
  flex-wrap: wrap;
}

.al-color-swatch {
  width: 24px;
  height: 24px;
  border-radius: 50%;
  cursor: pointer;
  border: 2px solid transparent;
  transition: all 0.2s;
}

.al-color-swatch.active {
  border-color: var(--text-primary);
  transform: scale(1.15);
}
</style>
