# 第 335 轮 · 架构复审（第二次）：P0 执行结果 + 分层方向攻坚

> 触发：老板指令「先 P0 的 6 项都做，然后**再次审查**项目的架构、模块化、
> 高内聚低耦合高复用（**特别要取消分层方向被打破这个问题**）」。
> 上一轮（第 334 轮）是**只读审查**（`docs/round-334-architecture-review.md`），
> 本轮**授权动手**：可改生产文件、可提交。
>
> 本报告的全部数字**由探针现算**，不手写：
> `.workbuddy/probes/r335-p0-8/measure.py`、`.workbuddy/probes/r335-p0-7/scan_core_reverse_deps.py`。

---

## 摘要（TL;DR）

| 项 | 状态 | 关键数字 |
|---|---|---|
| P0-1 分批提交 299 文件 | ✅ 完成 | 6 批入库，工作树干净 |
| P0-2 治理日志 | ✅ 完成 | `backend/logs` **1.2 G → 0.26 G** |
| P0-3 删前端 `mock/data.ts` | ⏸ **前提被证伪** | 它是**活代码**（有消费点） |
| P0-4 拆 `ReviewDeskConfig.vue` | ⬜ 未做（真实，2646 行） | 见 §5 决策项 |
| P0-5 统一亚马逊数据源真源 | ⬜ 未做（真实，双实现皆活） | 见 §5 决策项 |
| P0-6 拆 1289 行方法 | ⏸ **前提被证伪** | **不存在** 1289 行方法 |
| **P0-7 取消分层方向被打破** | ✅ **完成 29/36** | `core → modules` **35 → 7**，`core → ai_infra` **1 → 0**（合计 36 → 7） |

**分层方向这一项（老板点名重点）**：`core/` 反向依赖 `modules/` 从 **36 处降到 7 处**
（−80.6%），`core → ai_infra` 从 1 处降到 **0**。余下 7 处**全部**指向同一件事
（计费实体 `Subscription` / `SubscriptionPlan`），且**不能靠现有手法消除** ——
理由见 §2.3（有本仓三处自证）。

---

## 一、已完成并提交（含验证证据）

### 1.1 P0-1 保命提交 ✅

299 个未提交文件按**语义边界**分 6 批入库，避免「一个巨型提交无法回溯」：

```
95a7abe  feat(backend): 同步积压的后端源码（core / ai_infra / platforms / modules / alembic）
db56b5f  test(backend): 同步积压的测试用例与运维/探针脚本
144cb72  feat(frontend): 同步积压的前端源码、门禁脚本与 mock 退役
62505da  fix(backend): 同步 models/store.py 的字段调整
e5df944  docs: 落盘各轮次审查/架构/交付记录与复盘报告
d827785  fix(backend): 日志治理 P0-2
```

- 全程**未使用** `git checkout` / `stash` / `reset --hard`（本仓铁律：有未提交改动时
  无差别回滚会静默毁掉整轮）。
- `git status --porcelain` 最终为空。
- 触发的两个 hook 问题都按 hook 的**本意**修（把 6 个 `tmp_*.py` 归档到
  `.workbuddy/probes/r335-p0-1/archived-tmp-scripts/` 后再提交），未用 `--no-verify` 绕过。

### 1.2 P0-2 日志治理 ✅（提交 `d827785`）

- **磁盘**：`backend/logs` **1.2 G → 0.26 G**（释放 ~0.95 GB）。
- **根因是四层叠加**（比第 334 轮报告的判断更深）：
  1. `core.middleware.request_log` 每请求一条 INFO（13k+/日，含自动化流量）；
  2. `python_multipart` 第三方 DEBUG 噪音（7.5k）；
  3. `ai_infra.base_agent:__init__` / `dashscope_client`（8.3k）—— **每请求重新初始化 Agent**；
  4. **watchfiles 自反馈**：`--reload` 的 watcher 监听 `backend/logs/`，
     日志里逐字写着 `'D:\ai\eCommerce\backend\logs\2026-09-30.log'`
     ⇒ 「写日志 → 目录变更 → 重载 → 再写日志」。
