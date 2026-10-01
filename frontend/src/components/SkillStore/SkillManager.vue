<template>
  <div class="skill-manager">
    <!-- 头部 -->
    <div class="sm-header">
      <div class="sm-heading">
        <h2 class="sm-title">
          <AppstoreOutlined />
          <span>Skill 仓库</span>
        </h2>
        <p class="sm-sub">
          技能在这里<b>集中维护</b>、<b>按需勾选启用</b>（模型每轮只见「技能目录」，需要时才加载正文）。
          <br>
          ★ <b>有取舍、需人判 → 技能</b>
        </p>
      </div>
      <div class="sm-head-actions">
        <a-button
          :loading="store.loading"
          @click="refresh"
        >
          <template #icon>
            <ReloadOutlined />
          </template>
          刷新
        </a-button>
        <a-button
          type="primary"
          :disabled="!canWrite"
          @click="openCreate"
        >
          <template #icon>
            <PlusOutlined />
          </template>
          新建技能
        </a-button>
      </div>
    </div>

    <!-- 身份提示条 —— ★★ 第 269 轮：**只剩「没有身份」这一档**。
         老板原话：「skill仓库这个ui取消」，并附截图 = 「当前是演示账号」那条 info 提示条。
         · 退场的那条是第 182 轮的产物（当时诉求是「说明你现在是谁、改动会去哪儿」）。
           如今演示身份与真实账号在**能力上完全一致**（`canWrite = !!token`，不再区分两者），
           这条提示条便只剩一句同义反复 —— 于是按老板要求撤掉。
         · 判据也一并退役：`isDemoIdentity` computed 与 `isDemoToken` import 已删。
           留一个没人用的 computed 会撞 `frontend/tsconfig.app.json` 的 `noUnusedLocals`。
         · **保留**下面这条 warning：它守的是**真的写不了**（没有凭据 ⇒ 后端必 403），
           与「演示身份」不是同一件事。把它一起删掉，就变成「按钮禁用了但不解释为什么」。
         · `.sm-demo-tip` 这个类名沿用（它是 legacy 命名，但改它属于无收益的破坏性重命名）。 -->
    <a-alert
      v-if="!canWrite"
      type="warning"
      show-icon
      class="sm-demo-tip"
      message="当前没有可用身份"
      description="可以浏览技能仓库，但新建 / 修改 / 删除需要身份。请登录，或从演示模式进入。"
    />

    <a-alert
      v-if="store.error"
      type="error"
      show-icon
      closable
      class="sm-err"
      :message="store.error"
      @close="store.clearError()"
    />

    <a-tabs
      v-model:active-key="tab"
      class="sm-tabs"
    >
      <!-- ============ Tab 1：技能仓库（全局管理） ============ -->
      <!-- ★ 第 209 轮：本 tab 由「技能仓库」改名为「技能管理」——
           因为「工具仓库」已经升为**平级的独立入口**，
           两个页面各自定位：「技能管理」管技能本身，「工具仓库」管工具与绑定。
           ★★ 第 255 轮：再改名为「快捷卡片管理」（老板原话：「skill仓库中的
           技能管理改名为快捷卡片管理」）。理由是「技能」这个词在本页有两个所指 ——
           页面上维护的是**技能实体**（正文/版本/生效 Agent/配套工具），
           而用户在对话页真正看到的是它渲染出来的**快捷卡片**（`isShortcut`）。
           叫「技能管理」会让人以为改这里就等于改卡片外观，
           叫「快捷卡片管理」才和「这条技能要不要在对话框下面给一张卡」对得上。
           ⚠️ tab **key 仍是 `repo`**（不改 key：`check-skill-view-parity.cjs`
           等多处按 `key` 切片，改 key 属于无收益的破坏性重命名）。 -->
      <a-tab-pane
        key="repo"
        tab="快捷卡片管理"
      >
        <a-spin :spinning="store.loading">
          <a-empty
            v-if="!store.items.length"
            description="还没有技能。技能是「按需加载的能力说明」——新建一个试试。"
          />
          <!-- ★★ 第 196 轮：「筛选后为空」**不再有自己的空状态块** —— 直接空。
               老板原文：「当筛选为空时候，直接空就好了，你好像做了另外
               一个页面跳转（删除这个跳转，直接空，然后已经提供了重置筛选
               的功能了）」。

               旧形态的缺陷不只是多一个插画，而是**层级**：筛选栏
               本身也被关在 `v-else` 里 ⇒ 一旦筛空，连顶部「重置筛选」
               都一起消失，整页只剩居中空状态 —— 那才是“像跳到另
               一页”的来源；而空状态里那个按钮就成了**唯一**的逃生口
               （同一个 resetFilters 被迫有了两套入口）。
               ⇒ 修法两条必须一起做：① 筛选栏**提到判空之外**
                  （现在挂在 `!store.items.length` 的 v-else 上，与筛选结果无关）
                  ——「重置筛选」任何状态下都在；
                  ② 列表区自己按筛选结果守卫 ⇒ 筛空时**直接空**。

               ★ `!store.items.length`（库里真没技能）那个空状态**保留**：
                 那是另一种语义 —— 此时没有筛选栏可言，用户要的是“去新建”。
               ★ 判据落在 `check-skill-view-parity.cjs` 的 D 段（形态，非文案）。 -->
          <template v-else>
            <!-- 视图切换：平铺（卡片）/ 列表（行式）
                 ★ 第 193 轮：按钮组形态复用 ProductLibrary.vue 的 `.view-switch`
                   （同项目同类页面的既有范式，不另造控件）。 -->
            <!-- ============ 顶部筛选区（第 194 轮建 / 第 195 轮压成一行）============
                 老板原文：「把筛选器放在顶部，让用户快速收敛范围」，
                 位置就在「刷新 / 新建技能」下面。

                 ★★ 第 195 轮：由**两行压成一行**，形态照 `CandidateLibrary.vue`
                   —— 同项目「资料库」下的既有范式（一行工具栏，动作在行内）。
                   同批**删掉「按标签筛选」**：自定义标签只有筛选口、没有
                   任何录入入口 ⇒ 永远筛不出东西（老板原话「删除标签相关内容」）。

                 ★★ 筛选状态**全部住在 store**（照抄 `candidateLibrary.ts`
                   的既有范式），本组件只做 v-model 绑定。
                   状态放组件本地 `ref` 的后果是：切换 tab 回来全被清空，
                   而用户会以为"筛选不管用"。

                 ★ 三个下拉的默认值都是 `undefined`（= 不过滤），
                   与 `candidateLibrary.ts` 的注释口径一致：
                   默认状态下 `filteredItems === items`。

                 ★ 「已筛选 N 项」不再**另起一行**当 badge（那正是老板要压掉
                   的第二行），改为挂在「重置筛选」按钮上 —— 一个控件同时
                   承担「告知」与「一键清除」。 -->
            <div class="sm-filters">
              <a-input-search
                v-model:value="store.searchQuery"
                placeholder="搜索技能标识 / 展示名 / 描述"
                style="width: 240px"
                allow-clear
              >
                <template #prefix>
                  <SearchOutlined />
                </template>
              </a-input-search>

              <a-select
                v-model:value="store.filterAgent"
                style="width: 150px"
                placeholder="全部 Agent"
                allow-clear
              >
                <a-select-option
                  v-for="a in store.agents"
                  :key="a.name"
                  :value="a.name"
                >
                  {{ a.title }}
                </a-select-option>
              </a-select>

              <a-select
                v-model:value="store.filterKind"
                style="width: 132px"
                placeholder="全部类型"
                allow-clear
              >
                <a-select-option value="prompt">
                  纯提示词技能
                </a-select-option>
                <a-select-option value="tool">
                  绑定工具技能
                </a-select-option>
              </a-select>

              <a-select
                v-model:value="store.filterStatus"
                style="width: 118px"
                placeholder="全部状态"
                allow-clear
              >
                <a-select-option value="enabled">
                  已启用
                </a-select-option>
                <a-select-option value="disabled">
                  已停用
                </a-select-option>
                <a-select-option value="demo">
                  演示
                </a-select-option>
              </a-select>

              <a-select
                v-model:value="store.sortBy"
                style="width: 146px"
              >
                <a-select-option value="updated_at">
                  最近更新
                </a-select-option>
                <a-select-option value="name">
                  名称 A→Z
                </a-select-option>
                <a-select-option value="version">
                  版本号（高→低）
                </a-select-option>
              </a-select>
              <a-checkbox v-model:checked="store.onlyFavorites">
                仅看收藏 ⭐
              </a-checkbox>
              <a-checkbox v-model:checked="store.groupByAgent">
                按 Agent 分组
              </a-checkbox>
              <a-button
                size="small"
                :disabled="!store.activeFilterCount"
                @click="store.resetFilters()"
              >
                <ReloadOutlined v-if="store.activeFilterCount" />
                重置筛选<span v-if="store.activeFilterCount"> ({{ store.activeFilterCount }})</span>
              </a-button>
            </div>

            <div class="sm-toolbar">
              <a-radio-group
                v-model:value="repoView"
                size="small"
                button-style="solid"
                class="sm-view-switch"
              >
                <a-radio-button value="grid">
                  <AppstoreOutlined /> 平铺
                </a-radio-button>
                <a-radio-button value="list">
                  <UnorderedListOutlined /> 列表
                </a-radio-button>
              </a-radio-group>
              <span class="sm-count">
                显示 {{ store.filteredItems.length }} / {{ store.items.length }} 个技能
              </span>
            </div>

            <!-- ============ 分组外壳（第 194 轮）============
                 ★★ 「不分组」在 store 里就是「只有一个 title 为空的分组」
                   (`groupedItems`) ⇒ 下面两个渲染分支**只写一遍**。
                   若给"不分组"另写一份渲染，就会造出第三、四套渲染 ——
                   而它们必然分叉：`check-skill-view-parity.cjs` 钉的正是
                   "这两个分支字段对等"，多出来的那几套它**管不到**。

                 ★ 一条技能可挂多个 Agent ⇒ 分组后它会在多个分组各出现一次。
                   这是**正确的多归属语义**（用户的预期是"我给选品分析师找
                   技能，就在这一组里找到它"），不是重复 bug。

                 ★ 折叠状态住在 store（`collapsedGroups`）：放组件本地 ref 的话，
                   切 tab 回来就全展开了，用户得重新点一遍。默认**全部展开** ——
                   全折叠状态下第一眼只有一排标题，用户还得逐组点开才知道有什么。 -->
            <!-- ★ 第 196 轮：列表容器**自己**按筛选结果守卫 —— 筛成空时这里
                 什么都不渲染（老板要的「直接空」）。
                 ★★ 守卫必须挂在**这一层**：旧形态把整条筛选栏一起关进
                 v-else，导致筛空时连顶部「重置筛选」也消失 —— 那正是
                 “像跳转到另一个页面”的来源。
                 ★ 上方工具栏（平铺/列表 + 「显示 0 / N 个技能」）与筛选栏都**常驻**，
                   所以筛空时用户看到的是「显示 0 / 22」+ 可点的重置按钮，
                   而不是一页空白。 -->
            <div
              v-if="store.filteredItems.length"
              class="sm-groups"
            >
              <template
                v-for="g in store.groupedItems"
                :key="g.key"
              >
                <div class="sm-group">
                  <div
                    v-if="g.title"
                    class="sm-group-head"
                    @click="store.toggleGroup(g.key)"
                  >
                    <span class="sm-group-caret">{{ store.collapsedGroups[g.key] ? '▸' : '▾' }}</span>
                    <span class="sm-group-title">{{ g.title }}</span>
                    <span class="sm-group-count">（{{ g.items.length }} 个技能）</span>
                  </div>

                  <template v-if="!g.title || !store.collapsedGroups[g.key]">
                    <!-- ---------- 平铺（卡片网格） ---------- -->
                    <div
                      v-if="repoView === 'grid'"
                      class="sm-grid"
                    >
                      <div
                        v-for="skill in g.items"
                        :key="skill.id"
                        class="sm-card"
                      >
                        <!-- ① 星标 + 展示名（大号） -->
                        <div class="sm-card-top">
                          <button
                            class="sm-star"
                            :class="{ 'is-on': skill.favorited }"
                            :disabled="!canWrite"
                            :title="skill.favorited ? '取消收藏' : '收藏这个技能（顶部可「仅看收藏」）'"
                            @click.stop="store.toggleFavorite(skill, !skill.favorited)"
                          >
                            {{ skill.favorited ? '★' : '☆' }}
                          </button>
                          <span class="sm-card-title">{{ skill.title || skill.name }}</span>
                        </div>

                        <!-- ② 技能标识（小字，模型调 load_skill 用的名字） -->
                        <div
                          class="sm-card-name"
                          :title="`模型调用 load_skill 时使用的名字：${skill.name}`"
                        >
                          {{ skill.name }}
                        </div>

                        <!-- ③ 一行标签：版本 ｜ 状态 ｜ 类型 ｜ 启用于 ｜ 配套工具
                             ★ 「启用于」「配套工具」两个信息块由门禁 A5 钉住 ——
                               压成一行时**不删这两个词**（用户靠它们判断
                               "这个技能对谁生效、带哪些工具"）。 -->
                        <div class="sm-chips">
                          <span class="sm-chip sm-chip-ver">v{{ skill.version }}</span>
                          <span
                            v-if="skill.isDemo"
                            class="sm-chip sm-chip-demo"
                          >演示</span>
                          <span
                            v-if="!skill.enabled"
                            class="sm-chip sm-chip-off"
                          >已停用</span>
                          <span
                            v-else-if="skill.visibility === 'private'"
                            class="sm-chip sm-chip-priv"
                          >私有</span>
                          <span class="sm-chip">{{ skill.tools.length ? '工具技能' : '纯提示词' }}</span>
                          <span class="sm-chip sm-chip-agents">启用于：{{ skill.enabledAgents.map((a: string) => store.titleOfAgent(a)).join('、') || '未分配' }}</span>
                          <span
                            v-if="skill.isShortcut === false"
                            class="sm-chip sm-chip-no-card"
                            title="对话页不给它快捷卡片（它仍照常生效：Agent 会在需要时自行加载完整步骤，也能被别的技能正文引用）"
                          >不设卡片</span>
                          <span class="sm-chip sm-chip-tools">配套工具：{{ skill.tools.map((t: string) => store.titleOfTool(t) + (store.isApprovalTool(t) ? '·需审批' : '')).join('、') || '无' }}</span>
                        </div>

                        <!-- ④ 描述：默认只露 2 行，悬停看全文 —— 卡片拥挤的最大元凶就是这个 -->
                        <p
                          class="sm-card-desc"
                          :title="skill.description || undefined"
                        >
                          {{ skill.description || '（未填描述 —— 模型只能靠它判断要不要加载，建议补上）' }}
                        </p>

                        <div class="sm-card-actions">
                          <a-button
                            size="small"
                            :disabled="!canWrite"
                            @click="openEdit(skill)"
                          >
                            编辑
                          </a-button>
                          <a-button
                            size="small"
                            @click="openRevisions(skill)"
                          >
                            版本
                          </a-button>
                          <a-popconfirm
                            title="删除该技能？它的版本历史会一并删除，不可恢复。"
                            ok-text="删除"
                            cancel-text="取消"
                            :disabled="!canWrite"
                            @confirm="removeSkill(skill)"
                          >
                            <a-button
                              size="small"
                              danger
                              :disabled="!canWrite"
                            >
                              删除
                            </a-button>
                          </a-popconfirm>
                        </div>
                      </div>
                    </div>

                    <!-- ---------- 列表（一行一项，密度优先） ---------- -->
                    <div
                      v-else
                      class="sm-list"
                    >
                      <div
                        v-for="skill in g.items"
                        :key="skill.id"
                        class="sm-row"
                      >
                        <button
                          class="sm-star"
                          :class="{ 'is-on': skill.favorited }"
                          :disabled="!canWrite"
                          :title="skill.favorited ? '取消收藏' : '收藏这个技能（顶部可「仅看收藏」）'"
                          @click.stop="store.toggleFavorite(skill, !skill.favorited)"
                        >
                          {{ skill.favorited ? '★' : '☆' }}
                        </button>

                        <div class="sm-row-main">
                          <div class="sm-row-top">
                            <span class="sm-row-title">{{ skill.title || skill.name }}</span>
                            <span
                              class="sm-row-slug"
                              :title="`模型调用 load_skill 时使用的名字：${skill.name}`"
                            >{{ skill.name }}</span>
                          </div>
                          <p
                            class="sm-row-desc"
                            :title="skill.description || undefined"
                          >
                            {{ skill.description || '（未填描述 —— 模型只能靠它判断要不要加载，建议补上）' }}
                          </p>
                        </div>

                        <div class="sm-row-chips">
                          <span class="sm-chip sm-chip-ver">v{{ skill.version }}</span>
                          <span
                            v-if="skill.isDemo"
                            class="sm-chip sm-chip-demo"
                          >演示</span>
                          <span
                            v-if="!skill.enabled"
                            class="sm-chip sm-chip-off"
                          >已停用</span>
                          <span
                            v-else-if="skill.visibility === 'private'"
                            class="sm-chip sm-chip-priv"
                          >私有</span>
                          <span class="sm-chip">{{ skill.tools.length ? '工具技能' : '纯提示词' }}</span>
                          <span class="sm-chip sm-chip-agents">启用于：{{ skill.enabledAgents.map((a: string) => store.titleOfAgent(a)).join('、') || '未分配' }}</span>
                          <span
                            v-if="skill.isShortcut === false"
                            class="sm-chip sm-chip-no-card"
                            title="对话页不给它快捷卡片（它仍照常生效：Agent 会在需要时自行加载完整步骤，也能被别的技能正文引用）"
                          >不设卡片</span>
                          <span class="sm-chip sm-chip-tools">配套工具：{{ skill.tools.map((t: string) => store.titleOfTool(t) + (store.isApprovalTool(t) ? '·需审批' : '')).join('、') || '无' }}</span>
                        </div>

                        <div class="sm-row-actions">
                          <a-button
                            size="small"
                            :disabled="!canWrite"
                            @click="openEdit(skill)"
                          >
                            编辑
                          </a-button>
                          <a-button
                            size="small"
                            @click="openRevisions(skill)"
                          >
                            版本
                          </a-button>
                          <a-popconfirm
                            title="删除该技能？它的版本历史会一并删除，不可恢复。"
                            ok-text="删除"
                            cancel-text="取消"
                            :disabled="!canWrite"
                            @confirm="removeSkill(skill)"
                          >
                            <a-button
                              size="small"
                              danger
                              :disabled="!canWrite"
                            >
                              删除
                            </a-button>
                          </a-popconfirm>
                        </div>
                      </div>
                    </div>
                  </template>
                </div>
              </template>
            </div>
          </template>
        </a-spin>
      </a-tab-pane>
      <!-- ============ Tab 2：Agent 装配（「Agent 内勾选启用」） ============ -->
      <a-tab-pane
        key="wiring"
        tab="Agent 装配"
      >
        <p class="sm-tip">
          勾选即生效：这里改的是「该技能对哪些 Agent 生效」。
          未启用的技能对那个 Agent <b>不可见也不可加载</b>（模型连名字都看不到）。
        </p>
        <a-spin :spinning="store.loading">
          <a-empty
            v-if="!store.agents.length"
            description="Agent 目录加载失败或为空"
          />
          <div
            v-else
            class="sm-agents"
          >
            <div
              v-for="agent in store.agents"
              :key="agent.name"
              class="sm-agent-card"
            >
              <div class="sm-agent-head">
                <span class="sm-agent-title">{{ agent.title }}</span>
                <span class="sm-agent-key">{{ agent.name }}</span>
                <a-tag
                  class="sm-tag"
                  color="green"
                >
                  已启用 {{ store.skillsOfAgent(agent.name).length }} 个技能
                </a-tag>
              </div>
              <p class="sm-agent-desc">
                {{ agent.description }}
              </p>

              <a-empty
                v-if="!store.items.length"
                :image="simpleImage"
                description="还没有技能可分配"
              />
              <div
                v-else
                class="sm-agent-skills"
              >
                <a-checkbox
                  v-for="skill in store.items"
                  :key="skill.id"
                  :checked="skill.enabledAgents.includes(agent.name)"
                  :disabled="!canWrite || !skill.enabled"
                  @change="(e: any) => toggleForAgent(skill, agent.name, e.target.checked)"
                >
                  <span class="sm-ck-label">{{ skill.title || skill.name }}</span>
                  <span
                    v-if="!skill.enabled"
                    class="sm-muted"
                  >（该技能已停用）</span>
                </a-checkbox>
              </div>
            </div>
          </div>
        </a-spin>
      </a-tab-pane>
    </a-tabs>

    <!-- ============ 编辑抽屉 ============ -->
    <a-drawer
      v-model:open="editOpen"
      :title="editing ? `编辑技能 · ${editing.title || editing.name}` : '新建技能'"
      placement="right"
      :width="WINDOW_W.xl"
      :mask-closable="false"
    >
      <a-form layout="vertical">
        <a-form-item
          label="技能标识（name）"
          required
        >
          <a-input
            v-model:value="form.name"
            placeholder="kebab-case，如 price-drop-triage"
            :disabled="!!editing"
          />
          <div class="sm-help">
            模型加载技能时用它作为唯一名字，<b>全局唯一、创建后不可改</b>。
          </div>
        </a-form-item>

        <a-form-item label="展示名（title）">
          <a-input
            v-model:value="form.title"
            placeholder="中文名，如「竞品降价研判」"
          />
        </a-form-item>

        <a-form-item
          label="描述（description）"
          required
        >
          <a-textarea
            v-model:value="form.description"
            :rows="3"
            placeholder="这个技能解决什么场景的问题、什么时候该用它。"
          />
          <div class="sm-help">
            <b>这一段是渐进披露的唯一依据</b>：模型每轮只看到名字与描述，
            由它决定要不要加载正文。写成「这是一个技能」等于没写。
          </div>
        </a-form-item>

        <a-form-item>
          <!-- 提示词增强：正文就是模型照着执行的**规格**，补齐「适用条件/步骤/输出格式/红线」最有用。
               ★ description 不挂这个按钮 —— 那段是**检索信号**（渐进披露里决定要不要加载正文），
                 而增强器的三个维度是「任务目标 / 约束条件 / 输出形式」；把它写长、写成任务规格，
                 反而降低它作为「要不要加载」判据的区分度 ⇒ 不适配，宁可没有。 -->
          <template #label>
            <span style="display: inline-flex; align-items: center; gap: var(--space-6)">
              技能正文（content）
              <PromptEnhanceButton
                v-model="form.content"
                context="skill-authoring"
                size="sm"
              />
            </span>
          </template>
          <a-textarea
            v-model:value="form.content"
            :rows="14"
            placeholder="模型加载后看到的内容：适用条件、步骤、输出格式、红线。"
          />
          <div class="sm-help">
            正文<b>不常驻</b>上下文，只在模型调用 <code>load_skill</code> 时取回。
            正文变化会自动落一条版本快照并递增版本号。
          </div>
        </a-form-item>

        <a-row :gutter="12">
          <a-col :span="12">
            <a-form-item label="版本号">
              <a-input
                v-model:value="form.version"
                placeholder="留空则自动 +1（改正文时）"
              />
            </a-form-item>
          </a-col>
          <a-col :span="12">
            <a-form-item label="可见范围（权限）">
              <a-radio-group v-model:value="form.visibility">
                <a-radio value="account">
                  账号内共享
                </a-radio>
                <a-radio value="private">
                  仅创建者
                </a-radio>
              </a-radio-group>
            </a-form-item>
          </a-col>
        </a-row>

        <!-- ★★ 第 185 轮：自由文本输入 ⇒ **按 Agent 分组的选择器**
             （老板原话：「那用户怎么知道有哪些工具呢？目前是让用户自己写工具名」）

             旧形态是 `mode="tags"`：能填**任意字符串**、后端**不校验存在性**，
             而它的 placeholder 举例 `export_report` 全仓根本不存在 ——
             占位符在教用户填一个错的。改动后：
               · 候选集来自后端 `/tools`（工具名的唯一真源）；
               · 按**已勾选的 Agent** 收窄（工具是按 Agent 装配的，
                 绑了别的 Agent 的工具在运行期调不到）；
               · 已绑但不在候选里的项**保留**（见 `toolOptions` 的注释）。 -->
        <a-form-item label="配套工具（工具技能）">
          <a-select
            v-model:value="form.tools"
            mode="multiple"
            :options="toolOptions"
            :placeholder="toolPlaceholder"
            option-filter-prop="label"
            allow-clear
          />
          <div class="sm-help">
            加载该技能时，这份清单会随正文一起交给模型，它会
            <b>只用这些</b>工具完成技能里的步骤 ——
            这就是「工具技能」与「纯提示词技能」的唯一区别。留空 = 纯提示词技能。
            <br>
            工具按 <b>Agent</b> 分组：下面「启用给哪些 Agent」勾了谁，
            这里就只列谁名下的工具。标
            <a-tag
              color="orange"
              class="sm-inline-tag"
            >
              橙
            </a-tag>
            的每次调用都会弹人工审批。
          </div>
        </a-form-item>

        <a-form-item label="状态">
          <a-switch
            v-model:checked="form.enabled"
            checked-children="启用"
            un-checked-children="停用"
          />
          <span class="sm-help sm-help-inline">
            停用后不进任何 Agent 的技能目录（配置与历史保留）。
          </span>
        </a-form-item>

        <!-- ★★ 第 248 轮：与「状态」分开的第二把闸（老板拍板方案 B）。
             ★ 为什么必须是**独立开关**而不是复用「状态」：`enabled` 是三通道
               （目录注入 / load_skill / 卡片区）共用的全局开关，关掉它会让
               **别条技能**正文里对本技能的引用断链（周报逐字写着「表达结构
               沿用「复盘结论写法」」）⇒ 没有"零改动的正确解法"，只能拆字段。 -->
        <a-form-item label="快捷卡片">
          <a-switch
            v-model:checked="form.isShortcut"
            checked-children="显示"
            un-checked-children="不显示"
          />
          <span class="sm-help sm-help-inline">
            关掉后它<b>仍然生效</b>：照常进技能目录、可被 <code>load_skill</code> 加载、
            也能被别的技能正文引用；只是对话页不再给它一张可点的卡。
          </span>
          <div class="sm-help">
            什么时候该关 —— 两种情形（★ 第 295 轮补第 ② 种）：
            <br>
            ① <b>它是「怎么写」的规矩，不是一份东西</b>。典型是「复盘结论写法」：
            周报的正文逐字声明「表达结构沿用「复盘结论写法」」，
            所以它<b>不能停用</b>；但点它拿不到成品（"写什么"得先由别的技能产出），
            所以它不该占一格卡片。
            <br>
            ② <b>它已经有更合适的入口，卡片只是把同一件事再做一遍</b>。
            典型是「差评应对」：差评的取证 / 判定 / 补偿 / 处置在【差评台账】
            工作台里已是完整流程，卡片点下去只会重算一遍面板已有的东西。
            ★ 它同样<b>不能停用</b> —— 对话里的多轮追问（让它解释判定理由、
            跟买家拉锯）只有它能给，面板没有多轮。
            <br>
            对照：其余 20 多条技能点下去都会给出一份东西（标题 / 清单 / 判定 /
            话术 / 简报），且没有第二个入口，那些都该保留卡片。
          </div>
        </a-form-item>

        <a-form-item label="启用给哪些 Agent">
          <a-checkbox-group
            v-model:value="form.enabledAgents"
            class="sm-ck-group"
          >
            <a-checkbox
              v-for="a in store.agents"
              :key="a.name"
              :value="a.name"
            >
              {{ a.title }}
            </a-checkbox>
          </a-checkbox-group>
          <div class="sm-help">
            两者是与关系：技能需「已启用」且「勾选了该 Agent」才会注入。
          </div>
        </a-form-item>
      </a-form>
      <div class="sm-drawer-actions">
        <a-button @click="editOpen = false">
          取消
        </a-button>
        <a-button
          type="primary"
          :loading="store.saving"
          @click="submitEdit"
        >
          保存
        </a-button>
      </div>
    </a-drawer>

    <!-- ============ 版本抽屉 ============ -->
    <a-drawer
      v-model:open="revisionOpen"
      :title="`版本历史 · ${revisionTarget?.title || revisionTarget?.name || ''}`"
      placement="right"
      :width="WINDOW_W.lg"
    >
      <a-empty
        v-if="!store.revisions.length"
        description="还没有版本记录"
      />
      <a-timeline v-else>
        <a-timeline-item
          v-for="rev in store.revisions"
          :key="rev.id"
          :color="rev.action === 'create' ? 'green' : rev.action === 'rollback' ? 'orange' : 'blue'"
        >
          <div class="sm-rev-head">
            <b>v{{ rev.version }}</b>
            <a-tag class="sm-tag">
              {{ actionLabel(rev.action) }}
            </a-tag>
            <span class="sm-muted">{{ fmtTime(rev.changedAt) }}</span>
          </div>
          <div
            v-if="rev.note"
            class="sm-rev-note"
          >
            {{ rev.note }}
          </div>
          <div class="sm-rev-body">
            {{ preview(rev.content) }}
          </div>
          <a-popconfirm
            title="回滚到这一版？当前内容会被替换（历史不会丢，本次回滚也会记一条）。"
            ok-text="回滚"
            cancel-text="取消"
            :disabled="!canWrite"
            @confirm="doRollback(rev)"
          >
            <a-button
              size="small"
              :disabled="!canWrite || rev.id === store.revisions[0]?.id"
            >
              回滚到此版本
            </a-button>
          </a-popconfirm>
        </a-timeline-item>
      </a-timeline>
    </a-drawer>
  </div>
