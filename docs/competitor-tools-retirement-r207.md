# 竞品工具删除裁决（第 207 轮）

> 老板指令原文：
> 「analyze_buy_box 删除，detect_intruders 删除，**analyze_competitor_reviews 与目前竞品的评论痛点挖掘 skill 是否重叠**，
> **analyze_pricing_strategy 是否与竞品的策略推演 skill 重叠**，analyze_market_share 删除，
> track_batch_asins 批量追踪 ASIN 删除，monitor_competitor 删除」
>
> 本篇回答两个问题：**① 那两条是不是重叠；② 5 条明确删除各自会动到什么。**
> 全部结论来自运行时真源与 AST 采集（探针 `.workbuddy/probes/r207a_skill_tool_map.py`，产物 `out_r207a_map.txt`），无一处凭印象。

---

## 一句话结论

**两条都不重叠** —— 它们是**同一条链的两层**：技能卡是「方法论」，工具是「取数通道」，卡的 `tools` 字段把两层显式绑定。
**删掉这两条工具，等于把第 189 轮刚修好的「技能有卡、Agent 无原料」的病重新种回去。**

5 条明确删除中，**`analyze_buy_box` 干净**（零引用）、**`detect_intruders` 是空壳**（删了零能力损失）；
但 `monitor_competitor` / `track_batch_asins` / `analyze_market_share` 会**打断 3 张技能卡**（含第 181 轮那张老卡）。

⚠️ **一个必须先定的前提**：删完 5 条，`competitor_intel` 的工具面是 **8 → 3**；若连那 2 条一起删，是 **8 → 1**（只剩 `compare_competitors`）。
**这已经不是「精简工具」，是「把竞品 Agent 掏空」** —— 技能卡怎么处置，取决于你这一步的真实意图。

---

## 一、先把概念拆开：技能卡 ≠ 工具

这两层长得很像，但**不是同一件东西**，这是回答「是否重叠」的前提。

| | 技能卡（`seed.py::DEMO_SKILLS`） | 工具（`tools_catalog.py::TOOL_CATALOG`） |
|---|---|---|
| 是什么 | **方法论**：适用条件、步骤、输出格式、红线 | **取数通道**：一次结构化的服务调用 |
| 产出 | 一段给模型看的**流程指令**（不带数据） | 一份**真实业务数据**（JSON） |
| 谁消费 | `render_skill_body()` → 注入 `load_skill` 返回文本 | `bind_tools()` → 模型可调用 |
| 数量 | 22 张 | 60 条 |
| 绑定关系 | 卡的 `tools: [...]` 字段**指向**工具名 | —— |

**关键机制**：卡声明了工具后，`render_skill_body()` 在正文末尾附一段**工具清单**（`ai_infra/skills.py:357`），
把这个技能该用哪个工具**从「猜」变成「给定」**（源码注释原话）。

---

## 二、那两条「是否重叠」——机械核实结论：**不重叠**

### 2.1 `analyze_competitor_reviews` vs 技能卡「评论痛点挖掘」

| 维度 | 工具 `analyze_competitor_reviews` | 技能卡 `review-pain-mining` |
|---|---|---|
| 位置 | `competitor_intel/tools.py:241` | `seed.py:272-342` |
| 产出 | 竞品评论的优劣势/痛点/差异化机会（**数据**） | 三分类归因（产品问题/描述不符/物流售后）+ 频次×影响面排序（**方法**） |
| 绑定 | —— | **`"tools": ["analyze_competitor_reviews"]`**（逐字绑定，唯一落点） |

**证据（这张卡自己的注释，`seed.py:330-333`）写的**：

> 真正的落点是 **`competitor_intel`**：它的 `analyze_competitor_reviews`
> 逐字写着「竞品评论深度分析：挖掘竞品评论中的优劣势、**用户痛点**、差异化机会」，
> 与该技能正文要求的「一批评论 + 三分类归因」完全对口。

这段注释是**第 189 轮**你核查卡片归属时留下的：当时这张卡先挂在智能客服、又挂在运营复盘师，
两处的 Agent 都**不读评论**（`review_analyst` 的 6 个工具没有一个产出评论数据，system prompt 里连「评论」二字都没有）
⇒ 点了卡，Agent 手里没原料，**只能凭想象编**。最后落到 `competitor_intel` 才修好。

