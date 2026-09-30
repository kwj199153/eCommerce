# 每个 Agent 的原子级工具清单 · 现状与前端对账（第 206 轮）

> 老板原话：
>
>     现在的原子级工具是否写好，前端哪些在调用，结构化表格输出按不同 agent 给我介绍（包括中文说明做啥）
>
> 本文回答三问：**① 写好了吗 ② 前端哪些在调用 ③ 按 Agent 逐条说明（中文）**。
> 全部数字**运行时实测**，不手抄；每条结论都带可复算的命令/文件。

---

## 一句话结论

1. **工具层已闭环**：**60 条**原子级工具登记在唯一真源 `TOOL_CATALOG`，归属 **8 个 Agent**，
   并由门禁钉死「目录表 ≡ 真实装配点（集合相等）」——不存在「登记了但没绑上」或
   「绑上了但没登记」的工具。
2. **前端覆盖面分两档，差距在竞品**：Listing / 选品 / 复盘 / 广告 / AIGC / 客服 六家
   的工具**基本都有界面入口**；唯独 **竞品情报 8 条工具里只有 1 条（`compare_competitors`）
   在界面上有等价入口** —— 其余 7 条是「只有对话能触发、界面上没按钮」。
3. **前端调用点此前被低估 68%**：全前端 **224 次调用 / 172 个不同路径**，
   而按「`http.get(...)` 实例方法」这一种写法只扫得出 71 次 / 70 个路径 ——
   本仓 api 层有**三种调用风格**并存，只认一种就是系统性漏报。

---

## 一、总账

### 1.1 工具（真源：`modules/skills/tools_catalog.py::TOOL_CATALOG`）

| 指标 | 值 | 怎么来的 |
| --- | --- | --- |
| 条目数 | **60** | 运行时 `len(TOOL_CATALOG)`；门禁 `tests/test_tool_catalog.py:247` 钉 `== 60` |
| 归属 Agent | **8** | 见下表 |
| 跨 Agent 共用 | **2 条** | `list_candidates` / `list_products`（归 ProductResearcher + secretary 两家） |
| 副作用档 `approval` | **4 条** | `save_candidate` / `review_candidate` / `approve_candidate` / `create_ticket` |
| 副作用档 `read_only` | **56 条** | 免人工审批 |
| 禁名表 `REJECTED_TOOL_ALIASES` | **2 条** | `list_skus`（应叫 `list_products`）、`get_sku`（要补时叫 `get_product`） |

★ **沿革**（防数字漂移）：原文 28 → 第 204 轮接线 19 个后 **55** → 第 205 轮批 A 收敛
「同端点多名」后 **57** → 第 205 轮批 B 接入候选生命周期三条（`get_candidate` /
`review_candidate` / `approve_candidate`）后 **60**。
`tools_catalog.py` 头部注释里那句「**57 个里只有 2 个是 `approval`**」是批 A 时的旧口径，
**现状是 60 条里 4 个**（见第五章「已更正的陈旧注释」）。

### 1.2 按 Agent 分组计数

| Agent | 工具数 | 为主归属 | 备注 |
| --- | --- | --- | --- |
| ListingGenerator | **8** | 8 | 全只读 |
| ProductResearcher | **10** | 10 | 含 3 条 `approval` + 2 条共用 |
| review_analyst | **6** | 6 | 全只读 |
| secretary | **11** | 11 | 8 条是平台动作（不走 HTTP）+ 2 条共用 |
| competitor_intel | **8** | 8 | 全只读 |
| ad_analysis | **6** | 6 | 全只读 |
| AIGC 媒体生成器 | **9** | 9 | 全只读 |
| 智能客服 | **4** | 4 | 含 1 条 `approval` |
| **合计** | **62**（含 2 条共用各重复计 1 次） | | 去重后 **60** |

★ 为什么「合计 62」而「条目 60」：`grouped_catalog()` 会把共用工具**同时列在每一家**
的分组里（`list_candidates` 在选品分析师和秘书的分组里各出现一次），
所以「按家相加」比「去重条目」多 2。**报数时必须说清是哪个口径**。

---

## 二、按 Agent 逐条介绍

