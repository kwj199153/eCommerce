<template>
  <!--
    翻译类浮层：**全局各挂一次**。

    ★ 为什么要有这个壳（第 363 轮）：
      `Workspace.vue` 已经 1470 行，而它是体量棘轮冻结表里的文件
      （`tests/test_source_size_ratchet.py`，冻结值 1466，只许降不许升）。
      往它里面再加一个浮层就是让一个**已经越线**的文件继续长大。
      把「翻译浮层」这一组收口到一个组件里，消费方只需一行 ——
      以后再加第三种翻译入口（语音、OCR 点选…）也不用动 `Workspace.vue`。

    ★ 这个浮层的特点（第 367 轮起这里只剩划词一个）：
      · `Teleport to="body"`，与宿主布局无关；
      · 依赖全局事件（`selectionchange`），不接收任何 props；
      · 必须**全局只有一份实例**（内部有单例状态，挂两份 = 两个浮层抢同一份状态）。
      · **没有入口 UI** —— 划词翻译是被动弹出（选中即译），不是主动发起。

    ★ 为什么只剩一个也不并回 `Workspace.vue`：
      第 367 轮把「截屏翻译 + 粘贴图片」整套退场，这里就空出半个壳。
      并回去能少一个文件，但那是把那个**已经越线**的文件再推回去；
      壳留着，下一个翻译入口加进来时消费方仍然只需一行。
  -->
  <SelectionTranslateLayer />
</template>

<script setup lang="ts">
// ★ 只做「挂载」这一件事：这里**不写任何逻辑**。
//   一旦往里加状态，它立刻变成第三个实现该状态的地方（本仓禁止两份实现）。
import SelectionTranslateLayer from './SelectionTranslateLayer.vue'
</script>
