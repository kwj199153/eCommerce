# 第 239 轮：店铺数量「4 还是 9」——同一个判定，两份实现

> **老板的反馈（逐字）**
> 「在演示模式下的店铺数量 UI 上是 4 个，但是回答的有问题这个改了吗」
>
> **一句话回答：没有改。** 下面是实测证据、根因与修法。

---

## 一、现象：同一个问题，两个答案

浏览器实测输出（老板贴的）：

```
我有几个店铺
▸ 思考过程 1 步
您当前有9个店铺。具体店铺信息如下：
亚马逊1 (Amazon US)
```

而界面「店铺群」里只有 **4** 家。模型随后还补了一段自圆其说的解释：

> 「9 是模拟环境的默认测试数据总量……实际可用的店铺通常只有 1–2 个」

**那段解释是幻觉** —— 它是在为一个错误的输入编理由。数字 9 来自工具的返回值，不是模型数出来的。

---

## 二、实证：两个口径各读一次

探针 `.workbuddy/probes/239a_shop_scope_probe.py`（**只读**，不改任何数据）：

| 口径 | 谁在看 | 实现 | 结果 |
|---|---|---|---|
| **A** | 用户 / UI | `GET /api/v1/stores` → `filter_accessible_stores()` | **4** 家 |
| **B** | LLM / 工具 | `shop_tools._list_shops()` → `select(StoreRecord)` | **9** 家 |

**差值 = 5**。多出来的 5 家（`out-239a.txt`）：

| # | id | 名称 | platform | is_demo | 归属账户 |
|---|---|---|---|---|---|
| 5 | `store_33d77cb3` | 隔离店铺-A | amazon | False | **None** |
| 6 | `store_1d10ed24` | BOLA店铺-A | amazon | False | **None** |
| 7 | `store_72ad211f` | yamaxun1 | amazon_us | False | **`606a8199`（别人的账号）** |
| 8 | `store_82cce164` | pytest-ccb59b | amazon_us | False | None |
| 9 | `store_4978f2f0` | pytest-4e9183 | amazon_us | False | None |

而口径 A 的 4 家 = 演示账号 `4c4629a8-…`（`tenant-test-a@example.com`）名下的
**亚马逊1 / 亚马逊2 / 虾皮1 / 虾皮2**，全部 `is_demo=True`。

---

## 三、根因：同一判定，两份实现

```python
# 口径 A —— modules/stores/router.py:481（UI 侧，正确）
stores = await filter_accessible_stores(db, current_user, stores)

# 口径 B —— modules/secretary/shop_tools.py:56-58（LLM 侧，无过滤）
async with async_session_factory() as session:
    q = select(StoreRecord).order_by(*[getattr(StoreRecord, k) for k in SHOP_ORDER_BY])
    rows = (await session.execute(q)).scalars().all()      # ← 全表
```

`shop_tools.py` 的模块 docstring 第 11–12 行把这件事**写成了设计意图**：

> 「与 `select_product` 不同：`switch_shop` 要列出**所有**店铺（而非按当前 shop 过滤），
>   因此不依赖请求注入的 `shop_id`」

这句话的前半段对（要列全部，不能被单个 shop 绑住），后半段是**误推**：
「不按当前 shop 过滤」被实现成了「**不按任何人过滤**」。

这正是本仓反复吃过亏的形态 —— **同一判定两份实现**
（`core/auth/accounts.py` 的 docstring 已经把店铺归属收口过一次，
第 175/176/177/182 轮都在做同一件事）。这次漏掉的是**第三条入口：LLM 工具链**。

---

## 四、危害（比「数字不对」严重）

