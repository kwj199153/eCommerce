# L3 批次 1 / 批次 2 落地方案（第 344 轮 · 待拍板）

> 背景：老板拍板「方案 1 然后 2，两批都排」。
> 本文只出**方案**，不改业务代码。
> 前置：`docs/review-principles.md` 已按第 2 次复核修正（附录 A 的 L3-3 / L3-4 两条结论被推翻）。

---

## 0. 先说两处结论修正 —— 它决定这两批的**成本量级完全不同**

| 条目 | 第 1 次盘点（错） | 第 2 次实测（对） | 对成本的影响 |
|---|---|---|---|
| L3-3 Trace | 「无 trace 链路」 | `request_id` **已贯通后端全链路**；缺的是「接出去」 | 从「引入 OpenTelemetry」→「把已有 id 接到前端与 worker」，**降一个量级** |
| L3-4 prompt 版本 | 「无版本、不可审计」（估 1–2 天） | `PromptSpec` 的 `version` + `fingerprint` **齐备**、11 个模块真注册；只缺「指纹没人读」 | 1–2 天 → **半天** |

★ 两处**同一个错因**：用**字面量 grep** 判「某能力有没有」。`trace_id` / `prompt_version` 命中 0，
但真实符号叫 `request_id` / `PromptSpec.fingerprint` ⇒ 「符号叫别的名字」被误判成「能力不存在」。
**教训已并入 `review-principles.md` §3.1。**

---

## 1. 批次 1 —— 「补齐写了但从未生效的工程配置」

> **▶ 执行状态（第 346 轮）：前端部分（F-1）已落地并验收通过 —— 逐条对账见 §1.6。**
> §1.1 / §1.2 记录的是**第 344 轮立项时的现状与方案**，保留原文不改 ——
> 落地与方案之间的偏差本身就是证据（§1.6 最后一列），能防止下次照抄一份错的方案。
> 后端部分（B-1）另记。

### 1.1 现状（实测，非推测）

| 项 | 实测结果 |
|---|---|
| 前端 `devDependencies` | 仅 **6 个包**：`@types/markdown-it` / `@types/node` / `@vitejs/plugin-vue` / `typescript` / `vite` / `vue-tsc` ⇒ **无 eslint** |
| 前端 `scripts.lint` | `eslint . --ext .vue,.js,.jsx,.cjs,.mjs,.ts,.tsx,.cts,.mts --fix` ⇒ **两个问题**：① eslint 根本没装（死脚本）② 带 `--fix` ⇒ CI 里只该判、不该改 |
| 前端 eslint 配置 | 无 `eslint.config.*`，无 `.eslintrc*` |
| 后端 mypy 依赖 | `backend/requirements-dev.txt:21` 有 `mypy>=1.11` ✅ |
| 后端 mypy 配置 | `backend/pyproject.toml [tool.mypy]` 宽松档已就绪 ✅（`disallow_untyped_defs=false` / `no_implicit_optional=true` / `strict_equality=true`） |
| 后端 mypy CI | **无对应步骤** ❌ |

⇒ 两条都是**同一个病**：`配置 / 脚本写了，但依赖或 CI 步骤缺失 ⇒ 从未真正执行`。
与本仓已踩过的「`check-*.py` 门禁存在却从未执行」是同一种形态。

### 1.2 改动点

| # | 文件 | 改动 | 备注 |
|---|---|---|---|
| 1 | `frontend/package.json` | devDeps **+3**（`eslint` / `eslint-plugin-vue` / `typescript-eslint`）；`lint` 去掉 `--fix`；**新增 `lint:ci`**（带 `--max-warnings=0`） | 版本以 `npm` 实际解析为准，不手写 |
| 2 | `frontend/eslint.config.js`（新建） | flat config。★ **不用 `flat/recommended` 预设** —— 它一次开上百条必常红；改为**逐条列当前零违规的规则** | 棘轮落点 |
| 3 | `frontend/scripts/check-eslint-ratchet.cjs`（新建，可选加强） | 钉住「error 规则集合只增不减」 | 见 1.4 |
| 4 | `backend/pyproject.toml` | `[tool.mypy]` 补 `disable_error_code = [...]`（mypy 版棘轮） | 棘轮落点 |
| 5 | `.github/workflows/ci.yml` | frontend job：`vue-tsc` 之前加 `npm run lint:ci`；backend job：`Lint` 步骤旁加 `mypy` 步骤 | 两步都要 pin 住命令 |
| 6 | `.github/workflows/ci.yml` 头注 | 更新「ESLint 是死的 / mypy 未接入」那段如实标注 | 该头注现在准确，改完要同步 |

