<template>
  <div class="tool-manager">
    <!-- ============ 顶部工具条（照 SkillManager 的范式）============ -->
    <div class="tm-toolbar">
      <div class="tm-head">
        <span class="tm-head-title">工具仓库</span>
        <span class="tm-head-sub">
          工具由<b>代码</b>定义（后端 <code>tools_catalog.py</code> 是唯一真源）——
          本页<b>不能新建工具</b>，也不改工具归属。
          <br />
          ★ <b>确定可计算 → 工具</b>
        </span>
      </div>
      <div class="tm-head-actions">
        <a-button :loading="store.loading" @click="store.loadAll()">刷新</a-button>
      </div>
    </div>

    <a-alert
      v-if="store.error"
      type="error"
      show-icon
      class="tm-block-gap"
      message="加载失败"
      :description="store.error"
    />

    <a-tabs v-model:activeKey="tab" class="tm-tabs">
      <!-- ==================== Tab 1：工具管理 ==================== -->
      <a-tab-pane key="catalog" tab="工具管理">
        <p class="tm-tip">
          <b>只读目录。</b>工具是代码里的静态表 —— 没有 <code>tools</code> 表、没有实体、
          没有归属列，所以「新建工具」这件事<b>结构上就不存在</b>（不是"暂时没做"）。
          工具属于哪个 Agent 也是<b>代码声明</b>的，后端门禁断言它与真实装配点集合相等
          ⇒ 改它要改代码。<b>可写的绑定只有一处：「skill 配装」。</b>
        </p>

        <div v-if="store.toolUsage" class="tm-chips tm-block-gap">
          <span class="tm-chip">工具 {{ store.tools.length }} 个</span>
          <span class="tm-chip">已被引用 {{ store.toolUsage.referencedTools }} 个</span>
          <span class="tm-chip" :class="{ 'tm-chip-off': !store.unusedTools.length }">
            未被引用 {{ store.unusedTools.length }} 个
          </span>
          <span class="tm-chip tm-chip-quiet">
            按可见技能计 {{ store.toolUsage.totalSkills }} 个
          </span>
        </div>

        <!-- ★ 这是「被引用到不存在的名字」的展示面。
             读口 render_skill_tools 不校验工具名存在性，所以工具退役后
             库里可能还留着旧名字，而用户此前看不见、也就改不掉。
             这里只陈述事实并指路，不改任何写口行为。 -->
        <a-alert
          v-if="store.unknownTools.length"
          type="warning"
          show-icon
          class="tm-block-gap"
          message="有技能引用了目录里不存在的工具"
          :description="`${store.unknownTools.join('、')} —— 这些名字在运行期调不到（它们不在任何 Agent 手上）。请到「skill 配装」tab 取消勾选后保存。`"
        />

        <!-- 筛选栏：**常驻在判空之外**。筛空时它不能跟着消失，
             否则「重置筛选」就成了唯一的逃生口却够不着。 -->
        <div class="tm-filters">
          <a-input-search
            v-model:value="store.toolSearchQuery"
            placeholder="搜索工具名 / 中文名 / 说明"
            style="width: 240px"
            allow-clear
          >
            <template #prefix><SearchOutlined /></template>
          </a-input-search>

          <a-select
            v-model:value="store.filterToolAgent"
            style="width: 160px"
            placeholder="全部 Agent"
            allow-clear
          >
            <a-select-option v-for="a in store.agents" :key="a.name" :value="a.name">
              {{ a.title }}
            </a-select-option>
          </a-select>

          <a-select
            v-model:value="store.filterToolEffect"
            style="width: 130px"
            placeholder="副作用不限"
            allow-clear
          >
            <a-select-option value="approval">需审批</a-select-option>
            <a-select-option value="read_only">只读</a-select-option>
          </a-select>

          <a-select
            v-model:value="store.filterToolCited"
            style="width: 150px"
            placeholder="引用状态不限"
            allow-clear
          >
            <a-select-option value="cited">有技能引用</a-select-option>
            <a-select-option value="uncited">无技能引用</a-select-option>
          </a-select>

          <a-button
            v-if="store.toolFilterCount"
            size="small"
            @click="store.resetToolFilters()"
          >
            重置筛选（{{ store.toolFilterCount }}）
          </a-button>

          <div class="view-switch tm-viewswitch">
            <button
              :class="['view-btn', { active: view === 'grid' }]"
              title="平铺"
              @click="view = 'grid'"
            >
              <AppstoreOutlined />
            </button>
            <button
              :class="['view-btn', { active: view === 'list' }]"
              title="列表"
              @click="view = 'list'"
            >
              <BarsOutlined />
            </button>
          </div>
        </div>

        <a-spin :spinning="store.loading">
          <a-empty v-if="!store.tools.length" description="工具目录加载失败或为空" />
          <template v-else>
            <!-- ★ 筛选后为空 ⇒ **直接空**（照「快捷卡片管理」tab 的既有判据）：
                 不另起一个空状态块，因为筛选栏已在判空之外、
                 「重置筛选」任何状态下都够得着。 -->
            <div v-if="view === 'grid'" class="tm-grid">
              <div v-for="t in flatTools" :key="t.name" class="tm-card">
                <div class="tm-card-head">
                  <span class="tm-card-title">{{ t.title || t.name }}</span>
                  <a-tag v-if="t.effect === 'approval'" color="orange">需审批</a-tag>
                  <a-tag v-if="(t.agents || []).length > 1" color="blue">
                    {{ (t.agents || []).length }} 家共用
                  </a-tag>
                  <a-tag v-if="!store.usageOfTool(t.name).length">未被引用</a-tag>
                </div>
                <div class="tm-card-key">{{ t.name }}</div>
                <p class="tm-card-desc">{{ t.description }}</p>

                <div class="tm-card-line">
                  <span class="tm-meta-label">归属</span>
                  <span
                    v-for="a in t.agents || [t.agent]"
                    :key="a"
                    class="tm-chip tm-chip-quiet"
                  >
                    {{ titleOfAgent(a) }}
                  </span>
                </div>

                <div class="tm-card-line">
                  <span class="tm-meta-label">被引用于</span>
                  <template v-if="store.usageOfTool(t.name).length">
                    <a-tooltip
                      v-for="r in store.usageOfTool(t.name)"
                      :key="r.id"
                      :title="refTooltip(r)"
                    >
                      <span class="tm-chip" :class="{ 'tm-chip-off': !r.enabled }">
                        {{ r.title }}<template v-if="!r.enabled"> · 已停用</template>
                      </span>
                    </a-tooltip>
                  </template>
                  <span v-else class="tm-muted">
                    没有任何技能引用它 —— 模型不会被引导去调它。
                  </span>
                </div>
              </div>
            </div>

            <div v-else class="tm-list">
              <div v-for="t in flatTools" :key="t.name" class="tm-row">
                <span class="tm-row-title">{{ t.title || t.name }}</span>
                <span class="tm-row-key">{{ t.name }}</span>
                <a-tag v-if="t.effect === 'approval'" color="orange">需审批</a-tag>
                <span class="tm-row-agents">
                  {{ (t.agents || [t.agent]).map(titleOfAgent).join('、') }}
                </span>
                <span class="tm-row-refs">
                  <template v-if="store.usageOfTool(t.name).length">
                    被引用 {{ store.usageOfTool(t.name).length }} 次
                  </template>
                  <span v-else class="tm-muted">未被引用</span>
                </span>
              </div>
            </div>
          </template>
        </a-spin>
      </a-tab-pane>

      <!-- ==================== Tab 2：skill 配装 ==================== -->
      <a-tab-pane key="skill-tools" tab="skill 配装">
        <p class="tm-tip">
          <b>勾选即存</b>：这里改的是「该技能<b>配备</b>哪些工具」。
          <br />
          ★★ 必须说清它的真实作用：<b>这是提示词层面的引导，不是权限。</b>
          Agent 手上真正有哪些工具由<b>代码装配</b>决定（真源 <code>TOOL_CATALOG</code>），
          <code>skill.tools</code> 的唯一去处是把「本技能配套工具」渲染进提示词。
          ⇒ <b>勾了不等于授权，没勾也不等于禁止。</b>
          要判断一条引用跑不跑得起来，看那个工具是否属于该技能所启用的 Agent
          （见「Agent 配装」tab 的「调不到」标记）。
        </p>

        <a-alert
          v-if="!canWrite"
          type="info"
          show-icon
          class="tm-block-gap"
          message="当前身份只读"
          description="登录（或从演示模式进入）后才能修改技能的配套工具。"
        />

        <a-spin :spinning="store.loading">
          <a-empty v-if="!store.items.length" description="没有可见的技能" />
          <div v-else class="tm-skill-list">
            <div v-for="s in skillsSorted" :key="s.id" class="tm-skill-row">
              <div class="tm-skill-head">
                <span class="tm-skill-title">
                  <span v-if="s.icon" class="tm-skill-icon">{{ s.icon }}</span>
                  {{ s.title || s.name }}
                </span>
                <span class="tm-skill-key">{{ s.name }}</span>
                <a-tag v-if="!s.enabled">已停用</a-tag>
              </div>

              <div class="tm-card-line">
                <span class="tm-meta-label">生效于</span>
                <template v-if="(s.enabledAgents || []).length">
                  <span
                    v-for="a in s.enabledAgents"
                    :key="a"
                    class="tm-chip tm-chip-quiet"
                  >
                    {{ titleOfAgent(a) }}
                  </span>
                </template>
                <span v-else class="tm-muted">
                  未对任何 Agent 生效 —— 模型连它的名字都看不到。
                </span>
              </div>

              <!-- ★ 库里可能残留**已退役**的工具名（工具退役后库里没人清）。
                   这份名单取自后端 `/tools/usage` 的 `unknownTools`，
                   不在前端另算一遍"这个名字存不存在"。 -->
              <a-alert
                v-if="unknownOf(s).length"
                type="warning"
                show-icon
                class="tm-inline-warn"
                message="含目录里不存在的工具名"
                :description="`${unknownOf(s).join('、')} —— 已退役的名字，运行期调不到。请把它们取消勾选后保存。`"
              />

              <!-- ★★ 候选集**按该技能的生效 Agent 收窄**（第 255 轮）。
                   收窄判定与技能仓库编辑抽屉**共用同一实现**
                   （`store.toolOptionsFor`）；
                   这里不再自己 `v-for="g in store.toolGroups"` 平铺全部 Agent ——
                   平铺会造出「技能引导了该 Agent 手上没有的工具」这种运行期调不到的绑定，
                   而界面上完全看不出来。 -->
              <a-select
                mode="multiple"
                class="tm-tool-select"
                :value="s.tools || []"
                :disabled="!canWrite || !s.enabled"
                :options="toolOptionsOf(s)"
                :placeholder="toolPlaceholderOf(s)"
                :max-tag-count="'responsive'"
                option-filter-prop="label"
                @change="(v: unknown) => saveTools(s, v as string[])"
              />
            </div>
          </div>
        </a-spin>
      </a-tab-pane>

      <!-- ==================== Tab 3：Agent 配装 ==================== -->
      <a-tab-pane key="agent-wiring" tab="Agent 配装">
        <p class="tm-tip">
          <b>只读总览。</b>「Agent 手上有哪些工具」是<b>代码声明</b>的
          （<code>TOOL_CATALOG[].agent / agents</code>），后端门禁断言它与
          <b>真实装配点集合相等</b> ⇒ 这里<b>没有可勾的写动作</b>：
          做成可勾会造出第二个真源，且没有任何门禁会红。
          可写的绑定只有「skill 配装」那一处。
          <br />
          ★ 本 tab 真正的用处是看<b>组合约束</b>：技能引导了某工具、
          但那个工具<b>不属于</b>该 Agent ⇒ 运行期调不到（「给了方法，没给原料」）。
          这类缺口在别处看不见。
        </p>

        <div class="tm-chips tm-block-gap">
          <span class="tm-chip">Agent {{ store.agents.length }} 个</span>
          <span class="tm-chip">工具 {{ store.tools.length }} 个</span>
          <span class="tm-chip" :class="{ 'tm-chip-off': !mismatchTotal }">
            引用了但调不到 {{ mismatchTotal }} 条
          </span>
        </div>

        <a-spin :spinning="store.loading">
          <a-empty v-if="!store.agents.length" description="Agent 目录加载失败或为空" />
          <div v-else class="tm-agent-list">
            <div v-for="a in store.agents" :key="a.name" class="tm-agent-card">
              <div class="tm-agent-head">
                <span class="tm-agent-title">{{ a.title }}</span>
                <span class="tm-agent-key">{{ a.name }}</span>
                <a-tag color="blue">手上 {{ toolsOfAgent(a.name).length }} 个工具</a-tag>
                <a-tag color="green">
                  启用 {{ store.skillsOfAgent(a.name).length }} 个技能
                </a-tag>
              </div>

              <div class="tm-card-line">
                <span class="tm-meta-label">手上的工具（代码声明）</span>
                <template v-if="toolsOfAgent(a.name).length">
                  <span
                    v-for="t in toolsOfAgent(a.name)"
                    :key="t.name"
                    class="tm-chip"
                    :class="{ 'tm-chip-warn': t.effect === 'approval' }"
                    :title="t.description"
                  >
                    {{ t.title }}<template v-if="t.effect === 'approval'"> · 需审批</template>
                  </span>
                </template>
                <span v-else class="tm-muted">（这个 Agent 手上没有工具）</span>
              </div>

              <div class="tm-card-line">
                <span class="tm-meta-label">启用的技能</span>
                <template v-if="store.skillsOfAgent(a.name).length">
                  <span
                    v-for="s in store.skillsOfAgent(a.name)"
                    :key="s.id"
                    class="tm-chip tm-chip-quiet"
                  >
                    {{ s.title || s.name }}
                  </span>
                </template>
                <span v-else class="tm-muted">（没有启用任何技能）</span>
              </div>

              <div class="tm-card-line tm-card-line-wrap">
                <span class="tm-meta-label">技能引导的工具</span>
                <template v-if="guidanceOfAgent(a.name).length">
                  <span
                    v-for="row in guidanceOfAgent(a.name)"
                    :key="row.tool"
                    class="tm-chip"
                    :class="row.reachable ? '' : 'tm-chip-warn'"
                    :title="
                      row.reachable
                        ? '该工具在本 Agent 手上 —— 引用可生效'
                        : '★ 该工具不属于本 Agent —— 运行期调不到（技能给了方法，没给原料）'
                    "
                  >
                    {{ store.titleOfTool(row.tool) }}
                    <template v-if="!row.reachable"> · 调不到</template>
                  </span>
                </template>
                <span v-else class="tm-muted">（没有技能引导任何工具）</span>
              </div>
            </div>
          </div>
        </a-spin>
      </a-tab-pane>
    </a-tabs>
  </div>