</template>

<script setup lang="ts">
/**
 * Skill 仓库 / 技能管理页（第 181 轮 · 批 B）
 *
 * ============================================================================
 * ★ 界面形态：范式 1（Agent 平台类 —— 技能仓库全局管理，Agent 内勾选启用）
 * ============================================================================
 * 两个 Tab 正好对应该范式的两半：
 *   「技能仓库」 全局维护（新增 / 编辑 / 版本 / 权限 / 描述 / 工具定义）
 *   「Agent 装配」 按 Agent 勾选启用
 *
 * 为什么不做成「每个 Agent 各自一个技能列表」：
 * 同一份技能常常要被多个 Agent 复用（例：降价研判同时给竞品监控员、
 * 运营复盘师、广告分析师）。按 Agent 各存一份 ⇒ 同一份内容出现 N 份拷贝，
 * 改一处不会同步到其余 N-1 处，而且**不会报错**。
 * 仓库 + 勾选 = 一份内容、N 个引用。
 *
 * ============================================================================
 * ★ 第 182 轮：演示身份**功能齐全**（读得到、也写得了）
 * ============================================================================
 * ★★★ 这一段是需求变更的记录，别照着第 181 轮的形态改回去。
 *
 *   第 181 轮：演示身份在前端 = 只读。理由是"后端写口对无身份硬拒 403，
 *             前端提前禁用按钮，让用户不用去撞 403"。
 *   第 182 轮：老板明确要求「演示模式也当作一个真实的账号 …… 也有全套功能，
 *             目前无法编辑 skill」⇒ 后端把演示哨兵解析成了**演示账号主人**
 *             （真 User 行），写口因此对演示身份放行；前端也跟着放开。
 *
 * ★ 现在前端只判一件事：**有没有可用的身份凭据**（`canWrite`）。
 *   · 有（真实登录 或 演示身份）⇒ 写操作可用 —— 两者在这一点上**没有区别**；
 *   · 没有（`userStore.token` 为空）⇒ 禁用，因为后端一定会 403。
 *   ⇒ 演示身份与真实账号的**唯一**差异只剩提示条文案，不再是能力差异。
 *     这正好是老板那句话的实现：「只是无需账号密码」——少的只是登录动作。
 *
 * ★ 仍然保留「把后端错误文案显示出来」（`store.error`）：
 *   按钮禁用只是一个**提示性**优化，真正的门禁在后端。只靠前端禁用的话，
 *   任何一处遗漏都会表现为**静默失效**（记忆里那条「失败路径必须回写界面状态」）。
 */
