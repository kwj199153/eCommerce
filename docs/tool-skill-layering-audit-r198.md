# 第 198 轮 · 四问交付：能力核实 · 竞品接工具 · 装配覆盖率门禁 · service 粒度裁决

> 老板本轮四条需求，逐条给**可复算的读数**与**反向注入证据**，
> 并如实标出「没做完 / 结论被推翻 / 与直觉相反」的部分。
>
> 全部读数来自**运行时 / AST 双路取证**，不引用任何 docstring 的自述。
> 原始输出：`.workbuddy/probes/out_r198_*.txt`、`r198_*.xml`。

---

## 摘要

| # | 需求 | 结论 | 关键读数 |
|---|---|---|---|
| 1 | 记忆 / RAG / `knowledge_base` / `platform_rules` 这四类能力现状 | **一问三答，其中一条推翻我上轮的自述** | 记忆 = **注入式已做**；RAG = **已做但只有客服开**（1/8）；KB / platform_rules = **零 AI 通道**（各 12 / 9 端点纯 CRUD） |
| 2 | 范式 B 那 4 家：先拿 `competitor_intel` 试水 | ✅ 完成，含 **4 个连带修复** | 8 工具 × 归属注入；**修掉一个全仓静默缺陷**（`_router` 后缀未归一）；棘轮 33 → 25 |
| 3 | 补一条「装配覆盖率」门禁 | ✅ 完成 | 判据 F + **空转自检**；`test_tool_catalog.py` 13 例 |
| 4 | 审查 service 粒度 | ✅ 完成，**结论与直觉相反** | 老板点名的 5 个候选，实测业务 I/O **≤ 1** ⇒ **不需要拆接口**；真正该动的是 **14 个没被点名的** |

**全链验证**：门禁合并组 **132 例 / 0 红 / 1 skip**（skip 是既有「顶层 intent 恒空」的已知问题）；
**反向注入 6/6 如期转红、5 个被改文件逐字节零漂移**；
全量 pytest **1577 例 / 2 红 / 3 skip** —— 红的两条都在 `test_agent_session_state.py`，
**单跑该文件 46/46 全绿** ⇒ 是 **#803 的顺序依赖遗留**，**本轮零回归**。

---

## 0. 先更正一条：我上轮有一句话说错了

第 197 轮我写过「记忆 / RAG / knowledge_base / platform_rules 这四类……**连工具定义都没有**」。

本轮逐条核实后，这句话**对一半错一半**，必须更正：

| 能力 | 我上轮的说法 | 实测 | 判定 |
|---|---|---|---|
| **记忆** | 「连工具定义都没有」 | `backend/modules/memory/prompt_section.py` 通过 `register_prompt_section` 注册，`BaseAgent._llm_call_node` 每轮 `collect_prompt_sections(PromptContext(agent_name, user_id))` 注入 | ❌ **我说错了** —— 记忆**已经做了**，而且做法是对的（**注入式**，不是工具式） |
| **RAG** | 同上 | `BaseAgent.ENABLE_RAG` / `rag_engine` / `llm_rag_answer` 都在；但 8 个 Agent 里**只有 `customer_service` 把它置 True** | ✅ 「没有工具」成立，但**不是「没做」而是「只开了一家」** |
| **`knowledge_base`** | 同上 | 12 个 REST 端点 + seed，**零 AI 通道** | ✅ 成立 |
| **`platform_rules`** | 同上 | 9 个 REST 端点 + seed，**零 AI 通道** | ✅ 成立 |

**为什么这个更正重要**：记忆做成「工具」是**错的**——工具要模型主动调，
而记忆必须**每轮无条件注入**才生效。我把「注入式能力」误判成「没做成工具」，
等于要求一个本该注入的东西去走工具通道。RAG 同理（本轮未动它）。

**顺带两个发现**（未处理，登记）：

1. `modules/customer_service/knowledge.py` **不用** `modules.knowledge_base`
   —— 知识源有**两套**，客服那套自成一体。
2. `modules/platform_rules/seed.py` 的头号规则就是「Amazon 商品标题字符数限制」
   —— **listing 生成最需要的规则，AI 读不到**（因为没有工具通道）。

---

## 1. 第 2 问：`competitor_intel` 接上工具（试水一家）

