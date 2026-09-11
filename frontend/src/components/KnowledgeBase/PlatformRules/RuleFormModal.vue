<template>
  <a-modal
    v-model:open="open"
    :title="editingId ? '编辑规则' : '新增规则'"
    width="600px"
    :confirm-loading="saving"
    @ok="handleSubmit"
  >
    <a-form layout="vertical">
      <a-row :gutter="12">
        <a-col :span="12">
          <a-form-item label="平台" required>
            <a-select v-model:value="editForm.platform" placeholder="选择平台">
              <a-select-option v-for="p in PLATFORMS" :key="p.key" :value="p.key">
                {{ p.icon }} {{ p.label }}
              </a-select-option>
            </a-select>
          </a-form-item>
        </a-col>
        <a-col :span="12">
          <a-form-item label="规则分类" required>
            <a-select v-model:value="editForm.category" placeholder="选择分类">
              <a-select-option v-for="c in RULE_CATEGORIES" :key="c.key" :value="c.key">
                {{ c.icon }} {{ c.label }}
              </a-select-option>
            </a-select>
          </a-form-item>
        </a-col>
      </a-row>
      <a-form-item label="规则标题" required>
        <a-input v-model:value="editForm.title" placeholder="如：商品标题字符数限制" />
      </a-form-item>
      <a-form-item label="规则内容" required>
        <a-textarea
          v-model:value="editForm.content"
          :rows="5"
          placeholder="输入规则正文..."
        />
      </a-form-item>
      <a-row :gutter="12">
        <a-col :span="12">
          <a-form-item label="生效日期" required>
            <a-date-picker
              v-model:value="editForm.effective_date"
              value-format="YYYY-MM-DD"
              style="width: 100%"
            />
          </a-form-item>
        </a-col>
        <a-col :span="12">
          <a-form-item label="失效日期">
            <a-date-picker
              v-model:value="editForm.expiry_date"
              value-format="YYYY-MM-DD"
              style="width: 100%"
              placeholder="留空=永不过期"
            />
          </a-form-item>
        </a-col>
      </a-row>

      <!-- 有效期快捷选择 -->
      <div class="validity-quick-select">
        <span class="vqs-label">快捷设置有效期：</span>
        <a-space :size="6" wrap>
          <a-button
            size="small"
            :type="!expDateStr ? 'primary' : 'default'"
            @click="setExpiryDate(null)"
          >♾️ 永久</a-button>
          <a-button
            size="small"
            :type="isExpiryMatch(3) ? 'primary' : 'default'"
            @click="setExpiryDate(3)"
          >3 个月</a-button>
          <a-button
            size="small"
            :type="isExpiryMatch(6) ? 'primary' : 'default'"
            @click="setExpiryDate(6)"
          >6 个月</a-button>
          <a-button
            size="small"
            :type="isExpiryMatch(12) ? 'primary' : 'default'"
            @click="setExpiryDate(12)"
          >1 年</a-button>
          <a-button
            size="small"
            :type="isExpiryMatch(24) ? 'primary' : 'default'"
            @click="setExpiryDate(24)"
          >2 年</a-button>
        </a-space>
        <span v-if="expDateStr && effDateStr" class="vqs-preview">
          （有效期 {{ calcDurationDays }} 天）
        </span>
      </div>
      <a-form-item label="状态">
        <a-select v-model:value="editForm.status">
          <a-select-option value="auto">🤖 自动（根据日期计算，推荐）</a-select-option>
          <a-select-option value="active">🟢 强制生效中</a-select-option>
          <a-select-option value="upcoming">🟡 强制即将生效</a-select-option>
          <a-select-option value="expired">⚪ 强制已失效</a-select-option>
        </a-select>
        <div class="form-hint">选择「自动」时，系统根据生效/失效日期实时判定状态；手动选项用于特殊场景覆盖（如提前失效）</div>
      </a-form-item>
      <a-form-item label="标签（逗号分隔）">
        <a-input v-model:value="editForm.tagsText" placeholder="如：标题, 字符限制, Listing" />
      </a-form-item>
      <a-form-item label="来源链接">
        <a-input v-model:value="editForm.source" placeholder="https://..." />
      </a-form-item>
      <a-form-item label="来源文档">
        <a-select
          v-model:value="editForm.source_doc_id"
          placeholder="关联到已上传的规则原文文档"
          allow-clear
          style="width: 100%"
        >
          <a-select-option v-for="doc in store.docs" :key="doc.id" :value="doc.id">
            {{ getDocIcon(doc.file_type) }} {{ doc.filename }}
            <span class="select-doc-platform">({{ platformMeta(doc.platform).label }})</span>
          </a-select-option>
        </a-select>
        <div class="form-hint">选择后可在规则详情中一键跳转到完整原文</div>
      </a-form-item>
    </a-form>
  </a-modal>
</template>

<script setup lang="ts">
import { ref, reactive, computed, watch } from 'vue'
import { message } from 'ant-design-vue'
import { usePlatformRulesStore, PLATFORMS, RULE_CATEGORIES, type PlatformRule, type PlatformRuleDoc } from '@/stores/platformRules'

const store = usePlatformRulesStore()

const props = defineProps<{
  /** 编辑中的规则 id（null = 新增） */
  editingId: string | null
}>()
const emit = defineEmits<{
  (e: 'saved'): void
}>()

