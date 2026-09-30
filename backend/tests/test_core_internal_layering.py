"""第 140 轮 T-683 · **core 内部实现图的稳定性门禁**（G-2）。

## 这道门禁管什么

老板的原话：「物理分层做了，边界从未定义：core/ 独立且已加门禁，但内核实体
落在 modules/ 下，**横向耦合无约束**」。三个分句对三件事：

| 分句 | 归属 | 处置 |
|---|---|---|
| core/ 独立且已加门禁 | `test_core_layering.py` | 已有：`core` 不得在 import 期 import `modules.*` |
| 内核实体落在 modules/ 下 | T-682 实体归位 | 已做：`StoreRecord` -> `core/stores/models.py` |
| 横向耦合无约束 | **本文件** | 把 core 内部依赖图**显式登记**，任何变化立刻红 |

## ★ 为什么 core 内部**不建包门面**，而 `modules/` 之间要建

边界只应存在于**可以独立演进的切割面**上：

  · `modules/A` 与 `modules/B` 是**真正的模块边界** —— 可以单独收口、单独下线、
    单独换实现。所以跨过去必须走声明过的门面（见 `test_module_facades.py`）。
  · `core/` 内部的子包**不是模块边界**，而是同一个内核的实现分解：一起测试、
    一起发布、被 `test_core_layering.py` 当作一个整体对待。给它们加门面不会
    「定义边界」，只会把导入时点提前到包 `__init__` 期 —— 在一个**已经有环**的
    图上再叠一层顺序耦合。那是另一次独立的架构动作，要单独评估收益与风险。

=> 所以本文件做的是「**实现图的稳定性**」，不是「分层」。它不假装 core 已分层。

## 判据：三条硬规则 + 四张登记表

1. **边集相等**：import 期边 / 函数内边各自与登记表集合相等 —— 新增一条边要
   显式登记（强制 review），删掉一条不更新登记也红。
2. **强连通块相等**：core 内部目前只有 1 个含环的块（`KNOWN_SCCS`）。
   新增块 => 红；旧块被拆掉但不更新登记 => 也红。
3. **`config` 出度必须为 0**（配置真源必须垫在最底层），且**除登记在
   `STANDALONE_UNITS` 的单元外，每个 unit 都必须能沿 import 期边到达 `config`**
   —— 防「孤立小王国」悄悄长出来。

★ 为什么判环用**强连通分量**而不是「环枚举」：环枚举必须设长度上限（否则组合
  爆炸），而超限的长环会**静默漏掉** —— 那正是「门禁看起来在、实际不管事」。
  SCC 没有长度上限，任何规模的环都跑不掉（`test_scc_finder_detects_cycles` 用
  3 节点环钉住这一点）。

★ 为什么判据要**分「import 期 / 函数内」两档**：`core/database.py` 的
  `from core.identity.models import User` 在 `register_all_models()` 函数体内，
  import 期不执行 => 它不是横向耦合，而是「注册 / 引导」。把两档混在一起数会
  得出偏大的数字（实测 36 + 7 条；混算成 43 条）。

## 实测值（第 140 轮建立 / 第 327 轮复算 / 第 328 轮复算 / 第 331 轮再复算）

  `core/**/*.py` = **61** 个；unit = 21 个；
  import 期边 = **50** 条（唯一对）；函数内边 = **10** 条；
  含环的强连通块 = **1** 个：[['auth', 'identity', 'stores']]；
  `STANDALONE_UNITS` = ['<core>', 'profit_engine', 'timefmt']。
  复算方式：底部的 `_scan_core_graph()` 就是判据本体，直接调用即可，
  不需要任何手工计数。
  ★ 复算 SCC 时**只喂 import 期边**（`_strongly_connected_blocks(units, top)`）——
    与 `test_strongly_connected_blocks_match_registry` 同口径。
    把函数内边并进去会造出**跨层假环**（实测：`top|fn` 会报出
    `['audit','auth','database','identity','stores']` 与 `['logger','observability']`
    两个**不存在**的块）—— 那只会让人去拆一个本来没有的环。

## 本轮搬迁引入的变化（必须记住）

  `StoreRecord` 归位 `core/stores/` 后，新增了 `auth -> stores` 与
  `tenant -> stores` 两条 import 期边。于是：
    · 老的环 `auth <-> identity` 与新的环 `auth -> stores -> identity -> auth`
      共享 auth / identity => 合并成**同一个强连通块** `{auth, identity, stores}`；
    · 这不是缺陷，是「内核实体归位」的正常代价 —— 实体进了内核，内核自然要引用它。
  登记在此的目的不是消灭它，而是**不让它继续恶化**。

## 第 218 轮新增的两条边（必须记住）

  新建 `core/library_query/`（资料库查询执行内核）后，新增两条 import 期边：
    · `library_query -> database`（`async_session_factory` 开会话）
    · `library_query -> tenant`（`core.tenant.scoping.scoped` 挂 shop 作用域）

  为什么不降级进函数体：这两条是内核的**定义性依赖**
  （内核 = 拿会话 + 按作用域过滤 + 执行查询），同族先例已有 5 条
  （auth / identity / metering / stores / tenant -> database）。
  把结构性依赖藏进函数体只会让本门禁「看不见耦合」，是自欺。
  实测：未新增环（SCC 仍为 1 个）、未新增孤立单元。

## 第 327 轮新增的 9 条边（必须记住）

  新建 `core/audit/`（通用审计日志内核，P0-5）后，新增两类边：

  · **import 期 6 条**：`audit -> {auth, database, identity, middleware, observability, timefmt}`
      - `audit -> database`      开独立会话写审计（定义性依赖，同 5 条同族先例）
      - `audit -> observability` 指标出口 + 请求上下文（IP 兜底）
      - `audit -> middleware`    来源 IP 的唯一实现 `client_ip()`
      - `audit -> timefmt`       时间序列化的唯一口径 `utc_iso()`
      - `audit -> auth/identity` 读口复用 `get_admin_user` + `User` 类型

  · **函数内 3 条**：`{auth, database, identity} -> audit`
      - `identity` / `auth` 在端点体内调 `record_audit()`（登录成功 / 成员变更）
      - `database` 在 `register_all_models()` 里注册 `AuditLog`

  ★★ 为什么这 3 条刻意留在**函数体**而不上顶层：
    审计的内核（模型 / 服务 / 读口）住在 `audit`，而**读口反过来依赖 `auth`**
    （`get_admin_user`）。若消费方在顶层 import `core.audit`，就立刻形成
    `auth ⇄ audit` 与 `identity ⇄ audit` 两个 **2 节点环**，把 audit 卷进
    `{auth, identity, stores}` 那个大块 —— 那是**一次真实的架构变化**，
    而收益只是少写一句函数内 import。
    ⇒ 延迟导入是「旁路能力」的恰当形态：审计是横切关注点，
      不该把内核的初始化顺序变成隐式约束。
    实测：SCC 仍**恰好 1 个**（`{auth, identity, stores}`）、孤立单元仍**恰好 3 个**。

## 第 328 轮新增的 3 条边（必须记住）

  给审计加**保留期清理**（`core/audit/retention.py` + `core/audit/tasks.py`）后，
  `audit` 这个 unit 新增 3 条 import 期出边：

    · `audit -> config`  读 `config.audit_retention_days`（保留期是配置，不是常量）
    · `audit -> logger`  清理的结局必须落日志（定时任务的失效默认是静默的）
    · `audit -> redis`   `@celery_app.task` 装饰器需要 `celery_app`

  ★ 为什么这 3 条**可以**在 import 期存在，而不是降级进函数体：
    它们与 `audit -> database` 同族 —— 是「清理」这个能力的**定义性依赖**
    （读配置 + 记日志 + 注册任务），不是"顺手拿一下"。
    把结构性依赖藏进函数体只会让本门禁**看不见耦合**（自欺）。
    清理核**不需要**任何延迟导入，因为它没有被任何人反向依赖 ——
    与上一节形成对照：审计的**消费方**（auth/identity/database）必须延迟导入，
    因为读口反过来依赖 auth。

  ★ 为什么 `tasks.py` **不**被 `core/audit/__init__.py` re-export：
    那会把 `celery` 变成「任何一次 `import core.audit`」的硬依赖，
    而该包被 `core/database.py::register_all_models()` 在 **import 期**导入
    ⇒ 连只需要 ORM 实体的注册表也得拉起 celery。见该 `__init__` 的说明。

  实测：SCC 仍**恰好 1 个**、孤立单元仍**恰好 3 个**（清理不引入环、不引入孤岛）。

## 第 331 轮新增的 3 条边（必须记住）

  给身份域两张表接上**保留期清理**（新增 `core/identity/retention.py` +
  `core/identity/tasks.py`）后，`identity` 这个 unit 新增 3 条 import 期出边：

    · `identity -> logger`        清理的结局必须落日志（定时任务的失效默认是静默的）
    · `identity -> observability` 指标出口（`IDENTITY_PURGE_RUNS` / `_DELETED`）
    · `identity -> redis`         `@celery_app.task` 装饰器需要 `celery_app`

  ★ 为什么这 3 条**可以**在 import 期存在，而不是降级进函数体：
    与上一节（审计清理）**逐字同款** —— 它们是「清理」这个能力的**定义性依赖**
    （记日志 + 记指标 + 注册任务），不是"顺手拿一下"。
    把结构性依赖藏进函数体只会让本门禁**看不见耦合**（自欺）。

  ★ `identity -> redis` **不会**形成 `redis ⇄ identity` 的 2 节点环：
    `core/redis.py` 只 import `config`，**不** import `core.identity`
    ⇒ 这条边是单向的。（若哪天 `redis` 反过来要 import identity，
      `test_strongly_connected_blocks_match_registry` 会立刻报出新块。）
    实测：SCC 仍**恰好 1 个**（`{auth, identity, stores}`）、
    孤立单元仍**恰好 3 个**（`identity` 早已能到达 config）。

  ★ `identity -> logger` 此前**只**登记在函数内表里（某处函数内 import logger），
    此后**两张表都有**它。两表同时出现同一条边不是冗余：它记录的是
    「这条路在 import 期和调用期都被走过」，而"从函数内挪到顶层"正是
    本门禁要拦下的那次耦合升级 —— 现在它是一次**被看见**的升级。
"""