**结论**：不是重叠，是**「方法 ↔ 原料」**。删工具 = 卡重新失去原料。

> 另有一张容易混淆的卡：`candidate-pain-analysis`「痛点分析」（`ProductResearcher`）。
> 它与本卡**已在卡里显式分工**（`seed.py:929-932`）：
> 「手上**已有一批真实评论（≥30 条）**时，应当走基于评论的痛点挖掘流程……本技能是**没有自家评论**的阶段」。
> ⇒ 两张卡不重叠，是**阶段分工**；本次不涉及。

### 2.2 `analyze_pricing_strategy` vs 技能卡「策略推演」

| 维度 | 工具 `analyze_pricing_strategy` | 技能卡 `competitor-strategy-sim` |
|---|---|---|
| 位置 | `competitor_intel/tools.py:233` | `seed.py:765-815` |
| 产出 | 竞品**定价模式、促销节奏、价格弹性**（数据） | 定价/上新/广告**三条线**的方案+代价+不可逆标注（方法） |
| 绑定 | —— | `"tools": ["analyze_pricing_strategy", "compare_competitors", "analyze_market_share"]` |

**证据（这张卡正文第一条线，`seed.py:781-783`）**：

> 1. **定价**：跟价 / 维持 / 抬价
>    判据不是"对方降了多少"，而是「我方在该词上的**价格弹性**与**重合度**」。
>    **拿不到弹性数据时，明确写"无法量化，仅作方向判断"。**

**「价格弹性」这个词就是 `analyze_pricing_strategy` 的产出之一**。
⇒ 删工具，卡的第 1 条线就**永远只能写「无法量化」**——它自己写下了这个降级口径，说明原料不被满足是已知风险，而删工具正好把它变成常态。

**结论**：不是重叠，是**「原料 → 加工」**。删工具 = 卡的判据失去数据来源。

### 2.3 为什么会有「重叠」的错觉

因为**名字像**：工具名 `analyze_pricing_strategy`（定价策略分析）与卡名「策略推演」都含「策略」；
工具名 `analyze_competitor_reviews`（竞品评论分析）与卡名「评论痛点挖掘」都含「评论」。
但**判「同端点多名」不能用名字相似度** —— 这是第 206 轮已经踩过的坑
（`compare_competitor_listings` vs `compare_competitors` 五层全撞名，实现却完全不同）。
本轮同样：**看绑定关系与产出物，不看名字。**

---

## 三、5 条明确删除，逐条影响面

### 3.1 总表

| # | 工具 | 能力真实状态 | 引用它的技能卡 | 前端入口 | 删除代价 |
|---|---|---|---|---|---|
| 1 | `analyze_buy_box` | **实装**（`agent_competitor.py:758-760` 过 `_ensure_source`） | **无（0）** | 无 | 能力消失，**无人引用** ⇒ 最干净 |
| 2 | `detect_intruders` | **空壳** —— 唯一的 return 是 `_no_data(status="unsupported")`（`agent_competitor.py:749-751`） | 竞品周报、异动洞察 | 无 | **零能力损失**（本就不产出数据） |
| 3 | `analyze_market_share` | **实装**（`:585-587`） | 策略推演 | 无 | 策略推演卡少 1/3 原料 |
| 4 | `track_batch_asins` | **实装**（`:547-549`） | 竞品周报 | 无 | 竞品周报卡**断链** |
| 5 | `monitor_competitor` | **实装**（`:482-484`） | **竞品降价研判、竞品周报、异动洞察（3 张）** | 无 | ★ **3 张卡断链**，含第 181 轮老卡 |

> `detect_intruders` 是空壳这件事有独立证据：`test_competitor_intel.py:655-678`
> 叫 `test_intruders_detect_is_explicitly_unsupported`，断言 `data_status="unsupported"` +
> **不得返回** `new_competitors/threat_summary/response_strategies`（防伪数据入口）。
> 源码注释写明原因：竞品快照**没有「新进入者」这个维度**，要恢复得接①商品上架时间 或 ②类目新品榜。

### 3.2 反向索引全表（工具 ← 引用它的技能卡）

采集自 `seed.py` 的 AST（22 张卡里只有 5 张带工具绑定）：