</template>

<script setup lang="ts">
/**
 * 工具仓库（第 208 轮建「只读查看」→ 第 209 轮提升为**与 Skill 仓库平级**的页面）
 *
 * ============================================================================
 * ★ 需求原文（第 209 轮）
 * ============================================================================
 *   「我需要的工具仓库是与 skill 仓库平级的。界面可以参考 skill 仓库页面
 *    （仓库页面的技能仓库改为技能管理），tab 页面有工具管理（也有过滤器这些，
 *    平铺/列表 tab）、skill 配装、Agent 配装。」
 *   老板对「配装」语义的裁决：「技能配工具，Agent 配工具」
 *     + 反问「都是只读，还是说 Agent 不会单独配工具，都是走技能这条路？」
 *
 * ============================================================================
 * ★★★ 三条「真源」事实 —— 本页所有"为什么这里是只读"的来源
 * ============================================================================
 *  ① **工具本身**：真源是代码里的静态表 `tools_catalog.py::TOOL_CATALOG`。
 *     没有 `tools` 表 / ORM 实体 / 归属列 ⇒ 「新建工具」**结构上不存在**。
 *
 *  ② **工具归属哪个 Agent**：同样是代码声明。后端
 *     `tests/test_tool_catalog.py` 判据 A 断言这张表与**真实装配点**
 *     （`ASSEMBLY_POINTS` 登记的容器/工厂）**集合相等**；判据 B 还断言每条
 *     `effect`（含「需审批」）与工具自己 `metadata` 的副作用声明一致。
 *     ⇒ 做成可勾 = 造出第二个真源 + 与代码那份必然漂移 + **没有任何门禁会红**。
 *        所以「Agent 配装」tab 是**只读总览**（老板的反问，答案是
 *        「Agent 不单独配工具，工具到 Agent 这条路只有代码声明这一条」）。
 *
 *  ③ **技能配备哪些工具**（`skill.tools`）：这是**唯一可写**的工具绑定面
 *     （`PUT /skills/{id}/tools`）。但它在运行期**既不授予也不限制**任何工具：
 *     `build_skill_tools()` 恒只返回一个 `load_skill`，Agent 的工具面来自
 *     `BaseAgent.__init__` 的装配；`skill.tools` 的唯一去处是
 *     `render_skill_body()` 往提示词里渲染「本技能配套工具」。
 *     ⇒ 它是**提示词引导**（软），不是权限。界面必须如实标注
 *        （否则用户会以为"勾了就等于授权"）。
 *
 * ============================================================================
 * ★ 与 Skill 仓库的分工（两个**平级**入口，各自唯一）
 * ============================================================================
 *   Skill 仓库页 = 快捷卡片管理（技能本身的增删改 / 版本 / 筛选）+ Agent 装配
 *   工具仓库页   = 本页：工具管理 + skill 配装 + Agent 配装
 *   两条可写的绑定边各只出现一次，不重叠：
 *     · 技能 ← 工具 ⇒ 本页「skill 配装」
 *     · 技能 ← Agent ⇒ Skill 仓库页「Agent 装配」
 *
 * ============================================================================
 * ★ 数据来源（一个前端**自己算**的判据都没有）
 * ============================================================================
 *   `/tools`        工具目录 + 按 Agent 分组（`grouped` 由后端给）
 *   `/tools/usage`  反向引用 + `unknownTools` / `unusedTools`（同一次遍历的三个投影）
 *   `/skills`       技能列表（含 `tools` / `enabledAgents`）
 *   `/agents`       平台 Agent 目录
 *   ★ 「这个名字在不在目录里」一律读**后端给的 `unknownTools`**，
 *     不在前端拿目录做第二遍差集 —— 两份实现必然有一份先漂移。
 */

