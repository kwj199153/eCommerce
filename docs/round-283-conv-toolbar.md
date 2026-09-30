# 第 283 轮 · 对话窗口右上角工具条 + 右栏折叠回程入口

> 老板原话：「在对话窗口增加 3 个按钮（查找、分享、历史提问），参考 workbuddy 的对话窗口右上角；
> 右侧边栏的折叠按钮当折叠后，在对话窗口右上角没有展开按钮」
>
> 交付时间：2026-09-27 · 验证方式：CDP 真实浏览器探针（17/17）+ 全量前端门禁 + `npm run build`

---

## 一、做了什么

| # | 入口 | 位置 | 行为 |
|---|---|---|---|
| 1 | **查找** | 对话区右上角 | 弹出面板 → 输入关键词 → 命中行内高亮 → 点结果滚到那条并闪烁 1.8s |
| 2 | **分享** | 同上 | 下拉两项：复制为 Markdown / 下载 `.md` 文件（无对话时禁用） |
| 3 | **历史提问** | 同上 | 列出「我问过什么」（倒序、带序号与时间）→ 点击跳转 |
| 4 | **展开右侧面板** | 同上（紧邻三按钮右侧） | 右栏收起后出现，点击把右栏叫回来 |

改动文件：

| 文件 | 改动 |
|---|---|
| `frontend/src/components/ChatPanel/ConversationToolbar.vue` | **新建**（三按钮 + 两个面板 + 分享实现） |
| `frontend/src/views/Workspace.vue` | 顶栏挂载工具条；加展开按钮 + `canExpandRightPanel` 判据 + 样式 |
| `frontend/src/components/ChatPanel/index.vue` | 消息 wrapper 加 `data-msg-index`；监听跳转事件（滚动 + 高亮）；`.msg-flash` 动画 |
| `frontend/src/styles/popup.css` | 弹层样式（popover 被 teleport 到 body，scoped 样式够不到） |
| `frontend/scripts/cdp-conv-toolbar-probe.mjs` | **新建** 探针（17 条判据，含几何与行为） |
| `frontend/package.json` | 登记 `npm run check:conv-toolbar`（与 `check:sidebar-geometry` 同惯例） |

---

## 二、四个关键判断（都是「另一种写法会静默坏掉」的地方）

### 1. 数据不经过 props —— 直接读 `chatStore.messages`

工具栏渲染在顶栏，对话框在它下面。想让两者共享消息有两条路：props 下发，或各自读同一个 store。
选了后者：`chatStore.messages` 是按 `activeAgentId` 分片的 computed，**全局单例、与 ChatPanel 同源**
—— props 通道只会多出一份会漂移的拷贝。

### 2. 「跳到第几条」必须用**消息数组下标**，且落点只能在 ChatPanel

工具栏知道要跳哪条，但**消息 DOM 只住在 ChatPanel**（滚动容器 `.main-content` 也在那里）。
让工具栏自己 `document.querySelector` ⇒ 它得**复刻**「工具结果 / 普通文本两套 `v-if/v-else` 分支」
的下标算法 —— 同一个下标两份实现，将来加一种消息类型必然错位一处。

所以：工具栏派发 `chat-scroll-to-message { index }`，ChatPanel 落点。
下标写在 `v-for` 的 wrapper 上（`data-msg-index`），**不是 DOM 序号**。

### 3. 高亮片段必须先 `escapeHtml` 再插 `<mark>`

`v-html` 渲染的是**用户输入 + 模型输出**，两者都不可信（消息里完全可能出现 `<img onerror=…>`）。
顺序反了（先插标签再转义）就是自造一条 XSS 通道。

### 4. 弹层样式只能落在 `styles/popup.css`

antd 的 popover 被 teleport 到 `<body>`，组件里 scoped 样式的 `[data-v-*]` 选择器**匹配不到**
—— 写在组件 `<style scoped>` 里会**静默失效**（面板多出一圈白边，且没有任何报错）。
项目已有明确归处：`styles/popup.css`（文件头注释列了全部来源，本轮已登记新增项）。

