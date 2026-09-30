# 身份域保留期清理 —— 交付说明（第 331 轮 #1202~#1206）

> 起点：第 329 轮 §5.1「顺手发现的同类缺陷（本轮未动）」——
> `core/identity/login_guard.py::purge_old_attempts` 与
> `core/identity/email_tokens.py::purge_spent_tokens` **写好了、幂等、也有行为测试，
> 但生产代码里零调用点**（只有测试调）。于是两张表的实际行为是**只增不减**。
>
> 本轮拍档为「全做」：接线 + 补保留期配置 + 裸 SQL 收口到 ORM + 指标/告警 + 门禁。

---

## 1. 交付物

| # | 文件 | 动作 | 要点 |
|---|---|---|---|
| 1 | `core/identity/tasks.py` | **新增** | Celery 接线：任务名常量 + 每线程常驻 loop + 一次会话内清**两张表** + 一次 commit + 指标/日志双出口 + 异常不吞 |
| 2 | `core/identity/retention.py` | **新增** | 保留期**纯函数**（唯一钳位实现）+ 两个表各自的默认值包装 |
| 3 | `core/identity/login_guard.py` | 改 | `purge_old_attempts`：裸 SQL → ORM `delete(LoginAttempt)`；cutoff 走共享纯函数 |
| 4 | `core/identity/email_tokens.py` | 改 | `purge_spent_tokens`：裸 SQL → ORM `delete(EmailToken)`；`older_than_days` 默认从 `7` 改为 `None`（读配置） |
| 5 | `core/config.py` | 改 | 新增 `email_token_retention_days = 7`（改前**根本不存在**，保留期硬编码在函数签名里） |
| 6 | `core/redis.py` | 改 | `autodiscover_tasks` 加 `"core.identity"`；新增 `IDENTITY_PURGE_HOUR/MINUTE`（**5:17**）；beat 加一条 |
| 7 | `core/observability/metrics.py` | 改 | `IDENTITY_PURGE_RUNS{status}` + `IDENTITY_PURGE_DELETED{table}`，并注册进 `_REGISTRY`（16 → **18**） |
| 8 | `observability/alert_rules.yml` | 改 | 新分组 `storekeeper-identity`：`IdentityPurgeFailing`（critical）+ `IdentityPurgeStalled`（warning） |
| 9 | `tests/test_identity_retention_gate.py` | **新增** | 门禁 **17 条**（形态 7 + 行为 3 + 自检 5 + 配置 2） |
| 10 | `tests/test_core_internal_layering.py` | 改 | 登记 3 条新 import 期边 + 文件头新增一节 + 实测值复算 |
| 11 | `core/identity/__init__.py` | 改 | 0 字节 → 注释（说明**刻意不** re-export `tasks` 的理由） |

## 2. 关键设计决策（含被否方案）

### 2.1 两张表共用一个任务 + **一个事务**（被否：两条 beat 条目）

两个清理核都刻意「只删、不 commit」（那样测试能把它塞进自己的事务回滚）。
若各开一个会话各自 commit，就会出现「登录审计删了、token 没删，而任务报成功」
—— **一半成功比全失败更难发现**。放进同一个会话后，commit 是唯一落地点：
要么两张表都清完，要么都不清。

代价是"删了多少"混在一个返回值里 ⇒ 用**带 `table` 标签**的指标拆开，
信息没丢，而"哪张表在涨"仍然问得出来。

### 2.2 「钳位 + 算 cutoff」收口成**一份**纯函数（这是顺带修掉的缺陷）

改前两个清理核各写了一遍：

```python
# login_guard.purge_old_attempts          # email_tokens.purge_spent_tokens
days = int(retention_days or config.login_attempt_retention_days)   # older_than_days
cutoff = utcnow() - timedelta(days=max(1, days))                    # max(1, older_than_days)
```

看着"差不多"，但**有一处实质不同**：左边用 `or`（显式传 0 会退回配置值），
右边直接用（传 0 会钳成 1）。这类「同一判定两份实现」在本仓已登记多次，
结论固定：**至少有一份永远测不到**，而漂移方向恰好是「哪一天少钳了一点」。