- **多进程轮转竞争铁证**：`2026-09-28.log.gz` 与
  `2026-09-28.2026-09-29_00-07-13_129807.log.gz` 字节数**完全相同**（8,789,619），
  解压后 md5 全等（`711bde67…`，738,001 行）—— 即同一批内容被两个进程各写了一份。
- **修法**：
  - `core/logger.py` 复合轮转判据：**跨天 _或_ 超 `log_file_max_mb`（默认 200 MB）**；
  - 按**进程角色**分文件（`LOG_SINK_ROLE`，固定 `app` / `worker` / `beat`），
    竞争面归零；★ 不能用 `{process.id}`：loguru 的 `_file_sink.py::_create_path`
    只向文件名模板提供 `{time}`，硬插 pid 会让 retention 的 glob 变成 `*.12345.log`、
    **旧文件永不清理**；
  - 第三方降噪名单扩展（`python_multipart` / `watchfiles` / `celery.utils.functional` 等）；
  - `start-backend.bat` 加 `--reload-exclude logs/ .venv/`，切断自反馈。
- **验证**：`py_compile` OK；冒烟探针两支全绿（`LOG_SINK_ROLE` 空 / 非空）；
  `test_core_internal_layering.py` + `test_no_random_in_production.py` **22 passed**。

### 1.3 P0-7 取消分层方向被打破 ✅（提交 `a50b484` + `93256aa`）

见 §2（重点章节）。

---

## 二、【重点】分层方向：36 → 7（合计），以及最后 7 处的技术论证

### 2.1 事实

```
探针：.workbuddy/probes/r335-p0-7/scan_core_reverse_deps.py（AST，剥注释/字符串）

  第 334 轮报告口径：24 处（`core → modules`）+ 1 处（`core → ai_infra`）
  本轮实测起算值  ：35 处（`core → modules`）+ 1 处（`core → ai_infra`）
                    （报告低估了 11 处，原因见 §3.3「事实更正」）

  本轮处理后      ： 7 处（`core → modules`）+ 0 处（`core → ai_infra`）
```

36 → 7 的构成：**B 档 −28（`core → modules`）／A 档 −1（`core → ai_infra`）**。

### 2.2 做法：A 档「归位」+ B 档「依赖倒置」（不是 importlib 绕门禁）

**A 档（`core → ai_infra` 1 → 0）**：`DISTILL_HOUR` / `DISTILL_MINUTE` 的唯一消费方是
`core/redis.py` 的 `beat_schedule`。它们语义上是**部署侧调度时刻**（与 `core/config.py`
的 `BILLING_SWEEP_HOUR` 同类），已上移为 `MEMORY_DISTILL_*`。
业务口径（`DISTILL_PERIOD_HOURS` / `COOLDOWN` / `LOOKBACK`）仍留
`ai_infra/memory/limits.py` —— **唯一真源不破**。

**B 档（`core → modules` −28）**：`register_all_models`(17) + `seed_base_data`(11)。
它们是「**清单**」不是「机制」—— `core` 里硬编码了全部业务模块名。
做法是**依赖倒置**：

```
新增组合根 backend/wiring.py（顶层，既不在 core/ 也不在 modules/）
    MODEL_MODULES : tuple[str, ...]   # 22 个 ORM 模型模块
    SEED_STEPS    : tuple[SeedStep, ...]  # 12 步引导（有序；目标写成 "包.模块:属性"）

core 只留机制（参数必填、无默认值）：
    core/database.py  :: register_all_models(model_modules) / init_db(model_modules)
    core/bootstrap.py :: seed_base_data(steps) / SeedStep / _resolve()
                        / seed_default_plans()（内建步骤：订阅套餐）

依赖方向由此反转：wiring → core、wiring → modules 都是合法方向；core 不再认识 modules。
```

三个**刻意的设计约束**：

1. **参数必填无默认** —— 漏传直接 `TypeError`，而不是静默注册 0 个模型 /
   灌 0 条数据。后者是**没有任何报错的**故障（只在线上表现为「表不存在」）。
   ★ 冒烟已验证：`register_all_models()` / `seed_base_data()` 均抛
   `TypeError: missing 1 required positional argument`。
