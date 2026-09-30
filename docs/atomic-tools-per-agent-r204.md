# 每个 Agent 的原子级操作工具清单（第 204 轮）

> 需求原文：「帮我罗列出适合每个 agent 的原子级操作工具（并判断我是否已有工具），
> 如选品分析师的利润测算、获取选品、入选品库、入产品库等，这些原子级工具用于
> 注册给 agent 用；结果给我一张列表即可」

## 一句话结论

机械核验 22 条候选原子工具：**✓已有 2 条 / ✗缺 20 条**。
老板点名的四条里，「获取选品」和「入产品库」**都没有工具** —— 而「入产品库」
（`POST /api/v1/candidates/{id}/approve`）是**候选→产品库的唯一通道**，
Agent 目前够不着。

「已有」的判定真源是 `modules/skills/tools_catalog.py::TOOL_CATALOG`（**55** 个，
受 `tests/test_tool_catalog.py` 的门禁钉住），不是肉眼读代码。

---

## 一、主表：建议注册给 Agent 的原子级工具（22 条）

| # | Agent | 建议工具名 | 读写 | 对应后端原子能力（端点） | 现状 |
|---|---|---|---|---|---|
| 1 | 选品分析师 `ProductResearcher` | `analyze_profit` | R | `POST /product-research/profit` | ✅ **已有** |
| 2 | 选品分析师 | `list_candidates` | R | `GET /api/v1/candidates` | ❌ **缺** |
| 3 | 选品分析师 | `get_candidate` | R | `GET /api/v1/candidates/{candidate_id}` | ❌ **缺** |
| 4 | 选品分析师 | `save_candidate` | W | `POST /api/v1/candidates` | ✅ **已有**（HITL 审批） |
| 5 | 选品分析师 | `review_candidate` | W | `PATCH /api/v1/candidates/{candidate_id}/review` | ❌ **缺** |
| 6 | 选品分析师 | `approve_candidate` | W | `POST /api/v1/candidates/{candidate_id}/approve` | ❌ **缺** ← **「入产品库」唯一通道** |
| 7 | 选品分析师 | `update_candidate` | W | `PUT /api/v1/candidates/{candidate_id}` | ❌ **缺** |
| 8 | 选品分析师 | `list_candidate_groups` | R | `GET /api/v1/candidate-groups` | ❌ **缺** |
| 9 | 选品分析师 | `create_candidate_group` | W | `POST /api/v1/candidate-groups` | ❌ **缺** |
| 10 | 选品分析师 | `calculate_store_profit` | R | `POST /api/v1/stores/profit/calculate` | ❌ **缺** |
| 11 | 选品分析师 | `list_products` | R | `GET /api/v1/skus` | ❌ **缺** |
| 12 | Listing 优化师 `ListingGenerator` | `list_skus` | R | `GET /api/v1/skus` | ❌ **缺** ★与 #11 同端点 |
| 13 | Listing 优化师 | `get_sku` | R | `GET /api/v1/skus/{sku_id}` | ❌ **缺** |
| 14 | Listing 优化师 | `update_sku_listing` | W | `PATCH /api/v1/skus/{sku_id}/listing` | ❌ **缺** ← 生成结果**真正落地**的那一步 |
| 15 | 竞品监控员 `competitor_intel` | `get_monitor_dashboard` | R | `GET /competitor/monitor/dashboard` | ❌ **缺** |
| 16 | 竞品监控员 | `monitor_candidate` | W | `POST /api/v1/candidates/{candidate_id}/monitor` | ❌ **缺**（回填候选快照） |
| 17 | 智能客服 `customer_service` | `track_order` | R | `POST /customer-service/order/track` | ❌ **缺** |
| 18 | 智能客服 | `get_faq_categories` | R | `GET /customer-service/faq/categories` | ❌ **缺** |
| 19 | AIGC 媒体生成器 `aigc_media` | `enhance_prompt` | R | `POST /aigc/prompt/enhance` | ❌ **缺** |
| 20 | AIGC 媒体生成器 | `translate_selection` | R | `POST /aigc/content/translate-selection` | ❌ **缺** |
| 21 | 店秘书 `secretary` | `list_candidates` | R | `GET /api/v1/candidates` | ❌ **缺** ★与 #2 同端点 |
| 22 | 店秘书 | `list_products` | R | `GET /api/v1/skus` | ❌ **缺** ★与 #11 同端点 |

## 二、按 Agent 汇总

| Agent | 候选数 | ✅ 已有 | ❌ 缺 | 说明 |
|---|---|---|---|---|
| 选品分析师 `ProductResearcher` | 11 | 2 | **9** | 缺口集中在**候选库/产品库的读写**（带状态的流转动作） |
| Listing 优化师 `ListingGenerator` | 3 | 0 | **3** | 生成能力已齐；缺的是「读/写自有产品库」 |
| 竞品监控员 `competitor_intel` | 2 | 0 | **2** | — |
| 智能客服 `customer_service` | 2 | 0 | **2** | — |
| AIGC 媒体生成器 `aigc_media` | 2 | 0 | **2** | — |
| 店秘书 `secretary` | 2 | 0 | **2** | 缺「读资料库」类原子工具 |
| 运营复盘师 `review_analyst` | 0 | — | 0 | **零缺口**：6 个能力端点全部有工具 |
| 广告分析师 `ad_analysis` | 0 | — | 0 | **零缺口**：6 个能力端点全部有工具 |
| **合计** | **22** | **2** | **20** | 去重后工具名 **20 个**（3 组同名同端点） |

