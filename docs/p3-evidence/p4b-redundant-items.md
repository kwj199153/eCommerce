# P4b：11 个「逐项全冗余」选择器项的探针实测（变体语义验证）

> 承接 P4 收尾的待拍板项。静态分析器 `redundant_items.py` 判定这 11 项「每条颜色声明都与组件同名 token 一致 → 可零变化删」。
> **实测结论：11 项里只有 2 项是真零变化，另外 9 项会「恢复颜色语义」——属 B 桶，与已拍板的「只删 A 桶」口径冲突，故保留。**

---

## 一、静态判定为什么不可信（根因）

`redundant_items.py:80`：

```python
for c in re.findall(r'\.([a-zA-Z][\w-]*)', sels):      # ★ 把声明注册到选择器里的【每一个】类名
    for pr, tk in d.items():
        have[c][pr].add(tk)                            # ★ 且跨【全部文件】聚合
```

两个缺陷叠加：

1. **跨文件按类名聚合**：`.budget-card.suggested .value { color: var(--success) }` 会把 `--success` 记到类名 `value` 名下；
2. **只取 `last_cls` 比对**：补丁项 `.budget-card .value` 取末类名 `value`，一查「`--text-primary` 在不在 `value` 的 token 集合里」——被别的文件里的 `.value` 规则满足了 → **假阳性**。

也就是说：**它只证明了「某个 `.value` 规则用过 `--text-primary`」，完全没证明「补丁没在压变体」**。

而补丁带 `!important`、组件变体规则不带 → 按 CSS 层叠，**`!important` 无条件胜出（与特异性无关）**，变体色被压平。这正是要实测的部分。

---

## 二、实测方法

| 项 | 做法 |
|---|---|
| 探针页 | `views/__P4Probe2.vue`（临时路由 `/__p4b-probe`，**测完已删**） |
| 覆盖 | 10 个**真实组件**渲染：AnomalyDetect / BudgetAlloc / CompetitorAd / BidOptimize / Profit / BlueOcean / SEODiagnostic / CompareGrid / PriceTrack / AdDiagnosis + BlueOceanDetailDrawer |
| 为什么必须真实组件 | 组件样式是 `<style scoped>`（`.action-text[data-v-xxx]`），裸标记不会命中 → 只有真实组件渲染才能触发组件侧规则 |
| 主题 | `localStorage.setItem('theme_mode','dark')` + 重新导航（**只加 `html.dark` class 不行**，antd 仍走浅色） |
| 强制渲染 | `.right-panel` 仅 `currentView==='chat' && !isSecretaryAgent` 时渲染 → 用 `pinia._s.get('agent').setCurrentAgent(非店秘书)` 切到 `product-research` |
| 两态 | **逐项摘除**：遍历所有 `selectorText` 含 `html.dark` 且 `cssText` 含 `!important` 的规则（本次 6 条），对目标项执行 `rule.selectorText = 去掉该项的重建串` → 测量 → 还原。可精确归因到单项 |
| 采集 | `getComputedStyle` 的 `color` / `backgroundColor` / `borderTopColor` … |

---

## 三、实测结果（深色，19 个采集点 / 17 个有效）

| 补丁项 | 目标元素 | S1（现状） | 摘除该项后 | 判定 |
|---|---|---|---|---|
| `.anomaly-card` | `.anomaly-card.severity-high` 边框 | `rgb(48,48,48)` | `rgba(255,77,79,.45)` | **变化** |
| `.anomaly-card` | 同上 底色 | `rgb(31,31,31)` | `rgba(0,0,0,0)` | **变化** |
| `.action-text` | `.action-text` 文字 | `rgba(255,255,255,.92)` | `rgb(23,125,220)` | **变化** |
| `.budget-card .value` | `.budget-card.suggested .value` | `rgba(255,255,255,.92)` | `rgb(115,209,61)` | **变化** |
| `.budget-card .value` | `.budget-card.current .value`（对照） | `rgba(255,255,255,.92)` | `rgba(255,255,255,.92)` | 零变化 |
| `.dkpi-val` | `.dkpi-val.roi-mid`（ROI 语义类） | `rgba(255,255,255,.92)` | `rgb(255,197,61)` | **变化** |
| `.dkpi-val` | `.dkpi-val`（模板内联评分色） | `rgba(255,255,255,.92)` | `rgb(250,173,20)` | **变化** |
| `.metric-value` | `.metric-value.cost`（ProfitResult） | `rgba(255,255,255,.92)` | `rgb(255,120,117)` | **变化** |
| `.metric-value` | `.metric-value.profit`（对照） | `rgb(115,209,61)` | `rgb(115,209,61)` | 零变化 |
| `.metric-value` | `.metric-value.warn`（SEODiagnostic） | `rgba(255,255,255,.92)` | `rgb(255,197,61)` | **变化** |
| `.sov-card .value` | `.sov-card .value` | `rgba(255,255,255,.92)` | `rgb(23,125,220)` | **变化** |
| `.stat-value` | `.stat-excellent .stat-value` | `rgba(255,255,255,.92)` | `rgb(115,209,61)` | **变化** |
| `.stat-value` | `.stat-poor .stat-value` | `rgba(255,255,255,.92)` | `rgb(255,120,117)` | **变化** |
| `.rationale-box h4` | `.rationale-box h4` | `rgba(255,255,255,.65)` | `rgba(255,255,255,.92)` | **变化（变亮一档）** |
| `.rank-num` | `.rank-row.top1 .rank-num`（CompareGrid） | `rgba(255,255,255,.45)` | `rgb(255,197,61)` | **变化** |
| `.rank-num` | `.rank-num`（PriceTrack） | `rgba(255,255,255,.45)` | `rgb(23,125,220)` | **变化** |
| `.rationale-box p` | `.rationale-box p` | `rgba(255,255,255,.45)` | `rgba(255,255,255,.45)` | ✅ 零变化 |

