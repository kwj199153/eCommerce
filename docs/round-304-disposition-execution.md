# 第 304 轮（含后半轮更正 —— 见文末第六节） ·「已发放」是语义欺诈：把 `issued` 与 `executed` 拆开（P0·A 档）

> 老板四条指令：① P0·A 档；②【生成待处置】的提示要按真实原因；③ 差评是 009 ASIN、处置台账
> 却是 002 SKU，是不是两份数据；④ 截图那种常驻提示取消，改悬停。

---

## 一、头号结论：`issue_disposition` 零出站调用 ⇒ 「已发放」没有数据支撑

上一轮（303）老板问：「处置完之后，是不是应该接 API 到平台真实处置？」
这一轮把 A 档落地，**先做取证**：

| 取证项 | 结果 |
|---|---|
| `modules/trade/*.py` 里的 HTTP 客户端 | `httpx` / `requests` / `aiohttp` / `urllib` **命中 0 次** |
| `amazon_sp/data_sources/base.py` | 11 个能力清一色 `fetch_*` + `health_check`，**没有任何写方法** |
| `amazon_sp/auth.py` | 只申请 `sellingpartnerapi::migration`（**只读** scope） |
| `platforms/base.py` 抽象基类 | 同样没有写方法 |
| `platforms/shopee/client.py` | 大量 TODO + `return []` |

于是 `issue_disposition` 实际只做三件事：

1. 状态 `approved → issued`；
2. 生成**本地**券码 `_mint_coupon_code()`（注释明写「确定性，便于对账与断言」＝ 测试用）；
3. 可选地把券码重写进回复草稿。

**而界面写着「已发放」+ `effect: '退回部分或全部货款'`。**

这是**字面为真、暗示为假**：本地确实改了状态，但「钱退回去了」是界面自己编的 ——
库里此前**没有任何字段**能回答「平台上做没做」。

### A 档的修法不是「去接平台 API」

接真写接口需要：平台侧写权限 scope（Amazon 要重新申请 LWA scope）、退款/发券的幂等键设计、
失败重试与对账、多平台适配 —— 那是 B/C 档的活。

**A 档先把两个语义在数据层拆开**：

- `issued` ＝ **本地已核准**（券码已生成、给买家的回复可以对外），**平台侧还没动**；
- `executed` ＝ 平台上真的执行完了，且有回执（人 + 时间 + 凭证 + 方式）。

---

## 二、落地清单

### #1108 后端：回执字段 + `executed` 终态

| 落点 | 改动 |
|---|---|
| `modules/trade/db_model.py` | `review_dispositions` 加 5 列：`execution_mode` / `platform_ref` / `executed_by` / `executed_at` / `receipt_note` |
| `alembic/versions/h4f2a7c9d1b3_*` | 新迁移（逐列存在性探测，往返实测通过；`server_default` 补完即摘） |
| `modules/trade/service.py` | `DISPOSITION_STATUSES` 加 `executed`；`TRANSITIONS["issued"] = ("executed",)`；新增 `DISPOSITION_EXECUTION_MODES = ("manual",)`；新增 `record_execution_receipt()`；`_disposition_to_dict` 下发 5 字段 |
| `modules/trade/router.py` | 新增 `POST /dispositions/{review_id}/receipt`（`executed_by` 服务端注入） |
| `modules/trade/__init__.py` | 门面导出 `record_execution_receipt` / `DISPOSITION_EXECUTION_MODES` |

**为什么 `execution_mode` 值域只放 `manual`**：本模块没有任何出站 HTTP 客户端，系统
**没有能力**自动执行。现在就开放 `api` 等于允许「填个 mode 冒充系统已调用平台」——
那是把回执做成另一种自我声明。

### #1109 文案正名

| 位置 | 改前 | 改后 |
|---|---|---|
| 状态标签 | `issued` = 「已发放」(green) | 「已核准 · 待平台执行」(gold)；新增 `executed`「平台已执行」(green) |
| 抽屉按钮 | 「发放（不可逆）」 | 「核准（不可逆）」+ title「本地核准…不会调用平台接口」 |
| 确认框 | 「发放券码 / 退款不可撤销」 | 「本步只在本地登记 —— 不会调用任何平台接口，不会真的退款 / 发券」 |
| 步骤条 | ①草稿 ②批准 ③发放 | ①草稿 ②批准 ③核准 ④**平台执行（人工做完后登记回执）** |
| 通道说明 | 「发一张有面额的券…」 | 追加「★ 本系统不调用平台接口：核准之后仍需人工去平台后台把券发出去」 |
| 后端注释 | 「券真的发出去了」「已发放的补偿」 | 一律换成核准 / 已执行口径 |

