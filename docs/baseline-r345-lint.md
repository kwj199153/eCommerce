# 批次 1 原始基线：ESLint / mypy（第 345 轮）

> **本文件只放数据与口径，不含任何裁剪后的结论数字。**
> 所有数字都从「原始输出文件」现算 —— 原始文件永久保留在
> `.workbuddy/probes/r345_baseline/`，可用同目录的 `summarize.py` 复算。
>
> 拍板背景：老板裁定「先采集原始基线指标（保留原始数据，接受数据不好看），
> 依据基线结果再确定观测圈定范围，**不直接输出裁剪后结果**」。
> 因此本文按「全量 → 分组 → 建议」三层组织，建议部分明确标注为**待拍板**。

---

## 0. 采集口径（决定了这份数据在什么条件下才成立）

### 0.1 工具与解释器

| 侧 | 工具 | 版本 | 解释器 / 运行时 | 配置来源 |
|---|---|---|---|---|
| 前端 | eslint | **9.39.5** | Node 22.22.2 | 临时 flat config（`frontend/eslint.baseline.config.mjs`，**未入库，采集后删除**） |
| 前端 | @eslint/js | 9.39.5 | — | `js.configs.recommended` |
| 前端 | typescript-eslint | 8.71.0 | — | `tseslint.configs.recommended`（**非** type-checked，理由见 §0.3） |
| 前端 | eslint-plugin-vue | 10.11.1 | — | `pluginVue.configs['flat/recommended']` |
| 前端 | globals | 17.12.0 | — | 补 browser + node 全局 |
| 后端 | mypy | **2.3.1** | `backend/.venv` = **CPython 3.12.14** | `backend/pyproject.toml` 的 `[tool.mypy]` |

★ 与 CI 的口径差异（如实登记，避免「本地全绿推不出 CI 全绿」）：

- mypy 装的版本是 **2.3.1**，而 `requirements-dev.txt` 写的是 `mypy>=1.11`
  —— 2.x 与 1.x 的默认行为有差异，落地时应把 `requirements-dev.txt` 的约束写实。
- CI 的后端解释器是 **3.12**（`PYTHON_VERSION: "3.12"`），本地 venv 也是 3.12.14 ⇒ **同口径**。

### 0.2 有没有偷偷裁剪规则？

**没有。** 前端用的是三个官方 recommended 全集的并集，未手工 off 任何规则。
唯一一处「补环境」是配置 globals（browser + node），理由写在配置注释里：
不配的话 `no-undef` 会把 `window`/`document`/`process` 全报成未定义，
这些报错**无法区分「真未定义」与「本该是全局」**，数据会失去信息量。
配置文件全文可复核（`frontend/eslint.baseline.config.mjs`，采集完已删除，内容见附录 B）。

### 0.3 两处显式的口径选择（不是裁剪，是选边）

1. **typescript-eslint 用 `recommended` 而非 `recommendedTypeChecked`。**
   后者需要 `parserOptions.project` 指向 tsconfig，会与前端的 `vue-tsc` 类型检查大面积重叠，
   且耗时数倍。本轮的判断是：**先拿非类型感知集当第一档**，type-checked 单独作为下一轮候选。
2. **`scripts/*.cjs` 与 `src/**` 分开统计。**
   `scripts/` 下 37 个门禁脚本是 CommonJS，`require()` 在里面**完全合法**；
   混在一起统计会让 `no-require-imports` 看起来问题很大（112 条），实际是口径假象。

---

## 1. 前端 ESLint 原始基线（全量，未裁剪）

### 1.1 总量

| 指标 | 数值 |
|---|---|
| 扫描文件 | **320** |
| 问题总数 | **8116** |
| ├─ error | **950** |
| └─ warning | **7166** |
| 可自动修（`fix` 非空） | **6286** |
| 有问题的文件 | **189 / 320（59%）** |
| 命中规则种类 | **22** |
| 配置生效规则总数 | **204** |
| **当前零违规的规则** | **183**（棘轮第一档候选） |

★ **没有文件解析失败** —— 320 个文件全部解析成功，数字无缺口。
（第一版统计脚本把 `Unused eslint-disable directive` 误判成 parse error，
已修正：真正的解析失败带 `fatal: true`，而那条消息只是 `ruleId` 为 null。）

### 1.2 按文件域拆分