import { WINDOW_W } from '@/config/layout'
import { computed, onMounted, reactive, ref } from 'vue'
import {
  AppstoreOutlined,
  PlusOutlined,
  ReloadOutlined,
  SearchOutlined,
  UnorderedListOutlined,
} from '@ant-design/icons-vue'
import { Empty } from 'ant-design-vue'
import {
  useSkillStore,
  type Skill,
  type SkillRevision,
} from '@/stores/skills'
import { useUserStore } from '@/stores/user'
import PromptEnhanceButton from '@/components/common/PromptEnhanceButton.vue'

const store = useSkillStore()
const userStore = useUserStore()

// 小尺寸空状态用的简化图（与 antd 的 a-empty 尺寸配合）
const simpleImage = Empty.PRESENTED_IMAGE_SIMPLE

/**
 * 两个 tab：`repo`＝快捷卡片管理（第 255 轮改名；key 未变），`wiring`＝Agent 装配。
 *
 * ★★ 顺序是**契约**，不是排版偏好：
 *   `scripts/check-skill-view-parity.cjs` 的 C/D 段用
 *   「`key="repo"` → `key="wiring"`」这段切片判「快捷卡片管理」tab 的形态
 *   （筛选栏常驻 / 双视图对等 / 筛空即空）。
 *   ⇒ 往这**两个之间**插任何东西，那道门禁都会在**与它无关的代码**上
 *     报红或报绿（假红 / 更糟的假绿）。
 *
 * ★ 第 209 轮：原先排在这之后的第三个 tab「工具仓库」已**搬走** ——
 *   升成与技能仓库**平级**的独立页面
 *   （`components/ToolStore/ToolManager.vue`：工具管理 / skill 配装 / Agent 配装）。
 *   本页回到两个 tab，切片契约不变。
 *
 * ★ 面板顺序在这里与模板里是**两处**，改一处不会报错
 *   （`a-tabs` 按 template 顺序渲染，这个 ref 只存当前值）⇒ 两处必须一起改。
 */