### 1.3 ★ 棘轮怎么设（本批真正的技术难点）

**为什么不能直连全量**：103 个 `.vue` + 后端存量无标注，一次全开必然爆几千条 ⇒ 常红 ⇒
按 `review-principles.md` **原则四**，必然被 `--no-verify` 绕过，反而变成负资产。

**两边的棘轮机制不一样**，这点必须先说清：

| | ruff（现有范式） | ESLint | mypy |
|---|---|---|---|
| 默认语义 | `--select` = **白名单**（只跑我列的） | 默认**全开**（除了关的都跑） | 默认**全开** |
| 棘轮做法 | 天然棘轮，往 `--select` 加项 | 必须**反向**：`rules: {}` 里只列零违规规则为 `error`，其余不列 | 必须**反向**：全开 + `disable_error_code` 关掉当前有错的码 |
| 收紧方式 | `--select` 加一项 | `rules` 里加一条 `"error"` | 从 `disable_error_code` **删**一项 |

**第 1 步必须是跑基线，不能拍脑袋定数字**（这是本方案的硬前置）：

1. 装好依赖 → `npx eslint . --ext ... -f json > baseline.json` → 按规则统计违规数
2. `mypy core modules platforms ai_infra main.py worker.py` → 按错误码统计
3. **只把「当前 0 违规」的规则 / 错误码设为判据**；其余写进 `disable_error_code` / 不列
4. 每清掉一类，收紧一档；**只增不减**

**分母也要圈**：mypy 的检查面 = 传入的文件列表 ⇒ 先只查 `core/` + `ai_infra/`（这两个包最干净、
也最靠近本仓主战场），逐步扩到 `modules/`。ESLint 同理，可用 `ignores` 先排除存量最脏的目录。

### 1.4 验收判据（四条，缺一不可）

1. **门禁在跑**：CI 里确有两个新步骤（可直接 `grep` ci.yml；更稳的是复用前端已有的
   `check-*.*` glob 机制 —— 但这两条不是 `check-*` 文件，需单独断言）
2. **有牙齿**：反向注入 —— 在已圈目录里写一行 `console.log(...)`（ESLint `no-console`）、
   在 `core/` 里写一个 `no_implicit_optional` 违规 ⇒ **CI 必须红**。没做过这步 = 没有门禁。
3. **不得回退**（可选加强，`check-eslint-ratchet.cjs`）：把 `eslint.config.js` 里 `error` 的规则集合、
   与 `pyproject.toml` 里 `disable_error_code` 的项数落成快照 ⇒ 变小即红。
   ★ 这正是「棘轮」这件事本身的门禁 —— 否则棘轮只是口头约定。
4. **不破坏现有流程**：`npm run build` 仍只用 `.cjs`（Dockerfile 的 `node:22-alpine` **没有 python**，
   别把 `.py` 门禁并进 build）；`vue-tsc` 与 `vite build` 不受影响。

### 1.5 风险与取舍

| 风险 | 处置 |
|---|---|
| ESLint 9 flat config 与 `eslint-plugin-vue` / `typescript-eslint` **版本矩阵**不匹配 | `npm ci` 会直接失败 ⇒ 装完立刻 `npm ci` 复跑一次验证 |
| mypy 对 SQLAlchemy / pydantic 噪声大（`plugins = []` 是**刻意**不开） | 基线可能比预期脏 ⇒ 如实收窄圈定范围，不硬凑 |
| 直连全量 ⇒ 常红 ⇒ 被绕过 | 已在 1.3 明确禁止；第 1 步必须跑基线 |

### 1.6 执行记录 · F-1 前端 ESLint 棘轮（第 346 轮 · #1258）

**方案与落地逐条对账**（★ 这正是「方案写了 N 条、落地只做 1 条」的防复发动作）：

