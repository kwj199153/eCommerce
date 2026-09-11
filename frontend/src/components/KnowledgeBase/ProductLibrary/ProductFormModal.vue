<template>
  <a-modal
    v-model:open="open"
    :title="editingId ? '编辑产品' : '新增产品'"
    width="720px"
    @ok="handleSubmit"
    :okLoading="submitting"
    cancelText="取消"
  >
    <a-form :label-col="{ span: 5 }" :wrapper-col="{ span: 18 }">
      <a-row :gutter="16">
        <a-col :span="12">
          <a-form-item label="ASIN" required>
            <a-input v-model:value="form.asin" placeholder="B0XXXXXXXX" />
          </a-form-item>
        </a-col>
        <a-col :span="12">
          <a-form-item label="SKU">
            <a-input v-model:value="form.sku" placeholder="内部 SKU" />
          </a-form-item>
        </a-col>
      </a-row>
      <a-form-item label="产品标题" required>
        <a-textarea v-model:value="form.title" placeholder="产品名称/Listing 标题" :rows="2" />
      </a-form-item>
      <a-row :gutter="16">
        <a-col :span="12">
          <a-form-item label="品牌">
            <a-input v-model:value="form.brand" placeholder="品牌名" />
          </a-form-item>
        </a-col>
        <a-col :span="12">
          <a-form-item label="分类">
            <a-select v-model:value="form.category" placeholder="选择分类">
              <a-select-option v-for="cat in CATEGORIES" :key="cat.key" :value="cat.key">
                {{ cat.icon }} {{ cat.label }}
              </a-select-option>
            </a-select>
          </a-form-item>
        </a-col>
      </a-row>
      <a-row :gutter="16">
        <a-col :span="8">
          <a-form-item label="售价 ($)">
            <a-input-number v-model:value="form.price" :min="0" :precision="2" style="width:100%" />
          </a-form-item>
        </a-col>
        <a-col :span="8">
          <a-form-item label="成本 ($)">
            <a-input-number v-model:value="form.cost" :min="0" :precision="2" style="width:100%" />
          </a-form-item>
        </a-col>
        <a-col :span="8">
          <a-form-item label="配送方式">
            <a-select v-model:value="form.fulfillment_type">
              <a-select-option value="FBA">FBA</a-select-option>
              <a-select-option value="FBM">FBM</a-select-option>
            </a-select>
          </a-form-item>
        </a-col>
      </a-row>
      <a-row :gutter="16">
        <a-col :span="8">
          <a-form-item label="FBA 库存">
            <a-input-number v-model:value="form.fba_stock" :min="0" style="width:100%" />
          </a-form-item>
        </a-col>
        <a-col :span="8">
          <a-form-item label="FBM 库存">
            <a-input-number v-model:value="form.fbm_stock" :min="0" style="width:100%" />
          </a-form-item>
        </a-col>
        <a-col :span="8">
          <a-form-item label="日均销量">
            <a-input-number v-model:value="form.daily_sales_avg" :min="0" style="width:100%" />
          </a-form-item>
        </a-col>
      </a-row>
      <a-form-item label="标签">
        <a-select v-model:value="form.tags" mode="tags" placeholder="输入标签回车添加" style="width:100%" />
      </a-form-item>
      <a-form-item label="分组">
        <a-select
          v-model:value="form.groups"
          mode="multiple"
          placeholder="选择所属分组（可多选）"
          style="width:100%"
          :options="store.groups.map(g => ({ label: g.name, value: g.id }))"
        />
      </a-form-item>
      <a-form-item label="备注">
        <a-textarea v-model:value="form.notes" placeholder="运营备注..." :rows="2" />
      </a-form-item>

      <!-- 创建SPU（仅新增时可选） -->
      <template v-if="!editingId">
        <a-divider orientation="left" style="margin: 16px 0 8px">
          <span style="font-size: 13px; color: var(--text-secondary)">SPU</span>
        </a-divider>
        <a-form-item label="创建SPU">
          <a-switch v-model:checked="createVariation" :disabled="editingId !== null" />
          <span style="margin-left: 8px; font-size: 12px; color: var(--text-tertiary)">
            开启后生成 1 个SPU + 多个SKU，SKU各自独立维护价格/库存/文案
          </span>
        </a-form-item>
        <template v-if="createVariation">
          <a-form-item label="规格主题" required>
            <a-select v-model:value="variationTheme" placeholder="选择规格维度" style="width: 100%">
              <a-select-option value="Color">颜色 Color</a-select-option>
              <a-select-option value="Size">尺寸 Size</a-select-option>
              <a-select-option value="Color-Size">颜色 + 尺寸</a-select-option>
              <a-select-option value="Style">款式 Style</a-select-option>
              <a-select-option value="Package">包装 Package</a-select-option>
            </a-select>
          </a-form-item>
          <a-form-item label="SKU">
            <div style="width: 100%">
              <div v-for="(ch, i) in childVariations" :key="i" class="var-child-row">
                <a-input
                  v-model:value="ch.spec_value"
                  :placeholder="variationTheme === 'Size' ? '如 M / L / XL' : '如 红色 / 蓝色'"
                  style="width: 120px"
                />
                <a-input v-model:value="ch.asin" placeholder="ASIN (B0XXXX)" style="width: 140px" />
                <a-input-number v-model:value="ch.price" :min="0" :precision="2" placeholder="价格" style="width: 90px" />
                <a-input-number v-model:value="ch.stock" :min="0" placeholder="库存" style="width: 80px" />
                <a-button type="text" danger size="small" @click="removeChildVariation(i)">
                  <DeleteOutlined />
                </a-button>
              </div>
              <a-button type="dashed" size="small" block style="margin-top: 6px" @click="addChildVariationRow">
                <PlusOutlined /> 添加SKU
              </a-button>
            </div>
          </a-form-item>
        </template>
      </template>
    </a-form>
  </a-modal>
