# 第 199 轮 · 选品 Agent（`product_research`）能力面盘点

> 老板要求：「一个 agent 一个 agent 开始排查整改，首先是选品 agent ——
> 它有哪些函数（其中哪些做成了 API，哪些做成了工具，工具中哪些有被 skill 用到）」。
>
> **本轮只排查，不改代码。** 全部读数来自 **AST + 当前库**，不引用任何 docstring。
>
> 取证脚本：`r199_pr_ast.py`（四张表 + 按接收者数引用）、`r199_pr_view.py`（视图）、
> `r199_pr_skills_db.py`（从 `skills` 表读真实技能数据）、`r199_pr_deadchain.py`（死方法簇连带引用）。
> 原始输出：`.workbuddy/probes/out_r199_*.txt`、`r199_pr_*.json`。

---

## 0. 口径（先说清，否则数字会互相打架）

| 项 | 口径 |
|---|---|
| 「函数」分四层 | 端点（`router.py`）→ service（`service.py`）→ 工具（`tools.py`）→ agent（`agent_product_research.py`） |
| 「做成了 API」 | `router.py` 里挂了 HTTP 装饰器，且**实际调用**该 service 方法（读装饰器 + 函数体，不看 docstring） |
| 「做成了工具」 | 出现在 `product_research_tools` 注册表里，且其包装函数**实际调用**到的 service/agent 方法 |
| 「被 skill 用到」 | `skills` 表里 `tools` 字段含该工具名。**读当前库**，不读 seed 源码 |
| 引用计数 | **按接收者**数（`service.X` / `self.X` / `cls.X` / `*.agent.X`），**不按名字** —— <br>按名字数会把 ad_analysis / competitor_intel 等**同名的别家方法**算进来（实测 `_classify_intent` 虚高 10 处） |

**agent 方法 62 个、service 方法 12 个、端点 8 个、工具 5 个。**

---

## 1. ★ 主表：能力 × 三个暴露面

以 **service 层 + 一个 agent 私有方法**为主轴（这就是「选品 agent 会做的事」的全集）。

| # | 能力（实现位置） | 行 | 做成了 API？ | 做成了工具？ | 被 skill 用？ |
|---|---|---|---|---|---|
| 1 | `service.analyze_blue_ocean` | 38 | ✅ `POST /blue-ocean` | ✅ `analyze_blue_ocean` | ❌ |
| 2 | `service.analyze_profit` | 194 | ✅ `POST /profit` | ✅ `analyze_profit` | ❌ |
| 3 | `service.analyze_pain_points` | 261 | ✅ `POST /pain-points` | ✅ `analyze_pain_points` | ❌ |
| 4 | `service.compare_competitors` | 275 | ✅ `POST /competitors` | ✅ `compare_competitor_listings` | ❌ |
| 5 | `service.chat` | 306 | ✅ `POST /chat` | ❌ | ❌ |
| 6 | `service.stream_chat` | 364 | ✅ `POST /chat/stream` | ❌ | ❌ |
| 7 | `service.resume_approval` | 336 | ✅ `POST /approval/resume` | ❌ | ❌ |
| 8 | `agent._save_candidate` ★ | 1915 | ❌ | ✅ `save_candidate`（HITL 审批） | ❌ |
| 9 | `service._generate_mock_blue_ocean_products` | 94 | ❌ | ❌ | ❌ |
| 10 | `service._apply_filters` | 122 | ❌ | ❌ | ❌ |
| 11 | `service._calculate_blue_ocean_scores` | 160 | ❌ | ❌ | ❌ |
| 12 | `service._generate_suggestions` | 386 | ❌ | ❌ | ❌ |
| 13 | `service.__init__` | 33 | — | — | — |

**怎么读这张表**：

- **9–12 是 #1 / #5 的私有子步骤**，不外露是**对的**（不是缺口）。
- **★ #8 打破了既有范式**：其余 4 个工具都是 `req → await _service.x(req) → dump` 的
  1:1 service 薄包装；只有 `save_candidate` 绕过 service 层，
  直接 `await _service.agent._save_candidate(...)`（`tools.py:194`）。
  **后果**：入库这条链路的能力**在 service 层没有对应方法** ⇒ 用 service 做能力盘点会漏掉它；
  反过来，将来给 `ProductResearchService` 加方法也不会自动获得工具。
- **#5–7 有端点、无工具**：这三个是**编排入口**（开对话 / 流式 / 恢复审批），
  本来就不该做成工具（模型不该自己开一轮新对话）。**这是有意为之，不是缺口。**
