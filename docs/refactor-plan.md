# 前端巨型组件拆分方案（refactor-plan）

> 立项日期：2026-09-11
> 范围：`frontend/src`，仅做「代码搬家 + 样式归位」，不改数据流与状态管理
> 验收门禁：每阶段结束跑 `npm run build`（= `vue-tsc && vite build`，类型检查 + 构建双关）
> 提交策略：每阶段一个 commit（暂不 push，攒批）

---

## 一、体检结论

### 1.1 超标的不是一个组件，是 6 个

| 文件 | 总行数 | template | script | style | 主要病因 |
|---|---:|---:|---:|---:|---|
| `components/ChatPanel/index.vue` | 3550 | 401 | 2920 | 227 | 大脚本（业务函数堆组件里） |
| `components/KnowledgeBase/ProductLibrary.vue` | 2446 | — | — | 878 | 大脚本 + 大样式 |
| `components/KnowledgeBase/PlatformRules.vue` | 2178 | — | — | — | 大脚本（导入向导 404 行） |
| `components/SmartPanel/index.vue` | 2020 | 961 | 162 | 895 | 巨型 `v-else-if` 分支枚举 |
| `components/ChatPanel/results/BlueOceanResult.vue` | 1772 | — | — | 822 | 大模板 + 大样式 |
| `components/ChatPanel/tools/CompetitorCompare.vue` | 1213 | — | — | — | 大模板 + 大样式 |

**关键观察**：`style` 是隐形大头——5 个文件的样式块都在 700–900 行量级。拆组件必须连带拆 CSS，否则会拆出 N 份重复样式。

### 1.2 三类病因 → 三种刀法

| 病因 | 典型 | 特征 | 刀法 |
|---|---|---|---|
| 大脚本 | ChatPanel（script 2920） | 业务函数堆在组件里 | 按「是否依赖响应式状态」分层：纯函数进模块，带状态的进 composable |
| 大模板+大样式 | SmartPanel（template 961 + style 895，script 仅 162） | 巨型 `v-else-if` 分支枚举 | 每个分支连同它的样式下沉为独立面板，主文件退化成路由器 |
| 抄来的 CSS | KB 三姐妹 | 页面之间复制粘贴 | 先抽共享层再拆，否则拆完重复 N 份 |

### 1.3 两个更该先处理的隐患

1. **404 行非 scoped 样式正在全局泄漏**（`App.vue` 除外）

   | 文件 | 行数 | 性质 |
   |---|---:|---|
   | `BlueOceanResult.vue` | 297 | teleport 到 body 的 popup 样式 |
   | `BidOptimizeResult.vue` | 56 | `html.dark .xxx` 深色补丁 |
   | `BudgetAllocResult.vue` | 44 | `html.dark .xxx` 深色补丁 |
   | `CandidateLibrary.vue` | 7 | popup 样式 |

   其中 `BidOptimize` / `BudgetAlloc` 的 `html.dark` 补丁，正是「全局补丁」反模式的实例。

2. **重复选择器远比预估的多，且大部分不能合并**：实测全项目 `.vue` 的 scoped 块里，**340 个选择器跨文件重名**，其中 **203 个各文件的值并不相同**（`.action-bar` 在 28 个文件里有 6 种写法、`.section-title` 有 14 种、`.result-header` 有 12 种）。这些只是**重名的局部写法**，不是同一个组件原型——粗暴抽公共层会造成串味。

---

## 二、各文件目标结构

| 文件 | 现状 | 目标 | 抽出的东西 |
|---|---:|---:|---|
| `ChatPanel/index.vue` | 3550 | ~700 | `mock/toolExecutors.ts`（37 执行器 + registry，1643 行）、`composables/useChatOrchestrator.ts`（~1000 行） |
| `SmartPanel/index.vue` | 2020 | 226 ✅ | `panels/` 下按 `contentType` 拆 **21 个**子组件（实测 20 个分支 + 1 个 `RawPanel` 兜底），样式随分支下沉 |
| `ProductLibrary.vue` | 2446 | ~600 | 表格单元格渲染器、`ProductDetailDrawer.vue`、导入向导 |
| `PlatformRules.vue` | 2178 | ~550 | 导入向导（404 行那段）、AI 拆分流程、规则表 |
| `BlueOceanResult.vue` | 1772 | ~600 | 表格主体、详情抽屉；样式并入共享层 |
| `CompetitorCompare.vue` | 1213 | ~500 | 表格主体、SWOT 区块 |

