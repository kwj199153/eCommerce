# 项目复审 r332 —— 重锚 `technical-diligence-review-20260930.md`

> **复审对象**：`docs/technical-diligence-review-20260930.md`（22,650 B，写于 **2026-09-30 11:26**）
> **复审轮次**：r332
> **判据来源**：**磁盘实读（工作树）**，每条附 `文件:行`；测试读数走 `--junitxml`（本仓铁律）
> **方法学约束**：判据**禁「源码字符串包含」**（承 20260930 报告 §5 的教训：裸 `grep "if shop_id"` 把 11 处注释数成越权面）；凡「有没有实现」一律**逐条打开 / 走 AST / 查消费点**
> **不变式**：**判据以磁盘为准，不信任会话快照**

---

## 0. 结论摘要（TL;DR）

20260930 报告判 **P0-2/3/4/5 未修**，与磁盘现状**不符**。根因不是"判错"，而是**报告是 11:26 的快照，而这几项修复是此后 24 分钟 ~ 5 小时才落地的**（见 §2 时间线）。报告发布后从未回头更新。

**重新判定：9 项 P0 → 已修 5 / 部分修 3 / 未修 1**

| 判定 | 项 | 数量 |
|---|---|---:|
| ✅ **已修**（能力完整、有消费点、有门禁） | P0-1 / P0-3 / P0-4 / P0-5 / P0-8 | **5** |
| ⚠️ **部分修**（机制在，关键一环缺） | P0-2 / P0-6 / P0-7 | **3** |
| ❌ **未修** | P0-9 | **1** |
| ✅ 次级 P0-10（无 CD）→ **本轮已修**（见 §10） | P0-10 | — |

**同时新发现 1 处 P0 级回归**（§4）：`stores/router.py` 漏 import `STATUS_SUCCESS` ⇒ **店铺 connect 端点成功路径必 500**。**当前工作树是红的**（7 条用例失败，全为这一根因），**修掉之前本次交付不可上线**。
>
> ✅ **该回归已于 09-30 17:18 修复并三重验证通过（见 §4.6）**：修复前 7 FAILED → 修复后 27/27 PASSED、全仓 AST 未定义名 1 → 0 处、反向注入往返逐字节复原。

---

## 1. 复审方法

1. 以 20260930 报告为**基线**，但只把它当作"待验证的假设"，逐条对磁盘取证。
2. 每个 P0 取**三类证据**：①机制是否存在（文件/类/函数）②是否被**消费**（调用点）③是否有**门禁/测试**守着（防回流）。
3. 全量测试用 `--junitxml` 落盘解析（`.workbuddy/probes/r332_full.xml`），不读 stdout 汇总行（本仓实测过 pytest 卡 session 收尾 ⇒ 无最终统计行）。
4. 时间戳用于回答"报告的判定在其写作时刻是否为真"。

---

## 2. 报告为何过期：时间线铁证

| 时刻（09-30） | 事件 | 含义 |
|---|---|---|
| **11:26** | `docs/technical-diligence-review-20260930.md` 定稿 | 报告快照点 |
| 11:50 | `backend/scripts/backup_db.py` 落盘（23,801 B） | **P0-2 修复在报告之后** |
| 11:52 / 11:54 | `observability/prometheus.yml` / `alertmanager.yml` | **P0-3 修复在报告之后** |
| 11:56 | `docker-compose.yml` 改写（口令外置 + 端口回环） | **P0-4 修复在报告之后** |
| 12:03 ~ 13:24 | `backend/core/audit/`（`__init__/actions/models/router/service/retention/tasks`） | **P0-5 修复在报告之后** |
| 13:50 | `docs/audit-p0-5-delivery.md` / `docs/audit-retention-delivery.md` | P0-5 交付文档 |
| 16:26 | `backend/core/config.py`（P0-4 弱口令护栏） | P0-4 收口 |
| 16:29 | `observability/alert_rules.yml`（16,100 B） | P0-3 补齐 |
| 16:40 | `backend/core/identity/retention.py` / `tasks.py` | r331 |

⇒ **报告对 P0-2/3/4/5 的"未修"在其写作时刻是真的，但在写完后 24 分钟起就被逐条推翻，却无人更新报告**。这正是"重新审查"的价值：把结论重锚到磁盘。

> ★ 附带教训：**一份尽调报告的"实读"结论有保鲜期**。它必须带 **git 工作树指纹（`git stash create` 的 tree hash 或 `git status --porcelain | sha256`）**，否则读者无法判断它比当前分支旧了多少。本报告 §8 给出建议。

