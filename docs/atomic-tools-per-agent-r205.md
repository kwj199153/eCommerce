# 每个 Agent 的原子级操作工具清单 · 缺口的逐条裁决（第 205 轮）

> 需求原文：「1.3 组「同端点多名」…收敛；2.做技能库整理 3.**补充原子级工具清单
> 缺省部分（先判断是否当前项目必要）**」
>
> 本轮文档对应第 3 项。第 1 项（3 组同端点多名的收敛）已在同轮批 A 闭环，
> 见 `docs/orphan-tools-19-r203.md` 之后的 `modules/library/`（SHARED 层）与
> `tests/test_tool_catalog.py` 判据 G/H/I/J/K。

## 一句话结论

第 204 轮盘出的 **20 条缺口**逐条裁决：

| 分类 | 条数 | 说明 |
|---|---|---|
| ✅ **必要，本轮批 B 已落地** | **3** | `get_candidate` / `review_candidate` / `approve_candidate` |
| ⚠️ **必要，但未落地**（有前置条件） | **6** | 其中 2 条前置是**安全**问题，2 条前置是**归属通道缺失** |
| ❌ **不必要**（撤回原提议） | **7** | 含 2 条「注册进去就是递归」、1 条「与已有工具同一实现」 |
| 合计 | 16 | 20 减去批 A 已闭环的 4 条（`list_candidates`×2 家 / `list_products`×2 家）|

**最要紧的两条结论**：

1. **`GET /competitor/monitor/dashboard` 不应注册成新工具。** 它的实现就是
   `await service.monitor_competitor(request, store_id=...)` —— 与**已经存在**的
   工具 `monitor_competitor` 是同一份实现。注册它等于手工制造一个「同一能力两个
   名字」，正是本轮批 A 刚花力气收敛掉的那个病。
2. **`calculate_store_profit` 现状没有任何归属校验。** 它只读必填 header
   `X-Store-ID` 就从读缓存取店铺算利润；`stores` 模块自己的归属真源
   `_ensure_store_access()` **没有在这条路径上被调用**。后果不只是「能算别人的
   利润」，还把它变成**存在性预言机**：传自己的店 → 200，传不存在的店 → 404
   （`_get_store()` :280 抛 `店铺不存在: {id}`）⇒ 可逐个试探全库店铺 ID。
   把一个无归属校验的端点包成 Agent 工具，等于把那个洞直接递给模型。

---

## 一、裁决口径（四条判据，逐条实测）

不靠肉眼读代码，四条判据各有机械证据：

| # | 判据 | 怎么量 | 为什么是硬判据 |
|---|---|---|---|
| 1 | **有无真实现** | AST 扫各模块 `service.py` 的公开函数签名（含 class 方法） | 只有内联 handler 的端点，工具层**结构上无法**复用：跨模块 `import router` 会同时踩破①门面包契约（只允许 `from modules.X import <name>`）②分层表（禁 `PLUGIN → PLUGIN` 顶层 import） |
| 2 | **有无归属通道** | AST 扫 handler / service 签名的 `shop_id` / `store_id` / `account_id` 参数 | 工具入参由 LLM 生成，**塞不进** shop_id；归属只能由 ContextVar 注入。缺通道 ⇒ 注册出来的是个**跨租户**的口子 |
| 3 | **有无 Agent 消费场景** | 读该端点被谁消费：是「Agent 要判断的依据」还是「给人用的界面动作」 | 分组 / 下拉选项 / 输入框辅助这类动作，Agent 自己不需要「调一次」 |
| 4 | **注册后是否引入坏形态** | 对每条候选问两个问题：会不会与**已有工具**同名同实现？工具内部会不会**再调一个 Agent**？ | 本仓判据「同一判定两份实现 ⇒ 至少一份永远测不到」；以及「工具调 Agent」是递归 |

---

## 二、主表：16 条剩余缺口逐条裁决