| §1.2 条目 | 方案原文 | 实际落地 | 偏差 |
|---|---|---|---|
| 1 | devDeps **+3** | devDeps **+6** | 方案漏了 `@eslint/js` / `globals` / `vue-eslint-parser`。★ 最后一个必须**显式**装 —— 它只是 `eslint-plugin-vue` 的 **peerDependency**，不装则 `npm ci` 直接失败 |
| 2 | `frontend/eslint.config.js` | **`frontend/eslint.config.mjs`** | 仓内其它前端配置一律 `.mjs` ⇒ 跟随仓内约定 |
| 2 | 「逐条列当前零违规的规则为 `error`」 | **只显式 `off` 掉 21 条欠账，其余一条不动** | ★★ 方案方向**是错的**：ESLint 档位**按文件类解析**（同一条规则在 `.ts` / `.vue` / `.cjs` / `.mjs` 上可以不同）⇒ 把「基线里在某文件类是关闭」的规则全局钉成 `error` 会**新开一道闸**（实测冒出 `no-unused-vars` / `prefer-const` 等新 error） |
| 3 | `check-eslint-ratchet.cjs`「可选加强」 | **已做，且是必需件** | 棘轮方向与 ruff **相反**（ruff `--select` 是白名单=天然棘轮；ESLint / mypy 默认全开=黑名单）⇒ 没有这条门禁，棘轮只是口头约定 |
| — | 方案未提 | **`lint` 脚本同时删掉 `--ext`** | ESLint 9 已移除 `--ext`，不删则 `npm run lint` 自身报错 |

**权威口径（最终采用的数字，全部由实测产物现算、禁手写）：**

| 指标 | 值 | 口径 |
|---|---|---|
| `--print-config` 生效规则 | **204** | 基线配置（`recommended` 全集 + browser/node globals） |
| ├ 有违规的规则 | **21** | 8115 条问题（另有 1 条无 `ruleId` 的「多余 eslint-disable」⇒ 8116） |
| ├ 已生效且零违规 | **162** | 档位 `error` 141 + 档位 `warn` 21 |
| └ 基线即关闭 | **21** | 21+162+21 = 204 ✓ |
| `ENFORCED`（四文件类并集里任一 >0） | **181** | 规则全集 206 − `OFF_EVERYWHERE` 25 |
| `CEILING_DEBT`（显式关掉的欠账） | **21** | = 配置导出的 `LEGACY_DEBT_OFF` 条数 |

★ **`warn` 也按失败处理**：那 21 条 `warn` 是「已生效的零违规」（有牙齿的规则），
只判 `error` 会让它们形同不存在 ⇒ 门禁跑 `--max-warnings=0`。
★ 判据**问库本身**（ESLint Node API `calculateConfigForFile`），**不用文本正则抠 config**。

**验收三条（全过）：**
1. `npx eslint .` = **0 problem / 退出码 0**；`--max-warnings=0` 同样 0。
2. **反向注入 13/13 PASS**（R1 生效集合缩水 / R2 逐类条数缩水 / R3 欠账扩张 / R4 门禁自身自检）。
3. **不破坏现有流程**：前端 37 个 `check-*` 门禁全过 + `vite build` 成功 + `npm ci` 一致
   （★ 棘轮门禁文件名匹配既有 `scripts/check-*.*` glob，自动纳入 CI，无需单独加步骤）。

**顺带照出并修掉的两条真实缺陷**（不是本批目标，但正好被本批的「提级」照出来）：
- `frontend/scripts/cdp-review-desk-drawer-layout-probe.mjs:196`：一句**注释里的反引号**
  落在 ``run(`...`)`` 模板字面量内部 ⇒ 模板提前截断 ⇒ 该探针自第 298 轮起**整段死掉**
  （`run()` 一次都没被调用就抛 `ReferenceError`）；且它不在 CI 的 `check-*` glob 里 ⇒ 无人发现。
- `frontend/scripts/check-chat-failure-path.cjs`：挂着 `// eslint-disable-next-line no-new-func`，
  但 `no-new-func` **不在 `eslint:recommended` 里** ⇒ 该指令从写下起就是空转的
  （把「多余的 disable 指令」提为 `error` 后才现形）。

---

### 1.7 执行记录 · B-1 后端 mypy 棘轮（第 346 轮 · #1259）

**方案与落地逐条对账：**