### 1.1 接线本身：组合式路由子层，与 listing / PR 逐字同构

工具**只在图节点里生效**：`BaseAgent._llm_with_tools()` 才 `bind_tools`，
而它只被 `_llm_call_node` 调用。本 Agent 的 `analyze()` 从不驱动那张图
⇒ 只给 `super().__init__()` 加 `tools=` 是**装饰性接线**：
注册表不再「悬空」、门禁变绿，而模型手里依旧没有工具 —— **比不接更糟**，因为它把缺口藏起来了。

所以新增 `_get_router()` / `_build_router()` / `_route_via_tools()` 三方法，
把路由子层建成一个 `BaseAgent(agent_name=f"{self.agent_name}_router", tools=competitor_intel_tools, ...)`，
`stream_chat` 改为「工具环路优先，失败回退关键词路由」。

| 面 | 文件 | 改动 |
|---|---|---|
| 核心 | `modules/competitor_intel/agent_competitor.py` | 新增 `import json` + `ContextVar` 归属；`_router` 懒加载（避开 `tools → service → agent` 循环导入）；三个新方法；`stream_chat` 改为工具环路优先 |
| 工具 | `modules/competitor_intel/tools.py` | 新增 `_shop_id()`；**8 处**调用全部补 `store_id=` |
| 归一 | `modules/skills/agents.py` | 新增 `ROUTER_SUFFIX` + `business_agent_name()`（见 §1.3） |
| 归一 | `modules/skills/provider.py`、`selected_skill_section.py` | 两条技能注入通道各接一次归一 |
| 目录 | `modules/skills/tools_catalog.py` | 真源表 `competitor_intel … 8`（合计 28 → **36**）；新增 8 条目录项（全 `EFFECT_READ_ONLY`）；新增 `TEXT_ONLY_AGENTS` |
| seed | `modules/skills/seed.py` | **5 条**竞品技能绑工具（见 §1.4） |

### 1.2 连带修复 ①：8 个工具**一个都没传归属**（从未暴露过的潜伏缺陷）

`CompetitorIntelService` 收到 `store_id=None` ⇒ `_ensure_source()` 直接判 `no_data`，
理由写的是「未绑定店铺上下文（**请求缺少 X-Shop-ID**）」。
⇒ 改造前这 8 个工具**永远拿不到数据**，而且报错文案会把排查引向一个**不存在的问题**。

缺陷此前不可见的原因正是「注册表悬空、没有任何 Agent 装配它们」
—— **「先接线、再谈效果」这一步才把它照出来**。

归属只走 `ContextVar`（**服务端注入**），写入点是 `_route_via_tools()`（工具被调用之前），
**不是工具形参**：做成形参等于让模型决定租户边界。

### 1.3 连带修复 ②：`_router` 后缀全仓从未归一（**重大既有缺陷**）

技能启用（`skills.enabled_agents`）存的是**业务** `agent_name`
（`service._validate_agents` 只接受 `AGENT_CATALOG` 里那 8 个值），
而两条注入通道都按 `agent_name in enabled_agents` 过滤：

- 目录（第一级披露）：`provider._catalog_provider` → `build_catalog_for`
- 正文（点名加载）：`selected_skill_section` → `provider.read_skill_text`

⇒ 不做归一，**走工具通道的 Agent 技能目录恒为空、点名读不到正文，而且一处日志都没有**。
这是第 197 轮「技能目录不生效」的根因之一，**影响范围是 listing / product_research / review_analyst / competitor_intel 四家**（不是只影响新接的这家）。

修法（唯一真源）：`agents.business_agent_name()` 一处实现，两个 provider 共用；
并新增形态判据 `test_router_suffix_constant_matches_all_sub_layers`
把「`ROUTER_SUFFIX` 必须与全仓 `_build_router()` 真实用的后缀逐字一致」钉死。

### 1.4 连带修复 ③：5 条竞品技能绑上工具

`agents` 才是 seed 技能的真实字段（第 197 轮我的探针**字段名取错**了）。