> 约定：
> · **工具**列 = 模型实际看到的名字；**中文**列 = 界面上给租户看的名字（`title`）；
> · **做啥**列 = 目录表里的 `description`（写给**人**看的，不是模型腔）；
> · **前端**列 = 该工具背后的后端端点在**前端 172 个实测调用路径**里有没有出现
>   （✅ 有 / ✗ 无）。判据与证据见第五章。

### 2.1 ListingGenerator（Listing 优化师）· 8 条 · 全部只读

| 工具 | 中文 | 做啥 | 后端端点 | 前端 |
| --- | --- | --- | --- | --- |
| `optimize_listing_title` | 标题优化 | 优化 Listing 标题，返回 SEO 改进版、字符数与 SEO 评分 | `POST /api/v1/listing/optimize/title` | ✅ |
| `generate_bullet_points` | 五点描述 | 为产品生成五点描述（卖点） | `POST /api/v1/listing/generate/bullets` | ✅ |
| `generate_product_description` | 详情描述 | 为产品生成详情描述，可含 HTML 富文本 | `POST /api/v1/listing/generate/description` | ✅ |
| `generate_search_terms` | 后台搜索词 | 基于标题生成后台搜索词（Search Terms） | `POST /api/v1/listing/generate/keywords` | ✅ |
| `generate_complete_listing` | 整套 Listing | 从零生成一整套：标题 + 五点 + 描述 + 关键词 + SEO 评分 | `POST /api/v1/listing/generate` | ✅ |
| `optimize_listing` | 整体优化建议 | 分析现有 Listing 并给出逐项优化建议 | `POST /api/v1/listing/optimize` | ✅ |
| `analyze_listing_seo` | SEO 诊断 | 对现有 Listing 做 SEO 诊断评分 | `POST /api/v1/listing/analyze/seo` | ✅ |
| `generate_ab_test_variants` | A/B 测试变体 | 生成多个可用于 A/B 测试的标题变体 | `POST /api/v1/listing/ab-test` | ✅ |

**覆盖率 8/8（100%）**。工具↔端点**逐条 1:1**，依据是机械匹配（两者的实现体都调用
同名 service 方法，见 `probes/out_r206f2_map.txt`）。

★ 关于「Listing 生成的成果没有回写通道」：界面上**有**入口 ——
`PATCH /api/v1/skus/{sku_id}/listing`（前端 `api/products.ts` 已调用）。
缺的是**给 Agent 的工具**（第 205 轮裁决：Listing 模块全模块 0 处店铺归属引用 ⇒
硬前置缺失）。这是「界面能做、对话不能做」，不是「谁都做不了」。

### 2.2 ProductResearcher（选品分析师）· 10 条 · 3 条需审批

| 工具 | 中文 | 做啥 | 后端端点 | 前端 | 档 |
| --- | --- | --- | --- | --- | --- |
| `analyze_blue_ocean` | 蓝海品类挖掘 | 按「低竞争 + 有需求 + 有利润」筛候选商品，返回蓝海评分排序列表 | `POST /api/v1/product-research/blue-ocean` | ✅ | 只读 |
| `analyze_profit` | 利润测算 | 按售价 / 成本 / FBA 费用 / 广告费算净利润、ROI、盈亏平衡点 | `POST /api/v1/product-research/profit` | ✅ | 只读 |
| `analyze_pain_points` | 评论痛点分析 | 分析某 ASIN 的用户评论，提炼痛点与改进方向 | `POST /api/v1/product-research/pain-points` | ✅ | 只读 |
| `compare_competitor_listings` | 竞品 Listing 对比 | 对比多个竞品 ASIN 的 Listing 质量、价格与优劣势 | `POST /api/v1/product-research/competitors` | ✅ | 只读 |
| `list_candidates` ★共用 | 查看选品库 | 列出当前店铺候选选品库（草稿池）里的候选，可按评审状态筛 | `GET /api/v1/candidates` | ✅ | 只读 |
| `get_candidate` | 查看候选详情 | 看某个候选的完整详情（ASIN / 售价 / 评分 / 评审状态 / 备注） | `GET /api/v1/candidates/{id}` | ✅ | 只读 |
| `save_candidate` | 加入选品库 | 把商品加入候选选品库（草稿池，待评审） | `POST /api/v1/candidates` | ✅ | **审批** |
| `review_candidate` | 评审候选（淘汰/转评审） | 打评审结论：淘汰 / 转评审中 / 退回待评审 | `PATCH /api/v1/candidates/{id}/review` | ✅ | **审批** |
| `approve_candidate` | 评审通过·推进产品库 | 把候选推进自有产品库（建待完善 Listing 的 SPU 草稿） | `POST /api/v1/candidates/{id}/approve` | ✅ | **审批** |
| `list_products` ★共用 | 查看产品库 | 列出当前店铺产品（SKU 粒度，含所属 SPU 标题） | `GET /api/v1/skus` | ✅ | 只读 |