const tab = ref<'repo' | 'wiring'>('repo')

/**
 * 技能仓库的视图形态：平铺（卡片网格）/ 列表（一行一项）。
 *
 * ★ 第 193 轮：老板要求「技能仓库改为平铺/列表 tab 按钮」。
 *   两个视图是**同一份数据的两套排版** ⇒ 字段必须对等，由
 *   `scripts/check-skill-view-parity.cjs` 钉住
 *   （漏一处 = 那个字段在列表里**静默消失**，不报错）。
 * ★ 默认 'grid'：老板现在看到的形态就是平铺，加切换控件不该顺手改掉默认。
 * ★ 不持久化：与 `ProductLibrary.vue` 的 `viewMode` 一致（裸 `ref`，不进 store /
 *   localStorage），避免为一次视图切换新增存储键。
 */
const repoView = ref<'grid' | 'list'>('grid')

/**
 * 写操作是否可用 —— 只判「有没有身份凭据」，**不再区分演示与真实**。
 *
 * ★ 第 182 轮：判据由 `!token || isDemoToken(token)`（只读档）改为 `!!token`。
 *   原因见上方脚本头 docstring：演示身份在后端已是一个真用户，
 *   前端再单独禁它一次，就变成"后端放行、前端不放"的第二份实现 ——
 *   而那份实现**永远测不到**（本仓铁律：同一判定两份实现必有其一失效）。
 *
 * ★ 用 `computed` 而不是 onMounted 里赋一次值：登录态在页面存活期间会变
 *   （登录 / 切到真实账号 / 退出登录），一次性快照会把这之后的状态全部判错，
 *   而症状是「按钮该禁的没禁」—— 恰好是 fail-open 的方向。
 *
 * ★ 兜底方向仍是 **fail-closed**：拿不到 token 就禁用。
 *   理由与「拿不到权威清单 ≠ 清单为空」同源 —— 两个方向的代价不对称：
 *   误禁一个按钮只是多一次点击，误放行一次写操作会真的改到数据。
 */