---

## 3. P0 逐条重锚（9 + 1）

| # | 阻断项 | 20260930 判 | **r332 磁盘实读** | 关键证据（文件:行） |
|---:|---|:---:|:---:|---|
| **P0-1** | 3 处读端点跨租户越权 | ✅ 已修 | ✅ **已修（复核通过）** | `platform_rules/service.py:249/292/314/346` 五处**无条件** `scoped()`，无 `if shop_id:` 分支；修复理由以注释就地留存 |
| **P0-2** | 零数据库备份 / 无 PITR | ❌ 未修 | ⚠️ **部分修** | ✅ 脚本在：`backend/scripts/backup_db.py`（585 行，`backup`/`verify`/`drill`/`restore`/`prune` 五子命令 + 双重复核 + 原子写 + sha256）；❌ **未接 beat 调度**（`core/redis.py:171-262` 七条任务无备份）；❌ `wal_level`/`archive_mode`**全仓零命中**（无 PITR）；❌ 无异地/对象存储 |
| **P0-3** | 零告警 | ❌ 未修 | ✅ **已修（超标）** | `observability/alert_rules.yml` = **5 分组 / 16 条规则**；`prometheus.yml` 双出口抓取（api:8000 + worker:9100）；`alertmanager.yml` 分 severity 路由 + 抑制规则；`docker-compose.yml:274-312` 起 prometheus/alertmanager；门禁 `scripts/check_alert_rules.py` **实测 PASS（RC=0）** |
| **P0-4** | compose 明文口令 + 5432 全网卡 | ❌ 未修 | ✅ **已修** | `docker-compose.yml:77` `${POSTGRES_PASSWORD:-123456}`（插值）；`:83` `"127.0.0.1:5432:5432"`（回环）；`:148/185/237` `${DATABASE_URL:-...}`；**`core/config.py:334-351` 生产弱口令护栏**（命中 `123456/postgres/password/root/admin` ⇒ 拒绝启动）；`core/security/credentials.py` 凭证 Fernet 加密（`enc:v1:` + 缺密钥拒绝写入） |
| **P0-5** | 无审计日志 | ❌ 未修 | ✅ **已修** | `backend/core/audit/` 完整包：`models.py`（`audit_logs` 表，append-only 论证）、`actions.py`（动作目录唯一真源）、`service.py`（`record_audit` 唯一写路径，独立会话）、`retention.py`（唯一删除路径）、`tasks.py` + `router.py`（读口，超管专属）；迁移 `alembic/versions/j6c4b9e1f3a5_audit_logs.py`；`core/redis.py:238-242` 接 beat；告警 `alert_rules.yml:209/230/248` 三条；写入口 `stores/router.py:1025-1034` |
| **P0-6** | SP-API 授权链路未实现 | ❌ 未修 | ⚠️ **部分修（原判定问错了形态）** | ✅ 真实落点不是 `amazon_sp/router.py`，而是 **`modules/stores/connect/`**：`base.py`(ABC) + `registry.py` + `signing.py` + `platforms/{amazon,shopee,shopify,tiktok}.py`，`stores/router.py:49-61` 经 `get_connector()` 取用；❌ 残留 **`amazon_credentials` / `amazon_auth_logs` 两张零写入者死表**（`amazon_sp/db_model.py:34/109`，仅 `core/database.py:136` 注册，**零实例化、零 `session.add`**） |
| **P0-7** | 提示词 100% 硬编码、零版本 | ❌ 未修 | ⚠️ **部分修（原判定漏判 A 档）** | ✅ **A 档已落地且早于报告**：`ai_infra/llm/prompt_spec.py`（`PromptSpec`：version + `sha256(content)[:12]` 指纹 + `required_vars` 契约 + 重名拒绝 + 花括号配对校验），门禁 `tests/test_prompt_spec.py`（21 条，含"散落正文归位"扫描 + 扫描器自检）；❌ **B 档 DB 覆写层未做**：`prompt_versions`/`PromptVersion` 全仓零命中 |
| **P0-8** | 输出校验 / 幻觉防护缺失 | ✅ 已修 | ✅ **已修（复核通过）** | `base_agent.py:688-701` `is_llm_parse_failed()` → `success=False`；`dashscope_client.py:224/249/622` **相异结构信封** `__llm_parse_failed__`；消费点 `risk_scan.py:743`；测试 `tests/test_llm_output_validation.py` |
| **P0-9** | 无用户协议 / 隐私政策 | ❌ 未修 | ❌ **未修（确认）** | 全仓 `find` **零** `LICENSE*` / `*privacy*` / `*terms*`；前端仅 `Settings/VoiceClonePanel.vue:313` 的 `AGREEMENT_TEXT`（声音克隆同意书，**非**用户协议） |
| **P0-10** | 无 CD 流水线 | ❌ 未修 | ✅ **已修（第 333 轮，见 §10）** | 新增 `.github/workflows/cd.yml`（tag `v*` / 手动触发 → GHCR 构建 2 镜像 → SSH 部署 → 健康检查 → 失败**整组回滚**）+ `scripts/deploy/remote_deploy.sh`（幂等 / 回滚点 / 不动数据面）+ `docker-compose.yml` 的 `image:` **插值化**（`${API_IMAGE:-storekeeper-api:latest}`，默认值=原名 ⇒ 本地行为零变化）+ CI 门禁 `scripts/check-cd-assets.py`（39 项，8 类反向注入 8/8 OK）。**未启用**：缺 4 个部署机密 ⇒ 目前只构建推镜像 |