import { computed, onMounted, ref } from 'vue'
import { message } from 'ant-design-vue'
import {
  AppstoreOutlined,
  BarsOutlined,
  SearchOutlined,
} from '@ant-design/icons-vue'
import { useSkillStore } from '@/stores/skills'
import type { Skill, ToolCatalogItem, ToolUsageRef } from '@/stores/skills'
import { useUserStore } from '@/stores/user'

const store = useSkillStore()
const userStore = useUserStore()

/**
 * 三个 tab。
 * ★ `agent-wiring` 是**只读**总览，不含任何写动作（理由见文件头 ②）。
 */
const tab = ref<'catalog' | 'skill-tools' | 'agent-wiring'>('catalog')

/** 工具管理的视图形态：平铺（卡片网格）/ 列表（一行一项），与技能页同形 */
const view = ref<'grid' | 'list'>('grid')

/**
 * 能否写。判据与 `SkillManager` 一致（`!!token`）。
 *
 * ★ 方向选择：**拿不到凭据就禁用**。两个方向的代价不对称 ——
 *   误禁一个勾选只是多一次点击，误放行一次写会真的改到数据。
 *   （且真正的门禁在后端：`_reject_no_identity` + `ensure_can_access_skill`。）
 */
const canWrite = computed(() => !!userStore.token)