from __future__ import annotations

import ast
from pathlib import Path

BACKEND = Path(__file__).resolve().parents[1]
CORE = BACKEND / "core"

#: ------------------------------------------------------- 登记表 1（import 期边）
#: 模块**顶层**就会执行的 unit -> unit 边。集合相等断言 => 新增边必须登记，
#: 删除边必须删登记。
IMPORT_TIME_EDGES: set[tuple[str, str]] = {
    # ★ 第 327 轮（P0-5 通用审计）：audit 内核的 6 条出边。
    #   理由见文件头「第 327 轮新增的 9 条边」。
    ("audit", "auth"),
    # ★ 第 328 轮（保留期清理）新增 3 条：config（读保留期）/ logger（日志出口）
    #   / redis（Celery 任务装饰器）。理由见文件头「第 328 轮新增的 3 条边」。
    ("audit", "config"),
    ("audit", "database"),
    ("audit", "identity"),
    ("audit", "logger"),
    ("audit", "middleware"),
    ("audit", "observability"),
    ("audit", "redis"),
    ("audit", "timefmt"),
    ("auth", "config"),
    ("auth", "database"),
    ("auth", "identity"),
    ("auth", "middleware"),
    ("auth", "observability"),
    ("auth", "security"),
    ("auth", "stores"),
    ("bootstrap", "logger"),
    ("checkpoint", "config"),
    ("database", "config"),
    ("identity", "auth"),
    ("identity", "config"),
    ("identity", "database"),
    # ★ 第 331 轮（身份域保留期清理）新增 3 条：logger（日志出口）/
    #   observability（指标出口）/ redis（`@celery_app.task` 装饰器）。
    #   理由见文件头「第 331 轮新增的 3 条边」。
    #   ★ 其中 `identity -> logger` 此前**只**在函数内表里，此后两表都有
    #     （清理的结局必须在 import 期就拿到 logger 工厂）。
    ("identity", "logger"),
    ("identity", "middleware"),
    ("identity", "observability"),
    ("identity", "redis"),
    ("identity", "security"),
    ("identity", "storage"),
    ("library_query", "database"),
    ("library_query", "tenant"),
    ("logger", "config"),
    ("metering", "auth"),
    ("metering", "config"),
    ("metering", "database"),
    ("metering", "identity"),
    ("middleware", "config"),
    ("middleware", "logger"),
    ("middleware", "observability"),
    ("observability", "config"),
    ("observability", "logger"),
    ("redis", "config"),
    ("resilience", "logger"),
    ("security", "config"),
    ("storage", "config"),
    ("stores", "database"),
    ("stores", "identity"),
    ("tenant", "auth"),
    ("tenant", "database"),
    ("tenant", "observability"),
    ("tenant", "stores"),
}