- **「被 skill 用」整列为空**：见 §3。

---

## 2. 端点明细（8 个）+ 前端调用点

| # | 方法 + 路径 | handler | → service | 前端调用点 |
|---|---|---|---|---|
| 1 | `POST /api/v1/product-research/blue-ocean` | `analyze_blue_ocean` | `analyze_blue_ocean` | `mock/toolExecutors.ts:155` |
| 2 | `POST /api/v1/product-research/profit` | `analyze_profit` | `analyze_profit` | **无**（`api` 里封装了 `analyzeProfit`，零调用） |
| 3 | `POST /api/v1/product-research/pain-points` | `analyze_pain_points` | `analyze_pain_points` | **无**（同上） |
| 4 | `POST /api/v1/product-research/competitors` | `compare_competitors` | `compare_competitors` | `mock/toolExecutors.ts:229` |
| 5 | `POST /api/v1/product-research/chat` | `chat` | `chat` | `composables/chat/replies/productResearch.ts:60` |
| 6 | `POST /api/v1/product-research/chat/stream` | `chat_stream` | `stream_chat` | `replies/productResearch.ts:40`（**直连 `streamSSE`，绕过 api 层**） |
| 7 | `POST /api/v1/product-research/approval/resume` | `resume_approval` | `resume_approval` | `composables/useApprovalFlow.ts:78` |
| 8 | `GET /api/v1/product-research/capabilities` | `get_capabilities` | **不调 service**（硬编码返回） | **无**（`getProductResearchCapabilities` 零调用） |

- `router.py` 的模块 docstring 只列了 6 个端点 —— **漏掉 `approval/resume` 与 `chat/stream`**（文档漂移）。
- 端点 1–4 与工具 1–4 **指向同一批 service 方法** ⇒ 同一条能力有两条通道
  （面板走 API、AI 走工具）。这是本仓既定范式，不是重复实现。

---

## 3. 工具明细（5 个）+ skill 引用（**0**）

| # | 工具名 | 包装函数 | 真正调到的 | 副作用档 |
|---|---|---|---|---|
| 1 | `analyze_blue_ocean` | `_analyze_blue_ocean_tool` | `_service.analyze_blue_ocean` | 只读 |
| 2 | `analyze_profit` | `_analyze_profit_tool` | `_service.analyze_profit` | 只读 |
| 3 | `analyze_pain_points` | `_analyze_pain_points_tool` | `_service.analyze_pain_points` | 只读 |
| 4 | `compare_competitor_listings` | `_compare_competitors_tool` | `_service.compare_competitors` | 只读 |
| 5 | `save_candidate` | `_save_candidate_tool` | `_service.agent._save_candidate` ★ | **有副作用**（HITL 审批） |

### 3.1 被 skill 用到：**5 个工具，0 个引用**

从**当前库**读（`select * from skills`，22 条）：

- 22 条技能的 `tools` 字段**全部是 `[]`**（一条不剩）。
- 挂 `ProductResearcher` 的技能有 **6 条**，`tools` 也全是 `[]`：

| 技能名 | 标题 | 启用 | 工具 |
|---|---|---|---|
| `candidate-market-feasibility` | 市场可行性 | ✅ | `[]` |
| `candidate-launch-advice` | 上架建议 | ✅ | `[]` |
| `candidate-pain-analysis` | 痛点分析 | ✅ | `[]` |
| `candidate-risk-scan` | 选品避坑 | ✅ | `[]` |
| `blueocean-hard-filter` | 蓝海筛选硬门槛 | ❌（未启用） | `[]` |
| `candidate-benchmark-compare` | 竞品对比 | ✅ | `[]` |

⇒ **「工具中哪些有被 skill 用到」的答案是：0 个 —— 一个都没有。**

★ 一个必须说清的连带事实：第 198 轮给 5 条**竞品**技能在 `seed.py` 里绑了工具，
但**库里仍是 `[]`**。原因是 `ensure_demo_skills()` 的设计是「**已有则不覆盖**」
（第 182 轮定的：演示身份能改这些技能 ⇒ 重启后改动要还在）。
⇒ **改 seed 不等于改库**；要让绑定生效，必须删掉那几行让下次启动重建。
第 198 轮报告写了「5 条技能绑上工具」但**没写这一条**，属**未落地**。

---

## 4. agent 内部函数（62 个）

按职能分组（行号来自 AST）：

