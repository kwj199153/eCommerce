# Agent 底座对标 eEducation —— 可移植性与分级方案（r399）

> 起因：「参照 eEducation 的 agent 优化（HITL、skill/工具硬编码），你们都用 baseagent 底座，应该可以改？」
>
> **结论：可以改，但只有 3 项是"搬过来"，其余 4 项必须按多租户改写。**
> 另外发现 3 条**生产上已经跑不通的死链路** —— 那不是"要不要优化"，是 bug。

---

## 0. 先把三件事说清楚

### ① 底座确实是同一份

同名模块逐个比（`git diff --no-index --numstat`）：

| 模块 | eEducation | eCommerce | 判定 |
|---|---:|---:|---|
| `ai_infra/tools/side_effects.py` | 267 | 267 | **逐字同源**（差 43+/43-，语义级一致） |
| `ai_infra/tools/hitl_decorator.py` | 241 | 230 | 同源，我们少 11 行 |
| `ai_infra/tools/serialization.py` | 61 | 73 | 同源 |
| `ai_infra/skills.py` | 818 | 684 | **符号一一对应**（`parse_skill_document` / `render_skill_catalog` / `build_skill_tools` …），只差 `SKILLS_GUIDE` 等常量 |
| `ai_infra/base_agent.py` | 1235 | **1846** | 同源但**我们胖了 611 行** |
| `ai_infra/tools/clarification.py` | **479** | 146 | 对方重写过（见 P0-3） |
| `ai_infra/capability/` | **1699** | **不存在** | 对方新增（见 P1-1） |

⇒ 「都用 baseagent 底座」成立，**对照是有效的**，不存在"两套东西没法比"。

### ② 我们不是全面落后，是"落点不同"

- eEducation 的 Agent 要**替用户点按钮**（改作业、发通知、退款），所以必须有「发现 → 说明书 → 调用」的能力层。
- 我们的 8 个 Agent 各有**专属业务工具**（65 个，全部手写 + 手写目录），业务语义更强。
- 但差距是真的：**后端 299 个端点，Agent 只够得到 65 个**（且这 65 个是人工挑的），新增一个能力要**人工同步 3～9 处**。这就是"硬编码"的具体形态。

### ③ 最该先动的不是能力层，是 HITL 的闭环

我们的 HITL **策略层**（`side_effects.py` 三档 metadata + `derive_hitl_tools` + 写动词第二判据）和对方同源，甚至有 6 条 pytest 钉着。问题在**闭环只接通了 1 个 Agent**：

| Agent | 被审批工具 | resume 通道 | 生产上的实际结果 |
|---|---|---|---|
| 选品分析师 | 3（`save/review/approve_candidate`） | ✅ 全套 | 闭环可用（唯一） |
| 智能客服 | 1（`create_ticket`） | ❌ | **永远抛 `HITLPrerequisiteError`** |
| 智能客服（trade 域） | 1（`propose_review_disposition`） | ❌ | **同上** |
| 其余 6 个 | 0 | — | 不涉及 |

原因不是"没写"，是**调用方不传会话**：`modules/customer_service/agent_cs/core.py:203` 走 `router.run_session({"messages": [...]})`，没有 `session_id`/`user_id` ⇒ `graph_for_session(None, None)` 返回 memoryless 图 ⇒ 没有 `thread_id` ⇒ fail-closed 守卫直接拒（`hitl_decorator.py:138-158`）。

而 `tests/test_hitl_policy.py:600-678` 的三数联判只看**构造点有没有 checkpointer**（`core.py:111` 确实绑了），所以**门禁是绿的**。这是典型的"判据只看了一半"。

---

## 1. 六项差距（按"要不要做 / 做了什么感觉"排）

| # | 差距 | 对方做法 | 我们的现状 | 性质 |
|---|---|---|---|---|
| 1 | **HITL 闭环** | 通用 `hitl_presenter.py` + 按 agent/session 的 resume | 端点/卡片/编排全部绑死 `product-research`（`router.py:260`、`api/productResearch.ts:124`） | **bug**（2 个工具死） |
| 2 | **澄清真挂起** | `ask_clarification` 里 `interrupt(payload)`，同一轮继续 | 只 `json.dumps` 返回字符串；前端 0 消费者 | **半条链** |
| 3 | **决策档位** | 两档 `accept`/`reject`（555 轮砍掉 edit/response，理由：零调用方） | 四档（`hitl_decorator.py:169-202`），前端有 4 个按钮 | 冗余，不是错 |
| 4 | **能力层** | `capability/` 4 文件 1699 行：OpenAPI 派生 184 个操作、4 个通用工具（find/describe/read/call）、检索无向量、schema 合计 2938 字符 | 无。65 工具手写 + `TOOL_CATALOG` 手写 65 条（`tools_catalog.py:182-729`） | **硬编码主体** |
| 5 | **端点副作用声明** | `core/openapi_side_effects.py` 给每个 op 打 `x-side-effect`（read/write/irreversible） | `grep x-side-effect` = **0 命中** | 能力层的前置 |
| 6 | **base_agent 体积** | 1235 行（LLM 原语/消息清洗/会话入口已外移） | 1846 行，约 **900 行（49%）** 是可外移的横切逻辑 | 架构债 |