| 工具名 | 引用它的技能卡 |
|---|---|
| `monitor_competitor` | 竞品降价研判、竞品周报、异动洞察 |
| `detect_intruders` | 竞品周报、异动洞察 |
| `track_batch_asins` | 竞品周报 |
| `analyze_market_share` | 策略推演 |
| `analyze_pricing_strategy` | 策略推演 |
| `analyze_competitor_reviews` | 评论痛点挖掘 |
| `compare_competitors` | 策略推演 |
| **其余 53 条工具** | **无一被技能卡引用** |

**即：全部 8 条竞品工具里，7 条被引用；全库只有 5 张卡带工具绑定，且全部集中在竞品域。**

### 3.3 删除后「全悬空」的技能卡

| 技能卡 | 现在绑定 | 删 5 条后 | 删 7 条后 |
|---|---|---|---|
| 竞品降价研判 | `monitor_competitor` | **全悬空 ✗** | ✗ |
| 评论痛点挖掘 | `analyze_competitor_reviews` | 完好 | **全悬空 ✗** |
| 竞品周报 | `monitor_competitor`,`track_batch_asins`,`detect_intruders` | **全悬空 ✗**（3 个全删） | ✗ |
| 异动洞察 | `monitor_competitor`,`detect_intruders` | **全悬空 ✗** | ✗ |
| 策略推演 | `analyze_pricing_strategy`,`compare_competitors`,`analyze_market_share` | 剩 2 | 剩 1 |

---

## 四、两条静默损害（删工具若不处理卡片）

### 4.1 写口会**显式报错**（好事，但意味着删不干净就跑不起来）

`tools_catalog.py:722 is_known_tool()` 以 `TOOL_CATALOG` 为**唯一真源**，
`skills/service.py:541 _validate_tools()` 用它做 **fail-closed** 校验（未知工具名一律拒绝）。

⇒ **只删工具、不改卡片**：`ensure_demo_skills()` 播种时会被拒 ⇒ **播种失败**（不是静默）。

### 4.2 读口**不过滤**（坏事，这是真缺口）

`ai_infra/skills.py:313-320 render_skill_tools()` **只做去重保序，不校验工具名是否存在**，
把 `tools` 列原样渲染成 `- \`monitor_competitor\`` 追加进正文（`:357`）。

⇒ **库里已有的老卡片**不会因删工具而被重新校验，它们会**继续把失效工具名喂给模型**；
而模型的 `bind_tools` 清单里已经没有这个名字 ⇒ **模型被指引去调用一个不存在的工具**。

⚠️ 现有门禁 `test_skill_gate.py:506 test_bound_tools_reach_the_model_through_load_skill`
只覆盖「**合法**绑定能到达模型」，**不覆盖「失效绑定会不会仍被注入」** —— 这是真实缺口。

### 4.3 合法出口已经存在

`tools: []` 是**明确允许**的形态。`test_skill_gate.py:500-503` 有一条断言：

> `assert cleared["tools"] == [], "清空工具绑定被拦了 —— 纯提示词技能应当是合法的"`

全库 22 张卡里**已有 17 张是 `tools: []`**（纯方法论型）。
⇒ 卡片**可以保留**，方法论文本与红线全部仍然有效，只是不再声明工具。

---

## 五、删除对**前端与端点**的影响：零

这是本次唯一的宽慰：

| 通道 | 是否受影响 | 原因 |
|---|---|---|
| 前端 2 个调用点 | **不受影响** | `/competitor/compare` → `compare_competitors`（保留）；`/competitor/analyze` → `general_analysis`（**从未注册为工具**） |
| 14 个 `/competitor/*` 端点 | **不受影响** | 端点是 `router.py` 层，直调 service，不经工具层 |
| `/competitor/analyze` 自然语言路由 | **不受影响** | 走 `_classify_intent` 关键词路由 → **agent 方法**（`agent_competitor.py`），与 `tools.py` 注册表是两回事 |
| 对话里「模型自主选工具」 | **少 5 条** | 这是删除的**唯一实质影响** |

> ★ 端点是 14 条，前端只调 2 条 —— 与第 206 轮结论一致（竞品 12 条端点界面无入口）。

---

## 六、执行方案（需你定一件事）

### 6.1 唯一待定项：技能卡怎么处置？