| 技能 | 绑定工具 |
|---|---|
| `price-drop-triage` | `monitor_competitor` |
| `review-pain-mining` | `analyze_competitor_reviews` |
| `competitor-weekly-digest` | `monitor_competitor`, `track_batch_asins`, `detect_intruders` |
| `competitor-anomaly-triage` | `monitor_competitor`, `detect_intruders` |
| `competitor-strategy-sim` | `analyze_pricing_strategy`, `compare_competitors`, `analyze_market_share` |

### 1.5 连带修复 ④：棘轮收紧 33 → 25

`tests/test_tool_registry_guard.py` 的 `KNOWN_ORPHAN_REGISTRIES` 删掉 competitor 那条
（改插入注释块留痕），`ORPHAN_TOOL_BUDGET` **33 → 25**。棘轮语义不变：**只许往下走**。

---

## 2. 第 3 问：装配覆盖率门禁

### 2.1 先纠正一个前提：**门禁早就有一条，但它是「注册表中心」的**

`tests/test_tool_registry_guard.py` **早已有**「悬空注册表棘轮」
（`KNOWN_ORPHAN_REGISTRIES` + `ORPHAN_TOOL_BUDGET`）。
⇒ 我上轮说「**没有任何一条门禁**能拦住 27 个孤儿」**是错的**。

棘轮是**注册表中心**（「这个注册表有没有被任何 Agent 引用」）；
缺的是**以 Agent 为中心**的那条（「这个 Agent 有没有工具」）。两者不是一回事：

| 视角 | 能拦住 | 拦不住 |
|---|---|---|
| 注册表中心（既有棘轮） | 新增一个悬空注册表 | 一个 Agent **零工具**（它可能根本不该有工具） |
| **Agent 中心（本轮新增）** | Agent 静默无工具 | —— |

### 2.2 新增判据 F（`tests/test_tool_catalog.py`）

```
AGENT_CATALOG 每个 Agent 要么有工具，要么在 TEXT_ONLY_AGENTS 白名单登记
```

三条子判据：

1. 白名单里的 Agent 必须**真在** `AGENT_CATALOG` 里（写错名字不算数）；
2. `known - with_tools - declared` 必须为空（这是要拦的那 27 个孤儿）；
3. `declared & with_tools` 必须为空（**反向**：已经接了工具的 Agent 不许留在白名单里
   —— 否则白名单会腐烂成一句谎话）。

外加 `test_text_only_agents_are_not_vacuous`：白名单条目的**理由必须 ≥ 20 字**
（防「占位式登记」）。

`TEXT_ONLY_AGENTS` 本轮登记 **3 条**（`ad_analysis` / `AIGC 媒体生成器` / `智能客服`），
每条带理由。注意这三家是**范式 B 的另外三家**——本轮只接了一家（`competitor_intel`），
所以它们必须是**显式登记**而不是「不出现」，这样下一次要接谁、还剩几家，一眼可见。

---

## 3. 验证：读数与反向注入

### 3.1 门禁合并组（7 个文件，一份 junit）

| 文件 | 例数 |
|---|---|
| `test_competitor_intel.py` | 62 |
| `test_skill_gate.py` | 33 |
| `test_tool_catalog.py` | 13 |
| `test_hitl_policy.py` | 7 |
| `test_intent_single_source.py` | 7 |
| `test_skill_router_agent_name.py` | 5 |
| `test_tool_registry_guard.py` | 5 |
| **合计** | **132 例 / 0 红 / 0 error / 1 skip** |

该 skip 是既有已知问题（`test_top_level_intent_is_populated`：顶层 `intent` 字段从未被填充，恒空串）。

### 3.2 反向注入 6/6（`r198_reverse_inject.py`）

判定「红」读的是 **`--junitxml` 的断言明细**（哪一条用例失败、消息是什么），
**不看退出码** —— 退出码在本仓已知不可信。每条注入之间**还原全部被改文件并逐字节校验**。