2. **清单存字符串模块名**，`_resolve()` 在**要跑的那一刻**才 import ——
   `alembic/env.py` 导入 wiring 时不会把各业务 seed（及其服务层 / LLM 客户端）
   拉进迁移进程；迁移只需要 ORM 元数据。
3. **`SeedStep` 的定义住 `core/bootstrap.py`**（机制层的数据类型），wiring 只提供清单
   ⇒ 方向仍是 `wiring → core`，**core 不认识组合根**。

`core → modules` 的 7 处残留，全部是 `modules.billing.models`：
`core/metering/usage_tracker.py` ×5、`core/identity/router.py` ×1、
`core/identity/models.py:186`（import 期例外）×1。

### 2.3 为什么最后 7 处**不能**用同一手法消除（本仓三处自证）

**候选方案 A：实体归位（把 `Subscription` 等搬到 `core/billing/`）** —— `StoreRecord`
第 140 轮就是这么办的。**但本仓已记录它对本例不可行**：

1. `tests/test_module_layering.py:16-21` 明确指出 `stores` 能搬的前提之一是
   **「`StoreRecord` 零 `relationship()`（不碰 1:1 的 `Base.registry` 地雷）」**；
   而 `Subscription.user ↔ User.subscription` 正是 **1:1 双向关系**
   （`modules/billing/models.py:91` 与 `core/identity/models.py` 的注册行）——
   搬过去**恰好撞在这个地雷上**。
2. `core/identity/models.py:180-186` 与 `test_core_layering.py:54-64` 记着：该 1:1 要求
   两侧类同处一个 `Base.registry`，否则 `configure_mappers()` 抛
   `InvalidRequestError: expression 'Subscription' failed to locate a name`，
   且**只在特定导入顺序下复现**（属无法用测试稳定覆盖的形态）——所以它被登记为
   **唯一显式例外**（源码里带 `# noqa: E402` 自证）。
3. `modules/billing/__init__.py` 记录了**作者的决策与判据**：按「被 ≥2 个**别的模块**
   import ⇒ 基础域」的入度判据，`billing` 的跨模块消费者只有 1 处 ⇒ 实体留 `modules/`；
   `test_module_layering.py:26-31` 进一步把它显式标为 **KERNEL（语义分层）**，
   并说明「实体住 `core/` 还是 `modules/`」用的是**另一条轴**（入度判据），两者不矛盾。

**候选方案 B：core 侧端口 + 组合根注入**（`core` 只持一个 callable 单元格，billing 注册）——
技术上可行，**但被本仓自己的门禁哲学否掉**：`test_core_internal_layering.py` 反复写明
「**把结构性依赖藏进函数体只会让本门禁看不见耦合，是自欺**」。
端口只是把同一份耦合挪到一个不可见的全局单元格里，**耦合没减、可观测性变差**，
且新增「未装配 ⇒ RuntimeError」的运行期失效面（celery worker 路径尤其危险）。

⇒ **结论**：余下 7 处是「内核读业务域实体」这一形态在当前实体归属下的**结构性代价**，
已由既有门禁 `test_core_layering.py` 完整管控（6 处被推迟到调用期，1 处显式例外且
源码自证）。**要归零，必须先做一个独立的架构决策**（见 §5 决策项 A）。

### 2.4 门禁必须跟着改（**读集**变了）—— 这是本轮最容易漏的地方

改动让两处门禁的**读集**失效，两者都是**先红后修**，这就是门禁有牙齿的证据：

| 门禁 | 失效形态 | 处置 |
|---|---|---|
| `test_core_internal_layering.py::test_function_level_edges_match_registry` | 登记表仍列着 `database → {audit, identity, stores}` 三条**已消失**的函数内边 | 删 3 条登记；实测 `函数内边 10 → 7`，`unit`/`import 期边`/`SCC`/孤立单元均未变 |
| `test_trade_schedule.py::test_bootstrap_wires_trade_seed` | 判据读 `core/bootstrap.py` 源码里的 `seed_trade_if_empty` import 名 —— 清单外移后**源码里没有这个名字了** | 改**行为判据两半**：① `wiring.SEED_STEPS` 含该目标；② `seed_base_data` **函数体内**真的调 `_resolve(...)` |

### 2.5 反向注入取证（本仓铁律：没被注入验证过的门禁 = 没有门禁）

