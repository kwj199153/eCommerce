# 客服域「能不能拿出真数据」审查（第 285 轮）

> 起因：老板批准订单追踪的修法（先查自有订单库，查不到再走平台适配层），
> 并追加一句要求 —— **「除了这个功能/工具，也要审查下其是否也缺数据导致无法生成结果」**。
>
> 本文档回答两件事：① 订单追踪修成了什么样、为什么比原计划改得多；
> ② 全入口审查结论。**最重要的结论在第三节：绝大多数入口不是「缺数据」，
> 而是「真数据在库里、代码却读内存里的假数据」** —— 和订单是同一种病。

---

## 一、订单追踪：修成了什么

### 1.1 取数顺序

```
_fetch_order_info(order_id, shop_id)
   │
   ├─ ① shop_id 有值 → 查自有订单库（trade.service.get_order_context）
   │                    orders / order_items / shipments / 关联差评
   │     命中 ⇒ 直接返回（**不再问平台**）
   │     未命中 ⇒ 记下「自有库中查无此单」，继续 ②
   │
   └─ ② 平台适配层（SP-API Orders）—— 只在①拿不到时兜底
         命中 ⇒ 返回，并标注 data_source="platform_api"
         未命中 ⇒ 返回 (None, 原因)，原因里**两段的线索都在**
```

### 1.2 实测（订单 `AMZN123456789`，店铺 `store_c3529ab1`）

修复前：`found=False`，原因「当前店铺未接入 SP-API 订单数据源（凭据仍为占位符）」。
修复后：

| 字段 | 值 |
|---|---|
| 状态 | 已签收（`delivered`） |
| 商品 | 智能保温杯 温度显示 304不锈钢 大容量500ml |
| 金额 / 数量 | $29.99 / 1 |
| 收货地 | California / US |
| **承运商** | **UPS** |
| **运单号** | **`1Z999AA10123456784`** |
| **物流状态 / 最新位置** | 已签收 / San Jose, CA |
| **最新轨迹** | Delivered, left at front door |
| **在途 / 迟到** | 12 天 / **晚 7 天** |
| `data_source` / `is_mock_data` | `mock_seed` / `true` |

★ 承运商与运单号是**自有库独有的**：SP-API 的 Orders 接口本来就不返回这两项
（那是 Shipping API 的活）。这条同时消掉了 `_map_order_info` 里那句
「运单号与承运商：Orders 接口不返回，可在卖家后台查看」的自嘲文案。

### 1.3 为什么比原计划改得多

原计划说「只改 `agent_cs.py` 一个方法 + 一个字段映射」。**实测发现那条链上根本没有店铺上下文**：

| 环节 | 有没有店铺信息 |
|---|---|
| `POST /customer-service/order/track` | ❌ 端点**不接** `X-Shop-ID`（无任何 `Depends`） |
| `service.track_order` | ❌ 传给 `invoke` 的 context **只有** `{"order_id": ...}` |
| `agent.invoke` → `_route_by_intent` | ❌ 范式 B **从不设置** `_current_shop_id` |
| `_fetch_order_info` | ❌ 于是只能走店铺无关的 SP-API |

自有订单库是**租户隔离**的（查询必须带 `shop_id`），拿不到店铺就无从下手。
所以连带改了三处：

1. `router.py` —— `/order/track` 加 `get_current_shop_id_optional`
2. `service.py` —— `track_order(request, store_id)` 并把 `store_id` 放进 invoke 的 context
3. `agent_cs.py` —— 取数分支 + 字段映射 + 展示

★ 一个刻意的选择：**不读 `_current_shop_id` 这个 ContextVar，一律显式传参**。
因为范式 B 从不设置它，读它只能拿到上一次范式 A 留下的值 ⇒ 跨调用串味，
会拿 A 店铺的身份去查订单。

### 1.4 一处与既有纪律的冲突（已裁决）

`modules/trade/tools.py` 头部写着：「表是唯一真源，DB 查不到就如实说查不到
（fail-closed），**不回头再问一次另一个源**」。

本轮加了回退，理由写在代码注释里：那条纪律管的是**同一个工具内部**不许出现
两种答案；而这里是**同步任务还没跑过**的情形 —— 平台上有、我们库里暂时没有，
此时回退是「补拉」不是「给第二个答案」。两条路径的产出都带 `data_source`，
上层看得到差别。

★ **不在查询路径落库**：`fetch_order_tracking` 是 READ_ONLY，在查询里写库会让
「读」产生副作用。把平台数据变成自有数据的正确落点是
`modules/trade.sync.sync_orders_from_source`（订单同步任务）。

### 1.5 门禁与验证

- `tests/test_shop_id_guard.py` 拦下了新增的 optional 使用点（名单式白名单，
  必须先回答「会不会落数据 / 写路径是否硬拒绝」）⇒ 已按规范补登记
- 新增 `tests/test_customer_service_order_own_source.py`（6 条，全部 monkeypatch，
  **不连共享库**）—— 钉住「先问谁」；既有 `order_failclosed` 那套钉的是「不能编」，
  二者互补：**把取数顺序改回「只问平台」，那套仍然全绿**，就是它看不见这条
- 反向注入 **3/3**：摘掉前置分支 / 改死演示数据标记 / 去掉运单号，
  各条判据分别转红，还原后复绿

---

## 二、全入口审查：逐个问「给它合法入参，它能不能拿出真数据」

### 2.1 trade 域 5 个 Agent 工具 —— 全部可用 ✅