| 组 | 数量 | 成员 | 备注 |
|---|---|---|---|
| A. 入口 / 生命周期 | 7 | `__init__` `invoke` `stream`☠ `stream_chat` `resume_approval` `_invoke_impl` `_stream_chat_impl` | `stream` 零调用 |
| B. 路由与工具编排 | 8 | `_get_router` `_build_router` `_route_via_tools` `_stream_via_tools` `_parse_tool_output` `_route_gated_intent` `_stream_gated_intent` `_classify_intent` | 全活 |
| C. HITL 审批 | 4 | `_detect_pending_approval` `_pending_approval_from_interrupt` `_build_resume_payload` `_unwrap_hitl_tool_output` | 全活 |
| D. 会话状态 | 9 | `_state_scope` `_state_key` `_session` `_hydrate_state` `_flush_state` `_last_products` `_last_blue_ocean` `_bind_context` `_session_context_block` | `_last_blue_ocean` **只被测试引用** |
| E. 四大业务能力 + 兜底 | 7 | `_analyze_blue_ocean` `_analyze_profit` `_analyze_pain_points` `_analyze_competitors` `_general_chat` `_process_query` `_general_stream` | 全活 |
| F. 候选入库 | 7 | `_save_candidate` `_ask_for_save` `_resume_pending_save` `_write_candidates` `_candidate_payload_from_product` `_resolve_named_product` `_named_tokens` | 全活 |
| G. 解析 / 计算 / 文案 | 13 | `_extract_category` `_extract_asin` `_extract_multiple_asins` `_extract_ordinal` `_extract_product_info` `_generate_search_keywords` `_calculate_opportunity_score` `_generate_reason` `_estimate_price_range` `_estimate_margin` `_generate_improvement_suggestions` `_format_blue_ocean_reply` `_compose_reply` | 全活 |
| **H. 旧工具簇** | **7** | `_tool_search_blue_ocean` `_tool_analyze_profit` `_tool_extract_pain_points` `_tool_compare_competitors` `_tool_get_keyword_data` `_tool_search_products` `_tool_save_candidate` | **整簇已废**（见下） |

### 4.1 零调用清单（8 个）

| 方法 | 行 | 同文件 | via-agent | 具名实例 | 判定 |
|---|---|---|---|---|---|
| `stream` | 1164 | 0 | 0 | 0 | ☠ **死**（旧版关键字路由流式入口，已被 `stream_chat` 取代） |
| `_tool_search_blue_ocean` | 2127 | 0 | 0 | 1（测试） | ☠ 仅测试养活 |
| `_tool_analyze_profit` | 2133 | 0 | 0 | 0 | ☠ 死 |
| `_tool_extract_pain_points` | 2141 | 0 | 0 | 0 | ☠ 死 |
| `_tool_compare_competitors` | 2146 | 0 | 0 | 0 | ☠ 死 |
| `_tool_get_keyword_data` | 2151 | 0 | 0 | 0 | ☠ 死 |
| `_tool_search_products` | 2155 | 0 | 0 | 0 | ☠ 死 |
| `_tool_save_candidate` | 2159 | 0 | 0 | 0 | ☠ 死 |

**`_tool_*` 是什么**：文件里自标为「工具函数（供 LLM 调用）」的**上一代工具**
（agent 内方法 + Pydantic 返回类型）。它们已被 `tools.py` 的 5 个 `StructuredTool` 取代，
但方法体留在原地 ⇒ **新旧两套工具并存，旧的 7 个全无人调用**。
其中 `_tool_save_candidate` 还**复制了** `_current_context_id` / `_current_shop_id` 的读法，
与 `tools.py::_save_candidate_tool` 是**同一段逻辑的两份实现**。

**连带引用（`r199_pr_deadchain.py` 实测）**：删这 7 个方法**不会**产生未使用的 import ——
`adapter` 死区外仍有 12 处、`KeywordData` 2 处、`ProductData` 1 处、
`CompetitorAnalysis` / `BlueOceanOpportunity` / `ProfitAnalysis` / `PainPointAnalysis`
各 1 处落在 `ResearchReport` 的字段注解里。⇒ **可以直接删**（删前确认 `ResearchReport` 自身死活即可）。

---

## 5. 发现的问题（本轮只记录，未改）

