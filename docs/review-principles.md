# 审查原则与执行流程

> 目的：让「审查」这件事**可重复、可举证、可信**。以后每次审查（自审 / 他审 / 上线前）都按本文走。
> 适用：本仓（FastAPI + Vue3 + Agent + 多租户 · 跨境电商 SaaS）。
> 维护：§5 现状快照有变化时必须同步更新，否则本文会变成新的「纸面门禁」。

---

## 0. 这份文档解决什么问题

通用 SaaS 审查清单（10 维 / 80 条）的问题不在内容，而在**分布**：它是「从零建仓」的 checklist，
而本仓在 8/10 个维度上已有真实资产（第 1 次盘点结论见 §5）。照抄它有两个后果：

- 大半工时花在**复述已完成项**上；
- 真正会咬人的形态**全部漏掉** —— 本仓已被咬过、通用清单里没有的，见 §4。

所以本文不给清单，给三样东西：**分层的折法**（§2）、**判定的三问**（§3.1）、**每次审查的固定动作**（§3.2）。

---

## 1. 四条核心原则

**原则一：能自动化的不许进评审会。**
一件事只要有门禁（CI / 测试 / 脚本）在跑，就不要靠人记。评审会的每一分钟只应花在机器判不了的地方。
把已自动化项写进议程 = 把人的注意力浪费在最不需要它的地方。

**原则二：门禁的价值不由「写了」决定，由「红过」决定。**
**没被反向注入验证过的门禁 = 没有门禁。** 一条判据若从未有某次改动能把它打红，
它很可能恒真（fail-open），而非有效。
推论：新增判据必须**当场证明它能红** —— 注入一个缺陷形态 → 观察它转红 → 还原 → 记录齿痕。

**原则三：失明比失效更危险。**
失效会报错，失明会静默变绿。据此：

- 盘点型判据在**盘点数为 0 时必须失败**，不许 `skip`；「读不到」不得退化成「没有问题」。
- **读数抓到了 ≠ 判据会红**：抓到的字段必须**逐条**断言（只断言其中一条 = 其余字段无保护）。
- 判据的**窗口须限定在被测块内**：全文件正则会被他处同形调用旁路满足。

**原则四：阈值只能设「当前已绿」的档。**
门禁一亮红就会被 `--no-verify` 绕过，绕过一次这套体系就废了。
所以新门禁一律走**棘轮**：只圈当前已收敛的规则 / 目录，每收敛一类再收紧一档，**只增不减**。
（本仓 `ruff --select T20`、`npm audit --audit-level=critical`、覆盖率 `fail_under=65` 都是这个范式。）

---

## 2. 三层折法

任何一条审查项，先问它属于哪一层，再决定要不要花时间。

| 层 | 判据 | 处置 |
|---|---|---|
| **L1 已有判据** | CI 里正在跑的门禁 / 测试 | **不进评审会**，跑 CI 就是审 |
| **L2 需人工判断** | 门面原则、领域边界、API 契约、架构取向、取舍 | **评审会的全部议程** |
| **L3 尚无判据** | 重要但机器判不了 / 还没写判据 | **唯一的待办来源** |

---

## 3. 每次审查的固定动作

### 3.1 判定三问（对每一条判据问）

1. **这台机器上有门禁吗？** —— 有 ⇒ 归 L1；没有 ⇒ 进 L3 候选。
2. **这条门禁被反向注入过吗（真红过吗）？** —— 没红过 ⇒ 它现在只是**待验证的门禁**，优先级等于「没有」。
3. **红的时候 FAIL 行指对地方了吗？** —— 指错 ⇒ 是**负资产**（会把归因推给无辜的那一处，比没有更坏）。

★ **补充（第 2 次复核新增）：判定「有没有」也必须用形态判据，禁用字面量 grep。**
  `trace_id` / `prompt_version` 全仓 0 命中，但能力**其实存在** —— 符号叫
  `request_id` / `PromptSpec.fingerprint`。**「符号叫别的名字」与「能力不存在」在 grep 眼里长得一样**，
  而两者处置完全相反（前者不用做、后者要做）。⇒ 判「有没有」须查**符号 → 消费点 → 注册表是否真被填充**，
  按 §3.1 三问走完再下结论。

### 3.2 执行顺序

1. **跑 L1 取证**：全部 `.cjs` / `.py` 门禁 + pytest + `vue-tsc` + build，**留输出**。
   ★ 环境前提：探针须在 `backend/` 下跑（`.env` 相对 CWD）；地址一律写 `127.0.0.1`；
   沙箱批量删除守卫按 turn 累计 >50 文件即拒（跑完才抛 ⇒ 退出码假绿/假红）。
2. **核对 L2 议程**：每次只挑当轮**真正在动**的模块，不追求全覆盖。
3. **重盘 L3**：新出现的「尚无判据」补进待办；已补判据的移出。
4. **结论必须带证据**：每条结论后面跟「哪个命令 / 哪个文件 / 哪一行」。
   **没有可观测判据的结论 = 负资产。**

### 3.3 反面清单（本仓踩过，别再犯）

- 禁「源码字符串包含」当判据（docstring / 注释会骗过 → 假绿）；形态判据走 **AST**，门禁须**剥注释**。
- 禁按文案点 UI 按钮（antd 会在两个 CJK 字之间插空格）；取「可见元素」必须过滤 `display !== 'none'`。
- 禁 `python -c` 跑计数 / 正则脚本（bash 会吃掉 `\s`、`\b` 变退格符）⇒ **一律落文件再跑**。
- 禁无差别 `git show HEAD:f > f`：有未提交改动时会**静默毁整轮**；恢复前先查 `git status --porcelain`。
- 反向注入**不得**用 `git checkout` 还原；改既有文件须**行尾自适应**；写盘用**二进制**。
- 「可再生产物」≠「可删」：删之前先问「**本机现役副本还在吗**」——备份只有在源还在时才是备份。