| 注入 | 期望红 | 实测 |
|---|---|---|
| 基线（不改） | 全绿 | ✅ 132/132 |
| I1 删 `provider._catalog_provider` 的归一调用 | 目录通道那条 | ✅ **只有它**（实得 `['ListingGenerator_router', 'competitor_intel_router', 'secretary']`） |
| I2 删 `selected_skill_section` 的归一调用 | 点名通道那条 | ✅ **只有它**（实得 `[('competitor_intel_router', 'price-drop-triage')]`） |
| I3 把 `business_agent_name` 改成恒等函数 | 上面两条**同时**红 | ✅ 2 条 |
| I4 把竞品子层后缀改成 `-router` | 后缀一致性那条 | ✅ **只有它** |
| I5 删 `tools=competitor_intel_tools` | 8 工具接线那条 | ✅ **只有它**（漏装 8 个工具全列出） |
| I6 把第一处 `store_id=_shop_id()` 改成 `None` | 归属那条 | ✅ **只有它**（点名 `monitor_competitor`） |

**收尾复核**：5 个被改文件（`agent_competitor.py` / `tools.py` / `skills/agents.py` /
`provider.py` / `selected_skill_section.py`）全部 `byte-identical`，**零漂移**。

**★ 一个顺带读出来的判据互补关系**（I6）：AST 形式的
`test_every_service_call_in_tools_passes_store_id` **没红** ——
因为 `store_id=None` 里仍然有 `store_id=` 这个子串，形态判据看不出**值**变了。
是**运行时**那条（`test_all_competitor_tools_carry_shop_attribution`）抓住的。
⇒ 又一条「形态判据 + 行为判据必须配对」的实例。

### 3.3 全量回归

| 口径 | 结果 |
|---|---|
| 全量 `pytest tests` | **1577 例 / 2 红 / 3 skip**（rc=1） |
| 红的两条 | 都在 `tests/test_agent_session_state.py`（`test_real_pg_roundtrip_upsert_delete_and_ownership`、`test_table_shape_matches_the_contract`），异常在 `_purge()` / 建连阶段，是 SQLAlchemy async + 事件循环的形状 |
| 单跑该文件 | **46 例 / 0 红** |

⇒ **单跑绿 / 全量红 = 顺序依赖**，即既有的 **#803**，与本轮改动无关（本轮改的是
`competitor_intel` 与 `skills` 两块，`test_agent_session_state` 不碰这两块的状态）。
**本轮零回归**。

---

## 4. 第 4 问：service 粒度裁决 ★核心

### 4.1 先纠正口径：**参数个数与原子性正交**，而且可以反向

老板那句「**参数少 ≠ 原子**」是对的。但同一枚硬币的另一面也成立，
而且更容易被忽略：**参数多 ≠ 不原子**。

| 老板点名 | 工具参数 | service 函数 | 行 | service 参数 | 业务 I/O | 私有 helper | 判定 |
|---|---|---|---|---|---|---|---|
| `generate_product_image` | **16** | `aigc_media.generate_product_image_service` | 24 | 1 | 1 | 0 | **原子** —— 16 个参数是「出图的旋钮本来就多」（`material` / `shape` / `view_angle` / `need_logo` / `background_rule`…），而函数体只有一次调用 |
| `analyze_blue_ocean` | 9 | `product_research.analyze_blue_ocean` | 55 | 1 | **0** | **3** | **已内聚** —— 3 个子步骤早已抽成 `_generate_mock_blue_ocean_products` / `_apply_filters` / `_calculate_blue_ocean_scores` |
| `analyze_profit` | 8 | `product_research.analyze_profit` | 66 | 1 | 1 | 0 | 一次取数（`get_product_detail`）+ 纯计算 8 块输出 |
| `generate_complete_listing` | 6 | `listing_generator.generate_complete_listing` | 35 | 1 | **1** | 0 | **编排入口** —— 体里只有一次 `self.agent.invoke(...)`，把标题/五点/描述/关键词/SEO 交给**子 Agent 的图** |
| `weekly_report` | 1 | `review_analyst.weekly_report` | 37 | 2 | **0** | **5** | 一次取数（`_source()` 是同步函数）+ **5 个已内聚子步骤** |

**⇒ 5/5 都不需要拆接口。** 老板点名的 5 个「不原子」候选，
实测全部是「**单次取数 + 内部已内聚的多视图计算**」。

### 4.2 三条可测量判据（替代「参数个数」）

