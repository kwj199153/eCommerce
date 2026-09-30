# 「订单追踪」三条入口实测诊断（第 284 轮 · 第三段）

> 一句话结论：**能力是真的、数据是真的、工具也真的挂上了 —— 但界面上三条入口里，
> 两条被同向的「关键词短路」截到了死路上。**
> 这是「同一能力多条通道」在本仓的**第三种形态**：不是「一条真一条假」（r284 批 1 的
> 创建工单），也不是「有 API 没前端」，而是**两条通道都真调后端、都无假数据，只是取数源不同**。

---

## 一、三条入口的实测对照

| # | 入口 | 触发方式 | 路由范式 | 取数落点 | 结果 |
|---|---|---|---|---|---|
| ① | **工具卡** | 点「订单追踪」→ 填订单号 → 提交 | **B**：`invoke()` → `_classify_intent("订单")` **关键词短路** → `_handle_order_tracking` | `_fetch_order_info` → `get_data_source(prefer="sp_api")` | ❌ **实测 `found=False`** |
| ② | **对话（明说订单）** | 说「查订单 …」「物流到哪了」 | **B**：前端 `replies/customerService.ts:121` **本地正则短路**（`/订单\|order\|物流\|tracking\|到哪里/` 命中即 `return 'handled'`）→ `trackOrder()` | 同 ① | ❌ 同 ①（同一条链） |
| ③ | **对话（不点破）** | 说「帮我看看这单怎么样」这类**不含上述词**的话 | **A**：`stream_chat()` → `_stream_via_tools` → LLM `bind_tools` 自主选工具 | trade `fetch_order_tracking` → **`orders` 表** | ✅ 取数链路可用（**间接证据**，见下注） |

> **注（口径诚实）**：① ② 是**探针实测**（直接调 `CustomerServiceService.track_order`）。
> ③ 是**间接证据**——实测的是「router 运行时确实挂了 trade 的 5 个工具」+「`stream_chat`
> 确实走 `_stream_via_tools`」，**没有**端到端跑一次真 LLM 对话。这条标注在此，不放大成
> 「已验证可用」。

### 实测原始数据

同一订单号 `AMZN123456789`、同一店铺 `store_c3529ab1`、同一台机：

```
【A 路】trade_service.get_order_context()   ← 能力侧（= ③ 的取数点）
  found        = True
  data_source  = mock_seed
  is_mock_data = True
  明细条数     = 1
  运单         = { carrier: 'UPS', tracking_no: '1Z999AA10123456784',
                   transit_days: 12, delay_days: 7, ship_status: 'delivered',
                   events: [ ..., { status: 'EXCEPTION',
                                    description: 'Package crushed in transit, outer box damaged' },
                             { status: 'DELIVERED' } ] }

【B 路】CustomerServiceService.track_order()  ← 界面侧（= ① ② 的取数点）
  found   = False
  order   = None
  message = 未能查询到订单 AMZN123456789：当前店铺未接入 SP-API 订单数据源
            （缺少 SP-API 凭据（或仍为占位符）: SPAPI_LWA_CLIENT_ID,
              SPAPI_LWA_CLIENT_SECRET, SPAPI_REFRESH_TOKEN,
              SPAPI_AWS_ACCESS_KEY, SPAPI_AWS_SECRET_KEY）
```

`orders` 表实际有 **4 行**（`AMZN123456001/002/003/789`），全部 `shop_id=store_c3529ab1`。
`.env` 里 SP-API 五项凭据**全是占位符**（`your-lwa-client-id` 之类）⇒ 范式 B **必然**失败。

---

## 二、根因：两层**同向**短路

```
用户说「查订单 AMZN123456789」
  └─ 前端 replies/customerService.ts:121  ← 第 1 层短路（前端本地正则）
       命中 isOrderTrack ⇒ 直接调 trackOrder()，**return 'handled'**（不再走 SSE）
       └─ POST /customer-service/order/track
            └─ service.track_order ⇒ get_cs_agent().invoke(...)
                 └─ agent_cs.py:529 _classify_intent(query)  ← 第 2 层短路（后端关键词表）
                      intent='order_tracking' ⇒ _handle_order_tracking
                        └─ _fetch_order_info ⇒ get_data_source(prefer="sp_api")
                             └─ 缺凭据 ⇒ RuntimeError ⇒ (None, 原因) ⇒ found=False  ❌
```

**两层短路都指向范式 B、都指向 SP-API**，而范式 A（LLM 自主选工具 → 查自己的库）
恰好被前端的第 1 层短路挡在外面。

⇒ 本仓那条老判据在这里再次成立：
**「意图识别/规划没做好」先查短路 —— 关键词命中即 `return`，工具从未被调用。**
本轮的变体是：**短路不只在后端 `_classify_intent`，前端还有一层本地正则，且两层同向。**

⚠️ 后果的形状很不直观：**用户越明确地说「我要查订单」，越查不到**；
反而是含糊地说「帮我看看这单」，才会落到能查到的那条路。

---

## 三、这不等于「订单追踪没实现」

