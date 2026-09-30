# 第 260 轮 · 新增「复盘库」（资料库第 7 个库）+ 平台规则库是否移动的结论

## 0. 需求原话

> **1.新增一个复盘库  2.平台规则库（你认为需要移动吗）**

拆解：
- 子问题 1 = 开工指令。承接上一轮已定方案：**人工确认才入库**的复盘资料库，
  范围锁定「**入库 + 列表 + Agent 可读上期**」。
- 子问题 2 = 征询判断。

## 1. 子问题 2 的结论：**不建议移动**（维持现状）

平台规则库是**店铺级**数据，放进**账号级**的用户下拉菜单会造成**作用域错位**。
三条独立证据：

| 证据 | 位置 | 内容 |
|---|---|---|
| 外键 | `modules/platform_rules/db_model.py` | 两张表都有 `shop_id` → `stores_store.id`（约束名 `fk_platform_rules_shop_id_stores_store`） |
| 路由注释 | `modules/platform_rules/router.py:16` | 逐字「租户隔离：全部走 `get_current_shop_id`」 |
| 前端注释 | `components/KnowledgeBase/PlatformRules.vue:1208` | 「正常由 Workspace 的 `watch(currentShopId)` 触发」 |

⇒ 「菜单位置 ≠ 作用域」。若真实痛点是**每店重复维护**或**侧边栏太长**，
应分别用「规则模板 / 跨店复制」或「分组折叠」解决，**而不是移菜单**。

## 2. 本仓「资料库」是既有产品概念，不是新造

`Sidebar/KnowledgeBase.vue` 的「资料库」分组原有 **6 个库**：
`candidates / assets / products / competitors / faq / rules`；
后端 `modules/library/tools.py` 提供 6 个**只读**工具。
本轮加**第 7 个**（key = `reviews`）。

该分组的写死规约（`KnowledgeBase.vue` 注释逐字）：

> 资料库那一组**全部按 `X-Shop-ID` 过滤**（换店铺就换内容）；
> 技能是账号级、工具是平台级，都与店铺无关。

⇒ 复盘库与这 6 个**同组**，**不能**放进下面「能力」那一组。

## 3. 本轮改动清单（8 项）与落点

| # | 落点 | 文件 | 说明 |
|---|---|---|---|
| 1 | 数据层 | `backend/modules/review_analyst/db_model.py`（新） | `ReviewReportRecord` + 四维唯一约束 + FK 自洽注册 |
| 2 | 迁移 | `backend/alembic/versions/e7b2c9d4a1f8_review_reports_library.py`（新） | **幂等守卫**版（表/索引逐个探测） |
| 3 | 模型注册 | `backend/core/database.py` | `register_all_models()` 追加（**唯一真源**） |
| 4 | 查询元数据 | `backend/modules/review_analyst/spec.py`（新） | `REVIEW_SPEC`（`key="reviews"`） |
| 5 | 服务层 | `backend/modules/review_analyst/service.py` | `save_report / list_saved_reports / count_saved_reports / get_saved_report` |
| 6 | 端点 | `backend/modules/review_analyst/router.py` | `POST/GET /review/reports`、`GET /review/reports/{id}` + `_guard` 统一异常映射 |
| 7 | Agent 工具 | `backend/modules/review_analyst/tools.py` | 第 7 个工具 `list_reviews`（**只读**） |
| 8 | 工具目录 | `backend/modules/skills/tools_catalog.py` | 登记 + 分母 60 → **61**（4 处名单同步） |
| 9 | 前端 API | `frontend/src/api/review.ts` | `saveReviewReport / listSavedReports / getSavedReport` + 中文名唯一真源 |
| 10 | 归档入口 | `.../conversation/ReviewReportCard.vue` + `ConversationCard.vue` | 底部「归档到复盘库」（footer slot） |
| 11 | 视图贯通 | `Sidebar/KnowledgeBase.vue`、`views/Workspace.vue` | 菜单项 + 渲染分支 + 联合类型 + cast |
| 12 | 跨端白名单 | `frontend/src/utils/appActions.ts`、`backend/modules/secretary/navigation_tools.py` | `AppView` / `VALID_VIEWS` / `VIEW_LABELS` / `VIEW_IDS` / `ViewId` |
| 13 | 复盘库页面 | `frontend/src/components/KnowledgeBase/ReviewLibrary.vue`（新） | 列表 + 详情抽屉 + **周期对比**（本期 vs 上期） |