| # | 危害 | 说明 |
|---|---|---|
| 1 | **跨租户元数据泄漏** | `yamaxun1` 属于账户 `606a8199`（**别人**）。演示身份的对话上下文里现在有它的名字/平台/id。实测：那个账户的主人自己只看得到 **1** 家店，而演示身份却"知道"它存在。 |
| 2 | **`switch_shop` 候选集含他人店铺** | 9 家全是候选。演示身份说「切到 yamaxun1」会被工具接受、前端会 `setCurrentShop`。后续业务请求虽然被 `can_access_store` 403 挡住（**数据没漏**），但"店存在 + 店名"已经泄露出去了，且可枚举。 |
| 3 | **序号分母错** | `platform_total` 里 amazon = **7**（真实只该有 2）。老板说「第二个亚马逊店铺」时序号口径就已经错了 —— 这正是 `shop_tools.py` 自己注释里记载过的那类事故（"虾皮2 切成了虾皮1"）。 |
| 4 | **模型幻觉的直接源头** | 工具给 9、界面给 4，模型必须解释这个矛盾 ⇒ 编出「9 是测试数据总量」。**不是模型的错，是喂给它的数字错了。** |

---

## 五、为什么现有测试没抓到

`tests/test_stores.py:429` 有专门的一致性回归，但它的断言**主动容忍了这个差异**：

```python
# 两边可能因 owner 过滤差异而子集不同（api 会按当前用户过滤），
# 所以断言「api_ids 是 tool_ids 的子序列」且**相对顺序一致**。
assert set(api_ids) <= set(tool_ids), "api 返回了 tool 不认识的店铺"
```

「子序列」在 `api ⊆ tool` 时**恒真** —— 库里有别人店铺时它照样绿。
测试把 bug 当成了**既定前提**写进注释里，等于给它盖了层合法印章。

`tests/conftest.py:861` 的注释甚至记录了症状：

> 「报错信息是"api 返回了 tool 不认识的店铺"，看起来像**归属过滤出了问题**，
>   其实是测试进程内的残留 —— 别去改断言，先怀疑内存镜像没清」

当时的诊断是对的（另一个问题），但**同一句话里的前半句被忽略了**。

---

## 六、修法

### 生产改动：`_list_shops()` 加归属过滤（唯一一处）

```python
async def _list_shops() -> list[dict]:
    from core.observability.context import current_user_id
    from core.auth.accounts import filter_accessible_stores
    from core.identity.models import User

    async with async_session_factory() as session:
        q = select(StoreRecord).order_by(*[getattr(StoreRecord, k) for k in SHOP_ORDER_BY])
        rows = (await session.execute(q)).scalars().all()

        # ★★★ 归属过滤 —— 与 /api/v1/stores 共用**唯一真源**。
        #   `current_user_id()` 的唯一写入点是鉴权依赖
        #   （`require_auth_if_enabled` 的真身份分支 / 演示身份分支各写一次）。
        #   本工具跑在该请求的异步链上，实测可读到（见 §七 前提 1）。
        #   匿名或无上下文 ⇒ 空串 ⇒ user=None ⇒ 真源内部的 is_demo 窄口。
        uid = current_user_id()
        user = None
        if uid:
            user = (await session.execute(
                select(User).where(User.id == uid)
            )).scalar_one_or_none()
        rows = await filter_accessible_stores(session, user, rows)
    # ... 下面的 index / platform_index / platform_total / total 计算**一行不改**
```

**为什么这样写，而不是另写一套过滤**：

- `filter_accessible_stores` 是 `core/auth/accounts.py` 里已经收口过的唯一真源
  （列表 / 单店 / `X-Shop-ID` 三条路径共用 `_matches`）。再写一份就是**第三份实现**。
- 不需要改 `build_shop_tools()` 的签名，不需要沿途把 `User` 传进 `SecretaryAgent.__init__`
  —— 那是「显式传参」路线，改动面大得多（要动 `get_secretary_agent` 调用链）。

**`_switch_shop` 不需要单独改**：它的候选集来自 `_list_shops()`，改了上游就一起收敛。

### 同批要处理的三件事

| # | 对象 | 做什么 | 为什么 |
|---|---|---|---|
| 1 | `tests/test_stores.py::test_stores_order_matches_shop_tools_order` | 「子序列」收紧为**集合相等** | 旧断言是**负资产**：它锁定的正是错误行为 |
| 2 | `tests/test_secretary_agent.py`（6 处直调 `_list_shops()`） | 显式设置身份上下文，或改成「演示身份下应看到 4 家」 | 无上下文 ⇒ `user=None` ⇒ 只返回 `is_demo` 行，旧期望（全量）会红 |
| 3 | 新增门禁 `tests/test_shop_scope_consistency.py` | 钉住「同一身份下 `/api/v1/stores` 与 `_list_shops()` **集合相等**」+ 反向注入 | 「没被反向注入验证过的门禁 = 没有门禁」 |

