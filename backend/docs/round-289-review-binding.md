# 第 289 轮：差评 ↔ 产品关联（SPU 聚合壳 + 孤儿兜底）+ 差评工作台入口

> 起因：老板拍板
> **P0** 产品详情加「差评 tab」（按 SKU 软关联，空态区分两种语义），并追问「挂在 SPU 上是否合理」；
> **P1** 补「孤儿差评」兜底列表（SKU 关联不上的那批）；
> 同时纠正「不做 ①」的真实所指 —— **不做**的是把 approve/issue 做成 Agent 工具，
> **要做**的是「差评处理」做成客服 Agent **功能栏 form 工具按钮** + 右侧边栏列表，
> 并追问「确定性 → 功能栏、不确定 → 快捷卡片 skill」这个理解对不对。
>
> 本文是代码 + 真库取证的结果，不是评估意见。取证日期：2026-09-28。

---

## 〇、两句话结论

1. **挂 SPU 上合理，但 SPU 只能当「聚合壳」** —— SPU 无 ASIN、不可售，真正的匹配键是 **SKU 的 ASIN**；
   `spus.id → skus.spu_id → skus.asin` 这条路成立，代价是三条必须同时做对的 plumbing（去重 / 穿透店铺 / 两义空态）。
2. **「确定性 → 功能栏，不确定 → 快捷卡片 skill」这个理解是对的**，而且本仓早就按这条线实现了
   （`ToolDefinition.mode: 'form' | 'chat' | 'page'`，`mode='form'` 即点开右侧面板）。
   唯一例外：**批准 / 发放（approve / issue）不可逆**，不进任何工具，只走面板人工按钮 + REST。

---

## 一、SPU 能不能当挂载点

### 支持「挂在 SPU 上」的实证

| 事实 | 锚点 |
|---|---|
| SPU **无 ASIN、不可售**，只聚合公共属性 | `modules/products/db_model.py:9-11` |
| SKU **独立 ASIN**、一条 SKU 归属一个 SPU（`spu_id` 外键，这是**真外键**） | `modules/products/db_model.py:12-14` |
| 产品详情抽屉里本来就有 SKU 子表 —— 用户看 SPU 时的心智就是「这一整个产品怎么样」 | `frontend/src/components/KnowledgeBase/ProductLibrary.vue:621-630` |
| SKU 详情不需要另做一套：SKU 用 `p.spu_id` 兜到父 SPU 再聚合 | `ProductLibrary.vue:1198-1202` |

### 代价：三条 plumbing，漏一条就出错且**不报错**

| # | 代价 | 不做的后果 | 实测锚点 |
|---|---|---|---|
| 1 | **必须 `distinct`** | 真库 `B0CXXXX009` → 4 SKU / **4 个不同 SPU**：同一批差评被 4 个产品各认领一次，`count` 虚增 4 倍、分页还会漏行 | `service.py:1270-1275`、探针 C1 |
| 2 | **店铺作用域要穿透** | `skus` 表**没有 `shop_id`**，只能用 `scope_condition(SpuRecord, shop_id)` 经 `spus` 过滤；漏了 ⇒ 别店 SKU 来认领本店差评 | `service.py:1333-1345`（该函数内出现 **2 次** `scope_condition(SpuRecord, ...)`） |
| 3 | **「空」有两义，必须分开播报** | 混成一句「暂无差评」＝ 把数据缺口伪装成「产品没问题」 | `ProductLibrary.vue:1239-1272` |

### 结论与边界

- **合理**：SPU 是产品库现有的聚合壳，用户「看产品」的粒度就是 SPU；
- **但不是挂载点意义上的合理**：差评物理上挂在 ASIN 上，SPU 只是**转发**。
  所以接口叫 `by-spu/{spu_id}` 而不是「产品差评」，返回里还会带回 `sku_count` / `asin_count`
  让用户知道「这次是靠什么关联上的」。
- **什么时候不合理**：如果一个 SPU 名下 SKU 跨了多个店铺（同一份目录被多家店共享），
  SPU 聚合会把别店差评算进来 —— 本实现用 `spus.shop_id` 收窄，拿不到就 `not_found`（不是「空」）。

---

## 二、P0 的核心：两种「空」必须字面不同

后端返回 `empty_state`，四种取值都不是「列表为空」的替身：

| `empty_state` | 含义 | 是否算结论 | UI |
|---|---|---|---|
| `no_reviews` | 关联得上，确实没有符合条件的评价 | ✅ 正常结论 | ✅ 绿色，「未见中差评」+ 已登记 SKU/ASIN 数 |
| `no_asin_binding` | SKU 登记了，但 ASIN / SKU 码**都是空的** ⇒ 差评再怎么存在也对不上 | ❌ 数据缺口 | ⚠️ 黄色，提示「先去补 SKU 的 ASIN 再回来看」 |
| `no_sku` | SPU 下还没登记任何 SKU | ❌ 数据缺口 | ⚠️ 黄色 |
| `not_found` | 该产品在所选店铺下查不到（别店 / 已删） | ❌ 权限或生命周期 | 🔒 警告色 |

