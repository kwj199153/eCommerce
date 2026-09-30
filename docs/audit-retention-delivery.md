# 审计保留期清理 —— 交付说明（第 328 轮 #1200）

> 上游：`docs/audit-p0-5-delivery.md`（P0-5 通用审计读口）。
> 本轮补的是它的最后一块边角：`audit_logs` **只增不减**。
> 计划原文：「`audit_logs` 会随写操作稳定增长，建议加一个 Celery beat
> 任务（照 `login_guard.purge_old_attempts` 范式）或分区表。」

---

## 1. 交付物

| 类型 | 文件 | 说明 |
|---|---|---|
| **新增** | `backend/core/audit/retention.py` | 清理核：`retention_cutoff()`（纯函数）+ `purge_expired(db, retention_days=None)`。**审计的唯一删除路径** |
| **新增** | `backend/core/audit/tasks.py` | Celery 接线：`TASK_PURGE_EXPIRED` + 每线程常驻 loop + 指标/日志出口 |
| **新增** | `backend/tests/test_audit_retention_gate.py` | 门禁 13 条（形态 4 + 行为 3 + 自检 5 + 队列 1） |
| 改 | `backend/core/config.py` | `audit_retention_days: int = 90`（与登录审计的 30 天**分开**） |
| 改 | `backend/core/redis.py` | autodiscover 增 `"core.audit"`；`AUDIT_PURGE_HOUR/MINUTE`；beat 条目 `audit-purge-expired` |
| 改 | `backend/core/observability/metrics.py` | `AUDIT_PURGE_RUNS{status}` + `AUDIT_PURGE_DELETED`（并注册进 `_REGISTRY`） |
| 改 | `backend/core/audit/models.py` | 文件头「将来需要」→ 指向已落地的清理核（**不是**复制一份说明） |
| 改 | `backend/core/audit/__init__.py` | 补「**刻意不导出** tasks/retention」的理由（防后人顺手 re-export） |
| 改 | `observability/alert_rules.yml` | `AuditPurgeFailing`（跑了但抛错）+ `AuditPurgeStalled`（压根没跑） |
| 改 | `backend/tests/test_core_internal_layering.py` | 登记 audit 新增的 3 条 import 期边（+ 实测值 44→47） |
| 探针 | `backend/.workbuddy/probes/r329_*.py` | EOL 归一/分层对账/**反向注入 8 组**/端到端真跑 |

**运行期行为**：每天 **05:07**（`crontab`，Asia/Shanghai）删除 `created_at`
早于 `audit_retention_days`（默认 90 天）的行。

---

## 2. 关键设计决策

### 2.1 为什么清理**不能**住进 `service.py`（而必须独立成模块）

`models.py` 把本表定义为 **append-only**，并预先写下「保留期清理必须走独立的、
显式的归档任务」。这不是洁癖，是**证据完整性**：

> 一张能被随手 `DELETE` 的表，它的每一行都不再能证明任何事。

⇒ 清理住在**名字里就写着清理**的 `retention.py`：读代码的人一眼能看见
「谁能删审计」。由门禁钉住**删除路径只有一条**
（`test_audit_rows_are_deleted_only_in_the_retention_module`，
是 `test_audit_gate.py::A2`「构造 `AuditLog` 只允许在 service.py」的**删除版**）。

### 2.2 为什么是定时任务，而不是「写的时候顺手清一把」（**被否方案**）

直觉方案：`record_audit()` 里按概率删一批旧行 —— 不需要任何调度器。**否掉**，两条理由：

1. `record_audit()` 是**旁路**，契约是「绝不阻断业务、绝不变慢业务」。
   在里面做 DELETE，等于把「审计表的体量」变成「业务写操作延迟」的隐式函数
   —— 表越大业务越慢，**且没有任何地方会报错**。
2. 清理的失效必须**可被看见**。定时任务里，跑没跑 / 删了多少是一等公民
   （日志 + 指标 + 返回值）；散在写路径里则无从观测。

### 2.3 保留期**下限钳到 1 天**，且方向是「错得轻」的一侧

配置写成 `0` / 负数时，若不钳住，本任务退化成「每次清空全表」——
**不可逆的数据销毁**，而「配置写错」不该有这个后果。
钳到 1 而不是钳到 90：真要清干净的人会**立刻发现**「怎么只删了 1 天前的」
（可观测、可回退）；钳到 0 那一侧的后果是「整表没了」。⇒ 选错得轻的一侧。