| 域 | error | warning |
|---|---|---|
| `src/`（业务源码 Vue/TS） | **808** | **7165** |
| `scripts/`（.cjs 门禁 / .mjs 探针） | **142** | 1 |
| `<root(配置)>` | 0 | 0 |
| **合计** | **950** | **7166** |

### 1.3 按规则分解（全量，Top 22）

| # | 规则 | 总数 | error | warning |
|---|---|---|---|---|
| 1 | `vue/max-attributes-per-line` | 2607 | 0 | 2607 |
| 2 | `vue/singleline-html-element-content-newline` | 2522 | 0 | 2522 |
| 3 | `vue/html-indent` | 1529 | 0 | 1529 |
| 4 | `@typescript-eslint/no-explicit-any` | 689 | **689** | 0 |
| 5 | `vue/attributes-order` | 154 | 0 | 154 |
| 6 | `vue/html-self-closing` | 132 | 0 | 132 |
| 7 | `@typescript-eslint/no-require-imports` | 112 | **112** | 0 |
| 8 | `@typescript-eslint/no-unused-vars` | 103 | **103** | 0 |
| 9 | `vue/multiline-html-element-content-newline` | 83 | 0 | 83 |
| 10 | `vue/attribute-hyphenation` | 77 | 0 | 77 |
| 11 | `vue/v-on-event-hyphenation` | 31 | 0 | 31 |
| 12 | `no-undef` | 13 | **13** | 0 |
| 13 | `no-empty` | 12 | **12** | 0 |
| 14 | `vue/html-closing-bracket-spacing` | 10 | 0 | 10 |
| 15 | `no-case-declarations` | 9 | **9** | 0 |
| 16 | `vue/first-attribute-linebreak` | 9 | 0 | 9 |
| 17 | `vue/no-v-html` | 8 | 0 | 8 |
| 18 | `vue/multi-word-component-names` | 7 | **7** | 0 |
| 19 | `no-useless-escape` | 4 | **4** | 0 |
| 20 | `vue/html-closing-bracket-newline` | 3 | 0 | 3 |
| 21 | `<no-rule>`（未使用的 eslint-disable 指令） | 1 | 0 | 1 |
| 22 | `@typescript-eslint/no-unused-expressions` | 1 | **1** | 0 |

**读这张表要注意三件事**：

1. **前 3 条 vue 格式规则合占 6658 条（82%），全是 warning、全可自动修** ——
   它们**不是质量信号**，只是「没跑过 formatter」。跑一次 `--fix` 即可清掉绝大部分。
2. **`no-explicit-any` 689 条占 src error 的 85%** —— 这是存量风格债，
   逐条收敛成本极高（要逐个判真实类型），**不适合当棘轮第一档**。
3. **`no-require-imports` 112 条全在 `scripts/`** —— `.cjs` 门禁脚本用 `require()` 是合法的。
   正确处置是**给 scripts 域单独配置**（关掉这条），这不是"裁剪规则"，是"口径正确"。

### 1.4 error 按「域 × 规则」分解（只看 error）

| 域 | 规则 | error |
|---|---|---|
| `src` | `@typescript-eslint/no-explicit-any` | **689** |
| `scripts` | `@typescript-eslint/no-require-imports` | **112** |
| `src` | `@typescript-eslint/no-unused-vars` | 77 |
| `scripts` | `@typescript-eslint/no-unused-vars` | 26 |
| `src` | `no-empty` | 12 |
| `src` | `no-undef` | 12 |
| `src` | `no-case-declarations` | 9 |
| `src` | `vue/multi-word-component-names` | 7 |
| `scripts` | `no-useless-escape` | 3 |
| `scripts` | `no-undef` | 1 |
| `src` | `@typescript-eslint/no-unused-expressions` | 1 |
| `src` | `no-useless-escape` | 1 |

### 1.5 error 最密集的文件（Top 12）

| error | 文件 |
|---|---|
| 60 | `src/mock/toolExecutors.ts` |
| 36 | `src/components/KnowledgeBase/ReviewLibrary.vue` |
| 29 | `src/views/Workspace.vue` |
| 26 | `src/components/ChatPanel/results/conversation/ReviewReportCard.vue` |
| 24 | `src/views/Settings.vue` |
| 18 | `src/components/ChatPanel/results/AIGCMediaResult.vue` |
| 17 | `src/components/ChatPanel/results/BlueOceanResult.vue` |
| 17 | `src/utils/toolResultAdapters.ts` |
| 15 | `src/components/TaskConfigPanel/configs/ProfitConfig.vue` |
| 15 | `src/composables/chat/resultSummary.ts` |
| 13 | `src/components/ChatPanel/results/DescriptionGenerator.vue` |
| 13 | `src/stores/skills.ts` |

