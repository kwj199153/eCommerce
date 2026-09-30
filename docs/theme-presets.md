# 主题预设表（P0）—— 把 3 处颜色真源收敛成 1 张表

> 执行顺序：**先 presets（本文）→ 再清补丁层**。本文只覆盖第一步。
> 目标：让「加一套主题」从「改 8 处」变成「加 1 项」，且**零视觉变化**。

---

## 一、改造前的真实成本

同一套深色色值需要人工维护在 **3 个地方**，必须逐字保持一致（改一处要改两处，注释里甚至写了这条警告）：

| # | 位置 | 内容 | 谁在用 |
|---|---|---|---|
| ① | `App.vue` `:root` | 53 个颜色变量（亮色基线） | 全部业务组件的 CSS |
| ② | `App.vue` `html.dark` | 同样 53 个变量的深色值 | 同上 |
| ③ | `stores/theme.ts` `DARK_SEMANTIC` / `LIGHT_SEMANTIC` | 5 + 2 个同名语义色 | antd 组件（靠算法链钉住） |

`html.dark` 那 53 个变量是**加主题时唯一的线性增长项**——每加一套配色就要再复制一份。

---

## 二、改造后：一条颜色轴 + 一条外观轴

```
                    ┌─ 颜色轴（随主题切换）────────────────────────────┐
   themeStore.mode ─┤  唯一真源：src/theme/presets.ts                 │
   (light/dark/system)  ├─ vars  ──→ installThemeStyles() 注入        │
                    │  │            html[data-theme="x"] { --x: y }   │
                    │  └─ antd  ──→ a-config-provider :theme          │
                    │               [ 打底算法, 语义色 pin ]           │
                    └───────────────────────────────────────────────┘

                    ┌─ 外观轴（与明暗无关）──────────────────────────┐
   App.vue :root ────┤  63 个变量：--radius-* / --space-* /            │
                     │  --font-size-* / --control-height* / 字体栈     │
                     │  + theme.ts DIMENSIONS（antd 侧数字）13 值      │
                    └───────────────────────────────────────────────┘
```

**两条轴正交**：改颜色只碰 `presets.ts`；换圆角/密度/字号只碰 `:root` 那 63 个变量 + `DIMENSIONS`。组件零改动。

### 一次主题切换发生了什么

1. `mode` → `effective`（`system` 在这里被解析成 `light`/`dark`）
2. `documentElement.dataset.theme = 'dark'` → 命中注入样式表里的 `html[data-theme="dark"]{...}`
3. `documentElement.classList.toggle('dark', preset.isDark)` → 命中**补丁层** `html.dark .xxx`
4. `antdTheme` computed 变化 → `a-config-provider` 换 `algorithm: [darkAlgorithm, pin]`

---

## 三、改动清单

| 文件 | 改动 | 规模 |
|---|---|---|
| `src/theme/presets.ts` | **新增**——唯一颜色真源：2 个预设 × 53 变量 + antd 配置 + CSS 注入函数 + 菜单选项派生 | +415 行 |
| `src/stores/theme.ts` | **重写**——只做「模式 → 预设」的解析与应用，**不含任何色值** | 267 → **140** 行 |
| `src/App.vue` | `:root` 摘掉 53 个颜色变量；`html.dark{}` **整块删除**；只留 63 个尺寸变量 + 2 个首屏兜底 | 341 → **222** 行（−119） |
| `src/components/Sidebar/AccountMenu.vue` | 主题菜单改由 `THEME_OPTIONS` 派生（加主题不用改 UI） | 444 → 438 行 |
| `src/utils/appActions.ts` | `set_theme.mode` 类型由内联联合改为 `ThemeMode` | +1 行 |

### 三个刻意的设计选择