---

## 三、分阶段执行（S0 → S5，风险递增）

### S0 止血（风险低，不动结构）

**S0a 全局样式归位（已完成）**

- 4 处非 scoped 块（共 404 行）从组件搬进独立全局层，`main.ts` 统一引入：

  | 新文件 | 内容 | 来源 |
  |---|---|---|
  | `src/styles/popup.css` | teleport 到 body 的弹层样式 | `BlueOceanResult`（`.roi-tip*` / `.detail-*` / `.dkpi*` / `.drow` / `.cost-*` / `.lq-*`，248 行）+ `CandidateLibrary`（`.row-more-menu*`） |
  | `src/styles/dark-overrides.css` | `html.dark` 下的组件级补丁 | `BidOptimizeResult`(54) + `BudgetAllocResult`(42) + `BlueOceanResult`(49) |

- 这 4 处本来就是「非 scoped = 全局 CSS」，搬到独立文件是**等价迁移**（选择器、优先级、级联位置均不变）。
- **顺带修掉一个真 bug**：`BlueOceanResult` 的深色补丁写成了 `:global(html.dark) xxx`，但该块是非 scoped 的，Vue 不做 `:global()` 解析 → 构建产物里原样输出 `:global(html.dark)`（实测 18 处），是非法选择器，浏览器整条丢弃，**从未生效**。归位后去掉包装，规则开始生效。
- 结果：全项目只剩 `App.vue` 一个全局块（token 层），其余 4 处泄漏清零。

**S0b 重复选择器抽共享层（暂缓，需先设计）**

- 实测数据：340 个跨文件重名选择器里 **203 个写法不同**，只有 137 个逐字一致。
- 这些重名多为局部习惯命名（`.title` / `.meta` / `.info` / `.bar` / `.dot` / `.item-*`），**不是共享组件原型**。
- 结论：不能机械抽取。更合适的时机是 **S2/S4 重建这些组件时**——那时同一原型会被收敛成真正的共享组件，样式自然合并，而不是在现状上硬抽一个会污染全局命名空间的 `shared.css`。
- 待办：若要推进，只挑「逐字一致 + 出现 ≥3 文件 + 名字有明确语义」（如 `.kpi-grid` / `.panel-card` / `.loader-btn` / `.hint-chip`）的部分，逐个确认无跨组件误伤后再抽。

### S1 低垂果实（已完成）

**产出**

| 文件 | 变化 |
|---|---|
| `src/mock/toolExecutors.ts` | **新建**，1730 行：37 个 `executeXxx` + `getParamSummary` + `timeRangeLabel` + `toolExecutors` 注册表 |
| `src/components/ChatPanel/index.vue` | 3550 → **1760** 行（-1790） |

**做法**
- `executeXxx`（原 1000–2642）整块搬进新模块，加 `export`；
- 原 743–861 的 37 路 `switch (tool.id)` 换成 registry 查表：
  ```ts
  const executor = toolExecutors[tool.id]
  if (!executor) throw new Error(`未知工具: ${tool.id}`)
  const result: any = await executor(params)
  ```
- 同时把 `getParamSummary`（参数摘要，90 行）与它依赖的 `timeRangeLabel` 一并搬走（都是纯函数）。
- 唯一需要带过去的外部依赖是 `useMonitorPoolStore`（`executeMonitorDashboard` / `executePriceTrack` 内读取监控池）。

**留在组件的（碰 store，属编排层，S3 再处理）**
- `saveScriptToStore`（写 `videoScripts` store）
- `syncListingDraft`（读 `productLibraryStore` / 写 `listingDraftStore`）
- `normalizeDescToModules`（`syncListingDraft` 的私有辅助）

