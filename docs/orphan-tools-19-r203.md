# 19 个悬空工具清单（附中文解释）

> 第 203 轮 · 数据全部来自 AST 探针实测，非人工整理。
> 探针：`.workbuddy/probes/r203_orphans.py` / `r203b_landing.py` / `r203c_endpoints.py` / `r203d_crosscheck.py` / `r203e_map.py`

## 一句话结论

这 19 个工具**不是没做完的空壳**：每个都有完整实现、100% 打到真实 service 方法，而且**同一批 service 出口早已被 REST 端点暴露给前端**。

它们「悬空」的唯一含义是 —— **所属 Agent 从未把 `tools.py` 里的工具列表交给自己**，所以 LLM 看不到、调不到。**能力不缺，缺的是给 Agent 的那条通道。**

---

## 一、悬空是怎么判的（口径可复算）

复刻 `backend/tests/test_tool_registry_guard.py` 的棘轮口径：把 `modules/*/tools.py` 里的模块级容器（`*_tools`）拿出，扫全仓 AST 的 `Name(Load)` 出现次数，**零引用 = 悬空**。

实测结果：

| 项 | 读数 |
|---|---|
| 悬空容器 | **3 个** |
| 悬空工具 | **19 个** |
| 门禁 `KNOWN_ORPHAN_REGISTRIES` 登记 | 4 个（多了 `review_analyst/tools.py::review_analyst_tools`） |
| 门禁 `ORPHAN_TOOL_BUDGET` | 25（实测仅 19 ⇒ 额度虚高 6） |

> `review_analyst_tools` 其实**早已装配**（`review_analyst/agent.py:229` `BaseAgent(tools=review_analyst_tools)`），却仍在悬空名单里登记 ⇒ 属于「陈旧登记项」，导致棘轮额度虚高 6，还能悄悄新增 6 个悬空工具不转红。

---

## 二、19 条清单（含中文解释）

说明文字取自**工具自己写给模型的 `description`**（不是二次转述），因此它同时就是「Agent 该在什么时候调它」的触发条件。

### 容器 1 · `modules/ad_analysis/tools.py :: ad_analysis_tools` —— 广告分析（6 个）

| # | 工具名 | 中文说明（写给模型的原文） | 参数 | 对应 REST 端点 |
|---|---|---|---|---|
| 1 | `diagnose_ad_account` | 广告账户健康诊断：多维度评估广告表现，生成评级与问题清单。当用户想诊断广告/体检/看广告健康/广告表现怎么样时使用。 | `time_range='30d'`, `include_benchmark=True` | `POST /ad-analysis/diagnose`（+`GET /ad-analysis/quick/diagnose`） |
| 2 | `analyze_search_terms` | 搜索词效果分析：识别高效/低效/浪费词，挖掘新机会词。当用户想看搜索词报告/哪些词表现好/词报告时使用。 | `time_range='30d'`, `sort_by='spend'`, `min_spend=5.0`, `min_clicks=5` | `POST /ad-analysis/search-terms` |
| 3 | `optimize_bids` | 出价优化建议：按策略给出关键词/广告组的智能出价建议。当用户想优化出价/调价/给出价建议/控制 ACOS 时使用。 | `strategy='balanced'`, `target_acos=None`, `keywords=None` | `POST /ad-analysis/bid-optimize` |
| 4 | `analyze_ad_competitors` | 竞品广告分析：分析竞争对手广告策略、展示份额、关键词重叠。当用户想分析竞品广告/对手投放/展示份额时使用。 | `competitor_asins=None`, `auto_detect=True`, `time_range='30d'` | `POST /ad-analysis/competitors` |
| 5 | `optimize_budget` | 预算分配优化：多 Campaign 智能分配预算，提升整体 ROI。当用户想优化预算/分配预算/调拨预算/提升 ROI 时使用。 | `total_daily_budget=None`, `target_roas=None`, `seasonality_factor='normal'` | `POST /ad-analysis/budget` |
| 6 | `detect_ad_anomalies` | 广告异常检测：自动检测花费突增、转化骤降等异常。当用户想查异常/看有没有突然变化/检测波动时使用。 | `check_period='7d'`, `sensitivity='medium'` | `POST /ad-analysis/anomalies`（+`GET /ad-analysis/quick/anomalies`） |

### 容器 2 · `modules/aigc_media/tools.py :: aigc_tools` —— AIGC 素材（9 个）