### #1110 【生成待处置】用真实原因

真库实测（`probe_r304_backfill_reasons.py`，backfill 只 skip / fail，**不写库**，跑前后行数 5 = 5）：

```
scanned=9  created=0  skipped=5  failed=4
  R1DEMO0103 → 没有针对「物流延迟」的启用规则，给不出补偿方案（可到补偿规则里配一条）
  R1DEMO0151 → 没有针对「描述不符」的启用规则，给不出补偿方案（可到补偿规则里配一条）
  R1DEMO0132 → 没有针对「描述不符」的启用规则，给不出补偿方案（可到补偿规则里配一条）
  R1DEMO0144 → 没有针对「价格价值」的启用规则，给不出补偿方案（可到补偿规则里配一条）
```

**那 4 条全都有归因** ⇒ 界面原来猜的「多半是缺归因或没配规则」里，「缺归因」这一半是错的。
猜错方向的代价不是「说得不够准」，而是**把人引到错的地方**：他跑去重跑归因，而重跑归因
永远跑不出结果（缺的是规则，不是归因）。

> ⚠️ **本段下面这句概括在当天后半轮被实测推翻，见文末「六、后半轮更正」。**
> `R1DEMO0103`（物流延迟）库里**明明有启用规则** `logistics-delay-minor`，把它也报成
> 「没有启用规则」是**假陈述**，且「再配一条」**永远无效**。

改后播报（按归因归并计数，详情留在面板 `a-alert` 上，一句 toast 装不下 4 条不同原因）：

> 4 条给不出方案 —— 这几类归因没有启用补偿规则：物流延迟 1 条 / 描述不符 2 条 / 价格价值 1 条。
> 可到「补偿规则」里给它们各配一条。
>
> ⚠️ 上面这段是**旧版**（已废弃）：① 它把「有规则但条件不符」也报成「没配规则」；
> ② 「补偿规则」**根本没有配置入口**（见六）；③ 现版按 `reason_code` 分两桶给相反的动作。

### #1111 台账加显 ASIN

**不是两份数据，也不是不互通。** 取证（`probe_r303_asin_gap.py`）：

- 23 条差评 **ASIN 全 `B0CXXXX009`、SKU 全 `SKU-KC-002`**；台账 5 条同样。
- 老板看到「002」是因为台账那列渲染的是 `d.review?.sku`（`SKU-KC-002`），
  而 **asin 后端 `_review_to_dict` 本来就下发，只是前端 interface 与模板都没接**。

⇒ 台账表头加 `ASIN` 列（在 `SKU` 之前）。

### #1112 常驻提示改悬停

删掉 `ReviewDeskConfig.vue` 顶部那排常驻 `rd-flow` chip（3 条），同一份口径改挂到按钮 `title`：

| 按钮 | title |
|---|---|
| 刷新 | 「只读：重新拉取列表，不写任何数据、不生成草稿」 |
| 生成待处置 | 「写操作（批量，全仓只此一处）：…已有处置的一律跳过，不覆盖」 |
| 批准 / 驳回 / 核准 / 登记回执 | 「写操作（单条）…只能人点 / 不可逆」 |

CDP 探针 `B2` 随之从「数 chip」改成「数 title」；台账加列后状态列从 `nth-child(6)` 变 7，
两处一并改。

---

## 三、门禁与验证