/**
 * 该技能「配套工具」的候选集 —— 走 store 的**唯一收窄实现**（第 255 轮）。
 *
 * ★ 本页**不做**自己的收窄判断：两处入口各写一份的结果就是口径漂移，
 *   而漂移的表现（能造出运行期调不到的绑定）在界面上看不出来。
 * ★ 传 `s.tools` 进去而不是只传 Agent 集合：已绑定但不在候选里的项要**保留**
 *   在 orphan 组里显示 —— 否则这里一保存就**静默删掉了那些绑定**
 *   （判据「拿不到权威清单 ≠ 清单为空」，详见 store 内注释）。
 */
function toolOptionsOf(s: Skill) {
  return store.toolOptionsFor(s.enabledAgents || [], s.tools || [])
}

/**
 * 候选为空时的占位提示 —— **把"为什么空"说清楚**。
 *
 * ★ 无生效 Agent ⇒ 候选**必然**为空（候选 = 生效 Agent 手上的工具）。
 *   统一说「（未配备任何工具）」会让用户以为工具被删了，而实际是
 *   这条技能还没勾选生效 Agent（与技能抽屉同一判据）。
 */
function toolPlaceholderOf(s: Skill): string {
  return (s.enabledAgents || []).length
    ? '（未配备任何工具）'
    : '该技能未对任何 Agent 生效 —— 先到「技能仓库」勾选生效 Agent，这里才有候选'
}