```
① test_core_layering.py
   注入：往 core/database.py **末尾**追加 `import modules.billing.models`
   结果：恰好 tests/test_core_layering.py::test_core_has_no_import_time_reverse_import 红，
         断言点名 `core/database.py:151 -> modules.billing.models`
   回滚：绿     ⇒ INJECTION_CERTIFIED = True

② test_trade_schedule.py（两半各一次）
   注入①：删掉 wiring.SEED_STEPS 里 trade 那条          ⇒ 仅该用例红（登记半）
   注入②：让 seed_base_data 不再调 `_resolve(...)`      ⇒ 仅该用例红（执行半）

③ 全量回归
   28 个受影响测试文件（含全部门禁 + 计费 + 交易 + 认证 + 迁移一致性）= EXIT 0
```

★ **本轮踩到并已修正的一个方法论坑**：注入点若放在 `core/database.py` **文件头**，
会触发 conftest 的**循环 import** ⇒ 得到的是 pytest **collection error**（不是门禁断言）。
第一版探针因此把 `INJECTION_RED` 误判成 `False`。
⇒ 教训与既有铁律一致：**「注入本身失败」与「注入没抓到」必须分开报**，
且抓红行**不能按关键字过滤**（要数 pytest 自己的 `^FAILED ` 行）。

---

## 三、两份「前提被证伪」与三处事实更正

上一轮报告有两条 P0 的**前提不成立**，本轮实测推翻。记录下来，避免下次照着错的清单干活。

### 3.1 P0-3「`frontend/src/mock/data.ts` 是 1145 行整文件死代码（0 消费点）」——**错**

实测：`frontend/src/mock/toolExecutors.ts:191,205` 用**动态** `import('@/mock/data')`
消费了 `getBlueOceanCandidates` 与 `getMockPainPointAnalysis`；而
`blue-ocean` / `pain-points` 是**活跃工具**（`TaskConfigPanel:110,116`、`ChatPanel:61,68`、
`toolDefinitions:46`）。`check-tool-reality.cjs:734` 自己就写着
「执行器保留待接线或退役」。

⇒ **不可删**（删了打断功能）。处置：**暂缓 + 记入决策项**（§5 决策项 C）。
静态 grep「0 消费点」会漏掉**动态 import** —— 这正是本轮 3.1/3.2 两次误判的同一根因。

### 3.2 P0-6「`agent_product_research.py:1358-2646` 单方法 1289 行」——**错**

实测（AST，全文件 2646 行）：

```
最大定义 TOP 5
  2375 行  行 272-2646   class ProductResearchAgent     ← 真正的巨物是一个**类**
   131 行  行 1358-1488  _analyze_blue_ocean           ← 报告点名的「方法」只有 131 行
   111 行  行 1076-1186  _stream_via_tools
   106 行  行 2055-2160  _save_candidate
   103 行  行 873-975    resume_approval
```

⇒ 既没有 1289 行的方法，行号区间（1358-2646）也对不上。
**真实形态是 2375 行的 God Class**（约 40 个方法）。处置见 §5 决策项 B。

### 3.3 事实更正（三处）

| # | 上一轮报告的说法 | 实测 |
|---|---|---|
| 1 | `core → modules` **24 处** | **35 处**（低估 11 处）。差异集中在 `register_all_models`(17) 与 `seed_base_data`(11) 的**逐行清单**——人工数时容易按「模块」而不是按「import 语句」计。⇒ **结论：这类计数必须由探针现算** |
| 2 | 环 `amazon_sp ⇄ trade`（点名为架构缺陷） | **不是 import 期环**。import 期只有单向 `amazon_sp → trade`（`amazon_sp/data_sources/mock_source.py:35`，且走对方**门面**）；反方向 `trade → amazon_sp` 在 `trade/tasks.py:119,161` 是**函数内延迟 import**。⇒ 它**不可能**造成导入顺序故障，且两者都是 `SHARED`，`test_module_layering.py` 明确允许 `SHARED → SHARED` 顶层边 |
| 3 | `platforms/amazon`(932 行 MOCK) 是「同域双实现、疑似冗余」 | **两者都活**：`platforms/amazon/client.py`（38 KB mock）被 `modules/product_research/service.py:23` 与 `agent_product_research.py:1746` 消费；`platforms/amazon/sp_api/*` 是真实 SP-API，被 `modules/amazon_sp/data_sources/sp_api_source.py:63-69` 消费。⇒ 不是死代码，是**双通道且两派消费方分裂**（P0-5 的前提成立，但修法需要决策） |