| 项 | 结果 |
|---|---|
| 新建 `frontend/scripts/check-disposition-execution-honesty.cjs` | H0~H9 共 10 条；已挂进 `npm run build` |
| 该门禁反向注入 | 5/5 命中预期用例（改回「已发放」/ 删回执字段 / 删回执按钮 / 加回「多半是」/ 删「不调用平台接口」各转红） |
| `check-disposition-write-exit.cjs` | `WRITES` 加 `recordExecutionReceipt`（UI 出口 == 1）→ 16/16 |
| 后端 `test_trade_disposition.py` 第 ⑨ 节 | 新增 10 条；**反向注入 4/4**（让 issue 顺手推 executed / 去掉 mode 校验 / 放宽值域 / 去掉登记人校验，各转红） |
| CDP 真实浏览器 `cdp-review-desk-ui-probe.mjs` | **20/20**（新增 B3d：台账首行真的填了 ASIN，不是「—」） |
| `npm run build`（30+ 门禁 + vue-tsc + vite build） | 全链通过 |
| 后端定向回归 | trade 全族 + schema parity + 路由盘点 + 门面打桩 + 记忆卫生，全绿 |

---

## 四、踩到的坑

1. **新增代码撞了既有门禁**：`backfillFailureText` 里写了 `.sort()`，触发
   `check-review-risk-view.cjs` 的 R3「面板不得自己排序」。正确做法是**改掉 sort**（Map 的
   插入顺序 = 后端 `failed[]` 的顺序，已经确定），**不是放宽 R3** —— R3 是对的：
   面板里出现排序就是「顺序的第二份实现」。
2. **加列会让 CDP 探针的列序号错位**：台账插了一列，`td:nth-child(6)`（状态列）要改成 7。
   只查表头有没有 `ASIN` 也不够 —— 单元格里可能仍填着「—」，所以 B3d 判的是**单元格内容**。
3. **ORM 的 `default=""` 只在 INSERT 时生效**：测试里手工构造的 `ReviewDispositionRecord`
   读到的是 `None`，断言「`executed_at == ""`」会静默变松（`None` 也是 falsy）。
   测试夹具必须显式给空串。

---

## 五、未做

- **B 档**：接通一条平台写通道（先只做一家、一类动作），打写侧地基。
- **C 档**：多平台全通道 + 幂等键 + 对账。
- 本轮改动**仍未提交**（与第 303 轮积压在一起）。


---

# 六、后半轮更正：12 / 4 / 5 对账 ·「补偿规则在哪」· 一处自我纠错

老板追问三条：① 风险 12 条、不能生成 4 条、台账才 5 条，为什么对不上；
② 提示让人去【补偿规则】配，可补偿规则在哪；③ 截图「不是这个截图吧？」。

## 6.1 三个数字对不上 —— 因为三条链扫的是**三个不同集合**

`probe_r304_reconcile.py` 真库实测（shop = `store_c3529ab1`）：

| 链 | 输入条件 | 条数 |
|---|---|---|
| 风险识别 `GET /reviews/risk` | `rating <= 3` 且近 30 天，**不要求有归因**；纯判定、**不落库** | **12** 命中（另 8 干净） |
| `backfill_dispositions` | `rating <= 3` **且** `primary_cause != "unknown"` **且**尚无处置 | 可扫 7；5 已有处置 ⇒ 剩 **4** 条尝试生成 |
| 处置台账 `review_dispositions` | 全量 | **5** |

交叉：风险命中 12 条里 —— 有归因 4 / **无归因 8**；有归因总数（近 30 天中差评）7；已有处置 5。

**真因：风险命中的 12 条里，8 条 `primary_cause = unknown`（根本没有归因）**，
处置链的输入条件要求有归因 ⇒ 压根扫不到它们。`review_attributions` 全店 23 条里
`unknown` 占 14 条。

⇒ **不是数据不互通，是两条链的输入条件不同**。这 8 条**永远进不了台账**，
除非先给它们归因（是否补「补归因」入口待老板拍板）。

## 6.2 「补偿规则」**没有配置入口** —— 提示指向了不可达面板

| 层 | 现状 |
|---|---|
| 表 | ✅ `db_model.py:443` `__tablename__ = "compensation_rules"` |
| 种子 | ✅ `seed.py` 3 条：`logistics-delay-minor` / `packaging-damage-standard` / `product-defect-refund` |
| service | ✅ `match_compensation_rule` / `apply_compensation_rule` |
| **后端端点** | ❌ `router.py` 里 grep `compensation\|rule` 只命中 DTO 字段 ⇒ **零 CRUD** |
| **前端入口** | ❌ `api/*.ts` 里 `compensation` 只出现在 DTO 类型；`PlatformRules.vue` 是「平台规则库」，**不是**补偿规则 |