#: ------------------------------------------------------- 登记表 2（函数内边）
#: **函数体内**的 import（被推迟到调用期）。它们不是横向耦合，而是注册 / 引导 /
#: 延迟导入，所以允许存在；但仍然登记 —— 「从函数内挪到顶层」是一次真实的
#: 耦合升级，必须被看见。
FUNCTION_LEVEL_EDGES: set[tuple[str, str]] = {
    # ★ 第 327 轮：审计是**旁路**能力，消费方一律延迟导入 —— 上顶层会立刻
    #   形成 auth ⇄ audit / identity ⇄ audit 两个环。理由见文件头。
    ("auth", "audit"),
    ("bootstrap", "database"),
    ("bootstrap", "metering"),
    ("database", "audit"),
    ("database", "identity"),
    ("database", "stores"),
    ("identity", "audit"),
    ("identity", "logger"),
    ("logger", "observability"),
    ("tenant", "auth"),
}

#: ------------------------------------------------------- 登记表 3（含环的块）
#: core 内部**非平凡强连通分量**（size > 1）= 含环的块。当前只有 1 个。
#: 记录的是**事实**而非理想，理由见文件顶部「本轮搬迁引入的变化」。
KNOWN_SCCS: set[frozenset[str]] = {
    frozenset({"auth", "identity", "stores"}),
}