const canWrite = computed(() => !!userStore.token)

/* ★ 第 269 轮：`isDemoIdentity` computed 随「当前是演示账号」提示条一起退役
   （老板要求撤掉那条 UI）。它原先**只**服务那条提示条的 `v-if`，
   删掉提示条后没有任何消费方 —— 留着就是 `noUnusedLocals` 下的一条死代码。
   依赖它的那条 `@/config/demoMode` 导入也一并删。
   ⚠️ 若将来又要按身份分支渲染，**别自己在本组件里写「token 像不像 demo」**：
   复用 `@/config/demoMode` 的 `isDemoToken()`（与 request.ts / AccountMenu 同一处真源）。 */

// ===== 编辑抽屉 =====
const editOpen = ref(false)
const editing = ref<Skill | null>(null)

const form = reactive({
  name: '',
  title: '',
  description: '',
  content: '',
  version: '',
  visibility: 'account' as 'account' | 'private',
  tools: [] as string[],
  enabled: true,
  /**
   * ★ 是否在对话页显示为**快捷卡片**（第 248 轮）。
   *
   *   与 `enabled`（全局停用）是**两件事**，别混：
   *     `enabled=false` ⇒ 不进任何 Agent 的技能目录 / 不可 load ⇒ 会让别条技能
   *                       正文里对它的引用**断链**；
   *     本项关闭      ⇒ 其它一切照旧，只是对话页不再给它一张可点的卡。
   *   默认 true 与后端列默认同向（新建的技能默认是有卡片的）。
   */
  isShortcut: true,
  enabledAgents: [] as string[],
})