const flatTools = computed<ToolCatalogItem[]>(() =>
  store.filteredToolGroups.flatMap((g) => g.tools)
)

const skillsSorted = computed<Skill[]>(() =>
  [...store.items].sort((a, b) =>
    String(a.title || a.name).localeCompare(String(b.title || b.name), 'zh-Hans-CN')
  )
)

function titleOfAgent(name: string): string {
  return store.titleOfAgent(name) || name
}

/** 某技能 `tools` 里**后端认定为未注册**的那些名字 */
function unknownOf(s: Skill): string[] {
  const bad = new Set(store.unknownTools)
  return (s.tools || []).filter((t) => bad.has(t))
}

function refTooltip(r: ToolUsageRef): string {
  const agents = (r.enabledAgents || []).map(titleOfAgent).join('、') || '（未绑定任何 Agent）'
  return [
    `技能：${r.title || r.name}`,
    `标识：${r.name}`,
    r.enabled ? '状态：已启用' : '状态：已停用（该技能不会被注入，引用等于没写）',
    `生效于：${agents}`,
    '★ 技能引用工具只是「提示词引导」；工具能不能调起来，',
    '   取决于它是否在那个 Agent 手上。',
  ].join('\n')
}

function toolsOfAgent(agentName: string): ToolCatalogItem[] {
  return store.toolGroups.find((g) => g.agent === agentName)?.tools || []
}

