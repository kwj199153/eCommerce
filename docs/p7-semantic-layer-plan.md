# P7「业务语义层收敛」方案清单

> 目标：让「业务含义 → 颜色」的映射**只在一处定义**，同时被 CSS 与 JS 两个运行时读到。
> 前置：P5（presets 唯一真源）、P6（深色补丁层清空）已完成。
> 本文只给方案与判据。验收工具：`.workbuddy/tmp/p7/check_semantic.py`。

## 执行状态（2026-09-13 更新）

<strong>已执行：P0 + P1 + P2</strong>（老板拍板「只做 P0+P1，加做 P2」）。交付报告见 **`docs/p7-semantic-converged.html`**。

| 批 | 状态 | 结果 |
|---|---|---|
| P0 地基 | ✅ 完成 | `presets.ts` +13 变量 ×2 态（`--cyan`/`--gold`/`--chart-1..8`/`--rank-1..3`）；新增 `theme/semantic.ts`、`theme/palette.ts` |
| P1 评分/状态映射 | ✅ 完成 | **79 处 / 30 文件** → `SEM.*` 或 `var(--x)` |
| P2 图表/调色板 | ✅ 完成 | **24 处 / 8 文件** → `var(--chart-n)`；4 个 store 色板收敛到 `theme/palette.ts` |
| P3~P7 | ⏸ 未做 | 见 §四「不做清单」的划界 |

**判据变化**：① 语义色系 **182 → 59**（其中 JS 侧 **0**，剩 59 全在 CSS）；④ 图表调色板 42 → 8。

**与原方案的两处修正**
1. **store 分组色板不改成 `var()`** —— 它是**持久化数据**（`createCandidateGroup({color})` 会落库），
   改成变量表达式会把 CSS 字符串写进数据库。改为「抽共享常量 `GROUP_PALETTE`，保持 hex」 →
   同样达成「一处定义」，但**不随主题变**（用户选的红色不该因切深色而改变）。
2. **P1 实测 79 处而非方案估的 47 处** —— 因为把「内联 `style`」「属性绑定」「mock 数据」也按语义归类了。

**顺带发现**：CSS 里有 `var(--success-border, #b7eb8f)` 这类**带兜底的写法**（已接入变量，兜底只是保险），
在扫描里被算成残留，属口径噪声（约 20 处），清理归入 P3。


---

## 一、一页结论

| 问题 | 现状 | P7 后 |
|---|---|---|
| 语义色定义几处？ | **2 处并行**：`presets.ts`（CSS 变量）+ 各组件/store 内写死 hex | **1 处**（`presets.ts`） |
| 改「评分高=绿」要动几处？ | 散在 ~15 个组件，**阈值还不一致**（70 / 75 / 4） | 改 1 处 |
| 深色下语义色正确吗？ | ❌ **JS 侧写死的色值停在浅色档**，与 CSS 侧并存两种绿 | ✅ 两侧同源 |
| 换主题时图表跟不跟？ | ❌ 不跟（图表 color 是写死的 JS 值） | ✅ 自动跟随（实测 SVG 吃 `var()`） |

**一句话**：P5/P6 让「颜色定义」收敛了，但只收敛了 **CSS 那一半**；JS 那一半（图表配置、内联 style、状态映射表）**从未接入**——这是 P7 要补的。

---

## 二、现状实测（2026-09-13）

### 2.1 裸 hex 总量与分类

扫描 `src` 下 161 个文件（排除 `src/theme` 定义层）：

| 类别 | 处数 | 占比 | 归属 |
|---|---:|---:|---|
| ① **语义色系** | **182** | 51.4% | → 应收敛（P7 主战场） |
| ② 中性 / 结构色 | 45 | 12.7% | → 走 `var(--border-*)` / `var(--text-*)` |
| ③ 平台品牌色 | 22 | 6.2% | → 集中成 `PLATFORM_COLORS` |
| ④ 图表调色板 | 42 | 11.9% | → 集中成 `--chart-1..8` 变量 |
| ⑤ 待人工判定 | 63 | 17.8% | → 渐变 / 一次性装饰色，需人工过 |
| **合计** | **354** | 100% | (`rgba()` 另计 69 处) |

另有 **字符串色名 54 处**（`color="blue"` 这类 antd 预设名）。

### 2.2 ① 语义色系的改造形态（182 处）