| 选项 | 做法 | 代价 |
|---|---|---|
| **A（推荐）保卡清绑定** | 把受影响卡的 `tools` 清空为 `[]`，保留全部方法论文本与红线 | 卡变成「纯流程指引」，不再声明用哪个工具；**已有 17 例同形态** |
| **B 删卡** | 连卡一起删（并进 `RETIRED_DEMO_SKILLS`） | 竞品域方法论（含三分类归因、三条线推演、降价三类动机排除）**整体消失** |
| **C 改绑** | 把卡改绑到保留的工具 | 需要先论证保留的那条工具**真能产出卡所需原料**（如「策略推演」改绑 `compare_competitors` ⇒ 定价线仍拿不到弹性） |

**选 A 还是 B，取决于你的真实意图**：
- 只想「不要让模型手上有那么多竞品工具」⇒ **A**
- 想「竞品 Agent 整体退役」⇒ **B**，且还要一并处理 `AGENT_CATALOG` 条目、5 张卡、以及 `_build_router()` 是否保留

### 6.2 若你确认删除，改动点清单（供你判断「改动大吗」）

| # | 文件 | 改动 | 量级 |
|---|---|---|---|
| 1 | `modules/competitor_intel/tools.py` | 删 5 个 `StructuredTool` 条目 + 5 个 `_xxx_tool` 函数 | −约 100 行 |
| 2 | `modules/skills/tools_catalog.py` | 删 5 条目录项 | −约 35 行 |
| 3 | `modules/skills/seed.py` | 3~4 张卡的 `tools` 按 6.1 处置 | 约 4 行 |
| 4 | `tests/test_tool_catalog.py` | 计数 60→55（**7 处**） | 7 行 |
| 5 | `tests/test_skill_gate.py` | 计数 60→55（**2 处**） | 2 行 |
| 6 | `tests/test_hitl_wiring.py` | 1 处注释沿革 | 1 行 |
| 7 | `tests/test_agent_delegation_summary.py` | 1 处引用 | 1 行 |
| 8 | `modules/competitor_intel/agent_competitor.py` | **不用改**（`_build_router()` 是整表注入） | 0 |
| 9 | `competitor_intel/router.py` + service | **不用改**（端点保留） | 0 |
| 10 | `tests/test_competitor_intel.py` | **不用改**（45 条用例走端点，不依赖工具注册） | 0 |

**净影响**：5 个文件改代码 + 4 个测试文件改计数/注释；**端点、service、前端零改动**。

### 6.3 附带建议（与本次删除同批做，成本已共担）

1. **补一条读口门禁**：`render_skill_tools` 或加载侧过滤「不在 `TOOL_CATALOG` 里的工具名」，
   把 4.2 那个静默损害变成显式
2. **补一条反向引用门禁**：`每张 DEMO_SKILL 的 tools ⊂ TOOL_CATALOG`（现在只有写口 fail-closed，没有静态门禁）
3. **删 `analyze_buy_box` 前确认**：它是唯一「实装但零引用」的，删了就真丢了 Buy Box 能力 —— 若将来要做，得从 `agent_competitor.py:758` 那段重新接

---

## 七、核验口径与证据

| 结论 | 证据来源 |
|---|---|
| 60 条工具 / 8 个 Agent | 运行时 `TOOL_CATALOG`（探针 `r207a`） |
| 22 张技能卡 / 5 张带工具绑定 | `seed.py` AST 采集（探针 `r207a`，产物 `out_r207a_map.txt`） |
| 卡的 `tools` 字段内容 | `seed.py:221 / :341 / :763 / :814 / :764` |
| `detect_intruders` 是空壳 | `agent_competitor.py:749-751` + `test_competitor_intel.py:655-678` |
| 写口 fail-closed | `tools_catalog.py:722` + `skills/service.py:541` |
| 读口不过滤 | `ai_infra/skills.py:313-320` + `:357` |
| `tools: []` 合法 | `test_skill_gate.py:500-503` |
| 前端只调 2 条竞品端点 | 第 206 轮对账（`docs/atomic-tools-status-r206.md`） |

**复现命令**：
```bash
cd /d/ai/eCommerce/.workbuddy/probes
"D:/work/anaconda/anaconda3/envs/reactAgents/python.exe" r207a_skill_tool_map.py
```


---

## 八、执行结果（老板选 A · 保卡清绑定）