**覆盖率 10/10（100%）**。这一家是**本轮最完整的一家**：
「看候选 → 看详情 → 评审 → 入产品库 → 看产品库」这条**选品闭环**在对话侧与界面侧都通。
（第 205 轮批 B 之前，闭环在 Agent 侧是断的 —— `get/review/approve` 三条只以**内联代码**
存在于 router 里，Agent 够不着。）

### 2.3 review_analyst（复盘分析师）· 6 条 · 全部只读

| 工具 | 中文 | 做啥 | 后端端点 | 前端 |
| --- | --- | --- | --- | --- |
| `weekly_report` | 经营周报 | 汇总销售、广告、库存、退款数据，生成结构化周报 | `POST /api/v1/review/weekly-report` | ✅ |
| `monthly_review` | 月度复盘 | GMV / ACoS / 转化率 / 退货率趋势对比，附 SKU 贡献排名 | `POST /api/v1/review/monthly-review` | ✅ |
| `ad_review` | 广告归因分析 | ROAS / ACoS / CPC / CTR 多维回顾，附 campaign 评级 | `POST /api/v1/review/ad-review` | ✅ |
| `product_performance` | 商品表现分析 | SKU 级销量 / 利润 / 评分 / BSR / 周转排名，识别爆款与滞销 | `POST /api/v1/review/product-performance` | ✅ |
| `inventory_health` | 库存健康分析 | 滞销预警 / 断货风险 / 周转天数 / 补货建议 | `POST /api/v1/review/inventory-health` | ✅ |
| `profit_audit` | 利润审计 | 销售额 − 佣金 − 广告 − 退货全链路核算净利润与净利率 | `POST /api/v1/review/profit-audit` | ✅ |

**覆盖率 6/6（100%）**，工具↔端点逐条 1:1。

### 2.4 secretary（店秘书）· 11 条 · 全部只读

秘书的工具分三类，**只有第三类走后端**：

**（a）平台动作类 8 条 —— 不走 HTTP，是前端动作指令**

| 工具 | 中文 | 做啥 | 前端 |
| --- | --- | --- | --- |
| `switch_agent` | 切换 Agent | 切换到某个业务 Agent 的对话页 | ✅ 界面即入口 |
| `open_view` | 打开资料库 | 打开资料库 / 看板视图（产品库、选品库、竞品库） | ✅ |
| `open_account_menu` | 打开账户菜单 | 账户菜单项的统一跳转网关 | ✅ |
| `set_theme` | 切换界面主题 | 浅色 / 深色，直接生效 | ✅ |
| `switch_shop` | 切换店铺 | 切换当前工作的店铺（数据源） | ✅ |
| `select_product` | 选中工作商品 | 选中产品库里的第 N 个（默认第一个）作「工作商品」 | ✅ |
| `handoff_to_agent` | 转交专家 Agent | 把对话交接给某个专业 Agent 接管 | ✅ |
| `ask_clarification` | 追问补齐信息 | 向老板提问以补齐继续执行所必需的信息，本身不执行动作 | — 无需界面 |

**（b）数据类 1 条**

| 工具 | 中文 | 做啥 | 后端端点 | 前端 |
| --- | --- | --- | --- | --- |
| `get_my_subscription` | 查询我的订阅 | 查套餐名、状态、价格、当前周期、特性列表 | `GET /api/v1/billing/subscription` | ✅ |

