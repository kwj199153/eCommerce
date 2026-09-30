# 第 334 轮 · 架构 / 模块化 / 内聚耦合复用 / 垃圾清理 审查报告

- **审查对象**：`D:\ai\eCommerce`（FastAPI 后端 + Vue3/TS 前端，跨境电商 AI SaaS）
- **审查性质**：**只读**。本轮未修改任何文件；所有结论均带 `文件:行号` 或真实命令输出
- **调查线**：① 后端架构与分层 ② 耦合与复用 ③ 前端架构 ④ 垃圾清理盘点
- **侦察基线**：`git log -1` = `6394119 2026-09-30 11:12:47 +0800`

---

## 0. 结论摘要

| 维度 | 总体判断 | 最严重的三件事 |
|---|---|---|
| **架构** | 分层方向**基本正确**（`ai_infra`/`platforms` 不反向依赖 `modules`，有门禁钉住），但**内核层反向依赖业务层**、**路由层直接触库**两处系统性破窗 | ① `core/` 反向 import `modules/` 24 处；② 7 个模块的 `router.py` 直接拼 SQL；③ `platforms/amazon` 与 `modules/amazon_sp` **同域双实现**，消费方分裂成两派 |
| **模块化** | 23 个模块边界**大体清晰**（`conversation` vs `memory` 有文档化切分），但 `products`/`candidates`/`library` 三者边界模糊、6 个模块**缺 `service.py`** | ① 6 模块无 service 层；② `review_analyst` 等模块 `router` 与 `service` 各持一份判定；③ `stores/router.py` 兼做 vault+连接器+计费 |
| **高内聚低耦合高复用** | **有真源意识且部分做得很干净**（重试已唯一收口 `core/resilience.py`、`shop_id` 过滤收口 `core/tenant/scoping.py`、窗口宽度收口 `config/layout.ts` 且有门禁），但**模板复制痕迹明显** | ① `_get_router()` 逐字复制 **7 份**；`_dump()` 5 份；ContextVar 5 份；Celery 会话桥 6 份；② 前端 `api/` 层**两套调用风格并存**；③ 前端约 **45 个零调用 API 封装** |
| **垃圾清理** | 有一个**量级压倒一切**的垃圾源，且根因未治 | ① `backend/logs` = **1.2 GB**（其中未压缩 `.log` ≈ **1.07 GB**，单日最大 **435 MB**）；② `frontend/src/mock/data.ts` **1145 行整文件死代码**（0 消费点）；③ 21 个 `.pytest-tmp-*` 残留 + `.gitignore` 缺 3 类规则 |

**额外发现（不在原四维内，但风险等级最高）**：工作树有 **299 个文件未提交**（+23121 / −13117 行），已实测**不是行尾噪声**。见 §5。

---

## 1. 垃圾清理盘点

### 1.1 体量分布（实测 `du -sh`）

顶层：

| 目录 | 体量 | 性质 |
|---|---|---|
| `backend/` | **1.6 G** | 主因见下 |
| `frontend/` | 38 M | 已排除 `node_modules` |
| `backups/` | 15 M | **真实数据库备份，不可删** |
| `docs/` | 8.9 M | 文档 + 33 张 png |
| `跨境电商AI-SaaS功能说明.docx` | 272 K | 业务文档 |
| `scripts/` `observability/` | 32K / 28K | CD 资产 / Prometheus 配置 |
| `logs/` | **0** | 仅 2 个 **0 字节** `.log` |
| `50` | **0** | **0 字节文件**，见 §1.5 |

`backend/` 内部：

| 子项 | 体量 | 判定 |
|---|---|---|
| `logs/` | **1.2 G** | ★ 垃圾主因 |
| `.venv/` | 319 M | 虚拟环境（已 ignore） |
| `uploads/` | 82 M | **真实用户上传，不可删**（`aigc/`、`voice/`） |
| `modules/` | 7.9 M | 生产代码 |
| `tests/` | 4.8 M | 测试 |
| `scripts/` `core/` `ai_infra/` `platforms/` | 2.2M / 1.7M / 1.1M / 766K | 生产代码 |
| `coverage.xml` | 731 K | 轮次产物 |
| `.coverage` | 168 K | 轮次产物 |
| `.pytest-tmp-*` / `.pytest_tmp_*` | 681 K（21 个目录） | 轮次残留 |
| `__pycache__` | 62 个目录 / 431 个 `.pyc` | 已 ignore |
| `.ruff_cache/` `.pytest_cache/` | 275K / 159K | 缓存，已 ignore |

### 1.2 ★ `backend/logs` 1.2 GB 深挖

| 文件 | 体量 | 最后写入 |
|---|---|---|
| `2026-09-22.log` | **435,315,383 B（415 MiB）** | Sep 22 21:39 |
| `2026-09-24.log` | 258,929,506 B（247 MiB） | Sep 24 23:29 |
| `2026-09-23.log` | 181,669,758 B（173 MiB） | Sep 23 21:23 |
| `2026-09-30.log` | 154,630,871 B（147 MiB） | Sep 30 18:36（当天，仍在写） |
| `2026-09-26.log` | 22,881,823 B（22 MiB） | Sep 26 20:15 |
| `2026-09-25.log` | 19,062,144 B（18 MiB） | Sep 25 21:52 |
| **6 个未压缩 `.log` 合计** | **≈ 1.07 GB** | — |
| 15 个 `.log.gz` | ≈ 104 MB | 已压缩的历史 |
| `celerybeat-schedule.{bak,dat,dir}` | 2.9 KB | beat 调度状态 |

**根因（已定位到源码）**：`backend/core/logger.py:229-241`

