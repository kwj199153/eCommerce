# 第 326 轮：三处真源分叉修复 + 判据 M/P 落地 + 别名盲区

> 承接第 325 轮的「三处确证分叉仅上报未改」与老板拍板的「执行 1~4」。

## 一、三处生产改动（已落盘 + 幂等回读复核）

| # | 缺陷 | 文件 | 改动 | 证据 |
|---|---|---|---|---|
| 1 | 搜索 FAQ 漏传租户 ⇒ **活工具恒失败** | `modules/customer_service/tools.py` | `_service.search_faq(req)` → `_service.search_faq(req, _shop_id())` | 配套门禁 `tests/test_cs_faq_real_source.py` **12 passed** |
| 2 | 订阅工具未按身份过滤 ⇒ 可读**任意用户**订阅 | `modules/secretary/subscription_tools.py` | 新增 `current_user_id()`；空身份 **fail-closed**；查询体加 `.where(Subscription.user_id == user_id)` | 反向注入 I4 命中 |
| 3 | 选品工具绕内核 + `shop_id` 是**工具形参**（LLM 可自报租户） | `modules/secretary/product_tools.py` | 改走 `query_library(PRODUCT_SPEC, …)` / `count_library`；`_select` **去掉 `shop_id` 形参** | 反向注入 I1/I2 命中；schema 现只剩 `nth` |

回退备份：`.workbuddy/probes/r325/bak/*.pre326`。

## 二、新增两条门禁（均经反向注入证明有牙齿）

### 判据 M —— 工具层不得绕过内核
`tests/test_tool_catalog.py::test_tool_layer_reads_registered_libraries_only_through_the_kernel`

- 扫描面 = **产出 `StructuredTool` 的文件**（13 个），**不按文件名**认
  （按 `tools.py` 扫会漏掉本次修的 `secretary/product_tools.py`）。
- 实测**零命中** ⇒ 无需豁免表。
- 反向注入：换回 `pre326` ⇒ 精确报 `product_tools.py:36 'select(SkuRecord)' —— 绕过 PRODUCT_SPEC`。

### 判据 P —— 数据域 → 允许读它的函数集合（老板原话）
`tests/test_tool_catalog.py::test_library_data_domains_have_registered_reader_sets`

- 登记表**由探针现算生成**（8 个 `LibrarySpec` / **kernel 17 项** / **direct 47 项**），不手写。
- 四段断言：**A** 域完备、**B** kernel 栏集合相等、**C** direct 栏集合相等、
  **D** REST↔工具覆盖（用**源码实测**算，不用登记表）。
- 反向注入 3/3：

| 注入 | 动作 | 归因 token |
|---|---|---|
| I-P1 | 登记表 kernel 项改名 | `[PRODUCT_SPEC][kernel]` |
| I-P2 | 登记表 direct 删一项 | `[ASSET_SPEC][direct]` |
| I-P3 | 两个工具侧生产者 + 登记表**同步**摘掉 | `[lane D]`（实际满足域只剩 `['MARKET_SNAPSHOT_SPEC']`）⇒ 证明 D 独立于登记表 |

## 三、★ 判据 P 首版有一个 27% 的盲区（已修）

`modules/library/tools.py:93-97` 用的是**别名 import**：

```python
from core.library_query import (
    count_library as _svc_count_library,
    query_library  as _svc_query_library,
)
```

按函数名**字面**匹配 ⇒ **整体漏掉这个文件** ⇒ 漏掉 `_rows_to_products`，
而它正是 ProductResearcher 6 个 `list_*` 工具的**直接取数点**（kernel 16 → 17）。

**修法**：扫描器先遍历 `ImportFrom(module=…"library_query")` 建 `{本地名: 原名}`
别名表，再判真实函数名。

**教训**：发现盲区的线索不是「门禁红了」，而是**逻辑上说不通的空缺**——
「6 个读库的 `list_*` 工具居然一个都不在消费者名单里」。盯着绿/红永远看不出扫描面是残的。

## 四、全量 pytest 归因（2292 tests / 42 failed ⇒ **0 个由本轮引入**）

