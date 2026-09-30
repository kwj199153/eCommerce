# 「Service + 两套包装 + 工具注册表」架构对账（第 202 轮）

> 触发问题（老板原话）：
> `内部 Service 函数是原始业务实现；写两套独立包装：①FastAPI 路由（前端 HTTP）、②Tool 包装（给 Agent）；`
> `Tool 包装在模块插件启动时主动注册进 core 的 ToolRegistry；API 路由只挂载，不进 core 工具注册表。`
> `目前是这么做的吗 还是有更好的方式？`
>
> 口径：**只审计不改代码**。所有读数取自 AST / 源码锚点，可复算。
> 探针：`.workbuddy/probes/r202_surface.py` · `r202_wiring.py` · `r202c_router.py` · `r202d_router.py`

---

## 0. 一句话结论

**「Service 是唯一实现」「两套包装」「路由不进注册表」三条成立；
「注册进 core 的 ToolRegistry」不成立 —— 本仓刻意不做运行期注册，
改用「静态容器 + 显式传参 + 门禁对账」拿到了同样的保证，且零运行期耦合。**

---

## 1. 四句描述逐条对账

| 老板的描述 | 实测 | 判 |
|---|---|---|
| 内部 Service 是原始业务实现 | 8 个 Agent 模块 **76 / 82** 个 handler 委派 service（其余 6 个见 §4.2） | ✅ 基本成立 |
| 写两套独立包装（router / tools） | 有 Agent 的 8 个模块里 **7 个**同时有 router + tools；另 13 个模块只有 router | ✅ 成立 |
| Tool 包装在**模块插件启动时**注册进 **core 的 ToolRegistry** | `core/` 44 个文件里没有任何 tools/registry 模块；全仓 `ToolRegistry` / `register_tool` **零命中**；`core/bootstrap.py` 只做**数据 seed**，与工具无关 | ❌ **不成立** |
| API 路由只挂载，不进工具注册表 | 25 个 `include_router` 全在 `main.py`；与工具目录**零交集** | ✅ 成立 |

---

## 2. 真实形态

```
service.py（原始业务实现）
   ├── ① router.py ──→ main.py include_router ×25 ──→ 前端 HTTP
   └── ② tools.py 容器 ──→ 装配点 ×5 ──→ BaseAgent.__init__ ──→ LLM

（并列）TOOL_CATALOG 手写表 ──→ GET /api/v1/tools ──→ 技能勾选
```

### 2.1 读数

| 项 | 数量 | 真源 |
|---|---|---|
| 模块 | **21**（7 个业务 Agent + 1 orchestrator + 13 个纯 CRUD） | `backend/modules/*/` |
| 端点 | **209** | 各 `router.py` 的 `APIRouter(prefix=…)` + 装饰器 |
| 工具容器所在模块 | **8** | `modules/*/tools*.py` |
| **装配点** | **5** | `BaseAgent(tools=…)` ×4 + `super().__init__(tools=…)` ×1 |
| **真接线工具** | **36** | 与 `TOOL_CATALOG` **集合相等**（门禁钉住） |
| **悬空工具** | **19** | 全仓无消费点 |
| 容器项合计 | 55 = 装配 36 + 悬空 19 | |

### 2.2 五个装配点（「谁把工具交到 LLM 手里」的答案）

| 模块 | 位置 | 表达式 |
|---|---|---|
| 竞品情报员 | `competitor_intel/agent_competitor.py:251` | `BaseAgent(tools=competitor_intel_tools)` |
| Listing 优化师 | `listing_generator/agent_listing.py:341` | `BaseAgent(tools=listing_tools)` |
| 选品分析师 | `product_research/agent_product_research.py:572` | `BaseAgent(tools=product_research_tools)` |
| 运营复盘师 | `review_analyst/agent.py:229` | `BaseAgent(tools=review_analyst_tools)` |
| 店秘书 | `secretary/agent.py:101` | `super().__init__(tools=navigation_tools + subscription_tools + product_tools + shop_tools)` |

### 2.3 唯一的运行期「注册」漏斗

