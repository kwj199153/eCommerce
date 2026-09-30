# 第 283 轮 · 交易履约数据源落地 & 「收到差评」全流程回跑

> 日期：2026-09-27
> 授权原文：买家差评数据源、订单+物流数据源建表 → 插 mock → 客服挂工具与差评处理技能 →
> 订单落库同步 + 归因打标 + 补偿规则 + SKU 健康分 → **「数据源准备好后，再看看这个流程还缺什么」**

---

## 一、本轮落地清单

| # | 交付 | 落点 | 状态 |
|---|---|---|---|
| 1 | 交易履约域 8 张平台无关表 | `modules/trade/db_model.py` + 迁移 `g1d4e7f2a8b5` | ✅ |
| 2 | 适配层订单域拉取钩子 | `amazon_sp/data_sources/base.py` 加 `fetch_orders` / `fetch_customer_reviews` | ✅ |
| 3 | Mock 数据源实现（自认假数据） | `mock_source.py`，`supported=True` + `source=mock_seed` | ✅ |
| 4 | **剧本唯一真源** | `modules/trade/demo_script.py`（seed 与 Mock 共用，消灭两份实现） | ✅ |
| 5 | **落库唯一写入路径** | `modules/trade/sync.py`（502 行，幂等键 + 派生态 + 自动归因） | ✅ |
| 6 | seed 收敛为「只造载荷」 | `seed.py` 改走 `sync.upsert_*` | ✅ |
| 7 | 定时同步入口 | `modules/trade/tasks.py` + beat（`trade-sync-all-shops`，每 6 小时 23 分） | ✅ |
| 8 | bootstrap 挂 seed | `core/bootstrap.py` 第 ⑨ 项 | ✅ |
| 9 | 分层 / 门面 / 作用域三处门禁债修复 | `test_module_layering.py`、`trade/__init__.py` 门面、`core.tenant.scoping` | ✅ |
| 10 | 测试 + 反向注入 | `test_trade_sync.py`（6）、`test_trade_schedule.py`（5）；反向注入同步侧 5/5 转红、名录侧 1/1 转红 | ✅ |

**全量回归**：2025 用例，红数 9 → **3**（逐条定性见第四节），本轮改动**零回归**。

---

## 二、全流程回跑（老板演示剧本「收到一条差评」）

数据源：`store_c3529ab1`，主剧本订单 `AMZN123456789`。

### 步骤 1 · 定位订单与商品 —— ✅ 通

```
订单 ord-amazon-AMZN123456789        shop_id=store_c3529ab1
下单 2026-09-12 → 承诺 09-18 → 发货 09-13 → 送达 09-25
transit_days = 12        delay_days = 7        ← 与剧本「12 天才收到」逐字吻合
物流 shp-...  UPS / 1Z999AA10123456784  终态 delivered
明细 sku=SKU-KC-002  asin=B0CXXXX009  ¥29.99  智能保温杯 温度显示 304不锈钢 大容量500ml
source = mock_seed   ← 自己承认是演示数据
```

### 步骤 2 · 归因打标 + 补偿方案 —— ✅ 通（且逐字对上剧本）

```
差评 crev-amazon-R1DEMO0001  rating=1  status=triaged
归因 causes=['packaging_failure','logistics_delay']  conf=0.9  method=rule
证据 4 条，可引用订单号 AMZN123456789 与运单 1Z999AA10123456784
命中规则 packaging-damage-standard（prio=10, budget_cap=50）
处置 = channels['reply','coupon','reship'] + {'type':'coupon','amount':8.0,'USD','reship':True}
      ↑ 就是剧本要的「补偿 $8 优惠券 + 免费重发」
```

### 步骤 3 · 根因预警的量化依据 —— ❌ 缺（重点）

```
count_repeat_issues(SKU-KC-002, packaging_failure) -> historical_count=3  is_repeat=True
count_repeat_issues(SKU-KC-002, logistics_delay)   -> historical_count=2  is_repeat=False
```

返回值只有**历史总次数 + 是否重复（≥3）**，**没有「近 7 天 vs 上一 7 天」的环比窗口** ⇒
演示里那句「**同类问题近 7 天上升 40%**」目前**数不出来，只能是文案**。

### 步骤 4 · SKU 健康分 —— ⚠️ 通一半（数字方向不对）

```
SKU-KC-002  end=2026-08-28  分=33.0  prev=0.0  delta= 0.0  top=packaging_failure
SKU-KC-002  end=2026-09-27  分=47.0  prev=33.0  delta=+14.0  top=logistics_delay
```