| 选择 | 理由 |
|---|---|
| 选择器用 `html[data-theme="x"]` 而非 `html.dark` | 特异性 (0,1,1) **与原 `html.dark` 完全一致**、且 N 个主题互斥；比 `:root` (0,1,0) 高，因此与 App.vue 静态块的先后顺序无关（顺序无关 = 可证） |
| **保留** `html` 上的 `.dark` 类 | 补丁层按 `html.dark` 匹配，动它就得同步改补丁层。等补丁层清空后它只剩语义标记作用 |
| App.vue 留 2 个首屏兜底变量 | JS 注入前第一帧会用到 `--bg-base` / `--text-primary`；留 2 个值使首帧**与改造前逐字节相同**（避免白闪）。这是全局唯一允许的「颜色双写」，已在代码注释里标注 |

### 顺带发现

`src/style.css`（297 行）是 **Vite 脚手架残留、未被任何文件 import 的死文件**，里面还留着 `color-scheme: light dark` 与 `@media (prefers-color-scheme: dark)`
——一张会绕过主题 store 的「系统偏好直连」样式表。现在没生效，但建议删掉以免将来误引。**未擅自删除，等你点头。**

---

## 四、加主题成本：改造前 vs 改造后

| 场景 | 改造前 | 改造后 |
|---|---|---|
| **加第三套配色**（OLED 纯黑 / 高对比） | 改 **8 处**：类型 + `effective` 分支 + `antdTheme` 的 `if` + `classList.toggle` + `html.dark{}` 53 行 + `DARK_SEMANTIC`/pin + `token{}` + 补丁层 | **加 1 个 entry**（`presets.ts` 里 `{ name, label, icon, isDark, vars, antd }`）。菜单项自动出现 |
| 换品牌主色 | 改 3 处（CSS 变量 + 语义常量 + antd seed） | 改 1 处（预设表里 `--primary` 系 + `pin.colorPrimary`） |
| 换风格（圆角/密度/字号） | 已就绪 | 已就绪（不变） |

⚠️ **但「加第三套」目前仍不完整**：补丁层按 `html.dark` 匹配，新主题若是深色系，仍要给它复制补丁。
**补丁层归零才是这个承诺的最后一公里** —— 即下一步（P1）。

---

## 五、验证（四道，全过）

### ① 构造性等价 —— 不是"看起来一样"，是逐条 diff

把改造前的 `App.vue` / `theme.ts`（备份）与新 `presets.ts` 都解析成「名字 → 值」字典再对比：

```
旧 :root 116 变量 | 旧 html.dark 53 变量
新 LIGHT_VARS 53 | 新 DARK_VARS 53
  ✅ LIGHT: 颜色轴变量名 53 个完全一致
  ✅ LIGHT: 全部 53 个色值逐字相同
  ✅ DARK : 颜色轴变量名 53 个完全一致
  ✅ DARK : 全部 53 个色值逐字相同
  ✅ App.vue :root 剩余颜色变量 = 恰好 2 个首屏兜底，且值等于旧亮色基线
  ✅ App.vue :root 保留尺寸/字体变量 63 个（与明暗无关）
  ✅ DIMENSIONS: 11 项完全一致
  ✅ dark pin: 11 项完全一致
  ✅ light pin: 4 项完全一致
  ✅ dark token: 26 项完全一致
  ✅ light token: 12 项完全一致
  ✅ dark components: ['Layout', 'Input', 'Button', 'Typography'] 完全一致
🎯 构造性等价成立：色值 + antd 配置全部逐字相同，零视觉变化
```

> 生成方式：`presets.ts` 的 106 个色值**不是手抄的**，由 `gen_presets.py` 从原 `App.vue` 程序化抽取。

### ② 运行时实测（真实浏览器 · 53 个变量逐个回读）