补充：`name_guard.py`（编造名字检测，155 行）、`recursion_guard.py`（图递归兜底，80 行）、`session_context.py`（请求现场 ContextVar，196 行）我们都没有对应通用件 —— 前两项的能力在我们这儿是"某个业务模块自己写的补丁"（`modules/secretary/shop_context.py:259`）。

---

## 2. P0：三条死链路（建议立刻做，不做就是留着 bug）

### P0-1 客服两个写工具永远不可用

| 改动点 | 文件:行号 | 内容 |
|---|---|---|
| 补会话与身份 | `modules/customer_service/agent_cs/core.py:164-166`、`:203-205` | `run_session` / `stream_session` 传 `session_id` + `user_id`（与 PR 的调用形态对齐） |
| 门禁补洞 | `tests/test_hitl_policy.py` | 新增一条：**AST 判"每个调用 `run_session/stream_session` 的点是否传了 session_id"**，不只看构造点有没有 checkpointer |

> 备注：`create_ticket` 是客服从"聊"到"落工单"的唯一出口，现在这个出口在生产上是关着的，而模型只会转述一句"该操作需人工审批但缺少会话"。

### P0-2 resume 端点泛化

| 改动点 | 文件:行号 | 内容 |
|---|---|---|
| 后端 | `modules/product_research/router.py:260` | 抽成通用 `POST /api/v1/agents/{agent}/approval/resume`（或 `/chat/approval/resume`），内部按 agent_name 分发 |
| 渲染 | `modules/product_research/agent_hitl.py:66-98` | `hitl_presenter` 提到 `ai_infra` 之外的中立模块（对方在 `modules/conversation/hitl_presenter.py`） |
| 前端 | `frontend/src/api/productResearch.ts:124` | 改成通用 api 模块；`useApprovalFlow.ts:54-90` 按 agent 取端点 |
| 判据 | `frontend/scripts/check-hitl-approval.cjs` | 已存在，改成"每个有 gated 工具的 agent 都必须有 resume 通道" |

### P0-3 澄清：真挂起，或明确删掉契约

对方 479 行比我们 146 行多出来的**不是重构，是四条能力**：真 `interrupt()` 挂起（同轮继续，模型自己记得问过什么）、请求级队列 ContextVar + `bind/take`、无会话时三级降级（挂起 → 入队 → `channel_unavailable`）、选项对象化（`{label, description, recommended}`，上限 4 个）。

我们现在的状态是「协议定义了（`clarification_request`）、执行侧只吐字符串、UI 侧零消费者」⇒ 实际靠模型在正文里反问。

| 选项 | 动作 | 代价 |
|---|---|---|
| **A（推荐）** | 照对方做真挂起 | 搬 ~330 行 + 前端接一个卡片 + resume 复用 P0-2 |
| B | 删掉 `clarification_request` 契约与相关测试，明确"澄清 = 正文反问" | 少 1 条链路，但**诚实** |

> 顺带一个必须知道的坑：`ask_clarification` 的 `config` 注解必须逐字是 `RunnableConfig`，写成 `Optional[RunnableConfig]` 会让 langchain 的注入识别失效 ⇒ **永远不挂起且零报错**（对方第 559 轮实测）。

---

## 3. P1：消灭硬编码（用户点名的部分）

### P1-1 能力层：三档，建议先做"只读"

先看对方这一层的核心取舍（值得抄的不是代码，是这四条设计）：

