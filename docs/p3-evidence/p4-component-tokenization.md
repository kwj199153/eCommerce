# P4：② 组件侧补 token 写法 + 深色补丁层再收缩

> 承接 P3 拍板：**只删「档位压平」21 条**（实删 26 个选择器项）+ **组件侧补 token 写法，现在就做**。
> 本轮全部改动均以「浅色模式色值解算比对」+「深色模式 CSSOM 两态实测」双证。

---

## 一、组件侧 token 化：17 处颜色替换（8 文件）

### 1.1 新增主题 token（App.vue，2 组 6 行）

品牌粉此前在 `BulletGenerator` / `PainPointResult` 里散落 7 次硬编码，本轮收敛为一组主题变量：

| token | 浅色（= 原字面量，零变化） | 深色（本轮新增） |
|---|---|---|
| `--accent-pink` | `#f5576c` | `#ff7a90` |
| `--accent-pink-2` | `#f093fb` | `#f093fb` |
| `--accent-pink-soft` | `rgba(245,87,108,.1)` | `rgba(245,87,108,.18)` |

### 1.2 替换清单

| # | 文件:处 | 原字面量 | 改为 | 性质 |
|---|---|---|---|---|
| 1 | `BulletGenerator.vue` `.result-header` 渐变 | `#f093fb…#f5576c` | `var(--accent-pink-2)…var(--accent-pink)` | 品牌色 |
| 2 | `BulletGenerator.vue` `.bullet-card` 左边条 | `#f5576c` | `var(--accent-pink)` | 品牌色 |
| 3-4 | `BulletGenerator.vue` 两处 `:focus-within` 边+光圈 | `#f5576c` / `rgba(245,87,108,.1)` | `var(--accent-pink)` / `var(--accent-pink-soft)` | 品牌色 |
| 5 | `BulletGenerator.vue` `.bullet-number` 序号球 | `#f5576c` | `var(--accent-pink)` | 品牌色 |
| 6 | `BulletGenerator.vue` `.item-value.primary` | `#f5576c` | `var(--accent-pink)` | **补丁层阻塞项** |
| 7 | `PainPointResult.vue` 头部渐变 | 同 #1 | 同 #1 | 品牌色（同源） |
| 8 | `BlueOceanResult.vue` `.rating-star.warn` | `#fa541c` | `var(--orange-strong)` | 可读性改善 |
| 9 | `BlueOceanResult.vue` `.hc-value.warn` | `#fa541c` | `var(--orange-strong)` | 同文件 `.variation-many` 早已用此 token |
| 10 | `styles/popup.css` `.drow` 分隔线 | `#f7f7f7` | `var(--border-base)` | **★ 真 bug** |
| 11 | `styles/popup.css` `.drow b.warn` | `#fa541c` | `var(--orange-strong)` | 可读性改善 |
| 12 | `AdDiagnosisResult.vue` `.metric-card.status-warning` 底 | `#fffbeb` | `var(--warning-bg)` | **补丁层阻塞项** |
| 13 | `BuyBoxAnalysisResult.vue` `.factors-section` 顶线 | `#eee` | `var(--border-base)` | **★ 真 bug** |
| 14 | `BuyBoxAnalysisResult.vue` `.practices-box` 底 | `#fcffe6` | `var(--success-bg)` | **补丁层阻塞项** |
| 15 | `ReviewSpyResult.vue` `.intel-box` 底 | `#fcffe6` | `var(--success-bg)` | 同值一致性 |
| 16 | `BuyBoxAnalysisConfig.vue` `.quick-tips` 底+边 | `#fcffe6` / `#d3f261` | `var(--success-bg)` / `var(--success-border)` | 同值一致性 |
| 17 | `ProfitConfig.vue` `.preview-value.warning` | `#fa8c16` | `var(--warning)` | 与 `.positive/.negative/.suggested` 同族 |

**结果**：`diff_now` 的 `LITERAL` 桶 **8 条 → 0 条**（补丁层不再有任何「组件仍写字面量」的项）。

---

## 二、浅色模式色值变化（解算比对，共 19 条）

把新旧文件的所有颜色声明都按 `:root`（浅色）解算成具体色值后逐条 diff：

### 2.1 肉眼不可辨（≤ 7/255，4 条）

