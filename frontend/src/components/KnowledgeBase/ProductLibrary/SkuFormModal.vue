<template>
  <a-modal
    v-model:open="open"
    :title="editingId ? '编辑SKU' : '新增SKU'"
    width="480px"
    @ok="submit"
    :okLoading="submitting"
    cancelText="取消"
  >
    <a-form :label-col="{ span: 5 }" :wrapper-col="{ span: 18 }">
      <a-form-item label="规格值" required>
        <a-input v-model:value="childForm.spec_value" placeholder="如 红色 / M / XL" />
      </a-form-item>
      <a-form-item label="ASIN">
        <a-input v-model:value="childForm.asin" placeholder="B0XXXXXXXX" />
      </a-form-item>
      <a-form-item label="SKU">
        <a-input v-model:value="childForm.sku" placeholder="内部 SKU" />
      </a-form-item>
      <a-row :gutter="16">
        <a-col :span="12">
          <a-form-item label="价格 ($)">
            <a-input-number v-model:value="childForm.price" :min="0" :precision="2" style="width:100%" />
          </a-form-item>
        </a-col>
        <a-col :span="12">
          <a-form-item label="库存">
            <a-input-number v-model:value="childForm.stock" :min="0" style="width:100%" />
          </a-form-item>
        </a-col>
      </a-row>
    </a-form>
  </a-modal>
</template>

<script setup lang="ts">
import { ref, reactive, watch } from 'vue'
import { message } from 'ant-design-vue'
import { useProductLibraryStore, type ProductItem } from '@/stores/productLibrary'

const store = useProductLibraryStore()

const props = defineProps<{
  /** 编辑中的 SKU id（null = 新增） */
  editingId: string | null
  /** 新增时的父 SPU id */
  parentId: string | null
}>()
const emit = defineEmits<{
  (e: 'saved'): void
}>()

const open = defineModel<boolean>('open', { required: true })

const submitting = ref(false)

const childForm = reactive({
  spec_value: '',
  asin: '',
  sku: '',
  price: 0,
  stock: 0,
})

watch(open, (val) => {
  if (!val) return
  if (props.editingId) {
    const child = store.items.find(i => i.id === props.editingId)
    if (child) {
      Object.assign(childForm, {
        spec_value: child.spec_value || '',
        asin: child.asin,
        sku: child.sku,
        price: child.price,
        stock: child.fba_stock,
      })
    }
  } else {
    Object.assign(childForm, { spec_value: '', asin: '', sku: '', price: 0, stock: 0 })
  }
})

async function submit() {
  if (!childForm.spec_value.trim()) {
    message.warning('请填写规格值')
    return
  }
  submitting.value = true
  try {
    if (props.editingId) {
      // 编辑已有SKU
      await store.updateItem(props.editingId, {
        spec_value: childForm.spec_value.trim(),
        asin: childForm.asin.trim(),
        sku: childForm.sku.trim(),
        price: childForm.price,
        fba_stock: childForm.stock,
        title: `${store.items.find(i => i.id === props.editingId)?.title.split(' - ')[0] || ''} - ${childForm.spec_value.trim()}`,
      })
      message.success('SKU已更新')
    } else if (props.parentId) {
      // 新增SKU到SPU下
      const parent = store.findRowById(props.parentId)
      if (!parent) { message.error('SPU不存在'); return }
      await store.addChildVariation(parent, {
        spec_value: childForm.spec_value.trim(),
        asin: childForm.asin.trim(),
        sku: childForm.sku.trim(),
        price: childForm.price,
        stock: childForm.stock,
      })
      message.success('SKU已添加')
    }
    open.value = false
    emit('saved')
  } finally {
    submitting.value = false
  }
}
</script>