```python
logger.add(
    log_dir / "{time:YYYY-MM-DD}.log",
    rotation="00:00",      # ← 只按时间轮转，没有任何体积上限
    retention="30 days",
    compression="gz",
    ...
)
```

| 严重度 | 问题 | 证据 | 影响 |
|---|---|---|---|
| **P0** | 轮转**只有时间条件、没有体积条件** ⇒ 单日日志无上界（09-22 单日 435 MB） | `backend/core/logger.py:233`（`rotation="00:00"`，全文件无 `maxBytes`/size 轮转） | 磁盘可被单日日志打满；1.2 GB 已是当前最大垃圾源 |
| **P1** | `.log` 与其自己的 `.gz` **并存** ⇒ 压缩发生后旧 `.log` 未被清除 | `2026-09-26.log`（Sep 26 20:15，22 MB）与 `2026-09-26.log.gz`（Sep 27 01:38）同时在位 | 磁盘双倍占用；说明轮转时**有另一个进程仍持有该文件** |
| **P1** | **重复轮转产物**：同一份日志压缩出两个字节数完全相同的 gz | `2026-09-28.log.gz` 与 `2026-09-28.2026-09-29_00-07-13_129807.log.gz` 均为 `8789619 B` | 多进程（uvicorn + celery worker + beat）用 `enqueue=True` 共享同一 sink，午夜轮转发生竞争 |
| **P2** | `log_dir` 相对路径（默认 `logs`）⇒ 从不同 CWD 启动会落到不同目录 | `backend/core/logger.py:222`（`Path(getattr(config,"log_dir","logs"))`） | 解释仓库根 `logs/` 里那两个 0 字节 `.log`（曾从仓库根启动过一次） |

> **判定**：`logs/` 与 `*.log` 都在 `.gitignore` 中（`.gitignore` 的 `# ====== Logs ======` 段）⇒ **全部未入库，是纯磁盘垃圾，可安全清**。但**清完还会再长**，须先补体积轮转（`rotation="100 MB"` 或 `rotation="00:00"` + `maxBytes` 组合）。

### 1.3 未跟踪的轮次产物（`.gitignore` 缺口）

`git status --untracked-files=all` 实测 467 条未跟踪。其中属于轮次产物的：

| 类别 | 清单 | 体量 | `.gitignore` 是否覆盖 |
|---|---|---|---|
| junit 报告 | `backend/out-junit-r299-p1.xml`、`-p1b`、`-p1c`、`r300-c`、`r300-layers-a`、`r300-layers-b`（6 个） | 144 KB | ❌ **未覆盖** |
| 探针输出 | `backend/out-probe-{binding,join,r299-demo-eval,r299-demo-gate-injection,r299-demo-samples,r299-demo-seed,r299-r12-injection,r299-review-inventory,r299-risk-eval,review-entries,review-skill}.txt`（11 个） | 43 KB | ❌ **未覆盖** |
| 覆盖率 | `backend/coverage.xml`（731 K）、`backend/.coverage`（168 K） | 899 KB | ❌ 未覆盖（`.coverage` 其实有规则但写法为 `.coverage` 精确匹配，`backend/.coverage` 应命中；实测仍显示未跟踪 → 需复核） |
| pytest 临时目录 | `backend/.pytest-tmp-*` × 13、`backend/.pytest_tmp_*` × 8（共 **21 个**，含 `.pytest-tmp-r247-full3` 252K、`-r247-full` 232K） | 681 KB | ❌ **未覆盖**（`__pycache__` 有规则，`.pytest-tmp-*` 没有） |

现有 `.gitignore` 已有 `out-r*.txt` / `script-r*.py`（上轮所加），但**命名前缀没跟上**：实际产物是 `out-junit-*` / `out-probe-*`，前者规则一条都匹配不到。

### 1.4 `__pycache__` / 缓存

- `__pycache__` **62 个**（已排除 `.venv`）、`.pyc` **431 个** ⇒ 已被 `.gitignore` 的 `__pycache__/` + `*.py[cod]` 覆盖，**不影响 git 状态**，但占磁盘；可清、无风险。

### 1.5 `50` —— 一个 0 字节文件

```
$ ls -la 50
-rw-r--r-- 1 Administrator 197121 0 Sep 24 11:19 50
```

仓库根下的 **0 字节普通文件**（**不是目录** —— `ls 50/` 退出码 2）。时间戳 `Sep 24 11:19`。形态是典型的 shell 重定向事故（`cmd > 50` / `... 2>&1` 参数写错）。无任何引用，**纯垃圾**。

同类：仓库根 `logs/` 目录里有 `2026-09-18.log`（0 B）与 `2026-09-29.log`（0 B）—— 同样是误建的空文件（真实日志在 `backend/logs/`）。

### 1.6 不可删清单（防误清）

| 路径 | 为什么不能删 |
|---|---|
| `backups/`（15 M，`manifest.jsonl` + 3 个 `postgres-20260930-*.dump`） | **真实数据库备份**；`.gitignore` 已排除 ⇒ 它不在 git 里，删了就真没了 |
| `backend/uploads/`（82 M，`aigc/` + `voice/`） | **真实用户上传的图片/音频**；同样已 ignore，无第二副本 |
| `backend/.venv/`（319 M） | 开发环境；删了要重装 |
| `.workbuddy/` | 项目数据/记忆，**明令禁删** |

> 口径遵守：「可再生产物 ≠ 可删」——`out-junit-*` / `coverage.xml` 这类可重跑再生成，但 `backups/` / `uploads/` **本机就是唯一副本**，必须保留。

---

## 2. 后端架构与分层

### 2.1 依赖方向实测（目标：`core` ← `platforms` ← `modules` ← `main.py`）