| 场景 | `data-theme` | `.dark` 类 | 注入样式表 | 变量不符 | `#app` | body 背景 |
|---|---|---|---|---|---|---|
| 浅色冷启动 | `light` | false | 3600 B / 2 blocks | **0 / 53** | 23403 | `rgb(245,247,250)` = `#f5f7fa` ✓ |
| 深色冷启动 | `dark` | true | 3600 B / 2 blocks | **0 / 53** | **23420** | `rgb(20,20,20)` = `#141414` ✓ |
| **运行时切换**（调 `setMode('dark')`，不刷新） | `dark` | true | 同上 | **0 / 53** | 23420 | `rgb(20,20,20)` ✓ |

`#app = 23420` 与改造前深色基线**逐字节相同**；`html` 内联 style 为空（说明没走 `setProperty`，样式表方案生效）。

### ③ 产物核查

```
产物 CSS 里 --bg-base / #141414 / #1f1f1f / #303030 出现次数：0 / 0 / 0 / 0
产物 CSS :root 变量数 65（= 63 尺寸 + 2 首屏兜底）
预设表已进某 JS chunk，含 #73d13d（深色 success）✓
```

深色色值已**完全从静态 CSS 消失**，只剩 JS 里的一张表。

### ④ 类型 + 构建

`npx vue-tsc --noEmit` **EXIT=0**（预设表的 `antd.token` / `components` 用的是 antd 官方 `ThemeConfig` 类型，写错 token 名会被拦下）
`npm run build` → `✓ built in 19.38s` **EXIT=0**

---

## 六、回滚

改造前原件在 `.workbuddy/tmp/p3/archive/before-P5/`（`App.vue`、`theme.ts`）。
回滚 = 还原这两个文件 + 删掉 `src/theme/presets.ts` + 还原 `AccountMenu.vue` / `appActions.ts`（`git checkout`）。
无数据库、无配置、无持久化格式变更（`localStorage.theme_mode` 取值集合未变）。

---

## 七、下一步（P1：清补丁层）

补丁层现状：`App.vue` 里 **70 个选择器项**，按 `html.dark` 匹配、对组件 scoped 样式做 `!important` 覆盖。

- **A 桶（档位压平）已删净**（P4 完成）。
- 剩余 9 项「逐项静态全冗余」经实测（P4b）确认**不是零变化**：删掉会恢复红/绿/橙/蓝语义 —— 属产品决策，等你拍。
- 其余 62 项同理。

**拍板项**：是否接受「深色下恢复语义色」（红/绿/橙/蓝底与彩字回来）以换取补丁层归零？
接受 → 「加第三套主题 = 加 1 项」才真正成立。

## 八、把「发现」也自动化（第 321 轮补）

### 8.1 起因：**改法是收敛的，发现不是**

第 321 轮老板问：「现在是发现一处改一处？没有一个统一的配色方案吗？」

honest 答案分两半：

- **改法早就收敛了** —— 颜色真源只有 `src/theme/presets.ts` 一处，
  改一个 token 三套主题同时生效（第 317 轮订阅页、第 1148 轮 `--text-tertiary` 都是这么修的）。
- **「发现」没有收敛** —— 它靠人眼。当时的真机对比度探针 `cdp-dark-contrast.mjs`
  是**单页**的（`PROBE_URL` 只指一个地址，点名判据只列 subscription / task-config 两页）。
  实际验收面是 **8 路由 × 3 主题 = 24 格，探针实跑 1 格**。

⇒ 剩下 23 格只能等老板截图。这就是「发现一处改一处」的**机制性根因**：
不是配色方案缺失，是**发现机制**缺失。

### 8.2 现在：五条防线，各管一段

| 门禁 | 管什么 | 类型 | 跑在哪 |
|---|---|---|---|
| `check-theme-boot.py` | 生产者侧：主题清单 / 首帧兜底色跨文件一致 | 静态 | CI + `npm run check:py` |
| `check-theme-var-refs.py` | 消费者侧：`var(--x)` 的**名字**是否存在 | 静态 | CI + `check:py` |
| `check-hardcoded-pastel.py` | `background` 里的**硬编码粉彩亮底** | 静态 | CI + `check:py` |
| `check-contrast-matrix-coverage.cjs` | **覆盖面**：router ⊆ 探针清单、`ThemeName` == 探针主题 | 静态 | **CI + `npm run build`** |
| `cdp-contrast-matrix.mjs` | **全路由 × 全主题**真机对比度矩阵 | 真机 | `npm run check:contrast-matrix`（需 dev server + Chrome，刻意**不进 build/CI**） |

