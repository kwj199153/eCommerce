# Agent 能力缺口评审（第 141 轮）

> 题目：**自主规划 / HITL / 多轮记忆** —— 对照参考实现（WorkBuddy 的 Agent 运行时思路）逐轴体检
> 口径：所有数字均为**实测**（AST 扫描 / 全仓正则计数 / 运行时路由表），非估算
> 结论分四批，按「投产价值 ÷ 改动半径」排序

---

## 一、一句话结论

**这个项目不是「Agent 缺功能」，而是「Agent 只做了一半」——**

同一个 `BaseAgent` 基类上挂着**两个互斥的 LLM 槽位**，把 7 个业务 Agent 劈成了两条互不相通的链路：

| 链路 | Agent | 具备 | 缺失 |
|---|---|---|---|
| 槽位① LangChain 图内核 | 店秘书、选品分析师、Listing 优化师（**3 个**） | 工具循环、LLM 自主选工具、跨轮 checkpointer、HITL 接线（仅选品） | 无规划、无子 Agent、无上下文管理 |
| 槽位② DashScopeLLM 原语 | 广告、AIGC、竞品、客服（**4 个**） | 提示词 + 关键词表 + `structured_chat` | **结构上不可能有**工具循环 / 记忆 / HITL |

而槽位②的四个 Agent，其「分析结果」实际是 `random` 生成的伪数据（**96 处 `random.*` 调用**）。
讽刺的是：**它们的工具已经全部写好了**（32 个 `StructuredTool`），只是从没被挂进任何 Agent。

---

## 二、逐个事实（可复算）

### 2.1 工具面：50 个注册项，18 个装配，32 个悬空

| 注册表 | 条目 | 装配点 |
|---|---|---|
| `navigation_tools` | 5 | `modules/secretary/agent.py` ✅ |
| `listing_tools` | 8 | `modules/listing_generator/agent_listing.py` ✅ |
| `product_research_tools` | 5 | `modules/product_research/agent_product_research.py` ✅ |
| `ad_analysis_tools` | 6 | **无** ❌ |
| `aigc_tools` | 8 | **无** ❌ |
| `competitor_intel_tools` | 8 | **无** ❌ |
| `customer_service_tools` | 4 | **无** ❌ |
| `review_analyst_tools` | 6 | **无** ❌（`review_analyst` 模块连 `router.py` / agent 都没有） |

### 2.2 伪数据面：4 个 Agent 的产物不是真实数据

| Agent | `random.*` 调用 | `_generate_*` / mock 生成器 |
|---|---|---|
| `agent_ad.py` | **49** | 11 |
| `agent_aigc.py` | 28 | 6 |
| `agent_competitor.py` | 8 | 12 |
| `agent_cs.py` | 11 | 3 |
| `agent_listing.py` | 0 | 11 |
| `agent_product_research.py` | 0 | 3 |
| `agent.py`（secretary） | 0 | 0 |

调用链实证：`AdAnalysisService.diagnose()` → `AdAgent.invoke()` → `_classify_intent()` → `_analyze_diagnosis()` → `_generate_metrics()` → **`random.randint`**。
前端 `docs` 里写的「已接真后端」只意味着**发了 HTTP 请求**；后端收到后仍然返回随机数。
→ 前端门禁 `scripts/check-tool-reality.cjs` 钉的是「真调用执行器数量」，**量的是有没有发请求，不是数据真不真** —— 门禁绿，但用户拿到的是假数据。

### 2.3 HITL 面：覆盖率 1/7，且策略是手写名单

- 唯一接线点：`modules/product_research/agent_product_research.py:420  hitl_tools=["save_candidate"]`
- 其余 6 个 Agent **0 接线**；`secretary` / `listing` 的图**没有 checkpointer 的强制前提**（`interrupt()` 在没有 checkpointer 的图上直接抛，不是「降级为不审批」）
- 副作用判定靠 `_APPROVAL_GATED_INTENTS = frozenset({"save_candidate"})` 手写名单，**新增副作用工具不会自动获得审批**
- **没有「澄清」工具**：现在是把「≥2 个核心参数缺失就调 handoff」写进 `SECRETARY_SYSTEM_PROMPT` 的规则里，靠模型自觉
- 前端侧已经完备：`useApprovalFlow.ts` + `PendingApprovalCard.vue`（三条诚实性约束写得很好，可作为其他能力改造的模板）

### 2.4 记忆面：三个存储、三种持久性、三套口径