#: ------------------------------------------------------- 登记表 4（自足单元）
#: **沿 import 期边到不了 `config`** 的单元（= 与内核主干无 import 期关系）。
#: 登记的是事实，并要求**精确相等** => 新冒出孤立单元会红；已登记的单元哪天
#: 开始依赖 config 了也会红（该把它从本表删掉）。
#:   · "<core>"       —— `core/__init__.py` 是 0 字节空壳，不承载任何逻辑；
#:   · "profit_engine" —— `core/profit_engine.py`（770 行）是**纯计算内核**：
#:                       只 import enum / typing / pydantic，零 core 依赖。
#:                       这是刻意的零耦合（费用模板与利润公式不该被配置/DB 绑定），
#:                       不是漏依赖。
STANDALONE_UNITS: set[str] = {
    "<core>",
    "profit_engine",
    # ★ 第 283 轮登记：时间 → JSON 的序列化口径（`utc_iso`）。
    #   刻意零耦合 —— `tests/test_timefmt.py` 明确断言它「只能依赖标准库」，
    #   因为它被 `modules/billing/*` 在最内层调用，反向 import 业务包即成环。
    #   ⇒ 它到不了 config 是**设计**，不是孤岛，故登记在此。
    "timefmt",
}

#: 依赖图的根：配置真源。出度必须为 0。
ROOT_UNIT = "config"


# ================================================================ 判据本体


def _unit_of(rel_posix: str) -> "str | None":
    """`core/database.py` -> `database`；`core/auth/x.py` -> `auth`；
    `core/__init__.py` -> `<core>`。"""
    parts = list(Path(rel_posix).with_suffix("").parts)
    if not parts or parts[0] != "core":
        return None
    if parts == ["core", "__init__"]:
        return "<core>"
    return parts[1]


def _pkg_of(rel_posix: str) -> str:
    """当前文件所属**包**（相对 import 的解析基点）。

    `core/database.py` -> `core`；`core/identity/x.py` -> `core.identity`；
    `core/identity/__init__.py` -> `core.identity`。

    ★ 普通模块必须**去掉模块自己的名字**（`parts[:-1]`）。第一版只对
      `__init__.py` 去尾，于是 `core/identity/x.py` 得到 `core.identity.x`
      —— 相对 import 会多解析一层，被自检里的相对用例抓住。
    """
    parts = list(Path(rel_posix).with_suffix("").parts)
    return ".".join(parts[:-1])


def _resolve(cur_pkg: str, level: int, module: "str | None") -> str:
    """把 `(level, module)` 解析成绝对点分模块名（相对 import 必须解析）。"""
    if level == 0:
        return module or ""
    base = cur_pkg.split(".") if cur_pkg else []
    drop = level - 1
    if drop:
        base = base[: len(base) - drop] if drop <= len(base) else []
    if module:
        base = base + module.split(".")
    return ".".join(base)