1. **真源是 `app.openapi()`**，不是手写表 —— `tags`/`summary` 是端点作者写的，唯一随代码同步。
2. **读写拆成两个工具名**（`read_capability` / `call_capability`），因为审批判据是**静态工具名**；合成一个就变成"每次查数据都弹审批"⇒ 用户把确认点成肌肉记忆 ⇒ 闸等于没有。
3. **只有 4 个工具、schema 合计 2938 字符**（有门禁钉 < 4000）。操作知识不在 schema 里，靠 `describe_capability` 按需取。
4. **`sent: false/true` 必须可区分** —— "本地拦下"和"服务端拒绝"决定模型下一步是改参数重试还是先判断权限。

三档选择：

| 档 | 内容 | 我们这边的改动面 | 风险 |
|---|---|---|---|
| **A 只读三原语（推荐先做）** | `find_capabilities` / `describe_capability` / `read_capability` | 新增 `capability/`（约 900 行，砍掉 invoke 的写路径）+ `bind_app` + 中间件转发身份 + 装配 1 行 | 低。只读不写，审批面不变 |
| B 全量四原语 | 再加 `call_capability`（写，必过审批） | +400 行（写路径）+ 端点副作用声明**全覆盖** | 中。写路径要过租户闸 |
| C 不做 | 只把 65 个工具注册表化 | 见 P1-2 | 低但收益也低 |

**前置条件（A 档也要）**：给端点补 `x-side-effect`。对方是 `core/openapi_side_effects.py` 在生成 spec 时统一写入，默认档按方法推（GET→read / DELETE→irreversible / 其余→write），只对敏感面显式声明。我们 299 个端点，**0 声明** —— 所以不能照抄"逐个显式声明"，要走默认档 + 敏感前缀覆盖。

### P1-2 `TOOL_CATALOG` 从"手写 65 条"改成"派生 + 覆盖层"

现状：65 条 × 7 行 = 455 行手写，与真实装配靠 `tests/test_tool_catalog.py:272` 的集合相等钉住。加一个工具要同步：工具定义、目录条目、`EXPECTED_GATED`、目录审批名单、工具总数断言、Agent 工具数断言（3～6 处）。

改法：`name`/`agent`/`effect` 从工具对象**派生**（`effect` 本来就从 `metadata` 来，现在等于存了两遍），`title`/`description` 保留人工覆盖层（这部分是给人看的文案，派生不出来）。

收益：新增能力的同步点从 3～6 处降到 **1～2 处**；`tests/test_tool_catalog.py:307`（effect == metadata）这条判据从"人肉一致"变成"天然一致"。

---

## 4. P2：架构债（收益有，但不紧急）

| 项 | 现状 | 目标 |
|---|---|---|
| `base_agent.py` 拆分 | 1846 行 | **第 400 轮执行结果：只做了第二块**（详见下方「P2 实际落地」）—— 消息清洗 + 轮次口径 → `ai_infra/messages.py`，**1846 → 1651**，棘轮上限同步下调。另外两块**判定为不划算，主动不做** |
| `recursion_guard` | 无（超限直接抛给调用方） | ✅ 已做：`ai_infra/recursion_guard.py`（160 行）。★ 关键修正：对方是「捕获 + 兜底话术」，我们**还必须先设上限** —— `recursion_limit` 的单位是**超步**（模型节点 + 工具节点各 1），`max_iterations` 是**模型轮次**，不设 `2*n+8` 就永远先撞 `GraphRecursionError`，「到点正常收尾」走不到 |
| `name_guard` | 只有 secretary 的店铺名版（`shop_context.py:259`） | ✅ 已做：`ai_infra/name_guard.py`（218 行）+ `shop_context` 三函数改成薄适配壳 |

### P2 实际落地（第 400 轮）

| 块 | 行数 | 结论 |
|---|---|---|
| ② 消息清洗 + 轮次口径 | ~235 行 → `ai_infra/messages.py` | ✅ 做了。理由：这 5 个方法本来就是 `@staticmethod`（**零 `self`**），搬出去是纯位移，`BaseAgent` 上留 `staticmethod(...)` 薄壳即可，两类调用形态（`self.x()` / `BaseAgent.x()`）与 monkeypatch 通道全部不变 |
| ① LLM 原语 + RAG + 统计 | ~400 行 | ❌ 不做。全部吃 `self`（`_llm_stats` / `ENABLE_LLM` / `ENABLE_RAG` / `rag_engine` / `llm_client`），只能走 **mixin**（本仓已在 `tests/test_source_size_ratchet.py` 顶部明确否决：「藏进基类只会让耦合从可数的参数变成看不见的继承链」）或把 agent 当第一个参数传（收益只剩行数，代价是所有 6 个业务 Agent 的调用形状变化） |
| ③ 会话入口 | ~211 行 | ❌ 不做。`last_turn_was_clarification` 的「只读」由 `test_read_shell_is_read_only` 在**壳的就地源码**上数 `graph.aget_state == 1`；一旦把 `aget_state` 搬到 `session.py`，这条门禁只能跨文件追 —— 用一条更强约束换 200 行行数，亏 |