| # | Agent | 建议工具 | 端点 | 裁决 | 理由 | 前置条件 |
|---|---|---|---|---|---|---|
| 1 | 选品分析师 | `get_candidate` | `GET /candidates/{id}` | ✅ **必要 · 已落地** | 老板点名「获取选品」的后半；评审决策的输入 | 已解（下沉 service） |
| 2 | 选品分析师 | `review_candidate` | `PATCH /candidates/{id}/review` | ✅ **必要 · 已落地** | 候选生命周期另一半：淘汰 / 转评审中 | 已解 + 自动进审批面 |
| 3 | 选品分析师 | `approve_candidate` | `POST /candidates/{id}/approve` | ✅ **必要 · 已落地（P0）** | 候选 → 产品库的**唯一通道**，老板点名「入产品库」 | 已解 + 自动进审批面 |
| 4 | 选品分析师 | `update_candidate` | `PUT /candidates/{id}` | ⚠️ 必要 · **形态待定** | 修正候选数据是真实需求 | ★ 该端点接受 **34 个**可更新字段，**没有干净的扁平工具签名**。需先拍板：只暴露常用子集，还是收一个 JSON 对象参数 |
| 5 | 选品分析师 | `list_candidate_groups` | `GET /candidate-groups` | ❌ 不必要（P2） | 分组是**给人用的界面组织手段**（人给人分类）；Agent 没有「按分组再筛一遍」的消费场景 | — |
| 6 | 选品分析师 | `create_candidate_group` | `POST /candidate-groups` | ❌ 不必要（P2） | 同上。分组由人在面板上建，不是 Agent 的判断依据 | — |
| 7 | 选品分析师 | `calculate_store_profit` | `POST /stores/profit/calculate` | ⚠️ **必要，但前置是安全** | 与 `analyze_profit`（手填成本）口径互补，是两个不同问题的答案，缺了会出现「用错口径算利润」 | ★★ **现状无归属校验**：签名里只有必填 header `X-Store-ID`，**没有** `current_user`，也**没有** `_ensure_store_access()`（该方法在 :499/:600/:647 都有，唯独漏这条路径）⇒ 传别人的店照算，传不存在的店 404 ⇒ 存在性可枚举。注册前必须①补归属校验 ②下沉 service。★ **对第 204 轮口径的更正**：`_store_db` 已**不是**「不持久的内存字典」，而是 PG 回灌的**读缓存**（`load_stores_into_memory()` :60，写双写）⇒「落库」**已完成**，不必再做 |
| 8 | Listing 优化师 | `list_products` | `GET /api/v1/skus` | ⚠️ 必要 · **硬前置缺失** | Listing 生成的结果要落地，前提是它能读自己的产品库 | ★ `listing_generator` **全模块 0 处** `shop_id` / `store_id` / `tenant` 引用（agent 与 tools 都为零）⇒ 必须先给它建**归属通道**，否则注册出来即跨租户 |
| 9 | Listing 优化师 | `get_product` | `GET /skus/{id}` | ⚠️ 必要（P2） | 与 #8 同族，单条查询 | 同 #8；且 `products` 模块**根本没有 `service.py`**（14 个端点的业务逻辑全内联在 `router.py`）⇒ 需先提取 |
| 10 | Listing 优化师 | `update_sku_listing` | `PATCH /skus/{id}/listing` | ⚠️ 必要（P0）· 前置同 #8/#9 | Listing 优化师生成的东西**真正落地**的那一步；不注册等于每次生成都不落地 | Listing 归属通道 + `products` service 化 + 副作用档（写库 ⇒ 需人工审批） |
| 11 | 竞品监控员 | ~~`get_monitor_dashboard`~~ | `GET /competitor/monitor/dashboard` | ❌ **不必要（撤回原提议）** | 该 handler 的实现就是 `await service.monitor_competitor(request, store_id=store_id)` —— 与**已有工具 `monitor_competitor` 逐字同一份实现**。注册即成「同能力两名」 | — |
| 12 | 竞品监控员 | `monitor_candidate` | `POST /candidates/{id}/monitor` | ✅ 必要（P1）· 本轮未落地 | 竞品监控员**回填自己产出的快照**，是它自己的闭环（否则监控结果只能靠人在界面点回填） | `router → service` 提取（与 #1–#3 同型，成本已共担） |
| 13 | 智能客服 | ~~`track_order`~~ | `POST /order/track` | ❌ **不必要** | 该 service 内部是 `get_cs_agent().invoke(...)` —— 注册成工具就是「Agent 调工具、工具再调 Agent」的**递归**，且客服 Agent 内部**本就有**订单上下文与 `order_tracking` 状态。另外 `OrderTrackRequest` 只有 `{order_id, email, phone_last4}`，**无任何店铺字段** ⇒ 归属无法注入 | — |
| 14 | 智能客服 | ~~`get_faq_categories`~~ | `GET /faq/categories` | ❌ 不必要（P2） | 它返回的是**界面下拉框的静态分类**（由 `get_capabilities` + 客服知识库拼出）；客服已有 `search_faq` 按语义取答案，再给一个分类枚举没有增量 | — |
| 15 | AIGC 媒体生成器 | ~~`enhance_prompt`~~ | `POST /aigc/prompt/enhance` | ❌ **不必要** | service 直接调 `agent.enhance_prompt(...)` = **Agent 自身的方法**；且它是「**对话输入框的辅助**」（帮用户把草稿改写得可执行），Agent 调它是递归 | — |
| 16 | AIGC 媒体生成器 | ~~`translate_selection`~~ | `POST /aigc/content/translate-selection` | ❌ **不必要** | 同类：源码注释自述「与 `translate_selection_service` 并列：都是**轻量 LLM 辅助**，都只回一段文本」，面向**用户的阅读辅助** | — |