| 形态 | 处数 | 占比 | 改造手法 |
|---|---:|---:|---|
| CSS 规则（`<style>` 内 `color: #52c41a`） | 59 | 32.4% | 换 `var(--success)` |
| JS·调色板数组（`['#1890ff', '#52c41a', ...]`） | 53 | 29.1% | 换 `var(--chart-n)` |
| **JS·条件返回（`if (score>=75) return '#52c41a'`）** | **38** | **20.9%** | **换 `'var(--success)'`（修视觉 bug）** |
| JS·其他 | 23 | 12.6% | 逐个判定 |
| JS·对象属性（`{ excellent: '#52c41a' }`） | 9 | 4.9% | 换 `'var(--success)'` |

热点文件：`stores/{productLibrary,assetLibrary,candidateLibrary,monitorPool,knowledge}.ts`（调色板数组）、`ChatPanel/results/*`（条件返回）、`TaskConfigPanel/configs/*`（CSS 规则）。

### 2.3 ★ 关键实测一：JS 侧语义色**浅深两档都对不上**

浏览器实测（同一页面，dark 主题，注入两个测试元素对比）：

```
--success 变量 = #73d13d   →  var(--success) 渲染 rgb(115, 209, 61)  ✓ 深色档
内联 style="color:#52c41a" →  实际渲染     rgb(82, 196, 26)         ✗ 停在浅色档
```

即：**同一屏上同时存在两种绿**。四语义色对照表：

| 语义 | JS 写死值 | 浅色档（真源） | 深色档（真源） |
|---|---|---|---|
| 绿 `success` | `#52c41a` | `#389e0d` ❌ | `#73d13d` ❌ |
| 红 `danger` | `#ff4d4f` | `#ff4d4f` ✅ | `#ff7875` ❌ |
| 橙 `warning` | `#faad14` | `#ad6800` ❌ | `#ffc53d` ❌ |
| 蓝 `primary` | `#1890ff` | `#1890ff` ✅ | `#177ddc` ❌ |

**性质**：这不是「不优雅」，是**视觉缺陷**。深色底 `#1f1f1f` 上 `#52c41a` 对比度约 3:1（发虚），深色档 `#73d13d` 正是为对比度调过的；浅色档 `#389e0d` 是 green-8，专供白底文字。

**根因**：JS 侧写的是 **antd 默认色板**（green-6 / gold-6 / blue-6），而项目 CSS 变量用的是**重调过的档位**（green-8 / gold-7）。两套色板并行。

### 2.4 ★ 关键实测二：SVG 能直接吃 `var()` → 图表**不需要 JS 出口**

图表组件是**手写 SVG**（`src/components/charts/LineChart.vue`，`<polyline :stroke="s.color">`），不是 ECharts。

实测两种写法（light 主题，`--success` = `#389e0d`）：

```
presentation attribute： <polyline stroke="var(--success)">  → 计算值 rgb(56, 158, 13)  ✓
内联 CSS 声明：          el.style.stroke = 'var(--success)'  → 计算值 rgb(56, 158, 13)  ✓
```

**两条都生效**。原因是 SVG 2 规范把 presentation attribute 定义为「author-level 中优先级最低的 CSS 声明」，因此 `var()` 会参与变量解析（Chrome/Edge/Firefox 现代版均如此）。

**推论（重要）**：图表、内联 style 这类场景**可以直接传 `'var(--success)'` 字符串**，无需 JS 读值、无需响应式重算、改组件零成本。→ 原方案里的 `useSemanticColors()` 从「主力」降级为「兜底的少数派」。

> ⚠️ 仍必须用 JS 真值（hex）的场景：① 值参与字符串拼接/比较；② 传给 canvas（ECharts 等）；③ 需要做颜色计算（调亮/混合）。

---

## 三、方案设计：双出口同源，CSS 优先

```
                    presets.ts  (vars · 53 × 2  +  --chart-1..8 × 2)
                            │
              ┌─────────────┴─────────────┐
              ↓                           ↓
   CSS 出口（主力 · 已就绪）        JS 出口（兜底 · 新增）
   installThemeStyles()             semanticOf(theme)
   → html[data-theme] → var()       → 仅用于 canvas / 计算 / 拼接
```

**选型原则：能用 `var()` 就用 `var()`** —— 它是唯一「零 JS、自动响应、无重算」的通道。

### 3.1 新增：图表调色板进主题系统（`presets.ts` 各加 8 个变量）