### 1.6 两条需要单独交代的明细

**① `no-undef` 13 条 = 12 条假阳性 + 1 条待查**

- 12 条是 `'EventListener' is not defined`，出现在
  `src/views/Workspace.vue`（10 处）与 `src/components/ChatPanel/index.vue`（2 处），
  形态统一为 `window.addEventListener('x', handler as EventListener)`。
  **这是 TS 类型位置**，`no-undef` 不做类型解析 ⇒ 假阳性。
  ★ 这正是 typescript-eslint 官方立场：**TS 项目里应当关闭 `no-undef`**（TS 编译器已覆盖该检查）。
  落地时必须关 —— 这不是裁剪，是修正一个**在本技术栈下本就失效**的规则。
- 1 条在 `scripts/cdp-review-desk-drawer-layout-probe.mjs:196`：`'act' is not defined`，
  属 .mjs 探针脚本，需单独看一眼（本轮未定性）。

**② 1 条未使用的 eslint-disable 指令**

`scripts/check-chat-failure-path.cjs:204`：`Unused eslint-disable directive
(no problems were reported from 'no-new-func')` —— 说明那里有一条**已经不需要的豁免注释**。
危害不大，但它是「豁免注释会随代码漂移而失效」的实证。

---

## 2. 后端 mypy 原始基线（全量，未裁剪）

### 2.1 ★★ 先说两条「跑都跑不起来」的阻塞 —— 比错误数更重要

| # | 命令 | 结果 | 根因 |
|---|---|---|---|
| E1 | `mypy .` | **`Duplicate module named "conftest"`（errors prevented further checking）** | `backend/conftest.py` 与 `backend/tests/conftest.py` 同名，且两侧都没有 `__init__.py` ⇒ mypy 无法把它们映射到不同模块名 |
| E2 | `mypy <业务面>`（用 pyproject 里的 `python_version = "3.11"`） | **`numpy/__init__.pyi:737: error: Type statement is only supported in Python 3.12 and greater [syntax]`（errors prevented further checking）** | 配置写 `python_version = "3.11"`，而已装 numpy 的 stub 用了 3.12 的 `type` 语句 |

**E1 的含义**：直接把 `mypy .` 写进 CI 会**立刻红**，且红的原因与代码质量无关。
E1 的三种官方修法（mypy 自己提示的）：`--exclude` 排除其一 / 加 `__init__.py` /
用 `--explicit-package-bases`。

**E2 的含义**：`[tool.mypy] python_version = "3.11"` 与「CI 用 3.12 + 依赖 stub 已按 3.12 写」
**互相矛盾**，在当前配置下 mypy **一个业务字符都检查不到**。
把目标版本改成 3.12 后立刻跑通（下表数据即来自 3.12 口径）。

★ 这两条是「接入前必须先跑基线」这一纪律的直接兑现：**如果不跑基线，
接上去得到的是一条永不绿的门禁，最后必然被人 `--no-verify` 绕过。**

### 2.2 业务面基线（`core modules platforms ai_infra main.py worker.py`，py3.12）