## 4. 六个关键设计决定（以及为什么）

### 4.1 幂等键为什么是**四维**

`uq_review_reports_scope = (shop_id, report_type, period_days, period_end)`。

只按 (店铺, 类型, 周期末日) 三维去重的后果：
**同一天归档的「7 天复盘」与「14 天复盘」会互相覆盖** ⇒
`list_reviews` 永远读不到「上期」⇒ 复盘师那句「下一期读到上期做对比」失效。
`period_end` 由**服务端**写（`_today_iso()`，不读请求体）—— 客户端可控就等于
客户端能决定「覆盖哪一条」。

### 4.2 归属：请求体在**结构上**影响不了归属

快照（`data`）由前端原样回传，里面的 `store_id` 天然可被改成别家。
`service.save_report` 把 `report_type / period_days / store_id` **覆盖**成
服务端已校验的值后再落库 ⇒ 请求体在结构上不可能影响归属与幂等键。
（同族先例：`ReviewRequest` 干脆**没有** `store_id` 字段。）

判据不是「400」，而是「照发不报错、但**不被采纳**」——
只断言 `status == 200` 的写法会漏掉「采纳了 body」的实现。

### 4.3 「不存在」与「不属于你」回**同一句 404**

`service.get_saved_report` 的归属过滤走 `scoped()`，两种情形都 `None` ⇒
router 回同一句「复盘不存在」。否则可区分 ⇒ 可以拿 id 逐位枚举别家报告。

### 4.4 读口排序/过滤非法 ⇒ **400，不静默退化**

排序白名单 / 过滤值域 / limit 归一 / 真实 count 全部收口到
`core.library_query`（`REVIEW_SPEC`），REST 与 Agent 工具**共用同一份**。
非法值显式报错：静默退化会让「按创建时间排」与「你参数写错了」长得一样。

### 4.5 第 7 个工具**挂在复盘师自己**名下

不登记进 `modules/library/tools.py` 那 6 个跨 Agent 共用工具：
那 6 个是「读当前店铺的某个资料库」；而 `list_reviews` 的存在理由是
「**下一期复盘自动读到上期**」—— 消费者是复盘师本人。挂到别家去，
本模块的复盘就永远读不到自己的历史。

### 4.6 空状态 vs 失败态，前端分三种情形

| 情形 | 界面 | 为什么 |
|---|---|---|
| 库里没有（`total=0`） | 空状态 + 「去对话里生成并归档」 | 处置是"先去归档" |
| 筛选后为空 | 空状态 + 「清空筛选」 | 处置是"换条件"（**留逃生口**） |
| 请求失败 | 错误态 + 「重试」，**绝不**退回空状态 | 把故障说成"你没归档过"是归因错方向 |

## 5. 顺手修掉的既有漂移（`competitors`）

**改前**：`VIEW_LABELS` / `AppView` / `VALID_VIEWS` / 后端 `VIEW_IDS` 里
有 `monitor` 但**没有** `competitors`，而 `Workspace.currentView` 实际用
`'competitors'` 渲染竞品监控池。

后果是**同一条能力两条通道两种结果**：
组件内部走 CustomEvent（`IntelBoardConfig.vue:531`）能跳过去；
**经 AI 动作跳转会静默 `return false`**（白名单没这个值）。

**改后**：`competitors` 补进四处白名单；`monitor` **保留**并写清它
**不是**一个视图 id —— 它是「竞品监控**看板**」（大屏模式），
`handleKnowledgeNavigate` 收到它会重定向到 `openIntelBoard()`。
两者并存是有意的。

## 6. 门禁与**反向注入**验证

「没被反向注入验证过的门禁 = 没有门禁」。两份探针都把
「**注入本身失败**」（锚点失效）与「**注入没抓到**」（没变红）分开报。