---

## 4. 【新发现 · P0 级回归】店铺 connect 端点漏 import，成功路径必 500

### 4.1 现象

全量测试 **7 条失败**，**同一根因**：

```
NameError: name 'STATUS_SUCCESS' is not defined
```

| 失败用例 | 所属面 |
|---|---|
| `test_credential_encryption.py::test_connect_with_key_stores_ciphertext_and_is_decryptable` | 凭据加密 |
| `test_credential_encryption.py::test_plain_update_does_not_wipe_credentials` | 凭据加密 |
| `test_credential_encryption.py::test_disconnect_actually_clears_ciphertext` | 凭据加密 |
| `test_store_connect.py::test_store_connect_schema_masks_secrets` | 店铺连接 |
| `test_store_connect.py::test_connect_verified_sets_connected_and_persists` | 店铺连接 |
| `test_store_connect.py::test_refreshed_token_is_persisted_but_never_returned` | 店铺连接 |
| `test_store_connect.py::test_disconnect_clears_credentials_and_state` | 店铺连接 |

### 4.2 根因（形态判据，非字符串包含）

- **使用点**：`backend/modules/stores/router.py:1028` —— `status=STATUS_SUCCESS if result.ok else STATUS_FAILURE`
- **导入块**：`backend/modules/stores/router.py:84-92`，从 `core.audit` 导入了 `ACTION_STORE_CONNECT / ACTION_STORE_DELETE / ACTION_STORE_DISCONNECT / ACTION_STORE_TRANSFER / STATUS_FAILURE / TARGET_STORE / record_audit` —— **恰好漏了 `STATUS_SUCCESS`**
- **导出侧正常**：`core/audit/__init__.py:43` import、`:71` 进 `__all__` ⇒ **问题只在消费端的 import 列表**

### 4.3 为什么这是 P0（而不是"测试环境问题"）

1. **不是环境差异** —— `NameError` 是**语法期可判**的代码缺陷，任何环境都会崩。已用 AST 面确认：`STATUS_SUCCESS` 在该模块**从未被绑定**。
2. **打在主路径上** —— Python 三元表达式**先判 `result.ok`**：
   - `result.ok = True`（**凭据正确、验证通过 = 最重要的那条路**）→ 求值 `STATUS_SUCCESS` → **NameError → 500**
   - `result.ok = False`（验证失败）→ 求值 `STATUS_FAILURE`（已导入）→ 正常记失败审计
   ⇒ **功能主路径全崩，边缘路径正常** —— 最容易被误判成"平台接口抽风"的形态。
3. **是"半成功态"**（最坏的一种）：`_save_store_credentials()` 在 `:1009` **已先落库**，`record_audit` 在 `:1025` 才崩。于是用户看到的现象是
   **「点连接 → 界面 500 → 但凭据其实已经写进库了」**；用户重试会反复覆写同一店铺凭据。
4. **归因属于本轮 P0-5 审计接线** —— `record_audit(...)` 那一块是新加的（注释 `# ★ P0-5：...` 就在 `:1023`），`status=STATUS_SUCCESS if ...` 随之引入，但 import 列表没同步补齐。**这是"新增消费点未与导入对账"的典型**（本仓铁律：改字段/加消费点 → 生产者 + 消费者双向对账）。

### 4.4 修复方案（一行，零风险）