`ai_infra/base_agent.py:399`：

```python
self.tools = self._wrap_hitl_tools(
    (list(tools) if tools else []) + _planner + _skill_tools
)
```

= 子类传入的 `tools=` **＋** 规划工具 **＋** `build_skill_tools()`（恒 1 个 `load_skill`）
→ 合并 → HITL 包装。**内容仍由子类传入，不从注册表取。**

### 2.4 已存在的三套对账门禁

| 门禁 | 判据 |
|---|---|
| `tests/test_tool_catalog.py` | 判据 A：`TOOL_CATALOG` ⇔ **真实装配点**工具名**集合相等**（双向，非 ⊆）；判据 E：全仓每个 `tools=` 实参表达式必须已登记；防真空自检（必须解析出 36 个） |
| `tests/test_tool_registry_guard.py` | 工具名跨注册表全局唯一 · desc 交叉引用可解析 · **悬空棘轮**（只许减少）· 能力承诺与实现一致 |
| `tests/test_module_layering.py` | `KERNEL / SHARED / PLUGIN` 分层；禁 `PLUGIN → PLUGIN` 顶层 import、`KERNEL → modules` |

---

## 3. 为什么本仓**刻意不**做 core ToolRegistry

1. **工厂型工具拿不到**：`build_product_tools(shop_id)` / `build_shop_tools()` 是**运行期**构造，
   AST 与静态注册表都看不见它的产出物（`tools_catalog.py` docstring 明确记了这条，
   并解释「为什么必须运行时取而不能靠 AST 扫」）。
2. **分层门禁不允许**：`test_module_layering.py` 禁 `PLUGIN → PLUGIN` 顶层 import 与
   `KERNEL → modules` ⇒ 注册动作只能落在「插件 import 副作用」里 ⇒ 会复现本仓**已经踩过**的
   「装配顺序敏感」坑（`build_skill_tools()` 在读取器未注册时返回 `[]`，
   见 `tests/test_skill_injection.py` 的文件头）。
3. **受众不同**：工具的 `description` 写给**模型**（「当用户想算利润时使用」），
   目录表写给**人**（租户在勾选界面上判断「我要不要这个工具」）⇒ 自动派生只会得到一个模型腔的句子。

⇒ **要「单一真源」未必要注册表**。要「新模块接入零遗漏」，
本仓现成范式是把 `AGENT_CATALOG`（手写表 + 下发端点 + 门禁）扩写一格，而不是新建 core 注册表。

---

## 4. 实测出的真缺口（3 处）

### 4.1 ★★ 棘轮额度虚高 6（白名单陈旧项，会让棘轮失效）

`tests/test_tool_registry_guard.py` 的 `KNOWN_ORPHAN_REGISTRIES` 里仍有

```
modules/review_analyst/tools.py::review_analyst_tools
```

但它**早已装配**（`review_analyst/agent.py:229` 明确 `BaseAgent(tools=review_analyst_tools)`）。

⇒ 实测悬空只有 **19**，而 `ORPHAN_TOOL_BUDGET = 25`
⇒ **还能悄悄新增 6 个悬空工具而不转红**，「只许减少」的棘轮语义被架空。
该测试只有 `new_orphans` 的**正向**断言，缺「登记项必须真的悬空」的**反向**断言。

### 4.2 ★★ 「能力清单硬编码在路由层」3 处，只有 1 处有门禁

| 位置 | 行数 | 说明 |
|---|---|---|
| `listing_generator/router.py::get_capabilities` | **61 行** | 手写能力清单 |
| `product_research/router.py::get_capabilities` | **75 行** | 手写能力清单 —— 第 200 轮**已建门禁**（`features[].endpoint` ⇔ 路由表） |
| `aigc_media/router.py::get_tools` | **76 行** | 手写**前端功能卡**表（`id`/`name`/`endpoint`/`mode`） |

对照：`ad_analysis` 的 `get_capabilities` 只有 **4 行**（真的调 `AdAnalysisService.get_capabilities`）。
**同一个语义，本仓有三种做法。**

