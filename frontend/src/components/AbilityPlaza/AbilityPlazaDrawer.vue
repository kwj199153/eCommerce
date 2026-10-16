<template>
  <a-drawer
    v-model:open="visible"
    placement="right"
    :width="WINDOW_W.xl"
    :body-style="{ padding: '0 20px 24px' }"
    class="ability-plaza"
  >
    <template #title>
      <div class="ap-head">
        <span class="ap-head-title">能力广场</span>
        <span class="ap-head-sub">点一张卡 ＝ 把这条能力交给这个数字员工去做</span>
      </div>
    </template>

    <a-spin :spinning="skillStore.loading">
      <section
        v-for="group in groups"
        :key="group.id"
        class="ap-group"
      >
        <header class="ap-group-head">
          <span class="ap-group-icon">
            <component :is="group.icon" />
          </span>
          <span class="ap-group-title">{{ group.title }}</span>
          <span class="ap-group-count">{{ group.cards.length }} 项能力</span>
        </header>
        <p class="ap-group-desc">
          {{ group.description }}
        </p>

        <div
          v-if="group.cards.length"
          class="ap-cards"
        >
          <button
            v-for="card in group.cards"
            :key="card.id"
            type="button"
            class="ap-card"
            :title="card.description || card.title"
            @click="useAbility(group, card)"
          >
            <span class="ap-card-icon">{{ card.icon || '⚡' }}</span>
            <span class="ap-card-body">
              <span class="ap-card-title">{{ card.title }}</span>
              <span class="ap-card-desc">{{ card.description }}</span>
            </span>
            <span class="ap-card-go">用这条 →</span>
          </button>
        </div>
        <!-- 空组**不隐藏**：某个员工没有启用能力时，"这一栏是空的"本身就是信息，
             直接抽掉整栏会让用户以为这个员工不存在 -->
        <p v-else class="ap-group-empty">
          这个员工还没有启用的能力
        </p>
      </section>

      <a-empty
        v-if="!groups.length && !skillStore.loading"
        description="还没有可用的能力"
      />
    </a-spin>
  </a-drawer>
</template>

