# 第 330 轮：让 `alembic check` 归零 —— 16 处列属性偏差的一次性收敛

> 任务 **#1201**（承接 r327 交付说明 §6「建议的下一步」第 3 项）。
> 原计划的措辞是「修掉 **2 处**既存 alembic 偏差」。实际动手后测得 **16 处**
> —— 多出来的 14 处**只在「纯迁移建出的全新库」上可见**。本轮的交付说明
> 就要把这 14 处从哪来、为什么以前没人看见、以及它们意味着什么写清楚。

---

## 1. 交付物

| 文件 | 变化 | 说明 |
|---|---|---|
| `backend/alembic/versions/k7e2c4f1b849_reconcile_column_attrs_with_orm.py` | **新建**（LF，与同目录 22/25 一致） | 唯一交付物：把 16 处库侧属性收敛到 ORM |
| `.workbuddy/probes/r330_alembic_deviation.py` | 新建 | 偏差实测（`compare_metadata` 三元组 + ORM/库逐属性对照 + NULL 计数） |
| `.workbuddy/probes/r330_fresh_diff.py` | 新建 | 「全新库」与「开发库」两个口径分开摸清 |
| `.workbuddy/probes/r330_ci_roundtrip.py` | 新建 | **CI 等价**全链往返（一次性库：升级 / 单一 head / 降级 / 往返 / check / compare_metadata） |
| `.workbuddy/probes/r330_reverse_injection.py` | 新建 | 反向注入 5 组 6 条（含 md5 逐字节还原） |
| `.workbuddy/probes/r330_*.json` | 新建 | 三份结构化读数留档 |

**没有改任何一行业务代码**，也没有改历史迁移（理由见 §4）。

---

## 2. 偏差的完整清单（16 处）

`alembic check` 在**两个不同口径**上给出的数字不一样，这是本轮最重要的发现：

| 口径 | 报出条数 | 为什么 |
|---|---|---|
| **开发库**（`my-postgres` 里的 `postgres`） | **2** | 它的 `skills` / `skill_revisions` / `market_snapshots` 表当年是 `init_db()` 的 **`create_all()` 按 ORM 建的** ⇒ ORM 声明什么它就是什么；手写迁移里的错误声明被 `_has_table` / `_has_column` 守卫**跳过**了 |
| **纯 `alembic upgrade head` 建出的全新库** | **14** | 那些表由**手写迁移**建出 ⇒ 迁移声明错什么，库里就是什么 |

两者**并集去重 = 16 处**，全部出自「**迁移只写了 schema 的一半**」：

| # | 对象 | 缺的属性 | 根因迁移 |
|---|---|---|---|
| A1 | `skills.icon` | `nullable=False` | `f1906a3c8e5b`（第 188 轮）声明成 `nullable=True` |
| A2 | `stores_store.is_demo` | 列注释 | `d4a7b2e8c1f6`（第 175 轮）加列时漏了 `comment=` |
| B1 | `skills.title` | `nullable=False` | `e8c2f5a7b3d9`（第 181 轮） |
| B2 | `skills.description` | `nullable=False` | 同上 |
| B3 | `skills.content` | `nullable=False` | 同上 |
| B4 | `skills.version` | `nullable=False` | 同上 |
| B5 | `skills.visibility` | `nullable=False` | 同上 |
| B6 | `skills.created_at` | `nullable=False` | 同上 |
| B7 | `skills.updated_at` | `nullable=False` | 同上 |
| B8 | `skills.is_demo` | 列注释 | 同上 |
| B9 | `skill_revisions.version` | `nullable=False` | 同上 |
| B10 | `skill_revisions.content` | `nullable=False` | 同上 |
| B11 | `skill_revisions.note` | `nullable=False` | 同上 |
| B12 | `skill_revisions.action` | `nullable=False` | 同上 |
| B13 | `skill_revisions.changed_at` | `nullable=False` | 同上 |
| B14 | `market_snapshots.is_demo` | 列注释 | `i5b3a8d0e2c4`（第 305 轮） |