> ## ★★ 第 346 轮就地更正：下表的 **205 / 「ai_infra 29 + core 19」是欠计**
>
> **根因**：mypy 的**检查面积取决于「缓存状态」**，不只是「文件在不在磁盘上」。
> 本次采集的实际顺序是「先跑 py311（abort 于 §2.1 的 E2 numpy stub）→ **复用同一份
> `--cache-dir`** 再跑 py312」。`--python-version` **不参与缓存键**，于是 py312
> 那一跑复用了 py311 留下的中间结果 ⇒ **静默少报**，而且**连汇总行都不打印**
> （退出码仍是 2，所以从输出上看不出异常）。
>
> **四因子隔离实测**（同一 commit、同一 venv、同一命令
> `mypy core modules platforms ai_infra main.py worker.py`）：
>
> | 因子 | 结果 |
> |---|---|
> | `--python-version 3.12` | 299 → 299（**不影响**） |
> | **`--cache-dir`（唯一因子）** | 299 → **205**（`ai_infra/base_agent.py` 的 24 条**整份消失**、汇总行也不打印） |
> | 确定性重跑（`--no-incremental`） | **231** |
>
> **更正后的数字**：
> - 业务面（同一命令、确定性重跑）= **231**；其中 `ai_infra` **54** / `core` **20**；
> - **B-1 的目标集** `mypy core ai_infra`（不夹带 `modules/`）= **74 条 / 18 文件 / 87 源文件**
>   —— 这才是 §4.2 该用的规模数。
>
> **★ 安全边界（别把结论外推）**：目标集 `core ai_infra` 在**五个场景**下恒定 **74**
> —— 全新缓存 / 被 py311 abort 污染的缓存 / 热缓存 / `--no-incremental` / 默认缓存，
> **且每个场景都打印汇总行**。不稳的只是「含 `modules/` 的业务面」。
> ⇒ 「缓存跨口径复用会少报」这条只证明「圈小面」是稳的，**不等于**整份业务面也稳。
>
> 证据文件：`.workbuddy/probes/r346_f1/mypy_b1_deterministic.txt`（74）、
> `mypy_poison_py312.txt`（205，与 r345 原始产物**逐条一致**）、
> `mypy_scoped_cache_test.py`（五场景）、`mypy_factor_isolation.py`（四因子）。

| 指标 | 数值 |
|---|---|
| error 总数 | **205** |
| 涉及文件 | **50** |
| note 行数 | 93 |

按 error code：

| code | 数量 | 这类通常意味着什么 |
|---|---|---|
| `attr-defined` | 35 | 访问了类型上不存在的属性（**可能是真 bug**） |
| `assignment` | 34 | 赋值类型不符（混合：真 bug / 缺标注） |
| `arg-type` | 32 | 传参类型不符（**可能是真 bug**） |
| `union-attr` | 31 | 对「可能为 None」的值取属性（**可能是真 bug**） |
| `var-annotated` | 17 | 无法推断变量类型（**多为缺标注，噪声**） |
| `index` | 12 | 索引类型不匹配 |
| `call-arg` | 11 | 调用参数缺失/多出（**可能是真 bug**） |
| `call-overload` | 9 | 重载签名不匹配 |
| `misc` | 6 | 杂项 |
| `return-value` | 5 | 返回值类型不符 |
| `operator` | 4 | 运算符类型不匹配（**可能是真 bug**） |
| `name-defined` | 4 | 用了未定义的名字（**可能是真 bug**） |
| `override` | 2 | 覆写签名不兼容 |
| `return` | 1 | 缺 return |
| `dict-item` | 1 | 字典项类型不符 |

按顶层目录：`modules` 128 / `ai_infra` 29 / `platforms` 29 / `core` 19。

error 最密集的文件（Top 12）：

| error | 文件 |
|---|---|
| 27 | `modules/trade/service.py` |
| 20 | `modules/assets/seed.py` |
| 15 | `platforms/amazon/client.py` |
| 15 | `ai_infra/rag/hybrid_engine.py` |
| 15 | `modules/amazon_sp/data_sources/mock_source.py` |
| 13 | `modules/billing/router.py` |
| 10 | `modules/product_research/agent_analyzers.py` |
| 7 | `ai_infra/llm/prompt_spec.py` |
| 6 | `ai_infra/llm/dashscope_client.py` |
| 5 | `core/auth/jwt_handler.py` |
| 4 | `modules/listing_generator/schemas.py` |
| 4 | `platforms/amazon/sp_api/products.py` |

### 2.3 全量基线（含 `tests/`、`scripts/`，`--explicit-package-bases`，py3.12）

| 指标 | 数值 |
|---|---|
| error 总数 | **255** |
| 涉及文件 | **67** |

按顶层目录：`modules` 124 / `scripts` 34 / `ai_infra` 29 / `platforms` 29 / `tests` 20 / `core` 19。

`scripts/` 下新增的密集文件：`check_tenant_isolation.py` 12、`seed_knowledge_docs.py` 10。

**★★ 不要用「255 − 205 = 50」推「tests/scripts 贡献 50 条」—— 这是错的。**
两次跑的是**不同口径**：