```python
# backend/modules/stores/router.py:84-92 的 import 块
 from core.audit import (
     ACTION_STORE_CONNECT,
     ACTION_STORE_DELETE,
     ACTION_STORE_DISCONNECT,
     ACTION_STORE_TRANSFER,
+    STATUS_SUCCESS,
     STATUS_FAILURE,
     TARGET_STORE,
     record_audit,
 )
```

**验证判据**：重跑 `tests/test_store_connect.py` + `tests/test_credential_encryption.py`（11 条应全绿），并**反向注入**：删掉该 import 应重新出现同样的 `NameError`（证明判据有牙齿）。

### 4.5 取证复核（本轮实测，09-30 17:11~17:14）

为排除"报告自说自话"，本轮用三项**互相独立**的手段复核，全部落盘：

| # | 手段 | 结果 | 证据文件 |
|---|------|------|----------|
| ① | **AST 全仓扫描**未定义名（禁 grep：注释/字符串会骗过） | 扫 **564 个 .py**，未定义名**恰好 1 处**＝`STATUS_SUCCESS@1028`，全仓无同类第二例 | `.workbuddy/probes/r332_undef.txt` |
| ② | **反向注入自检**（证明判据有牙齿） | A 现状→复现 `{'STATUS_SUCCESS':[1028]}`；B 注入修复行→**归零**；C 删使用点→**归零**。判据有牙齿，RC=0 | `.workbuddy/probes/r332_undef_selfcheck.py` |
| ③ | **单跑涉事用例**（修复前基线） | `test_store_connect.py`(4) + `test_credential_encryption.py`(3) ＝ **7 条 FAILED**，全部同一 `NameError` | `.workbuddy/probes/r332_before_fix.xml` |

失败用例清单（7 条，供修复后逐条对账）：

- `test_store_connect.py::test_store_connect_schema_masks_secrets`
- `test_store_connect.py::test_connect_verified_sets_connected_and_persists`
- `test_store_connect.py::test_refreshed_token_is_persisted_but_never_returned`
- `test_store_connect.py::test_disconnect_clears_credentials_and_state`
- `test_credential_encryption.py::test_connect_with_key_stores_ciphertext_and_is_decryptable`
- `test_credential_encryption.py::test_plain_update_does_not_wipe_credentials`
- `test_credential_encryption.py::test_disconnect_actually_clears_ciphertext`

**踩坑留档（本轮真实发生）**：`stores/router.py` 是**全 CRLF**（实测 1219 CRLF / 0 bare LF）⇒ 反向注入探针的锚点若用 LF 写会**恒不命中**，首轮 B/C 两档即因此断言失败（＝"判据静默失效"，看起来像门禁坏了）。修为"锚点一律在 LF 归一化副本上匹配"后通过。这条再次印证本仓铁律：**同一仓可 CRLF/LF 混存 ⇒ 锚点须行尾归一化且要真做**。

---

> **是否立即执行**：✅ 已于 09-30 17:18 执行 —— 见 §4.6。

### 4.6 修复已落地（09-30 17:18）+ 三重验证

**改动（1 行）**：`backend/modules/stores/router.py` 的 `core.audit` import 块中，
在 `STATUS_FAILURE,` **之后**插入 `STATUS_SUCCESS,`。

> **为何不在 §4.4 示意的位置**：import 块按 isort 字母序排列
> （`ACTION_*` < `STATUS_FAILURE` < `STATUS_SUCCESS` < `TARGET_STORE` < `record_audit`），
> 插在 `STATUS_FAILURE` **之前**会破坏顺序。实际落在其后。
> **行尾**：该文件实测**全 CRLF**（1219/0），锚点必须带 `\r\n`，否则恒不命中。

| # | 判据 | 修复前 | 修复后 | 证据 |
|---|------|--------|--------|------|
| ① | **AST 全仓未定义名**（564 个 .py，禁 grep） | 1 处 | **0 处** | `probes/r332_undef.txt` |
| ② | `test_store_connect.py` + `test_credential_encryption.py` | **7 FAILED** | **27/27 PASSED** | `probes/r332_before_fix.xml` / `r332_after_fix.xml` |
| ③ | **反向注入往返**（删该行 → 跑 → 恢复） | — | **7 条红（pytest RC=1）** → 逐字节复原 sha256 一致 | `probes/r332_reverse_inject_roundtrip.py` |

文件写入后实测：54,405 B、CRLF 1219 → **1220**、bare LF 仍 **0**（行尾风格未被破坏）。

