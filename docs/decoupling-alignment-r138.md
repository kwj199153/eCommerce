# 解耦长文 vs 项目实况：对账与建议

> 第 138 轮 · 2026-09-18
> 输入：老板贴出的《前后端解耦 / 后端与数据库解耦 / 内核+插件化》长文（第三次）
> 方法：4 个 AST 探针（`.workbuddy/probes/r138_recon*.py`），全部走 AST / 文件事实，**无「源码字符串包含」判据**
> 数字口径：见各节「证据」；文件行尾 CRLF/LF 混存已归一化后再统计

---

## 0. 一句话结论

长文的三层解耦，本项目现状是：

| 层 | 状态 |
|---|---|
| 前后端解耦 | ✅ **基本达成**（独立部署 + 自建 Repository 等价层），缺「OpenAPI 自动生成 SDK」这一档 |
| 后端 ↔ 数据库解耦 | ⚠️ **只做到第 1 档（ORM）**，Repository 模式 0 落地；但**不建议补内存仓库** |
| 内核 + 插件 | ⚠️ **物理分层做了，边界从未定义**：`core/` 独立且已加门禁，但**内核实体错位在 `modules/` 下**，横向耦合无约束 |

实测出 **2 处真缺陷**（P0，成本各约 2–3 行）、**2 项结构性收敛**（P1）、**2 项对齐动作**（P2）。
另有 **6 条长文建议判定为本项目不适用**（附理由，含长文自评）。

---

## 1. 三层对账（总表）

| 长文的判据 | 项目实测 | 判定 |
|---|---|---|
| 后端只提供 API、输出 JSON、不渲染页面 | FastAPI，**217 个端点**分布在 23 个文件；无模板渲染 | ✅ |
| 前端/后端独立仓库、独立部署 | 同仓 monorepo（`frontend/` + `backend/`），但各有 Dockerfile + `nginx.conf` + `docker-compose.yml` ⇒ **独立部署已做** | ✅ |
| OpenAPI 作为双方契约 | 无 openapi.json/swagger.json 导出物；`main.py:97` `docs_url="/docs" if config.debug else None` | ⚠️ 运行时自动有，**但未被消费** |
| 前端基于 OpenAPI 生成 TS 类型 | 无 orval / openapi-typescript / openapi-fetch；0 个生成产物 | ❌ 未做 |
| 前端 Repository 层（业务页面不碰原始 API） | `api/request.ts` 361 行 = axios 实例 + 请求拦截器（注入 shopId）+ 响应拦截器（401 刷新 / 身份判定 / 路由跳转）+ 泛型 `get/post/put/patch/del` | ✅ **已自建** |
| ORM 层解耦 | SQLAlchemy 2.0（`Mapped` / `mapped_column`） | ✅ |
| Repository 模式：业务不碰 ORM、只调仓储接口 | **0 目录 / 0 类 / 0 base_repo**；`modules/` 非 router 文件 **56 处 `.execute()`**（16 文件）；**36 个文件**在 modules/core 里 import SQLAlchemy | ❌ 未落地 |
| 仓储接口只定义业务语义（不叫 `insert_raw`） | 函数名确为业务语义（`create_faq` / `list_knowledge_bases` / `candidate_exists`） | ✅ 这条**已达成** |
| 内核禁止 import 插件（核心红线） | 第 137 轮已加 `test_core_layering.py`：core 不得在 **import 期** import `modules.*`，唯一例外带 `# noqa: E402` 自证 | ✅ |
| 插件之间互相独立 | `modules/` 之间 **13 条直接 import 边，其中 11 条在模块顶层** | ⚠️ 见 §3.3 |
| 内核统一处理租户隔离，插件不用重复写 | **72 处手写 `== shop_id`** 散在 12 个文件；仅 1 个模块（knowledge_base）自建 `_scoped`；**无集中式 scope 工具** | ❌ 相反 |
| 事件总线（内核↔插件靠事件通信） | `EventBus` / `event_bus` / 事件名字符串 **0 命中**；靠直接函数调用 | ⏸ 长文自评为**阶段 2** |
| 前端插件化（plugins/ + plugin-loader） | `frontend/src/` 无 `plugins/`、无 plugin-loader | ⏸ 长文自评为**阶段 3** |
| 数据网关 / BFF / GraphQL / CQRS | 全无（2 处 grep 命中经核实为误报） | ❌ 不适用 |