★ 这些列的 ORM 侧**每一列都是非 `Optional` 的 `Mapped[...]` 且带 Python `default`**
（`""` / `"1.0.0"` / `"account"` / `"update"` / `False` / `datetime.utcnow`）
⇒ 是**声明式的"必有值"**，不是"可以不填"。方向只能是**收紧库**。

### 这意味着什么

`ci.yml` 第 144-157 步「迁移链完整性自检」的第 ③ 条就是

```yaml
set -e
python -m alembic upgrade head
python -m alembic downgrade base
python -m alembic upgrade head
python -m alembic check        # ← 第 ③ 条
```

CI 的 PG 是**全新空容器**（= 上面第二行那个口径）⇒ 这道门禁**从第 181 轮起就没绿过**。
一条常年红的门禁等于没有门禁：没人会去看一个总是失败的东西。

★ 「本地全绿 ≠ CI 全绿」在本仓的记录里已经出现过（`ci.yml` 自己的注释就写着这句），
本轮是它在 **schema 维度**的第一次实例化 —— 而且形态更隐蔽：
**同一句命令在两个库上给出 2 和 14 两个答案**，本地看永远是 2。

---

## 3. 验证证据（全部是真实退出码）

| 验证 | 命令 / 探针 | 结果 |
|---|---|---|
| 开发库 `alembic check` | `python -m alembic check` | `No new upgrade operations detected.` **rc=0** |
| 开发库独立口径 | `r330_alembic_deviation.py` | `compare_metadata` **0 条**，`Detected` 日志 **0 条** |
| 幂等 | `upgrade head` ×2 | 两次 **rc=0**，`check` 均干净 |
| **CI 等价全链往返** | `r330_ci_roundtrip.py`（一次性库） | **6/6 PASS**，`CI_ROUNDTRIP_EXIT=0` |
| 反向注入 | `r330_reverse_injection.py` | **6/6 PASS**，`REVERSE_EXIT=0`，文件 md5 逐字节还原 |
| 受影响门禁组 | 8 个测试文件 | **60 passed / 0 failed / 0 error / 0 skipped** |

### 3.1 CI 等价往返（`r330_ci_roundtrip.py`）

在自建的一次性库（`r330_ci_roundtrip_tmp`，跑完即删）上跑 `ci.yml` 的同一串：

```
[PASS] ① upgrade head（空库）
[PASS] ② heads 唯一(=1)
[PASS] ③ downgrade base            ← 降级真的可用（不是摆设）
[PASS] ④ upgrade head（往返后）
[PASS] ⑤ alembic check 归零         No new upgrade operations detected
[PASS] ⑥ compare_metadata 三元组为空  diff 条数=0
CI_ROUNDTRIP_EXIT=0
```

★ 为什么**不能**直接在本机开发库上照抄这段：里面有一条 `alembic downgrade base`
—— 在有数据的库上执行等于**删掉所有表**。CI 能这么干只是因为它的 PG 是空的。

### 3.2 反向注入（5 组 6 条）

| 组 | 注入了什么 | 期望 | 实测 |
|---|---|---|---|
| I1 | 整个 `upgrade()` 置空 | 全新库 diff == **16** | ✅ `diff 条数=16` |
| I2 | 删掉 `stores_store.is_demo` 的注释写入口 | 恰好 1 条 `modify_comment` | ✅ 含 `stores_store.is_demo` |
| I3 | 删掉 `market_snapshots.is_demo` 注释条目 | 恰好 1 条 | ✅ 含 `market_snapshots.is_demo` |
| I4 | 删掉 `skills.is_demo` 注释条目 | 恰好 1 条 | ✅ 含 `skills.is_demo` |
| I5a | **正例**：停在父 revision 插一行 `icon=NULL`，再 `upgrade head` | 成功，该行 `icon=''` | ✅ |
| I5b | **反例**：删掉 `UPDATE ... WHERE icon IS NULL` 那一行，同上 | `SET NOT NULL` **当场报错** | ✅ `NotNullViolation / null value / contains null` |

I5 是专门为「**看起来像死代码的承重代码**」设计的：`skills.icon` 的回填在**任何可达的现状库**
里都跑 0 行（本机实测 21 行 0 NULL）。光看现状它像可以直接删。必须**人为造出**那个历史形态
（`f1906a3c8e5b` 当年在已有数据的表上 `ADD COLUMN ... NULL` 必然产生 NULL 行）
才验得出它是承重的 —— 而 I5b 顺带证明了「不回填就会硬失败」，即 `SET NOT NULL` 是 **fail-closed** 的。