**小计**：必要 **9**（已落地 3 + 未落地 6）／不必要 **7**。

---

## 三、本轮批 B 已落地的 3 条：改动点

### 3.1 为什么这 3 条是「同一批」

它们在 `candidates/router.py` 里是**同一个形态**：业务逻辑**内联在 handler 体**
（`async_session_factory()` / `select()` / `scoped()` 直接写在函数里），
`service.py` 里**没有**对应函数。⇒ 三条共担同一次「下沉」的成本，分开做要付三遍。

### 3.2 改动点

| 文件 | 改动 | 前 → 后（字节） |
|---|---|---|
| `modules/candidates/service.py` | 新增 `get_candidate` / `review_candidate` / `approve_candidate` + `_load_scoped()` + `REVIEW_STATUSES` + `_UNSET` 哨兵 | 10,075 → 18,871 |
| `modules/candidates/router.py` | 3 个 handler 改为委派；`approve` 的 65 行内联体删除（`SpuRecord` 构造移入 service） | 14,790 → 12,866 |
| `modules/candidates/__init__.py` | 门面出口 5 → **8**（新增 3 条） | 1,163 → 1,807 |
| `modules/product_research/tools.py` | 新增 3 个工具函数 + 3 条 `StructuredTool` 注册 + `_NO_SHOP_HINT` | 12,874 → 18,326 |
| `modules/skills/tools_catalog.py` | 目录表 **57 → 60**；`ProductResearcher` 5 → 8 条 | 36,347 → 37,300 |
| `ai_infra/tools/side_effects.py` | `WRITE_VERB_PREFIXES` 补 `approve_` / `review_` | 11,890 → 12,358 |

### 3.3 三个刻意的设计决定

1. **`shop_id` 是必填位置参数，没有默认值。**
   本仓判据「签名即门禁」：调用方必须显式交代归属从哪来，禁掉
   「忘了传 ⇒ `scoped()` 跳过过滤 ⇒ 跨租户读到别人的候选」这条静默路径。
   传 `None` 只允许 REST 路由沿用既有语义；工具层在拿不到店铺时**硬拒绝**。
2. **「不存在」与「不属于你」返回同一个 `None`、同一句文案。**
   两者一旦可区分，就能拿 id 逐个试探、确认哪些 id 真实存在 ⇒ 可枚举别人的候选。
3. **`update_candidate` 故意**没做**。** 它接受 34 个可更新字段，没有一个诚实的
   扁平工具签名。硬做只能二选一：暴露一个不完整的子集（模型会以为那是全部），
   或者收一个「参数是个 JSON 字符串」（模型经常写坏）。这是**该拍板的事**，
   不该我单方面决定（见第五节）。

### 3.4 副作用档与审批面

`review_candidate` / `approve_candidate` 会写库 ⇒ 声明 `SIDE_EFFECT_METADATA`。
本仓的审批名单是 `BaseAgent._wrap_hitl_tools()` 按 `has_side_effects()`
**自动推导**的（业务侧没有手写名单可漏），所以这次**不需要**改 `agent_*.py`；
代价是四处「钉住旧形态」的门禁期望值必须同步，且必须**自觉**地改：

| 门禁 | 期望值变化 | 为什么必须改 |
|---|---|---|
| `test_tool_catalog.py::test_the_expected_tools_need_approval` | `["create_ticket","save_candidate"]` → 4 条 | 界面上的「需审批」标记不能骗人 |
| `test_hitl_policy.py::EXPECTED_GATED` | 2 → 4 条 | 推导结果的对账另一侧 |
| `test_hitl_wiring.py::test_router_wraps_exactly_the_gated_tools` | `{"save_candidate"}` → 3 条 | 防止「包装按名字命中、名字写错就静默落空」 |
| `test_secretary_agent.py` ×2 | 7 → 10 / 8 → 11 | 业务工具集合的墓志铭 |