---

## 4. 通用清单没写、但本仓已被咬过的形态

> 这一节是本文最值钱的部分。审查时逐条对照，**命中就是 L3 候选**。

**租户与鉴权**

- **认证 ≠ 授权**：按租户过滤必须查**归属**；写端点缺 `X-Shop-ID` → 400。
- **条件挂载依赖** `X if config.y else []` ⇒ 门禁**根本没挂**，静态看永远绿。
- **同一判定两份实现** ⇒ 至少一份**永远测不到**；应收敛到唯一真源。
- **归属只能服务端注入**：从请求体**删**字段（pydantic 忽略多余字段 ⇒ 不 422 也不被采纳）。
- **「不存在」与「不属于你」必须同一响应**（含逐字相同文案），否则可枚举 `session_id`。
- **「读判据」不得当「写判据」用**：读口刻意放行演示身份 ⇒ 当写口 = 匿名可改全局共享数据。

**诚实性（最难查，也最伤）**

- 后端**「伪成功」** = 200 + `success:true` + `data.error` ⇒ 只判 `success` 判不出。
- **「后端有端点」≠「前端在用」≠「接上了会渲染」** ⇒ 数**消费点**（变量写入点全集），不是 grep。
- **三态压两态 = 静默洗白**：`?` = unknown 与空串 = clean 必须分开；缺项 / 异常一律 unknown。
- **取不到禁静默退化**：全 0 兜底 = 假数据冒充实测；须显式报错 + 显式写进 prompt。
- 界面文案**字面为真、暗示为假** ⇒ 取证看**数据流走到哪一层**。
- **失败路径必须回写界面状态**，否则所有失败都被转译成「随机失败」。

**门禁自身**

- **读数抓到了 ≠ 判据会红**。
- FAIL 行**带缩进** ⇒ `startswith('FAIL')` 恒不匹配，须 `re.match(r'\s*FAIL\s+')`。
- 门禁钉住库的**私有符号名** = 负资产（升级即 ImportError）⇒ 判据须**问库本身**，禁自算复刻。
- 用例 `import` 被测模块取常量会**替被测行为完成注册** ⇒ 反向注入照旧绿。
- 门禁的**读集**变了 ⇒ 注入台架的**副本树必须跟着复制**（否则基线也红，看着像门禁坏了）。
- 断言前先答「**哪一处改动能把它打红**」；无可观测判据的改动 = 负资产。

**数据**

- **迁移必须幂等**：`--reload` 的 `create_all` 抢先建**新表**却不加列 ⇒ 库里「半新」。
- `json` 列里的中文是 `\uXXXX` 转义存储 ⇒ **禁**用中文 `LIKE` 过滤 json 列。
- seed 是「已有则不覆盖」⇒ 门禁守的是**源码规格表**、缺陷住在**已落库的行**；改规格须 `--resync`。
- `tests/` **直连共享生产库** ⇒ 全量不可复现，只认**单跑绿**。

---

## 5. 本仓 L1 现状快照（2026-10-01 实测）