| 判据 | 量什么 | 为什么不能用别的代替 |
|---|---|---|
| **A：业务 I/O 次数 ≥ 3** | 一次调用里串了几个**领域动作** | `await count` 会把 `commit/refresh/flush/rollback`（**事务簿记**）算进去 ⇒ 得出「`upsert_monitor` await=5 很重」的错误结论，实际它业务 I/O 只有 **1** 次 |
| **B：输出块数 ≥ 8** | 一次调用向调用方承诺几类结果 | ★ **这条必须人工判定，不能自动化** —— `record_to_dict`(38) / `serialize`(15) / `rule_to_dict`(13) / `faq_to_dict`(11) 这些**序列化函数的输出块多是天职**，不是「不原子」 |
| **C：私有 helper ≥ 4 且 行 ≥ 35** | 内部已内聚出几个子步骤 | C 命中反而说明**已经拆过了**（`weekly_report` helper=5 ⇒ 它内部是干净的） |

**自动化只能信 A**（客观、几乎无假阳性）；B 需要人判；C 是「已拆」的证据而非「该拆」的证据。

### 4.3 真正命中判据 A 的 14 个 —— **全在老板没点名的地方**

| 文件 | 函数 | 行 | 参 | 业务 I/O | 簿记 | 业务 I/O 明细 |
|---|---|---|---|---|---|---|
| `voice_clone` | `enroll` | 83 | **10** | **9** | 0 | 查重→存样本→3×upsert→`create_voice`→等就绪→4×upsert |
| `memory` | `save_memory` | **113** | 3 | 5 | 1 | `snapshot`, `_read_entry_rows`, `execute`, `_write_log`, `_ensure_profile` |
| `memory` | `reset_memory` | 24 | 1 | 5 | 0 | 同上（无 `execute` 的写入版） |
| `memory` | `apply_distilled` | 61 | 3 | 4 | 1 | 读 → 写 → 记日志 → 建 profile |
| `voice_clone` | `preview` | 46 | 4 | 4 | 0 | `get_record`, `synthesize`, `persist_remote_audio`, `upsert_record` |
| `knowledge_base` | `delete_kb` | 25 | 2 | 4 | 1 | 级联删 faq / doc / kb |
| `voice_clone` | `refresh_status` | 22 | 1 | 4 | 0 | `get_record`, `query_voice`, 2×`upsert_record` |
| `skills` | `update_skill` | 86 | 4 | 3 | 2 | `get_skill_by_name`, `is_favorited`, `generate_skill_icon` |
| `memory` | `claim_distill_run` | 58 | 2 | 3 | 0 | |
| `voice_clone` | `delete_record` | 50 | 3 | 3 | 1 | `delete`, `delete_voice`, `execute` |
| `conversation` | `append_message` | 29 | 4 | 3 | 0 | 归属校验 → 2×`execute` |
| `knowledge_base` | `list_knowledge_bases` | 22 | 1 | 3 | 0 | **2×`_count_map` + `execute` = N+2 次 count 查询** |
| `knowledge_base` | `get_kb_dict` | 15 | 2 | 3 | 0 | 3×`execute` |
| `skills` | `list_skills` | 14 | 2 | 3 | 0 | `filter_accessible_skills`, `_favorite_ids`, `execute` |

**分布很有信息量**：`memory` 3 个、`voice_clone` 4 个、`knowledge_base` 3 个、
`skills` 2 个、`conversation` 1 个 —— **一个 AI 工具通道都没有的模块居多**。
它们不是「工具太粗」，而是「**业务本身是多步流程**（复刻音色的审核状态机、记忆的读改写记）」。

### 4.4 处理方式：**不拆接口**，分三档

**档 1（默认，0 接口变更）：靠「描述消歧 + 粗/细分层」，不靠拆签名。**

`listing_generator` **已有现成范式**（本轮遵守「禁另发明」）：

```python
_fine_grained_tools = [optimize_listing_title, generate_bullet_points,
                       generate_product_description, generate_search_terms]
_coarse_grained_tools = [generate_complete_listing, optimize_listing,
                         analyze_listing_seo, generate_ab_test_variants]
listing_tools = _fine_grained_tools + _coarse_grained_tools
```

关键不在分层，而在**每条 `description` 都写了触发条件**：

> `generate_complete_listing`：……**当用户要「生成/写一套完整 listing」且没有指定只做标题/五点等单一部件时使用。**
> `optimize_listing_title`：……**当用户想改/润色/优化标题时使用。**