## 三、老板点名的四条（逐条实测答案）

| 动作 | 建议工具 | 现有端点 | 实测结论 |
|---|---|---|---|
| 利润测算 | `analyze_profit` | `POST /product-research/profit` | ✅ **已有**（`ProductResearcher`，手填成本口径） |
| **获取选品** | `list_candidates` / `get_candidate` | `GET /api/v1/candidates[/{id}]` | ❌ **缺** —— 端点在、工具不在 ⇒ Agent 列不出候选库 |
| 入选品库 | `save_candidate` | `POST /api/v1/candidates` | ✅ **已有**（全仓仅 2 个带副作用 + 真装配的工具之一，走 HITL 审批） |
| **入产品库** | `approve_candidate` | `POST /api/v1/candidates/{id}/approve` | ❌ **缺** —— 这是候选→产品库**唯一通道**，Agent 够不着 |

★ 补充：另有 `calculate_store_profit`（`POST /api/v1/stores/profit/calculate`）
是**按店铺真实费率**算利润，与 `analyze_profit`（手填成本）**口径不同**，也缺。
两个都注册才不会出现「用错口径算利润」。

## 四、三个「同端点多名」需要先拍板

| 端点 | 被哪几个 Agent 重复提议 | 建议 |
|---|---|---|
| `GET /api/v1/candidates` | 选品分析师 `list_candidates` / 店秘书 `list_candidates` | 收敛为**一个**工具，注册给两家（工具可复用） |
| `GET /api/v1/skus` | 选品分析师 `list_products` / Listing 优化师 `list_skus` / 店秘书 `list_products` | 同上，且**统一命名**（`list_products` 与 `list_skus` 是同一件事的两个名字） |

理由：本仓既有判据「同一判定两份实现 ⇒ 至少一份永远测不到」。
同一能力注册成两个名字，模型会在两处乱选，而测试只会覆盖其中一条。

## 五、故意**未**列入的端点及理由

| 端点 | 为什么不算「原子级工具」 |
|---|---|
| `POST /analyze`（竞品情报 `general_analysis`） | 「自然语言分析入口」= 与 Agent 自身职责重叠，不是原子操作 |
| 3 个 GET 快捷接口（`/intruders/{cat}`、`/market-share/{cat}`、`/reviews/{asin}`） | 是已被工具覆盖的 POST 端点的简化写法，注册进去只会造成二选一 |
| `POST /product-research/approval/resume` | HITL 恢复通道，**由人**回传决策；Agent 不该自主调 |
| `/chat`、`/chat/stream`、`/capabilities`、`/health`、`/tools`、`/quick-reply` | 入口 / 元信息，不是可组合的原子操作 |
| `/jobs*`（AIGC 异步任务 3 个） | 任务队列管理，不是业务原子操作 |
| 各模块的 `*.search / list` 元数据端点 | 同上 |

## 六、核验口径与证据

| 环节 | 做法 | 证据文件 |
|---|---|---|
| 「已有」判定 | 查 `TOOL_CATALOG`（55 条，受门禁钉住），**不读源码字符串** | `backend/modules/skills/tools_catalog.py` |
| 能力池枚举 | 按模块 AST 取 `APIRouter` 端点 + service 公开方法 | `.workbuddy/probes/out_r204n_inventory.txt` |
| 逐条 ✓/✗ | 22 条候选 ↔ 55 条已有，机械对照 | `.workbuddy/probes/out_r204o_gap.txt` |
| 端点引用自检 | 每条候选的端点路径必须在 AST 里真实存在 | 同上（**全部命中，无编造**） |
| 本轮接线门禁 | 19 个悬空工具已接上对应 Agent + 反向注入 10 组 | `.workbuddy/probes/out_r204l_inject.txt` |
| 本轮新判据反向注入 | 5 组（含本轮改口径的 3 条）全部真红 + 字节还原 | `.workbuddy/probes/out_r204u_inject.txt` |

## 七、下一步建议（按优先级）

| 优先级 | 事项 | 理由 |
|---|---|---|
| **P0** | `list_candidates` / `get_candidate` / `approve_candidate` | 老板点名的两条缺口，且 `approve_candidate` 是入产品库唯一通道 —— 不注册，**选品闭环在 Agent 侧断掉** |
| **P0** | `update_sku_listing` | Listing 优化师生成的东西**没有回写通道**，等于每次生成都不落地 |
| **P1** | `track_order` / `get_monitor_dashboard` | 客服/竞品的常用只读入口，端点现成 |
| **P1** | `calculate_store_profit` | 与 `analyze_profit` 口径互补，防「用错口径算利润」 |
| **P2** | 候选/产品分组类（`*_groups`） | 低频，可后置 |