> ⚠️ **测试夹具提醒**：`set_request_context()` 的**唯一清理点**是
> `core/middleware/request_log.py:148`（`RequestLogMiddleware.finally`）。
> 新增用例若手动设了上下文，**必须自己 `clear_request_context()`**，
> 否则会污染后续用例（keep-alive 下同一 asyncio task 复用）。

---

## 七、可行性：两个前提已实测（`probes/239b`）

修法押在两个前提上，**不能凭注释**：

### 前提 1 —— 请求身份能穿透到工具函数体内 ✓

| 请求 | 端点内 `current_user_id()` | **工具内** `current_user_id()` | 一致 |
|---|---|---|---|
| `Authorization: Bearer demo-token` | `86bd493a-…` | `86bd493a-…` | ✓ |
| 完全无凭据 | `''` | `''` | ✓ |

链路：HTTP → `require_auth_if_enabled`（写 ContextVar）→ Agent 图节点 → 工具。
与 `ai_infra/skills.py` 的 `load_skill` **同一范式**（它已经在用 `current_user_id()`）。

> 探针第 1 版在这里**假通过**过一次：探针 app 没挂 `RequestLogMiddleware`，
> 第 1 次请求写下的 id **残留**给了第 2 次请求（keep-alive 同一 task）。
> 因此第 2 格也"一致"了 —— 值是错的，结论却看起来成立。
> 修法：每次请求前显式 `clear_request_context()`。生产 app 有中间件，无此问题。

### 前提 2 —— 补过滤后两侧口径真的相等 ✓

| 身份 | 修复后 `_list_shops()` 返回 |
|---|---|
| 演示身份 | **4** 家：亚马逊1 / 亚马逊2 / 虾皮1 / 虾皮2 |
| 无身份（匿名档） | **4** 家（`is_demo` 窄口） |
| **另一真实店主** | **1** 家：yamaxun1 |

最后一行是关键：**同一份全表，换个身份答案就不同** —— 这正是未修版本
做不到的事（它对谁都返回 9）。

---

## 八、改动量评估

| 项 | 规模 |
|---|---|
| 生产代码 | **1 个函数**（`_list_shops`，约 +12 行；下方序号计算零改动） |
| 测试调整 | 2 个文件（1 处收紧断言 + 6 处补身份上下文） |
| 新增门禁 | 1 个文件（含反向注入） |
| 数据库 / 迁移 | **无** |
| 前端 | **无**（UI 侧口径本来就是对的） |

**风险**：低。唯一需要留意的是第 2 条 —— 那些用例原本靠"库里有别人的店"
才通过，改成显式身份后要在**干净数据**下重新校准期望值。

---

## 九、当前状态

| 项 | 状态 |
|---|---|
| 诊断 | ✅ 完成（239a 实锤 4 vs 9） |
| 可行性 | ✅ 完成（239b 两个前提均成立） |
| **生产代码修复** | ✅ **已落地**（§十，`shop_tools.py` +5 处；老板拍板「一次做完」） |
| 断言收紧 | ✅ 已收紧（子序列 → 集合相等，§10.3） |
| 门禁 | ✅ 已新建（`test_shop_scope_consistency.py` 5 条 + 反向注入 4/4，§10.4/10.5） |
| 回归 | ✅ 62 + 106 passed / 0 failed（§10.6） |

探针与原始输出：
- `.workbuddy/probes/239a_shop_scope_probe.py` → `out-239a.txt`
- `.workbuddy/probes/239b_scope_fix_feasibility_probe.py` → `out-239b2.txt`

---

## 十、执行记录：修复已落地

> 本节覆盖 §九 的"未动手"状态。老板拍板**一次做完**：
> 生产代码 + 收紧缩水断言 + 新增门禁。

### 10.1 生产代码改动：`modules/secretary/shop_tools.py`（5 处）