---

## 四、复审：架构 / 模块化 / 高内聚低耦合高复用

全部数字来自 `measure.py`（AST + 行数），可复算。

### 4.1 分层与依赖方向

| 检查项 | 结果 |
|---|---|
| `ai_infra` / `platforms` 反向依赖 `modules` | ✅ 无（既有门禁在管） |
| `core → ai_infra` | ✅ **0**（本轮 A 档） |
| `core → modules` | ⚠️ **7**（35 → 7；全部指向 `modules.billing.models`，见 §2.3） |
| import 期反向依赖 | ✅ **恰好 1 处**，且是显式登记的例外 + 源码 `# noqa: E402` 自证 |
| `modules` 之间顶层跨模块边 | 17 条（**无 2 节点 import 期环**） |

### 4.2 体量分布（>800 行的文件 = 58 个）

```
按目录前缀：frontend 26 / tests 14 / modules 13 / ai_infra 2 / core 2 / platforms 1

TOP 10：
   2646  modules/product_research/agent_product_research.py   ← God Class 2375 行
   2646  frontend/.../TaskConfigPanel/configs/ReviewDeskConfig.vue
   2535  modules/trade/service.py          （单文件跨 13 个子域）
   2378  frontend/src/components/KnowledgeBase/ProductLibrary.vue
   2085  modules/skills/seed.py
   1992  modules/customer_service/agent_cs.py
   1952  tests/test_skill_gate.py
   1917  frontend/src/components/KnowledgeBase/PlatformRules.vue
   1848  modules/aigc_media/agent_aigc.py
   1802  modules/listing_generator/agent_listing.py
```

**判断**：体量问题**没有被本轮改动缓解**（本轮只动了机制与清单，没动业务大文件）。
**frontend 26 个 >800 行文件**是最集中的一块 —— 比 modules(13) 还多一倍。

### 4.3 模块完整性（23 个模块）

| 缺失 | 数量 | 清单 |
|---|---|---|
| 缺 `service.py` | 6 | `amazon_sp`、`billing`、`library`、`products`、`secretary`、`stores` |
| 缺 `router.py` | 2 | `amazon_sp`、`library` |
| 缺 `db_model.py` | 7 | `ad_analysis`、`billing`、`competitor_intel`、`library`、`listing_generator`、`secretary`、`stores` |

**判断**：与第 334 轮一致，**未变**。
★ 但要补一句上一轮没说清的：`library` / `amazon_sp` 缺 `router.py` **不是缺陷**
（前者是「只读工具包」，后者是「适配器」，它们本就没有独立 HTTP 面）；
`stores` / `billing` 缺 `db_model.py` 也不是 —— 实体已归位 `core/stores/`，billing
则按 §2.3 的判据留在 `modules/billing/models.py`。
⇒ **「缺文件」清单必须区分「本该有」与「本就没有」，否则会凭空造出重构工作量。**

### 4.4 重复实现（剥注释/字符串后计数）

| 模式 | 命中 | 文件数 |
|---|---|---|
| `def _get_router` | 7 | 7 |
| `def _dump` | 8 | 8 |
| `_current_shop_id` | 243 | 38 |
| `ContextVar(` | 16 | 9 |
| `get_data_source(` | 10 | 8 |
| `register_all_models` | 13 | 5 |

**判断**：
- `def _get_router` ×7 / `def _dump` ×8 —— **与上轮一致，模板复制仍是最明确的复用缺口**，
  且**极易收口**（同形、同职责、无跨包语义）。
- `_current_shop_id` 243 次 / 38 文件 —— 数字大但**大部分是正当消费**（读租户作用域），
  不是复制实现；上轮把它列为「×5 复制」是**误读**（那 5 个是**定义**，其余是**调用**）。
  ⇒ 收口对象应是「定义」，不是「出现次数」。