| 级别 | # | 问题 | 证据 |
|---|---|---|---|
| **P0** | 1 | **库里 22 条技能的 `tools` 全为 `[]`** ⇒ 5 个工具零引用；第 198 轮绑的 5 条竞品技能**未落库**（`ensure_demo_skills` 已有则不覆盖） | `select tools from skills` ×22 |
| **P0** | 2 | **前端 `api/productResearch.ts` 里 3 个函数的字段名是 camelCase，与后端 snake_case 不符**；该文件自己的注释写着「必须与后端逐字一致」。`analyzeProfit` 传 `sellingPrice`/`costPrice`，而后端 `selling_price`/`cost_price` 是**必填** ⇒ 一旦被调用**必 422** | `api/productResearch.ts:31-42` vs `schemas.py:44-45` |
| P1 | 3 | agent 内 **8 个零调用方法**（7 个 `_tool_*` + `stream`），且 `_tool_save_candidate` 与 `_save_candidate_tool` 是同一逻辑两份实现 | §4.1 |
| P1 | 4 | **`_build_router()` docstring 说「注入 4 个工具」，实际 5 个** —— 且同一方法的注释里又写「5 个工具」⇒ 自相矛盾 | `agent:560` vs `agent:601` |
| P1 | 5 | `router.py` 模块 docstring 端点列表**漏 2 个**（`approval/resume`、`chat/stream`） | `router.py:6-12` vs 实际 8 个 |
| P2 | 6 | `GET /capabilities` 返回**硬编码**能力清单（不探测真实状态）⇒ 与实际会漂移；且前端零调用 | `router.py:310-352` |
| P2 | 7 | `compare_competitors` 前端调用传了后端**不存在**的 `dimensions` 字段（Pydantic 静默忽略）；`includeReviews` 亦被忽略（语义丢失，不报错） | `toolExecutors.ts:229` |

---

## 6. 建议的整改批次（待老板拍板）

| 批次 | 内容 | 风险 |
|---|---|---|
| **B1** | 删 agent 的 7 个 `_tool_*` + `stream`（8 个方法，约 50 行）；同时删测试里对 `_tool_search_blue_ocean` 的引用 | 低（零调用，已用 AST 双口径确认） |
| **B2** | 修前端 `api/productResearch.ts` 的 3 处 camelCase → snake_case（对齐后端），并补/删 `dimensions` | 低（改完必须实测 422→200） |
| **B3** | 决定「技能绑工具」要不要真落地：给 6 条选品技能绑定对应工具（`analyze_blue_ocean` / `analyze_profit` / `analyze_pain_points` / `compare_competitor_listings`...），并解决**「改 seed ≠ 改库」**这个一般性问题（否则下次还会不落地） | 中（涉及演示数据重建策略） |
| **B4** | 修 3 处 docstring 漂移（`_build_router` 4→5、`router.py` 端点列表、`capabilities` 硬编码） | 低 |

★ **B3 是最有业务价值的一条**：5 个工具现在**任何技能都用不上** ——
「技能绑定工具」这个机制建了 5 轮（第 185 轮起），在选品这条链上**从未生效过一次**。

---

## 7. 第 200 轮：整改落地（额外项 + B1–B4，全部完成）

> 老板指令（逐字）：
> `1.★ #8 打破范式：save_candidate（tools.py:194）绕过 service，直调 _service.agent._save_candidate`
> `⇒ 用 service 层做能力盘点会漏掉它，和其他做法统一。`
> `B1 删 8 个死方法 + 测试里对 _tool_search_blue_ocean 的引用 低`
> `B2 修前端 3 处 camelCase → snake_case 低`
> `B3 让「技能绑工具」真落地 + 解决「改 seed ≠ 改库」的一般性问题 中`
> `B4 修 3 处 docstring 漂移 也开始做`

### 7.1 落地读数（AST + 当前库，可复算）

| 项 | 整改前 | 整改后 | 证据 |
|---|---|---|---|
| **额外项** | `tools.py` 直调 `_service.agent._save_candidate` | `_service.save_candidate`（service 层**新增**该方法） | `tools_bypass_agent = []`；`tools_service_calls` 5 个全部形如 `_service.<同名方法>`；`service_has_save_candidate = True` |
| **B1** | agent **62** 个方法（含 8 个零调用） | **54** 个方法 | `agent_still_present = []`；`agent_product_research.py` 123,371 → **119,336 B**（−4,035） |
| **B2** | 3 个函数、7 个 camelCase 键 | 全 snake_case | `ts_camelcase_keys = []`（按**类型字面量键**判，不按源码子串） |
| **B3** | 库里 `tools` 非空 **0** 条 / **0** 处引用 | **14** 条 / **19** 处 | `select name, tools, enabled_agents from skills`（22 条） |
| **B4** | docstring 漏 2 端点；`features` 只列 5 项；`_build_router` 写「4 个工具」 | 8 端点 / 8 features / 5 个工具 | §7.3 |

