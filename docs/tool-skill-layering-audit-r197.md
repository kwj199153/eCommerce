# 工具 / 技能分层审计 —— 三段对话主张 vs 本项目实测（第 197 轮）

> 起因：老板拿来一段关于「Tool = 原子操作 / Skill = 业务编排包」的外部讨论，问三件事：
> ① 哪些适配我们项目（有什么启发）② 现有工具够不够原子 ③ 内部函数 / API 有没有没做成工具给 AI 调
>
> 本报告全部读数来自**运行时 / AST 双路取证**，不引用任何 docstring 的自述。
> 原始输出：`.workbuddy/tmp/r197_tool_audit.txt`、`r197_crossagent.txt`、`r197_demo_tools.txt`

---

## 0. 三问结论（先给答案）

| 问题 | 结论 |
|---|---|
| **Q1 哪些适配** | 那段对话的**方向**我们已经走了（渐进披露 + Skill 编排），但有一处**语义落差**：它说的「Skill 绑定工具 = 把工具 schema 交给 LLM」，在我们这里是**「在正文里写一段工具清单文字」** |
| **Q2 够不够原子** | **工具包装层是原子的**（46 个工具实现：平均 1 次 `await`、0 个 `if`、0 个 `for`）；但**能力粒度不齐** —— 11 个工具参数 ≥5，其中 `generate_product_image` 16 个参数，属「一次调用完成一整套流程」 |
| **Q3 有没有没做成工具的** | **有，三层，一层比一层严重**：① 27 个工具**做成了但没装配**（4 个 Agent 零工具）② 218 个 API 端点**所属模块零工具** ③ 记忆 / RAG 等基础设施能力**连工具定义都没有** |

---

## 1. 那段对话的主张 vs 本项目实测

| 主张 | 本项目实测 | 判定 |
|---|---|---|
| Tool = 最小原子，只做单一动作 | 工具层统一形态 `req = XxxRequest(...)` → `await _service.xxx(req)` → `resp.model_dump_json()`，是 service 的 **1:1 薄包装** | ✅ 包装层原子 |
| Tool 不该含业务判断 | 46 个工具实现里只有 `save_candidate` 有 3 个 `if`（其余全 0） | ✅ 基本干净 |
| ❌ 不要把完整流程写死成一个 Tool | `_coarse_grained_tools` 4 个（`generate_complete_listing` / `optimize_listing` / `analyze_listing_seo` / `generate_ab_test_variants`）**就是流程级入口**，且 8 个全绑给 LLM | ⚠️ 存在，但**是有意的**（见 §2.2） |
| ❌ 不要把一堆零散原子工具丢给 LLM 自由编排 | 本项目走的是 Skill 收窄 + 目录注入，方向一致 | ✅ 同向 |
| ✅ Skill 正文放业务规则、后端放数据读写 | 22 条演示技能正文都是方法学（标题四段式 / 退款话术 / 降价研判），无硬编码数据访问 | ✅ 同向 |
| ✅ **`load_skill` 时把「绑定的工具 schema」一起交给 LLM** | **不是**。我们渲染的是一段**文字清单**，工具 schema 从未注入 | ❌ **语义落差**（见 §3） |

### 1.1 最有启发的一条：`_TOOLS_GUIDE_HEAD` 的「只用这些」是收窄，不是交付

`ai_infra/skills.py::render_skill_tools()` 的产出实测长这样：

```text
## 本技能配套工具

执行上面的步骤需要取数或计算时，请调用下列工具（**只用这些**；不要调用清单之外的工具，也不要凭记忆编造工具名）：

- `get_my_subscription`
```

而 `render_skill_body()` 自己的 docstring 承认：

> 「工具是**按 Agent 装配**的，模型每轮只从 `bind_tools` 拿到自己的工具清单」

⇒ **两者叠加的后果**：这段文字只有在「绑定的工具 ⊆ 该 Agent 已有工具」时才有意义（**收窄**）；
一旦 `⊄`，模型会被明确告知去用一个**它手里没有的工具** —— 比不写这段更糟。

---

## 2. Q2：工具够不够原子

### 2.1 读数（AST，46 个工具实现）