| 存储 | 落点 | 装什么 | 失效条件 |
|---|---|---|---|
| LangGraph checkpointer | PostgreSQL（`core/checkpoint.py`） | 消息历史、图状态、待审批中断态 | 键变更即全部失联（silent） |
| `_session_state` | **Python 进程内存**（`agent_product_research.py:280`） | 蓝海结果缓存（供「第 1 个」指代）、`pending_save` 槽位填充态 | **重启即丢；`UVICORN_WORKERS>1` 时跨 worker 不可见** |
| `sessionId` | 前端浏览器本地 | 仅一个会话 ID | 换浏览器即丢 |

- **同一个会话的记忆分住两个存储**：消息在 PG（可跨重启），槽位/指代在内存（不可跨重启）。用户「先说一半、重启后再说另一半」= 槽位丢了但历史还在 ⇒ 表现为「AI 忘了我在补什么」。
- **`MemoryEvolution.vue`（「记忆与进化」页）是硬编码假页面**：`rawMemory = ref(\`# 工作背景 ...\`)`，`onSaveMemory` 只写本地 `ref`，**零 API 调用**。前端承诺了「每晚自动整理更新」，实现是零。

### 2.5 规划面：0

- `create_react_agent` 全仓 **0** 次；`StateGraph` 只在 `base_agent.py` 出现 **1** 次，图结构固定为 3 节点
  `START → llm_call →[should_continue]→ tool_node / respond`
- `max_iterations` 三处硬编码（secretary=6 / router=4 / 默认=10），**没有 token / 成本 / 时间预算**
- `AgentState.structured_response` 由 `_respond_node` 产出，**生产代码 0 个消费者**（仅 2 处测试断言）⇒ 死输出
- `AgentState.metadata` **0 处读取**（源码注释已自认是「死重量」）

### 2.6 上下文管理面：0

`base_agent.py` 中 `trim` / `summarize` / `compact` / `truncate` / `window` / `prune` **全部 0 命中**。
历史随 checkpointer 无限增长，唯一的防护是 `_sanitize_tool_call_pairing()` —— 那是**事后清洗**（把孤儿 `tool_calls` 剔掉以免 DashScope 400），不是**事前裁剪**。

### 2.7 意图识别面：至少 7 份实现

| # | 实现 |
|---|---|
| 1 | `modules/ad_analysis/agent_ad.py:323 _classify_intent` |
| 2 | `modules/aigc_media/agent_aigc.py:1635 classify_intent` |
| 3 | `modules/competitor_intel/agent_competitor.py:305 _classify_intent` |
| 4 | `modules/customer_service/agent_cs.py:415 _classify_intent` |
| 5 | `modules/listing_generator/agent_listing.py:464 _classify_intent` |
| 6 | `modules/product_research/agent_product_research.py:994 _classify_intent` |
| 7 | `modules/secretary/intent_shortcut.py`（决策层 B 短路） |
| 8 | `frontend/src/mock/secretaryBrain.ts:127 recognizeSecretaryIntent` |
| 9 | `frontend/src/mock/competitorIntel.ts:44 detectIntent` |

同一句「帮我看看广告」在 9 个地方有 9 套判据，**必然漂移**。

### 2.8 子 Agent / 委派面：无

- `metadata={"role": "sub_agent_router"}` 的「路由子层」是 **同一个 Agent 类的另一个实例**，与主层共用同一段消息历史口径，**不是上下文隔离的委派**
- `handoff_to_agent` 只产出一个 `{"action": "handoff", ...}` 标记，由前端 `dispatchAppAction` 消费 —— 是 **UI 动作**，不是 Agent 间委派

---

## 三、十个能力轴对照（参考实现 vs 本项目）