| | §2.2 业务面 | §2.3 全量 |
|---|---|---|
| 目标 | **显式列表** `core modules platforms ai_infra main.py worker.py` | `.` + `--explicit-package-bases` |
| 包基 | 各目录被当作顶层包 | 全仓以 `backend/` 为包基 |

实测反证：`modules` 在 §2.2 是 **128** 条、在 §2.3 却是 **124** 条 ——
**加了 tests/scripts 反而变少**。这说明包基不同会改变跨包引用的解析结果
（一部分原本解不出的引用在全量模式下变成可解）。
⇒ 两份数字**只能各自内部比较，不能相减**。
（这条是第一版文档里的真实错误，已就地修正 —— 记在此处是因为
「两次口径不同的数字相减」正是 review-principles §4 里点名的形态之一。）

---

## 3. 由基线直接推出的「必做前置修复」（3 条，无争议）

这三条不是"要不要做"的问题，而是**不做则后面全部白做**：

| # | 修什么 | 依据 | 为什么无争议 |
|---|---|---|---|
| **P1** | `[tool.mypy] python_version` 3.11 → **3.12**（或显式 `--python-version 3.12`） | §2.1 E2 | 不改则 mypy **一条业务结果都出不来**。**✔ 第 346 轮已落**（`backend/pyproject.toml`） |
| **P2** | mypy 的目标**必须显式给**（用 `core modules platforms ai_infra main.py worker.py` 这类列表，或 `--explicit-package-bases`） | §2.1 E1 | 不改则 `mypy .` 直接崩在同名 conftest |
| **P3** | ESLint 侧必须**关闭 `no-undef`** | §1.6 ① | TS 项目里该规则本就不生效（官方立场），13 条里 12 条是假阳性 |

---

## 4. 圈定范围：4 档候选（**待拍板**）

判据是「**当前零成本 / 可自动修 / 需人工判断 / 成本过高**」四分，
而不是「规则重不重要」——因为门禁的第一价值是**先立起来且不常红**。

### 4.1 前端 4 档

| 档 | 内容 | 规模 | 为什么这样分 |
|---|---|---|---|
| **F-1** | 183 条**当前零违规**规则开为 error | 0 行代码改动 | 零风险立门禁。**唯一"纯赚"的一档** |
| **F-2** | 3 条 vue 格式规则（6658 条）+ 其余 8 条可自动修 vue 规则 = **11 条** | ✔ **第 348 轮已落**：103 个 `.vue`，**6285 处**（+12646/−4011） | 跑一次 formatter 落一次大提交，之后开为 error。**收益是消除噪声、让真问题显形**（详见 §6） |
| **F-3** | `no-unused-vars` 103 / `no-empty` 12 / `no-case-declarations` 9 / `no-useless-escape` 4 / `multi-word-component-names` 7 / `no-unused-expressions` 1 | **136** | 这些**能真抓 bug**（未使用变量=可能写错、空块=漏实现、case 无块=作用域泄漏），需逐条看 |
| **F-4** | `no-explicit-any` 689 | **689** | 存量风格债，逐条要判真实类型 ⇒ **本轮不建议**（成本高、收益是"风格"不是"正确性"） |

另需**单独处置**（不属于任何档，是口径修正）：
`scripts/` 域关掉 `no-require-imports`（112 条）—— `.cjs` 用 `require()` 合法。

### 4.2 后端 4 档

| 档 | 内容 | 规模 | 说明 |
|---|---|---|---|
| **B-1** | 先修 P1 / P2，然后在 **`core/` + `ai_infra/`** 上开 mypy | **74** ⚠️ | 与 `--select T20` 相同的棘轮思路：**先圈小面**。★ **规模数已按 §2.2 的更正改为 74**（原写 48 = 欠计）。**✔ 第 346 轮已完成并接 CI** |
| **B-2** | 用 `disable_error_code` 关掉 `var-annotated`(17) + `assignment`(34) = 51 条噪声类 | 154 剩余 | 这两类在本仓多为"缺标注"，不是 bug |
| **B-3** | 高价值类优先收敛：`union-attr` 31 / `arg-type` 32 / `attr-defined` 35 / `call-arg` 11 / `operator` 4 / `name-defined` 4 | **117** | 这些**最可能藏真 bug**（None 解引用、参数错位、属性名写错） |
| **B-4** | `tests/` 与 `scripts/` 的 50 条 | 50 | 最后再收 |