| §4.2 / §3 条目 | 方案原文 | 实际落地 | 偏差 |
|---|---|---|---|
| P1 | `python_version` 3.11 → 3.12 | 已落 | — |
| P2 | 目标**必须显式给** | CI 写死 `mypy core ai_infra` | — |
| B-1 | 在 `core/` + `ai_infra/` 开 mypy（**48** error） | 同上，但真实基线 **74 条 / 18 文件** | ★ **48 是欠计**（见下） |
| — | 方案未提 | CI 还必须解决**第 2 条 blocking**：无参数 `mypy` 撞 `Duplicate module "conftest"`（退出码 2、**一条都没检查**） | 方案只把它当"本地跑不通"，没意识到它会让 CI **永远红或永远假绿** |

**1.7.1 权威口径（数字全部由实测产物现算）**

| 指标 | 值 |
|---|---|
| B-1 目标集基线 | **74 条 / 18 文件 / 87 源文件**（`mypy core ai_infra`） |
| ├ `ai_infra` | **54** |
| └ `core` | **20** |
| 落地后 | **0**（`Success: no issues found in 87 source files`） |
| 按 code | `assignment` 32（内含 **28** 条 implicit-Optional）/ `attr-defined` 14 / `union-attr` 11 / `arg-type` 6 / `return-value` 6 / `misc` 3 / `operator` 1 / `name-defined` 1 |
| 最密集文件 | `ai_infra/base_agent.py` 24 / `rag/hybrid_engine.py` 15 / `llm/prompt_spec.py` 7 / `llm/dashscope_client.py` 6 / `core/auth/jwt_handler.py` 5 / `core/logger.py` 3 |

**1.7.2 ★★ 口径级发现：mypy 的检查面积取决于「缓存状态」，不是「文件在不在磁盘上」**

同一 commit、同一 venv（mypy 2.3.1）、同一命令
`mypy core modules platforms ai_infra main.py worker.py`，仅因 `--cache-dir` 不同：

| 因子 | 结果 |
|---|---|
| `--python-version 3.12` | 299 → 299（不影响） |
| **`--cache-dir`（唯一因子）** | 299 → **205**（`base_agent.py` 的 24 条整份消失、**汇总行也不打印**，退出码仍是 2） |
| `--no-incremental` | **231** |

⇒ `docs/baseline-r345-lint.md` §2.2 的 **205 / 「ai_infra 29 + core 19」是欠计**：
「先跑 py311（abort 于 numpy stub）→ **复用同一份缓存**再跑 py312」，
而 `--python-version` **不参与缓存键**。已在该文档 §2.2 就地更正。

**★ 安全边界（别外推）**：目标集 `core ai_infra` 在**五个场景**下恒定 **74**
（全新缓存 / 被 abort 污染的缓存 / 热缓存 / `--no-incremental` / 默认缓存，**都带汇总行**）；
不稳的只是「含 `modules/` 的业务面」。这条只证明「圈小面」稳，不证明整份业务面稳。

**1.7.3 落地方式（逐条守「不改运行期行为」）**

以**一次性成表**的补丁脚本落地（`(old, new, expect_n)`，写盘后读回复核、**按文件保留行尾**）。
74 条里绝大多数是**纯注解**（补 `Optional` / 补类级注解 / 补 `cast` / 参数类型改 `Mapping`），
另**顺带修掉 2 条真实潜在崩溃**（这是 mypy 真正的价值所在，不是风格）：

1. `ai_infra/base_agent.py`：`(m.content or "").strip()` —— `BaseMessage.content` 的静态类型是
   `str | list[...]`（多模态块），**content 是列表时会抛 `AttributeError: 'list' object has no attribute 'strip'`**。
   改为统一走新增的 `_content_text(content)`（对 `str` 输入与原行为**逐字一致**，对列表取文本块拼接）。
2. `ai_infra/base_agent.py`：`if not last_message.tool_calls` —— `messages[-1]` 的静态类型是全部消息的
   联合，**只有 `AIMessage` 才有 `tool_calls`** ⇒ 拿到非 AI 消息时 AttributeError。
   加 `isinstance` 收窄，且收窄后语义更强：不是 AI 消息 ⇒ 本就没有工具调用 ⇒ respond。

**1.7.4 ★ 落地中踩到的三个坑（都进了护栏，供下次复用）**