| 轴 | 参考实现的做法 | 本项目实测 | 优先级 |
|---|---|---|---|
| 自主规划 | todo 清单**外置**为状态，跨上下文压缩存活；提供「先规划后执行」的模式 | 固定 3 节点 ReAct；`max_iterations` 硬截断 | **P0** |
| 上下文管理 | 自动压缩；子任务在隔离上下文里跑，只把摘要回传 | 0 处裁剪 / 摘要；靠事后清洗孤儿 tool_call | **P0** |
| 子 Agent 委派 | 独立上下文 + 独立工具集 + **只回摘要** | 无（「路由子层」共用历史） | **P0** |
| 工具渐进披露 | 工具 schema 按需加载，不一次全塞进 prompt | 全量 `bind_tools`；32/50 注册项从未装配 | **P0** |
| HITL | 危险操作走审批；提供独立「澄清」工具；模式可切换 | 覆盖 1/7；名单手写；澄清只是提示词规则 | **P0** |
| 记忆分层 | 各层有明确**上限 + 蒸馏规则 + 读写口** | 三处散落，口径不一；「记忆」页是假页面 | **P0** |
| 意图识别 | 单一模型判断 | **9 份实现** | P1 |
| 失败与降级 | 明确错误语义 | 基类这块做得好（`_mock_result` 返回 `success=False`），但伪数据链路把「降级」变成了「常态」 | P1 |
| 可观测 | 事件流 + 用量计量 | SSE + `record_llm_usage` 已通，但只覆盖**图路径** | P2 |
| 变更防护 | —— | **你的强项**：3 道新门禁 + 9 条反向注入；全量 998 / 0 失败 | ✅ |

---

## 四、设计不合理清单（按严重度）

| # | 不合理 | 为什么是问题 |
|---|---|---|
| 1 | **两个 LLM 槽位不可互换** | 一半 Agent 拿不到工具/记忆/HITL，另一半拿不到 `structured_chat`/RAG。同一个基类两种语义，业务侧按「继承谁」决定能力上限 —— 这不是设计，是历史包袱 |
| 2 | **伪数据当作降级形态** | `random` 生成「广告诊断报告」，前端还配了完整结果卡渲染 ⇒ 用户无法分辨真假。与项目既定原则（「空状态优于虚构默认」）直接冲突 |
| 3 | **副作用判定是手写名单** | 新增一个写库工具，默认**不审批**。安全属性靠人记得去改一个 `frozenset` |
| 4 | **记忆分住两个持久性不同的存储** | 槽位/指代在进程内存、消息在 PG ⇒ 重启后历史在、上下文没了；多 worker 直接错乱 |
| 5 | **`_respond_node` 产出死输出** | `structured_response` 0 消费者，却占着图的一层 |
| 6 | **意图识别 9 份实现** | 改一句触发词要改 9 个地方，且没有门禁钉住一致性 |
| 7 | **`AgentState.metadata` 只写不读** | 已在注释里自认，但没删 |
| 8 | **门禁量错了对象** | `check-tool-reality.cjs` 数「有没有发 HTTP」，不数「数据是否真实」⇒ 假数据下门禁全绿 |
| 9 | **`review_analyst` 前后端能力不对齐** | 前端 `AGENT_TOOLS['review-analyst']` 有 6 个工具卡片，后端**零 router、零 agent**、6 个工具零装配 |
| 10 | **HITL 的边界靠「有没有 checkpointer」隐式决定** | 没有 checkpointer 时 `interrupt()` 直接抛；`graph_for_session(None, None)` 正好会走到这条路径 ⇒ 「无会话」= 「所有审批操作被拒」，语义没显式声明 |

---

## 五、四批改造方案

### 批 A · 让 Agent 真起来（**最高价值 / 改动半径中等**）

**目标**：4 个「假 Agent」变成真 Agent，且产物不再是随机数。

| 改动点 | 文件 | 动作 |
|---|---|---|
| A1 挂工具 | `ad_analysis` / `aigc_media` / `competitor_intel` / `customer_service` / `review_analyst` 的 agent | 照 `product_research._build_router()` 范式加工具路由子层（绑 checkpointer + `checkpoint_ns`） |
| A2 切伪数据 | 各 `service.py` | 改为读真实数据源（`platforms/*/client.py`）；拿不到 ⇒ **空状态 + 显式原因**，删掉 `_generate_*` |
| A3 补模块 | `modules/review_analyst/` | 补 `agent.py` + `router.py` + `prompts.py`（现在只有 service/tools/schemas） |
| A4 门禁改正 | `scripts/check-tool-reality.cjs` | 把「真调用」判据从「发了请求」升级为「**返回非 mock 标记**」，并加一条 `random` 出现在生产 agent 里即失败的门禁 |

**验收**：每个 Agent 能对同一句话产出一条可追溯到数据源的结果；`random.*` 在生产 agent 中计数 = 0。

### 批 B · HITL 从「一处接线」到「策略化」