**（c）跨 Agent 共用 2 条**（与选品分析师共享**同一份实现**）

| 工具 | 中文 | 做啥 | 后端端点 | 前端 |
| --- | --- | --- | --- | --- |
| `list_candidates` ★共用 | 查看选品库 | 列当前店铺候选（可按评审状态筛） | `GET /api/v1/candidates` | ✅ |
| `list_products` ★共用 | 查看产品库 | 列当前店铺产品（SKU 粒度 + SPU 标题） | `GET /api/v1/skus` | ✅ |

★ 这 2 条是**第 205 轮的收敛成果**：同一能力原先被提议成两个名字，
且测试只会覆盖其中一条 ⇒ 收敛为**一个名字 + 一份 SHARED 层实现
（`modules/library/`）+ 两家注入**（秘书走构造期 `shop_id=` 绑定，
选品分析师走运行期 `resolve=` 取值）。

### 2.5 competitor_intel（竞品分析师）· 8 条 · 全部只读 · ★ 前端覆盖最低

| 工具 | 中文 | 做啥 | 后端端点 | 前端 |
| --- | --- | --- | --- | --- |
| `compare_competitors` | 多维度竞品对比 | 从价格、评分、评论、BSR、性价比等维度全面对比多个竞品 | `POST /api/v1/competitor/compare` | ✅ |
| `monitor_competitor` | 竞品 Listing 监控 | 追踪竞品的价格、排名、评论数、库存状态变化 | `GET /api/v1/competitor/monitor/dashboard` | ✗ |
| `track_batch_asins` | 批量追踪 ASIN | 一次对比多个竞品的关键指标 | `POST /api/v1/competitor/track/batch` | ✗ |
| `analyze_market_share` | 市场份额分析 | 基于 BSR 估算各品牌份额与类目集中度（CR4 / HHI） | `POST /api/v1/competitor/market-share` | ✗ |
| `analyze_pricing_strategy` | 定价策略分析 | 分析竞品定价模式、促销节奏与价格弹性，给调价建议 | `POST /api/v1/competitor/pricing/analyze` | ✗ |
| `analyze_competitor_reviews` | 竞品评论分析 | 挖竞品评论里的优劣势、痛点与差异化机会 | `POST /api/v1/competitor/reviews/analyze` | ✗ |
| `detect_intruders` | 入侵者检测 | 发现近期进入市场的新卖家 / 新产品并评估威胁等级 | `POST /api/v1/competitor/intruders/detect` | ✗ |
| `analyze_buy_box` | Buy Box 分析 | 分析购物车竞争格局与价格竞争力，给赢取建议 | `POST /api/v1/competitor/buy-box/analyze` | ✗ |

**覆盖率 1/8（12.5%）** —— 本轮最值得关注的一组：
后端 14 条竞品端点里前端只调了 2 条（`/competitor/analyze`、`/competitor/compare`），
而 **8 条 Agent 工具对应的端点在界面上都没有按钮**。
即：**这些能力目前只能通过对话触发**（打开对话 → 让竞品分析师做）。
这不是「工具没写好」，是「界面入口没做」—— 属于产品决策，见第六章。

### 2.6 ad_analysis（广告分析师）· 6 条 · 全部只读

| 工具 | 中文 | 做啥 | 后端端点 | 前端 |
| --- | --- | --- | --- | --- |
| `diagnose_ad_account` | 广告账户体检 | 多维评估广告表现，给评级与问题清单（含同类基准对比） | `POST /api/v1/ad-analysis/diagnose` | ✅ |
| `analyze_search_terms` | 搜索词分析 | 识别高效词、低效词与浪费词，并挖新的机会词 | `POST /api/v1/ad-analysis/search-terms` | ✅ |
| `optimize_bids` | 出价优化建议 | 按策略给出关键词 / 广告组的智能出价建议，可指定目标 ACoS | `POST /api/v1/ad-analysis/bid-optimize` | ✅ |
| `analyze_ad_competitors` | 竞品广告分析 | 分析对手的广告策略、展示份额与关键词重叠度 | `POST /api/v1/ad-analysis/competitors` | ✅ |
| `optimize_budget` | 预算分配优化 | 在多个 Campaign 之间智能分配预算，提升整体 ROI | `POST /api/v1/ad-analysis/budget` | ✅ |
| `detect_ad_anomalies` | 广告异常检测 | 自动发现花费突增、转化骤降等异常波动 | `POST /api/v1/ad-analysis/anomalies` | ✅ |