| 坑 | 现象 | 处置 |
|---|---|---|
| **锚点缩进整体多 4 空格** | 统计工具的输出格式是 `f"{path}:{lineno}\n    {text}"`，那 **4 空格是它自己加的前缀**；照抄进锚点 ⇒ 18 个文件里 **6 个锚点命中 0 次** | 改成「引号后正文 + 空格数」的**内容锚定**；纠正规则写成「块内引号后统一减 4 格」 |
| **`request: Request = None` 不能直接删 `= None`** | mypy 报的是 implicit-Optional，但删掉后 Python 语法禁止「无默认值形参跟在有默认值后面」⇒ `[syntax] Parameter without a default follows parameter with a default`，**整个文件连 import 都做不到**（mypy 只报 1 条，看着像小事） | 把 `request` **提到**有默认值的形参之前 —— FastAPI 按**类型注解**注入、与顺序无关；同仓 `security_router.forgot_password` 早已这么写（**与既有范式一致**） |
| **`Optional[...]` 会"传染"出 2 条新错** | `TokenData.user_id`（真值来自 `payload.get("sub")`，**确实可能缺失**）如实改成 `Optional[str]` 后，2 处 `get_user_by_id(db, user_id)` 报 arg-type | 用 `... if user_id else None` 把它归并进**原有的**「用户不存在」401（**文案、副作用完全不变**）—— 而不是把类型改回谎话 |

**1.7.5 验收（四条，全过）**

1. `mypy core ai_infra` = **0 error / 退出码 0**（`--no-incremental` 与默认缓存两种口径都验，
   另用**全新缓存目录**模拟 CI，同样 Success）。
2. **业务面全仓零新增**：`mypy core modules platforms ai_infra main.py worker.py`
   改前 **231** → 改后 **157**，逐条 diff **新增 0 条**、消失 65 处（`core/` + `ai_infra/` 全清）。
3. **反向注入自证通过**：往 `core/` 塞一个临时文件（implicit-Optional + union-attr 两条）
   ⇒ 基线绿 → 注入后 `exit=1` 且**红在指定的两条规则上** → 还原回绿（不留残file）。
   ★ 探针自身第一版把 `len(v: str | None)` 断言成 `union-attr`（实际 mypy 报 `arg-type`）⇒ **假红**；
   改成在 `int | str` 上取 `.bit_length()` 才是真 `union-attr`。**这条记下来：反向注入的断言必须
   与被测工具的实际归类一致，否则会把"探针写错"当成"门禁没抓到"。**
4. **不破坏现有流程**：19 个改动模块全部 import 通过；直接相关的 37 个测试文件全绿。

**1.7.6 CI 接线**

- backend job 在 `ruff` 之后、`pytest` 之前新增「类型检查（mypy：棘轮 —— 只查已收敛到零的目录）」，
  `run: mypy core ai_infra`（11 → 12 步）。
- 头注第 28 行的「`mypy：**仍未接入**`」同步改写，并把**两条 blocking** 与
  **基线口径更正到 74** 写进注释 —— 否则下一个人还会照 48 去规划。
- ★ 判据是**退出码**：mypy 报 `errors prevented further checking` 时同样非零 ⇒ 必须当失败看。

---

## 2. 批次 2 —— 「出事后能不能还原当时发生了什么」

### 2A `request_id` 贯通三段

| # | 缺口 | 实测证据 | 改法 | 成本 |
|---|---|---|---|---|
| A | **前端零参与** | `X-Request-ID` / `requestId` 在 `frontend/src` **命中 0** | `frontend/src/api/request.ts` 响应拦截器读 `X-Request-ID`，存进 error 对象 / 状态；失败时界面可显示「报错编号」 | 2–3 h |
| B | **Celery 跨进程断链** | 投递处 `delay()` / `apply_async` 不传 id；`worker.py` + `core/` 侧 **0 命中** | 投任务时带自定义头；worker 侧在任务启动钩子里读出并写回 ContextVar（Celery 原生支持 header 透传） | 4–6 h |
| C | **无分段耗时** | 只有总耗时 `X-Process-Time-Ms`，无 DB / LLM 分段 | 可选：DB 用 SQLAlchemy 事件钩子计时，LLM 在 client 入口计时 | 1–2 天 |

**★ 附带两处「不做就静默失效」的配置**（这类形态本仓踩过多次，必须一起做）：