| 方向 | 实测 | 判定 |
|---|---|---|
| `ai_infra/` → `modules/` | 未发现 | ✅ 干净，被 `tests/test_infra_layering.py` 钉住 |
| `platforms/` → `modules/` | 未发现 | ✅ 干净 |
| `modules/` → `core`/`platforms`/`ai_infra` | 大量 | ✅ 方向合法（向下依赖） |
| **`core/` → `modules/`** | **24 处** | ❌ **反向依赖** |
| **`core/` → `ai_infra/`** | **1 处** | ❌ **反向依赖** |
| `modules/` → `modules/` | **36 条边**（import 期 16 + 函数内 20） | ⚠ 横向耦合 |

**P1 · `core/` 反向依赖 `modules/`（24 处）**
- import 期 1 处：`backend/core/identity/models.py:186`（带 `# noqa: E402`）
- 函数内 23 处：`backend/core/database.py:125-186`、`backend/core/bootstrap.py:109-196`、`backend/core/metering/usage_tracker.py:82,140,202,245,504`、`backend/core/identity/router.py:219`
- 影响：内核被业务模块的**模型注册**与**引导 seed** 绑死，无法脱离 `modules/` 单独复用/测试。

**P1 · `core/` 反向依赖 `ai_infra/`（1 处）**
- `backend/core/redis.py:11`：`from ai_infra.memory.limits import DISTILL_HOUR, DISTILL_MINUTE`
- 影响：最底层 `core` 依赖 AI 层；而 `ai_infra/base_agent.py:99-101` 又依赖 `core` ⇒ **一旦 `ai_infra.memory.*` 顶层引入任何 `core` 依赖，立即形成 import 期循环**。当前仅因 `limits.py` 零依赖而未成环，是**靠运气**。

### 2.2 循环依赖

| 严重度 | 环 | 证据 |
|---|---|---|
| P1 | `modules/amazon_sp` ⇄ `modules/trade` | 正向（import 期）：`backend/modules/amazon_sp/data_sources/mock_source.py:35`：`from modules.trade import (SOURCE_MOCK_SEED, build_demo_order_payloads, build_demo_review_payloads,)`；反向（函数内）：`backend/modules/trade/tasks.py:119,161`：`from modules.amazon_sp import get_data_source` |
| P2 | `core/` 内部环 `{auth, identity, stores}` | 已由门禁显式登记为"已知环"：`backend/tests/test_core_internal_layering.py:253-255` |
| P2 | `core` ⇄ `ai_infra` 潜在环 | 见 §2.1 第二条 |

严格意义的 **import 期 A↔B 双向 import：未发现**（16 条 import 期模块边逐条判定均单向）。

### 2.3 分层穿透：`router.py` 直接触库

设计上 `router` 应只做 HTTP 契约、转调 `service.py`。实测**直接执行 SQL / 直接用 Session** 的模块：

| 模块 | 直接触库次数 | 代表证据 |
|---|---|---|
| `products/router.py` | **49** | `:121-122`（`session.execute` + `scoped(select(SpuRecord))`）、`:131`、`:135`、`:256`、`:270` |
| `billing/router.py` | **34** | `:197`、`:228-229`、`:241`、`:344`、`:349`、`:358`、`:627`、`:678`（该模块**根本没有 `service.py`**） |
| `assets/router.py` | **31** | `:91`、`:95`、`:128`(`session.add`)、`:139`、`:219`、`:243` |
| `monitors/router.py` | **29** | `:66`、`:70`、`:92`、`:125`、`:162`、`:212` |
| `candidates/router.py` | **27** | `:124`、`:126`、`:145`(`session.commit`)、`:181`、`:246` |
| `stores/router.py` | **11** | `:107`、`:189`、`:210`(`session.add`)、`:218`、`:252`、`:293` |
| `billing/payment_router.py` | — | `:136-137`、`:157`、`:234` |
| `aigc_media/router.py` | 1 | `:755`（直接 `db.commit()`） |

**已确认干净**（router 不直接触库）：`ad_analysis`、`competitor_intel`、`conversation`、`customer_service`、`listing_generator`、`memory`、`platform_rules`、`product_research`、`review_analyst`、`secretary`、`skills`、`trade`、`voice_clone`、`knowledge_base`。

**`modules/*/agent_*.py` 绕过 service 直接触库：未发现**（8 个 agent 逐一扫描 `SessionLocal`/`session.execute`/`select` 均 0 命中）—— 这一条做得好。

### 2.4 模块完整性（五件套缺口）

| 缺失面 | 模块 | 影响 |
|---|---|---|
| 缺 `service.py`（**6 个**） | `billing`、`stores`、`products`、`secretary`、`library`、`amazon_sp` | 业务规则无处收口（`billing` 的规则散在 `router.py`/`payments.py`/`pricing.py`） |
| 缺 `router.py`（2 个） | `library`、`amazon_sp` | 属"库/适配器"型模块，可接受 |
| 缺 `db_model.py`（7 个） | `ad_analysis`、`billing`、`competitor_intel`、`listing_generator`、`secretary`、`stores`、`library` | 持久化模型寄居他处 |

### 2.5 超大文件 / 职责过载（God Object）

`modules + core + ai_infra` 共 289 个 `.py`，**>800 行 19 个**。最严重的：