| 指标 | 值 |
|---|---|
| 工具实现总数 | 46（7 个模块的 `tools.py`） + 秘书 9（`navigation_tools` 等） = **55 个定义** |
| `await` 次数 | 每个都恰好 **1**（无多步编排） |
| `if` 分支 | 45 个为 **0**，只有 `save_candidate` 有 3 个 |
| `for` / `while` | 全部 **0** |
| 参数 ≥ 5 的 | **11 个** |

参数最多的 5 个：

| 工具 | 参数数 | 模块 |
|---|---|---|
| `generate_product_image` | 16 | aigc_media |
| `analyze_blue_ocean` | 9 | product_research |
| `analyze_profit` | 8 | product_research |
| `create_ticket` | 7 | customer_service |
| `generate_assets` | 7 | aigc_media |

### 2.2 判定

- **包装层（工具函数本身）是原子的** —— 它只做「建请求对象 → 调一次 service → 序列化」。
- **能力粒度由 service 决定**，工具层看不出来。所以「这个工具原不原子」这个问题，
  在我们的架构里等价于问「**这个 service 方法做几件事**」：
  - `optimize_listing_title` → 一件事（改标题）✅ 原子
  - `generate_complete_listing` → 标题 + 五点 + 描述 + 关键词 + SEO 评分，**5 件事** ⚠️ 流程级
  - `weekly_report` → 汇总销售 + 广告 + 库存 + 退款，**4 类数据** ⚠️ 流程级（虽然只 1 个参数）
- **本项目已经把这件事显式化了**：`listing_generator/tools.py` 里 `_fine_grained_tools`(4) 与
  `_coarse_grained_tools`(4) 分开命名，并靠 description 里的使用条件做消歧
  （例如 `generate_complete_listing` 写「当用户要『生成/写一套完整 listing』**且没有指定只做标题/五点等单一部件**时使用」）。
  ⇒ 这是用 **LLM 侧消歧**替代 **接口侧拆分**，是一种合理做法，代价是多消耗一点判断。

---

## 3. Q3：内部函数 / API 有没有没做成工具（三层）

### 第 1 层：**做成了工具，但零装配** —— 27 个（最严重）

**双路取证**：

| 路 | 方法 | 结果 |
|---|---|---|
| A 静态 | AST 扫 8 个 Agent 类的 `super().__init__(tools=...)` | 只有 **secretary** 在 `__init__` 里传了 `tools=` |
| B 静态 | 全仓 import 工具容器 | 只有 3 处：`from .tools import listing_tools / product_research_tools / review_analyst_tools` |
| C import | `from .tools import ad_analysis_tools` / `aigc_tools` / `competitor_intel_tools` / `customer_service_tools` | **零命中** |

⇒ 真正的装配点是 `_build_router()` 里那个**内部 BaseAgent**（listing/product_research/review_analyst 三家同形），
  加上秘书的 `super().__init__(tools=…)`。**共 4 处**。

**装配 / 未装配对照**：

| Agent | 范式 | 工具容器 | 定义数 | 装配数 |
|---|---|---|---|---|
| ListingGenerator | A | `listing_tools` | 8 | **8** |
| ProductResearcher | A | `product_research_tools` | 5 | **5** |
| review_analyst | A | `review_analyst_tools` | 6 | **6** |
| secretary | A | navigation + subscription + product + shop | 9 | **9** |
| ad_analysis | **B** | `ad_analysis_tools` | 6 | **0** |
| AIGC 媒体生成器 | **B** | `aigc_tools` | 9 | **0** |
| competitor_intel | **B** | `competitor_intel_tools` | 8 | **0** |
| 智能客服 | **B** | `customer_service_tools` | 4 | **0** |

**范式 B 的工作方式**（`AdAnalysisAgent` 实测）：

```python
async def invoke(self, query, context=None):
    intent = self._classify_intent(query)      # 关键词表 Route
    if intent == "diagnosis":     return await self._analyze_diagnosis(...)
    elif intent == "search_terms": return await self._analyze_search_terms(...)
    ...
```

⇒ **关键词路由 + 硬编码 `_handle_*` 流程，LLM 只做最后的文案总结**。
  这 4 个 Agent 的定义工具于是成为**永远调不到的死代码**。

**与 `TOOL_CATALOG` 交叉验证**：目录只覆盖 4 个 Agent（`ListingGenerator` / `ProductResearcher` /
`review_analyst` / `secretary`），而 `AGENT_CATALOG` 有 8 个 —— **差集正是这 4 个零工具 Agent**。
两条独立路径得出同一结论。