| 处 | 旧 → 新 |
|---|---|
| `.drow` 分隔线 | `#f7f7f7` → `#f0f0f0` |
| `.factors-section` 顶线 | `#eeeeee` → `#f0f0f0` |
| `.metric-card.status-warning` 底 | `#fffbeb` → `#fffbe6` |
| App.vue 补丁段（8 条） | 选择器列表缩短，**解析后色值完全一致** |

### 2.2 可见微调（7 条，均已核对语义合理）

| 处 | 旧 → 新 | 说明 |
|---|---|---|
| `.rating-star.warn` / `.hc-value.warn` / `.drow b.warn` | `rgb(250,84,28)` → `rgb(212,107,8)` | 橙红 → 深橙；白底对比度 3.4:1 → **4.5:1**，且与同文件既有 token 统一 |
| `.practices-box` / `.intel-box` / `.quick-tips` 底 | `#fcffe6` → `#f6ffed` | lime-1 → green-1；语义改为「成功色族」 |
| `.quick-tips` 边 | `#d3f261` → `#b7eb8f` | lime-3 → green-3 |
| `.preview-value.warning` | `rgb(250,140,22)` → `rgb(173,104,0)` | 亮橙 → 深金；对比度 2.6:1 → **5.1:1**（原值不达 AA） |

> 这 7 条若老板要求「浅色零变化」，可改为新增专用 token（`--volcano` / `--lime-bg`）保留原值。当前选择是**复用既有 token**，避免新增近似重复的色名。

---

## 三、深色模式实测（CSSOM 两态，探针页真实组件渲染）

用真实组件渲染探针页（`AdDiagnosisResult` / `BuyBoxAnalysisResult` / `BulletGenerator` / `ReviewSpyResult` + popup.css 裸标记），`localStorage.theme_mode='dark'` 生效后取 `getComputedStyle`。

### 3.1 深色 token 实际解析值

| token | 解析值 |
|---|---|
| `--accent-pink` | `#ff7a90` |
| `--accent-pink-soft` | `rgba(245,87,108,.18)` |
| `--orange-strong` | `#ffa940` |
| `--success-bg` | `rgba(82,196,26,.12)` |
| `--border-base` | `#303030` |
| `--warning` | `#ffc53d` |
| `--warning-bg` | `rgba(250,173,20,.12)` |

### 3.2 关键探针结果（S1 = 现状）

| 探针 | 深色实测 | 判定 |
|---|---|---|
| `bg:item-value.primary` | `rgb(255,122,144)` = `--accent-pink` | ✅ 补丁压制已解除，品牌粉生效 |
| `bg:item-value.success/.warning/.info` | `#73d13d` / `#ffc53d` / `#177ddc` | ✅ 语义色全部回来 |
| `buy:practices-box` | `rgba(82,196,26,.12)` | ✅ 成功底生效 |
| `rs:intel-box` | `rgba(82,196,26,.12)` | ✅ |
| `buy:factors-section` 顶线 | `rgb(48,48,48)` = `#303030` | ✅ **原 `#eee` 近白线已修复** |
| `popup:drow b.warn` | `rgb(255,169,64)` = `#ffa940` | ✅ |
| `popup:cost-row.net b` | `rgb(255,197,61)` = `#ffc53d` | ✅ 语义色回来 |
| `ad:metric-card.status-warning` | 仍 `#1f1f1f`（`--bg-elevated`） | ⏸ 补丁项**按拍板保留**（C 桶） |

### 3.3 补丁层残留影响面

**S1（现状）vs S2（把补丁里所有 `!important` 深色规则删掉）**：22 项探针中 **5 项**有差异 ——
`popup:drow` 底、`popup:cost-row` 底、`popup:dkpi-val` 字色、`ad:change.down` 底、`buy:buybox-card` 底。

这 5 项**全部属于老板明确保留的 B/C 桶**（深色专属底 / 语义色被中性化），与拍板一致。

---

## 四、补丁层删除：26 + 7 = 33 个选择器项

| 批次 | 内容 | 项数 |
|---|---|---|
| ① A 桶「档位压平」 | 21 个类名 → 26 个选择器项（`.label` 出现在 5 个块、`.section-title` 2 处…） | **26** |
| ② 组件侧补齐后可删 | `.practices-box` / `.cost-row b` / `.drow b` / `.hc-value` / `.item-value` + 2 个**死选择器**（`.value.primary` / `.value.warning`） | **7** |
| 合计 | 补丁段选择器项 **105 → 72** | **33** |