**结论**：该 P0 级回归**已消除**，`technical-diligence-review-20260930.md` §4 的"不可上线"判定不再适用。

---

## 5. 全量测试真读数（`--junitxml` 权威解析）

| 指标 | 20260930 报告 | r332 修复前 | **r332 修复后（干净全量）** |
|---|---:|---:|---:|
| 用例总数 | 2,295 | 2,347 | **2,347** |
| 通过 | — | 2,337 | **2,344** |
| **失败** | — | **7** | **0 ✅** |
| 异常 | — | 0 | 0 |
| 跳过 | — | 3 | 3 |
| 测试文件数 | 137 | 142 | 142 |
| 前端门禁脚本 | 41 | 37（`frontend/scripts/check-*.cjs`） | 37 |
| 后端脚本门禁 | — | 48（`backend/scripts/*.py`） | 48 |

**证据文件**：修复前 `probes/r332_full.xml`（7 F）；修复后 `probes/r332_full_clean.xml`（**RC=0**，5m58s 正常收尾，0 失败）。

> ⚠️ **口径铁律（本轮实测复现）**：全量测试**不可与其它 pytest 并发**。中途那次 `r332_full_after_fix.xml`
> 因与反向注入的 pytest 同时抢**共享生产库**，跑到 **98%（2300 通过 / 1 F）后卡在
> `test_voice_clone_isolation.py` 的 teardown**（asyncio proactor `close` 超时）⇒ **junitxml 未生成、退出码不可信**。
> 用「进度串位次 + `--collect-only` 文件区间」回推定位：该 1 F 在 `test_review_analyst_api.py`，
> **单跑 59/59 全绿 ⇒ 并发假红**。干净重跑（不并发）即 **RC=0 / 0 失败**。
> 统计一律以 `junitxml` 为准（本仓 pytest 有卡收尾史；`--collect-only` 回推仅作交叉校验）。

---

## 6. 各 P0 取证详情（补 §3 未展开部分）

### P0-2 · 备份：能力已建，缺"自动化"与"PITR"

`backup_db.py` 的设计已超越"能 dump 出文件"（脚本 docstring 自陈）：

- **双重复核**：`toc_list()`（`pg_restore --list` 解 TOC）+ `deep_verify()`（`pg_restore -f /dev/null` 真读全部数据块）—— 后者是因为**实测发现 custom format 的 TOC 在文件开头，截断后 `--list` 仍会成功**；
- **拒绝空备份**：`TABLE DATA=0` 或 `toc_entries_declared>0 而识别数=0` ⇒ 退出码 2（防解析器静默归零）；
- **`drill` 子命令**：真恢复到 `postgres_restorecheck` 演练库并比对表数；
- **拒绝覆盖生产库**：`restore` 目标非演练库须显式 `--force`。

**缺口**：`beat_schedule`（`core/redis.py:171-262`）**七条任务全为业务**（memory / billing×3 / trade / audit-purge / identity-purge），**没有备份任务** ⇒ 备份只在人手动执行时发生。报告 v1 要求的 `wal_level=replica + archive_mode=on`（PITR 前置）**全仓零命中**。

### P0-3 · 告警：16 条规则，门禁有牙齿

`check_alert_rules.py` 守**两种"假告警"**：①名字写错（规则引用不存在的指标 → Prometheus 不报错、永远空结果 → 永不触发）；②**指标没人写**（登记了但全仓零 `.inc()` ⇒ 阈值是死规则）。判据走 AST。实测输出：

```
注册表指标: 18 个
解析到 expr: 17 条
RESULT: PASS（17 条规则引用的 13 个指标全部真实且有人写入）
```

### P0-4 · 明文口令/端口：已收敛，且加了"启动期护栏"

`config.py:334-351` 是**关键补强**：它把"口令忘了改"从**静默放行**变成**拒绝启动**——理由写得明白："生产若忘了覆盖，服务会正常启动、正常连库、接口全部 200，唯一的现象是库对公网开着 5432 且口令是 123456，而这件事不会有任何报错"。

**残留**：`amazon_sp/db_model.py:50-56` 的 `access_token`/`refresh_token` 仍是 `Text` 明文列，且注释承诺"生产环境这些字段应在应用层加密后存入" —— 但这两张表是**死表**（§7 残留 1），当前不是活跃泄露面，**属于"注释承诺 vs 实现事实"的待办**。

### P0-5 · 审计：一张 append-only 表 + 唯一读写路径 + 保留期 + 告警

工程标准高于"建一张表"：