### 3.5 新增的门禁（可执行判据）

新建 `tests/test_candidate_lifecycle_tools.py`（4 条）。**注释里的承诺不构成
门禁** —— 三条工具的注释都许了「无归属硬拒绝」「归属透传」，本文件把两条承诺
各配一条可执行用例：

| 用例 | 钉住什么 | 怎么证 |
|---|---|---|
| `test_all_three_refuse_without_shop` | 无归属 ⇒ 三条都拒绝 | 数 **service 调用次数 = 0**（文案可以伪装，调用计数不行） |
| `test_all_three_pass_shop_id` | 有归属 ⇒ 原样透传 | 桩**收到** `shop_id` 的值 |
| `test_not_found_and_foreign_share_one_message` | 两种原因同一文案 | 逐字比较 |
| `test_new_write_tools_are_approval_gated` | 读免审批 / 写进审批 | 读**运行时** `has_side_effects()` |

**反向注入 4 组，全部真红 + 逐字节还原**（`.workbuddy/probes/out_r205bd_inject.txt`）：

| 注入 | 转红用例 |
|---|---|
| A 拆掉归属守卫 | `test_all_three_refuse_without_shop` |
| B 写库归属换成 `None` | `test_all_three_pass_shop_id` |
| C `approve_candidate` 副作用档改成只读 | **6 条**：`test_new_write_tools_are_approval_gated`、`test_router_wraps_exactly_the_gated_tools`、`test_catalog_effect_matches_runtime_side_effect_declaration`、`test_gated_set_matches_policy_derivation`、`test_wrapped_tool_keeps_name_and_schema`、`test_write_verb_tools_are_never_exempted` |
| D 目录表删一条 | `test_catalog_is_not_vacuous`、`test_catalog_names_match_real_assembly` |

★ 注入 C 的读数值得记一笔：目录侧那条 `test_the_expected_tools_need_approval`
**没有红**（目录表确实没被改），红的是**运行时镜像侧**那条
`test_catalog_effect_matches_runtime_side_effect_declaration`。
两条判据的分工是对的：一条管「目录改了、运行时没改」，另一条管反向。

---

## 四、与前一轮（204）的差异

| 项 | 第 204 轮 | 第 205 轮 |
|---|---|---|
| 工具总数 | 55 | **60** |
| 跨 Agent 共用面 | 无（3 组同名同端点待拍板） | `{list_candidates, list_products}`，各 2 家，**判据 G/H 钉住** |
| 老板点名「获取选品」 | ❌ 缺 | ✅ `get_candidate` + 共用 `list_candidates` |
| 老板点名「入产品库」 | ❌ 缺（唯一通道 Agent 够不着） | ✅ `approve_candidate` |
| 需人工审批的工具 | 2 | 4 |
| `GET /competitor/monitor/dashboard` | 列为缺口 | **撤回**：与已有工具同实现 |
| `track_order` / `enhance_prompt` / `translate_selection` | 列为缺口 | **撤回**：注册即递归 |

---

## 五、三条需要拍板的事（不做完这些，剩下的 6 条不该动）

| # | 事项 | 为什么需要你决定 |
|---|---|---|
| **P0-安全** | `calculate_store_profit` 没归属校验 | 补法有两种：①在这条路径上加归属校验（最小改：签名的 header 依赖换成 `current_user`，再调一次 `_ensure_store_access()`）②连 `_get_store()` 的 404 语义一起改 —— **「不存在」与「不属于你」返回同一个响应**（本仓既有判据），否则仍留着存在性枚举面。★ **口径更正**：店铺源**已经**收到 PG（`load_stores_into_memory()` + 写双写），原先第 204 轮说的「②顺手落库」**不必再做**。但①是**会改变行为**的一刀：此前任何持合法 header 的调用都 200，改后非归属方变 403/404，前端调用点需一并核 |
| **P0-设计** | Listing 优化师的**归属通道** | `listing_generator` 全模块没有任何店铺归属引用。它需要一条与 `competitor_intel` 同型的 ContextVar 通道（谁在入口 `_bind_context`？会话里怎么带？），这是**一个功能**不是一次接线 |
| **P1-形态** | `update_candidate` 的工具签名 | 34 个字段：暴露子集 vs 收 JSON 对象。定了才谈得上落地 |