| 严重度 | 文件 | 行数 | 职责过载证据 |
|---|---|---|---|
| **P0** | `modules/product_research/agent_product_research.py` | **2646** | 单方法 `_analyze_blue_ocean` 占 **1289 行**（`:1358-2646`）；类 `ProductResearchAgent` 起点 `:272` |
| **P0** | `modules/trade/service.py` | **2535** | 约 60 个顶层函数，横跨 **~13 个不相关子域**：时间工具/归因规则/人工补标/补偿规则/SKU 健康分/订单上下文/风险话术/重复问题/系统性判定/差评处置/序列化（分节 `:70,107,283,377,734,925,1058,1301,1366,1518,2186,2222`） |
| P1 | `modules/skills/seed.py` | 2085 | `:1-1439` 是**内嵌演示数据/提示词字面量**，`:1440` 才开始真逻辑 ⇒ 改一条演示文案要动源码 |
| P1 | `ai_infra/base_agent.py` | 1781 | `BaseAgent`（`:177`）40 个方法，同时承担 LLM 调用（`:1226-1415`）、图构建、HITL、RAG、会话状态、统计；`__init__` 195 行 |
| P1 | `modules/customer_service/agent_cs.py` | 1992 | 单类 44 个方法（`:208`），塞入 FAQ/情绪/6 条意图/工单/知识检索 |
| P2 | `core/config.py` | 876 | `Settings`（`:108-870`）**86 个字段** |
| P2 | `modules/stores/router.py` | 1220 | 约 28 个端点 + connector 解析 + 凭据保管 + 利润计算 + 费率模板 |

其余 >800 行：`aigc_media/agent_aigc.py` 1848、`listing_generator/agent_listing.py` 1802、`competitor_intel/agent_competitor.py` 1576、`ad_analysis/agent_ad.py` 1365、`platforms/amazon/client.py` 932、`core/auth/accounts.py` 927、`trade/risk_scan.py` 906、`skills/tools_catalog.py` 892、`library/tools.py` 851、`aigc_media/router.py` 842、`ai_infra/rag/hybrid_engine.py` 831、`ai_infra/llm/dashscope_client.py` 800。

### 2.6 ★ 模块划分：`platforms/amazon` 与 `modules/amazon_sp` 同域双实现（P0）

| 严重度 | 问题 | 证据 |
|---|---|---|
| **P0** | 仓内并存**两套亚马逊数据接入**：`platforms/amazon/client.py`（932 行，自述"编造"数据的 MOCK 世界，提供 product/keyword/review/competitor/fee）与 `modules/amazon_sp/`（数据源工厂，mock + 真实 SP-API） | `backend/platforms/amazon/client.py:1-21`、`:932`；`backend/modules/amazon_sp/data_sources/base.py:1-20`、`backend/modules/amazon_sp/__init__.py:10-24` |
| **P0** | **消费方分裂成两派**：`product_research` / `listing_generator` 走 `platforms` 假数据；`ad_analysis` / `competitor_intel` / `review_analyst` / `customer_service` / `trade` 走 `modules/amazon_sp` 工厂 | 假数据侧：`modules/product_research/service.py:22-23`、`agent_product_research.py:31,1664,1746`、`listing_generator/agent_listing.py:26-27,213`；工厂侧：`ad_analysis/agent_ad.py:128-130`、`competitor_intel/agent_competitor.py:24`、`review_analyst/service.py:31`、`customer_service/agent_cs.py:1700-1706` |
| P1 | "竞品快照"在 **3 处**落地（`amazon_sp` 表所有者 / `monitors` 时序生成 / `platforms/amazon` MOCK 生成） | `modules/amazon_sp/snapshot_repo.py:1-36`、`modules/monitors/snapshot.py:1-19`、`platforms/amazon/client.py:11` |
| P1 | `amazon_sp` 的 seed **反向依赖 `monitors` 的 ORM** | `backend/modules/amazon_sp/seed.py:223`：`from modules.monitors import MonitorRecord`（函数内） |
| P2 | `products` / `candidates` / `library` 边界模糊：`candidates` 与 `products` 字段高度重叠，`library` 只读聚合两者 | `modules/candidates/db_model.py:34-53` vs `modules/products/db_model.py:44-48`；`modules/candidates/service.py:568`：`from modules.products import SpuRecord, spu_to_dict`；`modules/library/tools.py:98-104` |

> 注：`conversation` vs `memory` **不算重叠** —— 有明确文档化切分（前者按 `thread_id`、后者按 `owner_id`），见 `modules/conversation/db_model.py:1-12` 与 `modules/memory/db_model.py:1-11`。

### 2.7 测试目录体量

`backend/tests` = **144 文件 / 64,760 行**，与生产代码（289 文件）同量级。单文件 >1500 行 4 个：

| 文件 | 行数 |
|---|---|
| `tests/test_skill_gate.py` | 1952 |
| `tests/test_tool_catalog.py` | 1608 |
| `tests/test_competitor_intel.py` | 1502 |
| `tests/conftest.py` | 1354（全局夹具） |

1000–1500 行 3 个：`test_auth_security_p1b.py` 1374、`test_agent_session_state.py` 1231、`test_memory_distill.py` 1056。

---

## 3. 耦合与复用

### 3.1 后端：逐字复制（同语义多份实现）