★ 后端与前端的关键差异：**前端 F-1 是零成本（183 条规则本来就没违规）；
后端没有对应物** —— mypy 一旦开跑就必然带 205 条红，所以后端**只能从"圈面 + 关噪声码"起步**，
这正是 B-1 / B-2 两个动作的由来。

### 4.3 一个反直觉但重要的建议

**不要先做 F-2（自动修 6286 处）。** 理由：
一次 `--fix` 会改动上百个文件，与手上正在做的组件拆分（`ReviewDeskConfig.vue` 那条线）
**产生大面积冲突**，而它带来的只是"格式统一"。
建议顺序改成：**F-1（零成本）→ 后端 B-1（圈小面）→ 手头重构告一段落 → F-2 → F-3 → B-2/B-3 → F-4**。
★ **第 348 轮**：B-1 与「手头重构告一段落」两格均已落，F-2 即按此顺序执行完毕。

---

## 5. 原始数据文件清单（全部保留，可复算）

目录：`.workbuddy/probes/r345_baseline/`

| 文件 | 内容 |
|---|---|
| `mypy-raw.txt` | `mypy .` 原始输出（E1 阻塞证据） |
| `mypy-biz-raw.txt` | 业务面 + pyproject 的 `python_version=3.11`（E2 阻塞证据） |
| `mypy-biz-py312-raw.txt` | **业务面 + py312 ⇒ 205 error（§2.2 的主数据）** |
| （第 346 轮新增）| `r346_f1/mypy_b1_deterministic.txt`（B-1 目标集 **74**）、`mypy_poison_py312.txt`（205 的复现 → 证明是欠计）、`mypy_after_broad.txt`（改后 157，新增 0） |
| `mypy-all-epb-raw.txt` | 全量 + `--explicit-package-bases` + py311（仍 E2 阻塞） |
| `mypy-all-py312-raw.txt` | **全量 + epb + py312 ⇒ 255 error（§2.3）** |
| `eslint-raw.json` | **ESLint 全量 JSON 结果（6.3 MB，§1 的唯一数据源）** |
| `eslint-print-config.json` | `--print-config src/main.ts` 的最终配置（用于算「零违规规则」名单） |
| `summarize.py` | 统计脚本（本文件所有数字都由它现算，禁手写） |
| `summary.json` | 结构化汇总（机读） |
| `summary.txt` | 汇总的人读输出 |

复算方式：

```bash
cd /d/ai/eCommerce
./backend/.venv/Scripts/python.exe .workbuddy/probes/r345_baseline/summarize.py
```

---

## 6. 第 348 轮：F-2 落地记录（自动修 + 棘轮收紧）

### 6.1 口径更正：「3 条 / 6286 处」→「11 条 / 6285 处」

§4.1 写的「3 条 vue 格式规则（6658 条）+ 其余可修项 = 约 6286 处」，
第 348 轮实测：**6285 处是由 11 条规则的可自动修条数构成的**，不只 3 条。

| 规则 | 总条数 | 可自动修 | 涉及文件 |
|---|---:|---:|---:|
| `vue/max-attributes-per-line` | 2607 | 1735 | 102 |
| `vue/singleline-html-element-content-newline` | 2522 | 2522 | 89 |
| `vue/html-indent` | 1529 | 1529 | 17 |
| **3 条主体小计** | **6658** | **5786** | — |
| `vue/attributes-order` | 154 | 154 | 46 |
| `vue/html-self-closing` | 132 | 132 | 43 |
| `vue/multiline-html-element-content-newline` | 83 | 83 | 21 |
| `vue/attribute-hyphenation` | 77 | 77 | 34 |
| `vue/v-on-event-hyphenation` | 31 | 31 | 9 |
| `vue/html-closing-bracket-spacing` | 10 | 10 | 4 |
| `vue/first-attribute-linebreak` | 9 | 9 | 5 |
| `vue/html-closing-bracket-newline` | 3 | 3 | 2 |
| **合计** | **7157** | **6285** | **103** |

### 6.2 一个反直觉的实测事实（★ 纪律）