### 8.1 一句话

**5 条工具已从工具面退役；4 张技能卡按 A 处置（3 张清空绑定、1 张只摘退役项）。
端点 / service / 前端零改动。受影响门禁 201/201 全绿，反向注入 7/7 全真红，
全量 1600 条仅剩 2 条既有失败（与本轮无关）。**

### 8.2 逐条落点

| 工具 | 目录表 | 注册表（`tools.py`） | 引用它的技能卡 | 卡的处置 |
|---|---|---|---|---|
| `monitor_competitor` | 移除 | 移除 | 降价研判 / 竞品周报 / 异动洞察 | 3 张 → `tools: []` |
| `track_batch_asins` | 移除 | 移除 | 竞品周报 | 同上 |
| `detect_intruders` | 移除 | 移除 | 竞品周报 / 异动洞察 | 同上 |
| `analyze_market_share` | 移除 | 移除 | 策略推演 | **只摘掉它**，保留另 2 条 |
| `analyze_buy_box` | 移除 | 移除 | （无） | — |

保留：`analyze_pricing_strategy` / `analyze_competitor_reviews` / `compare_competitors`。
锚工具表（`DEMO_SKILL_ANCHOR_TOOLS`）里 3 条置 `None` —— **不留在指向已删工具**
（留着的虽会被门禁跳过，但表本身在说谎）。

★ **「清绑定」≠「清掉仍然有效的绑定」**：`competitor-strategy-sim`（策略推演）原本绑 3 条，
只有 `analyze_market_share` 退役 ⇒ 摘 1 留 2。一股脑清空会**白丢两条有效配置**。

### 8.3 计数沿革

| 口径 | 前 | 后 |
|---|---|---|
| `TOOL_CATALOG` 条目 | 60 | **55** |
| `competitor_intel` 工具面 | 8 | **3** |
| 需人工审批的工具 | 4 | 4（**分子没动** —— 退役的 5 条全是只读） |
| 22 张演示卡中 `tools` 非空的 | 5 | **4** |

### 8.4 改动文件（12 个，全部二进制写盘 + 逐文件还原行尾）

| 文件 | 改动 | 前 → 后（字节） |
|---|---|---|
| `modules/competitor_intel/tools.py` | 删 5 个工具函数 + 5 个注册条目 + 收窄 import | 10,812 → **6,382**（CRLF 保持） |
| `modules/skills/tools_catalog.py` | 删 5 个目录条目 + 沿革改写 | 37,612 → 36,890 |
| `modules/skills/seed.py` | 3 张卡清空 + 1 张摘退役项 + 3 个锚置 `None` | 94,465 → 95,254 |
| `modules/skills/router.py` | docstring 57 → 55（57 本身已陈旧） | 19,703 → 19,703 |
| `tests/test_tool_catalog.py` | 7 处 60 → 55 | 50,805 → 50,946 |
| `tests/test_skill_gate.py` | 2 处 60 → 55 | 77,658 → 77,658 |
| `tests/test_competitor_intel.py` | 登记集合 8→3、调用表 8→3、**两处会 AttributeError 的引用** | 71,049 → 71,023（CRLF 保持） |
| `tests/test_hitl_wiring.py` | 陈旧举例（`track_batch_asins` 不在该注册表里） | 27,440 → 27,665（CRLF 保持） |
| `tests/test_agent_delegation_summary.py` | 样本名换成仍存在的工具 | 15,951 → 15,957 |
| `modules/product_research/agent_product_research.py` | 陈旧举例 | 119,336 → 119,447（CRLF 保持） |
| `tests/test_tool_registry_guard.py` | **补登 `modules/library/tools.py`** + 白名单 2 项 | 20,871 → 22,590（CRLF 保持） |
| `tests/test_hitl_policy.py` | 注册表清单补登 library | 29,082 → 29,746 |

`agent_competitor.py`、`competitor_intel/router.py`、`competitor_intel/service.py`、
`competitor_intel/schemas.py`、`test_competitor_intel.py` 的 45 条端点用例 —— **零改动**。

### 8.5 ★★ 顺带发现并修掉的**两条真缺陷**（都在本轮改动范围之外）

**① `modules/library/tools.py` 从未登记进 `test_tool_registry_guard.REGISTRY_FILES`**