/**
 * 工具下拉的候选项 —— **按已勾选的 Agent 收窄**（第 185 轮）。
 *
 * ★★ 第 255 轮：收窄的实现**搬进了 store**（`store.toolOptionsFor`）。
 *    原因是同一个字段 `skills.tools` 有**两个编辑入口** —— 本抽屉与工具仓库的
 *    「skill 配装」tab。原来两边各写一份，工具仓库那份**根本没做收窄**
 *    （平铺全部 Agent 的工具）⇒ 随时能造出「技能引导了该 Agent 手上没有的工具」。
 *    ⇒ 收窄口径只允许存在一处，两个入口都消费它，门禁
 *      `check-skill-tool-options-parity.cjs` 钉住唯一性。
 *
 * ★ 判据与取舍（收窄理由 / 为什么保留孤儿项）已随实现写进 store 注释，
 *   这里不再复述第二份说明（说明本身也会漂移）。
 */
const toolOptions = computed(() => store.toolOptionsFor(form.enabledAgents, form.tools))

const toolPlaceholder = computed(() =>
  form.enabledAgents.length
    ? '从下面 Agent 名下的工具里选（可不选 = 纯提示词技能）'
    : '先勾选下方「启用给哪些 Agent」，这里才会列出可选工具'
)

function resetForm() {
  form.name = ''
  form.title = ''
  form.description = ''
  form.content = ''
  form.version = ''
  form.visibility = 'account'
  form.tools = []
  form.enabled = true
  form.isShortcut = true
  form.enabledAgents = []
}

function openCreate() {
  editing.value = null
  resetForm()
  editOpen.value = true
}

async function openEdit(skill: Skill) {
  editing.value = skill
  // ★ 列表接口**不返回正文** ⇒ 编辑前必须拉一次详情。
  //   直接拿列表那条去保存会把正文写成空字符串（内容静默丢失）。
  const detail = await store.loadDetail(skill.id)
  const src = detail || skill
  form.name = src.name
  form.title = src.title
  form.description = src.description
  form.content = src.content || ''
  form.version = ''
  form.visibility = src.visibility
  form.tools = [...(src.tools || [])]
  form.enabled = src.enabled
  // ★ `!== false`：后端恒下发本字段，但缺字段（旧响应 / 缓存里的旧对象）
  //   一律按「显示卡片」处理 —— 反向取值会让用户在保存时静默关掉它。
  form.isShortcut = src.isShortcut !== false
  form.enabledAgents = [...(src.enabledAgents || [])]
  editOpen.value = true
}

async function submitEdit() {
  if (!form.name.trim()) {
    store.error = '技能标识（name）不能为空'
    return
  }
  const payload = {
    name: form.name.trim(),
    title: form.title.trim(),
    description: form.description.trim(),
    content: form.content,
    version: form.version.trim() || undefined,
    visibility: form.visibility,
    tools: form.tools,
    enabled: form.enabled,
    isShortcut: form.isShortcut,
    enabledAgents: form.enabledAgents,
  }
  const ok = editing.value
    ? await store.update(editing.value.id, payload)
    : await store.create(payload)
  if (ok) editOpen.value = false
}

// ===== 版本抽屉 =====
const revisionOpen = ref(false)
const revisionTarget = ref<Skill | null>(null)

async function openRevisions(skill: Skill) {
  revisionTarget.value = skill
  await store.loadRevisions(skill.id)
  revisionOpen.value = true
}

async function doRollback(rev: SkillRevision) {
  if (!revisionTarget.value) return
  const ok = await store.rollback(revisionTarget.value.id, rev.id)
  if (ok) await store.loadRevisions(revisionTarget.value.id)
}

// ===== 装配 =====
/**
 * 勾选/取消「某 Agent 启用某技能」。
 *
 * ★ 发的是**该技能启用 Agent 的完整集合**（全量覆盖语义）——
 *   服务端接口就是这样设计的：增量接口会让并发两次勾选产生无法解释的合并结果。
 * ★ 传 `agent.name`（后端 agent_name）而不是 `agent.id`（前端 id）：
 *   注入发生在后端，用 id 的症状是「勾了但永不注入」且不报错。
 */