---

## 2. 后端 ↔ 数据库解耦：只做到第 1 档

### 2.1 实测

- **ORM 层** ✅ 已在用，且是 SQLAlchemy 2.0 现代写法。
- **Repository 模式** ❌ 完全未落地：目录名/文件名/类名含 `repo|repository` 的搜索结果均为 **0**。
- **业务层直连 Session** ❌：`knowledge_base/service.py`（481 行）与 `platform_rules/service.py`（322 行）的形态是「模块级 `async def xxx(..., shop_id)` + 自建 `async_session_factory()` + 直接 `select()`」。长文明确写的「业务 service 层禁止直接导入 SQLAlchemy Session」——**当前完全违反**。

### 2.2 但：不建议引入「内存 Mock 仓库」

长文把「单元测试可换成内存仓库，不用启动真实数据库」列为 Repository 的最大好处。

**本项目的测试策略与这条直接冲突**：并发用例是**真跑 8 并发断言精确累加**（`test_billing_metering.py`）、门禁**真跑拒绝路径**、端到端探针关子进程。引入内存仓库会让「测试通过」不再等于「真库能跑」——**假绿风险换来的便利，在本项目是负收益**。

⇒ 判定：Repository 的**这半边不采用**。

### 2.3 真正有价值的是「作用域收敛」（见 §7 P1-3）

---

## 3. 内核 + 插件：物理分层做了，边界没定

### 3.1 已完成的部分

- `core/` 已是独立物理层：`auth` / `identity` / `metering` / `middleware` / `observability` / `security` / `storage` / `tenant`（8 个子包 + 若干模块）。
- 第 137 轮新增 `backend/tests/test_core_layering.py`（4 用例）：**core 不得在 import 期 import `modules.*`**，用**集合相等**断言例外表（多一处、少一处都红），并带反向注入自检。唯一例外 `core/identity/models.py:186`（1:1 双向 relationship 注册），在**源码**带 `# noqa: E402` 自证。

### 3.2 发现 A：内核实体错位 —— `stores` 逻辑上是内核，却住在 `modules/` 下

四条**互相独立**的事实同时指向这一点：

1. **`StoreRecord` 是全库唯一带 `tenant_id + account_id + owner_id` 三件套的表**（其余 36 个 model 只有 shop_id 或经 FK 传递）。
2. **7 个模块在顶层 import 它**：`assets` / `candidates` / `knowledge_base` / `monitors` / `platform_rules` / `products` 的 `seed.py` + `secretary/shop_tools.py`。这是全仓**入度最高**的模块。
3. 它持有 `SHOP_ORDER_BY` —— `db_model.py:21` 注释自称「**★ 店铺「序号」排序真源（唯一）—— 全项目禁止各自写 order_by**」。
4. `stores/db_model.py:149` 自己 import `core.identity.account_models` 做外键目标表的元数据注册，注释明确写「方向也正确：modules → core 是本项目允许的依赖方向」。

**同类**：`modules/billing`（订阅 / 计费 / 配额）。长文把「租户管理：配额、订阅套餐、计费、额度」明确列进**平台内核**。

⇒ **本项目的内核实际上是 {identity, auth, tenant, stores, billing, metering}，但只有前 4 个物理在 `core/`。**

### 3.3 发现 B：横向耦合 13 条边 —— 但「边数 ≠ 问题数」

```
assets       -> stores           1 处  顶层 1
candidates   -> products         2 处  顶层 1
candidates   -> stores           1 处  顶层 1
knowledge_base -> stores         1 处  顶层 1
monitors     -> stores           1 处  顶层 1
platform_rules -> stores         1 处  顶层 1
products     -> stores           1 处  顶层 1
secretary    -> stores           1 处  顶层 1
secretary    -> billing          1 处  顶层 1
secretary    -> products         1 处  顶层 1
secretary    -> conversation     1 处  顶层 0
review_analyst -> amazon_sp      1 处  顶层 1
product_research -> candidates   1 处  顶层 0
```

**拆性质**：