| 改动点 | 动作 |
|---|---|
| B1 审批策略表 | 用「工具是否声明 `side_effects`」替代手写 `frozenset`；未声明的默认 **fail-closed**（要么拒绝，要么强制审批） |
| B2 覆盖到全部副作用工具 | 把 `_build_router(hitl_tools=...)` 从常量改为**由策略表推导** |
| B3 澄清工具化 | 新增 `ask_clarification` 工具（类比 `AskUserQuestion`），从提示词规则升级为**工具**，前端复用 `PendingApprovalCard` 范式 |
| B4 无会话语义显式化 | `graph_for_session` 缺会话时不静默走「拒绝」路径，而是返回带原因的显式状态 |
| B5 门禁 | 新增：任何 `side_effects=True` 的工具，若未出现在某 Agent 的 `hitl_tools` 里 ⇒ 测试红；反向注入证明能打穿 |

### 批 C · 记忆收口 + 规划器 + 上下文管理

| 改动点 | 动作 |
|---|---|
| C1 槽位/指代落库 | `_session_state` 从进程内存搬到 **PG 会话表**（或并入 `AgentState`，让它随 checkpointer 走）；口径与 checkpointer 统一 |
| C2 `MemoryEvolution` 落实 | 要么接真后端（长期记忆 CRUD + 上限 + 蒸馏规则），要么下线；**不能留一个假页面承诺「每晚自动整理」** |
| C3 规划器 | 新增 `plan_tasks` / `update_task` 工具（todo 外置落库），子任务状态可在 UI 展示 |
| C4 上下文管理 | 在 `_llm_call_node` 前加裁剪/摘要钩子：按 token 预算裁历史 + **折叠旧工具结果为摘要**；门禁钉住「长时间会话不超预算」 |
| C5 预算化 | `max_iterations` 三处硬编码 → 统一预算（迭代 / token / 墙钟），超限显式报错 |

### 批 D · 子 Agent 委派 + 意图收口

| 改动点 | 动作 |
|---|---|
| D1 上下文隔离的委派 | 子 Agent 跑在**独立 thread**（不同 `checkpoint_ns`），只把结构化摘要回传父级；替代现在的「共用历史」 |
| D2 意图识别收唯一真源 | 9 份 → 1 份（LLM 分类 + 关键词表降级为加速器）；门禁：生产代码里只允许一处 `_classify_intent` |
| D3 删死重量 | `structured_response` + `AgentState.metadata` 二选一：接上消费者，或删掉 |

---

## 六、附：为什么这不是「重构冲动」

批 A 的实测依据是「**32 个工具的代码已经写完了**」——改造不是「从零做工具」，而是「把已有的挂上去 + 掐掉伪数据源」，边际成本极低、边际收益极大。

批 B–D 每一项都有**可执行门禁**兜底（本仓已有 3 道门禁 + 反向注入的成熟范式），不会变成「改完不知道有没有变好」。

---

*生成：第 141 轮 · 证据来源：全仓 AST 扫描 + 正则计数 + 运行时路由表；所有数字可用同口径脚本复算*

---

# 附 A · 那 32 个工具究竟是什么（第 141 轮追加取证）

老板追问：**「32 个工具有哪些是什么，确定不是多于无用的历史遗留吗」**

本节回答。探针 `r141_tools_audit_v2.py` → `r141_tools_audit_v2.txt`；全部数字可用同口径脚本复算。

## A.0 先纠正我自己的一个错误

上一轮「50 个工具、32 个悬空」——**数字对，但成色判断是我脚本的 bug**：

v1 探针按 `node.args[0]` 取工具函数，但真实写法是
`StructuredTool.from_function(coroutine=_diagnose_tool, name=..., ...)` —— **`coroutine` 是关键字参数**。
于是每个工具体都取到空字符串，输出「**50/50 静态桩**」的假结论。
v2 已修，并把判据加深到**全链路 3 跳**（工具 → service/agent → 数据源）。**下面是修正后的结果。**

## A.1 清单（32 个悬空工具）

### ① `ad_analysis_tools`（6）· 广告分析

| 工具 | 能力 | 链路末端 |
|---|---|---|
| `diagnose_ad_account` | 广告账户健康诊断（评级 + 问题清单） | `random` |
| `analyze_search_terms` | 搜索词效果（高效/低效/浪费/机会词） | `random` |
| `optimize_bids` | 出价优化建议（关键词/广告组） | `random` |
| `analyze_ad_competitors` | 竞品广告策略、展示份额、词重叠 | `random` |
| `optimize_budget` | 多 Campaign 预算分配 | `random` |
| `detect_ad_anomalies` | 花费突增 / 转化骤降检测 | `random` |

### ② `aigc_tools`（8）· 内容与素材生产