| 严重度 | 复制体 | 份数 | 证据（file:line） |
|---|---|---|---|
| P1 | `_get_router()` 懒加载方法（AST 归一化后 body 完全一致） | **7** | `ad_analysis/agent_ad.py:391`、`aigc_media/agent_aigc.py:372`、`competitor_intel/agent_competitor.py:225`、`customer_service/agent_cs.py:271`、`listing_generator/agent_listing.py:274`、`product_research/agent_product_research.py:578`、`review_analyst/agent.py:289` |
| P1 | `_dump(resp)` 工具出参序列化器 | **5**（+2 变体） | `ad_analysis/tools.py:54`、`competitor_intel/tools.py:58`、`customer_service/tools.py:62`、`product_research/tools.py:47`、`review_analyst/tools.py:84`；变体 `trade/tools.py:76`、`aigc_media/tools.py:325` |
| P1 | `_current_shop_id` ContextVar **各自定义** + 取值器 `_shop_id()`/`_store_id()` | **5** 定义 | 定义：`customer_service/agent_cs.py:51`、`competitor_intel/agent_competitor.py:40`、`ad_analysis/agent_ad.py:51`、`product_research/agent_product_research.py:223`、`review_analyst/agent.py:64`；取值：`ad_analysis/tools.py:35`、`competitor_intel/tools.py:40`、`customer_service/tools.py:37`、`review_analyst/tools.py:61` |
| P1 | Celery worker 会话桥：`_thread_loop`/`_run_sync` 逐字相同；`_new_session_factory`/`_execute_with_session` 逐字相同 | **4 + 2** | `core/audit/tasks.py:68,79`、`core/identity/tasks.py:106,117`、`modules/memory/tasks.py:117,128`、`modules/trade/tasks.py:74,88`；`aigc_media/tasks.py:67,78`、`billing/tasks.py:91,97` |
| P1 | 「该店铺是否已监控此 ASIN」**两份判定**，service 版存在但 router 未调用 | 2 | `monitors/service.py:236`（`monitor_exists`）vs `monitors/router.py:158`（`_monitor_exists_session`） |
| P2 | `_days_of("7d/30d/90d")` | 2 | `ad_analysis/agent_ad.py:58`、`competitor_intel/agent_competitor.py:46` |
| P2 | 上传根路径解析**绕过真源** `core/storage/paths.py::upload_root` | 2 | `voice_clone/service.py:141-152`（`_voice_upload_root`）vs `core/storage/paths.py:36` |
| P2 | 平台家族前缀归并 | 2 | `secretary/shop_tools.py:39`（硬编码元组）vs `stores/connect/registry.py:51`（注册表派生） |
| P2 | `aigc_media/service.py` 内联重复构造 `{"success": ..., ...}` 信封 | ~30 处 | `aigc_media/service.py:45,58,84,92,133,140,172,179,210,217,239,267,296,298,305,335,342,381,388,431,438,471,504` |
| P2 | 文档详情/删除端点**两份逐字相同** | 2 | `knowledge_base/router.py:198,211` vs `platform_rules/router.py:135,149` |

**做得好的（真源已收口，够硬）**：
- 网络重试 → 唯一真源 `core/resilience.py`（`:189,244,309`），且有形态门禁 `tests/test_resilience.py:371` 守着；仅剩 `customer_service/service.py:54` 一处「换号重试」DB 冲突循环未覆盖（非网络重试）。
- `shop_id` 过滤 → 收口 `core/tenant/scoping.py:83`（`modules/**` 已无手写 `shop_id ==`）。
- 归属判定 → 收口 `core/auth/accounts.py:414,576,629`（`stores/router.py:545`、`conversation/service.py:113` 均调真源）。

### 3.2 前端：重复实现

| 严重度 | 问题 | 证据 |
|---|---|---|
| P1 | **`api/` 层两套调用风格并存**：具名函数 vs 直接 `request.*`；`candidates.ts`/`products.ts` 两文件**同时 import 两种** | 具名：`assets.ts:8`、`billing.ts:5`、`knowledge.ts:12`、`memory.ts:38`、`monitors.ts:11`、`platformRules.ts:12`、`skills.ts:17`、`stores.ts:7`、`accounts.ts:16`、`auth.ts:50`、`audit.ts:29`；直接：`adAnalysis.ts:34`、`aigcMedia.ts:7`、`competitorIntel.ts:12`、`customerService.ts:5`、`listingGenerator.ts:36`、`productResearch.ts:5`、`review.ts:18`、`secretary.ts:5`、`trade.ts:19`、`voiceClone.ts:11`；混用：`candidates.ts:8-9`、`products.ts:8-9` |
| P1 | `detectInput`（ASIN/Shopee ID 识别）+ `platformLabel`/`platformTagColor` 两处几乎逐字相同 | `TaskConfigPanel/configs/ProfitConfig.vue:330-362` vs `PainPointConfig.vue:160-236` |
| P1 | `REVIEW_STATUS_LABELS`（new/triaged/replied/closed）两份逐字相同 | `KnowledgeBase/ProductLibrary.vue:1191-1196` vs `TaskConfigPanel/configs/ReviewDeskConfig.vue:959-964` |
| P2 | 金额格式化多份：真源 `composables/conversation/format.ts:15`，另有独立实现 + 大量内联 `$${...toFixed(2)}` | `utils/competitorIntel.ts:48`、`results/ProfitResult.vue:89`、`configs/ReviewConfig.vue:445`、`configs/AdDashboardConfig.vue:530` |
| P2 | 日期/时间格式化 **6 份**，且 **`dayjs` 与 `new Date` 两种库混用** | `views/Subscription.vue:701,706`、`views/Settings.vue:843,848`、`views/Team.vue:296`、`KnowledgeBase/AssetLibrary.vue:723`、`AuditLogPanel.vue:112`、`VoiceClonePanel.vue:416` |
| P2 | 文件大小 `formatSize` 两份（仅 `1024*1024` vs `1048576` 写法差异） | `PlatformRules.vue:743-747` vs `FaqKnowledgeBase.vue:510-514` |
| P2 | 视频平台标签映射 **3 份逐字相同** | `composables/chat/resultSummary.ts:142`、`mock/toolExecutors.ts:941`、`configs/VideoScriptConfig.vue:237-240` |
| P2 | 平台枚举 / 配色 / 币种各写一份，平台联合类型 **4 份** | `views/Settings.vue:697-729`、`Sidebar/ShopPopoverContent.vue:191-198`、`theme/semantic.ts:115`、`stores/platformRules.ts:85-88`、`configs/ProfitConfig.vue:331-337`；类型：`utils/platform.ts:9,13`、`stores/shop.ts:20`、`ProfitConfig.vue:208`、`PainPointConfig.vue:121` |