### 第 2 层：**有 API 端点，但所属模块零工具** —— 218 个

| 模块 | 端点数 | 工具 |
|---|---|---|
| aigc_media | 18 | 0（定义了 9，未装配） |
| products | **16** | **0** |
| competitor_intel | 14 | 0（定义了 8，未装配） |
| stores | 14 | 0 |
| candidates | 13 | 1（`save_candidate`，且属 ProductResearcher） |
| monitors | 13 | 0 |
| knowledge_base | 12 | 0 |
| ad_analysis / assets / billing / customer_service / skills | 各 11 | 0（ad/cs 定义了工具未装配） |
| platform_rules | 9 | 0 |
| voice_clone | 8 | 0 |
| memory | 6 | 0 |
| conversation | 3 | 0 |
| **core**（auth / identity / metering） | **37** | 0 |

合计：**246 端点 = 有工具模块 28 + 零工具模块 181 + core 37**。
（注：core 的 37 个是鉴权 / 计费 / 配额类，**本来就不该给 AI**；所以「218」是上界，真实缺口小于它。）

**直接命中老板上一条需求**：你问的「**这个产品帮我入库**」——
`POST /api/v1/spus` 确实存在（`modules/products/router.py:138`），但：

```python
async def create_spu(payload: dict, shop_id=Depends(get_current_shop_id)):
    spu_id = payload.get("id") or f"spu-{int(datetime.utcnow().timestamp() * 1000)}"
    record = SpuRecord(title=payload.get("title") or "未命名主产品", ...)   # ← 零校验
```

- **没有任何工具** ⇒ AI 拿不到这条路
- **没有任何校验** ⇒ 没有 ASIN 去重、没有必填字段检查、title 缺了静默填「未命名主产品」
- `products` 模块**没有 `service.py`**，业务逻辑直接写在 router 里

⇒ 那段对话里设计的「入库 Skill」（提取 ASIN → 查重 → 校验必填 → 写库），
**前置条件（原子工具）在我们这里一个都不存在**。

### 第 3 层：**连工具定义都没有的基础设施能力**

| 能力 | 位置 | 工具 |
|---|---|---|
| 长期记忆（写入 / 蒸馏 / 限额） | `ai_infra/memory/`（distill 20KB / entry 15KB / limits 16KB） | 无 |
| RAG 混合检索 | `ai_infra/rag/hybrid_engine.py`（27KB） | 无 |
| 平台规则查询 | `modules/platform_rules/`（service 13KB + seed 38KB） | 无 |
| 知识库检索 | `modules/knowledge_base/service.py`（19KB） | 无 |

这四项**恰好是"AI 最该自己用"的能力**（检索增强），却全都只能靠人去界面上点。

---

## 4. 顺带挖出的 4 个次生缺陷（都带证据）

| # | 缺陷 | 证据 | 性质 |
|---|---|---|---|
| **N1** | `service._validate_tools` docstring 承诺「合法但**不属于所挂 Agent** 的工具…**渲染期再兜一层过滤（见 `provider`）**」—— `provider.py` 里**没有这层过滤** | 实测：写口 `_validate_tools(['get_my_subscription'])` → 返回 `['get_my_subscription']`（**接受**）；`render_skill_body` 把该名字**原样渲染**进正文；而 `ListingGenerator` 手上只有 8 个工具、**不含**它 | **注释承诺型假门禁** |
| **N2** | **22 条演示技能 `tools` 全部是 `[]`** | seed 里 `"tools": []` 出现 **22 次**（= 技能条数）；全量扫描：真的绑了工具的 = **0 / 22** | 第 185 轮的「技能绑定工具」机制**零使用** |
| **N3** | `tools_catalog.py` docstring 说未接线的是「另外那 **35** 个」 | 实测未装配 = **27** 个（6+9+8+4）；docstring 把 listing 的 8 个也算进去了，但 `listing_tools` 明明接在 `_build_router` 上 | 数字真源不一致 |
| **N4** | `listing_generator/tools.py` 顶部 docstring 写「**不包** `chat` / `generate_complete_listing` / `optimize_listing` / `analyze_seo` 这类粗粒度入口」 | 同文件第 243 行 `_coarse_grained_tools` **恰恰包了这 4 个** | 注释与代码自相矛盾 |