---

## 4. 设计决策（含被否方案）

### 4.1 回填策略：**只回填「加列必然产生」的 NULL，不编造历史**

- **回填的只有 `skills.icon` 一处。** 因为 `f1906a3c8e5b` 是在**已有数据**的表上加列，
  且 `nullable=True`、无 `server_default` ⇒ PG **必然**把当时所有既有行填成 NULL。
  回填值 `''` 不是"顺手挑的"：`db_model.py` 写明「空串 = 没生成 / 用户没填」。
- **其余 15 处刻意不回填。** 那 12 列是**随建表一起**创建的（不是 `ADD COLUMN`）
  ⇒ 不存在"被 PG 填成 NULL"的必然性；经 ORM 的任何写入都带 Python default。
  三个时间戳列（`skills.created_at/updated_at`、`skill_revisions.changed_at`）
  和 `skill_revisions.action` 尤其如此 —— 拿 `now()` 或 `'update'` 去填，
  等于**编造"这行是何时/怎么来的"**。宁可让 `SET NOT NULL` 当场报错并指出是哪一列。

  实测（`r330_fresh_diff.json`）：开发库这 15 列 `attnotnull` 全为 `true`、NULL 计数**全为 0**
  （表行数 21 / 23 / 44），全新库 0 行 ⇒ 不回填在任何可达路径上都不会触发。

### 4.2 不去改那三条**根因**迁移

`e8c2f5a7b3d9` / `i5b3a8d0e2c4` / `d4a7b2e8c1f6` 都已在真实库上跑过且都带幂等守卫
⇒ 改它们**不会**改变任何已存在的库，只会让「迁移文件」与「库的实际来历」对不上。
而本迁移无论如何都必须存在（要修已存在的库）⇒ 改历史是纯额外风险、零额外收益。
（同款判断见 `a506249ae3e3_reconcile_drop_redundant_legacy_.py`。）

### 4.3 刻意**不加** `_has_column` 守卫

本仓「迁移必须幂等」那条铁律惯用的守卫是给 `add_column` 用的。本迁移没有 `add_column`：
三处操作（`UPDATE ... WHERE IS NULL`、`SET NOT NULL`、`COMMENT ON`）**在 PG 上天然幂等**。
加"跳过"守卫反而等于**把偏差留在库里**（守卫命中 ⇒ 不修）。

### 4.4 `SET NOT NULL` 不写 `existing_type`

写 `existing_type` 会多出一份与 ORM 并列的**类型真源**（类型若变必漂）。
PG 的 `SET NOT NULL` 不需要它；缺类型时的渲染正确性由 §3.1 的往返实测兜住
（`upgrade` 全程无 warning）。

### 4.5 `downgrade()` 的一个**刻意口径分歧**（写进了文件头）

`downgrade()` 把可空性退回 `e8c2f5a7b3d9` 当年**声明的**形态（`nullable=True`）
—— 那是**迁移链的定义**。对「当年由 `create_all` 建表」的库（如本机开发库），
它自己的过去其实是 NOT NULL ⇒ 回退后该库会与自己的历史不同。
这不是回退写错了，而是「链上定义」与「历史偶然」本来就有分歧
—— 迁移只能回退到链上的前一个状态。**写明它，比让它成为惊喜好。**

### 4.6 没有新增 pytest 门禁（刻意的）

这道偏差的守门人**已经存在**：`ci.yml` 的 `python -m alembic check`（GitHub Actions，
remote = `github.com:kwj199153/eCommerce.git`，会真跑）。再写一条 pytest 会构成
**同一能力两份实现** —— 而两份实现里至少有一份永远测不到。
本轮的任务不是造门禁，是**把这道已存在的门禁修绿**。

---

## 5. 判据自身的缺陷（本轮踩到 / 修掉的）