def _edges_of_source(
    source: str, rel_posix: str
) -> tuple[set[tuple[str, str]], set[tuple[str, str]]]:
    """返回 `(import 期边, 函数内边)`，边是 `(own_unit, target_unit)`。

    ★ 分档靠 **AST 祖先链**判「有没有函数祖先」，**不能靠行首缩进** ——
      多行 import 的后续行缩进非 0，缩进判据会把顶层语句误判成函数内。
    """
    own = _unit_of(rel_posix)
    if own is None:
        return set(), set()
    tree = ast.parse(source)
    parents: dict[int, "ast.AST"] = {}
    for node in ast.walk(tree):
        for ch in ast.iter_child_nodes(node):
            parents[id(ch)] = node

    def inside_func(node: "ast.AST") -> bool:
        cur = parents.get(id(node))
        while cur is not None:
            if isinstance(cur, (ast.FunctionDef, ast.AsyncFunctionDef)):
                return True
            cur = parents.get(id(cur))
        return False

    top: set[tuple[str, str]] = set()
    fn: set[tuple[str, str]] = set()
    cur_pkg = _pkg_of(rel_posix)
    for node in ast.walk(tree):
        targets: list[str] = []
        if isinstance(node, ast.ImportFrom):
            t = _resolve(cur_pkg, node.level, node.module)
            if t:
                targets.append(t)
        elif isinstance(node, ast.Import):
            targets.extend(a.name for a in node.names)
        else:
            continue
        for t in targets:
            if not (t == "core" or t.startswith("core.")):
                continue
            tu = "<core>" if t == "core" else _unit_of(t.replace(".", "/") + ".py")
            if tu is None or tu == own:
                continue
            (fn if inside_func(node) else top).add((own, tu))
    return top, fn


def _scan_core_graph() -> tuple[set[str], set[tuple[str, str]], set[tuple[str, str]]]:
    """扫全 `core/**`：返回 `(units, import 期边, 函数内边)`。"""
    units: set[str] = set()
    top: set[tuple[str, str]] = set()
    fn: set[tuple[str, str]] = set()
    for f in sorted(CORE.rglob("*.py")):
        if "__pycache__" in f.parts:
            continue
        rel = f.relative_to(BACKEND).as_posix()
        u = _unit_of(rel)
        if u is None:
            continue
        units.add(u)
        src = f.read_bytes().decode("utf-8", errors="replace").replace("\r\n", "\n")
        t_edges, fn_edges = _edges_of_source(src, rel)
        top |= t_edges
        fn |= fn_edges
    return units, top, fn


def _strongly_connected_blocks(
    units: set[str], edges: set[tuple[str, str]]
) -> set[frozenset[str]]:
    """Tarjan 强连通分量（迭代式）-> 只保留 size > 1 的块（= 含环的块）。

    ★ 用 SCC 而不是环枚举：环枚举必须设长度上限，超限的长环会**静默漏掉**。
    """
    adj: dict[str, list[str]] = {u: [] for u in units}
    for a, b in sorted(edges):
        adj.setdefault(a, []).append(b)
    index: dict[str, int] = {}
    low: dict[str, int] = {}
    on_stack: set[str] = set()
    stack: list[str] = []
    blocks: list[frozenset[str]] = []
    counter = 0

    for root in sorted(units):
        if root in index:
            continue
        work: list[tuple[str, int]] = [(root, 0)]
        while work:
            v, pi = work.pop()
            if pi == 0:
                index[v] = low[v] = counter
                counter += 1
                stack.append(v)
                on_stack.add(v)
            descended = False
            for i in range(pi, len(adj.get(v, []))):
                w = adj[v][i]
                if w not in index:
                    work.append((v, i + 1))
                    work.append((w, 0))
                    descended = True
                    break
                if w in on_stack:
                    low[v] = min(low[v], index[w])
            if descended:
                continue
            if low[v] == index[v]:
                comp: set[str] = set()
                while True:
                    w = stack.pop()
                    on_stack.discard(w)
                    comp.add(w)
                    if w == v:
                        break
                blocks.append(frozenset(comp))
            if work:
                parent = work[-1][0]
                low[parent] = min(low[parent], low[v])
    return {b for b in blocks if len(b) > 1}