---

## 六、核验口径与证据

| 环节 | 做法 | 证据文件 |
|---|---|---|
| 缺口前置事实 | AST 取 7 个模块的端点表 + service 签名（含 class 方法）+ Agent 归属词 + 工具注册表 | `.workbuddy/probes/out_r205aw_gapfacts.txt`（探针 `r205aw_gap_facts.py`） |
| 端点实现形态 | 逐端点看它是「调 service」还是「内联 `async_session_factory()`」 | 同上门禁表 |
| 归属通道 | `listing_generator` 归属词命中 = **无**；`candidates` 13 个 handler **全部**带 `shop_id` | 同上 |
| 落盘复核 | 按**磁盘字节**判（不认工具回执）：字节数 / 行尾 / 语法三项 | `.workbuddy/probes/out_r205ay_verify_run.txt` |
| 幂等 | 补丁复跑：全部「幂等跳过」，零字节变化 | `.workbuddy/probes/out_r205ay_reapply.txt` |
| 门禁 | 7 部门禁 114 条 0 失败；新增用例 4 条 0 失败 | `xml_r205b_gate2.xml` / `xml_r205b_life2.xml` |
| 反向注入 | 4 组，全真红 + 逐字节还原 | `.workbuddy/probes/out_r205bd_inject.txt` |
| 全量回归 | 单进程、不与任何 pytest 并发 | `.workbuddy/probes/xml_r205b_full.xml` |

---

## 七、下一步建议（按优先级）

| 优先级 | 事项 | 理由 |
|---|---|---|
| **P0** | 给 `calculate_store_profit` 补归属（或连同店铺源落库一起） | 现状是**无归属校验**的算利润入口，不补就不该交给模型 |
| **P0** | 给 Listing 建立归属通道，然后 `update_sku_listing` | 否则 Listing 的产出**永远不落地**；而它在没有归属通道前，任何产品库工具都是跨租户口子 |
| **P1** | `monitor_candidate` | 与 #1–#3 同型的提取，成本已共担；竞品监控的回填闭环缺它 |
| **P1** | `update_candidate`（先定签名形态） | 34 字段需要先拍板 |
| **P2** | `get_product` + 候选/产品分组 | 低频 |
| — | ~~`get_monitor_dashboard` / `track_order` / `get_faq_categories` / `enhance_prompt` / `translate_selection`~~ | **撤回**，理由见第二节 |

---

## 八、`calculate_store_profit` 补归属：**会改变什么**（第 205 轮续 · 实采）

老板要求「先告诉我」再动手。以下是逐场景实测，不是推断。

### 8.1 ★ 先更正我自己前一条的不准确表述

我在首轮汇报里写「此前任何持合法 header 的调用都 200」—— **这句不对**。

`main.py:474` 已经把整个 stores 路由**无条件**挂在 `BUSINESS_AUTH` 下：

```python
BUSINESS_AUTH = [Depends(require_auth_if_enabled)]     # main.py:367，第 106 轮起不再条件化
app.include_router(stores_router, dependencies=BUSINESS_AUTH)   # main.py:474
```

⇒ **认证层本来就存在**。带真 token 时身份**已经被解析出来**（无效 → 401 / 禁用 → 403），
只是解析出的 `User` 被**丢掉**了 —— 因为 router 级依赖**不向 handler 注入参数**。
这正是本仓那条「**路由级依赖 ≠ 端点有身份**」。

所以缺的是**授权**（这条数据归不归你），不是认证（你是谁）。

### 8.2 逐场景：只有一个变了

| # | 场景 | 现在 | 补归属后 | 变化 |
|---|---|---|---|---|
| A | 无凭据 + `AUTH_REQUIRED=true` | 401 | 401 | 不变 |
| B | 无凭据 + `AUTH_REQUIRED=false`（本地演示） | 200 | 200 | 不变（`current_user is None` ⇒ `_ensure_store_access` ①② 都放行） |
| C | `demo-token` 哨兵 | 200 | 200 | 不变 |
| D | 真 token + `X-Store-ID` = **自己的店** | 200 | 200 | 不变 |
| E | 真 token + `X-Store-ID` = **别人的店** | **200，返回别人的利润明细** | **403** | ★ **唯一实质变化** |
| F | `X-Store-ID` = 不存在的 id | 404 | 404 | 不变（保持 `_get_store()` 先判） |
| G | 缺 `X-Store-ID` | 422 | 422 | 不变 |