**N2 的连带影响值得单列**：22 条技能挂在 7 个 Agent 上，其中 **9 条挂在范式 B 的零工具 Agent 上**
（competitor_intel 5 / ad_analysis 2 / AIGC 1 / 智能客服 1）。
这 9 条技能即使绑了工具名字，范式 B 的 Agent 也**永远调不到**。

---

## 5. 建议（按优先级，**待老板拍板**）

### P0-1 补一条「装配覆盖率」门禁（防 27 个孤儿再出现）

现在 `test_tool_registry_guard.py` 与 `test_tool_catalog.py` 都存在，但**没有一条**钉住
「`AGENT_CATALOG` 里每个 Agent 是否装配了工具」。建议新增形态门禁：

> 对 `AGENT_CATALOG` 的每个 `agent_name`，断言 `len(tools_for_agent(name)) > 0`，
> **或**该 agent 在显式白名单 `TEXT_ONLY_AGENTS` 里登记（承认它走规则路由范式）。

**必须反向注入证明它能转红**（删掉 listing 的 `tools=` ⇒ 应只红这一条）。

### P0-2 补上 N1 承诺的那层过滤（或改掉承诺）

两个方向二选一：

- **方向 A（实现承诺）**：`render_skill_body(skill, agent_name=None)`，
  当 `agent_name` 给了就过滤掉不属于该 Agent 的工具；`read_skill_for_agent` 把 `agent_name` 传下去。
  好处：模型不再被指使去调一个手里没有的工具。代价：渲染函数多一个可选参数（`read_skill_body` 的
  「同名双通道共用」不变，只是都多传一个值）。
- **方向 B（改注释）**：承认不拦，但在技能编辑界面加实时警告「该工具不属于此技能启用的 Agent」。

我倾向 **A**，因为注释已经承诺了，而且 A 的判据可执行、可反向注入。

### P0-3 给演示技能绑上工具（让 N2 的机制真的跑起来）

22 条里至少 13 条有明确的可绑候选（挂在有工具的 Agent 上）：

| 技能 | Agent | 建议绑定 |
|---|---|---|
| `listing-title-formula` | ListingGenerator | `optimize_listing_title` |
| `listing-launch-checklist` | ListingGenerator | `generate_complete_listing` |
| `blueocean-hard-filter` | ProductResearcher | `analyze_blue_ocean` |
| `candidate-*`（5 条） | ProductResearcher | `analyze_profit` / `analyze_pain_points` / `compare_competitor_listings` / `save_candidate` |
| `review-weekly-brief` 等 5 条 | review_analyst | `weekly_report` / `monthly_review` / `ad_review` / `profit_audit` |

### P1 修两处 docstring 事实错误（N3 / N4）

纯文档，零风险，但它们是「真源」，错了会让下一个人重新踩一遍。

### P2 决策项：范式 B 的 4 个 Agent 怎么办

这是**产品决策**，我不替你定。三条路：

| 选项 | 说明 | 代价 |
|---|---|---|
| **B1 接上工具** | 把 4 家改成 `_build_router` 同形（内部 BaseAgent 绑工具），与范式 A 合并 | 每个 Agent 要改主流程 + 冒回归风险 |
| **B2 删掉 27 个孤工具** | 承认它们是规则引擎时代的遗留，从 4 个 `tools.py` 里移除 | 简单，但丢掉了「以后接上」的现成资产 |
| **B3 保持现状 + 登记为已知形态** | 只补 P0-1 的白名单，不做改造 | 零成本，但「两套范式并存」会长期存在 |

我倾向 **B1 中「先接 1 家试水」**（`competitor_intel` 有 8 个工具、5 条技能挂它，收益最大），
验证范式统一可行后再推其余 3 家。

---

## 6. 复算指引

```bash
cd D:/ai/eCommerce/backend
D:/work/anaconda/anaconda3/envs/reactAgents/python.exe ../.workbuddy/probes/r197_tool_audit.py
D:/work/anaconda/anaconda3/envs/reactAgents/python.exe ../.workbuddy/probes/r197_demo_tools_probe.py
```

（`r197_crossagent_probe.py` 同样可复算 N1；它用 managed 3.13 也可跑，因为只依赖纯函数。）