⇒ 抽成 `retention.py::retention_cutoff()`（纯函数）。收益有两层：
① 不可逆后果只由一处代码产生；② 门禁能用**纯算术**钉住方向与下限，不必对共享库
真删一次（那会把历史行真删掉——「验证代码的测试」不该有这种副作用）。

★ 显式记录一处**语义变更**：`retention_days=0` 改前 → 用配置值（30 天），
改后 → 钳成 1 天。两个方向都不可逆，取"与 `core/audit/retention.py` 同一条规则"
以消歧；实测全仓**没有任何调用点传 0**。

### 2.3 裸 SQL → ORM `delete()`：表名只能有**一份真源**

```python
text("DELETE FROM email_tokens WHERE ...")   →   delete(EmailToken).where(...)
```

理由不是"ORM 好看"：裸 SQL 里表名是**第二份真源**，写错时的现象是
**「删了 0 行」，与「没有过期行」长得一模一样**，而且不报错。
`core/audit/retention.py` 在 r328 为此定过同款规矩，本轮把它推广到这两张表。

★ 附带修掉一个隐患：改前 `purge_spent_tokens` 里 `:now` 与 `:cutoff` 是**两次独立的
`utcnow()`**；现在共用同一时刻（"刚过期"的行不会在两段条件里得到不一致的判断）。

### 2.4 `email_token_retention_days` 为什么是配置、且默认 **7** 天

- **为什么必须是配置**：同一件事三张表两种形态本身就是缺陷 ——
  `login_attempts` 有 `login_attempt_retention_days=30`、
  `audit_logs` 有 `audit_retention_days=90`，只有它在函数签名里写死。
  保留期是运维/合规参数，要能改环境变量当天生效。
- **为什么默认 7 天（比另两张短得多）**：token 在 `used_at` 非空或 `expires_at`
  过期之后**再无任何用途**（一次性凭据，永远不会再被读）。它不像登录审计那样
  "留久点能复盘"；留久只是把"用户点过几次重发"的隐私残留堆在库里。

### 2.5 触发时刻 **5:17**，且**不**与审计合并

- 分钟 **17**：避开 `billing-expire-pending` 的 `*/5` 边界，也不与审计的 7 撞车；
- 小时 **5**：与审计同一条理由 —— 3:00 memory / 3:20 billing 巡检 / 4:30 支付对账
  之后，"删多少行"才不会被当天尚未收敛的写入搅动。
- **为什么不合成一个任务**：四张表的清理混在一个任务里，出问题时"是哪一半挂了"
  只能靠猜；分成两条 beat 条目后各自的指标/告警天然分开。

### 2.6 指标的标签值取自 `Model.__tablename__`（不手写字面量）

`IDENTITY_PURGE_DELETED.inc(rows, table=model.__tablename__)` ——
与 2.3 同一条思路：表名只有一个真源，改名时指标不会静默失配。

### 2.7 失败**不吞**，且两个出口都要有

`except` 里先 `IDENTITY_PURGE_RUNS.inc(status="failed")` 再原样 `raise`。
若改成"捕获后返回删除 0 行"，「这次失败了」与「这次没有过期行」在结果里
长得**一模一样** —— 那正是"假成功"。

## 3. 验证证据（全部是真实退出码 / 真实读数）

### 3.1 反向注入 **13 条**（台架：`.workbuddy/probes/r331_reverse_injection.py`）

逐条把被测代码改坏 → 跑门禁 → 记录**哪一条用例转红** → 从自己保存的字节还原
（禁 `git checkout` 式还原）→ sha256 复核"已完全还原"。