| # | 位置 | 改动 |
|---|---|---|
| 1 | import 段 | 新增 `filter_accessible_stores` / `User` / `current_user_id` |
| 2 | 模块 docstring | 「列出**所有**店铺」→「列出**归属你的全部**店铺」，并写明「不受**当前 shop** 限制 **≠** 不受**租户**限制」——这是本缺陷的语义根源 |
| 3 | 新增 `_resolve_current_user(session)` | 从 `current_user_id()` 解析 `User`；**查不到 ⇒ `None`**（与 `resolve_demo_user` 守卫②同构） |
| 4 | `_list_shops` docstring | 「读取所有店铺」→「读取**当前身份可见的**店铺」 |
| 5 | `_list_shops` 函数体 | `select` 之后插入 `user = await _resolve_current_user(session)` + `rows = await filter_accessible_stores(session, user, rows)` |

文件 8348 → **11149 B**（行尾保持纯 CRLF）。最终形态与 §六 草案的一处差异：
身份解析**抽成独立函数**而非内联 —— 可被形态门禁单独钉住，且与
`ai_infra/skills.py::_load_skill` 读 `current_user_id()` 的点同形。

```python
async def _resolve_current_user(session):
    uid = current_user_id()
    if not uid:
        return None
    user = (await session.execute(select(User).where(User.id == uid))).scalars().first()
    if user is None:
        logger.warning("[shop_tools] 上下文 user_id=%r 查不到 User 行 ⇒ 按无身份处理", uid)
    return user
```

**`_switch_shop` 一行未改**：候选集来自 `_list_shops()`，上游收敛后它自动跟着收敛。

### 10.2 修后实测（`probes/239e`）

| 身份 | 修前 | 修后 | 与 §七 前提 2 的预期 |
|---|---|---|---|
| 无上下文（匿名） | 9 | **4** | ✓ 一致 |
| 演示账号主人 | 9 | **4** | ✓ 一致 |
| **另一真实店主** | 9 | **1**（仅 `yamaxun1`） | ✓ 一致 |
| 上下文里是**不存在的** user_id | 9 | **4** + warning | ✓ 退回演示窄口 |

序号自洽：全局序号连续 ✓ / `total` == 集合大小 ✓ / 平台内序号连续 ✓。
`platform_total` 从错算的 **`amazon=7`** 修正为 **`amazon=2`**（§四第 3 条危害消除）。
预演切换：另一店主 `nth=999` → 夹到 `yamaxun1`（`total=1`），**不会**切到别家店。

### 10.3 收紧的断言：`tests/test_stores.py`

`test_stores_order_matches_shop_tools_order`

- **修前**：`set(api_ids) <= set(tool_ids)`（子序列）—— 在「工具读全表」时**恒真**
- **修后**：注入该用户身份后调 `_list_shops()`，断言 `set(api_ids) == set(tool_ids)`，再断言 `api_ids == tool_ids`

决定性证据：改完生产代码后这条**确实变红** —

```
assert set(api_ids) <= set(tool_ids)   # 旧断言
AssertionError: api 返回了 tool 不认识的店铺
  Extra items in the left set: store_31a73390 / store_9f9a670d / store_317013f1
```

`api` 的 3 家真实店 ⊄ `tool` 的 4 家演示店 —— 它此前**真的在替缺陷打掩护**；
注入身份后转绿。

### 10.4 新增门禁：`tests/test_shop_scope_consistency.py`（5 条，三层）

| 层 | 用例 | 钉什么 |
|---|---|---|
| 行为 | `test_tool_scope_equals_api_scope_and_isolates_tenants` | 同一身份下两边**集合相等**（不是子集） |
| 隔离 | `test_tool_scope_denies_other_tenant_store` | A（**零店铺**）看不到 B 的店 —— 任何泄漏都逃不掉 |
| 窄口 | `test_tool_scope_without_identity_only_sees_demo_stores` | 无身份 ⇒ 只见 `is_demo` 行；与 `filter_accessible_stores(user=None)` 独立对账 |
| 形态 | `test_list_shops_calls_the_shared_scope_filter` | AST：`_list_shops` **函数体内**真的调了 `filter_accessible_stores` + `_resolve_current_user`，且**顺序在 `select` 之后** |
| 形态 | `test_list_shops_does_not_read_the_table_unfiltered` | AST：函数体内 `select` 调用**恰好 1 次** |