| 工具 | 能力 | 链路末端 |
|---|---|---|
| `generate_product_image` | 「生成产品图」 | **只拼提示词**，不出图 |
| `analyze_main_image` | 主图质量诊断（评分/CTR 预测/合规） | `random`（13 处） |
| `generate_a_plus_content` | A+ / EBC 品牌内容分模块 | 部分 `random` + LLM |
| `generate_brand_story` | 品牌故事（定位/使命/卖点/标语） | 真 LLM（`_llm_generate_text`） |
| `translate_content` | 多语言翻译 + SEO 保留 | 真 LLM |
| `generate_infographic` | 信息图规格（分区/文案/配色/CTA） | 纯计算 |
| `check_image_compliance` | 图片合规检查 | 少量 `random` |
| `generate_video_script` | 短视频脚本（分镜/旁白/钩子/CTA） | 真 LLM + 模板 |

### ③ `competitor_intel_tools`（8）· 竞品情报

| 工具 | 能力 | 链路末端 |
|---|---|---|
| `monitor_competitor` | 竞品 Listing 监控（价格/排名/评论/库存） | 纯计算（数据全来自内存） |
| `track_batch_asins` | 批量 ASIN 关键指标对比 | 纯计算 |
| `analyze_market_share` | 市场份额估算（CR4 / HHI） | 少量 `random` |
| `analyze_pricing_strategy` | 定价模式/促销节奏/价格弹性 | `random`（3 处） |
| `analyze_competitor_reviews` | 竞品评论优劣势 / 差异化机会 | **`_mock_review_analysis`**（方法名自带 mock） |
| `detect_intruders` | 新卖家入侵检测与威胁评级 | 纯计算 |
| `analyze_buy_box` | Buy Box 竞争格局 | **`_mock_buy_box_data`** |
| `compare_competitors` | 多维竞品对比 | 纯计算 |

### ④ `customer_service_tools`（4）· 智能客服

| 工具 | 能力 | 链路末端 |
|---|---|---|
| `search_faq` | 客服知识库检索 | `search_knowledge_base`（未见落库） |
| `create_ticket` | 创建工单（工单号现编、零持久化） | 无 |
| `analyze_sentiment` | 情感倾向分析 | 无（规则/LLM 未定） |
| `get_conversation_summary` | 对话摘要 | 无 |

### ⑤ `review_analyst_tools`（6）· 运营复盘师 ★ 标杆

| 工具 | 能力 | 链路末端 |
|---|---|---|
| `weekly_report` | 经营概览周报（销售+广告+库存+客诉） | **`get_data_source()` 工厂** |
| `monthly_review` | 月度经营复盘 | 同上 |
| `ad_review` | 广告投放复盘 | 同上 |
| `product_performance` | 商品表现分析 | 同上 |
| `inventory_health` | 库存健康（账龄分布） | 同上 |
| `profit_audit` | 利润审计（含 FBA/佣金/退款） | 同上 |

## A.2 成色分类（这才是「有没有用」的答案）

判据是**全链路末端**：`db` 访问 / 网络 / `random` / LLM / 硬编码。
**50 个工具全部 `db=0`** —— 没有任何一个触达数据库（唯一疑似命中的 `_session` 经核实是会话状态方法，不是 DB 会话）。

| 类 | 模块 | 数 | 证据 | 处置 |
|---|---|---|---|---|
| **标杆** | `review_analyst` | 6 | `_source()` 走 `get_data_source(prefer="auto")`，真/Mock 可切换；docstring 还记录了历史缺陷（模块级单例导致「配好凭据也永远跑假数据且不报错」） | **补 router + 挂 Agent，当模板用** |
| **真链路被绕过** | `aigc_media` | 8 | 模块内 `asset_gen.py` + `image_client.py`(DashScope，含并发限流/180s 超时) + `job_service.py`(Celery) **真出图链路完备**，`router.py` 走它；但 `generate_product_image` 工具走 `generate_product_image_service`（**对话驱动，只拼提示词**），而真出图的 `generate_assets_service` **没注册成工具** | 把真能力注册成工具；或至少改 desc（现在自称「生成产品图片」是误导 LLM） |
| **有源可接却没接** | `ad_analysis` | 6 | 末端 `_generate_metrics()` → `random.*`；而 `amazon_sp` 的 `fetch_ad_metrics()` + `AdMetric` 表**都已存在**。模块内还自建了一个**同名** `AdMetric` Pydantic 模型（`agent_ad.py:54`）——同名不同物 | **删 random，改接 `get_data_source()`** |
| **真假混杂** | `competitor_intel` | 8 | `_mock_review_analysis` / `_mock_buy_box_data` 是假；`_llm_insights` 是真 LLM | 逐个甄别，mock 的接 `fetch_competitors()` |
| **薄壳** | `customer_service` | 4 | 无 random、无 DB、无网络 | 接知识库 / 工单表；`create_ticket` 需落库 + 审批 |