**为什么 B1 只减了 8 个方法却少了 4,035 字节**：7 个 `_tool_*` 各自带着一段
Pydantic 返回类型注解与一段「上一代」实现，`stream()` 还有一整段关键字路由；
外加残留的小标题 `# ====== 工具函数（供 LLM 调用）======`。
删完实测 `leftover_section_header = False`。

### 7.2 ★ 收尾时又挖出两处「说好的门禁并不存在」

这是本轮最该记住的部分 —— **两处都不是代码错，是「关于代码的说法」错**。

**(1) `router.py` 的 docstring 承诺了一个不存在的测试文件。**
第 199 轮把端点清单补全时，docstring 被写成：

    端点列表（共 8 个 —— 与路由表**逐条对应**，
    由 `tests/test_product_research_capabilities.py` 钉住不许漂移）

而 `backend/tests/` 下**根本没有这个文件**（全仓 grep `capabilit` 只命中
`test_aigc_compliance_failclosed.py` / `test_tool_registry_guard.py`）。
这正是本仓记过多次的「**注释承诺型假门禁**」：注释里许下一句保证，实现里没有任何东西守它。
**它比写错更危险** —— 下一个读代码的人会以为「有门禁，我不用管」。

**修法不是把承诺删掉，而是把文件建出来**（`backend/tests/test_product_research_capabilities.py`），
让那句话变成真的。见 §7.4。

**(2) B2 修完没有任何东西阻止它复发。**
`api/productResearch.ts` 里 `chatWithProductResearcher` 与 `resumeApproval` 的注释
**早就写着**「必须与后端字段逐字一致」，而它上面那三个函数照旧写错 5 轮 ——
说明**注释不构成门禁**。仓里唯一管字段名的门禁是
`frontend/scripts/check-hitl-approval.cjs` 的 D 段，而它**只覆盖 HITL 那条链**
（`context_id` / `decision`），对 `analyzeProfit` / `analyzePainPoints` /
`compareCompetitors` **零覆盖**。

**修法**：新建 `backend/tests/test_frontend_api_field_contract.py`
（前端 `data: {...}` 类型字面量 ⇔ 后端 Pydantic schema 字段集合的**双向对账**，
带显式注册表 + 注册表自校验）。见 §7.4。

### 7.3 B4 三处 docstring 漂移 + 一个更严重的连带发现

| # | 漂移 | 修法 |
|---|---|---|
| 1 | `_build_router()` docstring 写「注入 **4** 个工具」（同一方法的注释里却写「5 个」，自相矛盾） | docstring 改 **5 个工具** |
| 2 | `router.py` 模块 docstring 端点清单**漏 2 个**（`approval/resume`、`chat/stream`） | 补全为 8 个，并写明「与路由表逐条对应」 |
| 3 | `GET /capabilities` 的 `features` 只列 **5** 项（漏 `chat/stream`、`approval/resume`、自身） | 补到 **8** 项，逐项与路由表对齐 |

**★ 连带发现（比三处漂移都严重）：`seed.py` 的 `if __name__ == "__main__"` 不在文件末尾。**

它在文件中部（第 19/26 个顶级语句），后面还有 8 个模块级定义
（`DEMO_SKILL_ANCHOR_TOOLS` / `RETIRED_DEMO_SKILLS` / `DEMO_SKILL_COUNT` …）。
后果是**两条 CLI 路径双双失效**，而 `import` 路径完全正常：

    python -m modules.skills.seed --resync --dry-run
      → 只报 5 条（回填的 9 条不见，因为 DEMO_SKILL_ANCHOR_TOOLS 在 -m 路径下不存在）

    python -m modules.skills.seed --ensure
      → NameError: name 'RETIRED_DEMO_SKILLS' is not defined（报错点落在 ensure_demo_skills() 里）

⇒ **第 195 轮做的「退役技能清理」在 CLI 路径从未生效过**，
而 `NameError` 的报错点与根因**不在同一处**（报错在 `ensure_demo_skills()`，
根因在文件中部那个 guard），极易归因到错误的方向。