1. **CORS `expose_headers`**：`main.py` 的 `CORSMiddleware` **没有 `expose_headers`** ⇒
   一旦前端与 API **不同源**，浏览器**不允许 JS 读取** `X-Request-ID` / `X-Process-Time-Ms`。
   **实测澄清**：nginx 同时 serve SPA 与代理 `/api`、Vite 也 proxy `/api` ⇒ **当前两种部署都是同源**，
   CORS 不参与 ⇒ 本地与现网都是绿的，**只有将来改成分离部署（CDN / 独立域名）才静默坏**。
   ⇒ 结论：这是**低成本防御**（加一行），**不是当前阻塞**。
2. **`X-Request-ID` 的透传语义**：后端已支持「上游带了就用上游的」。若前端要表达「用户这一次点击」，
   应**前端生成并发送**；否则后端每次新生成 ⇒ 同一操作的多次重试会拿到不同 id，串不起来。

**判据**：
- A：成本低。CDP 探针里制造一次失败请求，断言错误对象带 `requestId`。
- B：后端 pytest（celery eager 模式）投一个任务，断言 worker 侧 ContextVar 里是**投递时那个 id**。
- ★ **诚实说明**：B 的判据**当前没有现成台架**，要新建（这是本批最花时间的地方，不是改代码本身）。

### 2B prompt 指纹留痕

| # | 缺口 | 实测证据 | 改法 | 成本 |
|---|---|---|---|---|
| 1 | **类型擦除** | `ai_infra/base_agent.py:790` `get_prompt_template(self, name, **kwargs) -> str` ⇒ 把 `RenderedPrompt` 降级成 `str`，**指纹在出口被丢掉** | 返回注解改成 `RenderedPrompt`。★ 它是 `str` 子类 ⇒ **向后兼容，~12 个调用点零改动** | **0.5 h** |
| 2 | **指纹无人记录** | `.fingerprint` 在 `modules/` + `ai_infra/` **0 命中**（除 `prompt_spec.py` 自身） | 在 LLM 调用入口记一条 `prompt_name / version / fingerprint` 进日志（只需一处） | 2–3 h |
| 3 | B 档 DB 覆写层 | `models/` + `alembic/` **无任何相关表** | 可选：新表 + 迁移，用于「不改代码就换提示词」+ 靠 fingerprint 比对标 `stale` | 1–2 天 |

**★ 第 1 条是性价比最高的单点**：改一行返回注解，把「已算好但扔掉」的指纹变成「全程携带」。
`RenderedPrompt` 继承 `str` ⇒ 现有 `system_prompt=self.get_prompt_template("xxx")` 的调用**全都不用改**。

**判据（成本最低、最好做的一条）**：
- **AST 形态门禁**：`get_prompt_template` 的返回注解**不得**是 `str`（用 AST 取 `returns` 的源码形态，
  禁字符串包含 —— 否则注释里的 `-> str` 会骗过判据）。
- 反向注入：把注解改回 `-> str` ⇒ 门禁**必须红**。
- 运行时判据：调一次 LLM 后，日志里出现 `prompt_fingerprint=`。

---

## 3. 与两份清单的对应

| 你的 10 维清单 | 你的 6 类清单 | 本方案 |
|---|---|---|
| 工程质量 & CI/CD | 测试与质量审查 | **批次 1 全部** |
| 可观测性 | 运维 & 部署审查 | **批次 2A** |
| AI Agent 层 | **（6 类里缺这一类）** | **批次 2B** + `review-principles.md` §6.2 补一 |

---

## 4. 待你拍板的四点

1. **批次 1 的第 1 步是「跑基线」，产出真实数字（可能不好看）。**
   要不要先只跑基线、把数字给你看，再决定圈多大？还是一次做完、只给结果？
2. **批次 2A 的 C（分段耗时）成本最高、收益最模糊** —— 我建议**先不做**，只做 A + B。你的意见？
3. **批次 2B 的 B 档（DB 覆写层）**：我倾向**现在不做**（当前提示词都在代码里、也没有「不改代码就换提示词」的需求），
   只做 1 + 2。你的意见？
4. **§6.2 的「补二 触发映射」要不要落成 PR 模板？** 落模板会改所有人提 PR 的流程，
   是**流程变更**而不是代码变更，需要你点头。