**已装配的 18 个也不全是真数据**（诚实起见一并列出）：
- `listing_generator` 8 个：末端 `_llm_generate` → 真 LLM（这条合理，文案生成本就是 LLM 任务）
- `product_research` 5 个：`analyze_blue_ocean` 走 `_generate_mock_blue_ocean_products`（**造候选产品**）、`save_candidate` 才真落库、其余纯计算
- `navigation_tools` 5 个：UI 动作（切 Agent / 开视图 / 主题 / handoff），本就不需要数据源

## A.3 「是不是无用遗留」——三条判据，逐条查

| 判据 | 结论 |
|---|---|
| **有人在等吗**（前端消费者） | 有。`review_analyst` 6 个在 `frontend/src/mock/toolExecutors.ts` 里都有对应执行器；`switch_agent` 17 处、`set_theme` 8 处、`save_candidate` 2 处。其余为 0 |
| **有测试钉住吗** | 有。49/50 有测试引用（`save_candidate` 67 次、`switch_agent`/`set_theme` 各 15 次、`analyze_blue_ocean` 10 次）。`test_secretary_agent.py:343-368` 甚至有一份**工具名清单断言** |
| **有真实数据源可接吗** | 有。`review_analyst` 已接工厂；`ad_analysis` 可接 `fetch_ad_metrics()`；`aigc_media` 可接 `asset_gen` |

**git 历史**（这条最直接）：
```
6 个文件全部来自 2026-09-11 的两个提交，此后均只有 1 次提交、再没被改过：
  757305e  feat(secretary): 铺开主 Agent 工具层 + 会话级记忆 + handoff 承接
  ddcbc21  feat(secretary): 收官工具层——竞品监控修复 + 运营复盘师新建
```

⇒ **它们不是「古老遗留」，而是 7 天前一次性成批铺开的「已铺未接」**。
提交信息自己就写着「**铺开**主 Agent 工具层」——铺开了，但只接上 18/50。

## A.4 但确实有两处该处理的「多余」

老板的怀疑不是空穴来风，查出来**两处真问题**：

1. **重名（必须处理）**：`compare_competitors` 同时存在于 `competitor_intel_tools` 和 `product_research_tools`。
   挂到同一个 Agent 上会冲突 ⇒ **「32 个无脑全挂」不可行，挂之前必须合并或改名**。

2. **语义重叠（需合并评审）**：`ad_analysis` 的 6 个里，
   - `diagnose_ad_account` / `detect_ad_anomalies` ↔ `review_analyst.ad_review`（同读广告数据）
   - `analyze_ad_competitors` ↔ `competitor_intel` 全家
   - **真正独有**的只有 `optimize_bids` / `optimize_budget` / `analyze_search_terms`

## A.5 修正后的批 A 口径

上一轮批 A 写的是「挂上 32 个已写好的工具」。**按本节取证应改为四步**：

| 步 | 动作 | 依据 |
|---|---|---|
| A1 | **先去重**：合并重名的 `compare_competitors`，评审 ad_analysis ↔ review_analyst / competitor_intel 的重叠 | A.4 |
| A2 | **接数据源**：`ad_analysis` 6 个删 `random` 改接 `get_data_source()`；`competitor_intel` 的 `_mock_*` 改接 `fetch_competitors()` | A.2 |
| A3 | **注册真能力**：把 `aigc_media` 的 `generate_assets_service`（真出图）注册成工具；改掉 `generate_product_image` 的误导性 desc | A.2 |
| A4 | **补缺件**：`review_analyst` 补 `router.py`（前端 6 张卡在等）；`customer_service` 的 `create_ticket` 落库 | A.2 |

**结论一句话**：32 个工具**没有一个是空的、也没有一个是「无用」的**（每个都有 docstring、参数说明、测试引用）；
真正的问题是**它们背后的数据管道只被 1/7 的模块接上**——而那条管道（真 SP-API 客户端 + 可切换工厂 + 8 张落库表）**早已建好**。