/**
 * 某个 Agent 名下：技能引导了哪些工具、其中哪些**不在它手上**。
 *
 * ★ 这是本页真正不可替代的信息：正向边（技能配了哪些工具）与
 *   归属边（工具在谁手上）分开看都"正常"，只有放在一起才看得出
 *   「给了方法，没给原料」—— 这类配置看起来生效、运行时无事可做，
 *   而且别处没有任何展示面。
 */
function guidanceOfAgent(agentName: string): { tool: string; reachable: boolean }[] {
  const owned = new Set(toolsOfAgent(agentName).map((t) => t.name))
  const out: { tool: string; reachable: boolean }[] = []
  const seen = new Set<string>()
  for (const s of store.skillsOfAgent(agentName)) {
    for (const t of s.tools || []) {
      if (seen.has(t)) continue
      seen.add(t)
      out.push({ tool: t, reachable: owned.has(t) })
    }
  }
  return out
}

const mismatchTotal = computed(() =>
  store.agents.reduce(
    (n, a) => n + guidanceOfAgent(a.name).filter((r) => !r.reachable).length,
    0
  )
)

/**
 * 「skill 配装」的保存：**勾选即存**（照 Skill 仓库「Agent 装配」的既有范式）。
 *
 * ★ 传**完整的目标数组**（`a-select multiple` 的 change 事件天然就是全量值）
 *   ⇒ 后端全量覆盖，天然幂等；不做增量 add/remove（并发勾选会产生
 *   无法解释的合并结果）。
 * ★ 失败必须**回写界面状态**：`store.saveSkillTools` 会把错误写进 `store.error`，
 *   这里据此弹提示。不弹的话所有失败都被转译成「随机失败」。
 */