初轮 JSON 统计里 `vue/max-attributes-per-line` 有 **872 条（2607−1735）没有 `fix` 字段**，
看上去「不可自动修」。**这个判断是错的** —— 那是 ESLint 的**同位置 fix 冲突去重**
（同一行多个属性时只保留一个 fix）。`--fix` 多轮迭代后 **2607 条全部清零**。

⇒ **判「能不能自动修」不能只看单轮 JSON 的 `fix` 字段**（会低估 872 条），要看 `--fix` 跑完后的残留。

### 6.3 落地结果

| 项 | 前 | 后 |
|---|---:|---:|
| 问题总数（清空欠账口径） | 8117 | **960** |
| 欠账表条数 | 21 | **10** |
| 生效规则集合 | 181 | **192** |
| 改动文件 | — | **103 个 `.vue`**（+12646 / −4011） |
| `eslint . --max-warnings=0` | 0 problem | **0 problem** |

剩余 960 条**全部不可自动修**：`no-explicit-any` 689 / `no-require-imports` 115 /
`no-unused-vars` 103 / `no-undef` 12 / `no-empty` 12 / `no-case-declarations` 9 /
`vue/no-v-html` 8 / `vue/multi-word-component-names` 7 / `no-useless-escape` 4 /
`no-unused-expressions` 1。

### 6.4 棘轮门禁同步（`frontend/scripts/check-eslint-ratchet.cjs`）

棘轮**只增不减**，所以「清空欠账」必须同步更新三张冻结表（属**收紧**方向）：

- `FLOOR_ENFORCED` 181 → **192**（11 条清零规则**入列**，从此不许再关）
- `CEILING_DEBT` 21 → **10**（11 条移出）
- `FLOOR_PER_CLASS` 实测四类**均 +11** ⇒ 162→173 / 177→188 / 175→186 / 175→186
- R4 自检常量同步：`!== 181`→`!== 192`、`!== 21`→`!== 10`

**反向注入自证**（`.workbuddy/probes/r348/revinject_ratchet.py`）：

| 注入 | 期望 | 实测 |
|---|---|---|
| ① `vue/html-indent` 塞回欠账表 | R1+R3 红 | ✔ 红，报出 `vue/html-indent -> main.ts=0 App.vue=0` |
| ② `App.vue` 冻结值抬到 999 | R2 红 | ✔ 红（缩水） |
| ③ 自检数字改成 193 | R4 红 | ✔ 红（自身被改坏） |

三次还原后均回绿 ⇒ **收紧后的门禁有牙齿**（不能靠把新入列规则塞回欠账表回退）。

### 6.5 行尾

103 个改动文件中 39 个 `w/lf`、64 个 `w/mixed` —— 后者是 fixer 插入的 `\n` 落在
原本 CRLF 的 worktree 上所致。`git add` 按 `.gitattributes`（`* text=auto eol=lf`）统一
规范化为 LF ⇒ **blob 不受影响**；三条后端 LF 门禁（`backend/ai_infra/*.py`）与 `.vue` 无关，
不会假红。

### 6.6 附带修复：4 道门禁的锚点改为**免疫空白**（本轮的真实技术债偿还）

F-2 暴露了一个**既有**技术债：4 道门禁用**单行字面量锚点**判源码形态，
自动格式化把开标签拆成多行后，它们一律失配 —— 症状是报「找不到锚点」，
与真实缺陷毫无关系。**不改判据就得回退 6741 条收益**，所以本轮改判据。

| 门禁 | 失败条数 | 修法 |
|---|---:|---|
| `check-skill-view-parity.cjs` | 6 | `readTarget()` 加 `collapseTagWs`（只折叠标签**内部**空白） |
| `check-review-library-view.cjs` | 4 | `menuKeysIn` 支持正则锚点：`'资料库</div>'` → `/资料库\s*<\/div>/` |
| `check-review-chat-entries.cjs` | 2 | `readSrc()` 加 `collapseTagWs`（**只对 `.vue`**，`.ts` 不动） |
| `check-chat-failure-path.cjs` | 1 | L10 正则结尾 `>` → `\s*>`（`\s` 含换行） |

归一化的定义（只折叠**标签内部**）：

```js
s.replace(/<[^>]*>/g, (t) => t.replace(/\s+/g, ' ').replace(/\s+>$/, '>'))
```