**验收**：`npm run build` → `✓ built`，0 类型错误。纯机械改造，无行为变更。

### S2 SmartPanel（已完成，但**发现该组件是死代码**）

**产出**

| 文件 | 变化 |
|---|---|
| `src/components/SmartPanel/index.vue` | 2020 → **226** 行（-1794） |
| `src/components/SmartPanel/panels/*.vue` | **新建 21 个**（20 个 `contentType` 分支 + `RawPanel` 兜底） |

**做法**
- 模板 20 路 `v-else-if` 链保留在 `index.vue`（**保住原「数据缺失时落到 `v-else` 显示 JSON」的 fall-through 语义**），分支体逐个下沉为 `panels/<Name>.vue`，模板原文照搬。
- **props 用 store 派生类型**而非 `any`，避免拆完丢失类型推断：
  ```ts
  import type { useResultStore } from '@/stores/result'
  type ResultStore = ReturnType<typeof useResultStore>
  defineProps<{ profitData: NonNullable<ResultStore['profitData']> }>()
  ```
  这样 store 字段改名时，21 个面板仍会被 `vue-tsc` 抓到。
- **样式拆分按归属分析**：165 条顶层规则逐条判定归属——每面板独占规则随分支下沉；跨面板共享的 9 条原子（`.panel-title` / `.section-title` / `.score-label` / `.score-value` / `.score-header` / `.rec-list` / `.metric-value` / `.code-block`）**留在 `index.vue` 并用 `:deep()` 穿透**，避免抄成 N 份。
- 有两条规则（`.section-title` / `.score-label` / `.score-value`）原文**各有两份定义、靠级联后者胜出**，属历史遗留。为保零视觉变化，两份都保留在原顺序（未合并、未"修正"）。
- 覆盖率自检：**165 条规则一条不漏**（三合一的 `.competitor-monitor, .market-share, .intruder-detection` 拆成 3 条，故 165 → 167）。

**顺带修掉一个真 bug**：生成的 `index.vue` 里 `ChartPanel` 误用 `v-if` 而非 `v-else-if`，会**另起一条条件链**——`contentType === 'table'` 时会同时渲染 `RawPanel`（`v-else`）。已修。

**⚠️ 重大发现：`SmartPanel` 是死代码**

全仓检索确认：**没有任何文件 import 过 `SmartPanel`**，全项目只有 `stores/result.ts:270` 的一句注释提到它（"供 SmartPanel 可视化使用"）。`vite build` 产物里也完全搜不到 `smart-panel` / `panel-content` / `profit-analysis` —— 它被 tree-shaking 整个丢掉了。

成因推测：任务 #97「将工具结果从独立区域改为消息流内联模式」把结果展示搬进了 `chatStore.messages` 内联渲染，旧的右侧展示面板就此被废弃，但组件与 `resultStore` 的写入调用一起留了下来。

连带发现：
- `stores/result.ts` 是**只写不读**——`ChatPanel` 有 5 处 `useResultStore().setResultData(...)`，但**没有任何读取方**。
- `ChatPanel/results/SentimentAnalysisResult.vue` 同样 0 引用。

**对比：S1 的目标 `ChatPanel` 是活代码**（`views/Workspace.vue:144` 渲染它），所以 S1 与 S0 的收益是实的；S2 则是在给一段不参与构建的代码做整形。

**处置结论（2026-09-11）：整棵子树已删除。** 删除集与证据：

| 删除对象 | 规模 | 证据 |
|---|---|---|
| `src/components/SmartPanel/`（index.vue + panels/ 21 个） | 22 文件 | 0 引用；CSS 分毫未进产物 |
| `src/stores/result.ts` | 1129 行 | 仅 `ChatPanel` 5 处写入、无读取方 |
| `src/components/ChatPanel/results/SentimentAnalysisResult.vue` | 126 行 | 0 引用 |
| `ChatPanel/index.vue` 内 5 处 `setResultData(...)` + 1 处 import | -15 行 | 同几行上方已有 `chatStore.addMessage({ data, displayType })`，写入纯冗余 |