- `models.py`：`actor_id` **刻意不挂外键**（审计必须比主体活得久；`CASCADE` = 删号即清痕迹，`SET NULL` = 丢归属）；`target_id` **刻意不叫 `shop_id`**（否则触发 `test_schema_parity.py` 的外键不变量，与"不做外键"立场冲突）；
- `service.py`：`record_audit()` **自带短会话、独立提交**（业务 rollback 不得连带回滚审计；审计语义是"发生过的事"不是"成功提交的事"）；写失败**不抛但绝不静默**（`logger.error` + `AUDIT_WRITE_ERRORS.inc` + 返回 `False`）；
- 未知 `status` **原样落库 + WARNING**，绝不改写成 success（防"静默洗白"）；
- `retention.py`：**唯一删除路径**独立成模块；保留期下限钳到 1 天（配成 0 时"错得轻"的那一侧）；
- **实测库内 84 行**（`audit_logs`），`stores/router.py` 有 6 处 `record_audit`。

### P0-6 · 授权链路：真实落点与"死表"

`modules/amazon_sp/` **没有 `router.py` 是设计使然**（它是 SHARED 适配层），报告问错了形态。真实的"连接平台"能力在 `modules/stores/connect/`：`PlatformConnector` 抽象 + 四平台实现 + `signing.py` + `get_connector()` 惰性导入（避免"前端进页面读表单 schema"拉起整条 Amazon 依赖链）。

**真实残留**是两张死表（见 §7）。

### P0-7 · 提示词：报告漏判的 A 档

报告检索词 `prompt_versions|PromptVersion` **只覆盖 B 档（DB 覆写层）的表名**，而 r283 落地的是 **A 档（源码侧规格）**，类名叫 `PromptSpec`、文件在 `ai_infra/llm/prompt_spec.py`，**mtime 09-27（早于报告）**。

⇒ 这是"**检索词未覆盖实际形态**"导致的漏判，与本仓铁律"判据的 needle 必须先在文件里实测存在"同源。

---

## 7. 真正剩下的缺口（复审判定"仍需做"）

| # | 缺口 | 级别 | 依据 |
|---|---|---|---|
| 1 | **`amazon_credentials` / `amazon_auth_logs` 两张死表** | P1 | 零实例化、零 `session.add`；`tok` 列为明文 Text（注释承诺"应用层加密"未兑现）；全仓**无"表必须有写入者"门禁** ⇒ 死表可长期冒充"有能力" |
| 2 | **备份未接调度 + 无 PITR + 无异地** | P0 | `beat_schedule` 无备份任务；`wal_level`/`archive_mode` 零命中 |
| 3 | **提示词 B 档（DB 覆写层）未做** | P2 | `prompt_versions` 零命中；A 档接口（`get_prompt_spec(name).fingerprint`）已就位待用 |
| 4 | **无 `LICENSE` / 用户协议 / 隐私政策** | P0 | 全仓零命中 |
| 5 | ~~无 CD 流水线~~ → **CD 已建但未启用** | P0-次级 | 第 333 轮已补 `.github/workflows/cd.yml` + `scripts/deploy/remote_deploy.sh` + 门禁 `scripts/check-cd-assets.py`（39 项全绿 / 反向注入 8/8）；**仍需配 4 个部署机密**才会真正部署（见 §10） |
| 6 | **`payload: dict` 89 处、`v-html` 10 处** | P2 | 报告的 F 组批评项，未复测（本轮未展开静态扫描） |
| 7 | **D2：无 RLS / 无 `with_loader_criteria` 自动注入** | P1 | 隔离仍靠"每个调用点自己写" + 事后门禁（报告的 D2=2 维持） |
| 8 | **E：无 MFA、token 存 localStorage、密码最小 6 位** | P1 | 未复测 |
| 9 | **`agent_cs.py:1675 if shop_id:`** | 观察项 | 已在注释显式声明降级语义，不产生跨租户读 |

---

## 8. 建议（按 ROI 排序）

