# 新手引导（Product Tour）锚点清单 —— #1012 产出

> 状态：**已冻结**（供 #1013 配置层 / #1014 打标 / #1015 门禁 / #1016 实测消费）
> 范围：MVP · 一条主线 **7 步**（选店铺 → 挑 Agent → 说话 → 看结果 → 配任务 → 翻资料库 → 收尾）
> 语音：浏览器原生 `speechSynthesis`（老板拍板）
> 进度：`localStorage`（老板拍板）

---

## 一、先说结论：三条硬约束

### 约束 1 · 锚点**禁止**用 CSS 选择器，一律 `data-tour="xxx"`

不是洁癖，是本仓已经踩到的坑。实测证据：

```
$ grep -rl 'class="main-content"' src/
src/components/ChatPanel/index.vue      ← 对话区容器
src/views/Workspace.vue                 ← 中间内容区容器
```

**同一个类名在两个组件里各指一个不同的盒子**（且都是各自 `scoped` 样式）。
一旦锚点写成 `.main-content`，下面三件事必然发生其一：

- 选中了两个 ⇒ 聚光圈按第一个算，高亮到错误的盒子（且**不会报错**）；
- 组件加 `:class` 动态样式 / 改类名 ⇒ 锚点静默落到 0 个元素，引导走到那一步**空跑**；
- 折叠态 / 大屏模式给外层套条件类 ⇒ 锚点与「随时会改的 DOM 结构」绑死，改样式就等于改引导。

`data-tour` 的三个附加好处：**可被脚本双向对账**（注册了没标 / 标了没注册都能查，这是 #1015 的判据基础）、**不影响任何既有样式**（零选择器权重）、**读不懂 CSS 也能看懂 demo 意图**。

### 约束 2 · 锚点必须是「折叠态仍然存在」的容器

`a-layout-sider :collapsed` 改变的是**宽度**，不是挂载（这一点待 #1016 在真实浏览器里用 `getBoundingClientRect` 复核，不预先当结论）。
因此折叠态下所有侧栏锚点**仍然选得到**，但只有约 80px 宽 —— 聚光圈会缩成一条缝，等于没讲。

⇒ 处理办法不是回避这些锚点，而是**进入侧栏类步骤前先请求展开**（见 §四）。

### 约束 3 · 引导**不得**替用户伪造业务状态

举例：右栏 `TaskConfigPanel` 的挂载条件是 `currentView === 'chat' && !isSecretaryAgent`。
而本项目**店秘书是默认选中的 Agent**（task #292），所以新人第一次进来的画面里**右侧根本没有面板**。

如果在引导里强行渲染一块「假的面板」来讲解，就是本仓反复防过的「**不可达面板 + 看得见的装饰**」。
正确做法是：**依赖不满足 ⇒ 该步跳过，并在收尾如实列出跳过原因**（见 §三 `requires` 列）。

---

## 二、锚点清单（7 步主线）

| # | `data-tour` | 落在哪个元素 | 源码锚点 | 挂载条件 | 未登录/演示态 | 折叠态 | `requires` |
|---|---|---|---|---|---|---|---|
| 1 | `tour-brand` | Workspace 左上品牌行（机器人头像 + 店名 + 店铺按钮的整体容器） | `views/Workspace.vue:18` `<div class="logo-row">` | 恒挂载 | ✅（店名可能为空，文案不得断言店名） | ✅ 收窄到 80px | 无 |
| 2 | `tour-shop-switch` | 店铺群触发器（右上角小图标 + 数量角标） | `views/Workspace.vue:36` `<button class="shop-trigger-btn">` | 恒挂载 | ✅ | ✅ | 无 |
| 3 | `tour-agent-list` | 侧边栏「Agent 群」整组 | `components/Sidebar/AgentList.vue:2` `<div class="agent-list">` | 恒挂载 | ✅ | ✅ 收窄 | 无 |
| 4 | `tour-chat-input` | 对话输入卡片（含语音输入 / 增强提示词 / 停止生成） | `components/ChatPanel/index.vue:265` `<div class="input-area">` | `currentView === 'chat'` | ✅ | —（不在侧栏） | `view === 'chat'`（可复用既有 `view-navigate` 事件切回） |
| 5 | `tour-chat-stream` | 对话消息区（AI 的回复与结构化结论卡都长在这里） | `components/ChatPanel/index.vue:4` `<div class="main-content" ref="mainContentRef">` | 同 4 | ✅ | — | 同 4 |
| 6 | `tour-right-panel` | 右侧任务配置面板（antd sider 本体） | `views/Workspace.vue:213` `<a-layout-sider class="right-panel">` | `view==='chat' && !isSecretaryAgent` | ⚠️ 默认选中的就是店秘书 ⇒ **首次进入不挂载** | — | `已选中 Agent 且 ≠ secretary`（另需 `rightPanelCollapsed === false`） |
| 7 | `tour-sidebar-repo` | 侧边栏「资料库 + 能力」整组 | `components/Sidebar/KnowledgeBase.vue:2` `<div class="knowledge-base">` | 恒挂载 | ✅ | ✅ 收窄 | 无 |