匹配条件两侧都要判非空，否则 `"" == ""` 会让**所有**空 ASIN 差评命中**所有**空 ASIN SKU
（把「没登记」读成「全店通用」）—— 这类 bug 不报错，只表现为「数量不对」：

```python
# service.py:1278-1298
or_(
    and_(CustomerReviewRecord.asin != "", SkuRecord.asin != "",
         SkuRecord.asin == CustomerReviewRecord.asin),
    and_(CustomerReviewRecord.sku != "", SkuRecord.sku_code != "",
         SkuRecord.sku_code == CustomerReviewRecord.sku),
)
```

---

## 三、P1 孤儿兜底：为什么必须单独一条路

「某个 SPU 有多少差评」回答不了「这批差评**有没有被认领**」。孤儿列表的判据是
**在本店的 ASIN/SKU 码解集里找不到任何承接方**：

```python
# service.py:1487-1495
~(select(SkuRecord.id)
  .join(SpuRecord, SpuRecord.id == SkuRecord.spu_id)
  .where(scope_condition(SpuRecord, shop_id))
  .where(_review_match_condition())
  .correlate(CustomerReviewRecord)).exists()
```

两个坑，都**不报错**：

- `.correlate(CustomerReviewRecord)` **不能省**：省掉后条件退化成「本店是否存在任意能对上的 SKU」
  ⇒ 结果要么全孤儿、要么全不孤儿。
- 承接方必须是**本店**的 SKU：把 SPU 挪到别店后，差评应立即回落为孤儿（探针 C6c 实测 5/5）。

---

## 四、入口：为什么「差评处理」是功能栏而不是快捷卡片

`ToolDefinition.mode`（`frontend/src/components/ChatPanel/tools/toolDefinitions.ts:15`）：

| 落点 | 是什么 | 点击后去哪 |
|---|---|---|
| `mode='form'` | **功能栏工具按钮** | 右侧 `TaskConfigPanel` 出面板 |
| 对话输入框上方的「快捷卡片」 | skill chip | 进 LLM 推理一轮 |

按老板的分法套到差评上：

- 「本店有哪些差评 / 哪些没关联上产品 / 处置到哪一步了」＝ **查表可答**，不需要 LLM ⇒ form 工具；
- 「帮我归因根因 / 该怎么赔 / 回复话术怎么写」＝ **结论不确定** ⇒ skill chip 走对话。

所以给 `customer-service` 加的是 `review-desk`（`mode: 'form'`），面板落在
`TaskConfigPanel/configs/ReviewDeskConfig.vue`，双视图：

- **近期差评**（时间窗 + 星级筛选）→ 点开右侧处置抽屉；
- **未关联产品的孤儿差评**（P1 兜底）。

**唯一不进工具的**：approve / reject / issue —— 面板里是人工按钮 + 二次确认，
后端 REST `POST /reviews/dispositions/{id}/approve|reject|issue`
（`trade/router.py:308/323/343`，issue 标注「不可逆」），HITL 兜住。这与老板「不做 ①」一致。

---

## 五、改动清单

### 后端

| 文件 | 改动 |
|---|---|
| `modules/trade/service.py` | 新增区块「产品 ↔ 差评 关联」：`_review_match_condition`(1278)、`_rating_condition`(1301)、`_match_kind_of`(1315)、`list_reviews_for_spu`(1328)、`count_orphan_reviews`(1428)、`list_orphan_reviews`(1447)、`_not_bound_to_sku`(1487)；另抽 `_recent_negative_condition`(653) 给 list/count 共用一份条件 |
| `modules/trade/router.py` | `GET /reviews`(223) 主列表、**`GET /reviews/by-spu/{spu_id}`**(255)、**`GET /reviews/orphans`(282)** |
| `modules/trade/__init__.py` | 门面导出四个新函数 |

### 前端

| 文件 | 改动 |
|---|---|
| `api/trade.ts` | `listShopReviews`(218) / `listReviewsBySpu`(234) / `listOrphanReviews`(248) |
| `KnowledgeBase/ProductLibrary.vue` | 详情抽屉 `a-tabs`(490) 加「差评」pane；条数/缺口角标；`reviewEmpty`(1239) 四态分别播报；开抽屉/换产品自动重拉(1231) |
| `ChatPanel/tools/toolDefinitions.ts` | `customer-service` 增加 `review-desk`(221)，注释写明确定性 vs 不确定的落点 |
| `TaskConfigPanel/index.vue` | `<ReviewDeskConfig v-else-if="currentTool.id === 'review-desk'" />`(168) |
| `TaskConfigPanel/configs/ReviewDeskConfig.vue` | **新建** 差评工作台面板（近期 / 孤儿双视图 + 处置抽屉） |