> **更新 · 第 346 轮**：批次 1 已落地（L3-1 前端 ESLint 棘轮 `4835dea`；L3-2 后端 mypy 棘轮 `5b2df09`）。下表与附录 A 已同步。
>
> **更新 · 第 350 轮**：**按 `review-principles.md` 本身跑了一次全量复审**，结论落
> `docs/reviews/2026-10-01-项目复审与进度归档.md`（§6.2「补三」约定的目录与格式，本轮首次落地）。
> 本节据此同步：门禁数 37 → **38** `.cjs`；附录 A 的 10 条逐条实测重盘 + 新增 6 条（L3-11 ~ L3-16）。
> ★ 本轮另得两条**度量口径**（防下次误判，已写进该报告 §9）：F-2 格式化后 `.vue` 行数**不可跨版本比**；
> 度量脚本**必须排除 `.workbuddy/`**（否则探针留痕把「>800 行文件」从 51 撑到 336）。
>
> **更新 · 第 351 轮**：批次 2 落地（L3-11 门禁注入开口 + **L3-3 trace 三段** + **L3-4 prompt 指纹**）。本节同步：
> 门禁数 38 → **39** `.cjs`（新增 `check-trace-propagation.cjs`）；**注入开口 38 道 / 无开口 1 道**
> （`check-eslint-ratchet.cjs` 是**配置面**例外，不读源码 ⇒ 非缺口）。结论落
> `docs/reviews/2026-10-01-第351轮-批次落地.md`。
>
> **更新 · 第 351 轮（同轮续 · P0 四项）**：同轮再落 **P0-9 法务占位符**（可客观确定的 5/36 + 新门禁
> `tests/test_legal_docs.py`）、**P0-6 SP-API 按店 OAuth**（`modules/amazon_sp/router.py` 6 端点 + 30 用例）、
> **P0-7 B 档 提示词 DB 覆写层**（表 `prompt_versions` + 迁移 `l8d5e2a9c3f6` + 19 用例）、
> **P0-2 PITR**（`scripts/pg_pitr.py` 五子命令 + 端到端恢复演练 + 19 用例）。
> pytest 由 **2450 → 2523**（153 文件）、`mypy core ai_infra` **88 → 89 文件**；
> 分层门禁同步登记 `prompt_versions → PLUGIN`、`wiring.py::MODEL_MODULES` 加 `prompt_versions.db_model`。
>
> **更新 · 第 352 轮**：**法务文本落地**（P0-9 剩余占位符 + 子处理者清单 + 仓库根 `LICENSE`）。本节同步：
> 占位符 **36 → 22**（累计处置 14 项 = r351 5 + 本轮 9：取证回填 6 + 出境三项如实改写）；
> 新增 `docs/legal/subprocessors.md`（7 条子处理者 + 5 项明确不列入 + 4 条复现命令，逐条附代码取证锚点）；
> 仓库根 `LICENSE` 由 `docs/legal/LICENSE` **派生**（剥内部维护者备注）；
> `tests/test_legal_docs.py` **5 → 9** 条（新增 L5 根副本同源 / L6 无维护者备注 / L7 清单锚点须真实存在 /
> L8 对外文本须链接清单）。pytest 由 **2523 → 2527**（仍 153 文件）、`mypy core ai_infra` 仍 **89 文件**；
> 8 组反向注入全红 + 逐字节还原。结论落 `docs/reviews/2026-10-01-第352轮-法务文本落地.md`。
>
> **更新 · 第 353 轮**：**全量复审**（L1 取证 + 反向注入 + P0/L3 逐条重锚）。本节同步：
> 门禁仍 **39 部 `.cjs` + 4 部 `.py`**；**注入开口 38 道 / 无开口 1 道**（本轮独立复验；
> ★ 须注意：r350 的探针只认 `process.env.LITERAL`，认不出 r351 引入的 `pick('NAME')` 动态键
> ⇒ **修正口径后**才得到 38/0/1，沿用旧口径会误报成 26/0/13）；
> pytest **2527 用例 / 153 文件**（delta 0；2523 passed / 1 环境假红 / 3 skipped）、
> `mypy core ai_infra` 仍 **89 文件**；P0 九项重锚 → **已闭合 8**（P0-2 的 PITR / P0-6 / P0-7 B 档
> 均已在 r351 落地，本轮逐个验承载物：`pg_pitr.py`+beat 两条 / `amazon_sp/router.py`+`main.py:641` /
> `modules/prompt_versions/`+迁移 `l8d5e2a9c3f6`）。
> ★ **新增 L3-17**：`backend/scripts/check_tenant_isolation.py` **无任何自动入口**
> （AST 判据复核：4 部后端脚本门禁中仅此 1 部无 pytest 包装、CI 也不跑它 —— **更正 r350 §5
> 「4 部由 pytest 包着跑」的错记，实为 3 部有包装 + 1 部裸奔**）
> \+ **期望值过期**（演示模式那条停在 r177 之前的「演示身份无条件放行」；
> 现行为是「演示店 200 / 真实店 403」，已用探针实证 ⇒ **非真回归**）。
> ★ 另两处旧结论被时间改写：**L3-14 由 1 → 3 个文件**（两条 alembic 迁移也带 `invalid escape sequence`，
> 其中 `e7b2c9d4a1f8_review_reports_library.py:34` 污染**每次 alembic 运行**的输出）；
> **L3-16 的「死表」举证失效**（`amazon_credentials` / `amazon_auth_logs` 已有真实写入者，来自 r351 的 P0-6）。
> 结论落 `docs/reviews/2026-10-01-第353轮-项目复审.md`。
>
> **更新 · 第 354 轮**：批次 3 落地（**P1-1 = L3-17** / **P1-3 = L3-5** / **P2-1 = L3-14**）
> + **P3 复算**。本节同步：
> ① **L3-17 闭合**：`scripts/check_tenant_isolation.py` 的期望改贴第 177 轮口径
> （演示身份只放行演示店 ⇒ 演示店 200 / 真实店 403，**两个方向都测**）+ 补第 182 轮
> **哨兵身份**路径（此前零覆盖）+ 新增 `tests/test_tenant_isolation_gate.py`（**3 条**，
> 两种模式各跑一次）。⇒ 后端脚本门禁由「4 部中 3 部有 pytest 包装」变为 **5 部 5/5**。
> ② **L3-5 闭合**：新增 `scripts/check_openapi_contract.py` + 快照
> `backend/docs/api/openapi.json`（**236 路径 / 151 schema / 579 KiB**，快照本身即交付物）
> + `tests/test_openapi_contract_gate.py`（**8 条**）。
> ★ **实测口径**：契约**只有一根环境敏感轴** —— `VOICE_CLONE_ENABLED`（off 少 8 条
> `/api/v1/voice-clone*` 路径与 5 个 schema）；`AUTH_REQUIRED` / `DEBUG` /
> `METRICS_ENABLED`（`/metrics` 是 `include_in_schema=False`）/ `DEMO_MODE` **无影响**；
> `ENVIRONMENT=production` **测不了**（被 `_enforce_production_safety` 拒启）
> ⇒ 门禁固定 `development` + `VOICE_CLONE_ENABLED=true` 取最大面。
> ★ 固定环境的代价是**其它 env 轴的影响会隐身** ⇒ 门禁带 `--env-axes` 子模式，
> 用子进程把 `AUTH_REQUIRED` 翻一次并断言**逐字节不变**，
> 把「路由不得条件挂载」（r351 前的缺陷形态）钉住。
> ③ **L3-14 闭合**：三处 `r""` 前缀 + **门禁化** `tests/test_no_syntax_warnings.py`
> （**2 条**；判据用 `compile()` 走 CPython 词法分析器，而非 grep 转义表）。
> ④ **P3 复算**：生产源码 >800 行 **51 个** / `def _get_router` **×7** / `def _dump` **×8**
> —— 后两条与 r335/r350/r353 **完全一致**（**未改善**）。
> pytest 由 **2527 → 2542**（153 → **156** 文件，delta = +3 文件 / +15 用例）；
> `mypy core ai_infra` 仍 89 文件。反向注入 **9 组全红**（L3-17/L3-14 共 3 组 + L3-5 共 3 组 + 第 3 批 3 组）
> + 逐字节还原 sha 一致 + 回绿复核。
> ★ **P3 口径敏感（新增，防下次误判）**：「>800 行」在同一份代码上随口径变化 ——
> 计入 `modules/*/seed.py` ⇒ **51**，剔除 seed ⇒ **50**（= r353 记的数），
> 再剔 `frontend/src/mock/` ⇒ **49**。⇒ 报这个数**必须连口径一起报**；
> r353 的「50」与本轮「51」**不是代码变了，是口径不同**。
> 结论落 `docs/reviews/2026-10-01-第354轮-P1-3与P3落地.md`。
>
> **更新 · 第 347 轮**：**核正 pytest 用例数口径** —— 下表原写「11276 用例」是
> **无来源的错记**（全仓 grep 只此一处，且与同类快照 2295/r332 2347 差 4.6 倍）。
> 真实口径见表格下方脚注（**2435 用例 / 148 文件**）。