后两条是第 321 轮新增。为什么覆盖面要单独一条静态门禁：
探针里那两份清单（`DEFAULT_ROUTES` / `DEFAULT_THEMES`）是 `router/index.ts` 与
`presets.ts` 的**副本**，而副本的失效方式不是报错，是**静默变小** ——
新加一条路由或一套主题、忘了同步 ⇒ 那个组合**天然免检**，门禁照样全绿。
覆盖面门禁把它变成静态可判：**加路由/加主题忘了同步 ⇒ CI 直接红。**

### 8.3 文字层级语义表（此前**没有任何地方写过**）

这张表是 8.1 那个问题的直接产物：token 名对不对是**语法**问题（`check-theme-var-refs` 能管），
但**用哪一级**是**语义**问题，**任何静态检查都判不出来**。没有表，每个人凭感觉选，
缺陷形态就是「看起来对、实测 1.84:1」。

| token | 语义 | 用在哪 | **不要**用在哪 |
|---|---|---|---|
| `--text-primary` | 正文 | 标题、正文、表格主列 | — |
| `--text-secondary` | 次要正文 | 说明文字、次要列、**弱化但需达 AA 的元信息** | 禁用态 |
| `--text-tertiary` | 弱化正文 | **常驻提词**、元信息、辅助说明、单位后缀 | 占位符（那是 `--text-placeholder` 的语义） |
| `--text-disabled` | **仅禁用态** | `:disabled` / `.disabled` 的控件文字；纯装饰（图标、分隔线、色点） | **任何可读正文**，包括"更淡一点的提示" |
| `--text-inverse` | 反色 | 压在 `--success` / `--primary` 等**实色底**上的文字 | 压在半透明或渐变底上（那要用底色算） |

**实证（第 321 轮矩阵首跑抓到）**：`ChatPanel/index.vue` 的 `.input-hint`
（「Enter 发送 · Shift+Enter 换」，一条**常驻**提词）用的是 `--text-disabled`
⇒ 三主题实测 **light 1.84 / dark 2.28 / macaron 1.75**，全部 < 3:1（"看不见"级）。
变量名存在、语法合法、四条既有门禁**全数漏过**（它不是 `background`，也不在订阅页）。
改到 `--text-tertiary` 后：**light 5.25 / dark 4.73 / macaron 4.49** —— 一处改动、三主题同时生效。

### 8.4 加主题 / 换主色的当前成本（第 321 轮复核）

| 场景 | 成本 | 易漏点 |
|---|---|---|
| 加**浅色族**主题 | `presets.ts` 加 1 个 entry（差异表形态，十几行） | ①`ThemeName` union ②`index.html` 首屏兜底（`THEMES`/`DARK_THEMES` + 内联兜底色）③后端 `navigation_tools.py` 的 `ThemeMode` Literal（+ `intent_shortcut.py` 口语映射及其测试）④**让矩阵跑它** ← 现在由覆盖面门禁兜住 |
| 加**深色族**主题 | 同上 | 外加 `App.vue` 的 `html.dark` 补丁层（该层未清空前仍要复制） |
| 换品牌主色 | 改 1 处（预设表 `--primary` 系 + `pin.colorPrimary`） | `pin` 必须与 `vars` 同名语义色**逐字一致** |
| **调色板化**（用户运行时自选 primary） | **大活**，三个硬障碍 | ①`var(--primary)` 实测 **215 处**消费 ②`colorPrimary` 是 antd 的 **seed**，动态改必须同时重建整套派生色阶（否则"你选的蓝 ≠ antd 画的蓝"）③现有 `pin` 是**静态逐字一致**不变量，与"运行时改色"直接冲突，须改成"由选色**计算** pin"的生成式；另需色值持久化 + 调色板组件 |