### 4.3 ★★ 第 5 套「工具」命名空间

`GET /aigc/tools` 返回的是**前端功能卡**（带 `endpoint` + `mode:"form"`），
与 LLM 工具**同名叫 tools、语义完全无关**。

本仓「工具」共有 **5 套命名空间**：

| # | 命名空间 | 位置 | 消费者 |
|---|---|---|---|
| 1 | LLM 工具（`StructuredTool`） | `modules/*/tools*.py` 容器 | `bind_tools` → 模型 |
| 2 | `TOOL_CATALOG` | `modules/skills/tools_catalog.py`（手写） | `GET /api/v1/tools` → 租户勾选 |
| 3 | `skills.tools` | DB 列 | `render_skill_tools()` → `load_skill` 返回正文 |
| 4 | `REGISTRY_FILES` + 棘轮 | `tests/test_tool_registry_guard.py` | 审计 |
| 5 | `GET /aigc/tools` | `aigc_media/router.py` | 前端功能卡面板 |

⇒ 盘「工具有几个」之前必须先问**是哪一套**。

### 4.4 附：router 委派 service 的逐模块读数

| 模块 | 委派 / 总数 | 未委派的那些 |
|---|---|---|
| customer_service | **11 / 11** | — |
| competitor_intel | **14 / 14** | — |
| aigc_media | 16 / 18 | `get_tools`(76 行硬编码)、`health_check`(只读 agent 属性) |
| listing_generator | 10 / 11 | `get_capabilities`(61 行硬编码) |
| product_research | 7 / 8 | `get_capabilities`(75 行硬编码) |
| ad_analysis | 9 / 11 | `quick_diagnose` / `quick_anomalies`（各 7 行） |
| review_analyst | 6 / 7 | `chat`(33 行，走 `agent.invoke` —— 编排入口，合理) |
| secretary | 0 / 2 | 本模块**没有 service 层**，router 直连 agent 的 `route` / `current_plan`（orchestrator，设计如此） |

合计 **76 / 82**。即「router 是薄包装」基本成立，例外集中在
**能力清单类端点**（§4.2）与**编排入口**（合理）。

---

## 5. 建议分档（待拍板）

| 档 | 内容 | 代价 | 收益 |
|---|---|---|---|
| **档 1**（推荐，零运行期耦合） | ① 棘轮收紧：删 `review_analyst_tools` 陈旧登记、`ORPHAN_TOOL_BUDGET` 25 → 19，并加反向断言「登记项必须真的悬空」；② 把第 200 轮那条 `features ⇔ 路由表` 门禁推广到 `listing_generator` / `aigc_media` 的同类硬编码端点 | 小（纯测试侧） | 棘轮恢复有效；能力清单不再能悄悄漂移 |
| **档 2**（把「唯一实现」补到位） | 把 `get_capabilities` 三处收口到各模块 `service`，router 只转发 | 中（3 个模块 + 门禁同步） | 与 §0 那条约定真正一致 |
| **档 3**（才需要 core 注册表） | 新建 core 注册表 + 启动期自动注册 | **大**，且要付 §3 的三条代价 | 仅当要求「新增模块/Agent 时**不改任何中心文件**就自动出现在 UI 并可被技能勾选」时才值得 |
| **不推荐** | 让 `ad_analysis` / `aigc_media` / `customer_service` 的 19 个悬空工具自动进目录表 | — | 会让租户勾到**调不起来**的工具，比不给勾更糟 |

> 注：**「有 router 无 tools」不是缺口** —— 13 个纯 CRUD 模块没有 Agent，
> 本来就不该有工具，别计入「未覆盖」。

---

## 6. 本轮动作

- 新增探针 4 个（`r202_surface` / `r202_wiring` / `r202c_router` / `r202d_router`）+ 输出落盘；
- 判据落 `_pending/第202轮.md`（7 条，含 `from . import X` 的 AST 坑）；
- skill `agent-capability-surface-audit` 增「注册表三个所指」整节 + 铁律 11–13；
- **未改任何生产代码**（问题问的是现状与方案，等拍板）。