### 2.4 任务名是**字面量**，两处由门禁钉住（不是靠注释提醒）

`core` 不得 import `modules`（既有分层铁律），所以 beat 表里的任务名与
`tasks.py` 的常量必然构成「同一事实两份写法」。写错的现象是
「审计表只增不减，且日志里一条都没有」——「没人消费」本身不是错误，
所以**什么都不发生**。⇒ `test_beat_task_name_equals_task_constant` 钉住。

### 2.5 失败**不吞**，且两个出口都要有

- `except` 里**先记指标再 `raise`**：Celery 的 FAILURE 只活在 worker 日志与
  结果后端里（`result_expires=3600`），指标才是**长期**告警的载体；
  `raise` 保证任务被标 FAILURE，而不是伪装成「删了 0 行」。
- 告警是**两条方向相反**的规则：`Failing`（跑了但抛错）+
  `Stalled`（压根没跑）。只留前者的话，「beat 没起 / 任务名两处不一致」
  这类**完全不产生任何指标**的故障永远不会被报出来。

### 2.6 落脚点为什么是 `core/audit/` 而不是新建 `modules/audit/`

计划点名照 `login_guard.purge_old_attempts` 的范式 —— 它住在 **`core/identity/`**。
审计的内核（模型 / 写路径 / 读口 / 清理核）整体已在 `core/audit/`，
清理只是它自己的编排。新建 `modules/audit/` 会得到一个**不含任何业务代码**的空壳域，
还要额外动 `test_module_facades.py` 的门面登记。

---

## 3. 验证证据

| 验证 | 结果 |
|---|---|
| `pytest tests/test_audit_retention_gate.py tests/test_core_internal_layering.py` | **21 passed**，`EXIT=0` |
| `pytest tests/test_audit_gate.py test_alert_rules_gate.py test_memory_distill.py test_billing_schedule.py test_trade_schedule.py test_core_layering.py` | **46 passed**，`EXIT=0` |
| `pytest tests/test_llm_metrics.py test_module_layering.py test_module_facades.py` | **EXIT=0** |
| 分层图对账（探针现算，非手写） | 新增 **恰好 3** 条边、**0** 条消失；SCC 仍 **1** 个；孤立单元仍 **3** 个 |
| **反向注入 8 组** | 8/8 **恰好**命中预期用例，文件 md5 **逐字节还原**，`REVERSE_EXIT=0` |
| **端到端真跑**（真库 + 真任务入口 + 连调两次） | **9/9 通过**，`E2E_EXIT=0` |
| 告警 YAML 结构（PyYAML 解析） | 4 组、audit 组 3 条规则、每条都有 `expr` |
| 新建文件行尾 | 纯 CRLF（与 `backend/` 基线一致，脚本显式归一） |

### 3.1 反向注入明细（每条都要求「恰好预期那条红」）

| 注入 | 改动 | 实际红 | 还原 |
|---|---|---|---|
| I1 | beat 表任务名改一个字符 | `test_beat_task_name_equals_task_constant` | OK |
| I2 | autodiscover 删掉 `"core.audit"` | `test_task_is_registered_by_autodiscover` | OK |
| I3 | 任务体改成 `deleted = 0`（空壳） | `test_task_body_actually_calls_the_purge_kernel` | OK |
| I4 | 清理核 `< cutoff` → `> cutoff` | `test_purge_deletes_only_rows_past_the_retention_window` | OK |
| I5 | 调度条目删掉 `options.queue` | `test_the_entry_declares_a_queue` | OK |
| I6 | `except` 里去掉了 `raise`（吞异常） | `test_task_does_not_swallow_exceptions` | OK |
| I7 | 在 `service.py` 塞入第二处 `delete(AuditLog)` | `test_audit_rows_are_deleted_only_in_the_retention_module` | OK |
| I8 | 去掉保留期下限钳位 | `test_retention_cutoff_clamps_low_values` | OK |

### 3.2 端到端真跑（`r329_e2e_purge.py`）

造 1 行 200 天前 + 1 行「今天」，调**任务入口本身**、**连调两次**：