</template>

<script setup lang="ts">
import { ref, reactive, watch } from 'vue'
import { message } from 'ant-design-vue'
import { DeleteOutlined, PlusOutlined } from '@ant-design/icons-vue'
import { useProductLibraryStore, PRODUCT_CATEGORIES, type ProductItem } from '@/stores/productLibrary'

const store = useProductLibraryStore()
const CATEGORIES = PRODUCT_CATEGORIES

const props = defineProps<{
  /** 编辑中的产品 id（null = 新增） */
  editingId: string | null
}>()
const emit = defineEmits<{
  (e: 'saved'): void
}>()

const open = defineModel<boolean>('open', { required: true })

const submitting = ref(false)

const form = reactive({
  asin: '',
  sku: '',
  title: '',
  brand: '',
  category: 'other',
  price: 0,
  cost: 0,
  fulfillment_type: 'FBA' as 'FBA' | 'FBM',
  fba_stock: 0,
  fbm_stock: 0,
  daily_sales_avg: 0,
  tags: [] as string[],
  notes: '',
  groups: [] as string[],
})

// SPU 创建（仅新增时可用）
const createVariation = ref(false)
const variationTheme = ref('Color')
const childVariations = ref<Array<{ spec_value: string; asin: string; price: number; stock: number }>>([])

function addChildVariationRow() {
  childVariations.value.push({ spec_value: '', asin: '', price: 0, stock: 0 })
}

function removeChildVariation(i: number) {
  childVariations.value.splice(i, 1)
}

function resetVariationState() {
  createVariation.value = false
  variationTheme.value = 'Color'
  childVariations.value = []
}

function resetForm() {
  Object.assign(form, {
    asin: '', sku: '', title: '', brand: '', category: 'other',
    price: 0, cost: 0, fulfillment_type: 'FBA',
    fba_stock: 0, fbm_stock: 0, daily_sales_avg: 0,
    tags: [], notes: '', groups: [],
  })
  resetVariationState()
}

function fillFrom(record: ProductItem) {
  resetVariationState()
  Object.assign(form, {
    asin: record.asin, sku: record.sku, title: record.title,
    brand: record.brand, category: record.category,
    price: record.price, cost: record.cost,
    fulfillment_type: record.fulfillment_type,
    fba_stock: record.fba_stock, fbm_stock: record.fbm_stock,
    daily_sales_avg: record.daily_sales_avg,
    tags: [...record.tags], notes: record.notes,
    groups: [...(record.groups || [])],
  })
}

// 打开时根据 editingId 决定是重置还是填充
watch(open, (val) => {
  if (!val) return
  if (props.editingId) {
    const record = store.items.find(i => i.id === props.editingId)
    if (record) fillFrom(record)
  } else {
    resetForm()
  }
})

async function handleSubmit() {
  if (!form.title.trim()) {
    message.warning('请填写产品标题')
    return
  }
  submitting.value = true
  try {
    // 创建SPU：生成SPU + SKU（走 createVariationGroup）
    if (!props.editingId && createVariation.value) {
      if (!variationTheme.value) {
        message.warning('请选择规格主题')
        return
      }
      const children = childVariations.value.filter(c => c.spec_value.trim())
      if (children.length === 0) {
        message.warning('请至少添加一个 SKU')
        return
      }
      for (const c of children) {
        if (!c.spec_value.trim()) {
          message.warning('SKU的「规格值」不能为空')
          return
        }
      }
      await store.createVariationGroup(
        {
          title: form.title,
          brand: form.brand,
          category: form.category,
          spu_theme: variationTheme.value,
          selling_points: '',
          keywords: [],
          groups: form.groups,
        },
        children.map(c => ({ spec_value: c.spec_value.trim(), asin: c.asin.trim(), price: c.price, stock: c.stock })),
      )
      message.success(`已创建SPU：1 个SPU + ${children.length} 个SKU`)
      open.value = false
      emit('saved')
      return
    }

    // 普通新增/编辑
    const payload = {
      ...form,
      currency: 'USD',
      sub_category: '',
      listing_status: 'pending' as const,
      bsr: null as number | null,
      rating: 0,
      review_count: 0,
      main_image: '',
      images: [] as string[],
      spu_id: null,
      spu_theme: null,
      variations: [] as any[],
      roi: 0,
      margin: form.price > 0 ? Math.round(((form.price - form.cost) / form.price) * 100) : 0,
      shop_id: '',
      status: 'active' as const,
    }
    if (props.editingId) {
      await store.updateItem(props.editingId, payload)
      message.success('产品已更新')
    } else {
      await store.addItem(payload)
      message.success('产品已添加')
    }
    open.value = false
    emit('saved')
  } finally {
    submitting.value = false
  }
}
</script>

<style scoped>
.var-child-row {
  display: flex;
  gap: 8px;
  align-items: center;
  margin-bottom: 8px;
}
</style>