**★ 形态判据走 AST 而非源码串**：`_list_shops` 的**注释里就写着** `filter_accessible_stores`
（解释为什么这么做）⇒ 字符串包含判据会**假绿**。本仓已踩过同类（docstring 骗过源码串断言）。
AST 天然不含注释。

**★ 为什么必须有「隔离」用例**：单个主体的"集合相等"可能是**真空为真**
（库里恰好只有你的店）。两个主体互不可见才是反例断言。

### 10.5 反向注入验证（`probes/239g`）

**基线**：门禁 5 passed / 0 failed。随后逐条破坏生产代码：

| # | 注入 | 期望 | 实测 |
|---|---|---|---|
| ① | 摘掉归属过滤那一行 | 行为 2 + 窄口 1 + 形态 1 红；形态 2 绿 | **4 红 / 1 绿 ✓** |
| ② | `user = None`（不解析身份） | 形态 1 红；形态 2 绿 | **1 红 / 1 绿 ✓** |
| ③ | 过滤写 `select` **之前** | 形态 1 红（顺序判据）；形态 2 绿 | **1 红 / 1 绿 ✓** |
| ④ | 多出第二条 `select` 读表路径 | 形态 2 红；形态 1 绿 | **1 红 / 1 绿 ✓** |

四条均「红的总数 == 命中数」、零误伤；每条之间从**备份字节**还原（不用 `git checkout`）；
末次还原字节一致，复跑 5 passed / 0 failed。

> 探针自身的两个坑（已修，记录以免重犯）：
> ① 本仓 pytest **不打印 "N passed" 汇总行**（只有进度点 `.....  [100%]`）⇒
>    按 summary 正则计数**恒得 0**，会被 `crash` 兜底误判成「注入失败」⇒ 结论相反。
>    改法：从进度串 `.FEsx` 计数。
> ② 目标文件是**纯 CRLF** 而锚点用 LF 写 ⇒ 四条**全**报「锚点未命中」，
>    而这与「门禁没抓到」是两回事 ⇒ 读入先 `\r\n → \n` 归一化，写回还原。

### 10.6 回归

| 批次 | 结果 |
|---|---|
| `test_stores.py` + `test_secretary_agent.py` + `test_shop_scope_consistency.py` | **62 passed / 0 failed** |
| 归属相关 8 文件（tool_catalog / tool_registry_guard / hitl_policy / demo_store / account_store_hierarchy / auth_optional_semantics / shop_id_guard / demo_identity） | **106 passed / 0 failed** |

**§六 表里第 2 条（6 处直调补身份）实测无需改动**：`239c` 证明匿名档走 `is_demo` 窄口，
返回的正是同 4 家演示店铺 ⇒ **既没 skip、也没红**。

> ⚠️ 但这 6 条是**依赖库里存在演示店铺**才绿的（seed 在则绿）。
> 若哪天演示店铺消失，它们会**静默 skip** —— 这是"安全失败"但也是**门禁失效**。
> `test_shop_scope_consistency.py` 的窄口用例正是防这件事的哨兵（它独立算一遍预期值）。

### 10.7 同类根因扫描（是否还有第二处）

全仓 `select(StoreRecord)` 共 **6 处生产位置**：

| 位置 | 性质 |
|---|---|
| `core/tenant/middleware.py:280` | 按 `id == shop_id` 查单条 → 走 `can_access_store` ✓ |
| `modules/stores/router.py:153` | 按 id 查单条（更新路径）✓ |
| `modules/stores/demo.py:147` | `ensure_demo_stores` 的 **seed 维护**：读全表以双向收敛 `is_demo` 标记，无身份概念、结果不喂 LLM ✓ |
| `scripts/check_tenant_isolation.py:115` | 独立诊断脚本，按 name 查 ✓ |
| `modules/secretary/shop_tools.py:93` | ← **本轮已修** |
| `tests/*` | 测试代码 |

⇒ **无遗漏通道**。本缺陷是"同一判定的第三份实现"，
而这份实现是**唯一**一份没走 `filter_accessible_stores` 的。

### 10.8 一处过期注释（发现，未改）