| 类 | 数 | 单跑 | 根因 |
|---|---|---|---|
| `UnicodeDecodeError`(byte 0xa4 @ pos 64) | 8 | **仍红** | `backend/.venv/Lib/site-packages/joblib/test/test_func_inspect_special_encoding.py` 是 joblib 自带的 **GBK 编码夹具**，门禁 `rglob("*.py")` 扫进了 `.venv` |
| `403 无权访问该店铺` | 25 | **绿** | 共享生产库**顺序依赖**（本仓已知，只认单跑绿） |
| `shop_voice` 外键违反 | 6 | **绿** | 同上 |
| 工具数 `64→65` / `15→16` | 3 | **仍红** | `query_market_insight`（09:11 已装配且已进 `TOOL_CATALOG`=65），但 `test_skill_gate.py:1203` 硬编码 64、`test_secretary_agent.py:402` 期望集合缺它 ⇒ **期望值未同步** |

**mtime 铁证**：本轮改的 4 个文件 `10:07~10:21`；`product_research/tools.py` = `09:11`、
`test_secretary_agent.py` / `test_skill_gate.py` = **昨天 21:15**。

## 五、第 323 轮「做成可访问页面」的真实入口

= **侧边栏账户菜单 → 抽屉**，**未新增 UI 入口**：

- `AccountMenu.vue:519-537` 派发 `open-settings-drawer` / `open-memory-drawer`
- `Workspace.vue:257,260` 挂 `<Settings>` / `<MemoryEvolution>`
- `appActions.ts:171-180` agent 网关 `account_menu` 分支同走抽屉
- 路由页 `/settings` `/memory` **零 UI 入口**（全仓无 `router.push({name:'Settings'})`）；
  仅 `MemoryEvolution.vue:558` 一条 401 回跳 `/memory`，`Login.vue:337-345` 消费 `redirect`
- 第 323 轮实际做的是**修 `ROUTE_MODE` 让 URL 直达不白屏**

## 六、各 Agent 数据能力矩阵（8 Agent / 65 工具）

**结论：修完三处分叉 ≠ 让每个 Agent 都有数据能力。** 那三处只**统一已有的查询实现**，
不新增任何工具绑定或表读取。

| Agent | 工具数 | 取数通道 | DB/看板能力 |
|---|---|---|---|
| **ProductResearcher** | 15 | 6 个 `list_*` 经 `modules/library/tools.py` → 内核读 6 个已登记域；`query_market_insight` → 内核读选品大盘；4 个候选写工具 → candidates service | **完整** |
| **智能客服** | 10 | FAQ / 评价 / 订单 / SKU 健康分读表（`search_faq` 本轮修通） | **完整** |
| **secretary** | 10 | `select_product` → 内核；`get_my_subscription` → DB（本轮修）；`list_shops` / `switch_shop` → stores | **完整** |
| **competitor_intel** | 3 | 读竞品表 | **完整** |
| **review_analyst** | 6 | `list_reviews` → 内核读 `REVIEW_SPEC`；其余 5 个 → `get_data_source()`（Mock/SP-API，**非 DB**） | **部分** |
| **ad_analysis** | 4 | `get_data_source()`（Mock/SP-API，**非 DB**） | **部分** |
| **ListingGenerator** | 8 | 纯生成，**无取数** | **无** |
| **AIGC 媒体生成器** | 9 | 纯生成，**无取数** | **无** |

**本轮实证的硬数字**：全仓工具层**直接调内核**的只有 **3 个函数**——
`library/tools.py::_rows_to_products`、`product_research/tools.py::_query_market_insight_tool`、
`secretary/product_tools.py::_select_product`。

## 七、未处置（待拍板）

3 处硬编码期望未同步（非本轮引入，单跑仍红）：

1. `tests/test_skill_gate.py:1203` —— `64` → `65`
2. `tests/test_secretary_agent.py:402` —— 期望集合补 `query_market_insight`
3. `tests/test_secretary_agent.py:630` —— `15` → `16`

另有 1 处**门禁缺陷**（可选修）：`tests/test_context_propagation.py` 与
`tests/test_conversation_ownership.py` 的 `rglob("*.py")` 未排除 `.venv`
⇒ 被 joblib 的 GBK 夹具打红（6 个用例）。修法是排除规则加 `.venv`。