1. **【立即 · 阻断】** 修 §4 的一行 import（`STATUS_SUCCESS`）并重跑两文件用例。**在此之前，工作树不可上线**——店铺连接功能对用户是"必崩"，且伴随"凭据已落库但界面报错"的半成功态。
2. **【立即 · 一行】** 把"**新增消费点必须与 import 对账**"补成门禁：可用 AST 扫「模块内引用了 `core.audit` 的名字但未 import」或更通用地跑 `ruff --select F821`（undefined-name）。**这处缺陷若有一道 F821 级门禁，会在提交前就红。**
3. **【半天】** 给 `beat_schedule` 加 `db-backup-daily`（cron 调 `backup_db.py backup`）+ 一条 `BackupStalled` 告警（对齐 `AuditPurgeStalled` 的既有范式）。PITR 属下一档（需改 postgres 启动参数 + 归档卷）。
4. **【半天 · 与 3 同批】** 死表处置：`amazon_credentials` / `amazon_auth_logs` 二选一 —— ①接线为真实写入者，或 ②移出 `register_all_models()` 并写迁移 drop。**同时补一道"表必须有写入者"门禁**（现在的 `test_schema_parity.py` 只判外键，不判写入者）。
5. **【流程】** 尽调报告必须带 **git 工作树指纹**（见 §2 教训）。加一段"本报告读的树 = `<hash>`"，否则无法判断报告比当前分支旧了多少 —— 本次过期的直接原因就是它。
6. **【合规】** P0-9 起草 ToS/隐私/DPA（纯文本工作，可与工程并行）。
7. **【半天 · 已执行】** 补 CD 流水线（P0-10）：`.github/workflows/cd.yml` + `scripts/deploy/remote_deploy.sh` + CI 门禁 `scripts/check-cd-assets.py`。详见 §10。**剩余动作在用户侧**：提供部署目标机并配 4 个仓库机密。

---

## 9. 附：本次复审产出的证据文件

| 文件 | 内容 |
|---|---|
| `.workbuddy/probes/r332_full.xml` | 全量 pytest junitxml（2347 用例） |
| `.workbuddy/probes/r332_full.log` | 全量 pytest stdout（12,584 行） |
| `.workbuddy/probes/r332_parse_junit.py` | junitxml 权威解析脚本（本报告 §5 数字来源） |

> 报告所有"未找到"均列明检索关键词（如 P0-2 搜 `wal_level|archive_mode|pg_basebackup|PITR`、P0-7 搜 `prompt_versions|PromptVersion|prompt_spec`、P0-9 搜 `LICENSE*|*privacy*|*terms*`、P0-10 搜 `deploy|registry|docker push|ghcr|kubectl|release`）。

---

## 10. 第 333 轮：P0-10（无 CD）已补

> 本节由第 333 轮追加。承 §8 之后的下一项；方向由用户以单词指令「CD」指定。

### 10.1 交付物

| 文件 | 作用 |
|---|---|
| `.github/workflows/cd.yml`（新） | 触发（tag `v*` / 手动）→ 构建 2 镜像 → 推 GHCR → SSH 部署 |
| `scripts/deploy/remote_deploy.sh`（新） | 服务器侧幂等部署：记回滚点 → 拉镜像 → 切服务 → 健康检查 → 失败整组回滚 |
| `scripts/check-cd-assets.py`（新） | CI 门禁：存在性 / 行尾 / shell 语法 / YAML 结构 / 镜像名对账 / 无明文凭据 |
| `docker-compose.yml`（改） | `image:` 插值化：`${API_IMAGE:-storekeeper-api:latest}` ×3 + `${WEB_IMAGE:-...}` ×1 |
| `.github/workflows/ci.yml`（改） | assets job 新增「CD 资产门禁」步骤 |
| `README.md`（改） | 新增「持续部署（CD）」章节 + 上线前必读第 8 条 + 已知缺口一行 |

### 10.2 关键设计决定（每条都对应一个真实会踩的坑）

1. **GHCR + 内置 `GITHUB_TOKEN`** —— 零额外密钥（不用建 PAT、不用配 DOCKERHUB_TOKEN）。
   代价：镜像名**必须全小写**，而本仓 `kwj199153/eCommerce` 含大写 ⇒ workflow 里用 `tr` 显式小写化。
2. **secrets 未配时优雅跳过（不红）** —— 否则本仓库会被自己的 CD 判成常红，
   进而有人为了「让它变绿」而写出一个假的部署步骤。这条是刻意的，已写进 workflow 注释。
3. **整组回滚，而不是只回镜像** —— compose 文件本身也随版本演进，
   只回镜像会得到「新 compose + 旧镜像」的半成品组合，比不回滚更难查。
4. **不动数据面** —— 只 `up -d backend worker beat frontend`，绝不 recreate postgres/redis
   （重启数据库会中断连接，且期间无法回滚）。