**覆盖率 6/6（100%）**，逐条 1:1。

### 2.7 AIGC 媒体生成器 · 9 条 · 全部只读

| 工具 | 中文 | 做啥 | 前端 |
| --- | --- | --- | --- |
| `generate_assets` | 生成图片素材 | **真正出图**：白底图 / 场景图 / 主图 / 信息图 / 广告图，返回图片 URL | ✅ |
| `generate_product_image` | 出图提示词包 | 产出出图方案（提示词 / SEO 关键词 / 文案建议 / 风格指南），**不含图片文件** | 见注 |
| `analyze_main_image` | 主图质量诊断 | 给主图打分，并给出 CTR 预测、合规问题与改进建议 | ✅ |
| `generate_a_plus_content` | A+ 内容生成 | 生成 A+（EBC 增强品牌内容）各模块文案 | ✅ |
| `generate_brand_story` | 品牌故事生成 | 生成品牌定位、使命、卖点、标语与叙事角度 | ✅ |
| `translate_content` | 多语言内容翻译 | 把文案翻译到目标语言，并保留 SEO 关键词 | ✅ |
| `generate_infographic` | 信息图规格 | 生成营销信息图的分区、文案、配色与 CTA 规格 | ✅ |
| `check_image_compliance` | 图片合规检查 | 检查图片是否合规，返回状态、评分与整改建议 | ✅ |
| `generate_video_script` | 短视频脚本 | 生成短视频脚本：分镜、旁白、字幕、钩子与 CTA | ✅ |

**该模块前端覆盖良好**：`/aigc/*` 18 条端点里前端调了 15 条。

> **注**：AIGC 的 router 装饰器全部是**换行写法**（`@router.post(` 换行后再给路径），
> 超出了本探针的端点覆盖（见第五章「覆盖缺口」）⇒ **这 9 条的「工具↔端点」逐条映射
> 未做机械确定**，只做模块级归属。`generate_product_image` 与 `generate_assets` 的
> 分工在工具描述里已显式写明（一个只出方案、一个真出图）。

### 2.8 智能客服 · 4 条 · 1 条需审批

| 工具 | 中文 | 做啥 | 后端端点 | 前端 | 档 |
| --- | --- | --- | --- | --- | --- |
| `search_faq` | 检索客服知识库 | 搜索客服知识库（FAQ），返回匹配的问题与标准答案 | `POST /api/v1/customer-service/faq/search` | ✅ | 只读 |
| `create_ticket` | 创建客服工单 | 创建工单，返回工单号与预计响应时间 | `POST /api/v1/customer-service/ticket/create` | ✅ | **审批** |
| `analyze_sentiment` | 情感分析 | 判断文本是正面 / 负面 / 中性，返回标签与置信度 | `POST /api/v1/customer-service/analyze/sentiment` | ✅ | 只读 |
| `get_conversation_summary` | 会话摘要 | 获取某段客服对话的摘要 | `GET /api/v1/customer-service/conversation/{id}` | ✅ | 只读 |

**覆盖率 4/4（100%）**。

★ 客服的 `POST /api/v1/customer-service/order/track`（订单物流查询）**界面已用**
（前端 `api/customerService.ts` 已调用），但**没有做成 Agent 工具** ——
第 205 轮裁决「撤回」：该端点的 service 内部会 `get_cs_agent()` 再 invoke，
注册成工具会变成「Agent 调工具、工具再调 Agent」的递归。

---

## 三、前端调用面（实测）

### 3.1 三种调用风格 —— 这是本轮踩到的最大坑