```ts
// LIGHT_VARS 追加
'--chart-1': '#5b8ff9', '--chart-2': '#5ad8a6', '--chart-3': '#f6bd16', '--chart-4': '#e8684a',
'--chart-5': '#9270ca', '--chart-6': '#13c2c2', '--chart-7': '#eb2f96', '--chart-8': '#fa8c16',
// DARK_VARS 追加（深色档整体提亮，解决决策 B）
'--chart-1': '#7db3ff', '--chart-2': '#7ee0c0', '--chart-3': '#ffd666', '--chart-4': '#ff9d7a',
'--chart-5': '#b79bf0', '--chart-6': '#5cdbd3', '--chart-7': '#ff85c0', '--chart-8': '#ffb066',
```

### 3.2 新增模块（兜底用）：`src/theme/semantic.ts`

```ts
import { THEME_PRESETS, type ThemeName } from './presets'

/** JS 侧语义色出口 —— 与 CSS 变量同源（都读 THEME_PRESETS[*].vars） */
export function semanticOf(theme: ThemeName) {
  const v = THEME_PRESETS[theme].vars
  return {
    success: v['--success'], danger: v['--danger'], warning: v['--warning'],
    primary: v['--primary'], purple: v['--purple'],
  }
}
export type SemanticColors = ReturnType<typeof semanticOf>

/** 平台品牌色（品牌色不随主题变；深色下如需提亮在此单列 dark 变体） */
export const PLATFORM_COLORS: Record<string, string> = {
  shopee: '#ee4d2d', amazon: '#ff9900', temu: '#fb7701', lazada: '#0f146d',
  tiktok: '#fe2c55', walmart: '#0071dc', ebay: '#e53238', shein: '#000000',
}
```

### 3.3 配套：`src/composables/useSemanticColors.ts`（仅在需真值处使用）

```ts
import { computed } from 'vue'
import { useThemeStore } from '@/stores/theme'
import { semanticOf } from '@/theme/semantic'

export function useSemanticColors() {
  const theme = useThemeStore()
  return computed(() => semanticOf(theme.effective))
}
```

### 3.4 改造前后对照

```ts
// ❌ 前：写死 + 阈值各写各的（BlueOceanResult 用 70，BuyBox 用 75）
const scoreColor = (s: number) => s >= 75 ? '#52c41a' : s >= 50 ? '#faad14' : '#ff4d4f'

// ✅ 后：变量字符串，自动跟随主题，无需 composable
const scoreColor = (s: number) => s >= 75 ? 'var(--success)' : s >= 50 ? 'var(--warning)' : 'var(--danger)'
```

```html
<!-- ❌ 前 --> <LineChart :series="[{ name:'销售额', color:'#5b8ff9', data }]" />
<!-- ✅ 后 --> <LineChart :series="[{ name:'销售额', color:'var(--chart-1)', data }]" />
```

> ⚠️ **只能用于「最终作为 CSS/SVG 值」的位置**。若该值还要参与 JS 运算或字符串拼接，改用 `useSemanticColors()` 拿真值。

---

## 四、分批清单

按**改造手法**分批（同批可复用同一套替换脚本 / 同一套验证）。

| 批 | 内容 | 处数 | 涉及文件 | 价值 | 风险 | 手法 |
|---|---|---:|---:|---|---|---|
| **P0** | 加 `--chart-1..8` 变量 + 建 `theme/semantic.ts` + 校验脚本 | +16 变量 / +1 文件 | 2 | 地基 | 无 | 纯新增，零业务改动 |
| **P1** | **JS 条件返回 + 对象属性**（评分/状态映射） | **47** | ~18 | ★★★ 修视觉 bug | 低 | 换 `'var(--success)'` |
| **P2** | **调色板类**（JS 数组 53 + 图表 42） | **95** | ~20 | ★★ 图表随主题 | 低 | 换 `var(--chart-n)` |
| **P3** | **CSS 侧语义色**（`<style>` 内 hex）+ JS 其他 | **82** | ~50 | ★★ 防回归 | 中（需逐处判语义） | `var(--x)` |
| **P4** | 中性 / 结构色 | 45 | ~30 | ★ | 中（灰阶需映射到 `--border-*`/`--text-*`） | `var()` |
| **P5** | 平台品牌色集中 | 22 | ~8 | ★ | 低 | `PLATFORM_COLORS` |
| **P6** | 字符串色名 → `colorSemantics` 常量 | 54 | ~20 | ★ | 低 | `COLOR_NEW` / `productTagColor()` |
| **P7** | ⑤ 待人工判定（渐变 / 一次性装饰） | 63 | — | 视情况 | 需人工判定 | 集中到文件顶部常量或保留 |