| 被质疑的 | 事实 |
|---|---|
| 「伪功能」 | **不是**。两条通道都真调后端、都没有编造数据（历史那版 `_mock_order_info` 随机生成状态/运单号的实现**已被整体删除**） |
| 「没接数据源」 | **接了**，而且数据就在自己的库里（`orders` 表 4 行 + `order_items` + `shipments` 的事件轨迹） |
| 「工具没挂上」 | **挂上了**。运行时实测 `CustomerServiceAgent._router.tools` 共 **10 个**：`search_faq` / `create_ticket` / `analyze_sentiment` / `get_conversation_summary` / `fetch_order_tracking` / `list_customer_reviews` / `get_customer_review_context` / `get_sku_health_score` / `plan_compensation` / `load_skill` |
| 真正的问题 | **界面侧（① ②）的取数源接错了**：`prefer="sp_api"` 是分水岭 —— 凭据缺失时工厂**抛错、不静默回退 mock**，所以库里有多少数据都与这条链无关 |

### 附带发现：走自己的库，信息反而更全

`orders`/`shipments` 侧能给出 **`carrier` + `tracking_no` + `transit_days` + `delay_days`
+ 物流事件轨迹**（含那条 `EXCEPTION: Package crushed in transit` —— 正是差评
`R1DEMO0001` 的根因证据）。
而 SP-API 的 Orders 接口**本来就不返回运单号与承运商**，所以 `_map_order_info` 的注释里
明写「不产出 `tracking_number` / `carrier` 两个键」。

⇒ 修 `_fetch_order_info` 接入自己的库，不是「降级用 mock」，而是**换到信息更全的真源**
（且 `source` 字段会如实标注 `mock_seed` / `csv_import` / `platform_api`，可对账）。

---

## 四、处置选项（待拍板）

| 选项 | 改动面 | 修好哪几条入口 | 代价 |
|---|---|---|---|
| **A · 修 `_fetch_order_info`：先查自己的库，查不到再走 SP-API**（推荐） | `agent_cs.py`：`_fetch_order_info` 加一个前置分支 + 新增一个 `_map_trade_order` 字段映射（约 40 行）。前端 / 表 / 端点 / 门禁**都不动** | **① + ② 同时打通**（两条都汇到这一个取数点） | 语义要定：「库优先」意味着依赖同步任务的时效；库里的 `source` 字段可如实标注数据来源 |
| B · 只摘前端正则短路 | `replies/customerService.ts:121` 一行 | 只修 ②（改走范式 A，交给 LLM） | ① 工具卡仍是死的；且把确定性的表单查询变成 LLM 调用（慢、要钱、可能不稳） |
| C · 与创建工单同尺子，一并退役卡片 | 删卡 + `OrderTrackConfig.vue` + `executeOrderTrack` + `OrderTrackResult.vue` | ① 消失；② 仍死（若不同时做 A/B） | 丢掉一个**本该最好用**的入口（填表单 vs 打字）；且 ② 的短路仍在 |

**注意 ② 不依赖卡片存在** —— 只要 `replies/customerService.ts:121` 那条正则还在，
「查订单」这句话就永远走不到范式 A。所以**无论卡片删不删，B 或 A 都得做**。

---

## 五、复现方式（只读，不写库）

```bash
cd /d/ai/eCommerce/backend
# 必须在 backend/ 下跑（.env 相对 CWD 解析）；用受管解释器
"C:/Users/Administrator/.workbuddy/binaries/python/envs/default/Scripts/python.exe" <探针>
```

探针要点：
- A 路：`os.chdir(backend)` → `from modules.trade import service` →
  `await trade_service.get_order_context(session, "store_c3529ab1", "AMZN123456789")`
- B 路：`from modules.customer_service.service import get_cs_agent`（**注意不在 `agent_cs`**）
  → `from modules.customer_service.service import CustomerServiceService` →
  `await CustomerServiceService.track_order(OrderTrackRequest(order_id="AMZN123456789"))`
- 运行时盘点工具：`get_cs_agent()._get_router().tools` →
  取 `getattr(t, "name", ...)`，**别 grep 源码字面量**（模块级 import 副作用会回填）

---

## 六、同批的 `reply-draft` 退役（已执行）

`reply-draft` 连续两轮靠「`coming_soon` 是诚实占位」被豁免，本轮复核后退役：

| 查什么 | 结果 |
|---|---|
| 配置面板 / 执行器 / 结果卡 / api 调用 | **全零** |
| 后端 4 个客服工具里有它吗 | **没有** |
| 全仓真实定义处 | **只有 `toolDefinitions.ts` 一处** |
| 规格表 / backlog 依据 | **没有** |
| 职责是否已被覆盖 | **是** —— 两条客服技能正文都在干这个（`cs-negative-review-triage` 最后一步就是「回复」） |

⇒ 它与上批退役的三张卡**同一把尺子**（职责已被技能覆盖 + 无后端承载）。
性质上**不是伪功能**（从不假装能用），是**零价值登记** —— 占位也须有规格表依据。

连带处理：F7 门禁的 `coming_soon` 豁免分支**失去生产样例**（它是唯一的），
故反向注入脚本改为**自造样例**验证该分支（① active 幽灵⇒红 / ② coming_soon 幽灵⇒不红 /
③ 组合：先 coming_soon 不红、原地改 active 即红）。当前目录 **22 条全 active、零 coming_soon**。