<script setup lang="ts">
/**
 * 能力广场（技能**陈列**面，第 371 轮）
 *
 * ============================================================================
 * ★ 与「Skill 仓库」的关系：**同一份数据源，相反的视角**
 * ============================================================================
 *   数据源都是 `skills` 表（`GET /api/v1/skills`），不是第二份实现。
 *   差的是回答的问题 ——
 *
 *     | | Skill 仓库（`SkillManager.vue`） | 能力广场（本组件） |
 *     |---|---|---|
 *     | 视角 | **管理员**（维护者） | **使用者**（新手） |
 *     | 问的是 | 这条技能**对不对**（正文/版本/生效员工/配套工具） | 我能用它**做什么** |
 *
 *   本项目代码里本来就写着这件事：`SkillManager.vue` 第 255 轮的注释
 *   「技能在这里**集中维护**、按需勾选启用」。⇒ 不需要新建数据源，
 *   也不需要改动那个 1533 行的维护页。
 *
 * ============================================================================
 * ★★ 过滤口径：**只用 `skillsOfAgent()`，前端不另写一套判定**
 * ============================================================================
 *   卡片集合 = `skillStore.skillsOfAgent(agent.name)`，即
 *   `enabled && enabledAgents.includes(agent_name)` —— 与后端
 *   `provider.build_catalog_for` 同口径，且与对话页快捷卡片区**同一个 store 方法**。
 *
 *   ★ 为什么**不**在这里再过滤一遍 `visibility` / `isDemo`：
 *     `GET /skills` 的可见性收口在**后端**（过 `get_acting_user`，只下发当前身份
 *     可见的技能）。前端再算一遍 = 同一判据的第二份实现 —— 两份必然漂移，
 *     而漂移的症状是"某个技能在某处可见、另一处不可见"，没有任何一处会报错。
 *     本仓判据：**前端不得推算后端判据**。
 *
 *   ★ 为什么**不**再摘 `isShortcut === false`（与对话页卡片区不同）：
 *     `isShortcut` 的语义是"要不要在**对话框下方**给它一张快捷卡"，
 *     不是"这条能力能不能用"。能力广场陈列的是**这个员工会什么** ——
 *     像「复盘结论写法」这类**方法型**技能属于该员工的能力，只是不该占
 *     对话页的一格卡片位。把它藏掉，用户就永远看不到它存在。
 *     （点它照样跑得通：`runSkillCard` 不看 `isShortcut`。）
 *
 * ============================================================================
 * ★★ 点一张卡之后：为什么必须**先切视图 + 等两帧**再投递事件
 * ============================================================================
 *   `Workspace.vue` 里 `<ChatPanel v-if="currentView === 'chat'" />` 是**条件渲染**，
 *   而技能点名/发送的落点（`useAgentShortcuts`）住在 ChatPanel **内部**。
 *   ⇒ 用户停在「资料库 / Skill 仓库」等视图时点这里的卡，ChatPanel **根本不存在**，
 *     监听器没挂 ⇒ 直接投递事件会**静默丢失**（点了没反应，且零报错）。
 *
 *   ⇒ 顺序固定为：① 先 `view-navigate` 切到对话视图（Workspace 同步改 `currentView`）；
 *     ② `await nextTick()` 两帧 —— 第一帧完成父组件重渲染 + ChatPanel 挂载，
 *        第二帧兜住子组件 setup 内可能排队的微任务；
 *     ③ 再投递 `ability-plaza:run`。
 *   ★ 两帧不是"多等一会儿保险"：`useAgentShortcuts(ctx)` 在 ChatPanel 的同步 setup
 *     栈里执行，但 `useChatOrchestrator` 内部还有 watch 的 flush 排队 —— 一帧实测
 *     在"用户停在其它视图后立刻点卡"这条路径上不稳。
 *
 *   ★ 投递的是 CustomEvent 而不是直接调 store：这是本仓既定的跨组件范式
 *     （`review-send-to-chat` / `view-navigate` / `product-listing-optimize` 同款）。
 *     事件名 `ability-plaza:run` 的**唯一消费点**在
 *     `composables/chat/useAgentShortcuts.ts`（那里才拿得到 `ctx` / `handleSend`）。
 */
import { computed, nextTick, watch } from 'vue'

import { WINDOW_W } from '@/config/layout'
import { useAgentStore } from '@/stores/agent'
import { useSkillStore, type Skill } from '@/stores/skills'

const props = defineProps<{ open: boolean }>()
const emit = defineEmits<{
  (e: 'update:open', value: boolean): void
}>()

const visible = computed({
  get: () => props.open,
  set: (v: boolean) => emit('update:open', v),
})

const agentStore = useAgentStore()
const skillStore = useSkillStore()

interface AbilityGroup {
  id: string
  title: string
  description: string
  icon: unknown
  cards: Skill[]
}

/**
 * 按**数字员工**分组（顺序 = `GET /agents` 的顺序，即后端 `AGENT_CATALOG` 的顺序）。
 *
 * ★ 顺序不去前端重排：`AGENT_CATALOG` 的注释写明「顺序即界面展示顺序」，
 *   前端再排一次就是第二份实现（改一处就静默失配）。
 * ★ 组内排序按 `name` 升序 —— 与后端 `provider.build_catalog_for` 及
 *   `useAgentShortcuts::skillCards` 同口径；不一致会让同一个员工的技能
 *   在「能力广场」与「对话页卡片」下顺序不同，用户会当成两套数据。
 */
const groups = computed<AbilityGroup[]>(() =>
  skillStore.agents.map((a) => ({
    id: a.id,
    title: a.title,
    description: a.description,
    icon: agentStore.agentList.find((x) => x.id === a.id)?.icon,
    cards: [...skillStore.skillsOfAgent(a.name)].sort((x, y) =>
      x.name < y.name ? -1 : x.name > y.name ? 1 : 0
    ),
  }))
)

/**
 * 打开时补一次目录加载 —— 只在**空**时拉。
 * 与 `useAgentShortcuts` 里那一处同判据：`/agents` 是静态元数据，
 * 技能条目由 store 的写口刷新；这里只是兜住"用户一进站就直接开能力广场"
 * （此时对话页可能从未挂载过，`loadAll()` 从没跑过 ⇒ 广场会是空的）。
 */