**做得好的**：`config/layout.ts`（窗口宽度）经门禁 `frontend/scripts/check-window-widths.cjs` 实测 **56 个窗口零字面量**，是少见的**已收口且被守住**的真源。`utils/platform.ts` 已是平台语义真源，但被上述三处绕过。

### 3.3 前端：自算后端判据（第二份实现）

| 严重度 | 问题 | 证据 |
|---|---|---|
| P2 | 前端镜像了后端的角色权限判定 | `api/accounts.ts:113`（`canManageMembers` 镜像后端 `role_allows`） |
| P2 | 前端自持配额上限 | `stores/monitorPool.ts:247`（`quotaReached` 本地写死 20） |
| P2 | 前端按 `account_id` 自行过滤店铺可见性，真源在 `core/auth/accounts.py:261 filter_accessible_stores` | `stores/account.ts:71-78` |
| P2 | 前端视图/state **绕过 `api/` 层直接调 `@/api/request`** | `views/Settings.vue:496,524,563,622,637,647,676`；`stores/shop.ts:238`（与 `api/stores.ts:207 deleteShop` 同端点两份）；`stores/user.ts:251,448` |
| P2 | 时间入 JSON 的真源 `core/timefmt.py::utc_iso` 被裸 `.isoformat()` 绕过（返回**无偏移**字符串给前端） | `products/router.py:143,190,264,340,377,397,418,447,492`；`monitors/router.py:99,200,221,252,281`；`candidates/router.py:144,185,186,254,283`；`assets/router.py:103,149,197,226,269` |

### 3.4 低内聚（巨型函数 / 多职责）

| 严重度 | 函数 | 规模 | 证据 |
|---|---|---|---|
| P1 | `build_library_tools` | **364 行**，一个函数造 6+ 个工具（取数+过滤+排序+出参格式化） | `modules/library/tools.py:488` |
| P1 | `change_plan` | **317 行**，套餐选择+同步/异步支付分流+账单落库+订阅变更+响应构造 | `modules/billing/router.py:253` |
| P2 | `scan_reviews_risk`（165 行/7 参）、`connect_store_platform`（156 行）、`_enforce_production_safety`（201 行）、`seed_products_if_empty`（180 行）、`BaseAgent.__init__`（12 参）、`record_audit`（10 参）、`_generate_product_image_tool`（16 参） | — | `trade/service.py:1134`、`stores/router.py:896`、`core/config.py:156`、`products/seed.py:359`、`ai_infra/base_agent.py:253`、`core/audit/service.py:82`、`aigc_media/tools.py:42` |
| P2 | 「工具结果渲染」知识双份：`resultSummary.ts` 巨型 switch（跨 140+ 行） vs 各结果卡组件各自渲染（`order-track` 已收口，其余未收） | `composables/chat/resultSummary.ts:18`；已收口样例 `utils/orderTracking.ts:16` + `resultSummary.ts:59` |
| P2 | 「店铺」概念多形态并存：pydantic `models/store.py:80` + ORM `core/stores/models.py` | `models/store.py:80`、`core/stores/models.py` |

---

## 4. 前端架构与模块化

### 4.1 目录结构

全前端 = **103 个 `.vue` + 106 个 `.ts` = 78,314 行**。`frontend/src` 主要目录：

| 目录 | 文件数 | 行数 |
|---|---|---|
| `components/TaskConfigPanel/configs` | 27 | **14,387** |
| `components/KnowledgeBase` | 8 | 9,449 |
| `stores/` | 21 | 8,453 |
| `components/ChatPanel/results` | 15 | 7,169 |
| `views/` | 8 | 6,934 |
| `api/` | 26 | 5,795 |
| `mock/` | **3** | 2,406 |
| `utils/` | 12 | 2,405 |
| `composables/`（含 `chat/`、`replies/`） | 25 | ~8,900 |

| 严重度 | 问题 | 证据 |
|---|---|---|
| P2 | `components/` **已完成子目录分类，无平铺**（做得好） | `find src/components -maxdepth 1 -type f -name "*.vue"` → 0；13 个子目录 |
| P1 | `TaskConfigPanel/configs` 单目录 **27 文件 / 14,387 行**，占全前端 24%，模块边界仅靠文件名 | `wc -l src/components/TaskConfigPanel/configs/*.vue` → total 14387 |
| P1 | `stores/` **21 个 store 平铺无子目录**，且存在职责相邻对 | `monitorPool`(700) vs `competitorPool`(326)；`productLibrary`(976) vs `candidateLibrary`(638) |

### 4.2 超大组件

| 严重度 | 组件 | 行数 | 证据 |
|---|---|---|---|
| **P0** | `ReviewDeskConfig.vue` | **2646** —— 全仓最大，**超过历史峰值 2400**，是**新长出的 God Component** | `:1`(template) / `:886`(script) / `:2133`(style) |
| P1 | `ProductLibrary.vue` | 2378 —— 历史 2400+ **未拆净** | `:810`(script) / `:1370`(style)；仅拆出 `ProductLibrary/` 3 个 modal 共 530 行 |
| P1 | `PlatformRules.vue` | 1917 —— 仅拆出 1 个 modal | `:696`(script) / `:1214`(style)；`PlatformRules/` 仅 1 文件 332 行 |
| P2 | `BlueOceanResult.vue` | 1206 —— **已从 2400+ 降下来，拆分有效** | `:296`(script) / `:668`(style) |
| P2 | `Subscription.vue` 1677、`Workspace.vue` 1431、`SkillManager.vue` 1300、`AssetLibrary.vue` 1177、`ChatPanel/index.vue` 1127 | — | script 段普遍 350–760 行 |