剧本要「**健康分 -0.7**」，实测是 **+14.0**。原因：样本只有 4 条评价，两期窗口不同且重叠，
负评率从 1.0 掉到 0.5 ⇒ 分数反而涨了。**不是算错，是没有稳定的连续口径**。

---

## 三、剩余缺口清单（按优先级）

| P | 缺口 | 证据 | 修法 | 量 |
|---|---|---|---|---|
| **P0** | **`review_dispositions` 恒为 0 行** —— 补偿只停在「建议」，无发放 / 无归档 | 实测该表全库 0 行；`plan_compensation` 只出方案不落库 | 新增落库写口（`trade/sync.py` 或新 `disposition()`），并与 HITL 审批挂接 | 1 天 |
| **P0** | **trade 域无 REST 端点、前端零消费** —— 数据在库里，界面上看不到 | `modules/trade/` 无 `router.py`；`main.py` 无 trade；前端 `src/` 零 `customer_reviews / sku_health / order_tracking` 调用 | 建 `trade/router.py` + 前端接入 | 2 天 |
| **P0** | **健康分没有生产入口** —— 只在 seed 时算过一次 | `compute_sku_health` 调用点只有 `seed.py` 两处；无 Celery、无端点、无工具 | 挂进 `sync_trade` 收尾 + beat | 半天 |
| **P1** | **「近 7 天上升 40%」数不出来**（剧本步骤 3 的量化依据） | `count_repeat_issues` 返回结构里无环比窗口 | 给该函数加 `window_days`，返回 `current / previous / pct_change` | 半天 |
| **P1** | **`list_faqs(category="packaging")` 不存在** | `service.search_faq` 只有 `query` + `limit`，无 category；`knowledge.py` 的 category 取值只有 物流配送 / 支付 / 退换货，**没有「包装」** | 补 category 过滤 + 补包装类 FAQ 语料 | 半天 |
| **P1** | **SKU 口径分叉**：剧本写 `KITCH-002-BLUE`，库里是 `SKU-KC-002` | 步骤 1 实测 | 二选一：改剧本 SKU，或落一条 SKU 别名映射 | 1 小时 |
| **P2** | 竞品「包装视频」证据无数据源 | `competitor_intel` 无 packaging / video 相关能力 | 待定（依赖竞品链路真源，见 #736） | — |

---

## 四、全量回归剩余 3 条红的定性（**均与本轮改动无因果**）

| 用例 | 根因 | 性质 |
|---|---|---|
| `test_listing_seo_contract` × 2 | 端点抛 `ValueError` 未收敛，被 starlette 包成 `ExceptionGroup` ⇒ TestClient 直接炸 | 既有（新版 starlette 行为差） |
| `test_memory_distill::test_beat_task_name_is_registered` | 前置哨兵被上游污染：污染源实测为 `test_account_store_hierarchy.py::test_legacy_shops_entity_is_gone`（它会 finalize celery ⇒ 触发全量 autodiscover）。**对照实验：把 `autodiscover` 里的 `"modules.trade"` 摘掉后照样红** ⇒ 与本轮无关 | 既有顺序依赖红 |

> 另有一条 `test_billing_alipay_webhook` 根因是本地虚环境漏装 `qrcode`
> （`requirements.txt` 里写的是 `qrcode>=7.4`，requirements 是对的），已补装，**现已转绿**。

---

## 五、回答「还是可以作业了」

**能作业，但要限定范围。** 目前真正能端到端跑出来的是**步骤 1 + 步骤 2**：

- 「给我看 AMZN123456789 这笔单」 → ✅ 订单 / 明细 / 物流三表联动，在途 12 天、迟到 7 天，全部有据可查
- 「这条差评怎么回事、该怎么赔」 → ✅ 归因 `packaging_failure`+`logistics_delay`（conf 0.9、4 条证据），
  命中规则给出 **$8 券 + 免费重发**，与剧本逐字一致

**步骤 3 和步骤 4 还不能当作结论交付**，因为它们的量化依据不存在：

- 「近 7 天上升 40%」→ 函数里没有环比窗口，说出口就是编的
- 「健康分 -0.7」→ 实测 +14.0，而且这个分**新差评来了不会重算**（无生产入口）

另外有一条全局性的：**补偿到现在为止没有任何一行归档**（`review_dispositions` 0 行），
也就是说「赔了多少、赔给谁、谁批的」目前**不可回溯** —— 真上线前这是必须补的。