watch(
  () => props.open,
  (open) => {
    if (open && !skillStore.agents.length) void skillStore.loadAll()
  }
)

/** 点一张卡 ⇒ 切视图 + 等两帧 + 投递（时序理由见文件头） */
async function useAbility(group: AbilityGroup, card: Skill): Promise<void> {
  visible.value = false
  window.dispatchEvent(new CustomEvent('view-navigate', { detail: { view: 'chat' } }))
  await nextTick()
  await nextTick()
  window.dispatchEvent(
    new CustomEvent('ability-plaza:run', {
      detail: { agentId: group.id, skillName: card.name },
    })
  )
}
</script>

<style scoped>
.ap-head {
  display: flex;
  flex-direction: column;
  gap: 2px;
}
.ap-head-title {
  font-size: var(--font-size-16);
  font-weight: 600;
  color: var(--text-primary);
}
.ap-head-sub {
  font-size: var(--font-size-12);
  font-weight: 400;
  color: var(--text-tertiary);
}

.ap-group {
  padding-top: var(--space-16);
}
.ap-group + .ap-group {
  margin-top: var(--space-8);
  border-top: 1px solid var(--border-base);
}
.ap-group-head {
  display: flex;
  align-items: center;
  gap: var(--space-8);
}
.ap-group-icon {
  display: inline-flex;
  align-items: center;
  font-size: var(--font-size-16);
  color: var(--text-secondary);
}
.ap-group-title {
  font-size: var(--font-size-14);
  font-weight: 600;
  color: var(--text-primary);
}
/* 计数靠右：一眼看出"这个员工有几项能力"，不用数卡片 */
.ap-group-count {
  margin-left: auto;
  font-size: var(--font-size-12);
  color: var(--text-tertiary);
}
.ap-group-desc {
  margin: var(--space-2) 0 var(--space-8);
  font-size: var(--font-size-12);
  line-height: 1.5;
  color: var(--text-tertiary);
}
.ap-group-empty {
  margin: var(--space-2) 0 0;
  font-size: var(--font-size-12);
  color: var(--text-tertiary);
}

.ap-cards {
  display: flex;
  flex-direction: column;
  gap: var(--space-2);
}
/* 用 <button> 而不是 <div>：键盘可达（Tab 能走到、回车能触发），
   且语义上它确实是"一个动作"，不是"一块内容"。 */
.ap-card {
  display: flex;
  align-items: flex-start;
  gap: var(--space-8);
  width: 100%;
  padding: var(--space-8) var(--space-10);
  text-align: left;
  background: var(--bg-elevated, #fff);
  border: 1px solid var(--border-base);
  border-radius: var(--radius-6);
  cursor: pointer;
  transition: border-color 0.15s, background-color 0.15s;
}
.ap-card:hover {
  border-color: var(--primary, #4f46e5);
  background: var(--bg-hover-light, #fafafa);
}
.ap-card-icon {
  flex: 0 0 auto;
  font-size: var(--font-size-16);
  line-height: 1.4;
}
.ap-card-body {
  display: flex;
  flex-direction: column;
  gap: 2px;
  min-width: 0;
  flex: 1 1 auto;
}
.ap-card-title {
  font-size: var(--font-size-13);
  font-weight: 500;
  color: var(--text-primary);
}
.ap-card-desc {
  font-size: var(--font-size-12);
  line-height: 1.5;
  color: var(--text-tertiary);
  /* 描述最多两行，避免长描述把卡片撑成一样高而挤掉后面的卡 */
  display: -webkit-box;
  -webkit-line-clamp: 2;
  -webkit-box-orient: vertical;
  overflow: hidden;
}
.ap-card-go {
  flex: 0 0 auto;
  align-self: center;
  font-size: var(--font-size-12);
  color: var(--primary, #4f46e5);
  opacity: 0;
  transition: opacity 0.15s;
}
.ap-card:hover .ap-card-go,
.ap-card:focus-visible .ap-card-go {
  opacity: 1;
}
</style>