⇒ 界面让人「到补偿规则里配一条」，但**这个面板不存在**（负指令：指向死路）。
本轮只把文案改成「讲成因 + 真实下一步」；**是否补一个真实配置入口属新功能，待老板拍板**。

## 6.3 自我纠错：`match_compensation_rule → None` 有两种成因（#1116）

| 成因 | 真实下一步 | 旧文案是否适用 |
|---|---|---|
| ① 该 cause 一条启用规则都没有 | 需要新增规则 | ✅ |
| ② 有规则，但这条差评不满足条件 | 改条件 / 改数据 / 人工兜底 | ❌ **假陈述**，且「再配一条」**永远无效** |

事故本尊：`R1DEMO0103` 归因 `logistics_delay`，库里有启用规则
`logistics-delay-minor`（`enabled=True`, `cond={max_rating:3, min_delay_days:3}`），
却被报成「没有针对『物流延迟』的启用规则」 —— 因为 `build_disposition_draft`
把两种成因合并成一句话。`tools.py::plan_compensation` 有**同款** bug，一并修。

落点：

- `service.py` 新增 `list_enabled_rules_for_cause()` —— **候选集唯一实现**，
  `match_compensation_rule` 改为复用它；`build_disposition_draft` 四条「给不下」分支
  各下发 `reason_code`：`no_rule` / `rule_conditions_unmet` / `no_attribution` / `over_budget`。
- `frontend/src/api/trade.ts` 新增 `BackfillFailure`（`failed: any[]` → `failed: BackfillFailure[]`）。
- `ReviewDeskConfig.vue::backfillFailureText` 按 `reason_code` 分 `noRule` / `condUnmet` 两桶，
  **给相反的下一步动作**；兜底按原文归并，刻意不用 `.sort()`（R3）。
- 门禁 `check-disposition-execution-honesty.cjs` 新增 **H6b**：失败原因必须按后端 `reason_code`
  分流（不许前端正则猜形状）—— 断言含 `reason_code` / `'no_rule'` / `'rule_conditions_unmet'`，
  且**不含**旧文案「没有针对」。
- 后端 `test_trade_disposition.py` 追加第 ⑩ 节 4 条，其中
  `test_candidate_rule_lookup_has_a_single_source` 用 `inspect.getsource` 钉「候选集唯一真源」并带反向自检。

验证：后端 `test_trade_disposition.py` 40 条全绿；trade 相关 9 文件 123 条全绿；`vue-tsc` 过；
`npm run build` 全链过（含处置诚实性门禁 11 条）。**反向注入 3/3 命中预期用例**
（退回 `no_rule` / `match` 不复用候选集 / 前端不读 `reason_code`）。

## 6.4 截图认错 —— 查明，未擅自再删

- 前半轮删的是顶部那排 `rd-flow` 常驻 chip（`grep -c rd-flow` 现 = 1，仅剩注释行 2031）。
- 老板这次的截图 2 指向的是**另外两块**常驻说明（`ReviewDeskConfig.vue:492~546`）：
  ① `处置通道` 块的 `rd-chips` + `⚠️ 已选不可逆通道`（516~519）；
  ② `补偿方案` 块的「要调金额请去改规则表」（543~544）—— 这句**同样指向不存在的面板**。

**本轮未删除任何东西**，列候选请老板点名。

## 6.5 本轮新增的坑

1. **一个 `None` 两种成因 ⇒ 合并成一句话 = 假陈述 + 永远无效的建议**（本轮事故本尊）。
   凡是「取不到 ⇒ 报一句」的分支，都要先问「取不到有几种成因、各自下一步是什么」。
2. **提示里的「去 X 里配」是负指令**：X 若没有入口，提示就是把人引向死路。
   写这类引导前先数 X 的**消费点**（后端端点 + 前端入口），一个都不存在时应写「暂不支持」。
3. **数字对不上先数三条链各自的输入条件**，不要先猜「数据不互通」。

## 6.6 待拍板

| # | 事项 |
|---|---|
| ① | 要不要给「补偿规则」补真实配置入口（后端 CRUD + 前端面板） |
| ② | 那 8 条无归因的风险差评要不要给「补归因」入口 |
| ③ | 截图里两块常驻说明要取消哪一块 |
| ④ | 本轮 + 第 303/304 轮改动**全部未提交** |