`.ts` 最大两个**都是应退役的 mock 文件**：`mock/data.ts:1145`、`mock/toolExecutors.ts:1121`；其后 `stores/productLibrary.ts:976`、`stores/skills.ts:823`、`stores/voiceTts.ts:725`、`stores/platformRules.ts:705`、`stores/monitorPool.ts:700`。

### 4.3 ★ mock 层残留

| 严重度 | 问题 | 证据 |
|---|---|---|
| **P0** | `src/mock/data.ts` **1145 行整文件死代码**，13 个导出，全仓 **0 消费点** | `grep -rn "mock/data" src` → 0；`grep -rn "@/mock"` → 仅 `secretaryBrain`/`toolExecutors` |
| P1 | `mock/toolExecutors.ts` **1121 行仍在线**于 `tool-analysis` 主路径 | 消费点 1 处 `useChatEventBridge.ts:23`；运行处 `:210 toolExecutors[tool.id]`、`:194 getParamSummary`；自述 `:69`「其余执行器**仍是本地 mock**」 |
| P1 | `mock/secretaryBrain.ts` 140 行，动态 import 兜底 | 消费点 1 处：`composables/chat/replies/secretary.ts:270`：`await import('@/mock/secretaryBrain')` |
| P2 | 注释失实：store 声称"失败回退 mock"，实际无 mock import | `stores/candidateLibrary.ts:5` |
| P2 | 注释引用了**不存在**的 `src/api/competitorIntelligence.ts` | `utils/competitorIntel.ts:33`、`:238`；实际只有 `api/competitorIntel.ts` |
| P2 | 已退役 6 个 mock 文件**确认不在** `src/mock/`（退役执行到位） | `ls src/mock` → 仅 3 个文件 |

### 4.4 api 层：约 45 个零调用封装

`src/api/` = 26 文件 / 5795 行。`request.ts` 是**唯一** axios 实例持有者（未见第二套请求封装）。

| 严重度 | 问题 | 证据 |
|---|---|---|
| P1 | **大量「后端端点已封装、前端零调用」**，粗估 **~45 个函数** | `aigcMedia.ts` 17 导出中 14 个零调用（`:16-:342`）；`stores.ts` 5/17（`:160,:357,:364,:374,:382`）；`customerService.ts` 4/9；`listingGenerator.ts` 3/10；`productResearch.ts` 3/8；`products.ts` 2/16；`accounts.ts` 3/12；`candidates.ts` 2/13 |
| P1 | `api/monitors.ts` **13 端点中 3 个零调用** | `:20 fetchMonitor`、`:29 updateMonitor`、`:33 deleteMonitor` |
| P1 | `api/aigcMedia.ts` 整个 job/图像族无消费 | `:16 generateImage`、`:280 submitAigcJob`、`:288 getAigcJob`、`:293 listAigcJobs`、`:318 submitAndWaitAigcJob`、`:48 generateAPlusContent` |
| P2 | `api/review.ts` 5 个 `fetch*` 外部零引用但**非死码**（经注册表消费） | `review.ts:253-259 REVIEW_FETCHERS` ← `configs/ReviewConfig.vue:365` |

### 4.5 状态管理

| 严重度 | 问题 | 证据 |
|---|---|---|
| P1 | Pinia store **互相 import 形成耦合** | `stores/account.ts:36-37`（import shop + user）；`stores/agent.ts:3`（import chat） |
| P1 | 组件**直接改 store 内部状态、绕过 action** 共 **12 处** | `AssetLibrary.vue:157,168,179`；`CandidateLibrary.vue:103,114,125`；`PlatformRules.vue:150,160,170,180`；`SkillManager.vue:788`；`TourHost.vue:154` |
| P1 | **provide/inject 隐式契约偏多**：21 个 `provide(`、36 个 `inject(` | `Workspace.vue:377-589` 单文件 **15 个 provide**；`TaskConfigPanel/index.vue:350-364` 4 个 |
| P1 | **window CustomEvent 事件总线**：14 个事件名、31 次 `dispatchEvent`、34 次 `addEventListener` | `useChatEventBridge.ts:71-73` 监听 3 个 |
| P2 | 已知循环依赖靠注释规避 | `stores/user.ts:271-273`（user→authVault→request→user 说明） |

### 4.6 死代码（前端）

| 严重度 | 问题 | 证据 |
|---|---|---|
| **P0** | `mock/data.ts` 整文件死（见 §4.3） | `:249 MOCK_PRODUCTS` 等 13 导出全零引用 |
| P1 | `utils/colorSemantics.ts` **12 个导出常量零引用** | `:34,36,38,40,42,44,46,56,86,114,116,124` |
| P2 | `utils/download.ts` 3 个导出零引用 | `:84 toExcelArrayBuffer`、`:192 downloadJsonFile`、`:197 downloadCsvFile` |
| P2 | `config/authVault.ts` 3 个导出零引用 | `:73 purgeLegacyCredentialStore`、`:124 loadRemembered`、`:182 AUTH_VAULT_STORAGE_KEY` |
| P2 | `composables/useSpeechInput.ts` 的 `startSpeech` 零外部引用 | 文件被 `ChatPanel/index.vue:368` 导入 |
| — | **未见死 `.vue` 组件**（做得好） | 103 个组件全有 import 点；6 个 view 由 `router/index.ts:11-74` 懒加载 |