**合计 408 处**（354 裸 hex + 54 色名）。

### 建议的推进节奏

- **只做 P0 + P1**：拿到 90% 收益——修掉深色下语义色错误这个**真实缺陷**，改动面小（~18 文件）。**推荐先做这两批。**
- **加做 P2**：图表开始跟随主题，且顺带解决「深色下图表偏暗」（`--chart-*` 深色档提亮）。价值明显，风险低。
- **P3 之后**：属于「防未来劣化」，可分批长期做，不做也不影响当前正确性。

---

## 五、每批验收（四道）

1. **静态判据**：`python .workbuddy/tmp/p7/check_semantic.py --strict` → 「① 语义色系」残留 **0**（该批范围内）
2. **运行时两态实测**：注入 `#hex` vs `var(--x)` 对比元素，确认同屏不再出现两种同语义色（P1 批核心验收）
3. **主题切换不刷新**：切深/浅后，图表与内联色**跟随变化**（P2 批）
4. **像素级 A/B**：⚠️ **本批浅色下也会有变化**（见 §6 决策 A），需人工确认观感；深色下应有变化
5. `npm run build`（`vue-tsc && vite build`）→ EXIT=0

---

## 六、需你拍板的 3 个决策点

### 决策 A：浅色下绿会变深，接受吗？
`--success` 浅色档是 `#389e0d`（green-8），而组件现在写 `#52c41a`（green-6）。向变量看齐后，**浅色下所有绿色会变深一档**。
- 选项 1（推荐）：**向变量看齐**——`#389e0d` 是为白底对比度有意选的
- 选项 2：把浅色档 `--success` 改回 `#52c41a`——保持现状观感，但对比度 3.3:1 不达 WCAG AA

### 决策 B：图表调色板深色档怎么定？
§3.1 已给出一组「提亮 1-2 档」的候选值。你可以：
- 选项 1（推荐）：**采用提亮方案**（深色底上 `#f6bd16`、`#5d7092` 对比度确实偏低）
- 选项 2：**深色沿用浅色档**（删掉 `--chart-*` 的深色定义，两份相同）——品牌一致性优先
- 选项 3：你给一组品牌图表色，我按你的填

### 决策 C：平台品牌色深色下是否提亮？
Shopee 橙 `#ee4d2d`、Amazon 橙 `#ff9900` 是品牌色，通常不随主题变。
- 选项 1（推荐）：**不动**，保持品牌还原度
- 选项 2：深色下单列提亮变体

---

## 七、不做清单（明确划界）

- ❌ 不引入 CSS-in-JS（vanilla-extract / styled-components）——现有 CSS 变量够用
- ❌ 不为图表另建主题系统——`--chart-*` 变量 + 现有 `html[data-theme]` 机制即可
- ❌ 不追求「裸 hex 归零」——⑤ 待判定里的渐变、一次性装饰色可保留，但要求**集中在文件顶部**
- ❌ 不为 P7 引入 `useSemanticColors()` 到所有组件——**能用 `var()` 就不用 JS**（§2.4）
- ❌ 不动 `--control-height*`（外观轴独立问题，另议）
- ❌ 不改动 P5/P6 已定的主题机制

---

## 八、回滚

本方案未改任何代码。将来执行时，按批建立检查点：

```bash
git stash create "checkpoint: before P7-Pn"
git update-ref refs/checkpoints/before-p7-pn <sha>
git checkout <sha> -- frontend/src/<file>     # 单文件回滚
```

---

## 附：本轮证据与工具

| 文件 | 内容 |
|---|---|
| `.workbuddy/tmp/p7/check_semantic.py` | 残留校验（`--strict` 可做 CI 门禁，`--allow` 白名单） |
| `.workbuddy/tmp/p7/dark.json` / `light.json` | 深/浅两态 `var()` vs 硬编码对比实测原始输出 |
| `.workbuddy/tmp/p7/svgtest.json` | SVG attribute / style 两种写法对 `var()` 的支持实测 |
| `.workbuddy/tmp/p7/hexmap.json` | 逐文件 × 逐色值 × 分类明细 |
| `docs/p6-patch-layer-removed.html` | P6 补丁层清空的对照报告（前置成果） |