| 注入点 | 打红的用例 |
|---|---|
| ① `core/redis.py` 那条 `"task":` 改一个字符 | `test_beat_task_name_equals_task_constant` |
| ② autodiscover 列表删掉 `"core.identity"` | `test_task_is_registered_by_autodiscover` |
| ③ `_purge_once()` 换成 `return {}` | `test_task_body_actually_calls_both_purge_kernels` + `test_purge_kernels_are_wired_exactly_once` |
| ④ `_purge_once` 里删掉 `purge_spent_tokens` 调用 | 同上两条 |
| ⑤ `_purge_once` 里去掉 `await session.commit()` | `test_task_body_actually_calls_both_purge_kernels` |
| ⑥ `login_guard.py` 里 `created_at < cutoff` 改 `>` | `test_login_attempt_purge_deletes_only_rows_past_retention` |
| ⑦ `email_tokens.py` 里**外层** `AND` 改 `OR_` | `test_email_token_purge_keeps_unspent_unexpired_rows`（D 行） |
| ⑧ 调度条目删掉 `"options": {"queue": ...}` | `test_the_entry_declares_a_queue` |
| ⑨ `_purge_once` 里多调一次清理核 | `test_purge_kernels_are_wired_exactly_once`（计数 2） |
| ⑩ 清理核换回裸 SQL | `test_each_table_has_exactly_one_delete_path` |
| ⑪ `except` 里 `raise` 换成 `return {"ok": False}` | `test_task_does_not_swallow_exceptions` |
| ⑫ `_run_sync(_purge_once())` 换 `asyncio.run(...)` | `test_task_module_does_not_use_asyncio_run` |
| ⑬ `email_token_cutoff` 默认值写死回 `7` | `test_defaults_come_from_config` |

13/13 全部至少打红一条，且打红位置与预测一致；还原后**基线复绿**
（台架自带"注入是否真的扎进去"的前置断言 —— 否则"没扎进去"会被误读成"门禁没牙齿"）。

### 3.2 端到端真跑（`.workbuddy/probes/r331_probe_e2e.py`）

```
保存期：login_attempts=30 天 / email_tokens=7 天
[第 1 次] 返回 = {'ok': True, 'deleted': {'login_attempts': 0, 'email_tokens': 0}, 'elapsed_ms': 97}
跑后：login_attempts=3169 行（最老 2026-09-16 14:34）/ email_tokens=1 行（最老 2026-09-30 04:39）
[第 2 次] 返回 = {'ok': True, 'deleted': {'login_attempts': 0, 'email_tokens': 0}, 'elapsed_ms': 8}
指标增量：{'runs_ok': 2.0, 'runs_failed': 0.0}
★ 连跑两次均成功（同一常驻 loop）= True
    identity_purge_runs_total{status="ok"} 2
```

- **连跑两次**是刻意的：`asyncio.run()` 的坑正是「第一次成功、第二次必挂」，
  单次运行会全绿放行 ⇒ 第二次调用才是那条判据的**行为证据**。
- 真库删 0 行符合预期（本机最老数据 14 天 / 今天，而保留期 30 天 / 7 天）；
  跑前跑后行数一致 ⇒ 真实数据未被误动。
- ★ 行为门禁另有 3 条在**真库**上验边界（过期行删掉 / 期内行留下 / 未消费未过期的
  token 必须留下），全部在**未提交的事务**里跑完再 rollback。

### 3.3 回归（真实退出码）

| 批次 | 文件 | 结果 |
|---|---|---|
| 1 | `test_identity_retention_gate` / `test_audit_retention_gate` / `test_audit_gate` / `test_core_internal_layering` / `test_core_layering` / `test_alert_rules_gate` / `test_billing_schedule` / `test_trade_schedule` / `test_ci_gate_coverage` / `test_schema_parity` | rc=0，**84 passed, 1 skipped** |
| 2 | `test_auth_security_p1b` / `test_context_propagation` / `test_conversation_ownership` / `test_default_account` / `test_facade_monkeypatch_targets` / `test_import_boundaries` / `test_intent_single_source` / `test_demo_identity` / `test_identity_endpoint_auth` / `test_llm_metrics` | rc=0，**143 passed** |

另单独跑：`scripts/check_alert_rules.py` → `RESULT: PASS（17 条规则引用的 13 个指标全部真实且有人写入）`，rc=0；
`observability/alert_rules.yml` 用 YAML 解析器复核过（5 个分组、折叠标量正常）。

### 3.4 分层台账代价（精算到边，不是估）

新增 `core/identity/retention.py` + `tasks.py` 后：

```
core/**/*.py = 61（原 59）；unit = 21（不变）
import 期边  = 50（原 47，+3：identity -> {logger, observability, redis}）
函数内边     = 10（不变）
含环的强连通块 = 1 个（不变，仍 {auth, identity, stores}）；孤立单元 = 3 个（不变）
```

