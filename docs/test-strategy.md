# 改动分级测试策略（P0）—— 不再每次跑全量

> 起因：老板问「改一个功能就要跑全量测试，是用例太多了吗？为什么每次测很久？」
> 结论：**不是用例太多，是「范围没分级」+「测试里真调了 LLM」**。两者已分别修掉（后者见 §五）。
> 本文只解决第一件事：**每次改动该跑多少测试，由改动位置决定，不靠人记。**

---

## 一、一句话规则

| 改了什么 | 跑什么 | 实测耗时 |
|---|---|---|
| 单个业务模块内部（`modules/<x>/`） | 只跑 `test_<x>.py`（或补丁表登记的几支） | **5～10s** |
| 前端任意文件 | `vue-tsc` + 两个自检脚本，**不跑 pytest** | 约 30～60s |
| 契约/基础设施层（见 §三） | **全量**（490 项） | **约 78s** |
| **拿不准 / 未命中任何测试** | **全量**（脚本自动升级） | 约 78s |

**铁律：漏跑的代价远大于多跑 1 分钟。** 任何不确定 ⇒ 升级全量。

---

## 二、工具：`backend/scripts/pick_tests.py`

不需要人记规则，跑一条命令让它判：

```bash
cd backend

# ① 日常：看「相对上次提交」改了什么 → 自动定范围
"D:/work/anaconda/anaconda3/envs/reactAgents/python.exe" scripts/pick_tests.py --base HEAD

# ② 选出后直接跑
"...python.exe" scripts/pick_tests.py --base HEAD --run

# ③ 只想知道改了哪些文件
"...python.exe" scripts/pick_tests.py --base HEAD --paths

# ④ 只看已 git add 的
"...python.exe" scripts/pick_tests.py --staged

# ⑤ 手工指定（脱离 git）
"...python.exe" scripts/pick_tests.py backend/modules/secretary/shop_tools.py
```

> ⚠️ **不要不带参数裸跑。** 不带参数 = 读整个工作区 diff。本项目曾累积 **177 个跨轮次未提交文件** → 必然判全量、等于没用。
> **养成习惯：改完一批就 commit，或用 `--base HEAD` 只看增量。**

判定输出示例（三个分支）：

```
检测到 1 个改动文件
⇒ 判定：**定向** —— 2 个测试文件
  - test_secretary_agent.py  ← backend/modules/secretary/shop_tools.py
  - test_secretary_intent_shortcut.py  ← backend/modules/secretary/shop_tools.py

检测到 1 个改动文件
⇒ 判定：**全量**（backend/ai_infra/base_agent.py 属于契约/基础设施层（backend/ai_infra/））

检测到 1 个改动文件
⇒ 判定：**全量**（未命中任何专属测试，保守升级）
```

---

## 三、三级分类（脚本背后的规则）

### L1 定向 —— 只在单个业务模块内改
**触发**：`backend/modules/<名>/*` 且该模块有专属测试
**映射原则**：按**目录/模块名同构**（`modules/secretary/` → `tests/test_secretary.py`），**不猜语义**。
**耗时**：5～10s（实测 secretary 4.8s / knowledge_base 5.2s）

命名对不上时，在脚本的 `EXTRA_MAP` 里**显式登记**，目前 7 条：

| 模块 | 对应测试 |
|---|---|
| `secretary` | `test_secretary_agent.py`, `test_secretary_intent_shortcut.py` |
| `product_research` | `test_product_research_candidate_flow.py`, `..._blue_ocean.py`, `..._intent_routing.py` |
| `user_subscription` | `test_billing_endpoints.py`, `test_billing_metering.py` |
| `stores` | `test_stores.py`, `test_seed_shop_ids.py` |
| `aigc_media` | `test_stream_sse.py` |
| `listing_generator` | `test_stream_sse.py`, `test_auth_and_tenant.py` |
| `voice_clone` | `test_voice_clone_isolation.py` |

### L2 契约层 —— 碰了前后端接口 / 动作契约
**触发**：`backend/modules/*/router.py`、`schemas.py`、`backend/platforms/`、前端 `src/api/`、`src/utils/appActions.ts`
**跑**：该模块的定向测试 **+ 前端三项检查**（见 §四）
**为什么**：接口形状变了，光测后端不够，前端类型/契约也要过。

### L3 全量升级 —— 碰了契约/基础设施/跨模块
**触发路径（脚本硬编码，命中即全量）**：

```
backend/main.py                 启动装配
backend/core/                   配置/数据库/计量/利润引擎
backend/ai_infra/               Agent 基类 / LLM 客户端 / SSE
backend/models/                 ORM 模型（所有模块共享）
backend/core/metering/           计费计量
backend/modules/billing/        订阅与计费（契约层）
backend/tests/conftest.py       测试总闸（影响全部用例）
backend/pytest.ini              测试配置
backend/alembic/                迁移
```

**为什么必须全量**：这类文件的影响面**无法靠命名推断**。改一个 `BaseAgent` 方法，谁调用它是运行时才知道的。实测：改 `ai_infra/base_agent.py` → 必须全量。

---

## 四、前端改动的三项检查

前端**不走 pytest**（无测试框架，逻辑已抽到后端测）。改前端必跑：