另设**一个常驻重播入口**（不是引导步骤）：账户菜单 `components/Sidebar/AccountMenu.vue` 的 overlay 里加「重看新手引导」一项。
理由：新手引导是一次性的（看完就记不住了），必须有一个**随时能回来的重播入口**；而账户菜单已经是「设置 / 外观 / 记忆」的既有落点，放这里不需要新开一处 UI。

> **为什么第 1、2 步不合并**：它们是两个不同的心智单元 ——「我是谁 / 当前在哪（品牌行）」与「数据作用域怎么切（店铺群）」。
> 后面所有资料库数据都按 `X-Shop-ID` 过滤，「切店铺 = 换一整套数据」这件事必须在引导里有**独立的一步**讲清楚，塞进品牌行那步会被带过。

---

## 三、每个锚点的实现批注（给 #1013/#1014 看的细节，非文案定稿）

### 1 · `tour-brand`
- 讲的是三件事：机器人头像 = 回店秘书；中间 = 产品名 + **当前店铺**；右侧 = 店铺群。
- ⚠️ 文案**不得**插值 `currentShop.name` —— 演示态 / 首屏店铺尚未加载时为 `undefined`，会出现「当前店铺：· undefined」。要提店名就用「这里会显示你当前所在的店铺」这种不依赖具体值的说法。
- 为什么不用 `.logo-brand`（只包头像+名）：它 `flex: 1` 但**不含**店铺按钮，聚光圈会切掉那颗按钮的一半。

### 2 · `tour-shop-switch`
- 角标 `<span class="shop-trigger-count">` 有 `v-if="!sidebarCollapsed"`，折叠态不渲染 ⇒ 按钮本体仍在，**不影响锚点存在性**，只是视觉上没数字。
- MVP **不自动展开**店铺 popover。理由：antd popover 会被 teleport 到 body，它的几何在滚动 / 重算时最脆，且会引入「引导必须驱动业务状态」的耦合。
  文案写成「点开它可以在你的 N 个店铺之间切换」即可 —— 用户读完这一步自己就会点。

### 3 · `tour-agent-list`
- 整组（含分组标题「Agent 群」+ `a-menu`）一起高亮，而不是高亮某一个 `a-menu-item`。
  理由：这一步的目的是让人知道「这里有 6 个分工不同的 Agent」，指向某一项会误导成「从这里开始」。
- 排除秘书是 AgentList 自己的逻辑（`agentList` computed 过滤 `id !== 'secretary'`），引导不需要知道。

### 4 · `tour-chat-input`
- 输入区里有三颗值得讲的按钮：麦克风（浏览器原生语音输入，已在 #424 落地）、「增强提示词」（`#911` 抽的共享组件）、停止生成（`#310` 同一位置二选一）。
- 这一步是「你不需要会写提示词」的落点。

### 5 · `tour-chat-stream`
- 锚的是 `.main-content`（ChatPanel 内），**必须**用 `data-tour` 而不是类名 —— 它是 §一 约束 1 的正面案例。
- 讲的是：回复逐字流出 → 结论就地长成结构化卡片 → 顶上「📌 最近结果」条（`index.vue:7`）可随时找回被冲走的结论。