第 205 轮新建的跨 Agent 共用注册表（工厂式 `build_library_tools()`，产出
`list_candidates` / `list_products`）**不在任何扫描名单里** ⇒ 该文件的三条判据
（工具名唯一 / desc 交叉引用 / 悬空棘轮）对它**全部静默放行** —— 与第 145 轮批 B1
补登 secretary 两张表之前的「真空区」**完全同形**。

实测代价：`test_desc_cross_references_resolve` 把 `product_research/tools.py` 里
`get_candidate` 那句**正确的**交叉引用（「先用 list_candidates 拿到候选」）
判成悬空引用 ⇒ **第 205 轮起这条判据一直是红的**，而「没人想到要跑这个文件」
⇒ 无人看见。**注入 #7 复现的正是这条原始红。**

⇒ 教训：**新建注册表时，「登记进扫描面名单」与「写注册表本身」同等重要。**

**② 两份手写清单互为守门人（这条机制工作正常，值得记下）**

补登 ① 之后，`test_hitl_policy.py` 第 5 条判据
（`test_registry_lists_agree_with_tool_registry_guard`）**立刻报红**：
「本文件漏登记注册表（tool_registry_guard 有、这里没有）：['modules/library/tools.py']」。
那不是误报，是它在**正常工作** —— 两份清单分别服务「工具名唯一性」与
「副作用声明」两个门禁，**只登记一处 ⇒ 另一个门禁对该注册表静默放行**。

### 8.6 反向注入 7 组（全真红 + 逐字节还原，`out_r207q_inject.txt`）

| # | 注入 | 预期红 | 实测 |
|---|---|---|---|
| 1 | 卡里写回已退役工具名（违背 A 处置） | `test_demo_skill_tools_are_registered_and_cover_their_anchor` | ✅ 真红 |
| 2 | 锚工具表写回已退役工具 | `test_demo_skill_anchor_tool_is_reachable_from_its_agent` | ✅ 真红 |
| 3 | 目录表多留一条（= 半删） | `test_catalog_names_match_real_assembly` | ✅ 真红（+ 计数自检） |
| 4 | 装配点多出目录表没有的工具 | 同上 | ✅ 真红（+ 竞品 8→3 钉子） |
| 5 | 某条工具不再透传店铺归属 | `test_all_competitor_tools_carry_shop_attribution` | ✅ 真红（+ 形态判据） |
| 6 | 两份注册表清单漂移 | `test_registry_lists_agree_with_tool_registry_guard` | ✅ 真红 |
| 7 | 把 library 从扫描面摘掉 | `test_desc_cross_references_resolve` | ✅ 真红（**复现原始红**） |

### 8.7 回归

| 范围 | 结果 |
|---|---|
| 受影响 11 个测试文件 | **201 / 201 绿** |
| 全量 | **1600 tests / 2 failures / 0 errors** |

那 2 条是 `tests/test_agent_session_state.py` 的
`test_real_pg_roundtrip_upsert_delete_and_ownership` 与
`test_table_shape_matches_the_contract`，均为 **「全量红 / 单跑绿」**的既有问题
（`psycopg3` 异步 + Windows Proactor 事件循环跨用例污染，本仓 #803 早已登记），
**与本轮改动无关**。

### 8.8 尚存缺口（未做，需你定）

1. **读口不过滤**（见 §4.2）：`render_skill_tools()` 仍把 `tools` 列**原样**渲染进
   正文，不校验工具名是否还存在。本轮把演示卡清干净了，但**租户自己建的技能**
   若引用了「后来被删的工具」，仍会静默把模型指向一个不存在的工具。
   补法：加载侧按 `TOOL_CATALOG` 过滤（或改为显式标注），而不是渲染层直接依赖业务表。
2. **§6.3 建议的「卡 `tools` ⊂ `TOOL_CATALOG` 门禁」—— 它已经存在**，不必再补：
   `test_skill_gate.py::test_demo_skill_tools_are_registered_and_cover_their_anchor`
   的 A 分支（第 200 轮建的）。**注入 #1 已证明它真会红。**
3. `analyze_buy_box` 是唯一「实装但零技能卡引用」的一条，已删 ⇒ **Buy Box 能力
   从工具面消失**；将来要做需从 `agent_competitor.py:758` 那段重新接。