async function toggleForAgent(skill: Skill, agentName: string, checked: boolean) {
  const next = checked
    ? Array.from(new Set([...(skill.enabledAgents || []), agentName]))
    : (skill.enabledAgents || []).filter((n) => n !== agentName)
  await store.saveAgents(skill.id, next)
}

async function removeSkill(skill: Skill) {
  await store.remove(skill.id)
}

// ===== 工具函数 =====
function actionLabel(action: string): string {
  return action === 'create' ? '创建' : action === 'rollback' ? '回滚' : '编辑'
}

function fmtTime(iso: string | null): string {
  if (!iso) return ''
  const d = new Date(iso)
  if (Number.isNaN(d.getTime())) return iso
  const pad = (n: number) => String(n).padStart(2, '0')
  return `${d.getFullYear()}-${pad(d.getMonth() + 1)}-${pad(d.getDate())} ${pad(d.getHours())}:${pad(d.getMinutes())}`
}

function preview(text: string): string {
  const t = (text || '').replace(/\s+/g, ' ').trim()
  return t.length > 110 ? t.slice(0, 110) + '…' : t || '（空正文）'
}

async function refresh() {
  await store.loadAll()
}

onMounted(async () => {
  await store.loadAll()
})
</script>

<style scoped>
.skill-manager {
  height: 100%;
  overflow: auto;
  padding: var(--space-20) var(--space-24) var(--space-40);
  background: var(--bg-base);
}

/* ---- 头部 ---- */
.sm-header {
  display: flex;
  align-items: flex-start;
  justify-content: space-between;
  gap: var(--space-16);
  margin-bottom: var(--space-12);
}
.sm-heading { min-width: 0; }
.sm-title {
  display: flex;
  align-items: center;
  gap: var(--space-8);
  margin: 0 0 var(--space-4);
  font-size: var(--font-size-18);
  font-weight: 600;
  color: var(--text-primary);
}
.sm-sub {
  margin: 0;
  font-size: var(--font-size-12);
  line-height: 1.6;
  color: var(--text-tertiary);
  max-width: 720px;
}
.sm-head-actions {
  display: flex;
  gap: var(--space-8);
  flex-shrink: 0;
}
.sm-demo-tip { margin-bottom: var(--space-12); }
.sm-err { margin-bottom: var(--space-12); }

/* ---- 视图切换工具条（形态复用 ProductLibrary.vue 的 .view-switch） ---- */
.sm-toolbar {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: var(--space-12);
  margin-bottom: var(--space-12);
}
.sm-view-switch { flex-shrink: 0; }
.sm-count {
  font-size: var(--font-size-11);
  color: var(--text-tertiary);
}

/* ---- 卡片网格 ---- */
.sm-grid {
  display: grid;
  grid-template-columns: repeat(auto-fill, minmax(320px, 1fr));
  gap: var(--space-12);
}
.sm-card {
  display: flex;
  flex-direction: column;
  gap: var(--space-6);
  padding: var(--space-14);
  background: var(--bg-elevated);
  border: 1px solid var(--border-base);
  border-radius: var(--radius-10);
  box-shadow: var(--shadow-card);
  transition: border-color 0.15s ease;
}
.sm-card:hover { border-color: var(--primary); }
.sm-card-top {
  display: flex;
  align-items: center;
  flex-wrap: wrap;
  gap: var(--space-6);
}
.sm-card-title {
  font-size: var(--font-size-14);
  font-weight: 600;
  color: var(--text-primary);
}
.sm-tag { margin: 0; font-size: var(--font-size-11); }
.sm-card-name {
  font-family: var(--font-mono);
  font-size: var(--font-size-12);
  color: var(--text-tertiary);
}
.sm-card-desc {
  margin: 0;
  font-size: var(--font-size-12);
  line-height: 1.65;
  color: var(--text-secondary, var(--text-primary));
  display: -webkit-box;
  /* ★ 老板原文：「描述文字默认截断，只展示前 2 行，鼠标悬浮 tooltip 展示完整描述。
     原来卡片大段描述占满空间，是造成页面拥挤最大元凶。」
     悬停全文由模板上的 `:title` 承担（原生 tooltip，零依赖）。 */
  -webkit-line-clamp: 2;
  -webkit-box-orient: vertical;
  overflow: hidden;
}
.sm-meta {
  display: flex;
  align-items: center;
  flex-wrap: wrap;
  gap: var(--space-4);
  font-size: var(--font-size-11);
}
.sm-meta-label {
  color: var(--text-tertiary);
  margin-right: var(--space-2);
}
.sm-agent-tag,
.sm-tool-tag {
  margin: 0;
  font-size: var(--font-size-11);
}
.sm-muted {
  color: var(--text-disabled);
  font-size: var(--font-size-11);
}
.sm-card-actions {
  display: flex;
  gap: var(--space-6);
  margin-top: var(--space-4);
  padding-top: var(--space-8);
  border-top: 1px solid var(--border-base);
}

/* ---- 列表视图（第 193 轮）----
   ★ 密度优先：一行一项，行内三段 = 主区（标题 / slug / 描述）| 装配区 | 操作区。
   ★ 与卡片视图**共用同一份数据**（同一批 store.items、同一批 store.titleOf*），
     字段对等由 `scripts/check-skill-view-parity.cjs` pin 住。 */
.sm-list {
  display: flex;
  flex-direction: column;
  background: var(--bg-elevated);
  border: 1px solid var(--border-base);
  border-radius: var(--radius-10);
  box-shadow: var(--shadow-card);
  overflow: hidden;
}
.sm-row {
  display: flex;
  align-items: center;
  gap: var(--space-12);
  padding: var(--space-8) var(--space-14);
  border-bottom: 1px solid var(--border-base);
  transition: background 0.15s ease;
}
.sm-row:last-child { border-bottom: none; }
.sm-row:hover { background: var(--bg-base); }
.sm-row-main {
  flex: 1 1 auto;
  min-width: 0;
  display: flex;
  flex-direction: column;
  gap: 2px;
}
/* 行内**不换行**（align-items 不带 wrap）：换行会把行高撑起来，密度就没了 */
.sm-row-top {
  display: flex;
  align-items: center;
  gap: var(--space-6);
  min-width: 0;
}
.sm-row-title {
  font-size: var(--font-size-13);
  font-weight: 600;
  color: var(--text-primary);
  white-space: nowrap;
}
.sm-row-slug {
  font-family: var(--font-mono);
  font-size: var(--font-size-11);
  color: var(--text-tertiary);
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
  min-width: 0;
}
.sm-row-desc {
  margin: 0;
  font-size: var(--font-size-12);
  line-height: 1.6;
  color: var(--text-secondary, var(--text-primary));
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}
/* 装配区：定宽两行小字；标签超出**裁掉**（悬停 title 看全），不换行 */
.sm-row-side {
  flex: 0 0 236px;
  min-width: 0;
  display: flex;
  flex-direction: column;
  gap: 2px;
}
.sm-row-meta {
  display: flex;
  align-items: center;
  gap: var(--space-4);
  font-size: var(--font-size-11);
  min-width: 0;
  overflow: hidden;
}
.sm-row-meta :deep(.ant-tag) {
  margin: 0;
  font-size: var(--font-size-11);
  flex-shrink: 0;
}
.sm-row-actions {
  flex: 0 0 auto;
  display: flex;
  gap: var(--space-6);
}