async function saveTools(s: Skill, toolNames: string[]) {
  const ok = await store.saveSkillTools(s.id, toolNames)
  if (!ok) {
    message.error(store.error || '保存失败')
  } else {
    message.success('已保存')
  }
}

onMounted(() => {
  // 本页三张表都要：目录（工具管理）、反向引用（被引用于/未注册）、技能（配装）
  if (!store.tools.length || !store.items.length || !store.toolUsage) {
    store.loadAll()
  }
})
</script>

<style scoped>
/* ★ 配色只用既有 token（`App.vue` 的 --space/--radius/--font-size-*，
   `theme/presets.ts` 的语义色），**不引入任何裸 hex** ——
   本仓有「硬编码颜色收敛」的棘轮门禁，新加的裸色值都会变成要还的债。 */

.tool-manager {
  padding: var(--space-14);
  color: var(--text-primary);
}

/* ---- 顶部工具条 ---- */
.tm-toolbar {
  display: flex;
  align-items: flex-start;
  justify-content: space-between;
  gap: var(--space-12);
  margin-bottom: var(--space-10);
}
.tm-head-title {
  font-size: var(--font-size-16);
  font-weight: 600;
  margin-right: var(--space-8);
}
.tm-head-sub {
  font-size: var(--font-size-12);
  color: var(--text-secondary);
}
.tm-head-actions {
  flex: none;
}

.tm-tabs :deep(.ant-tabs-nav) {
  margin-bottom: var(--space-10);
}

.tm-tip {
  font-size: var(--font-size-12);
  line-height: 1.7;
  color: var(--text-secondary);
  background: var(--bg-elevated);
  border: 1px solid var(--border-base);
  border-radius: var(--radius-8);
  padding: var(--space-10);
  margin-bottom: var(--space-12);
}
.tm-tip code {
  font-family: var(--font-mono);
  font-size: var(--font-size-11);
}

.tm-block-gap {
  margin-bottom: var(--space-12);
}

/* ---- chips ---- */
.tm-chips {
  display: flex;
  flex-wrap: wrap;
  align-items: center;
  gap: var(--space-6);
}
.tm-chip {
  display: inline-block;
  font-size: var(--font-size-11);
  line-height: 1.6;
  padding: 1px var(--space-6);
  border-radius: var(--radius-6);
  border: 1px solid var(--border-base);
  background: var(--bg-elevated);
  color: var(--text-secondary);
  white-space: nowrap;
}
.tm-chip-quiet {
  color: var(--text-tertiary);
}
.tm-chip-off {
  color: var(--text-disabled);
}
.tm-chip-warn {
  border-color: var(--warning-border);
  background: var(--warning-bg);
  color: var(--warning-strong);
}
.tm-meta-label {
  font-size: var(--font-size-11);
  color: var(--text-tertiary);
  margin-right: var(--space-4);
  flex: none;
}
.tm-muted {
  font-size: var(--font-size-11);
  color: var(--text-tertiary);
}