---

## 三、顺带发现的两个问题

### 问题 1：右栏「收起」曾经是个**单向操作**

右栏是 `<a-layout-sider :collapsed-width="0" :trigger="null">`：收起后宽度归零、
默认把手也关掉，界面上**不留任何痕迹**。

而面板内的收起按钮（`.collapse-trigger`）随面板一起消失 —— 它虽然写了
`v-else` 的展开箭头，但那行代码在 0 宽容器里谁也看不见。
于是「收起」之后只有三条**绕路**能把它叫回来：选工具 / 切 Agent / 从资料库返回。

现已补上唯一的直接回程入口。显示条件与右栏自身挂载条件**同源**
（`currentView === 'chat' && !isSecretaryAgent`）—— 店秘书没有右栏，
对它显示这个按钮就是一个「点了没反应」的按钮。

### 问题 2：antd 关 popover 是 `display:none`，**不销毁 DOM**

这条是探针自己抓出来的：两个面板都带 `.conv-toolbar-pop`，
`document.querySelector` 永远返回**第一个**（即使它已隐藏）⇒
「历史提问」的标题读成空串、行数读成消息总条数 —— 一条**假读数**。

修法：探针里筛「可见的那个」（`getBoundingClientRect().width > 0`）。
同类坑：关弹层要发 `mousedown`（antd 判「外部点击」听的是 mousedown，不是 click），
只发 click 面板会一直挂着。

---

## 四、验证

### CDP 真实浏览器探针（`npm run check:conv-toolbar`，17/17）

| 组 | 判据 |
|---|---|
| L0 | 恰好 3 个按钮、都有图标、title 分别是查找/分享/历史提问 |
| L1 | 在顶栏纵向范围内、落在**右半区**、三按钮水平排布 |
| L2–L3 | 查找面板打开 → 有内容或诚实空态 → 输入过滤生效且命中词被 `<mark>` → 点结果后面板关闭**且目标消息带 `.msg-flash`** |
| L4 | 历史提问面板标题正确、有内容或诚实空态 |
| L5 | 分享菜单两个出口（Markdown / 下载） |
| L6 | 切到有右栏的 Agent：不显示展开按钮 → 收起后宽度归零**且展开按钮出现** → 按钮在顶栏右半区、与工具条同一条线 → 点击后右栏恢复、按钮自行消失 |
| L7 | 大屏模式（中间栏被压窄）下顶栏子元素**不越界** |

截图留档：`.workbuddy/probes/r283_conv_toolbar/`（5 张）

### 其它

- `npm run build` 全绿（27 条前端门禁 + `vue-tsc` + `vite build`）
- 三条主题/动作 python 门禁全绿（`check-theme-var-refs` / `check-theme-boot` / `check-app-actions`）
- 逐条复核过的相邻门禁：`check-empty-state-honesty`（空态文案口径）、
  `check-toast-ownership`（成功提示归调用点、不得出现裸 `silent`）、
  `check-chat-domain-split`（编排域 return 键序列 —— 本轮**刻意不动**它，功能全在组件内）

---

## 五、刻意没做的

- **没有把三个按钮接进 `useChatOrchestrator` 的返回键**：那 30→23 个键是冻结契约
  （`check-chat-domain-split.cjs::RETURN_KEYS` 逐项相等），而本轮功能完全可以住在组件内。
- **没有给弹层加 `destroyOnHidden`**：不确定 antd-vue 4.x 的确切 prop 名，
  加错等于没加；隐藏 DOM 只是多占一点内存，不影响行为（探针已按"可见性筛选"处理）。
- **没有做「分享链接」**：后端没有对话分享接口，做个假链接就是死按钮。
  现在两个出口（复制 Markdown / 下载 .md）都是真能用的。