>
> **更新 · 第 354 轮（第 3 批）**：§8 的「三处未验证」前两条**从推理变成读数**。
> ① **L3-5 门禁在 CI 里从未实跑 → 已实跑，并抓到真缺陷**：
>    用 `git worktree add --detach <tmp> HEAD` 建一份**无 `.env` 的干净检出**（= CI 等价条件），
>    实测 **rc=1** —— `info.title` 本地是 `CrossBorder-AI-SaaS`、无 `.env` 时是 `跨境电商AI SaaS`。
>    根因：`main.py` 的 `FastAPI(title=config.app_name, version=config.app_version)` 把两个
>    config 字段**直接写进 `info`** ⇒ 它们是**第二根 env 敏感轴**；而上一轮的矩阵只比了
>    「有 `.env`」那一档（`.env` 恰好改了 `APP_NAME`）⇒ 整条轴隐身，docstring 里
>    「只有一根轴」的结论一并失效。
>    ⇒ `FORCED_ENV` 补 `APP_NAME`/`APP_VERSION` + `--env-axes` 新增**轴 3**；
>    快照随之重生成，差异**恰好 1 行**。复验（同一 worktree + CI `env:` 段）：
>    `--check` rc=0 / `--env-axes` rc=0 / `pytest` **10 passed**。
> ② **production env 契约 → 静态取证**：`main.py` 里按 config 条件挂载路由的**只有**
>    `if config.voice_clone_enabled`（`metrics_enabled` 那块只有 `include_in_schema=False`
>    的 `/metrics`；`docs_url`/`redoc_url` 不进 schema；`BUSINESS_AUTH` 自 09-17 起是无条件常量）
>    ⇒ 生产 env 不产生额外差异，且该轴已被轴 2 翻转钉住。
> ③ **前端消费点仍为「未做」**（不硬造）：L3-5 的触发条件本就是「有外部消费者」。
> ★ 并补两条用例把「新轴会隐身」堵死（8 → 10）：
>   `test_conditional_mount_axes_are_registered`（AST 实测条件挂载字段集合 == 登记集合，**双向**）
>   + `test_registered_axes_are_actually_flipped`（登记的轴必须真被 `--env-axes` 翻过）。
> ★ 教训：**「在一处绿」≠「在部署处绿」** —— 固定环境时，**被固定的字段集合本身**也要数清；
>   本轮漏了 `APP_NAME`，代价是「本地恒绿、CI 恒红」，且要等第一次 CI 运行才暴露。
> 结论落 `docs/reviews/2026-10-01-第354轮-P1-3与P3落地.md` §10。

> 目的：下次审查直接从 L2 开始，不必重走 L1 盘点。**有变化时更新本节。**

### CI（`.github/workflows/ci.yml` 430 行 / `cd.yml` 261 行）

| Job | 步骤 |
|---|---|
| 后端 | `compileall` → `import main`（抓循环导入）→ `alembic upgrade head` → **迁移链三重自检**（单一 head / downgrade→upgrade 往返 / `alembic check`）→ `bootstrap_db`（与 lifespan 同源）→ `ruff` 棘轮（当前 `--select T20`）→ **`mypy` 棘轮（`core ai_infra`，第 346 轮接入；第 353 轮实测 `Success, 89 source files`）** → pytest（**2542 用例**）+ 覆盖率棘轮（`fail_under=65`） |
| 前端 | 门禁 glob `check-*.*` + **覆盖率自证**（漏跑即红）→ `vue-tsc` → `vite build`（`VITE_DEMO_MODE=false`） |
| 资产 | 必需文件存在 → `docker compose config` → `nginx -t` → 敏感文件未被 git 跟踪 → **CD 资产门禁** |
| 安全 | bandit（Medium+ = 0）/ pip-audit / npm audit（阈值 `critical` —— 按原则四锁在「当前已绿」） |

> **用例数口径（第 347 轮核正）**：取数命令（**不要手写数字**）——
>
> ```bash
> # Windows 本机：./.venv/Scripts/python.exe ；Linux/CI：pytest（或 .venv/bin/python -m pytest）
> cd backend && ./.venv/Scripts/python.exe -m pytest tests/ --collect-only -q --no-header \
>   | python -c "import sys,re;print(sum(int(m.group(1)) for m in \
>     (re.match(r'^tests/\S+\.py: (\d+)$', l.strip()) for l in sys.stdin) if m))"
> ```
>
> 第 347 轮实测 = **2435 用例 / 148 个文件**（`--collect-only` 按文件求和）。
> ★ 这个数**每轮都在涨**，历史快照：867@r126 → 1674@09-27 → 2025@r283 →
> 2295@09-30(137 文件) → 2347@r332 → 2435@r347(148 文件) → 2450@r351(149 文件)
> → 2523@r351(153 文件)（同轮四道新门禁：`test_amazon_sp_oauth` / `test_prompt_versions` /
> `test_legal_docs` / `test_pitr`）→ **2527@r352(153 文件)**（`test_legal_docs` 由 5 条涨到 9 条）→
> **2542@r354(156 文件)**（`test_openapi_contract_gate` **10**（第 3 批由 8 涨到 10）
> + `test_tenant_isolation_gate` 3 + `test_no_syntax_warnings` 2）。
> ⇒ 本节是**快照**：更新时必须重跑上面这条命令，**不要沿用旧数**。
> ★ 为什么之前会写错：`11276` 既不是用例数、也不是 coverage statements 数
> （实测 statements ≈ 27150），属纯错记；根因是「写现状快照时没有当场取数」。