/* ---- 筛选栏（一行，动作在行内）---- */
.tm-filters {
  display: flex;
  flex-wrap: wrap;
  align-items: center;
  gap: var(--space-8);
  margin-bottom: var(--space-12);
}
.tm-viewswitch {
  margin-left: auto;
}

/* ---- 平铺 ---- */
.tm-grid {
  display: grid;
  grid-template-columns: repeat(auto-fill, minmax(320px, 1fr));
  gap: var(--space-12);
}
.tm-card {
  border: 1px solid var(--border-base);
  border-radius: var(--radius-10);
  background: var(--bg-elevated);
  padding: var(--space-12);
  display: flex;
  flex-direction: column;
  gap: var(--space-6);
}
.tm-card-head {
  display: flex;
  flex-wrap: wrap;
  align-items: center;
  gap: var(--space-6);
}
.tm-card-title {
  font-size: var(--font-size-13);
  font-weight: 600;
}
.tm-card-key,
.tm-row-key,
.tm-skill-key,
.tm-agent-key {
  font-family: var(--font-mono);
  font-size: var(--font-size-11);
  color: var(--text-tertiary);
}
.tm-card-desc {
  font-size: var(--font-size-12);
  line-height: 1.6;
  color: var(--text-secondary);
  margin: 0;
}
.tm-card-line {
  display: flex;
  flex-wrap: wrap;
  align-items: center;
  gap: var(--space-4);
}
.tm-card-line-wrap {
  align-items: flex-start;
}

/* ---- 列表 ---- */
.tm-list {
  display: flex;
  flex-direction: column;
}
.tm-row {
  display: flex;
  align-items: center;
  gap: var(--space-10);
  padding: var(--space-8) var(--space-10);
  border-bottom: 1px solid var(--border-base);
  font-size: var(--font-size-12);
}
.tm-row-title {
  min-width: 150px;
  font-weight: 500;
}
.tm-row-agents {
  color: var(--text-tertiary);
  font-size: var(--font-size-11);
}
.tm-row-refs {
  margin-left: auto;
  color: var(--text-secondary);
  font-size: var(--font-size-11);
}

/* ---- skill 配装 ---- */
.tm-skill-list {
  display: flex;
  flex-direction: column;
  gap: var(--space-10);
}
.tm-skill-row {
  border: 1px solid var(--border-base);
  border-radius: var(--radius-10);
  background: var(--bg-elevated);
  padding: var(--space-12);
  display: flex;
  flex-direction: column;
  gap: var(--space-8);
}
.tm-skill-head,
.tm-agent-head {
  display: flex;
  flex-wrap: wrap;
  align-items: center;
  gap: var(--space-8);
}
.tm-skill-title {
  font-size: var(--font-size-13);
  font-weight: 600;
}
.tm-skill-icon {
  margin-right: var(--space-4);
}
.tm-tool-select {
  width: 100%;
}
.tm-inline-warn {
  margin: 0;
}

/* ---- Agent 配装（只读）---- */
.tm-agent-list {
  display: grid;
  grid-template-columns: repeat(auto-fill, minmax(380px, 1fr));
  gap: var(--space-12);
}
.tm-agent-card {
  border: 1px solid var(--border-base);
  border-radius: var(--radius-10);
  background: var(--bg-elevated);
  padding: var(--space-12);
  display: flex;
  flex-direction: column;
  gap: var(--space-10);
}
.tm-agent-title {
  font-size: var(--font-size-13);
  font-weight: 600;
}

/* tooltip 里的多行说明需要保留换行 */
:deep(.ant-tooltip-inner) {
  white-space: pre-line;
}
</style>