★ 结论：**「可回落到 ~1000 行」这个预估偏乐观** —— 它假设三块都像②那样零 `self`。实际只有②成立。

---

## 5. 四处**不能照抄**（对方单租户，我们多租户）

| 对方的实现 | 我们的问题 | 必须怎么改 |
|---|---|---|
| `FORWARD_HEADERS` 只含 `authorization`/`x-learner-id`/`x-account-id`/`x-request-id`/`x-api-key` | 我们的作用域是 `X-Shop-ID → store_id`（`scoping::SHOP_SCOPE_ATTR`） | 白名单必须含 `x-shop-id`；且**非只读操作缺 shop 头要硬拒**（否则能力层成了绕过租户隔离的通道 —— 本仓已有这条纪律） |
| `CallIdentity.user_id` 只写不读（预留） | 我们按租户过滤必须查归属 | 落到审计日志与归属判定，不能只写 |
| `path_params` 直接 `str.replace` 拼 URL | 值里含 `/`、`?`、`#` 会改掉最终路径，而 `BLOCKED` 只在**模板**上判过 | 移植时加 `urllib.parse.quote(value, safe="")` |
| `_EMPTY_IDENTITY` 是模块级单例，`budget` 被所有未绑定身份的调用共享 | 非 HTTP 路径（脚本/后台任务）会共用 24 次配额 | 改成按上下文派生 |

另外对方有三处**判据自己漂移**，别照抄：`probe-capability.py` 的 D3 白名单已过期（对方现状会红）、`as_row()` 全仓零调用、两个被点名的探针文件不存在。

---

## 6. 建议顺序与工作量

| 阶段 | 项 | 改动面 | 什么时候能看出来 |
|---|---|---|---|
| **P0** | P0-1 客服会话 + 门禁补洞 | 3 文件 | 客服能真的建工单（且要人点一下） |
| | P0-2 resume 泛化 | 后端 2 + 前端 3 | 任意 agent 的审批都能点 |
| | P0-3 澄清真挂起（选 A） | 后端 1 + 前端 2 | 点选项 = 同一轮继续，不再开新话题 |
| **P1** | P1-1 能力层 A 档（只读） | 新增 ~900 行 + 装配 1 行 + 中间件 1 处 | 问"我这个店最近哪些 SKU 断货"→ Agent 能自己找到端点读数据，不用先写工具 |
| | P1-2 TOOL_CATALOG 派生 | 1 文件 + 2 处测试 | 加工具只改工具定义 |
| **P2** | base_agent 拆三块 | 实际只拆了 1 块（②消息口径）+ 2 个新守卫 | ✅ 已交付；①③ 判定不划算未做（理由见 §4「P2 实际落地」） |

---

## 7. 要你拍板的三件事

1. **能力层做到哪一档？** 我推荐 **A（只读三原语）**：收益最大的一步（Agent 从"够得到 65 个"变成"够得到全部读端点"），风险最小（不碰写、不改审批面）。B 可以等 A 跑稳了再加。
2. **澄清是"真挂起"还是"删契约"？** 我推荐**真挂起**（A 档），因为它能直接复用 P0-2 的 resume 通道，边际成本低；但如果你觉得"正文反问"够用，删掉契约更诚实。
3. **`TOOL_CATALOG` 要不要去手写？** 我推荐**去**（`effect` 已经是存两遍），但 `title`/`description` 的人读文案必须保留人工覆盖 —— 那部分是产品语言，派生不出来。

---

## 附：本次调研的取证方式

- 两边同名模块：`git diff --no-index --numstat`（行数差表）
- eCommerce 侧：AST 扫 `StructuredTool.from_function`/`@tool` 得 68 个构造点（65 业务 + 3 机制）；`grep -c '^        "name":'` 得 `TOOL_CATALOG` 65 条；`@router/@app` 装饰器行首匹配得端点 **299**（modules+core+main）
- eEducation 侧：`capability/` 四文件 1699 行；其探针实测可见操作 **184** 条（read 72 / write 85 / irreversible 27），四工具 schema 合计 2938 字符
- 未执行任何写操作；未跑全量 pytest（本仓 tests 直连共享库，按纪律单跑）