`identity -> redis` **不构成环**：`core/redis.py` 只 import `config`，
不 import `core.identity` ⇒ 单向边。三条新边与 `audit -> {config, logger, redis}`
同族（是「清理」这个能力的**定义性依赖**，不是"顺手拿一下"），
理由写进了 `test_core_internal_layering.py` 文件头的新一节。

## 4. 判据自身的缺陷（本轮踩到 / 修掉的，值得记）

1. **探针用自己的坑喂给自己**：v1 在调用任务前先 `asyncio.run(_row_counts())`
   数体量 ⇒ 那条连接绑在临时 loop 上，`asyncio.run` 把 loop 关掉，任务再用自己的
   常驻 loop 去池里取同一条连接 ⇒ `AttributeError: 'NoneType' object has no attribute 'send'`
   （proactor transport 已随旧 loop 报废）。**这不是产品缺陷** ——
   生产 worker 里没人会先 `asyncio.run` 一把。修法：全程走任务自己的 `_run_sync`。
   ⇒ 教训：**先判"是探针的锅还是产品的锅"，再改产品**。
2. **SCC 口径错**：探针把 `top | fn` 喂给 SCC 判定，报出
   `['audit','auth','database','identity','stores']` 与 `['logger','observability']`
   两个**不存在**的块 —— 混层会造出跨层假环。门禁的口径是**只喂 import 期边**。
   已把这条写进 `test_core_internal_layering.py` 文件头的实测值一节。
3. **CRLF / LF 混存**：`core/redis.py` / `login_guard.py` / `email_tokens.py` 是 CRLF，
   本轮新建的 `tasks.py` / `retention.py` 是 LF。注入台架最初用 `\n` 写针
   ⇒ 命中 0 次 ⇒ 会被误读成"门禁没牙齿"。台架因此加了行尾自适应。
4. **bytes 字面量不能含中文**（`SyntaxError: bytes can only contain ASCII literal characters`）
   ⇒ 针允许写成 `str`，台架内统一 `.encode("utf-8")`。
5. **我把一处因果写反了，实测后订正**：最初 docstring 写「`or_` 写成 `and_` ⇒ D 被删」。
   实际方向相反 ——
   · **外层** `AND` → `OR`（条件变松）⇒ D 被删；
   · **内层** `or_` → `and_`（条件变紧）⇒ B 留下、`deleted >= 2` 不成立。
   两种都实测过，门禁里的表格与断言文案已改成实测口径。

## 5. 未做项（**明确不擅自展开**）

- **P0-6** `modules/amazon_sp/` 未挂载；**P0-7** `prompt_versions` 覆写层（任务 #992）；
  **P0-9** `LICENSE*` —— 均为既存独立项，本轮未动。
- **不给 `.env.example` 加保留期键**：它与 r328 保持一致（那里也没加
  `audit_retention_days`），且全仓无 `.env.example` 与 config 的对账门禁。
  若哪天要加，应当**三张表一起加**，而不是只加本轮新引入的那个。
- **不做"已过期但未消费"与"已消费但未过期"的分列指标**：当前按表聚合已够回答
  "谁在涨"；再细分会让基数与维护面同时变大，收益不明。

## 6. 建议的下一步

1. **部署后 50 小时内 `IdentityPurgeStalled` 会响一次属正常**（还没有第一个 5:17）——
   与 `MemoryDistillStalled` / `AuditPurgeStalled` 同款提示，别当成故障。
2. 观察 `identity_purge_deleted_rows_total{table="login_attempts"}` 的**累计斜率**：
   它约等于登录审计表的真实增长速率上界。本机开发库现状是 14 天 **3169** 行
   —— 这正是"这条链此前一次都没跑过"的量化证据。
3. 若哪天 `login_attempts` 长到千万级，再评估**分区表 / 批量删除**
   （单次 `DELETE` 全表扫会持锁较久）—— 与 r329 §6 第 3 项同一条，标"可选"。
4. `pytest` 全量跑仍会在**会话收尾**卡住（r329/r330 已记），
   本轮的回归证据一律取自**分批 + 退出码**，不依赖全量一次跑完。