| # | 工具名 | 中文说明（写给模型的原文） | 对应 REST 端点 |
|---|---|---|---|
| 7 | `generate_product_image` | 产出产品图片的**提示词包**（提示词、SEO 关键词、文案建议、风格指南），**不生成、不返回图片文件**。当用户只要出图方案/提示词/主图文案时使用；当用户要真正的图片时，**必须改用 `generate_assets`**。 | `POST /aigc/image/generate` |
| 8 | `generate_assets` | 生成产品静态素材图片（白底图/场景图/主图/信息图/广告图），**返回真实图片 URL**。当用户要图片本身、要出图、要做白底图/主图/场景图时使用。（若只要提示词或文案方案，用 `generate_product_image`。） | `POST /aigc/asset/generate` |
| 9 | `analyze_main_image` | 分析产品主图质量（评分、CTR 预测、合规、改进建议）。当用户想诊断/优化主图时使用。 | `POST /aigc/image/analyze` |
| 10 | `generate_a_plus_content` | 生成 A+ 内容（EBC 增强品牌内容）各模块。当用户想做 A+ / EBC / 详情页品牌内容时使用。 | `POST /aigc/content/a-plus` |
| 11 | `generate_brand_story` | 生成品牌故事（定位、使命、卖点、标语、叙事角度）。当用户想写品牌故事/品牌文案时使用。 | `POST /aigc/content/brand-story` |
| 12 | `translate_content` | 多语言内容翻译（含 SEO 优化与关键词保留）。当用户想翻译文案到其他语言时使用。 | `POST /aigc/content/translate` |
| 13 | `generate_infographic` | 生成营销信息图规格（分区、文案、配色、CTA）。当用户想做信息图/营销图时使用。 | `POST /aigc/design/infographic` |
| 14 | `check_image_compliance` | 检查图片合规性（状态、评分、问题清单、整改建议）。当用户想检查图片是否合规时使用。 | `POST /aigc/compliance/check` |
| 15 | `generate_video_script` | 生成短视频脚本（分镜、旁白、字幕、钩子、CTA）。当用户想做短视频/视频脚本时使用。 | `POST /aigc/video/script` |

> `[07]` 与 `[08]` 是一组**能力边界对**：前者只出方案、后者真出图。两条 description 互相点名，接进 Agent 时必须**成对接**，否则模型会拿提示词包当图片交付。

### 容器 3 · `modules/customer_service/tools.py :: customer_service_tools` —— 智能客服（4 个）

| # | 工具名 | 中文说明（写给模型的原文） | 参数 | 对应 REST 端点 |
|---|---|---|---|---|
| 16 | `search_faq` | 搜索客服知识库（FAQ），返回匹配的问题与标准答案。当用户想查常见问题/找话术/搜知识库答案时使用。 | `query`, `limit=5` | `POST /customer-service/faq/search` |
| 17 | `create_ticket` | 创建客服工单，返回工单号与预计响应时间。当用户想创建工单/记录客户问题/建单时使用。 | `store_id`, `subject`, `description`, `category`, `order_id`, `priority`, `customer_id` | `POST /customer-service/ticket/create` |
| 18 | `analyze_sentiment` | 分析文本情感倾向（正面/负面/中性），返回情感标签与置信度。当用户想分析评论情感/看客户情绪/判断是好评还是差评时使用。 | `text` | `POST /customer-service/analyze/sentiment` |
| 19 | `get_conversation_summary` | 获取某段客服对话的摘要。当用户想总结对话/看会话摘要/复盘客服时使用。 | `conversation_id` | `GET /customer-service/conversation/{conversation_id}` |

> ⚠️ **`create_ticket` 是本组唯一带副作用的工具**（`SIDE_EFFECT_METADATA`，会写库建单）。接进 Agent 时必须挂 HITL 审批（本仓 `save_candidate` 是同类唯一已装配的先例）。另外 3 个是只读。

---

## 三、为什么悬空：三个 Agent 的构造**没有传 tools**

三个模块**都有 agent 文件**（`agent_ad.py` / `agent_aigc.py` / `agent_cs.py`），所以不是「没有 Agent 所以没人用」，而是**Agent 在、工具位空着**：

| Agent | 构造点 | 形态 |
|---|---|---|
| `ad_analysis/agent_ad.py` | `:417-419` | `def __init__(self):` … `super().__init__()` ← **无参** |
| `aigc_media/agent_aigc.py` | `:266-268` | `def __init__(self):` … `super().__init__()` ← **无参** |
| `customer_service/agent_cs.py` | `:301-303` | `def __init__(self):` … `super().__init__()` ← **无参** |