5. **`image:` 插值化（本轮唯一的"改产品行为"嫌疑点，已双向实测排除）** ——
   CD 推的是 GHCR 镜像，而 compose 原本把镜像名写死为本地名，
   `docker compose pull` 会去 Docker Hub 的 `library/` 命名空间找同名镜像 ⇒ **永远拉不到**。
   改成插值后默认值 = 原值 ⇒ 本地 `up -d --build` 行为**完全不变**。
6. **`deploy` 用 `environment: production`** —— 配了 required reviewers 时在此等人工放行，
   同时让「谁在何时部署了什么」留在 GitHub Deployments 里。

### 10.3 验证（全部实测，非推断）

| 项 | 手段 | 结果 |
|---|---|---|
| compose 插值默认值不变 | `docker compose config`（不设变量） | `storekeeper-api:latest` / `storekeeper-web:latest` —— **与改前一致** |
| compose 插值可覆盖 | `docker compose config`（设 `API_IMAGE`/`WEB_IMAGE`） | 展开为 `ghcr.io/...` ✓ |
| compose 语法 | `docker compose config --quiet` | 通过（docker 29.5.2） |
| CD 资产门禁 | `python scripts/check-cd-assets.py` | **39 通过 / 0 失败 / 0 跳过**，RC=0 |
| 门禁有牙齿 | 8 类反向注入（`r333_cd_gate_injection.py`） | **8/8 OK**（CRLF 注入 / 删 rollback / 数据面注入 / 镜像名改歪 / 明文 IP / 删文件…），每次注入后**逐字节复原** |
| 行尾 | 字节级计数 | `cd.yml` CR=0、`remote_deploy.sh` CR=0（LF）；`README.md` 改后仍 CRLF 465/0 |

### 10.4 过程中修掉的**门禁自身**两个缺陷（假红与假绿同害）

1. **`bash -n` 假红**：Windows 上 `subprocess.run(["bash", ...])` 按 PATH 命中
   `C:\Windows\System32\bash.exe` —— 那是 **WSL 启动器**，不是 POSIX shell
   （本机还被安全策略直接拦掉，只吐一段乱码）。修法：`find_bash()` 显式排除 `system32`/`wsl`，
   并从 `git --exec-path` 反推 Git Bash；本机找不到则**显式 SKIP**（CI 上必跑，那才是真门禁）。
2. **镜像名对账假红**：第一版正则 `\$\{[A-Z_]+:-([^}]+)\}` 扫**全文**，
   把 `POSTGRES_PASSWORD:-123456`、`DATABASE_URL:-postgresql+...` 一并抓进集合 ⇒ 永不相等。
   修法：只取「**同时有 `build` 段的服务**」的 `image` 插值 —— 那才是"我们自建、
   因此 CD 必须构建"的镜像集合。

> 教训：门禁的**假红**与**假绿**同害 —— 假红会逼人绕过门禁（本仓记忆里
> 「门禁一亮红就被 --no-verify 绕过」）。两者都只能靠**反向注入**发现，
> 且必须把 `INJECT-NOOP`（注入没生效）、`GATE-STILL-GREEN`（没牙齿）、
> `WRONG-FAILURE`（红在别处）三类**分开报** —— 本轮第 5 项就是 `WRONG-FAILURE`：
> 门禁其实有牙齿，是我的注入只改了一处、不够彻底。

### 10.5 仍未做（如实标注）

- **CD 未真正生效**：缺 4 个部署机密（`DEPLOY_HOST` / `DEPLOY_USER` / `DEPLOY_SSH_KEY` /
  `DEPLOY_PATH`）⇒ 目前只构建并推送镜像。本仓亦无部署目标机记录，机密需用户提供。
- 未做：灰度 / 分批发布、部署通知（Slack / 企微）、镜像签名与 SBOM、部署后自动跑迁移。
- 服务器侧前置（已写进 README §持续部署）：私有 GHCR 包需 `docker login`，或把包设为 public。

### 10.6 本轮新增证据文件

| 文件 | 内容 |
|---|---|
| `.workbuddy/probes/r333_cd_gate_injection.py` | 8 类反向注入自检（8/8 OK） |
| `.workbuddy/probes/r333_patch_compose.py` | compose 插值化补丁（幂等 + 回读复核） |
| `.workbuddy/probes/r333_patch_ci.py` | ci.yml 接入门禁补丁 |
| `.workbuddy/probes/r333_patch_readme.py` | README CD 章节补丁（CRLF 归一化回写） |
| `.workbuddy/probes/r333_lineend_scan.py` / `r333_to_lf.py` | 行尾探测 / 归一化工具 |