const open = defineModel<boolean>('open', { required: true })

const saving = ref(false)

const editForm = reactive({
  platform: 'amazon',
  category: 'listing',
  title: '',
  content: '',
  effective_date: '',
  expiry_date: undefined as string | undefined,
  status: 'auto' as PlatformRule['status'],
  tagsText: '',
  source: '',
  source_doc_id: undefined as string | undefined,
})

// ====== 有效期快捷选择（表单专属，随弹窗下沉）======

/** 统一日期值提取：兼容 Dayjs 对象与字符串 */
function toDateStr(val: any): string {
  if (!val) return ''
  if (typeof val === 'object' && val.format && typeof val.format === 'function') {
    return val.format('YYYY-MM-DD')
  }
  if (typeof val === 'string') return val
  return ''
}

const effDateStr = computed(() => toDateStr(editForm.effective_date))
const expDateStr = computed(() => toDateStr(editForm.expiry_date))

function calcExpiryDate(months: number): string {
  const effRaw = effDateStr.value || new Date().toISOString().slice(0, 10)
  const eff = new Date(effRaw + 'T00:00:00')
  eff.setMonth(eff.getMonth() + months)
  return eff.toISOString().slice(0, 10)
}

function setExpiryDate(months: number | null) {
  if (months === null) {
    editForm.expiry_date = undefined as any
  } else {
    if (!effDateStr.value) {
      editForm.effective_date = new Date().toISOString().slice(0, 10) as any
    }
    editForm.expiry_date = calcExpiryDate(months) as any
  }
}

function isExpiryMatch(months: number): boolean {
  const exp = expDateStr.value
  if (!exp || !effDateStr.value) return false
  return exp === calcExpiryDate(months)
}

const calcDurationDays = computed(() => {
  const eff = effDateStr.value
  const exp = expDateStr.value
  if (!eff || !exp) return 0
  const effDt = new Date(eff + 'T00:00:00')
  const expDt = new Date(exp + 'T00:00:00')
  return Math.ceil((expDt.getTime() - effDt.getTime()) / (1000 * 60 * 60 * 24))
})

// ====== 纯辅助（与父组件重复定义，保持子组件自治）======

function getDocIcon(type: PlatformRuleDoc['file_type']): string {
  switch (type) {
    case 'pdf': return '📄'
    case 'md': return '📝'
    case 'excel': return '📊'
    case 'txt': return '📃'
    default: return '📎'
  }
}

function platformMeta(key: string) {
  return PLATFORMS.find(p => p.key === key) || { key, label: key, icon: '🌐', color: 'var(--text-tertiary)' }
}

// ====== 打开时填充/重置 ======
watch(open, (val) => {
  if (!val) return
  if (props.editingId) {
    const record = store.items.find(i => i.id === props.editingId)
    if (record) {
      Object.assign(editForm, {
        platform: record.platform,
        category: record.category,
        title: record.title,
        content: record.content,
        effective_date: record.effective_date,
        expiry_date: record.expiry_date,
        status: record.status,
        tagsText: record.tags.join(', '),
        source: record.source || '',
        source_doc_id: record.source_doc_id,
      })
    }
  } else {
    Object.assign(editForm, {
      platform: 'amazon',
      category: 'listing',
      title: '',
      content: '',
      effective_date: '',
      expiry_date: undefined,
      status: 'auto',
      tagsText: '',
      source: '',
      source_doc_id: undefined,
    })
  }
})

async function handleSubmit() {
  if (!editForm.title.trim() || !editForm.content.trim()) {
    message.warning('请填写规则标题和内容')
    return
  }
  saving.value = true
  try {
    const payload = {
      platform: editForm.platform,
      category: editForm.category,
      title: editForm.title.trim(),
      content: editForm.content.trim(),
      effective_date: effDateStr.value || new Date().toISOString().slice(0, 10),
      expiry_date: expDateStr.value || undefined,
      status: editForm.status,
      tags: editForm.tagsText.split(',').map(t => t.trim()).filter(Boolean),
      source: editForm.source.trim(),
      source_doc_id: editForm.source_doc_id || undefined,
    }
    if (props.editingId) {
      await store.updateItem(props.editingId, payload)
      message.success('规则已更新')
    } else {
      await store.addItem(payload)
      message.success('规则已新增')
    }
    open.value = false
    emit('saved')
  } finally {
    saving.value = false
  }
}
</script>

<style scoped>
/* 有效期快捷选择 */
.validity-quick-select {
  display: flex;
  align-items: center;
  gap: 8px;
  padding: 8px 12px;
  background: var(--bg-sidebar);
  border-radius: 6px;
  border: 1px solid var(--border-base);
  margin-top: -8px;
  margin-bottom: 4px;
  flex-wrap: wrap;
}
.vqs-label {
  font-size: 12px;
  color: var(--text-tertiary);
  white-space: nowrap;
}
.vqs-preview {
  font-size: 12px;
  color: var(--primary);
  white-space: nowrap;
}
.form-hint {
  font-size: 11px;
  color: var(--text-tertiary);
  margin-top: 4px;
}
.select-doc-platform {
  color: var(--text-tertiary);
  font-size: 11px;
  margin-left: 4px;
}
</style>