### 6 · `tour-right-panel`
- **唯一有条件挂载的锚点**，也是唯一需要「请求 UI 准备」的两处之一。
- 两个前置必须都成立才讲：① 已选中 Agent 且不是 secretary（决定它存不存在）；② `rightPanelCollapsed === false`（决定它有没有宽度 —— collapsed 时宽度是 0，`getBoundingClientRect()` 拿不到可讲的盒子）。
- 前置不成立 ⇒ **跳过并在收尾如实报告**，不允许用静态示意图代替真实面板（约束 3）。

### 7 · `tour-sidebar-repo`
- 「资料库」7 项 + 「能力」2 项（Skill 仓库 / 工具仓库）两个 `a-menu` 同在一个根容器下，一步讲完。
- 顺序不是契约（KnowledgeBase 里有注释：门禁按**集合相等**判定），引导文案不要写「从上往下第三个」。

---

## 四、引导需要的两条例外命令（不要把 DOM 引用乱飞）

`sidebarCollapsed` / `rightPanelCollapsed` 都是 `Workspace.vue` 的 `<script setup>` 局部 ref，
而 `<TourHost />` 挂在 `App.vue`（全应用唯一的干净挂点），拿不到它们。两条路：

| 方案 | 代价 |
|---|---|
| A · 把两个 ref 提到新 store | 要动 Workspace 的所有消费点；为一个 MVP 去重构 Workspace 的既有格局，不划算 |
| **B · window CustomEvent 命令（采纳）** | Workspace 加 2 个 listener；**与本仓既有范式完全一致** |

本仓已经在用这套：`open-settings-drawer` / `open-memory-drawer` / `view-navigate` / `product-listing-optimize` / `monitor-launch-analysis`
—— 全是「谁都发得起、由属主自己执行」的命令式事件。跟着既有范式走，不新增一种架构。

需要的命令：

1. `tour:ensure-sidebar` —— 展开左栏（幂等：`sidebarCollapsed = false`，已是展开态则无副作用）。进入步骤 1/2/3/7 前发。
2. `tour:ensure-right-panel` —— 展开右栏（幂等：`rightPanelCollapsed = false`）。进入步骤 6 前发；**若右栏本身未挂载（店秘书状态）则这一步已被 `requires` 判死，不要发**。

切回对话视图**不需要新增**——复用既有的 `window.dispatchEvent(new CustomEvent('view-navigate', { detail: { view: 'chat' } }))`，
Workspace 已在 `onMounted` 监听并走 `handleKnowledgeNavigate('chat')`（它会把 Agent/工具状态一并理顺）。

> ⚠️ 边界：两条命令**只展开、不折叠**。引导无权在新人面前收起他本来就展开了的东西，
> 也无权在引导结束后把一个被展开态改写了的侧栏硬拧回去 —— 副作用单向、且首次进入时默认就是展开态。

---

## 五、给下游三个任务的输入

### → #1013（配置层）
`config/tourAnchors.ts` 必须是**锚点 id 的唯一真源**：一个 `readonly TourAnchorId[]`，7 个值逐字对齐本文件 §二 的第 2 列。
`config/tourSteps.ts` 只引 id，**不许**再写一遍字符串。

### → #1014（打标）
7 处 `data-tour`，每处都是**无条件渲染**的属性（不写 `:data-tour="cond ? 'x' : undefined"`）。
理由：一旦变成条件属性，「元素存在但没标」和「元素不存在」在 DOM 上同形，#1015 的对账门禁就废了一半。

### → #1015（门禁）
对账必须**双向**：
- 方向 A：注册了没标（`.ts` 里有 id，全仓 `data-tour` 找不到）⇒ 失败
- 方向 B：标了没注册（DOM 上有 id，清单里没有）⇒ 失败

反向注入至少 4 组：① 删掉一处 `data-tour`；② 清单里多写一个 id；③ 把某个 id 改一个字符（A+B 同时红）；④ 在别的文件里偷偷加一处同名 `data-tour`（重复宣告 ⇒ 必须红）。

---

## 六、本轮修正的一条旧说法

上一轮我在汇报里说「build 链有 **58 个** `check-*.cjs` 门禁」。实测：

```
build 链总步数 28，其中 check-*.cjs = 26
scripts/ 下 check-*.cjs 总数 = 26
⇒ 26 个全都挂在 build 链上，没有游离未挂载的
```

真实数字是 **26**（我此前把 `scripts/` 下所有脚本混着数了）。用它当「必须补门禁」的论据仍然成立，但数字按这个来。