**体积收益（删除前后同机构建对比）**

| chunk | 删除前 | 删除后 | 变化 |
|---|---:|---:|---:|
| `Workspace-*.js` | 981.61 kB | 961.80 kB | **-19.81 kB**（gzip -7.91 kB） |
| `Workspace-*.css` | 226.24 kB | 226.24 kB | 0（不变） |

CSS 分毫不动 → **反证 SmartPanel 确实早已被 tree-shaking 剔除**（产物里从来不存在）；JS 少 19.81 kB → 证明 `result.ts` 是**真被打进包的活代码**，这笔删除才是实打实的收益。

备份：`.workbuddy/backup/dead-code-20260911/`（含删除前的 SmartPanel 全树、result.ts、SentimentAnalysisResult.vue、ChatPanel 清理前快照）。

### S3 ChatPanel 编排层（✅ 已完成，风险实为中偏低）

`handleToolAnalysisEvent` / `addResultSummaryToChat` / `simulateAgentResponse` / `syncListingDraft` / `saveScriptToStore` / 快捷 chip / HITL / 滚动 → `composables/useChatOrchestrator.ts`。**`ChatPanel/index.vue` 1746 → 732 行，新文件 1138 行。**

**为什么风险被改判**：搬的是 899 行控制流（行为主干），但真接缝只有 3 处 —— ① 2 个 `v-model`（`intelDays`、`inputMessage`）② 4 类模板/注入绑定（`messageListRef` / `mainContentRef` / `loadedCandidate`）。这些**必须留在组件**、以参数传入 composable；其余符号无跨组件耦合。做法沿用 S2 套路（纯内部直接搬、绑定留组件、`build` 双关）。

组件层保留的「不可搬」清单（即 `ChatOrchestratorOptions` 的由来）：

| 类别 | 符号 | 原因 |
|---|---|---|
| v-model ref | `inputMessage`、`intelDays` | ref 若由 composable 拥有，组件侧 `v-model` 会退化成给 const 赋值 |
| 模板 ref | `messageListRef`、`mainContentRef` | 只在模板里声明 |
| inject | `loadedCandidate`（`workingCandidate`） | 只能在组件 setup 中 inject |
| store（模板直用） | `agentStore`、`pool`、`shopStore` | 模板里做 Agent 判定与 scope tag |

**顺带清掉的死符号**：`setSelectedTool`（inject 后从未调用，仅注释里提及）、`loadedProduct`（inject 后从未引用）。另有一处真 bug 修复：`review-spy` 摘要模板多了一个 `}`（`${brand || '-'}}`）会渲染出 `-}`。

**验收**：`npm run build`（= `vue-tsc && vite build`）EXIT=0 → 类型检查与打包双通过；产物中可搜到 composable 特征字符串（未被 tree-shake）；`Workspace-*.js` 963.14 kB（S1/S2 基线 961.80 kB，+1.34 kB 为模块边界与返回对象的开销）。样式未改动。

> 仍需实机验证：流式渲染与工具分析两条真跑 SSE 的路径（清单见第五节末）。

### S4 知识库三姐妹（风险中高）

`ProductLibrary` / `PlatformRules` / `CandidateLibrary` / `AssetLibrary`。依赖 S0 的共享样式层先就位。

### S5 结果卡收尾（风险中）

`BlueOceanResult` / `CompetitorCompare` 等结果组件的表格主体与详情抽屉下沉。

---

## 四点五、动工前的存活检查（S2 教训）

**每个阶段开工前，先跑一遍「谁引用它」**，避免像 S2 那样给死代码整形：

```bash
# 1) 组件是否被引用（0 = 死代码）
grep -rn "组件名" src --include=*.vue --include=*.ts | grep -v "^src/components/<自身目录>/"

# 2) 是否真的进了构建产物（0 = 被 tree-shake 掉）
npm run build && grep -rl "<特征字符串>" dist/
```