### 门禁总数

- 前端 `frontend/scripts/check-*.{cjs,py}`：**39 部 `.cjs` + 4 部 `.py`**（第 351 轮实测；
  ★ 其中 **38 部自带 env 注入开口**（`pick(env, fallback)` / `process.env[var]` 两种写法都算），
  **1 部没有**：`check-eslint-ratchet.cjs` —— 它读的是 **ESLint 配置面**、不读源码 ⇒ **非缺口**）
- 后端 `backend/scripts/check_*.py`：**5 部**，且**全部**由 pytest 包着跑：
  `test_alert_rules_gate.py` / `test_compose_secrets_gate.py` / `test_agent_session_memory.py` /
  `test_import_boundaries.py` / `test_openapi_contract_gate.py`
  ★ r350 曾记「4 部由 pytest 包着跑」为**错记**（r353 更正为 3/4：`check_tenant_isolation.py` 裸奔）；
  r354 新增第 5 部的同时把那处缺口补平 ⇒ **5/5**（「有几部」与「有几部被跑」从此同值）
- 另有一批 CDP 行为探针（`frontend/scripts/cdp-*.mjs`），其中
  `cdp-review-desk-config-baseline.mjs` 是拆 `ReviewDeskConfig.vue` 的**行为安全网**（33 条判据，含计算样式）

### 已核实「不是缺口」（防止未来重复怀疑）

| 项 | 承载 |
|---|---|
| 租户隔离 / 越权 | `scripts/check_tenant_isolation.py` + `test_tenant_scoping.py` / `test_shop_scope_consistency.py` / `test_tenant_id_spaces.py` / `test_auth_and_tenant.py` / `test_voice_clone_isolation.py` |
| 模块边界（跨包 import 形态） | `tests/test_import_boundaries.py`（AST 形态判据，覆盖「数据源必须经工厂」+「跨包禁 import 私有符号」） |
| 路由盘点 | `scripts/route_inventory.py`（唯一真源；容器识别走**结构**不钉私有名，遇不识对象**必须炸**） |
| **OpenAPI 契约快照** | `scripts/check_openapi_contract.py` + `docs/api/openapi.json`
  （236 路径 / 151 schema）+ `tests/test_openapi_contract_gate.py`（8 条）。
  ★ 快照**本身是交付物**（前端/第三方直接读，不必起服务）；★ 判据全部住在脚本里，
  用例只断言退出码与关键行（0=一致 / 1=漂移 / 2=环境错，三档分开）；
  ★ 带 `--env-axes` 子模式：固定环境让契约可复现，代价是其它 env 轴的影响会隐身 ⇒
  用子进程把 `AUTH_REQUIRED` 翻一次断言逐字节不变，把「不得条件挂载」钉住 |
| LLM 预算 | `ai_infra/budget.py`（`AgentBudget` + 三档 + `check_budget`）+ `base_agent.py:1383` **真消费** + `test_agent_budget.py` |
| RBAC | `core/auth/accounts.py`（`role_allows` / `resolve_account_role()`；团队角色与平台超管**两条链路**分开） |
| 密钥加密 | `core/security/credentials.py`（Fernet + 三类显式错误） |
| 备份 / 恢复演练 | `scripts/backup_db.py`（backup / 结构校验 / restore / **drill 演练** / 轮转） |
| **PITR**（WAL 归档 / 物理基线 / 恢复到**具名还原点**） | `scripts/pg_pitr.py`（`status` / `enable` /
  `archive-fetch` / `basebackup` / `drill`）+ `tests/test_pitr.py`（19 条，含端到端演练）+
  beat 两条（外送每 15 分钟 / 基线周一 2:11）+ 告警三条。★ 与上一行**互补不重复**：
  `pg_dump` 只能整库回退到某个 dump 瞬间，PITR 才能「恢复到 14:02 且保留 14:00 后的新单」 |
| SP-API 按店 OAuth | `modules/amazon_sp/oauth.py`（纯逻辑，零 DB）+ `router.py`（6 端点）+
  `tests/test_amazon_sp_oauth.py`（30 条；不存在与不属于你**同一响应**防枚举） |
| 提示词 DB 覆写层（B 档） | `modules/prompt_versions/`（表 `prompt_versions` + 五态常量 + 6 端点）+
  `ai_infra/llm/prompt_overrides.py`（应用半，避开 `ai_infra` 不得 import `modules.*` 的红线）+
  `tests/test_prompt_versions.py`（19 条：落库前先校验、`applied` 由内存表现算） |
| 法务文本与占位符 | `docs/legal/PLACEHOLDERS.md`（自证命令 + 「已处置」登记表）+ `tests/test_legal_docs.py`（**9 条**：
  无工程细节 / 天数 == 代码默认值 / 模板占位符 ⊆ 清单 / 自报数 == 实测数 / 根 `LICENSE` 与维护副本同源 /
  根 `LICENSE` 无内部维护者备注 / 子处理者清单的**代码取证锚点须真实存在** / 对外文本须链接清单）。
  ★ 该门禁**不**断言「占位符为 0」：余下 22 项无真值（主体信息 / 法务参数 / 部署事实 / 客户侧字段），
  钉的是「自报数 == 实测数」这类**可机器核对的关系**，不是一个恒不可能满足的零 |
| 子处理者清单 | `docs/legal/subprocessors.md`（7 条现行子处理者 + 5 项**明确不列入**及理由 +
  §5 四条复现命令）。★ 收录口径写成**可在代码里 grep 的判据**：「只有真的会向该方发送数据的依赖才算」
  ⇒ 把「清单是否完整」从凭记忆的问题变成可查证的问题。对外发布时须发布为公开 URL（未完成，已挂缺口） |