### 8.5 判定口径：为什么 `< 3:1` 判定、AA 缺口只报告

矩阵判定项只钉 **`< 3:1`**（"看不见"的硬门槛），`3:1 ~ 4.5:1` 的 AA 缺口**打印但不判定**。
理由：本仓存在**数学上到不了 AA** 的已知取舍 —— macaron 的 `--text-tertiary`
语义上必须比 `--text-secondary`（粉底 4.72:1）更浅 ⇒ 它**永远 ≤ 4.72:1**。
把 AA 缺口入判定 ⇒ 永久红 ⇒ 整条门禁会被关掉，那才是最坏结果。
（第 323 轮实测：AA 缺口 84 条，硬缺口 **2 条**且全部有豁免理由。
比第 321 轮的「69 / 5」多了 AA、少了硬缺口 —— 因为 `/settings` `/memory`
从"被豁免的空白页"变成**真体检**（多出 16×3 + 5×3 个节点），
同时头像那 1 条硬缺口被真修掉了。）

### 8.6 第 323 轮闭合（两条死路由 + 头像品牌绿）

- **`/settings` 与 `/memory` 两条路由直接访问是空白页 → 已闭合**
  （老板拍板「做成可访问页面」）。★ 但**根因与当初上报的完全不同** ——
  当初写的是"抽屉组件被当路由用，`open` 无人传"，实测是两个**各自独立**的形态：
  · `/settings`：`Settings.vue` 把 `open` 声明成**必填**（`open: boolean`）⇒ 路由不传
    ⇒ Vue 直接 `[Vue warn] Missing required prop: "open"`，抽屉永远关着。
  · `/memory`：`props.open ?? true` 是**结构性死代码** ——
    `defineProps<{ open?: boolean }>()` 编译出的运行时 prop 类型是 `Boolean`，
    而 Vue 对 Boolean prop 有一条**缺席强制转换**：没传 + 没写默认值 ⇒ 值被写成
    `false`，**不是 `undefined`**。`false ?? true === false`
    ⇒ `MemoryEvolution.vue` 文件头那段「没传 `open` ⇒ 自行打开（页面）」的注释，
    描述的是一个**从未生效的意图**。
  修法（两处一致）：`withDefaults(defineProps<{ open?: boolean }>(), { open: undefined })`
  关掉那条转换 + 「路由模式」分支（自行打开；**关闭时 `router.push('/')` 退回工作台**，
  否则用户会停在一条只剩背景色的空白路由上）。
  ⇒ `MemoryEvolution.vue` 的 `redirect: '/memory'` 也从「跳空白页」变成真链路。
  ⇒ 两条路由不再出现在矩阵的 `[blank]` 未覆盖台账里。
- **`AccountMenu .avatar` 白字压绿 2.27:1 → 已闭合**：渐变 `#52c41a → #389e0d`
  改成 `#2c8409 → #237804`（4.76:1）。**同源四处一起改**（`AccountMenu` 的
  `.avatar` / `.mh-avatar` / `.sp-avatar` 选中态 + `Login.vue` 的 `.ra-avatar`），
  否则同款头像会出现两种绿。矩阵里那条硬缺口豁免已随之删除。