S2 之后已确认的存活状态：

| 模块 | 引用 | 结论 |
|---|---|---|
| `components/ChatPanel` | `Workspace.vue:144` | ✅ 活 |
| `mock/toolExecutors.ts`（S1 产物） | `ChatPanel/index.vue:449` | ✅ 活 |
| `components/ChatPanel/results/*` | 各 2–7 处 | ✅ 活（`SentimentAnalysisResult` 已删） |
| `components/SmartPanel` | **0** | ❌ 死代码 → **已删除** |
| `stores/result.ts` | 只有写入方，无读取方 | ⚠️ 只写不读 → **已删除** |
| `ChatPanel/results/SentimentAnalysisResult.vue` | **0** | ❌ 死代码 → **已删除** |

---

## 四、边界（明确不做）

- **不改数据流**：`provide/inject`、`CustomEvent`、`chatStore.messages` 内联 `tool_result` 渲染全部保持原样，只搬代码位置。
- **不顺手换状态管理**：不引入 Pinia 改造、不重写响应式结构——那是另一个量级的风险。
- **不为了拆而拆**：`stores/platformRules.ts`(1268)、`mock/data.ts`(1253) 虽大，但是单一职责的数据文件，拆了反而更难找，**不动**。

---

## 五、进度

| 阶段 | 状态 | 备注 |
|---|---|---|
| S0a 全局样式归位 | ✅ 完成 | `src/styles/popup.css`(262) + `dark-overrides.css`(166)；顺带修掉 `:global()` 死规则 |
| S0b 重复选择器抽共享层 | ⏸ 暂缓 | 实测 340 个重名、203 个写法不同 → 不可机械抽取，宜随 S2/S4 收敛 |
| S1 低垂果实 | ✅ 完成 | `mock/toolExecutors.ts`(1730) 新建；ChatPanel 3550 → 1760 |
| S2 SmartPanel | ✅ 完成 | 2020 → 226 行 + `panels/` 21 个；顺带修掉 `ChartPanel` 误用 `v-if` 的链断裂 bug。**但该组件 0 引用，是死代码** |
| S3 编排层 | ✅ 完成 | ChatPanel 1746 → 732；新建 `composables/useChatOrchestrator.ts`(1138)；清掉 2 个死符号 + 修 1 处模板 bug |
| S4 知识库三姐妹 | 未开始 | |
| S5 结果卡收尾 | 未开始 | |

### 实机验证清单（S3 后，`npm run dev` 手动点）

因为 S3 动的是行为主干，构建通过 ≠ 运行正确，以下两条真跑 SSE 的路径需要点一遍：

1. **流式渲染**：选品分析师 / Listing 优化师 / 广告分析师 / 智能客服 → 输入任意问题发送，确认打字机逐字输出、「思考中」spinner 在首 token 后消失、失败时能降级到非流式。
2. **工具分析**：右侧配置面板触发任一工具 → 确认对话流按序出现「参数摘要 → 结果卡 → 摘要文本」，且 Listing 类工具结果同步到右侧草稿。
3. 顺带看：竞品监控员/选品/复盘/广告四个 chip 动作条（归属 composable）；发送按 Enter；新消息自动滚到底；暗色模式下 BlueOceanResult 的深色补丁（S0 激活的那批）。

---

## 六、待老板决策

1. **`SmartPanel` 已删**（连同 `stores/result.ts`、`SentimentAnalysisResult.vue`，2026-09-11 老板选「1：删除整棵子树」）。备份在 `.workbuddy/backup/dead-code-20260911/`，如需复活可从那里取回整棵子树。

## 七、后续可选

- **S4 知识库三姐妹**（`ProductLibrary` 2446 / `PlatformRules` 2178 / `CandidateLibrary` / `AssetLibrary`）：依赖 S0 共享样式层已就位（已完成），随时可开工。建议先跑存活检查。
- **S5 结果卡收尾**：`BlueOceanResult` / `CompetitorCompare` 表格主体与详情抽屉下沉。