| 仓库根 `LICENSE` | 由 `docs/legal/LICENSE` **派生**（`split("★ 维护者备注")[0]` 再剥尾部分隔行），
  使「内部备注不应随发行物交付」从一句注释升级为**门禁**（L6 直接断言根副本不含该标记） |
| 告警规则 / compose 密钥 | `check_alert_rules.py` / `check_compose_secrets.py`（各有 pytest 包装） |
| 审计留存 | `core/audit/retention.py` |

---

## 6. 审查类型与触发映射（第 2 次复核新增）

> 背景：另有一份常见分法按「**审查类型**」分 6 类 —— 架构 / 代码 / 安全 / 测试与质量 /
> 运维与部署 / 业务与产品。它与本文 §2 的三层折法**不是竞争关系**：
> 六分类的划分依据是「**在什么时点、审什么对象**」，三层折法的依据是
> 「**这条判据该不该进人的议程**」。两个维度**正交**，叠加起来才完整。

### 6.1 两维叠加：六分类分别落在哪一层

| 审查类型 | 触发时机 | 主要落在 | 谁执行 |
|---|---|---|---|
| 架构审查 | 大重构 / 模块拆分 / 新增 Agent 能力 / 库结构变更 | **L2**（取向与取舍机器判不了）；L1 兜底（`test_import_boundaries`） | 人 |
| 代码审查（PR） | 每次合并 | **L1**（39+4 门禁 + pytest + `vue-tsc`）；L2 只审「门面有没有被绕过」 | 机器 + 人抽查 |
| 安全审查 | 涉密钥 / 多租户 / 对外接口上线前 | **L1**（bandit / pip-audit / npm audit / `check_tenant_isolation`）；L2 审「授权模型要不要加角色」 | 机器 + 人 |
| 测试与质量审查 | 版本发布前 / 重构后验收 | **L1 全自动**（覆盖率棘轮 + CDP 行为基线 33 条）；L2 审「新增路径有没有配对判据」 | 机器 |
| 运维与部署审查 | 生产发布 / 环境变更 | **L1**（assets job + CD 资产门禁）；L2 审「回滚方案」 | 机器 + 人 |
| 业务 / 产品审查 | 新功能上线 | **L2 全部** —— 唯一几乎不产生 L1 的类型 | 人 |

**用法**：改动落地时先认「本次属于哪几类」（可多选），再按上表取动作。
★ 最常见错误是**只按「代码审查」走**（因为合并是必经动作）⇒ 架构类改动（模块拆分 / 库结构变更）
也只得到 L1 的待遇，而它真正需要的是 L2 的人工判断。

### 6.2 建议补的三处

**补一：加第七类 —— 「AI Agent 行为审查」（当前六分类完全没有）**

六分类是通用 SaaS 的分法，**没为「LLM 参与的系统」留位置**。而本仓最大风险面恰在此处，
其缺陷形态与上述六类**都不重合**。共同特征是「**链路两端各自都正确，错在中间的隐式传递**」：

- 提示词改了 / 模型换了 / 数据变了 —— 三者**无法区分**（这正是 `PromptSpec` 要解决的问题）；
- 工具结果落 LangGraph checkpoint ⇒ 改工具输出后**旧会话仍复述旧值**；
- 同一 `thread_id` 跨 Agent **静默串味**（checkpoint 只按 id 分片、不含图身份）；
- 意图**关键词短路** ⇒ 工具未调用、点名技能永不生效；
- 范式 B（`invoke`）不设店铺 ContextVar ⇒ 读到上次范式 A 的**残留**。

⇒ 触发时机：改 prompt / 换模型 / 改工具签名 / 改意图分类 / 改 Agent 图结构。
本类判据目前大多是 L3（无判据），是**下一个该投入的判据池**。

**补二：把「适合场景」列形式化成触发映射**

六分类第 4 列（「适合你的项目场景」）目前是**散文**，执行时必然漏。
建议改成「改动类型 → 必跑清单」的硬映射落进本文件，并在 PR 模板留一格勾选。

**补三：审查结论归档**

当前每次审查的结论散在对话与工作日志里 ⇒ ①同一件事会被重复审 ②无法证明「审过」。
建议结论落 `docs/reviews/YYYY-MM-DD-<主题>.md`，只记三样：**结论 + 证据命令 + 未验证项**
（与附录 C 的「一次命令可复现」是同一个要求）。

---

## 附录 A：L3 待办清单（第 1 次盘点 · 2026-10-01 · **优先级待拍板**）

> 「实测证据」列的每条都可复核；改优先级时请连同证据一起改。

### ★ 复核修正（同日第 2 次盘点：L3-3 / L3-4 两条结论被推翻）

第 1 次盘点用 **grep 字面量**下结论（`trace_id` / `prompt_version` 命中 0 处 ⇒ 判「没有」）。
第 2 次改用**形态核查**（查符号、查消费点、查注册表是否真被填充），两条都错：

- **L3-3 不是「无 trace」**：`core/observability/context.py` 已有请求级全链路 ——
  `RequestLogMiddleware` 生成 / 透传 `X-Request-ID` → `set_request_context()` 写 ContextVar →
  `core/logger.py::_inject_context` 给**每一条业务日志**自动补
  `request_id / shop_id / user_id / account_id / client_ip` → 响应头回传 `X-Request-ID`。
  真实缺口收窄为三段：**①前端零参与**（`X-Request-ID` 在 `frontend/src` 命中 0）
  **②Celery 跨进程断链**（`delay()` 不传 id，worker 侧 0 命中）**③无分段耗时**（只有总耗时）。
