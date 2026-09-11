<template>
  <a-modal
    v-model:open="open"
    title="提升为SPU"
    width="480px"
    @ok="submit"
    :okLoading="submitting"
    okText="确定组化"
    cancelText="取消"
  >
    <a-alert
      type="info"
      show-icon
      style="margin-bottom: 16px"
      message="本产品将成为该 SPU 的首个 SKU，保留其 ASIN/价格/库存/评分等信息；同时生成一个 SPU 作为公共模板。"
    />
    <a-form :label-col="{ span: 5 }" :wrapper-col="{ span: 18 }">
      <a-form-item label="规格主题" required>
        <a-select v-model:value="promoteForm.spu_theme" placeholder="选择规格维度" style="width: 100%">
          <a-select-option value="Color">颜色 Color</a-select-option>
          <a-select-option value="Size">尺寸 Size</a-select-option>
          <a-select-option value="Color-Size">颜色 + 尺寸</a-select-option>
          <a-select-option value="Style">款式 Style</a-select-option>
          <a-select-option value="Package">包装 Package</a-select-option>
        </a-select>
      </a-form-item>
      <a-form-item label="本产品规格值" required>
        <a-input
          v-model:value="promoteForm.first_value"
          :placeholder="promoteForm.spu_theme === 'Size' ? '如 M / L / XL' : '如 黑色 / 红色'"
        />
      </a-form-item>
    </a-form>
  </a-modal>
</template>

<script setup lang="ts">
import { ref, reactive, watch } from 'vue'
import { message } from 'ant-design-vue'
import { useProductLibraryStore } from '@/stores/productLibrary'

const store = useProductLibraryStore()

const props = defineProps<{
  /** 要提升为 SPU 的产品 id */
  productId: string | null
}>()
const emit = defineEmits<{
  (e: 'saved'): void
}>()

const open = defineModel<boolean>('open', { required: true })

const submitting = ref(false)

const promoteForm = reactive({
  spu_theme: 'Color',
  first_value: '',
})

watch(open, (val) => {
  if (val) Object.assign(promoteForm, { spu_theme: 'Color', first_value: '' })
})

async function submit() {
  if (!promoteForm.spu_theme) {
    message.warning('请选择规格主题')
    return
  }
  if (!promoteForm.first_value.trim()) {
    message.warning('请填写本产品的规格值')
    return
  }
  const product = store.items.find(i => i.id === props.productId)
  if (!product) { message.error('产品不存在'); return }
  submitting.value = true
  try {
    await store.promoteToVariationGroup(
      product,
      promoteForm.spu_theme,
      promoteForm.first_value.trim(),
    )
    message.success('已提升为 SPU，本产品已成为该 SPU 的首个 SKU')
    open.value = false
    emit('saved')
  } finally {
    submitting.value = false
  }
}
</script>