### 8.3 前端调用点（全仓 2 处，已逐处核）

| 调用点 | 传的 storeId | 结论 |
|---|---|---|
| `components/TaskConfigPanel/configs/ProfitConfig.vue:399` | `shopId.value`（当前选中店铺） | 恒走场景 D ⇒ 不变 |
| `composables/chat/toolResultPost.ts:27-29` | `useShopStore().currentShopId` | 恒走场景 D ⇒ 不变 |

且 `ProfitConfig.vue:401-407` **已有** try/catch 把失败写回 `previewError`
（源码注释就写着「降级必须给出原因，绝不编一个数字顶上」）⇒ 即便真触发 403 也**不会静默**。

### 8.4 后端测试影响

`tests/test_stores.py` 的 4 条利润用例**全部带 `auth_off`** ⇒ `current_user=None` ⇒ 走演示分支放行
⇒ **保持全绿**；`test_routes_under_business_auth_gate` 是源码断言，不受影响。

⇒ **这一刀的风险面极窄：唯一被改变的是场景 E（跨租户读别人的利润）。**

### 8.5 改完**仍会残留**的事（要单独决定）

`_get_store()` 在归属判定**之前**跑，且查的是**全量内存缓存（不看用户）**
⇒ 「不存在 = 404」「不属于你 = 403」**可区分** ⇒ 仍可逐个试探 store_id 是否存在。

`stores/router.py:306-311` 的 docstring **自己承认了**这点，并记为批 C 遗留 **C6**。
统一成 403 需要同时处理「演示模式下 store 为 None」的分支 ⇒ 属**另一个决定**
（会动 `test_profit_calculate_unknown_store_404` 的期望值与前端的 404 分支）。

### 8.6 现在**没有**完整性门禁

全仓只有 `test_stores.py` 的 4 处提到 `X-Store-ID`，**没有任何判据**要求
「凡读 `X-Store-ID` 的端点必须调 `_ensure_store_access`」⇒ **同类洞可能不止这一处**。
补这条门禁与补这个洞应当**同一批做**，否则下一个人还会漏。

---

## 九、★ 新发现：`current_shop_id()` 是一个**死通道**（全仓 0 个写入点）

这条与「Listing 归属通道」直接相关，故一并记下。

| 环节 | 位置 | 事实 |
|---|---|---|
| 变量 | `core/observability/context.py:54` | `_shop_id_var`，`default=""` |
| 唯一写入口 | 同文件 `:96` | `set_request_context(shop_id=...)` |
| 读口 | 同文件 `:121` | `current_shop_id()` |

实测**全仓** `set_request_context(` 的调用点：
`core/middleware/request_log.py:85`（request_id / client_ip）、
`core/auth/dependencies.py:130`/`:294`/`:437`（user_id / client_ip）、
`core/tenant/middleware.py:299`（**account_id**）。

**没有任何一处传 `shop_id=`** ⇒ `current_shop_id()` 在生产里**恒返回 `""`**。

这是本仓那条「判横切是否收敛要数**接入点的埋点**」的**第三例**
（前两例：`LLM_CALLS`、`current_user_id()` 曾全仓 0 个 inc）。

★ 最讽刺的一处：`core/tenant/middleware.py:280-288` **刚刚校验完归属**、手里正握着
已验证的 `shop_id`，紧接着 `:299` 只写了 `account_id`。而那段 docstring 专门论证了
「为什么必须**解析出具体店铺之后**才写上下文」—— 同一段理由对 `shop_id` **完全成立**，却没写。

**对「Listing 归属通道」的直接含义**：与其加**第 6 份** module-local `_current_shop_id`
ContextVar（现有 5 份：`competitor_intel` / `ad_analysis` / `customer_service` /
`product_research` / `review_analyst`），不如让 `middleware.py:299` 顺手补一行
`set_request_context(shop_id=shop_id)` —— **一行同时修掉这个死通道**。

⚠️ **但必须先实测**：请求级 ContextVar 能否透传到 LangGraph 的图节点 / 工具执行点。
那 5 家各自在**图入口**显式 `set`，可能正是为了绕开这个不确定性 —— 结论未验证前不下判断。