- **L3-4 不是「无版本」**：`ai_infra/llm/prompt_spec.py`（第 283 轮 A 档）已有
  `PromptSpec.version`（人写）+ `.fingerprint`（`sha256(content)[:12]`，内容算）+ `required_vars`
  反解校验；`RenderedPrompt` 是 `str` 子类、携带 `name/version/fingerprint`；
  `PROMPT_TEMPLATES` **被 11 个业务模块真实填充**（ad_analysis / aigc_media×3 /
  competitor_intel / customer_service / listing_generator / product_research×2 /
  review_analyst / secretary / skills）。
  真实缺口只有一条：**指纹算出来没人读** —— `.fingerprint` 在 `modules/` + `ai_infra/`
  **0 命中**；且 `base_agent.py::get_prompt_template()` 的返回注解是 `-> str` ⇒ **类型擦除**，
  指纹在出口就被丢掉。

★ **教训（已并入 §3.1 判定三问）**：判「某能力有没有」**必须用形态判据，禁用字面量 grep** ——
  「符号叫别的名字」与「能力不存在」在 grep 眼里长得一模一样，而两者处置完全不同。

> 「实测证据」列的每条都可复核；改优先级时请连同证据一起改。

| # | 缺口 | 实测证据 | 建议 | 成本 |
|---|---|---|---|---|
| ~~L3-1~~ | ~~前端 ESLint **从未能跑**~~ | ✔ **已闭合（第 346 轮 · F-1）**：新建 `frontend/eslint.config.mjs`（flat config；**只显式 `off` 掉 21 条欠账**并导出 `LEGACY_DEBT_OFF` 供门禁 import，其余一条不动）+ 新增 `frontend/scripts/check-eslint-ratchet.cjs`（判据**问库本身**：`calculateConfigForFile`，冻结三张表 + 四条断言）+ `lint` 去掉破坏性 `--fix` 与 ESLint 9 已移除的 `--ext` + CI frontend job 接 `npm run lint:ci`（`--max-warnings=0`）+ devDeps **+6**（含 `@eslint/js` / `globals` / `vue-eslint-parser` —— 最后一个是 peerDependency，不显式装则 `npm ci` 失败）。稳态 **0 problem**；反向注入 **13/13 PASS**。★ 方案原写「逐条列零违规规则为 error」方向**是错的**：档位**按文件类解析**，全局提级会新开闸。详见 `docs/plan-l3-batches.md` §1.6 | 批次 1 | ✔ |
| ~~L3-2~~ | ~~后端 mypy **已装已配未接 CI**~~ | ✔ **已闭合（第 346 轮）**：CI backend job 已加 `run: mypy core ai_infra`（棘轮：只查已收敛到零的目录，基线 **74 条 → 0**）。★ 接入时还修掉两条 blocking：`python_version` 写 3.11 而 venv 是 3.12（mypy **一条业务结果都出不来**）、无参数 `mypy` 撞同名 `conftest`（退出码 2 但**一条都没检查**） | 批次 1 | ✔ |
| L3-3 | **请求级 trace 已有，缺三段** | `request_id` 已贯通后端全链路（见附录 A 上方「复核修正」）：缺 ① 前端零参与 ② Celery 跨进程断链 ③ 无分段耗时。★ **第 350 轮实测：三段全未动** —— `frontend/src` 内 `X-Request-ID`/`requestId` 命中 **0**；`X-Process-Time-Ms` 仍是**总耗时**（`core/middleware/request_log.py:113`），无 DB/LLM 分段；`main.py:167` 的 `CORSMiddleware` **无 `expose_headers`** | 批次 2 | 2–3 天 |
| L3-4 | **prompt 指纹算出来了但没人读**（第 350 轮实测：**仍未动**，`base_agent.py:824` 依旧是 `-> str`；行号由 790 漂到 824，因 B-1 注解补齐） | `PromptSpec`（`version` + `fingerprint` + 变量契约）齐备、**11 个业务模块真在注册**；缺的是：`.fingerprint` 在 `modules/` + `ai_infra/` **0 命中**、`get_prompt_template() -> str` **类型擦除**、B 档 DB 覆写层无表 | 批次 2 | 半天 |
| L3-5 | OpenAPI 契约无快照 | `route_inventory.py` 只**盘点路由**、不做 schema diff | 批次 3 | 1 天 |
| L3-6 | 前端无字段 / 按钮级权限渲染 | 全仓无 `v-permission` / `hasPermission`；只有业务态 `editable` | 批次 3 | 2–3 天 |
| L3-7 | 无 SBOM | 无 `syft` / `cyclonedx`（漏洞扫描已由 pip-audit / npm audit 覆盖，SBOM 是**交付物**而非检测手段） | 批次 3 | 半天 |
| L3-8 | 无 ADR（架构决策记录） | `docs/` 有大量审计报告与交付文档，但无决策记录 | 批次 3 | 持续 |
| L3-9 | 数据出境未落地 | `docs/legal/PLACEHOLDERS.md` 已登记 `CROSS_BORDER_DESTINATION` / `CROSS_BORDER_MECHANISM` / `CROSS_BORDER_LIST_URL` 待填 | 批次 4 | 等客户 |
| L3-10 | 无 K8s / 水平扩容 | 仅 `docker-compose.yml` | 批次 4 | 等需要 |

### ★ 第 350 轮全量重盘（逐条实测，取代上面「第 1/2 次盘点」的状态列）