| 类别 | 边数 | 性质 |
|---|---|---|
| 依赖 `stores` / `billing` | **8** | ✗ **不是插件互耦** —— 是 §3.2 的**内核错位** |
| 跨域取模型（`candidates→products.SpuRecord`、`secretary→products.Spu/SkuRecord`） | 2 | ⚠️ 同域关联 vs 跨域共享，边界未定义 |
| 跨域调服务（`secretary→conversation.service`、`product_research→candidates.service`、`secretary→billing`） | 3 | 函数内，性质较轻 |
| **跨模块 import 私有函数** | **1** | ✗✗ **真坏味道**（见 §6 P0-2） |
| 顶层 import 具体实现绕过工厂 | 1 | ✗✗ **真缺陷**（见 §6 P0-1） |

⇒ 结论：13 条里**只有 2 条是真问题**，其余是「内核边界未定义」的症状。**先划边界，才谈隔离** —— 这与长文自己的核心洞察一致。

### 3.4 发现 C / D：EventBus 与前端插件化

- `EventBus` / `event_bus` / `dispatch_event` / 事件名字符串（`tenant.created` 式）**0 命中**。
- `frontend/src/` 无 `plugins/`、无 plugin-loader。

长文自己把事件总线放**阶段 2**、前端动态插件放**阶段 3**，并明确「阶段 1：**现阶段可以硬加载插件**，不用做动态插件启停，先把边界划清楚」。

⇒ **现在不做是对的**。项目正处在长文定义的阶段 1。

---

## 4. 前后端解耦

### 4.1 已完成

- 后端只输出 JSON（217 端点 / 23 文件）。
- 独立部署：`frontend/Dockerfile` + `frontend/nginx.conf` + `backend/Dockerfile` + 根 `docker-compose.yml`。
- **前端已有自建 Repository 等价层**：`api/request.ts`（361 行）—— axios 实例 + 请求拦截器（`getShopId()` 注入）+ 响应拦截器（401 → `refreshOnce()` / 身份判定 `requiresIdentity` / 路由跳转）+ 泛型 `get/post/put/patch/del`。
- 前端已有 **6 条自建 AST 门禁**挂在 `npm run build`（`check-session-registry` / `check-auth-refresh-guard` / `check-auth-vault` / `check-tool-reality` / `check-tool-adapters` / `check-hitl-approval`），零新依赖。

### 4.2 缺口

- **无 OpenAPI 生成 SDK**：`package.json` 无 orval / openapi-typescript / openapi-fetch，0 个生成产物。
- 20 个 `api/*.ts` 文件的**路径是手写字符串**（`get('/spus')`），类型来自**前端 store**（`import type { Spu } from '@/stores/productLibrary'`）而**不是后端 schema** ⇒ 后端改接口，前端**不会**报红。
- 仓库内无契约导出物，`main.py` / `scripts/` 也无 openapi 导出逻辑。

⇒ 判定：**中成本、中高收益**（引入依赖 + 重构 20 个 api 文件 + 生成物入库）。但排在跨轮遗留项（vite 5→8 major、xlsx→exceljs）之后。

---

## 5. 归属链复核：已闭合（修正第一轮的假警报）

第一轮粗扫报「12/37 个 model 缺租户字段」。第二轮把**外键传递**计入归属链后**修正**：

| 类别 | 数量 | 说明 |
|---|---|---|
| **自带归属字段** | **25** | `account_id` / `owner_id` / `shop_id` / `user_id` / `tenant_id` |
| **经 FK 传递归属** | **9** | `amazon_sp` 的 **8 张表全部** `store_id → stores_store.account_id`；`skus.spu_id → spus.shop_id` |
| **全局表（合理无归属）** | **3** | `users`（身份根）、`subscription_plans`（套餐字典）、`conversation_messages`（经 `conversation_id` 间接） |

⇒ **归属链无缺口**。第一轮的「12 个缺口」是我的扫描器未把 FK 计入归属链造成的**假警报**。

### 会话消息隔离（复核确认已收口）

`conversation/service.py` 头部有一段 P0-1（2026-09-18）的详尽说明，实测形态与说明一致：