```
[OK] beat 条目 task='audit.purge_expired' schedule=<crontab 5:7> 下次触发≈…
[OK] 任务已注册：audit.purge_expired
[OK] 任务返回：{'ok': True, 'deleted': 1, ...} / {'ok': True, 'deleted': 0, ...}
  [OK] 200 天前的行被删      [OK] 今天那行**留下**了
  [OK] runs{ok} 恰好加 2     [OK] runs{failed} 未增长
  [OK] deleted 行数指标累计 >=1   [OK] 总行数只少 1（没误删真实数据）
```

**连调两次**是刻意的：`asyncio.run()` + 应用级连接池的坑正是
「第一次成功、第二次必挂」，且**单次验证会全绿放行**。
本文件用**每线程常驻 loop**（与 `modules/memory` / `modules/trade` 同款）。

---

## 4. 判据自身的缺陷（这批踩到的，值得记）

1. **行为用例差点变成数据破坏者**：`purge_expired` 是**全局**删除
   （按 `created_at`，不按租户 —— 这正是保留期任务该有的语义）。
   若门禁真的 `commit` 一次，它会把共享库里所有超过 N 天的**真实**审计行删掉。
   ⇒ 改成「插自造行 → 在新会话里跑清理并断言 → **rollback**」。
   副产品：顺带把「只删不提交」这条契约也钉住了。
2. **「钳位」这个唯一不可逆的判断，不能靠真删验证**：原计划用一次真删来验
   「配成 0 会怎样」。⇒ 抽出纯函数 `retention_cutoff()`，
   改成**零副作用的算术断言**。
3. **字符串里的 ASCII 双引号把文件打成 SyntaxError**：中文论述里写
   `（每天"成功"一次）` 时，那对引号落在 `f"..."` 内部。
   ⇒ 文件内一律用中文引号「」，并先 `ast.parse` 自检再跑。
4. **探针与任务共用全局连接池 = 探针伪影**：探针的 loop 与任务的线程 loop
   若共用池，会造出「attached to a different loop」——
   那是**共享池**才有的问题，生产里 worker 与 API 是**两个进程**。
   ⇒ 探针侧一律用**自带 NullPool 引擎**，两条 loop 彻底隔离。
5. **`Write` 工具恒以 LF 落盘，`Edit` 保留 CRLF**（实测）：
   `backend/` 全是纯 CRLF ⇒ 新建文件必须显式归一，否则下次 diff 整文件改写。

---

## 5. 未做项（未擅自展开）

- **P0-6**（`modules/amazon_sp/` 未挂载）、**P0-7**（`prompt_versions` 覆写层，任务 #992）、
  **P0-9**（`LICENSE*`）—— 本轮一律不动。
- 记忆结算（`check_budget.py` WARN）仍属独立任务。

### 5.1 顺手发现的同类缺陷（**本轮未动**，建议单列任务）

`purge_old_attempts`（`core/identity/login_guard.py`）与
`purge_spent_tokens`（`core/identity/email_tokens.py`）**在生产代码里零调用点**
—— 只有测试调。也就是说计划里点名的那个「范式」本身，
**恰恰是本轮要避免的那种形态**：函数写好了、幂等、有行为测试，
但没有任何东西会去调用它。

本轮审计这边的做法是：**不照抄「只写个函数」**，
而是把「真的接上了调度」变成判据。
那两张表是否也接同一个 beat 时段（或并入本任务），建议作为独立任务评估
（改动点同在本轮已改的 `core/redis.py::beat_schedule`，代价很低）。

---

## 6. 建议的下一步

1. ~~**修掉 2 处既存 alembic 偏差**（任务 **#1201**，本轮计划的第 3 项）：
   `skills.icon` nullable 方向待判、`stores_store.is_demo` comment。
   验收：`alembic check` / `compare_metadata` **零偏差**（用 `(op, table, column)`
   三元组，不要只信 repr）。~~
   → **第 330 轮已结清（迁移 `k7e2c4f1b849`）**，见 `docs/round-330-alembic-reconcile.md`。
   ★ 结清时发现原估值严重偏低：本处写的「2 处」只是**开发库口径**；
   **纯 `alembic upgrade head` 建出的全新库报 14 处**（并集 **16**）⇒ CI 的这道门禁
   从第 181 轮起就没绿过。**判 schema 漂移不能只跑一个库。**
2. （可选）给上面 5.1 两处死代码接线 —— 同一 beat，低代价。
3. （可选）`audit_logs` 若长到千万级，再考虑**分区表**替换 DELETE
   （本轮已把清理收口到单一模块，届时替换点只有一处）。