```bash
cd frontend && npx vue-tsc --noEmit          # 类型
python frontend/scripts/check-theme-boot.py   # 主题跨文件一致（新增配色必查）
python frontend/scripts/check-app-actions.py  # 动作契约（新增动作必查）
```

后端测试**永远测不出前端的问题**——这三点漏一个，就是「后端全绿但页面白屏」。

> ★ 第 161 轮补记（真实缺陷）：上面两个 `.py` 自检脚本此前**从未在 CI 里执行过** ——
> CI 的门禁 glob 写死 `scripts/check-*.cjs`（后缀限定），而这两个脚本原名用**下划线**
> （`check_theme_boot.py`），连 `check-*` 这个前缀都匹配不上 ⇒ 「存在却静默不执行」。
> 现修法：①文件名分隔符统一成连字符；②CI glob 放开到 `scripts/check-*.*` 并按后缀分派
> （`.cjs` → node、`.py` → python、未知后缀直接失败）；③循环内**覆盖率自证**
> （glob 命中数 vs 该目录 `check-*` 总数，不等就红）。
> 门禁本体 = `backend/tests/test_ci_gate_coverage.py`（7 条）⇒ 谁再改回 `.cjs` 限定、
> 或把门禁改名回下划线，都会立刻红。
> **`.py` 门禁没有并进 `npm run build`**：`frontend/Dockerfile` 构建阶段是
> `node:22-alpine`（镜像里没有 python），并进去会让镜像构建失败。本地要跑用 `npm run check:py`。

---

## 五、为什么「全量」能压到 78s（已修的坑）

原本全量 **6m33s**，压到 **78s（约 5×）**，原因是**测试里真调了 LLM 的 API**：

| 问题 | 现象 | 修法 |
|---|---|---|
| 打桩不全 | `fake_llm` 只补了栈 B（`DashScopeLLM.chat`），栈 A（LangChain `ChatOpenAI`）和 `chat_stream` 全裸奔 → 大量用例真出网，单例 10～36s | `conftest._no_real_llm` **三层总闸**：httpx 域名拦截 + 栈 A 入口桩 + 栈 B 双方法补桩 |
| 桩不报用量 | 计费用例 `test_agent_chat_counted_and_llm_cost_persisted` FAIL —— 因为它**原本靠真调 API 才通过** | 桩补上报 `usage_metadata` + `record_llm_usage`，12.47s → 0.14s |
| 自检缺位 | 哪天总闸又被绕过，没人发现 | 新增 `tests/test_llm_offline_guard.py`（2 项常驻断言） |

> **必须记住**：本项目有**两套独立 LLM 栈**（栈 A `ChatOpenAI` 走工具路由/正文；栈 B `DashScopeLLM` 走 `llm_chat/llm_stream`）。**只补一套 = 假打桩**。

---

## 六、执行节奏（日常怎么用）

```
改代码
  │
  ├─ 改的是前端 ────────────────→ vue-tsc + 2 个自检脚本（约 1 分钟）
  │
  ├─ 改的是单个 modules/<x>/ ──→ pick_tests.py --base HEAD --run（约 10s）
  │                                  │
  │                                  └─ 若脚本判「全量」→ 别争，跑全量
  │
  └─ 改的是 ai_infra/core/models/main ──→ 直接全量（78s）

收尾（提交前 / 交付前）：
  跑一次全量 pytest -q   ← 这一步不能省，前面都是「改的过程中」的加速
```

**关键区分**：
- **开发过程中** → 定向，图快，只验证「我改的这块没坏」
- **交付前** → 全量，图稳，验证「我改的没弄坏别的」

---

## 七、可移植性检查清单

要把这套搬到别的项目，照着回答这四问：

1. **哪些路径的影响面无法靠命名推断？** → 那就是 `FULL_RUN_TRIGGERS`
2. **模块名 → 测试名 是否有同构关系？** → 有就自动映射，没有的登记进 `EXTRA_MAP`
3. **有没有「前端改动但不适用后端测试」的独立检查？** → 有就单列
4. **有没有「未命中」的兜底？** → **必须升级全量**，不能静默跳过

---

## 附：已知不适用 / 已否决的方案

| 方案 | 结论 | 原因 |
|---|---|---|
| `pytest-xdist` 并行 | **不可用** | 未安装；且与 `pytest.ini` 的 **session 级事件循环** 冲突（asyncpg 连接绑定在创建它的 loop 上，换进程/换 loop 会报 `attached to a different loop`） |
| 「按用例数量判断快慢」 | **错误直觉** | `--durations` 实测：**用例数量与耗时几乎无关**。慢的是**出网**和**进程启动** |
| 只跑「最近改的文件」的直接测试 | **不够** | 所以有 L2/L3：cross-module 影响必须靠契约层规则兜住 |

### 一个易踩的误读

`--durations` 里的 `call` 时间**不含 pytest 进程启动与 import**。实测：**纯函数用例（零依赖）墙钟也要 2.55s**——这 2.5s 是固定启动成本。
所以看到「一堆用例都是 2s」时，**不要**误判成「每用例 setup 有 2s 底板」；先量一次「跑 1 个纯函数用例」的墙钟做基线。
**推论：一次 pytest 进程跑完所有选中文件**（`pick_tests.py` 就是这么做的），比拆成 N 次调用快得多。