| 风格 | 形态 | 用它的 api 文件 |
| --- | --- | --- |
| (1) 实例方法 | `http.get('/x')` / `request.post('/x')` | `listingGenerator.ts` 等 |
| (2) 解构具名 | `get('/x')` / `post('/x')` / `del('/x')` | assets / billing / candidates / knowledge / memory / monitors / platformRules / products / skills / stores（**10 个**） |
| (3) 泛型具名 | `post<ProfitResult>('/x')` | `stores.ts::calculateProfit` 等 |

按 `request.ts` 的导出：它一共导出 **5 个具名函数** `get / post / put / patch / del`。
**只按 (1) 扫，得到 71 次 / 70 路径；三种全覆盖，得到 224 次 / 172 路径 —— 差 68%。**

★ 这条对本仓的既有判据有直接影响：
「后端有端点 ≠ 前端在用」「接线了但没渲染」这类核查，**如果扫描器只认一种调用风格，
结论会系统性偏向「前端没在用」**。

### 3.2 总量

| 指标 | 值 |
| --- | --- |
| 后端端点数（运行时 FastAPI 路由表） | **246** |
| 前端调用点（次数） | **224** |
| 前端调用路径（去重 + 归一化占位符后） | **172** |
| 前端路径在后端路由表里找不到同名 | **4**（全是模板拼接假象，非真断链） |

4 条「找不到」的明细（都是 `${}` 里拼 query 导致的归一化残留，**不是缺陷**）：
`/billing/invoices{}`、`/billing/usage{}`、`/skus{}`、`/stores/fee-templates{}`。

### 3.3 后端端点按模块分布（246 条）

| 模块 | 端点数 | 模块 | 端点数 | 模块 | 端点数 |
| --- | --- | --- | --- | --- | --- |
| aigc | 18 | accounts | 9 | asset-groups | 5 |
| auth | 16 | candidates | 9 | product-groups | 5 |
| stores | 14 | monitors | 9 | spus | 5 |
| competitor | 14 | skills | 9 | candidate-groups | 4 |
| knowledge-base | 12 | voice-clone | 8 | monitor-groups | 4 |
| ad-analysis | 11 | product-research | 8 | platform-rule-docs | 3 |
| billing | 11 | review | 7 | conversations | 3 |
| customer-service | 11 | assets | 6 | orchestrator | 2 |
| listing | 11 | platform-rules | 6 | docs / health / metrics / agents / tools | 各 1 |
| | | skus | 6 | openapi.json / redoc | 各 1 |
| | | users | 6 | | |
| | | memory | 6 | | |

---

## 四、本轮三个新发现

### 4.1 竞品情报的 12 条端点「界面无入口」

`/api/v1/competitor/*` 共 14 条端点，前端只调用 2 条（`/analyze`、`/compare`）；
8 条 Agent 工具里 7 条对应的端点在界面上没有按钮。
**含义**：这些能力目前**只能通过对话触发**。是不是缺陷取决于产品定位 ——
若定位「竞品分析走对话」，那么现状是对的；若界面应有独立入口，则缺 7 个入口。

### 4.2 ★ 一个**未收敛**的候选：`compare_competitor_listings` vs `compare_competitors`

机械匹配先给出「两个工具 → 同一端点」的信号，**核实后判定为假阳性**，
但它暴露了一个**真实存在的形态**：

| | 选品分析师 | 竞品分析师 |
| --- | --- | --- |
| 工具名 | `compare_competitor_listings` | `compare_competitors` |
| 实现函数名 | `_compare_competitors_tool` | `_compare_competitors_tool`（**同名**） |
| 请求模型 | `CompetitorCompareRequest(asins, include_reviews)` | `CompetitorCompareRequest(asins, dimensions)`（**同名**） |
| service | `product_research.service.compare_competitors` | `competitor_intel.service.compare_competitors`（**同名**） |
| 端点 | `POST /api/v1/product-research/competitors` | `POST /api/v1/competitor/compare` |

**结论：工具名已区分（✅），描述里也显式写了「★ 与竞品情报模块的 compare_competitors
区分」（✅），且两者实现/端点确实不同 ⇒ 不是缺陷。**
但**五个层级的名字全撞**（函数名、请求模型名、service 方法名），
**任何靠「名字」做的盘点都会在这里给出错结论** —— 本轮就踩到了。