/* ---- Agent 装配 ---- */
.sm-tip {
  margin: 0 0 var(--space-12);
  font-size: var(--font-size-12);
  color: var(--text-tertiary);
}
.sm-agents {
  display: flex;
  flex-direction: column;
  gap: var(--space-10);
}
.sm-agent-card {
  padding: var(--space-14);
  background: var(--bg-elevated);
  border: 1px solid var(--border-base);
  border-radius: var(--radius-10);
}
.sm-agent-head {
  display: flex;
  align-items: center;
  gap: var(--space-8);
  flex-wrap: wrap;
}
.sm-agent-title {
  font-size: var(--font-size-14);
  font-weight: 600;
  color: var(--text-primary);
}
.sm-agent-key {
  font-family: var(--font-mono);
  font-size: var(--font-size-11);
  color: var(--text-tertiary);
}
.sm-agent-desc {
  margin: var(--space-4) 0 var(--space-10);
  font-size: var(--font-size-12);
  color: var(--text-tertiary);
}
.sm-agent-skills {
  display: flex;
  flex-wrap: wrap;
  gap: var(--space-6) var(--space-16);
}
.sm-ck-label { font-size: var(--font-size-12); }
.sm-ck-group {
  display: flex;
  flex-wrap: wrap;
  gap: var(--space-6) var(--space-16);
}

/* ---- 抽屉 ---- */
.sm-help {
  margin-top: var(--space-4);
  font-size: var(--font-size-11);
  line-height: 1.6;
  color: var(--text-tertiary);
}
.sm-help-inline { margin-left: var(--space-10); }
.sm-inline-tag {
  margin: 0 2px;
  font-size: var(--font-size-11);
  line-height: 16px;
}
.sm-help code {
  padding: 0 4px;
  font-family: var(--font-mono);
  background: var(--bg-hover-light);
  border-radius: var(--radius-3);
}
.sm-drawer-actions {
  display: flex;
  justify-content: flex-end;
  gap: var(--space-8);
  margin-top: var(--space-16);
}
.sm-rev-head {
  display: flex;
  align-items: center;
  gap: var(--space-8);
  font-size: var(--font-size-12);
  color: var(--text-primary);
}
.sm-rev-note {
  margin-top: var(--space-2);
  font-size: var(--font-size-11);
  color: var(--text-tertiary);
}
.sm-rev-body {
  margin: var(--space-6) 0;
  padding: var(--space-8);
  font-family: var(--font-mono);
  font-size: var(--font-size-11);
  line-height: 1.6;
  color: var(--text-secondary, var(--text-primary));
  background: var(--bg-hover-light);
  border-radius: var(--radius-6);
}
/* ---- 顶部筛选区（第 194 轮建 / 第 195 轮压成一行，照资料库范式）----
   ★ `flex-wrap: wrap` 是**兜底**而不是主态：主态（≥1280px）全部控件在
     同一行；窄屏宁可换行，也不要横向溢出把页面撑出滚动条。 */
.sm-filters {
  display: flex;
  align-items: center;
  flex-wrap: wrap;
  gap: var(--space-8);
  padding: var(--space-10) var(--space-12);
  margin-bottom: var(--space-12);
  background: var(--bg-elevated);
  border: 1px solid var(--border-base);
  border-radius: var(--radius-10);
}
.sm-filters > .ant-checkbox-wrapper {
  font-size: var(--font-size-12);
  white-space: nowrap;
}

/* ---- 分组外壳（第 194 轮）----
   ★ 「不分组」时 `g.title` 为空 ⇒ 不渲染标题行，这一层退化成透明的容器
     （这正是"单组特例"能在视觉上也成立的原因）。 */
.sm-groups {
  display: flex;
  flex-direction: column;
  gap: var(--space-14);
}
.sm-group-head {
  display: flex;
  align-items: center;
  gap: var(--space-6);
  padding: var(--space-6) var(--space-8);
  margin-bottom: var(--space-8);
  cursor: pointer;
  user-select: none;
  border-radius: var(--radius-6);
  transition: background 0.15s ease;
}
.sm-group-head:hover { background: var(--bg-hover-light); }
.sm-group-caret {
  width: 14px;
  font-size: var(--font-size-11);
  color: var(--text-tertiary);
}
.sm-group-title {
  font-size: var(--font-size-13);
  font-weight: 600;
  color: var(--text-primary);
}
.sm-group-count {
  font-size: var(--font-size-11);
  color: var(--text-tertiary);
}

/* ---- 收藏星标（⭐）----
   ★ 用**原生 button** 而不是 `a-button`：两侧（卡片/行）都要有它，
     用 antd 按钮会同时改变 `check-skill-view-parity.cjs` A4 数到的
     按钮数量 —— 虽然两侧同增同减仍相等，但这个按钮的语义是"开关"，
     不是 antd 那套"操作按钮"，混进去会让 A4 这个数字的含义变模糊。 */
.sm-star {
  flex-shrink: 0;
  padding: 0 2px;
  font-size: 15px;
  line-height: 1;
  color: var(--text-disabled);
  background: none;
  border: none;
  cursor: pointer;
  transition: color 0.15s ease, transform 0.1s ease;
}
.sm-star:hover:not(:disabled) { color: var(--primary); transform: scale(1.15); }
.sm-star.is-on { color: var(--primary); }
.sm-star:disabled { cursor: not-allowed; opacity: 0.5; }

/* ---- 一行标签（版本｜状态｜类型｜标签｜启用于｜配套工具）----
   ★ 配色只用已确认存在的 token（`--text-*` / `--bg-hover-light` / `--primary`）：
     本轮**不引入任何裸 hex** —— 本仓有「硬编码颜色收敛」的棘轮门禁，
     新加的每一个裸色值都会变成下一个要还的债。 */
.sm-chips,
.sm-row-chips {
  display: flex;
  align-items: center;
  flex-wrap: wrap;
  gap: var(--space-4);
  font-size: var(--font-size-11);
  min-width: 0;
}
.sm-chip {
  padding: 1px 6px;
  color: var(--text-secondary, var(--text-primary));
  background: var(--bg-hover-light);
  border-radius: var(--radius-3);
  white-space: nowrap;
}
.sm-chip-ver {
  font-family: var(--font-mono);
  color: var(--text-tertiary);
}
.sm-chip-demo { color: var(--primary); }
.sm-chip-off { color: var(--text-disabled); }
.sm-chip-priv { color: var(--text-tertiary); }
.sm-chip-no-card { color: var(--text-secondary); }
.sm-chip-agents,
.sm-chip-tools { color: var(--text-tertiary); }

/* 行视图的标签区：允许换行但默认单行显示，超出裁掉（悬停看全由 title 承担） */
.sm-row-chips {
  flex: 0 0 320px;
  overflow: hidden;
}


</style>