修法：把入口语句剪到文件**末尾**，并附一段「为什么必须在末尾」的注释。
**并建门禁 `backend/tests/test_main_guard_position.py`**：扫全仓 `*.py`，
AST 判定 `if __name__ == "__main__":` 必须是**最后一个顶级语句**
（带 `assert guards_seen > 0` 防空跑）。实测全仓 13 处 guard，**1 处坏**（就是它）。

### 7.4 新增/改动的门禁与反向注入

| 门禁 | 判据 | 反向注入（实测转红） |
|---|---|---|
| `backend/tests/test_product_research_capabilities.py`（**新建**） | A：docstring 端点清单 ⇔ 路由表（双向 + 条数）；B：`/capabilities` 的 `features[].endpoint` ⇔ 路由表 | I1 删 docstring 一行 → A 红；I2 改 features endpoint → B 红 |
| `backend/tests/test_frontend_api_field_contract.py`（**新建**） | A：前端键 ⊆ 后端字段；B：前端必填 ⊆ 后端必填；C：注册表路径 == 代码里的路径；D：防空跑 | I3 `selling_price`→`sellingPrice` → A+B 红；I4 改注册表路径 → C 红 |
| `backend/tests/test_main_guard_position.py`（**新建**） | `__main__` guard 必须是最后一个顶级语句 | 把 guard 移回中部 → 红，报「第 19 个顶级语句（共 28 个），后面还有 8 个」 |
| `backend/tests/test_skill_gate.py`（**改**） | 新增「技能 `tools` 里的名字必须已注册」+「锚工具非 None 且已注册 ⇒ `tools` 必须含它」 | `tools=["export_report"]` → A 红；`blueocean-hard-filter` 的 `tools=[]` → B 红 |

四条注入全部**带 sha256 校验还原**（`identical: true`），还原后复跑零红。

**门禁合并组读数**（16 个测试文件，本轮触达面）：
**259 tests / 0 failures / 0 errors / 0 skipped**。

### 7.5 B3 的「改 seed ≠ 改库」是怎么解的

根因：`ensure_demo_skills()` 的设计是「**已有则不覆盖**」
（第 182 轮为「演示模式里改的东西重启后还在」而定）⇒ **改 seed 不等于改库**。

两步：

1. **让绑定真落地**：`seed.py` 新增 `_backfill_anchor_tools()`，
   按 `DEMO_SKILL_ANCHOR_TOOLS`（技能名 → 产出其原料的锚工具）回填
   **未声明工具**的技能的 `tools` 列。三条排除规则：① 已有声明，不碰；
   ② 锚为 `None`（清单/规范/推理/取证型无对口工具，正当留空）；
   ③ 锚工具**悬空未注册**（`is_known_tool` 为假）⇒ 跳过。回填结果导出为
   `DEMO_SKILL_BACKFILLED`，实测**回填 9 条**。
2. **让改动能进库**：走现成的 `resync_demo_skills()` + CLI `--resync`
   （同步 `enabled_agents` / `tools` / `icon`（仅空））。
   ★ 但这条路**本轮之前是坏的** —— 见 §7.3 的 main guard 位置缺陷。

**库里仍留空的 8 条（正当，不是缺口）**：

| 原因 | 技能 |
|---|---|
| 锚为 `None`（无对口工具） | `candidate-risk-scan` / `listing-launch-checklist` / `review-action-plan` / `weekly-review-narrative` |
| 锚工具**悬空**（3 个 Agent 的工具集全仓零装配） | `ad-bid-suggest` / `ad-budget-rebalance` / `aigc-main-image-brief` / `cs-refund-playbook` |

⇒ 第二行与第 198 轮 `TEXT_ONLY_AGENTS` 登记的三家（`ad_analysis` / AIGC / 智能客服）
**是同一批工作**：给它们接工具，这 4 条技能的锚才有着落。**未做，待拍板。**

### 7.6 本轮登记、未处理的（P2）

| # | 事项 | 说明 |
|---|---|---|
| 1 | agent 内 4 个历史遗留未使用 import（`PlatformType` / `ReviewData` / `_prompts` / `datetime`） | **非本轮引入**（B1 的 AST 复核已证明删 8 个方法不产生新的未使用 import） |
| 2 | `GET /capabilities` 仍**硬编码**、不探测运行期真状态 | 本轮只保证它与路由表对齐（判据 B 钉住），「要不要真探测」未决 |
| 3 | 前端 `analyzeProfit` / `analyzePainPoints` / `getProductResearchCapabilities` **零调用** | B2 因此无需同步任何调用方；但这也意味着这三个封装目前是死代码 |