`core/stores/models.py:181` 写着「第 175 轮的演示店铺**刻意无主**
（`account_id` / `owner_id` 均为 NULL）」，但 `239c` 实测：
4 家演示店铺 `account_id=4c4629a8`、`owner_id=86bd493a` **皆非空** ——
第 176 轮已改成「**演示账号名下**的店铺」（`accounts.py:280` 有记载）。

两处注释矛盾，**以实测为准**。本错误**不影响判定**（`filter_accessible_stores`
的分支一行未变），但会误导下一个人 ⇒ 建议下轮同步该注释。

### 10.9 本轮探针清单

| 探针 | 作用 |
|---|---|
| `probes/239c_shop_scope_matrix_probe.py` | 身份×可见性矩阵（修前预期值 + 裁决"演示店铺有主"） |
| `probes/239d_patch_shop_scope.py` | 生产代码补丁（5 处，带幂等与行尾归一化） |
| `probes/239e_shop_scope_after_fix_probe.py` | 修后真实行为（4 种身份） |
| `probes/239f_patch_tighten_assert.py` | 收紧 `test_stores.py` 子序列断言 |
| `probes/239g_shop_scope_gate_mutation.py` | 门禁反向注入 4 条（含备份/还原） |

---

## 十一、修复已生效，为什么老板仍然看到「9 家」？（本轮复盘）

### 11.1 结论先行

| 问题 | 结论 |
|---|---|
| 要重启后端吗？ | **不用** —— `start-backend.bat` 带 `--reload`，worker 已自动重启 |
| 现在代码返回几家？ | **4 家**（真 HTTP 实测，见 11.3） |
| 那老板看到的 9 从哪来？ | 那条**会话的检查点里存着修前的旧工具结果**，模型没重新查、直接复述（见 11.4） |
| 怎么才能看到 4？ | **开一条新会话**。注意：**刷新页面不算**（`session_id` 存在 localStorage） |

### 11.2 时间线（全部有日志/DB 证据）

| 时刻 | 事件 | 证据 |
|---|---|---|
| 15:53:50 | 老板问「我有几个店铺」→ 模型调 `switch_shop` | 日志 `tools=['switch_shop'] actions=1` |
| 15:53:50 | 工具返回 **`total: 9`**（当时还是旧代码） | checkpoint blob 原文 |
| **16:59:52** | 本轮的归属过滤**落盘** | `shop_tools.py` mtime |
| **16:59:53** | uvicorn **自动重载**，起新 worker | PID 18184 启动时间 |
| 17:06:27 | 老板刷新后重问「我现在有几家店了」 | 日志 `session=session_d2e3dc8bfce542da` |
| 17:06:27 | **`tools=-` `actions=0`** ⇒ **一个工具都没调** | 同上 |
| 17:06:27 | 回复里**逐字照抄**了那个旧 JSON | `conversation_messages` seq=52 |
| 17:1x | 真 HTTP 验证：新会话返回 **4** | `probes/239k` |

### 11.3 真 HTTP 验证（唯一硬证据）

★ 为什么不能只用日志：17:04/17:05 日志里那些候选集留痕，前缀是
`| - | - | - |`（**无请求上下文**）⇒ 那是 **pytest / 进程内探针**打的，
**证明不了 HTTP 服务已加载新代码**。只有真发一个请求才算数。

`probes/239k_live_http_verify_probe.py` —— 走 `POST /api/v1/orchestrator/chat/stream`，
**新建 session**（不复用老板那条被污染的历史）：

| 问法 | 工具返回 | 正文 |
|---|---|---|
| 我现在有几家店铺？ | `"total": 4` | 您当前账号下总共有**4**家店铺 |
| 同会话追问 | `"total": 4` | 你当前共有**4**家店铺 |

两次都**正常调用了工具**，两次都是 4 ⇒ 修复在生产通路上生效。

### 11.4 根因：工具结果落在 **checkpoint**，修不回旧会话

`probes/239l_session_history_dump.py`（只读）捞出老板那条会话的 52 条消息，
其中 `assistant` 消息里同时含「9」和「店」的有 **5 条**，包括：