★ 为什么**只**折叠标签内部：标签之外的缩进必须保留 —— `check-skill-view-parity` 的
`TPL_END`（`\n<10 空格></template>\n`）正是靠缩进把 `v-else` 兄弟节点的收尾与
行内 `<template>` 的收尾区分开（实测该文件 `</template>` 缩进分布 `{0:1,10:4,14:1,16:1,18:1}`）。
一刀切地 `\s+ → ' '` 会把这个区分抹掉。

★ 为什么 `.ts` 不折叠：`check-review-chat-entries` 的 `readSrc` 也读 `.ts`，
而 TS 里的跨行泛型 `Foo<\n  A,\n  B\n>` 会被 `<[^>]*>` 误伤 ⇒ 按扩展名分流。

**反向注入自证**（`.workbuddy/probes/r348/revinject_gates_ws.py`，5 条）：

| 注入 | 期望判据 | 实测 |
|---|---|---|
| `class="sm-list"` → `sm-listX` | A1 | ✔ 红 |
| `@click="sendToChat"` → `sendToChatX` | R0 | ✔ 红 |
| `:disabled="!detailView.id"` → `…idX` ★专门打被折叠修好的那条锚 | R0「形态变了」 | ✔ 红 |
| `key="reviews"` → `reviewsX` | B0 | ✔ 红 |
| `class="pending-skill-chip"` → `…chipX` | L10 | ✔ 红 |

全部「基线绿 → 注入红 → 报在预期判据 → 还原绿」⇒ **判据没有被归一化成恒真**。

---

## 附录 A：采集步骤（可重放）

```bash
# ---- 后端（mypy 不在 requirements-dev 的已装集合里，需先补）----
cd /d/ai/eCommerce/backend
~/.local/bin/uv.exe pip install --python .venv/Scripts/python.exe "mypy>=1.11"

# E1/E2 证据
./.venv/Scripts/python.exe -m mypy .                                   # -> Duplicate module conftest
./.venv/Scripts/python.exe -m mypy core modules platforms ai_infra main.py worker.py
                                                                       # -> numpy stub syntax（py311）

# 主数据
./.venv/Scripts/python.exe -m mypy core modules platforms ai_infra main.py worker.py \
    --python-version 3.12 > ../.workbuddy/probes/r345_baseline/mypy-biz-py312-raw.txt
./.venv/Scripts/python.exe -m mypy . --explicit-package-bases --python-version 3.12 \
    > ../.workbuddy/probes/r345_baseline/mypy-all-py312-raw.txt

# ---- 前端（不写 package.json / lock）----
cd /d/ai/eCommerce/frontend
npm install --no-save --no-package-lock "eslint@^9" "@eslint/js@^9" \
    typescript-eslint eslint-plugin-vue globals
node node_modules/eslint/bin/eslint.js . --config eslint.baseline.config.mjs \
    -f json -o ../.workbuddy/probes/r345_baseline/eslint-raw.json
node node_modules/eslint/bin/eslint.js --print-config src/main.ts \
    --config eslint.baseline.config.mjs \
    > ../.workbuddy/probes/r345_baseline/eslint-print-config.json
```

★ 采集期间的三个坑（已实录，供下次避坑）：
1. `npm install --no-save` 装的包，会被**后续任何一次 `npm install` 当作 extraneous 清掉**
   ⇒ 必须**一条命令一次装全**，中途不能再装别的。
2. 本仓 `backend/.venv` 是 **uv 建的（没有 pip）**，`python -m pip` 会报 `No module named pip`
   ⇒ 用 `~/.local/bin/uv.exe pip install --python .venv/Scripts/python.exe`。
3. `@eslint/js` 最新版会要求 `eslint@^10` ⇒ 装 ESLint 9 时必须把 `@eslint/js` 也锁 `^9`，
   否则 npm 报 ERESOLVE 冲突（不是装不上的真问题，是版本没对齐）。

## 附录 B：ESLint 基线配置全文（采集后已从仓库删除）

见 §0.1 描述；全文保留在 `.workbuddy/probes/r345_baseline/` 的采集记录中
（本文档提交前，该文件仍在 `frontend/` 下临时存在，采集完成后立即删除，不入库）。

---

*生成方式：全部数字由 `summarize.py` 从 `eslint-raw.json` / `mypy-*-raw.txt` 现算；
未验证项已就地标注（如 §1.6 ② 的 .mjs 探针 no-undef 未定性）。*