★ 教训：**「同名」不等于「同能力」，「同名」也不等于「同端点」**。
判「同端点多名」必须落到「端点是哪一条」，不能用函数名相似度。

### 4.3 陈旧注释（已在本轮修正）

`modules/skills/tools_catalog.py` 头部那句
「**57 个里只有 2 个是 `approval`：`save_candidate` 与 `create_ticket`**」
是第 205 轮**批 A** 时的口径；批 B 又接入 `review_candidate` / `approve_candidate`
两条写工具，现状是 **60 条里 4 条 `approval`**。已改成现口径并注明沿革。

---

## 五、核验口径与证据

### 5.1 工具真源（不手抄）

```
探针 .workbuddy/probes/r206a_catalog_dump.py
  → out_r206a_catalog.txt      （60 条工具的 agent/name/title/effect/description）
  → routes_r206.json           （运行时 FastAPI 路由表，246 条）
  → fe_calls_r206.json         （前端调用点 224 条，带风格标记）
  → fe_paths_r206.txt          （前端归一化路径 172 个）
```

### 5.2 前端调用点扫描口径

扫 `frontend/src/**`（排除 node_modules / dist），三种形态全覆盖（见 3.1），
路径归一化：`${...}`、`{...}` `:param` 一律替换成占位符 `{}`；
前端相对路径统一补 `/api/v1` 前缀后与后端路由表比对。

### 5.3 工具↔端点机械匹配（及其覆盖缺口）

```
探针 .workbuddy/probes/r206f2_map.py
  → out_r206f2_map.txt
判据：工具实现体里调用的函数/方法名集合 ∩ 端点 handler 体里调用的同名集合 ≠ ∅
     （并过滤「在 >3 个端点里出现的通用词」如 execute / select / isoformat）
自检：AST 推导出的端点路径 189 条，与运行时路由表吻合 189 条（100%）
```

**覆盖缺口（必须声明）**：AST 推导只覆盖 **189/246 = 76.8%** 端点，
缺的 57 条是本探针**看不见**的（例如 `aigc_media/router.py` 的装饰器全部写成
`@router.post(` 换行再给路径，正则要求同行 ⇒ 整模块 18 条端点未被收集）。
⇒ 本文中所有「工具↔端点」映射，**只对匹配成功的 42 条成立**；
未匹配的不导出「无端点」，只标「模块级归属」。

### 5.4 本文里数字的可复算方式

| 数字 | 复算命令 |
| --- | --- |
| 60 条工具 | `python -c "from modules.skills.tools_catalog import TOOL_CATALOG as T; print(len(T))"`（须在 `backend/` 下） |
| 246 条端点 | 见 `probes/routes_r206.json`（运行时导出） |
| 224 次 / 172 路径 | 见 `probes/fe_calls_r206.json` / `fe_paths_r206.txt` |
| 门禁是否钉住 60 | `tests/test_tool_catalog.py:247`、`tests/test_skill_gate.py:1188` |

---

## 六、下一步建议（按优先级）

| # | 事项 | 为什么 | 代价 |
| --- | --- | --- | --- |
| P1 | **竞品 7 条端点是否要界面入口** | 这是**产品决策**，不是技术债。现状=只能对话触发 | 决策后 7 个入口 |
| P1 | **补一条门禁**：前端 api 层调用点必须覆盖三种风格（或直接禁掉其中两种） | 本轮实测漏报 68%，同类核查全都会踩 | 小 |
| P2 | 修本探针的端点覆盖缺口（装饰器换行形态） | 只为下一轮盘点用，不进生产 | 小 |
| P2 | 把「工具↔端点」映射改成**运行时取**（import 工具、调 `has_side_effects`、读 `metadata`）而不是 AST | 与 `TOOL_CATALOG` 的既有做法一致（本仓已有范式） | 中 |
| P3 | 第 205 轮遗留三件（`calculate_store_profit` 补归属 / Listing 归属通道 / `update_candidate` 34 字段形态） | 等老板拍板 | 见 r205 文档 |