| 探针 | 位置 | 结果 |
|---|---|---|
| 后端 | `.workbuddy/probes/r260_review_library/inject_reverse.py` | 注入 **16** / 变红 **16** / 异常 **0**，还原后基线 31/31 绿 |
| 前端 | `.workbuddy/probes/r260_review_library/inject_reverse_frontend.cjs` | 注入 **17** / 变红 **17** / 异常 **0**，还原后基线 37/37 绿 |

反注入**抓到两个真实的门禁缺陷**（都已修）：

1. **F4 被判据前缀顶掉**：原写法 `/res\.item/` 被**页面**里的 `res.items`
   （复数）满足 —— `res.item` 是 `res.items` 的前缀 ⇒ 把归档端点的
   "伪成功防御"删掉，断言照样绿。改为 `/\bres\.item\b/`。
2. **F5 被注释喂饱**：原写法 `/\$slots\.footer/` 对**原文**匹配，而外壳文件的
   注释里就写着「用 `$slots.footer` 判断…」⇒ 把真实属性删掉也不红。
   改为统一走 `code()`（剥三类注释）后再断言。

另有两条注入的锚点在 Workspace 里**命中 2 次**（联合类型 + cast 各一份）
——被 `INJECT_FAIL` 单独报出来，而不是记成"门禁没抓到"。

## 7. 门禁清单（新增）

- `backend/tests/test_review_library.py`（新，31 条用例 / 25 个用例函数）
  · 写口缺头 400 / 读口缺头空列表 / 详情缺头 404
  · 快照 `store_id` 不可覆盖；两店互不可见
  · 幂等（`created` 先 true 后 false，库里仍 1 行）；不同 `period_days` 分行
  · 写口值域（`report_type` / `period_days` / `data`）⇒ 422
  · 「不存在」与「不属于你」同一句 404
  · 列表不出快照 / `total` 不被 limit 截断 / 排序与过滤非法 ⇒ 400
  · `list_reviews`：无归属 ⇒ `library_read_failed`；参数非法 ⇒ `invalid_argument`
  · AST：端点清单**集合相等**、`save_report` 从不读 `payload["store_id"]`、
    `_require_store` + `validate_save_payload` 真被调用、工具只读、spec key
- `frontend/scripts/check-review-library-view.cjs`（新，37 条形态断言）
  · 五处接线逐个 key（侧边栏 / 渲染分支 / 联合类型 / cast / AppView / VALID_VIEWS / VIEW_LABELS / VIEW_IDS）
  · **集合相等**（不是子序列）：侧边栏两组 key == 视图联合；
    AppView \ {chat, monitor} == 资料库分组；后端 VIEW_IDS == AppView \ {chat}；
    渲染分支 == 视图联合（**双向**：无孤儿视图、无孤儿分支）
  · 唯一真源：会话卡不得再写一份类型中文名；前端类型集合 == 后端 `REVIEW_REPORT_TYPES`
  · 归属：页面不得出现 `store_id`（剥注释后判）
  · 失败路径：错误态优先于空状态；归档有失败回写；匿名/缺店铺可归因
  · 已接入 `package.json` 的 `build` 链与 `check:review-library`

## 8. 已知的诚实边界

- `MockAmazonDataSource` 不按 `store_id` 过滤 ⇒ 本轮的「按店铺分区」判据
  只测到**复盘库这一层**（`review_reports.shop_id` 真实生効），
  6 项能力的取数分区仍由数据源侧负责。
- `alembic check` 恒 FAILED：库里有两条**与本轮无关**的既有 schema 偏差
  （`skills.icon` nullable / `stores_store.is_demo` 注释）。本轮不"顺手修"，
  另写探针用**同口径差分**证明「本轮零偏差」（`check_schema_drift.py`）。
- 前端「复盘库」页面的**周期对比**只按**指标名**对齐（取并集，缺的一侧显示「—」）。
  两份类型不同的报告放在一起比时会有大量「—」——界面已显式提示
  「两份复盘的类型不同」。不做"按下标对齐"（会把「营收」和「ACoS」摆同一行）。
- 平台规则库**未移动**（见 §1）。
