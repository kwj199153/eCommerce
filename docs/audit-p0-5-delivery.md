# P0-5 通用审计日志 · 交付说明（第 327 轮）

> 复评报告 §9 的**第三步**。前两步（P0-4 compose 明文口令/5432、P0-2 备份 + P0-3 告警）已交付。
> 本轮范围：**只做 P0-5**；P0-6 / P0-7 / P0-9 未动（见文末）。

---

## 1. 交付物（12 个文件）

| 类别 | 文件 | 说明 |
|---|---|---|
| **新内核** | `backend/core/audit/__init__.py` | 包门面（`__all__`；**刻意不导出 router**，避免把鉴权链拉进 import 期） |
| | `backend/core/audit/actions.py` | 动作目录**唯一真源**：7 个动作 + 结果/目标类型枚举 |
| | `backend/core/audit/models.py` | `AuditLog`（`audit_logs` 表，**零外键**，3 个索引） |
| | `backend/core/audit/service.py` | `record_audit()` —— **唯一写入路径**，自带会话 |
| | `backend/core/audit/router.py` | 仅平台超管可读：`GET /logs`（分页 + 6 种过滤）、`GET /actions` |
| **新迁移** | `backend/alembic/versions/j6c4b9e1f3a5_audit_logs.py` | `down_revision='i5b3a8d0e2c4'`，`_has_table` 幂等守卫 |
| **新门禁** | `backend/tests/test_audit_gate.py` | 14 项（形态 A1~A4 / 行为 B1~B4 / 自检 C1~C2） |
| 改 | `backend/core/database.py` | `register_all_models()` 登记 `AuditLog` |
| 改 | `backend/core/observability/metrics.py` | 新增 `audit_records_total` / `audit_write_errors_total` |
| 改 | `backend/core/auth/dependencies.py` | `get_admin_user` 收口到真源 `is_platform_admin()` |
| 改 | `backend/core/identity/router.py` | 登录成功 → `login.success` |
| 改 | `backend/core/auth/accounts_router.py` | `update_member` / `remove_member` |
| 改 | `backend/modules/stores/router.py` | connect（成功 + 被拒）/ disconnect / transfer / delete（成功 + 被拒） |
| 改 | `backend/main.py` | 挂载审计读口 |
| 改 | `backend/tests/test_core_internal_layering.py` | 登记 9 条新边 |
| 改 | `observability/alert_rules.yml` | 新增 `AuditWriteFailing` |

**审计覆盖的 7 类写操作**：登录成功 · 连接店铺 · 断开店铺 · 转移店铺归属 · 删除店铺 · 修改成员 · 移除成员。
（其中「被平台拒绝的凭据」「被外键拦下的删除」记 `status=failure` —— 审计问的是「谁试过」。）

---

## 2. 五个关键设计决策（含被否方案）

| 决策 | 选了什么 | 否掉了什么 / 为什么 |
|---|---|---|
| **外键** | `actor_id` 裸列 + 索引，**不指 `users`** | `CASCADE` ⇒ 删号即清痕迹；`SET NULL` ⇒ 丢归属。审计必须**比主体活得久** |
| **事务** | `record_audit` **自带会话**，与请求事务解耦 | 挂在请求事务上 ⇒ 业务回滚会把「尝试删除」这条审计一起回滚，而"谁试过"最需要留痕 |
| **失败处理** | **不抛** + 三处出口（`logger.error` / 指标 / 返回 `False`） | 抛 ⇒ 审计抖一下拖垮全站写操作；吞 ⇒ 「审计悄悄停了」无人知道 |
| **目标列名** | `target_type` + `target_id` | 叫 `shop_id` 会触发 `test_schema_parity` 的「必须指向 stores_store」不变量，与「零外键」直接冲突 |
| **导入时机** | 消费方**函数内** import `core.audit` | 顶层 import 会立刻形成 `auth ⇄ audit`、`identity ⇄ audit` 两个环。实测 SCC **恰好仍是 1 个** |

**附带收口**：`get_admin_user` 原先硬编码 `role.value != "admin"`，与真源 `accounts.is_platform_admin()` 构成**两份实现** ⇒ 改为调用真源。审计读口因此全仓只剩**一个** admin 判定。

---

## 3. 验证证据（全部可复跑）

| 项 | 结果 |
|---|---|
| `tests/test_audit_gate.py` | **14/14 PASS**（含连库的「写入 → 读口读回」闭环、匿名 401 / 普通 403 / 超管 200 三分档） |
| 反向注入（4 次） | **4/4 全部转红**，且文件 **md5 字节级还原**（`.workbuddy/probes/r327_audit_reverse_injection.py`） |
| 受影响门禁组 | 批 1 **34/34**、批 2 **21/21** |
| 迁移 | `alembic heads` 单 head = `j6c4b9e1f3a5`；`upgrade head` 真跑 `i5b3a8d0e2c4 → j6c4b9e1f3a5`；**第二次 upgrade 无 Running 行**（幂等） |
| `alembic check` | **开发库口径**：仅 2 处**既存**偏差（`skills.icon` nullable / `stores_store.is_demo` comment，均非本轮）；`audit_logs` **零偏差** ★ 第 330 轮订正：**全新库口径报 14 处**（并集 16）⇒ 上面这句只是半个答案，见 `docs/round-330-alembic-reconcile.md` |
| 行尾 | 16 个文件全部与各自目录基线一致（字节级复核） |

反向注入的 4 个注入点：摘掉读口门禁 / 制造第二处 `AuditLog(...)` / 动作名改裸字符串 / 删掉失败分支的指标 inc。

---

## 4. 本轮发现的 4 个「判据自身缺陷」（值得单独记住）

1. **计数断言凭印象写**：`Depends(get_admin_user)` 实测命中 **3** 次（文件头 docstring 里也有）、`accounts_router` 的 `request: Request` 是 **3** 处、stores 审计点实为 **6** 个。
2. **`grep -c $'\r'` 是恒真判据**（Git Bash 下 `$'\r'` 展开为空串 ⇒ `grep -c ''` 匹配所有行）。它把 4 个 LF 文件判成了 CRLF-OK。
3. **Write 工具写 LF、脚本写 CRLF** —— 本仓 CRLF/LF 混存的直接来源 ⇒ 新建文件后**必须**跑字节级归一化。
4. **shell heredoc 里的反斜杠被多吃一层** ⇒ 探针必须落文件再跑（本仓已有此铁律，本轮再次中招）。

---

## 5. 未做项（不在本轮指令范围）

| 项 | 状态 |
|---|---|
| P0-9 `LICENSE*` | 未动 |
| P0-7 `prompt_versions` 覆写层 | 未动（任务 #992） |
| P0-6 `modules/amazon_sp/` 未挂载 | 未动 |
| 记忆结算 | `check_budget.py` 报 WARN（`MEMORY.md` 100% / `_pending` 34 份）—— 属独立任务 |

## 6. 建议的下一步

1. **前端接入**读口（`/api/v1/audit/logs` + `/actions`）—— 目前只有后端能力，管理界面尚未接。
2. **保留期清理**：`audit_logs` 会随写操作稳定增长，建议加一个 Celery beat 任务（照 `login_guard.purge_old_attempts` 范式）或分区表。
3. ~~**修掉那 2 处既存 alembic 偏差**（`skills.icon` / `stores_store.is_demo`）—— 需要一条新迁移，建议单独一轮做。~~
   → **第 330 轮已结清**（迁移 `k7e2c4f1b849`）。实际是 **16 处**（开发库 2 + 全新库 14 的并集），
   见 `docs/round-330-alembic-reconcile.md`。