全仓 `tools=` 装配点只有 **5 个**（4 个 `BaseAgent(tools=…)` + 1 个 `super().__init__(tools=…)`，都在 secretary），三个悬空模块**一个都不在**。

---

## 四、悬空 ≠ 能力缺失（硬判据）

用**同一命名空间**（service 方法名）机械对账 —— 「tools 消费的 service 出口」⊆「router 消费的 service 出口」：

| 模块 | tools 出口 | router 出口 | 共有 | **仅 tools 有** |
|---|---|---|---|---|
| `ad_analysis` | 6 | 9 | 6 | **0** ⇒ 成立 |
| `aigc_media` | 9 | 13 | 9 | **0** ⇒ 成立 |
| `customer_service` | 4 | 10 | 4 | **0** ⇒ 成立 |
| **合计** | **19** | 32 | **19** | **0** |

> `aigc_media` 的 router 走的是 `AIGCMediaService.generate_product_image(...)`，而 tools 走 `generate_product_image_service(...)` —— 看起来是两条路，实为同一个函数：`service.py:499` 的 `AIGCMediaService` 是个 **`staticmethod` 别名壳**（13 条 `X = staticmethod(Y)`）。**同内核，零分叉。**

因此 19/19 个工具的能力，**前端今天就能通过 REST 端点调到**；缺的只有「Agent 也能自主调」这一条通道。

---

## 五、把工具接上去的代价（实测）

| 维度 | 读数 | 含义 |
|---|---|---|
| 工具实现完整度 | 19/19 是实实现（非 TODO / 非空壳） | 不用重写 |
| 后端落地率 | **19/19 = 100%** 命中 service 方法 | 不用补后端 |
| description 就绪度 | 19/19 已写好（写给模型看的） | 不用补提示词 |
| 调用骨架就绪度 | 19/19 已用 `StructuredTool.from_function` | 只需在 agent 构造里传参 |
| 唯一风险点 | `create_ticket` 有副作用 | 需挂 HITL |

**顺带解掉的另一个债**：第 200 轮 B3「技能绑工具」剩的 4 条无锚技能，锚工具正好都在这 19 个里 —— `ad-bid-suggest` → `optimize_bids`、`ad-budget-rebalance` → `optimize_budget`、`aigc-main-image-brief` → `generate_product_image`、`cs-refund-playbook` → `create_ticket`。三家一接上，这 4 条技能即自动有锚。

---

## 六、探针自身的坑（3 个，本轮全踩过）

写这份清单时探针给了 3 次**假结论**，每个都已修正并复跑：

1. **「单一 receiver 名」假阴性**：只认 `_service.X(...)`，对 `from .service import X` 后直接调 `X(...)` 的模块（aigc）判为 0 处 ⇒ 差点得出「aigc 工具是空壳」的反向结论。
2. **类名实例化当方法出口**：`_service = AdAnalysisService()` 里 `AdAnalysisService` 被计入「service 出口」⇒ 2 条口径噪声，需按「首字母大写」剔除并单列。
3. **`staticmethod` 别名壳**：`AIGCMediaService.generate_product_image` 与 `generate_product_image_service` 是同一函数，但名字不同、AST 不同 ⇒ 必须解析别名表才能对上。**这是本轮最隐蔽的一个坑** —— 只看调用名会得出「router 与 tools 走两条路」的架构级错误结论。

**通用教训**：跨文件做「谁调了谁」的对账时，receiver 的**所有形态**（实例变量 / 模块级导入 / 类静态壳 / 别名赋值）都要覆盖，否则假阴性会伪装成「另一端什么都没做」。

---

## 七、新增读数索引（可复算）

| 探针 | 输出 | 给出什么 |
|---|---|---|
| `r203_orphans.py` | `out_r203_orphans.txt` | 19 条 name + description + 参数签名 |
| `r203b_landing.py` | `out_r203_landing.txt` | 19 条的后端落地率 = 100% |
| `r203c_endpoints.py` | `out_r203_endpoints.txt` | 7 个模块的 REST 端点全表 |
| `r203d_crosscheck.py` | `out_r203_crosscheck.txt` | tools ⊆ router 的 service 出口对账 |
| `r203e_map.py` | `out_r203_map.txt` | 19 行「工具 → 出口 → 端点」机械映射 |