- 归属判定**只有一处**：`can_access_conversation` / `get_owned_conversation`，其余函数都从它进；
- `user` 是**首参必填** ⇒ 签名即门禁（忘了判权写不出可运行调用点）；
- `_load_history` 私有且**刻意不导出**，注释写明「只有已授权调用方准用」；
- 「不存在」与「不属于你」共用同一文案 `NO_SESSION_DETAIL = "会话不存在或无权访问"`，且**不回显**传入 ID。

⇒ 无缺口。唯一可加强项：`history_of(conv)` 这个「不再判一次」的变体，安全性依赖调用方自律（只是约定），可考虑补 AST 门禁。

---

## 6. 两处真缺陷（P0）

### P0-1 ★ `review_analyst` 硬绑 Mock 数据源，绕过已建成的抽象层

四个事实**同时成立**：

1. **抽象层齐全**：`amazon_sp/data_sources/base.py`（132 行）= `AmazonDataSource(ABC)`，7 个 `@abstractmethod fetch_*`。
2. **工厂齐全**：`data_sources/__init__.py` 的 `get_data_source(prefer="auto"|"sp_api"|"mock")` —— auto 档「有 SP-API 凭据则用真实源，否则回退 Mock **并打 warning**」；`sp_api` 档凭据缺失时**抛 RuntimeError**。
3. **真实实现存在**：`sp_api_source.py`（539 行）。
4. **但消费端硬绑**：

```python
# review_analyst/service.py
L15  from modules.amazon_sp.data_sources.mock_source import MockAmazonDataSource
L25  _source = MockAmazonDataSource(seed=42)      # ← 模块级单例
```

12 处调用全部走这个单例（L70-72 / 105-106 / 146 / 203-205 / 258 / 294-295）。

⇒ **语义**：评价分析**永远**跑假数据 —— 即使配置了真实 SP-API 凭据；且因为是**模块级单例**，连 `prefer` 都不可配、无法按店铺区分。
⇒ 与本项目已确立的判据「**降级路径禁用全 0 兜底**（恒 0 = 假数据冒充实测）」**同源**。
⇒ `review_analyst/schemas.py` 另有 1 处 mock 类型引用。

**改动点**：2 个文件、约 3 行（import 改工厂 + 单例改按需取源）。

### P0-2 跨模块 import 私有函数

```python
# candidates/router.py:217
from modules.products.router import _spu_to_dict as _product_to_dict
```

`_spu_to_dict` 定义在 `products/router.py:38`。全仓**跨包 import 下划线私有符号仅此 1 处**。
⇒ 它事实上已是公共 API，但名字说「私有」——契约与命名不一致，且改名/重构时没有保护。

**改动点**：2 个文件、约 2 行。

---

## 7. 建议清单

### P0 —— 立即做（真缺陷，成本极小）

| # | 改动 | 文件数 | 规模 | 配套门禁 |
|---|---|---|---|---|
| 1 | `review_analyst` 改走 `get_data_source()` | 2 | ~3 行 | **AST 门禁**：非 `data_sources/` 目录禁止顶层 import `mock_source` |
| 2 | `_spu_to_dict` 提升为公开（或在 products 加公开别名） | 2 | ~2 行 | **AST 门禁**：跨包不得 import 下划线符号（当前违规 1 处） |

两条门禁都是**代码形态**门禁（不是人工名单），可仿第 137 轮 `test_core_layering.py` 的写法，并配反向注入验证。

### P1 —— 结构性收敛（中成本，高收益）

| # | 改动 | 说明 |
|---|---|---|
| 3 | **收敛「数据作用域」为唯一真源** | 现状：**72 处手写 `== shop_id`** 散在 12 个文件，仅 `knowledge_base/service.py::_scoped` 一个自建封装，**无集中工具**。这一项**同时**解决长文的「Repository 模式」与「内核统一处理租户隔离」两条。⚠️ **只收敛 scope，不引入内存仓库**（见 §2.2） |
| 4 | **显式声明「内核模块清单」+ 门禁** | 把 `stores` / `billing` 连同已在 `core/` 的 identity/auth/tenant/metering 标为内核（**物理不动**），加门禁「**插件之间不得顶层互相 import，只能依赖内核模块**」。这是第 137 轮 core 门禁的**自然延伸**，成本低、立刻可钉 |

**推荐顺序**：先做 1、2（今天可完），再议 3、4。