### 测试

`backend/tests/test_trade_review_binding.py`（新建，**19 项全绿**）：空态字面、`.distinct()`
必存、`total` 计 distinct、`match_kind` 报告、`scope_condition(SpuRecord, shop_id)` ≥ 2 次、
孤儿 `correlate` + `spus.shop_id`、禁止手写 `Xxx.shop_id ==`、四个 service 函数必须各有 HTTP 出口。

---

## 六、取证结果（2026-09-28 复跑，产物 `backend/out-probe-binding.txt`）

探针 `scripts/probe_review_binding_api.py`，直连真库 `postgres@localhost`：

```
=== C1+C2 逐个 SPU 聚合 ===
  prod-002: found=True empty=None sku=1 asin=1 total=4 页内重复=False match_kind=['asin']
  其余 SPU : found=True empty=no_reviews total=0
  => 跨 SPU 认领次数分布: {'R1DEMO0001':1,'R1DEMO0002':1,'R1DEMO0003':1,'R1DEMO0004':1}
=== C3 跨租户反向注入 ===
  victim=prod-002 别的 shop -> not_found；None shop -> not_found        => PASS
=== C4+C5 孤儿 ===
  max_rating=None: 本店差评=4 孤儿=0 (count_orphan=0)
=== C6 反向注入（事务内，最后 rollback） ===
  注入 1 条无匹配差评         -> 孤儿=1 (count=1) 命中=['crev-probe-orphan-1']   PASS
  把它的 ASIN 改成能匹配的     -> 孤儿=0                                        PASS
  把全部承接方 SPU 挪到别店    -> 孤儿=5（不认别店 SKU）                          PASS
=== C7 反向注入 no_asin_binding ===
  清空 SKU 的 ASIN/SKU 码：before empty=None total=4 → after empty=no_asin_binding total=0  PASS
=== 汇总 === C6a/C6b/C6c/C7 全绿
```

**复跑后复核真库未被污染**：`reviews 总数 = 4`、`探针残留 = 0`、`prod-002 shop = store_c3529ab1`、
`prod-002 SKU = B0CXXXX009 / SKU-KC-002`（全部按原样回滚）。

其它门禁：

- 路由实挂验证 `scripts/probe_check_trade_routes.py`（直读 `app.routes`，不受 `route_inventory.py`
  的 `_biz[:15]` 截断打印误导）：`/api/v1/trade/*` **10 个端点齐全，缺失：无**。
- `vue-tsc --noEmit` 0 error；`node scripts/check-tool-reality.cjs` **39/39 PASS**（F1「注册了没入口」
  与 F7「active 目录没承载面板」成对，双向都验）。
- 受影响回归批次全绿（列强分层/租户 21、trade 域 51、契约 12、鉴权 45、客服+知识库 66）。

---

## 七、本轮在门禁上抓到的假绿（值得记一笔）

| 坑 | 现象 | 修法 |
|---|---|---|
| **docstring 会骗过字符串判据** | 判据写 `"no_asin_binding" in src`，而该串只存在于注释里 ⇒ 把真逻辑改错照样绿 | AST 取字符串常量并**剥 docstring**（`_string_literals_in`） |
| **router 调用点探不到** | 本仓是 `_guard(service.X, ...)`，收「调用」得到空集恒红 | 改收**属性引用**，并加 `test_router_call_probe_is_not_empty` 自证探针非空 |
| **店铺判据太弱** | 同一 needle 出现 2 处，删一处仍绿 | 改成 `>= 2` 次，并在报错里点名两处路径 |
| **假会话误判语句** | 孤儿明细查询被当成 SKU 列表查询 | `NOT (EXISTS` 判据排在 `FROM skus` **之前** |

---

## 八、遗留（不影响验收，待老板拍板）

1. **演示数据只有一条 ASIN 有差评**（`B0CXXXX009` → 4 条），其余 SPU 全是 `no_reviews`；
   要看「缺口型空态」得手动清一次 SKU 的 ASIN —— 是否在 seed 里造一两条「ASIN 未登记」的样本 SKU。
2. **`order-track` 的取数源错位**（顺手复核时确认，非本轮引入）：对话范式 A 查 `orders` 命中，
   工具卡范式 B 走 `get_data_source(prefer="sp_api")` 查不到 —— 与本轮无关，已在 `toolDefinitions.ts:199-210` 记录待定。
3. 一次性补丁脚本（`backend/scripts/_patch_*.py`）尚未整理留痕 / 或退役。