1. **`compare_metadata` 的返回形态我读错了两次。**
   第一版当成「op 对象」读（`d[0]` 上取 `table_name`）；第二版当成「嵌套 tuple」读
   （`d[0]` 取出七元组）。真实形态是**单元素 list 里装七元组**：
   `[('modify_nullable', None, 'skills', 'icon', {...}, True, False)]`。
   两次都"看起来合理"，也都**没报错**，只是把 `op/table/column` 打成了 `tuple`/`list`/`None`。
   ⇒ 现在用「循环剥单元素容器」写成形态无关的抽取，并在 docstring 里留了实测形态。

2. **`alembic check` 在库未到 head 时直接拒绝运行**：
   `downgrade -1` 之后它报的是 `Target database is not up to date.`（**不是**那 16 条 diff）。
   ⇒ 想拿"偏差清单"就必须用 `compare_metadata`（它不检查 revision 一致性）。
   这也解释了为什么 §3.2 的反向注入必须走探针而不是 `alembic check`。

3. **`alembic check` 只给一坨 repr**（本仓早已记录）。本轮沿用 `compare_metadata`
   拿三元组；但要拿到**方向**（`existing=True → new=False`）还得看 repr 的第 6/7 位，
   所以又加了一个 `logging.Handler` 把 alembic 自己的 `Detected ...` 抓下来做**第二口径**。

4. **「backend/ 全是纯 CRLF」是我上一轮的过度概括。** 本轮实测：
   `backend/**/*.py` = **290 LF / 258 CRLF / 1 mixed**（真混存）；
   而 `alembic/versions/` 是 **22 LF : 3 CRLF**（LF 占绝对多数）。
   `.gitattributes` 对 `*.py` **没有任何规则**，`core.autocrlf=true` 又只在
   checkout/add 时归一化 ⇒ **工作区的 .py 行尾对 diff 是无影响的**（index 里一律 LF）。
   ⇒ 正确做法是**按目录的多数派/相邻文件对齐**，不是假定全局 CRLF。
   本轮的新迁移是 LF（实测 `crlf=0, bare LF=262`），与目录多数派一致。
   （仓库确实有 EOL 门禁，但只覆盖特定范围：`test_agent_context_trim.py:700`
   写着「`ai_infra` 全仓 LF-only」。`alembic/` 不在其中。）

5. **一个 `None` 变体的坑**：修 I5b 断言时，第一版在 stderr 里找 `not-null`，
   但 alembic 的报错**尾巴**是 SQLAlchemy 的 `(Background on this error at: ...)` 注释
   ⇒ 取最后一行永远取到注释。改成在**全部输出**里找关键词才命中。
   （与「门禁 FAIL 行带缩进 ⇒ `startswith('FAIL')` 恒不匹配」是同一族形态：
   **"最后一行的内容"不是你能假设的东西**。）

---

## 6. 本轮附带修掉的环境问题（如实标注）

`pytest-timeout` **没装在本地 `.venv`**（它在 `requirements-dev.txt:32` 里）⇒
`tests/test_pytest_guardrails.py::test_timeout_rail_is_actually_installed` 是**假红**，
而且这正是本仓「pytest 卡在 session 收尾、没有汇总行」的同源症状。
本轮用 `uv pip install --python .venv/Scripts/python.exe "pytest-timeout>=2.3"`
装上了（2.4.0）。**这是环境修复，不是代码改动**；但如果不修，本轮的"门禁全绿"里会混进一条假红。

---

## 7. 未做项 / 建议的下一步

1. **P0-6**（`modules/amazon_sp/` 未挂载）、**P0-7**（`prompt_versions` 覆写层，任务 #992）、
   **P0-9**（`LICENSE*`）—— **本轮未展开**（不在 #1201 范围内）。
2. 给 `purge_old_attempts` / `purge_spent_tokens` 两处**零调用点**的死代码接线
   （同一 beat，代价低）—— r329 已登记为建议，仍未做。
3. `backend/.venv` 缺 `pip` 模块（`uv` 建的 venv 默认不带）——
   本仓若要在本地补依赖，需要走 `uv pip --python .venv/Scripts/python.exe`，
   而不是 `python -m pip`。**这条值得写进启动文档**。
4. 记忆结算（`check_budget.py` WARN）仍属独立任务。