> 关于 `stores` 是否物理搬迁到 `core/`：**不建议现在搬**。搬 `models` 跨界会牵动 7 个顶层 import + Alembic 历史 + 1:1 relationship 的 `Base.registry`（第 137 轮已踩过：搬 models 跨界会让 1:1 relationship 崩，且自检必须分进程）。**用清单 + 门禁表达边界，比搬家便宜得多。**

### P2 —— 对齐动作（小成本）

| # | 改动 |
|---|---|
| 5 | `tenant_id` 注释澄清（见 §9-3）—— 1 行 |
| 6 | 前端 OpenAPI 生成 SDK（orval）—— 判为**中成本中高收益，排跨轮遗留项之后** |

---

## 8. 判定「不适用」的长文建议（7 条）

| 长文建议 | 判定 | 理由 |
|---|---|---|
| BFF 层（Backend for Frontend） | ❌ 不适用 | 本项目无「一个页面聚合多个后端服务」的需求 |
| GraphQL + Apollo Client | ❌ 不适用 | 217 个 REST 端点已足够；改造成本极高、收益不明 |
| CQRS / 事件溯源 | ❌ 不适用 | 原型阶段。**长文自评**「你的 SaaS 原型阶段没必要上」 |
| 独立数据网关（Hasura / PostgREST） | ❌ 不适用 | **长文自评**「小 SaaS 项目一般不推荐，过重」 |
| 表前缀（`cross_*`） | ❌ 不适用 | 前缀是为「多插件表共存」服务的；当前只有一套业务，按域命名（`spus`/`candidates`/`amazon_*`）更清晰 |
| EventBus 事件总线 | ⏸ 暂缓 | **长文自评**属阶段 2。项目处阶段 1，长文明确认可「现阶段可以硬加载插件」 |
| 前端插件动态加载 | ⏸ 暂缓 | **长文自评**属阶段 3 |
| Repository 的「内存 Mock 仓库」 | ❌ 不采用 | 与端到端真跑 PG 的测试策略冲突（见 §2.2） |

---

## 9. 三处修正（诚实边界）

1. **「前端只有接口约定 + 裸写 axios」⇒ 修正**：`api/request.ts` 已是**自建 Repository 等价层**（拦截器 + 泛型封装 + shopId 注入 + 401 刷新），缺的只是 OpenAPI 类型生成这一档。
2. **「12/37 model 缺租户字段」⇒ 修正为假警报**：把 FK 传递计入归属链后，**归属链无缺口**（25 自带 + 9 经 FK + 3 全局）。
3. **`tenant_id` 那条约注释承诺「不参与任何判定、新代码不要再读它」⇒ 实测为真、不是假门禁**：非测试代码 5 处引用（1 处在 Alembic baseline，4 处在 `stores/router.py`：L82 写入 / L118 读出 / L155 搬运），AST 确认**全部不参与比较或布尔判定**。只是「不要再读它」的措辞与「`to_dict` 往返必须原样带出」相冲突 ⇒ 属**措辞过头**，非缺陷。
4. **本轮新发现（上一轮完全没查的维度）**：Repository 模式 0 落地、EventBus 0 存在、`modules/` 横向耦合 13 条边、`review_analyst` 硬绑 Mock、72 处手写作用域过滤。

---

## 10. 侦查方法（可复现）

| 探针 | 覆盖 |
|---|---|
| `.workbuddy/probes/r138_recon.py` | A Repository / B EventBus / C 横向矩阵 / D 模型字段 / E 前端 / F 契约 / G BFF |
| `.workbuddy/probes/r138_recon2.py` | C 深化（具体符号）/ D 修正（FK 归属链）/ A 样本 / E `request.ts` / F OpenAPI / B 误报核实 |
| `.workbuddy/probes/r138_recon3.py` | 作用域实现份数 / `tenant_id` 残留 / 会话消息隔离 / mock 顶层 import / 私有符号跨包 |
| `.workbuddy/probes/r138_recon4.py` | `tenant_id` 4 处语义（AST 判 Compare/BoolOp）/ 会话调用链 / 数据源工厂 vs 消费端 |

输出：同级 `r138_recon*.txt`。全部走 **AST / 文件事实**，无「源码字符串包含」判据。