- 整条规则删除 **0** 条（全是项级摘除）；括号平衡 10/10；CRLF 342 → 343，无行尾污染。
- `.value.primary` / `.value.warning` 经全库模板扫描确认**无任何元素同时具备 `value` + `primary/warning` 类**（`class="item-value primary"` 是 `item-value` + `primary`）→ 从未命中过，属**从未生效的历史错误选择器**。

---

## 五、附带修复的真 bug（3 项）

| # | 位置 | 症状 | 根因 | 修法 |
|---|---|---|---|---|
| 1 | `styles/popup.css` `.drow` | ROI 抽屉每行分隔线在深色下是**近白色亮线** | `border-bottom: 1px solid #f7f7f7` 浅色硬编码 | → `var(--border-base)`（深色 `#303030`） |
| 2 | `BuyBoxAnalysisResult.vue` `.factors-section` | 同上（`#eee`） | `border-top: 1px solid #eee` | → `var(--border-base)` |
| 3 | `AdDiagnosisResult.vue:108` | `a-table` 表格在**任何主题**下都抛 `records.forEach is not a function`，Campaign 健康表恒空 | `<script setup>` 里遗留 `const campaignTableData = (props) => props.data?.campaigns \|\| []`，**遮蔽**了下方 Options API 的同名 `computed` → `:dataSource` 收到函数 | 删除该遗留行，统一走 computed |

> #1 #2 是「浅色硬编码在深色下错」的典型；#3 是**潜伏在所有主题**下的组件 bug（因 Vue 的 `errorHandler` 兜底，控制台外无感，只表现为表格空白）。

---

## 六、口径修正（本轮发现的分析器缺陷）

| 缺陷 | 影响 | 修正 |
|---|---|---|
| 扫描范围只含 `**/*.vue` | `styles/popup.css` 成盲区 → `.cost-row`/`.currency`/`.dkpi-val`/`.drow` 被误判成「组件无该属性声明（NORULE）」 | 纳入 `**/*.css` |
| 组件侧用 `re.match(r'var\(')` | `border-bottom: 1px solid var(--x)` 匹配不到（var 不位于开头）→ 误判为「无声明」 | 改 `re.search` |
| `have` 侧未排除补丁自身 | 补丁的 `html.dark …` 规则被当成「组件已有同 token」→ **63 条假冗余** | 加 `if 'html.dark' in sels: continue` |
| 「类名 × 属性」桶 ≠ 可删粒度 | 一个选择器项常混装「冗余属性 + 必要属性」 | 新增**逐选择器项**判定（要求每一条声明都冗余） |

**修正后真实图景**：`DIFF 51 / TOKEN 18 / MISSING 33 / LITERAL 0`（此前误报为 `DIFF 65 / TOKEN 10 / MISSING 53 / LITERAL 6`）。

---

## 七、待老板拍板 / 后续

### 7.1 候选：11 个「逐项全冗余」的选择器项（可零变化删除）

`.workspace-container .right-panel`、`.anomaly-card`、`.action-text`、`.budget-card .value`、
`.dkpi-val`、`.metric-value`、`.sov-card .value`、`.stat-value`、`.rationale-box h4`、
`.rank-num`、`.rationale-box p`

> ⚠️ 静态判定只保证「同名 token 存在」，**不保证该值不被补丁覆盖变体**（如 `.metric-value.critical` 的语义色正是被补丁压掉的）。
> 因此这 11 项若要删，需先用同款探针跑一遍两态实测再落盘。

### 7.2 仍在库中的残留硬编码（不在补丁层范围，8 处 `#fa8c16`）

`TitleGenerator.vue:616`、`AdDashboardConfig.vue:416`、`KeywordsSection.vue:71`、
`TitleSection.vue:78`、`PitfallsConfig.vue:501`，以及 3 处 JS 内联色
（`MarketShareResult.vue:105`、`MonitorDashboardResult.vue:100`、`CandidateLoaderButton.vue:160`）
+ 4 个 store 的分组色板数组。

### 7.3 补丁层剩余 72 项的结构

- **DIFF 51 条**（B 桶语义色被中性化 + C 桶深色专属底/边）—— 按拍板保留
- **TOKEN 18 条**（真冗余，需逐项核验后才能删）
- **MISSING 33 条**（组件确无该属性声明；含 `ant-card`/`ant-layout-sider` 等 antd 运行时类 5 条，**正确保留**）