---

## 5. 附加发现：提交卫生（风险最高）

| 严重度 | 问题 | 证据 |
|---|---|---|
| **P0** | 工作树有 **299 个文件未提交**（+23,121 / −13,117 行）、**32 个文件已删除未提交**、**467 条未跟踪** | `git diff --numstat` → 299 行；`git diff --stat` → `299 files changed, 23121 insertions(+), 13117 deletions(-)`；`git status --porcelain` → `354 ??` / `32 D` / `267 M` |
| — | **已实测排除行尾噪声**（不是 CRLF 造成的假信号） | `core.autocrlf=true`；但 `git diff --numstat --ignore-cr-at-eol` 仍 **299** 文件、`-w` 仍 **299** ⇒ 是真实内容差异 |
| — | 改动确实是真实工作（非噪声）：最大改动 | `frontend/scripts/check-tool-reality.cjs` +1009/−12；`backend/modules/customer_service/agent_cs.py` +947/−238；`backend/tests/test_competitor_intel.py` +820/−122；`frontend/src/views/Subscription.vue` +728/−93 |
| — | 32 个删除文件中含**历史多轮的 mock 退役与死组件清理** | `frontend/src/mock/{adDashboard,competitorIntel,competitorRecommend,listingBoard,reviewDashboard}.ts`；`ChatPanel/results/{AnomalyDetectResult,BudgetAllocResult,CompetitorIntelEvidence,...}.vue`；`configs/{AdDiagnosisConfig,BidSuggestConfig,IntelAnalysisConfig,...}.vue` |

> 最后一个提交是 `2026-09-30 11:12:47`，此后所有轮次的工作都**stack 在工作树里**。这既是"垃圾清理"的一部分（未提交=无版本保护），也是最大单点风险：一次误操作（`git checkout .` / `git stash drop`）就会丢掉几十轮成果。
> **注意本仓铁律**：恢复前必须先查 `git status --porcelain`，**禁无差别 `git show HEAD:f > f`**（有未提交改动时静默毁掉整轮）。

---

## 6. 优先级汇总与建议处置（待老板拍板，本轮未执行任何动作）

### P0（建议优先）

| # | 问题 | 一句话处置方向 |
|---|---|---|
| P0-1 | **299 文件未提交**（§5） | 分批提交（按 后端/前端/文档/门禁 切分），先保命再谈清理 |
| P0-2 | **`backend/logs` 1.2 GB**，根因 `rotation="00:00"` 无体积上限（§1.2） | 清历史 `.log`；源码补体积轮转；查多进程竞争（`enqueue=True` 共享 sink） |
| P0-3 | `frontend/src/mock/data.ts` 1145 行死代码（§4.3） | 删文件 |
| P0-4 | `ReviewDeskConfig.vue` 2646 行 God Component（§4.2） | 按 AIGC/Listing 的大屏范式拆 |
| P0-5 | `platforms/amazon` vs `modules/amazon_sp` 同域双实现、消费方分裂（§2.6） | 定唯一真源，另一侧下线（这决定"两个世界的数据"问题） |
| P0-6 | `product_research/agent_product_research.py` 单方法 1289 行（§2.5） | 拆函数 |

### P1

| # | 问题 |
|---|---|
| P1-1 | 7 个 `router.py` 直接触库（最多 `products` 49 处）；6 模块缺 `service.py`（§2.3/2.4） |
| P1-2 | `core/` 反向依赖 `modules/`（24 处）与 `ai_infra/`（1 处）（§2.1） |
| P1-3 | `_get_router` ×7 / `_dump` ×5 / ContextVar ×5 / Celery 桥 ×6 逐字复制（§3.1） |
| P1-4 | 前端 `api/` 两套调用风格；`detectInput` / `REVIEW_STATUS_LABELS` 各两份（§3.2） |
| P1-5 | 前端 **~45 个零调用 API 封装**（§4.4） |
| P1-6 | `trade/service.py` 2535 行横跨 13 子域；`skills/seed.py` 数据与逻辑同文件（§2.5） |
| P1-7 | 14 个 `CustomEvent` + 21 provide / 36 inject 隐式契约（§4.5） |
| P1-8 | `mock/toolExecutors.ts` 1121 行仍在 `tool-analysis` 主路径（§4.3） |

### P2

`.gitignore` 缺 `out-junit-*` / `out-probe-*` / `.pytest-tmp-*`（§1.3）；21 个 `.pytest-tmp-*` 残留（681 KB）；仓库根 0 字节文件 `50` 与 `logs/` 两个空 `.log`（§1.5）；测试单文件 >1500 行 4 个（§2.7）；前端 12 处绕过 store action；`colorSemantics.ts` 12 个死导出；前端自算后端判据 3 处；`utc_iso` 被裸 `.isoformat()` 绕过；`stores/` 21 个平铺（§4.1）。

---

## 附：本轮方法论备注

- 全程只读；未 `Edit`/`Write` 任何既有文件，仅新增本报告。
- 所有行号为真实读数；跨层判定用 **AST 祖先链**（非行首缩进）区分「import 期」与「函数内」，与既有门禁 `test_module_layering.py` / `test_core_layering.py` / `test_infra_layering.py` 同口径。
- 体量口径：`du -sh --exclude=node_modules --exclude=.git`；行数口径 `wc -l`（已排除 `node_modules`/`dist`）。
- git 口径：`git status --porcelain` 与 `git diff --numstat [--ignore-cr-at-eol | -w]` 三读对照，用于排除行尾噪声假信号。