- `seq=46`（15:53 生成）您当前有**9个**店铺…
- `seq=48`（模型自造的辩解）「9 是模拟环境的默认测试数据总量…」—— **幻觉**
- `seq=52`（17:06 生成）根据系统当前返回的店铺切换响应：`{… "total": 9}`

**问题**：`conversation_messages` 只存 `role + content`，**不存工具结果**。
那模型是怎么在 17:06 逐字写出 `store_c3529ab1` 这个 id 和 `total: 9` 的？

答：**LangGraph 的 `AsyncPostgresSaver` 把消息（含 `ToolMessage`）整体落库**。
直接扫那条 thread 的 checkpoint blob，原文就是：

```
thread_id = 86bd493a-2d75-4ee8-81f4-c9e0ca07c0d8:session_d2e3dc8bfce542da
channel   = messages
ToolMessage content = {"action": "switch_shop", "shop": {"id": "store_c3529ab1",
                      "name": "亚马逊1", "platform": "amazon_us"},
                      "index": 1, "total": 9}
AIMessage  content = 您当前有9个店铺。具体店铺信息如下：1. **亚马逊1** (Amazon US)
```

**⇒ 机制串联**：修前的工具结果**持久化在检查点里** → 同一会话下一轮
`checkpointer` 把它**原样恢复进上下文** → 模型认为「答案已经在手边」，
**不再调工具**，直接把 9 复述出来（17:06 那次回复里的 JSON 就是这么来的）。

**这不是代码没生效，是旧会话的上下文被污染了。** 也解释了为什么：
- 我做的所有测试（pytest / 进程内探针 / 新会话 HTTP）**全都看不到**这个现象；
- 老板**刷新页面也逃不掉** —— 见 11.5。

### 11.5 为什么刷新页面没用（顺带查出一个产品缺口）

会话 id 的持久化（`frontend/src/stores/chat.ts`）：

```ts
const sessionIdByAgent = ref<Record<string, string>>({})
// sessionId 持久化 key
localStorage.setItem(SESSION_KEY, JSON.stringify(sessionIdByAgent.value))   // 'secretary_session_ids'
```

而清空会话的 `resetSessionState()` **全仓只有一个调用点**：
`utils/sessionContext.ts:68`，由 **切换账号 / 登出 / 401** 触发。

> ★ **前端没有「新建对话」入口。** 刷新页面只是从 localStorage 恢复同一个
> `session_id` ⇒ 服务端检查点把同一段被污染的上下文再喂一遍。
> 结果是：**用户遇到答错时，没有出口** —— 只能去登出/切账号。

这既是本次「刷新了还是 9」的直接原因，也是一个独立的产品缺口。

### 11.6 解法

**立刻可用（零改动）**：侧栏**切换账号 / 退出登录**再进来（会清 `session_id`），
然后问「我现在有几家店铺」→ 应看到 **4**。

**要治本，三条（按性价比排序，需老板拍板）**：

| # | 措施 | 效果 | 代价 |
|---|---|---|---|
| 1 | 前端加**「新建对话」**按钮（调 `resetSessionState`） | 用户随时能摆脱被污染的会话 | 小（复用已有函数） |
| 2 | 提示词加固：「店铺数量/列表等**易变状态**，回答前必须**当轮调工具核实**，禁止复述历史里的数字」 | 降低「拿旧值回答」的概率 | 中（行为变更，需 A/B 对照） |
| 3 | 会话历史**主动失效**（工具输出带 `as_of` 时间戳等） | 治本，但要设计 | 大 |

★ 措施 1 是**纯前端、无行为争议**的，建议优先。

### 11.7 本轮探针清单（追加）

| 探针 | 作用 |
|---|---|
| `probes/239k_live_http_verify_probe.py` | **真 HTTP** 打运行中的服务（新会话）⇒ 证明 `total: 4` |
| `probes/239l_session_history_dump.py` | 只读导出该会话 52 条消息 ⇒ 定位「9」的历史出处 |

★ 一次方法学提醒：**判定「服务端是否加载了新代码」不能看日志里"
候选集"留痕** —— 进程内探针与 pytest 打的是同一个日志文件，前缀
`| - | - | - |` 是区分标志（有请求上下文才会有 request-id / shop-id）。