def _reachable(start: str, edges: set[tuple[str, str]]) -> set[str]:
    """从 `start` 出发沿 `edges` 可达的 unit 集合（不含 start 自己）。"""
    adj: dict[str, list[str]] = {}
    for a, b in edges:
        adj.setdefault(a, []).append(b)
    seen: set[str] = set()
    stack = [start]
    while stack:
        for w in adj.get(stack.pop(), []):
            if w not in seen:
                seen.add(w)
                stack.append(w)
    return seen


# ================================================================ 用例


def test_import_time_edges_match_registry():
    """登记表 1：import 期边**集合相等**。

    新增边 => 红（横向耦合不能被「顺手加上」）；删除边但留着登记 => 也红
    （否则登记表会越积越松，最后变成历史文档）。
    """
    _, top, _ = _scan_core_graph()
    added = sorted(top - IMPORT_TIME_EDGES)
    removed = sorted(IMPORT_TIME_EDGES - top)
    assert not added, (
        "core 内部出现**新增**的 import 期横向依赖（要么拆掉，要么想清楚后登记）：\n"
        + "\n".join(f"  {a} -> {b}" for a, b in added)
        + "\n（登记前先问：这条边真的必须在 import 期存在吗？能挪进函数体就是"
          "降级，不必新增登记。）"
    )
    assert not removed, (
        "登记表里有**已消失**的边（源码改了但没更新登记）：\n"
        + "\n".join(f"  {a} -> {b}" for a, b in removed)
        + "\n（删掉对应登记即可。）"
    )


def test_function_level_edges_match_registry():
    """登记表 2：函数内边集合相等。

    函数内 import 不是横向耦合（import 期不执行），所以允许存在；但仍然登记 ——
    「从函数内挪到顶层」是一次真实的耦合升级，必须被看见。
    """
    _, _, fn = _scan_core_graph()
    added = sorted(fn - FUNCTION_LEVEL_EDGES)
    removed = sorted(FUNCTION_LEVEL_EDGES - fn)
    assert not added, (
        "core 内部出现新增的**函数内**延迟依赖：\n"
        + "\n".join(f"  {a} -> {b}" for a, b in added)
    )
    assert not removed, (
        "登记表里这些函数内依赖已消失，请删登记：\n"
        + "\n".join(f"  {a} -> {b}" for a, b in removed)
    )


def test_strongly_connected_blocks_match_registry():
    """登记表 3：含环的强连通块集合相等。

    这条**不是要求消灭环** —— 内核实体归位必然带来互相引用。它要求的是
    「环的数量与成员是已知的、被 review 过的」，而不是随机生长。
    """
    units, top, _ = _scan_core_graph()
    found = _strongly_connected_blocks(units, top)
    added = sorted(sorted(b) for b in found - KNOWN_SCCS)
    removed = sorted(sorted(b) for b in KNOWN_SCCS - found)
    assert not added, (
        "core 内部出现了**新的强连通块**（新的环）：\n"
        + "\n".join(f"  {b}" for b in added)
    )
    assert not removed, (
        "登记表里这些强连通块已消失（环被拆掉了）：\n"
        + "\n".join(f"  {b}" for b in removed)
        + "\n（拆环是好事 —— 但请同步更新登记，别让登记表失真。）"
    )


def test_config_has_no_outgoing_edges():
    """`config` 必须零出度：它是配置真源，必须垫在最底层。

    任何 `config -> core.X` 都是分层倒退：一旦配置真源反过来依赖某个单元，
    那个单元就变成「配置的前提」，初始化顺序会立刻变成隐式约束。
    """
    units, top, fn = _scan_core_graph()
    assert ROOT_UNIT in units, f"找不到 unit {ROOT_UNIT}（路径或命名变了）"
    out = sorted(b for a, b in (top | fn) if a == ROOT_UNIT)
    assert not out, f"{ROOT_UNIT} 出现了出边（它是根，出度必须为 0）：{out}"


def test_standalone_units_registry_is_exact():
    """登记表 4：**到不了 `config`** 的单元集合必须与登记精确相等。

    两个方向都防：
      · 新冒出一个与内核主干无 import 期关系的单元 => 红（要求显式登记 + 写理由）；
      · 已登记的单元哪天开始依赖 config 了 => 也红（该把它从登记里删掉）。
    """
    units, top, _ = _scan_core_graph()
    unreachable = {
        u for u in units
        if u != ROOT_UNIT and ROOT_UNIT not in _reachable(u, top)
    }
    new = sorted(unreachable - STANDALONE_UNITS)
    stale = sorted(STANDALONE_UNITS - unreachable)
    assert not new, (
        "以下 core unit 沿 import 期边**到不了** config（脱离内核主干的孤岛），且未登记：\n"
        + "\n".join(f"  {u}" for u in new)
        + "\n（若是刻意的零耦合单元，请在 STANDALONE_UNITS 里登记并写清理由；"
          "否则补上对 config 的依赖。）"
    )
    assert not stale, (
        "STANDALONE_UNITS 里有已失效的登记（它们现在能到达 config 了）：\n"
        + "\n".join(f"  {u}" for u in stale)
    )