- `get_data_source(` 10 次 / 8 文件 —— 8 个消费方**分裂成两派**（§3.3 第 3 条），
  这是 P0-5 的实质。

---

## 五、结论与待拍板决策清单

### 5.1 本轮结论

1. **老板点名的「分层方向被打破」已解决 29/36（80.6%）**：
   `core → ai_infra` **归零**；`core → modules` **35 → 7**（合计 36 → 7）。
   余 7 处有**本仓三处自证**说明不能靠现有手法消除（§2.3），且已被既有门禁完整管控。
2. **保命提交与日志治理落地**，磁盘释放 ~0.95 GB，且补上了**体积轮转**与
   **进程分文件**两道根治手段（连同 `--reload-exclude` 切断自反馈）。
3. **上一轮报告的 6 条 P0 里有 2 条前提不成立**（P0-3、P0-6），另有 3 处事实需更正。
   ⇒ 根因是「人工计数 + 静态 grep」；**本轮起全部改用探针现算**。
4. 架构/模块化的**结构与上轮一致、未被恶化**；体量问题（58 个 >800 行文件）
   与模板复制（`_get_router` ×7）**仍未处理**。

### 5.2 待老板拍板（按建议优先级）

| # | 决策项 | 选项 | 我的建议 |
|---|---|---|---|
| **A** | `core → modules` 最后 7 处是否归零 | ①**保持现状**（有门禁管控 + 理由已记录）②实体归位 `core/billing/`（撞 1:1 `Base.registry` 地雷，需先拆 1:1 关系）③core 侧端口注入（耦合没减、可观测性变差，与门禁哲学冲突） | **①保持现状**；若必须归零，先做「拆 1:1 关系」这个**独立前置动作**，不要直接搬 |
| **B** | P0-6 的真实形态：2375 行 God Class `ProductResearchAgent` | ①按能力拆成多个 Agent/服务类 ②只抽「工具路由 / 流式输出 / 落库」三块 ③不动 | **②分步抽三块**（God Class 一次性拆解风险过高，且它有 HIL / 流式 / 路由多套状态机） |
| **C** | P0-3 `mock/data.ts` + `toolExecutors.ts` 的动态 import 链 | ①保留（当前）②把 `blue-ocean`/`pain-points` 两个执行器**接到真数据源**后再删 mock ③删工具 | 先做 ②的**接线评估**（删工具会砍掉两个活跃能力） |
| **D** | P0-4 拆 `ReviewDeskConfig.vue`（2646 行：template 884 / **script 1246** / style 514） | ①抽 composable（把 1246 行 script 按「筛选 / 列表 / 详情 / 批量操作」切成 4~5 个）②只抽 template 子组件 ③不动 | **①**，但需先建**前端行为基线探针**（本仓已有 `frontend/scripts/cdp-*.mjs` 范式），否则拆完无法证明行为未变 |
| **E** | P0-5 统一亚马逊数据源真源 | ①全部改走 `get_data_source()` 工厂 ②保留 mock 但**显式标注为演示数据** ③不动 | **②优先**（①会让无 SP-API 凭据时演示直接崩——工厂对 `prefer="sp_api"` 是**抛错不回退**；②符合本仓「不拿假数据冒充实测」的既有原则） |

### 5.3 复算方式（逐条可验证）

```bash
# core 反向依赖（A 档 + B 档 + C/D 档全口径）
python .workbuddy/probes/r335-p0-7/scan_core_reverse_deps.py

# 反向注入取证（会临时改文件并自动还原）
python .workbuddy/probes/r335-p0-7/verify_injection.py
python .workbuddy/probes/r335-p0-7/verify_trade_gate.py

# 复审度量（最大文件 / 模块完整性 / 重复实现 / core 图）
python .workbuddy/probes/r335-p0-8/measure.py
python .workbuddy/probes/r335-p0-7/recount_core_graph.py

# 门禁（判绿用退出码）
cd backend && python -m pytest tests/test_core_layering.py tests/test_core_internal_layering.py \
  tests/test_module_layering.py tests/test_infra_layering.py \
  tests/test_schema_parity.py tests/test_trade_schedule.py -q
```

---

*报告生成：第 335 轮。上一轮：`docs/round-334-architecture-review.md`。*