- **顺带修两处 —— 都是上面两条"逼出来"的，不是另起需求**：
  · `MemoryEvolution.vue` 的 `.error-title` 用 `--danger`(#ff4d4f) 当**文字色**，
    压在 `--danger-bg` 浅红底上只有 light 2.97:1 / macaron 2.91:1（<3:1 硬门槛）。
    改用 `--danger-strong`(#cf1322) ⇒ light 5.08:1 / macaron 4.97:1。
    `presets.ts` 对该 token 的注释早就把这条规则写死了（「深档文字**不要**用
    `--danger`，白底仅 3.3:1」）。★ 这处缺陷**此前量不到**：路由是空白页，
    而抽屉（在 `/` 上是关着的）从没被矩阵量过 ⇒ 一变成真体检就暴露了。
  · `cdp-contrast-matrix.mjs` 补 **429 感知**，见 8.7。
- **仍未闭合（新发现，未擅自动）**：
  · `AdDashboardConfig.vue` 的评分卡 `.grade-A` 是**白字压固定亮绿**
    `#52c41a → #73d13d` —— 与头像**同形**，且 `.grade-B/C/D` 三档同样是
    白字压浅渐变（`#faad14→#ffc53d` 等）。复核：这是**另一族**元素
    （评分语义色、后端五档 A~F），不随主题翻，改它等于改评级配色语义
    ⇒ 属品牌/语义决策，另报等拍。
  · `MemoryEvolution.vue` 还有三处把 `--danger` 当**文字色**
    （`.save-error` / `.log-error` / `.logs-error`）。它们压的是白/卡片底
    ≈ **3.3:1**，**过 3:1 硬门槛**、只差 AA ⇒ 按 8.5 的口径
    （「AA 缺口只报告不判定」）**不擅自改**，在此记账。
    ★ 这三处**矩阵量不到**：它们只在「保存失败 / 日志里有失败条目」时渲染，
    demo 身份到不了那个状态。改法同样是 `--danger` → `--danger-strong`。
- 补丁层 70 项（见第七节）。

### 8.7 第 323 轮：矩阵补 **429 感知**（保真缺陷，非功能缺陷）

**症状**：全量跑 8 路由 × 3 主题，`/subscription` 从 **112 节点**掉到 **37 节点**，
并**同时**产出两条红：① 降级态里冒出一条正常态根本不存在的硬缺口
（`p.ant-empty-description`，`rgba(0,0,0,.25)` 压白 = 1.83:1）；
② 豁免表里那条 `当前套餐` **没命中** ⇒ 门禁报「硬缺口豁免表每条都真的命中」FAIL ——
**看着像"白名单过期了"**。

**真因**：矩阵与被测应用**共享同一份限流配额**（后端 `core/middleware/rate_limit.py`，
60 次/分钟、按 IP 共享，连 `/static/*` 都计数）。本轮 `/settings` `/memory`
从"空白页、0 请求"变成"真加载数据"⇒ 全量 24 格的总请求量更大 ⇒ 排在后面的
`/subscription` 吃到 429 ⇒ 页面**降级成错误/空态**，而矩阵只会照常去量那个降级页面。

**判定关键**：`/subscription` **单跑**（独占配额）= 112 节点、7/7 全绿。
⇒ 「单跑绿、连跑红」先怀疑配额，别改业务代码。

**修法**（`scripts/cdp-contrast-matrix.mjs`）：
- 开 `Network` 域收 `429`，并从响应头 `x-ratelimit-reset` 读窗口剩余；
- 每格导航前**清空上一格的 429 记录**（上一页在途请求会晚到 ⇒ 归因错方向）；
- 撞 429 ⇒ **等回血重采**（最多 3 次）；重采仍失败 ⇒ 如实记成
  `kind: 'throttled'`「本轮没体检到」，**不拿降级页面凑结论**；
- 分类顺序上 `throttled` 必须排在 `blank` **之前**（降级页也"文字节点少"，
  会被 `blank` 吞掉 ⇒ 报告会说"页面是空白的"，而真相是"我们被限流了，没测到"）。

**自证**：第 323 轮终局跑里这条退避**真的触发了一次**
（`/settings @ light 撞 429 ⇒ 等 45s 回血重采`）⇒ 不是空跑。
修后 9/9 全绿，`/subscription` 回到 112 节点、豁免命中。