# ================================================================ 自检


def test_edge_scanner_separates_import_time_from_function_level():
    """★ 反向注入自检：扫描器必须真的分得清「顶层」与「函数内」。

    没有这一条，`IMPORT_TIME_EDGES` 可能因为判据写反而恒绿。
    """
    top, fn = _edges_of_source(
        "from core.identity.models import User\n", "core/database.py"
    )
    assert top == {("database", "identity")} and fn == set()

    top, fn = _edges_of_source(
        "def f():\n    from core.identity.models import User\n    return User\n",
        "core/database.py",
    )
    assert top == set() and fn == {("database", "identity")}, (
        "函数内 import 被判成了 import 期耦合 —— 两档必须分得开"
    )

    # 多行 import 的后续行缩进非 0 —— 靠缩进判定的实现会误判成函数内
    top, fn = _edges_of_source(
        "from core.identity.models import (\n    User,\n)\n", "core/database.py"
    )
    assert top == {("database", "identity")} and fn == set(), (
        "多行 import 未按 import 期处理 —— 缩进判据会漏报这一类"
    )

    # 同 unit 内不算横向耦合（core/auth/a.py -> core/auth/b.py）
    top, fn = _edges_of_source(
        "from core.auth.jwt_handler import verify_token\n", "core/auth/accounts.py"
    )
    assert top == set() and fn == set(), "同 unit 内部引用被算成了横向耦合"

    # 相对 import 必须被解析（core/identity/x.py 里的 from ..auth.y import z）
    top, fn = _edges_of_source(
        "from ..auth.jwt_handler import verify_token\n", "core/identity/x.py"
    )
    assert top == {("identity", "auth")}, "相对 import 未被解析成绝对名"

    # 非 core 引用不得误报
    top, fn = _edges_of_source(
        "from modules.billing.models import Subscription\n", "core/identity/models.py"
    )
    assert top == set() and fn == set(), "modules 引用被算进了 core 内部图"


def test_scc_finder_detects_cycles():
    """★ SCC 判据自检：**必须**能报出环，且不能把无环图报成有环。

      · `a -> b -> a`（2 节点环）必须报；
      · `a -> b -> c -> a`（3 节点环）必须报 —— 设了长度上限的实现会漏掉它；
      · `a -> b -> c`（无环）必须不报；
      · 自环 size == 1，按定义不算「块」（不是横向耦合）。
    """
    two = {("a", "b"), ("b", "a")}
    assert _strongly_connected_blocks({"a", "b"}, two) == {frozenset({"a", "b"})}

    three = {("a", "b"), ("b", "c"), ("c", "a")}
    assert _strongly_connected_blocks({"a", "b", "c"}, three) == {
        frozenset({"a", "b", "c"})
    }, "3 节点环没被报出 —— 环枚举类实现会因长度上限静默漏掉它"

    acyclic = {("a", "b"), ("b", "c")}
    assert _strongly_connected_blocks({"a", "b", "c"}, acyclic) == set(), (
        "无环图被误报成有环"
    )

    assert _strongly_connected_blocks({"a"}, {("a", "a")}) == set()


def test_scan_actually_covers_the_core_tree():
    """防「路径写错 => 空集 => 恒绿」。"""
    units, top, fn = _scan_core_graph()
    assert len(units) >= 15, (
        f"只发现 {len(units)} 个 core unit，扫描路径可疑：{sorted(units)}"
    )
    assert len(top) >= 30, f"只扫到 {len(top)} 条 import 期边，扫描逻辑可疑"
    assert len(fn) >= 5, f"只扫到 {len(fn)} 条函数内边，扫描逻辑可疑"
    assert (CORE / "config.py").exists()
    assert (CORE / "stores" / "models.py").exists(), "实体归位后的 core/stores 不存在"