**为什么优先这个**：拆接口会把**同一个下游数据拉 N 遍**（业务 I/O × N），
而 LLM 侧消歧**零 I/O 成本**；且工具包装层已经是原子的（同轮读数：46 个工具实现平均 1 次 `await`）。

**档 2（只对「业务 I/O ≥ 3 **且** ≥ 50 行」做**内部**拆分，**不改对外签名**）**：
本轮 14 个里只有 **2 个**同时满足 —— `voice_clone.enroll`（9 / 83 行）与 `memory.save_memory`（5 / **113 行，全仓最大**）。
其余 12 个拆了只会把一次事务切成两段，收益为负。

**档 3（先修事务边界，再谈粒度）**：见 §4.5。

### 4.5 顺带发现：**事务边界**问题（不是粒度问题，别混在同一个数字里）

把 `commit` / `refresh` / `flush` / `rollback` 单独算之后，浮出两个：

| 函数 | 簿记次数 | 明细 | 问题 |
|---|---|---|---|
| `monitors.upsert_monitor` | **4** | `commit, refresh, commit, refresh` | **事务边界开合 2 轮** —— 中间那次 `commit` 一旦成功、后段失败，就留下半截状态 |
| `skills.set_favorite` | **3** | `commit, commit, rollback` | 两条路径各 commit 一次 + 异常回滚，**边界与业务分支耦合** |

另有 **13 个**函数是 `commit, refresh` 组合（正常形态，不作为问题登记）。

**★ 为什么必须把它们从「粒度」里拆出来**：`upsert_monitor` 在混算口径下
「await=5、看起来最重的几个之一」，按粒度去拆它 —— **改错了地方**。
它的病在事务边界，修法是「一段事务只 commit 一次」。

---

## 5. 遗留与建议的下一步

### 5.1 已登记待办

| # | 事项 | 状态 |
|---|---|---|
| **#803** | `test_agent_session_state` 两条真 PG 用例**顺序依赖**红（单跑绿） | 未修（本轮已确认与本轮改动无关） |
| **#806** | 本轮完成裁决；§4.4 档 2 的 2 个函数（`enroll` / `save_memory`）、§4.5 的 2 个事务边界 | 待老板裁决 |
| **#808** | 见 §5.2 —— **建议但未实施** | 待裁决 |
| 前轮遗留 | 4 个仍 > 30 KB 的 skill；触发语「只写不读」撞车；`_pending/` 积压 6 份 / 35.4 KB（热区仅余 2,218 B） | 未处理 |

### 5.2 建议补的门禁（**未实施，等裁决**）：把 listing 的既有范式变成可执行判据

**要钉的现象**：粗粒度工具存在的**全部合法性**，建立在「description 能把模型劝到正确的那个」上。
而 `description` 现在**没有任何判据** —— 抹掉「当…时使用」，`test_tool_catalog` 的计数不会变，全绿。

**判据（候选 3 条）**：

1. `listing_tools` 必须**同时**包含非空的 `_fine_grained_tools` 与 `_coarse_grained_tools`；
2. 两者的每个工具的 `description` 必须含**触发条件从句**（「当…时使用」形态）；
3. 粗/细分层不许被合并回一个平坦列表（形态判据）。

**反向注入（拟）**：① 删 `_coarse_grained_tools` 一项 → 红；
② 抹掉某条 description 的「当…时使用」→ 红；
③ **交换两者的拼接顺序 → 必须不红**（顺序无意义，用来证明判据不是靠位置作弊）。

**为什么值得做**：这是「参数少 ≠ 原子」在本仓**唯一的可执行出口** ——
否则 §4.4 档 1 的结论就只是一段口头建议，下一轮还会有人问同一个问题。

### 5.3 本轮没做、需要明说的

- **范式 B 的另外三家**（`ad_analysis` / `AIGC 媒体生成器` / `智能客服`）**没有接工具**，
  本轮按老板指令只试水 `competitor_intel` 一家。它们现在在 `TEXT_ONLY_AGENTS` 里**显式登记**，
  所以「还剩几家」是可数的（3 家 / 19 个孤工具：ad 6 + AIGC 9 + 客服 4），不会再次隐身。
- §4.4、§4.5 的所有改动**一行代码都没动** —— 本轮第 4 问只做审查与裁决。
