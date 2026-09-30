<template>
  <div class="knowledge-base" data-tour="tour-sidebar-repo">
    <!-- 「竞品监控」独立入口已下线：看板并入竞品监控员的右侧边栏；
         旧入口（蓝海抽屉 / 选品库开启监控 / 店秘书导航）在 Workspace 统一重定向。 -->
    <div class="sidebar-section-title">资料库</div>
    <a-menu
      class="sidebar-nav-menu"
      mode="inline"
      :selectedKeys="selectedKeys"
      @click="handleMenuClick"
    >
      <!-- ★★ 第 269 轮：老板指定「资料库」这一组的**顺序**为
           候选池-竞品池-素材库-自有产品库-业务话术库-复盘库-平台规则库
           （对应 key：candidates-competitors-assets-products-faq-reviews-rules）。
           改动**只调顺序**：三个库的改名（选品库→候选池 / 营销素材库→素材库 /
           竞品监控池→竞品池）因影响面过大本轮**未做** —— 详见
           `.workbuddy/memory/_pending/第269轮.md`。key 一律未动。
           顺序**不**是契约：`check-review-library-view.cjs` 的 D1/D4 用**集合相等**
           （`uniq+sorted` 后比较）判定，故此处重排不会、也不该让那条门禁变红。 -->
      <a-menu-item key="candidates">
        <FilterOutlined />
        <span>选品库</span>
      </a-menu-item>
      <a-menu-item key="competitors">
        <FundOutlined />
        <span>竞品监控池</span>
      </a-menu-item>
      <a-menu-item key="assets">
        <PictureOutlined />
        <span>营销素材库</span>
      </a-menu-item>
      <a-menu-item key="products">
        <DatabaseOutlined />
        <span>自有产品库</span>
      </a-menu-item>
      <a-menu-item key="faq">
        <MessageOutlined />
        <span>业务话术库</span>
      </a-menu-item>
      <!-- ★ 第 251 轮：复盘库（第 7 个资料库）。
           与同组其它库一样按 `X-Shop-ID` 过滤 —— 它不是「账号级」的东西，
           所以**不能**放到下面「能力」那一组。
           key 必须与后端 `review_analyst/spec.py::REVIEW_SPEC.key`（"reviews"）
           和 `utils/appActions.ts::AppView` 逐字一致；跨端对齐由
           `scripts/check-review-library-view.cjs` 钉住。
           ★ 第 269 轮：位置由末位前移到「平台规则库」之前（老板指定的顺序），key 未动。 -->
      <a-menu-item key="reviews">
        <FileDoneOutlined />
        <span>复盘库</span>
      </a-menu-item>
      <a-menu-item key="rules">
        <SafetyCertificateOutlined />
        <span>平台规则库</span>
      </a-menu-item>
      <!-- ★ 第 291 轮：差评处置**从这个分组撤掉** —— 它不是独立的资料库，
           而是「差评台账」这条能力的后半段（批准 / 发放），已并入客服功能栏
           「差评台账」右栏面板的**处置台账**视图。留在这儿的结果是同一个
           不可逆的人审动作在两处都有按钮，HITL 的唯一把关点被架空。
           谁要是想把它加回来，请先去看 `TaskConfigPanel/configs/ReviewDeskConfig.vue`。
           注：删完本组 8 个 key 变 7 个 —— `check-review-library-view.cjs`
           的 B0 判的是「≥7」，正好卡在下界上，再删一个就该改那条门禁了。 -->
    </a-menu>

    <!-- 「Skill 仓库 / 工具仓库」与「资料库」**同级**（各自一个分节），刻意不并进上面那组：
         资料库那一组全部按 `X-Shop-ID` 过滤（换店铺就换内容），
         而技能是**账号级**、工具是**平台级**的，都与店铺无关。
         并进同一组会让人以为「换个店铺技能就变了」。
         ★ 第 209 轮：分节名由「技能」改为「能力」—— 节里不再只有技能。 -->
    <div class="sidebar-section-title">能力</div>
    <a-menu
      class="sidebar-nav-menu"
      mode="inline"
      :selectedKeys="selectedKeys"
      @click="handleMenuClick"
    >
      <a-menu-item key="skills">
        <ThunderboltOutlined />
        <span>Skill 仓库</span>
      </a-menu-item>
      <!-- ★ 第 209 轮：工具仓库与 Skill 仓库**平级**（老板原话「与 skill 仓库平级」）。
           两个独立入口、各自一套 tab；**不**并成同一个页面的两个 tab。
           工具本身由代码定义（不可新建），所以这个入口是**只读目录 + 两条绑定视图**。 -->
      <a-menu-item key="tools">
        <AppstoreOutlined />
        <span>工具仓库</span>
      </a-menu-item>
    </a-menu>
  </div>
</template>

<script setup lang="ts">
import { ref } from 'vue'
import {
  AppstoreOutlined,
  MessageOutlined,
  DatabaseOutlined,
  PictureOutlined,
  FilterOutlined,
  SafetyCertificateOutlined,
  FundOutlined,
  FileDoneOutlined,
  ThunderboltOutlined,
} from '@ant-design/icons-vue'

const emit = defineEmits<{
  (e: 'navigate', key: string): void
}>()

const selectedKeys = ref<string[]>([])

const handleMenuClick = ({ key }: { key: string }) => {
  selectedKeys.value = [key]
  emit('navigate', key)
}

/** 外部可调用的切换方法（只同步高亮；视图切换由 'navigate' 的接收方决定） */
function navigateTo(key: string) {
  selectedKeys.value = [key]
}

defineExpose({ navigateTo })
</script>

<style scoped>
/* ★ 第 260 轮：分组标题与菜单项样式已收进 `src/styles/sidebar-nav.css`（唯一真源，
   与 AgentList.vue 共用同一份 —— 改一次两处生效）。
   这里只保留容器自身：**不得**再加纵向 padding，那会与标题的 margin-top 叠加，
   让「资料库 / 能力」的上间距与第一个分组不一致（正是本轮修掉的缺陷）。
   `.knowledge-base` 这个类名被 scripts/cdp-repo-banner-tab-probe.mjs 依赖，勿改名。 */
.knowledge-base {
  padding: 0;
}
</style>
