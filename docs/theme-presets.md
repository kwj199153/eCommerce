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