| # | 状态 | 第 350 轮实测证据 |
|---|---|---|
| L3-1 | ✅ 闭合（r346），且已三轮收紧 | 棘轮 `FLOOR_ENFORCED` **181 → 193**、欠账 **21 → 9** |
| L3-2 | ✅ 闭合（r346） | `mypy core ai_infra` → **Success, 87 source files**（74 → 0） |
| L3-3 | ✅ 闭合（r351） | 前端两出口注入 `X-Request-ID` + 后端 `request_timing.py` 三段计时 + CORS `expose_headers`；11 条新门禁 / 10 条 pytest / 真浏览器 5/5 / 反向注入 5 红 |
| L3-4 | ✅ 闭合（r351） | 渲染留痕（`render_prompt` INFO 级，只记变量名） + `base_agent.py:824` → `-> "RenderedPrompt"`；5 条新判据 + 反向注入 5/5 + mypy 仍 88 文件 |
| L3-5 | ❌ 未做 | `docs/openapi*` glob **0 命中** |
| L3-6 | ❌ 未做 | `v-permission` / `hasPermission` 命中 **0** |
| L3-7 | ❌ 未做 | `*.cdx.json` / `**/sbom*` 均 **0** |
| L3-8 | ❌ 未做 | `docs/adr/**`、`docs/ADR-*.md` 均 **0** |
| L3-9 | 🟡 清单已建，字段待填 | `PLACEHOLDERS.md` 自证命令实测 = **36 个占位符** |
| L3-10 | ❌ 按设计不做 | `**/k8s/**` = 0 |

**新增（第 350 轮重盘发现）**

| # | 缺口 | 级别 | 实测证据 |
|---|---|---|---|
| L3-11 | ✅ 闭合（r351）：**8 道真缺口**全部补 `pick` 开口 + 空源自证 **8/8**；余 1 道（`check-eslint-ratchet.cjs`）是配置面例外 | P1 | `.workbuddy/probes/r351/revinject_emptysrc.py` |
| L3-12 | **本地 venv 缺 `ruff`/`bandit`/`pip-audit`** ⇒ 这 3 道 CI 步骤本地不可复现 | P2 | 三者均 `No module named …` |
| L3-13 | **欠账表注释数字漂移** | P3 | `eslint.config.mjs:80` 写 `no-undef 13 条`，实测 **19**；`:85` 写 `112`，实测 **115** |
| L3-14 | **`SyntaxWarning` 污染输出**（第 353 轮实测 **3 个文件**，其中 **2 条是 alembic 迁移** ⇒ 污染**每次 alembic 运行**） | P3 | 全仓 `compile()` 捕 `SyntaxWarning`：`b8d4e2f6c3a5_memory_tables.py:11` · **`e7b2c9d4a1f8_review_reports_library.py:34`** · `patch_nav_view_ids_comment.py:6` |
| L3-15 | **仓库根无 `LICENSE`**（文本在 `docs/legal/LICENSE`） | P1 | `LICENSE` 不存在 |
| L3-16 | **无「表必须有写入者」门禁**（r332 §8 建议 4 未做） | P2 | `test_schema_parity.py` 只判外键。★ 第 353 轮更正：原举证「`amazon_credentials`/`amazon_auth_logs` 零实例化」**已失效** —— r351 的 P0-6 给它们接上了真实写入者（`amazon_sp/router.py` ×2 / ×1）⇒ 举证案例须另找 |
| **L3-17** | **`backend/scripts/check_tenant_isolation.py` 无任何自动入口 + 期望值过期** | **P1** | 第 353 轮：AST 判据实测「4 部后端脚本门禁中**唯一**没有 pytest 包装、CI 也不跑它」；实跑 **1/2 通过**（演示模式那条期望 200、实得 403）⇒ 探针证得系**期望过期**（现行口径是「演示店 200 / 真实店 403」）。★ 与 L3-11 方向相反：L3-11 是「**红不了**」，本条是「**红了没人看**」 |

> 完整重锚（含 P0 九项逐条）见 `docs/reviews/2026-10-01-项目复审与进度归档.md`。

### 分批建议与理由

- **批次 1 ——「补齐写了但从未生效的工程配置」**（L3-1 + L3-2）—— ✔ **第 346 轮两条全部闭合**
  两条**同源**：都是「配置 / 脚本写了，但依赖或 CI 步骤缺失 ⇒ 从未真正执行」。
  成本最低，且直接加固当前正在进行的重构（后端有 `vue-tsc` 的对位物，前端补 lint）。
  ★ 必须按**原则四**走棘轮：`eslint` 与 `mypy` 都不要直连全量（103 个 `.vue` + 后端存量无标注
  会一次爆几千条 ⇒ 常红 ⇒ 被绕过）。照 `ruff --select` 的范式，先圈已收敛的目录 / 规则。
- **批次 2 ——「出事后能不能还原当时发生了什么」**（L3-3 + L3-4）—— ✔ **第 351 轮两条全部闭合**
  两条回答**同一个问题**：Trace 管**链路**（前端请求 → FastAPI → Agent → DB），
  prompt 版本管**Agent 当时看到的是哪一版指令**。单独做 Trace 而不做 prompt 版本，
  Agent 那一段仍是黑盒。
  ★ **触发条件**：若有明确的海外客户 / 上线时间表，本批次应提到批次 1 **之前**。
- **批次 3 —— 触发条件明确**：L3-5 等前端 / 第三方要接 API 时；L3-6 等出现第二个角色时；
  L3-7 等客户要；L3-8 从现在开始**顺手记**（成本极低，靠习惯）。
- **批次 4 —— 明确不做**：L3-9 等有海外客户；L3-10 等真有水平扩容需求。

---

## 附录 B：明确「当前阶段不适用」（不是缺口）

| 项 | 结论依据 |
|---|---|
| Redis 缓存击穿 / 雪崩 | 实测 `core/redis.py` 只有 broker / result backend 与 Celery beat 排期，**没有业务缓存层** ⇒ 前提不存在 |
| 读写分离 | 当前单实例 PostgreSQL，无只读副本 |
| 爬虫合规 / 防封店 | `modules/platform_rules` 已承载平台规则；调用侧限流由 `RateLimitMiddleware` 覆盖 |

---

## 附录 C：本文自身的证据链约定

本文任何一条结论，将来被别人质疑时，应当能在**一次命令**内复现。做不到的结论请标为「未验证」，
不要写成断言 —— 这正是原则二对本文自身的要求。