**单项结论**

| # | 补丁项 | 变体证据 | 结论 |
|---|---|---|---|
| 1 | `.workspace-container .right-panel` | 组件 `.right-panel` 三属性同 token；实测 6 属性全等 | ✅ **零变化，可删** |
| 2 | `.anomaly-card` | `.severity-high/medium/low { border-color: var(--danger-border-strong/orange-border/border-strong) }` 被压 | ❌ 保留 |
| 3 | `.action-text` | `.action-row .action-text { color: var(--primary) }` 被压 | ❌ 保留 |
| 4 | `.budget-card .value` | `.budget-card.suggested .value { color: var(--success) }` 被压 | ❌ 保留 |
| 5 | `.dkpi-val` | `.roi-high/mid/low` + 模板内联 `:style="{color: getScoreColor()}"` 双双被压 | ❌ 保留 |
| 6 | `.metric-value` | ProfitResult `.cost/.profit`、SEODiagnostic `.ok/.warn/.bad` 被压 | ❌ 保留 |
| 7 | `.sov-card .value` | 组件 `.sov-card .value { color: var(--primary) }` 被压 | ❌ 保留 |
| 8 | `.stat-value` | BlueOcean `.stat-excellent/medium/poor/saved`、SEO `.positive/.negative`、CandidateLibrary `.blue/orange/green/gray` 等被压 | ❌ 保留 |
| 9 | `.rank-num` | CompareGrid `.rank-row.top1/.top3`、PriceTrack `.rank-num { color: var(--primary) }` 被压 | ❌ 保留 |
| 10 | `.rationale-box h4` | **反向覆盖**：删掉它，泛化项 `[class*="-result"] h4` 会接管 → 由次级 `.65` 跳到主级 `.92`（**变亮**） | ❌ 保留 |
| 11 | `.rationale-box p` | 组件 `.rationale-box p { color: var(--text-tertiary) }` 同 token，且泛化项不含 `p` | ✅ **零变化，可删** |

**合计：11 项中 2 项真零变化，9 项会改变深色渲染结果。**

> 三个「零变化」的对照点（`.budget-card.current .value` / `.metric-value.profit` / `.anomaly-card` 之外的基例）恰好证明探针有效：它们该不变就不变。
> 其中 `.metric-value.profit` 有意思——组件写的是 `var(--success) !important`，特异性 `(0,3,0)` 高于补丁 `(0,2,1)`，所以补丁本来也压不住它。

---

## 四、落盘与验证

**删除 2 项**（`drop_items2.py`，备份 `archive/App.vue.before-P4b-drop`）：

- `html.dark .workspace-container .right-panel`
- `html.dark .rationale-box p`

| 校验 | 结果 |
|---|---|
| 干跑 | 删 2 项 / 整条删除 0 条 / 保留 70 项 / 未命中目标 0 |
| 行尾 | CRLF 341 / 独 LF 0（**未被 Edit 污染**） |
| 语法 | 补丁段花括号 10/10 平衡 |
| 残留 | `grep workspace-container .right-panel` / `rationale-box p` 无残留；其余项完好 |
| **回归实测** | 重跑同一套探针：**S1 与删除前 19/19 项完全一致** ✅ |
| `.right-panel` 回归 | 删除前/后 6 属性全等，`foundRule` 1 → 0 ✅ |
| 构建 | `npm run build` → `✓ built in 17.53s`，EXIT=0 ✅ |

**补丁段规模：选择器项 72 → 70。**

---

## 五、剩余补丁层现状（70 项）

| 类别 | 数量 | 处置 |
|---|---|---|
| B 桶（语义色被中性化） | ~21 | 按拍板**保留** |
| C 桶（深色专属底/边） | ~23 | 按拍板**保留** |
| 上述 9 个「伪冗余」项 | 9 | 本次实测**确认保留** |
| antd 运行时类（`.ant-card` / `.ant-layout-sider`） | 5 | **正确保留，不可动** |
| 结构/变量定义块（`html.dark` / `body` / `#app` / 滚动条 / `.section-card`） | 6 | 保留 |

---

## 六、方法论沉淀

1. **逐项冗余判定必须验证「变体语义」**，不能只比对基选择器的 token —— 补丁的 `!important` 会无条件压掉组件变体（`.xxx.cost` / `.severity-high` / 内联 `:style`）。
2. **反向覆盖也要查**：`.rationale-box h4` 删掉后会被更泛化的 `[class*="-result"] h4` 接管，文字**变亮**而非不变 —— 只测「组件同名规则」会漏掉这类。
3. **可复用实测手法**：`rule.selectorText = 去掉目标项的重建串` → 测量 → 还原，可在**一次页面会话内**逐项归因，不必逐项重新构建页面。
4. 探针页的组件必须**真实渲染**，scoped 样式才会生效；`class*=` 归一化选择器与 `:deep()` 都不受 scoped 约束，但普通类名受。