| 工具 | 取数源 | 库里有数吗 | 实测 |
|---|---|---|---|
| `fetch_order_tracking` | `orders` / `shipments` | 4 / 4 行 | ✅ 完整 |
| `list_customer_reviews` | `customer_reviews` | 4 行 | ✅ |
| `get_customer_review_context` | 差评 + 归因 + 物流 | 4 行 | ✅ |
| `get_sku_health_score` | `sku_health_scores` | 2 行 | ✅ |
| `plan_compensation` | `compensation_rules` | 3 行 | ✅ 命中规则并给出方案 |

这五个是本仓写得最好的一批：**fail-closed、拿不到给具体原因、绝不编**。
差评处理主链路（定位 → 归因 → 补偿 → 健康分）在数据层是通的。

### 2.2 客服侧 7 个意图分支 —— 只有 1 个接了真数据 ❌

| 分支 | 实际取数源 | 库里有真数据吗 | 实测问答 |
|---|---|---|---|
| **订单追踪** | 自有库 → 平台 | orders 4 行 | ✅ **本轮已修** |
| FAQ 检索 / RAG | **内存 `MOCK_FAQ_DB` 12 条** | `knowledge_faqs` **24 条** | ⚠️ 用假数据，真的没接 |
| 物流咨询 | `MOCK_FAQ_DB` 分类=物流 | `shipments` 4 行 | ❌ 答「请登录账户自行查看」 |
| 退换货 | 写死 `faq-002` | `orders` 4 行 | ❌ 静态指南，不校验订单 |
| 投诉 / 质量 | 写死 `faq-005` + 安抚话术 | `customer_reviews` 4 行 | ❌ 不查真实差评 |
| 支付问题 | 写死 `faq-007` | — | ❌ 静态支付方式列表 |
| 升级 | 纯文案 | — | ❌ **承诺「主管 30 分钟内联系」但无实现** |
| 兜底 general | `_search_faq` → `MOCK_FAQ_DB` | — | ❌ 静态 |

实测四句典型问话（范式 B）：

```
Q: 我的货到哪了     → 「登录账户 → 我的订单 → 查看物流」（不查 shipments）
Q: 我要退货         → 「退换货指南」静态 5 步（不校验订单是否在退货窗口）
Q: 你们产品质量太差 → 「质量问题处理流程」静态文案（不查那条差评）
Q: 支付失败怎么办   → 「支持的支付方式」静态列表
```

★ 最扎眼的一点：**用户问「货到哪了」，系统让他自己去别处看** ——
而 `shipments` 表里那 4 行连运单号、轨迹、迟到天数都存好了。

### 2.3 那句 `search_knowledge_base` 是命名欺骗

```python
async def search_knowledge_base(self, query, limit=5):
    result = self._search_faq(query)          # ← 搜的是内存里的 MOCK_FAQ_DB
    return [m.model_dump() for m in result.matches[:limit]]
```

名字叫「知识库」，检索源是**进程内存里 12 条硬编码 FAQ**，
跟 `knowledge_faqs`（24 条，带 `usage_count` 真实热度、`keywords`、`category`）
**没有任何关系**。RAG 索引也是这 12 条（日志：`Built TF-IDF index: 12 docs`）。

实测 `search_knowledge_base("包装破损怎么赔")` → **命中 0 条**。
这正好印证上一轮报的 P1：`MOCK_FAQ_DB` 里没有「包装」这个分类，
而 `knowledge_faqs` 表有 `product` / `shipping` / `return` 等规范分类。

**决定性证据**：`modules/knowledge_base/db_model.py` 文件头白纸黑字写着
`knowledge_faqs` —— 「结构化话术条目（**智能客服 RAG 的一路检索源**）」。
⇒ 设计意图就是要接这张表，**只是从来没接**。

---

## 三、结论：绝大多数不是「缺数据」，是「接错源」

把「空」分成三类，代价和修法完全不同：

| 类型 | 表现 | 本轮实例 | 修法 |
|---|---|---|---|
| **A. 接错源**（最普遍） | 库里有真数据，代码读内存 mock | 订单追踪（已修）、客服 FAQ/RAG、物流咨询 | 改取数，≈40 行/处 |
| **B. 真缺数据** | 表建好了但 0 行 | `review_dispositions` 0、`cs_tickets` 0、`knowledge_docs` 0 | 补写入路径 + 出口 |
| **C. 没接** | 静态文案 / 空承诺 | 退换货、支付、升级分支 | 要么接，要么改成诚实文案 |

★ **A 类是本轮最值得做的**：数据已经在库里躺着，改一个取数口就能变现，
不需要造数据、不需要新表、不需要迁移。订单追踪就是样板。

---

## 四、建议的下一步（按性价比排序）

| 优先级 | 事项 | 类型 | 说明 |
|---|---|---|---|
| **P0** | 客服 FAQ 接到 `knowledge_faqs` 表 | A | 与订单**完全同型**，真数据 24 条在库里。`db_model.py` 已写明它本就是「智能客服 RAG 的一路检索源」。改完顺带消掉「包装破损查不到」 |
| **P0** | `review_dispositions` 的出口 | B | 上一轮已报的 P0-1：有状态/补偿/双语回复，却后端无端点、前端零消费、全库 0 行 |
| **P1** | 物流咨询 / 退换货接真实订单与物流 | A | 「货到哪了」应查 `shipments`；退货应先校验订单在不在窗口内 |
| **P1** | `knowledge_docs` 0 行 | B | RAG 的文档检索源是空的，知识库页面传了文档也走不到检索 |
| **P2** | 升级分支的「主管 30 分钟联系」 | C | 没有人工队列，这是**承诺型假话**；要么建机制，要么改文案 |

---

## 附：库里各表数据量（审查快照）

```
orders 4 / order_items 4 / shipments 4
customer_reviews 4 / review_attributions 4 / review_dispositions 0
compensation_rules 3 / sku_health_scores 2
knowledge_bases 4 / knowledge_faqs 24 / knowledge_docs 0
cs_tickets 0
```
