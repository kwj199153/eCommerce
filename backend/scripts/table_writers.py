"""ORM 表写入者盘点 —— **唯一真源**（第 357 轮 · L3-16）。

==============================================================================
★ 为什么需要这个模块（来自 r332 §8 建议 4）
==============================================================================
`tests/test_schema_parity.py` 判的是**外键目标可达**（每张表引用的表都在同一
模块闭包里声明过），**不判写入者**。于是「DDL 建好了、迁移带着走、外键全对、
但生产代码里没有任何一处往里写」的表可以长期存在 —— 它们不是表，是**墓碑**：
占着 schema、进 `create_all()`、跟着迁移走，却永远不会有一行数据，
任何「这个功能的数据从哪来」的追问都问不出结果。

r357 实测：`Base.metadata.tables` 共 **57** 张表，其中 **5** 张零写入者，
全部在 `modules/amazon_sp/db_model.py`。

==============================================================================
★ 判据（本仓铁律的落地）
==============================================================================
1. **表清单只问 SQLAlchemy 本身**：`Base.metadata.tables` 拿 DDL 真源，
   `Base.registry.mappers` 拿「类名 ↔ 表名」。**禁 grep `__tablename__`** ——
   docstring / 注释里的同名字符串会假命中。r357 三口径对账实测：
   grep 行级 **70** / AST 真声明 **57** / metadata **57**，差集 0；
   13 行噪声里 6 行在测试文件、7 行在注释与 docstring。
2. **写入者只认 AST**，不认字符串匹配：注释里写 `DailySales(...)` 不算写入者。
3. **盘点失明必须炸**（照 `scripts/route_inventory.py` 的范式）：
   - 表数 < `MIN_PLAUSIBLE_TABLES` ⇒ 抛 `TableWritersError`
     （否则 `register_all_models` 静默注册 0 个模型时，门禁会「全绿」）。
   - metadata 里存在**不属于任何映射类**的表 ⇒ 抛。映射类是本模块识别写入者
     的**唯一入口**；未映射的表我看不见，此时任何「无写入者」的结论都是假的 ——
     宁可炸，不许猜。
   - 白名单里出现**不存在的表名** ⇒ 抛（白名单正在腐化的信号）。

★ 被认作写入者的形态（W1–W5，全 AST 口径）：
  W1  ORM 实例化   `Model(...)` / `db_model.Model(...)`
  W2  Core insert  `insert(Model)` / `insert(Model.__table__)` / `insert("table_name")`
  W3  PG insert    `pg_insert(Model)` / `pg_insert(Model.__table__)`
  W4  批量         `bulk_save_objects(...)` / `bulk_insert_mappings(Model, ...)`
  W5  表对象       `Model.__table__.insert()`

★ 已知盲区（如实标注，别当它不存在）：
  ① 映射类以**参数**形式传给通用 upsert 助手时，助手体内的 `pg_insert(model)`
     里 `model` 是形参 ⇒ 扫不到。r357 已按该形态单独核对过那 5 个类名，零命中，
     故结论成立。将来若引入这种助手，须把**调用点**也算成写入者，否则假红。
  ② W2/W3 只按名字匹配（不校验名字是否 import 进来）⇒ 同名局部变量会假命中。
     这是**假绿**方向（可能漏掉一张真死表），不会造成假红；W1/W5 已加 import 校验。

==============================================================================
★ 分层：口径 / 纯函数 / 判据（为了能被反向注入）
==============================================================================
  scan_source(rel, src, cls2tbl)   纯函数：**一段源码文本** -> [Hit]
  scan_writers()                   走真实目录，喂给 scan_source
  evaluate(tables, found, allowlist)  纯函数：**盘点结果** -> Report
  inventory()                      = scan_writers() + 三道失明检查 + evaluate(FROZEN_ALLOWLIST)

  ★ 之所以把 `scan_source` / `evaluate` 拆成纯函数：门禁要能用**合成输入**
    做反向注入（「删掉唯一写入者必须红」）。若它们只认真实目录，
    验证就只能去改真实仓库文件 —— 那既慢又危险。

==============================================================================
★ 用法
==============================================================================
    from scripts.table_writers import inventory

    rep = inventory()                     # 失明即抛；否则返回结构化结果
    assert rep.violations == ()           # 无写入者且不在白名单 ⇒ 必须红
    assert rep.allowlist_stale == ()      # 白名单不许留已经接上线的条目

命令行（`--json` 给机器读，默认给人看摘要）：
    python scripts/table_writers.py
    python scripts/table_writers.py --json
"""

from __future__ import annotations

import ast
import json
import pathlib
import sys
from dataclasses import dataclass

# scripts/ 下的脚本被直接运行时（`python scripts/table_writers.py`），
# sys.path[0] 是 scripts/ 而非 backend/ ⇒ 下面 `from core.database import ...` 会炸。
# 补上 backend 根目录；已存在则不重复插入。（仓内既有惯例，见 scripts/bootstrap_db.py）
_BACKEND = pathlib.Path(__file__).resolve().parents[1]
if str(_BACKEND) not in sys.path:
    sys.path.insert(0, str(_BACKEND))

ROOT = _BACKEND.parent

#: 扫描根目录。**前 4 项与 `pyproject.toml` 的 `[tool.bandit] targets` 对齐**
#: （core / modules / platforms / ai_infra + main.py / worker.py），
#: 另加 `scripts/`：seed 与 bootstrap 也是真实的库写入来源，漏掉它们会把
#: 「只由 seed 灌数据」的表误判成死表（那是另一种形态的假红）。
SCAN_ROOTS = ("core", "modules", "platforms", "ai_infra", "scripts")
SCAN_EXTRA_FILES = ("main.py", "worker.py")

#: 表数低于此值即视为「盘点失明」。r357 实测 57，取 40 留足增长余量，
#: 但绝不放宽到能把「静默注册 0 个模型」吞成绿。
MIN_PLAUSIBLE_TABLES = 40

#: Core / PG insert 函数名（按 `node.func` 的末段名匹配）。
CORE_INSERT = frozenset({"insert", "pg_insert"})
#: 批量写入方法名。
BULK_INSERT = frozenset({"bulk_save_objects", "bulk_insert_mappings"})

#: ---------------------------------------------------------------- 冻结白名单
#: 「无写入者」的表**必须先登记在这里**，且每条都要写清：①取证读数 ②处置方向
#: ③谁批的 / 为什么还没做。
#: ★ 这不是「豁免名单」，是**欠债台账**：`evaluate()` 会反向检查 ——
#:   表一旦接上写入者（或表名消失），条目即 `allowlist_stale` ⇒ 门禁红。
#:   所以这张表只能缩短，不能原地长住。
FROZEN_ALLOWLIST: dict[str, str] = {
    "amazon_daily_sales": (
        "零写入者（映射类 DailySales，modules/amazon_sp/db_model.py）。"
        "r357 用真实类名全仓 grep：只在定义行出现。"
        "r332 §8 建议 4 的处置（①接线为真实写入者 / ②移出 register_all_models() 并写迁移 drop）尚未获批。"
    ),
    "amazon_ad_metrics": (
        "零写入者（映射类 AdMetric，modules/amazon_sp/db_model.py）。"
        "★ 同名干扰：modules/ad_analysis/agent_ad.py 另有一个 Pydantic 类也叫 AdMetric，非 ORM —— "
        "故本模块的类名口径取自 Base.registry.mappers，不靠名字。处置同上，尚未获批。"
    ),
    "amazon_listing_snapshots": (
        "零写入者（映射类 ListingSnapshot，modules/amazon_sp/db_model.py）。"
        "对照：同文件的 CompetitorSnapshot 有真实写入者（modules/amazon_sp/seed.py），"
        "故这不是「整个模块都没接线」，是这 5 张表单独没接线。处置同上，尚未获批。"
    ),
    "amazon_report_tasks": (
        "零写入者（映射类 ReportTask，modules/amazon_sp/db_model.py）。"
        "r357 用真实类名全仓 grep：只在定义行出现。处置同上，尚未获批。"
    ),
    "amazon_inventory_health": (
        "零写入者（映射类 InventoryHealth，modules/amazon_sp/db_model.py）。"
        "r357 用真实类名全仓 grep：只在定义行出现。处置同上，尚未获批。"
    ),
}


class TableWritersError(RuntimeError):
    """盘点失明 —— **必须让门禁变红**，不许静默返回空集合。"""


# ------------------------------------------------------------------ 数据结构
@dataclass(frozen=True)
class Hit:
    """一处写入点。"""

    table: str
    file: str          # 相对仓库根的 posix 路径
    line: int
    func: str          # 所属函数名（模块级为 "<module>"）
    kind: str          # W1..W5

    @property
    def is_demo(self) -> bool:
        """是否来自 seed / bootstrap 这类**演示数据**来源（非业务路径）。"""
        return _is_demo_source(self.file)

    def __str__(self) -> str:  # pragma: no cover - 仅 CLI 展示
        return f"{self.file}:{self.line} ({self.func}, {self.kind})"


@dataclass(frozen=True)
class Report:
    """一次盘点的完整结果。**判据都在这里，门禁不要再自己算一遍。**"""

    tables: tuple[str, ...]
    writers: dict[str, tuple[Hit, ...]]
    #: 一张写入者都没有的表（排好序）。
    unwritten: tuple[str, ...]
    #: 有写入者、但**全部**来自 seed/bootstrap。观测项，当前不是判据。
    demo_only: tuple[str, ...]
    #: 白名单 ∩ 无写入者 = 已登记的欠债。
    allowlist_hit: tuple[str, ...]
    #: 白名单里「已经不该在」的条目（表已接上写入者）⇒ 必须删条目。
    allowlist_stale: tuple[str, ...]
    #: **门禁判据**：无写入者且不在白名单。
    violations: tuple[str, ...]


# ------------------------------------------------------------------ 权威清单
def _load_registry() -> tuple[set[str], dict[str, set[str]]]:
    """返回 `(metadata 表名集合, 类名 -> {表名})`。

    两处都问 SQLAlchemy 本身（`Base.metadata` / `Base.registry.mappers`），
    不 grep、不自己维护清单。
    """
    from core.database import Base, register_all_models  # noqa: PLC0415
    from wiring import MODEL_MODULES  # noqa: PLC0415

    register_all_models(MODEL_MODULES)

    tables = set(Base.metadata.tables)
    cls2tbl: dict[str, set[str]] = {}
    for mapper in Base.registry.mappers:
        cls2tbl.setdefault(mapper.class_.__name__, set()).update(
            t.name for t in mapper.tables
        )
    return tables, cls2tbl


# ------------------------------------------------------------------ AST 工具
def _imported_names(tree: ast.Module) -> set[str]:
    names: set[str] = set()
    for n in ast.walk(tree):
        if isinstance(n, ast.Import):
            for a in n.names:
                names.add(a.asname or a.name.split(".")[0])
        elif isinstance(n, ast.ImportFrom):
            for a in n.names:
                names.add(a.asname or a.name)
    return names


def _assigned_names(tree: ast.Module) -> set[str]:
    """模块内被赋值过的名字 —— 用来挡「同名局部变量冒充 ORM 类」。"""
    names: set[str] = set()
    for n in ast.walk(tree):
        if isinstance(n, ast.Assign):
            for t in n.targets:
                if isinstance(t, ast.Name):
                    names.add(t.id)
        elif isinstance(n, ast.AnnAssign) and isinstance(n.target, ast.Name):
            names.add(n.target.id)
    return names


def _callee_class_name(node: ast.Call) -> str | None:
    """`Model(...)` / `mod.Model(...)` -> 'Model'；其它形态 -> None。"""
    f = node.func
    if isinstance(f, ast.Name):
        return f.id
    if isinstance(f, ast.Attribute) and isinstance(f.value, ast.Name):
        return f.attr
    return None


def _table_arg_names(node: ast.Call) -> set[str]:
    """`insert(X)` 里 X 能解析出的表名 / 类名。"""
    out: set[str] = set()
    for a in list(node.args) + [k.value for k in node.keywords]:
        if isinstance(a, ast.Constant) and isinstance(a.value, str):
            out.add(a.value)                              # insert("orders")
        elif isinstance(a, ast.Name):
            out.add(a.id)                                 # insert(Order)
        elif isinstance(a, ast.Attribute) and a.attr == "__table__":
            base = a.value
            if isinstance(base, ast.Name):
                out.add(base.id)                          # insert(Order.__table__)
            elif isinstance(base, ast.Attribute) and isinstance(base.value, ast.Name):
                out.add(base.attr)                        # insert(mod.Order.__table__)
    return out


def _is_demo_source(rel: str) -> bool:
    """seed / bootstrap 类来源 —— 写进去的是演示数据，不是业务路径。"""
    p = pathlib.PurePosixPath(rel)
    if "scripts" in p.parts:
        return True
    return p.stem == "seed" or p.stem.startswith("seed_") or p.stem == "bootstrap"


# ------------------------------------------------------------------ 纯函数：单文件扫描
def scan_source(rel: str, src: str, cls2tbl: dict[str, set[str]]) -> list[Hit]:
    """扫**一段源码文本**，返回它产生的写入点。

    ★ 纯函数（只依赖入参）—— 反向注入台架可以喂合成源码，不必碰真实仓库。
    ★ 语法错的文件返回空列表（那种文件由 ruff / 编译检查兜底，本门禁不重复管）。
    """
    try:
        tree = ast.parse(src)
    except SyntaxError:
        return []

    cls_names = set(cls2tbl)
    # 表名 -> 类名（反查：`insert("orders")` 这种字面量表名也算命中）
    tbl2cls: dict[str, set[str]] = {}
    for c, ts in cls2tbl.items():
        for t in ts:
            tbl2cls.setdefault(t, set()).add(c)

    imported = _imported_names(tree)
    assigned = _assigned_names(tree)

    # 每个 AST 节点所属的函数名（便于报告定位；最外层优先）
    parent: dict[int, str] = {}
    for n in ast.walk(tree):
        if isinstance(n, (ast.FunctionDef, ast.AsyncFunctionDef)):
            for sub in ast.walk(n):
                parent.setdefault(id(sub), n.name)

    out: list[Hit] = []
    for node in ast.walk(tree):
        if not isinstance(node, ast.Call):
            continue
        where = parent.get(id(node), "<module>")
        targets: set[str] = set()
        kind = ""

        # W1：ORM 实例化。两种书写都要认：
        #   ① 裸名     `Widget()`
        #      —— 要求 `Widget` 是 import 进来、且未被赋值的名字。
        #   ② 模块前缀 `db_model.Widget()`
        #      —— 要求**前缀**（db_model）是 import 进来、且未被赋值的名字。
        #         属性名属不属于那个模块静态判断不了，只能信（假绿方向，可接受）。
        #   ★ 这个洞是 r357 反向注入台架抓出来的：一开始只判了裸名形态，
        #     于是 `db.Widget()` 一条都认不出来 —— 那是**假红**方向
        #     （把真有写入者的表报成死表），比假绿更该修。
        name = _callee_class_name(node)
        if name is not None and name in cls_names:
            if isinstance(node.func, ast.Attribute):
                prefix = node.func.value.id          # _callee_class_name 已保证是 Name
                ok = prefix in imported and prefix not in assigned
            else:
                ok = name in imported and name not in assigned
            if ok:
                targets |= cls2tbl[name]
                kind = "W1-instantiate"

        # W5：`X.__table__.insert()`
        if isinstance(node.func, ast.Attribute) and node.func.attr == "insert":
            base = node.func.value
            if isinstance(base, ast.Attribute) and base.attr == "__table__":
                b = base.value
                if (
                    isinstance(b, ast.Name)
                    and b.id in cls_names
                    and b.id in imported
                    and b.id not in assigned
                ):
                    targets |= cls2tbl[b.id]
                    kind = "W5-table-insert"

        # W2/W3/W4：Core / PG / 批量 insert
        fname: str | None = None
        if isinstance(node.func, ast.Name):
            fname = node.func.id
        elif isinstance(node.func, ast.Attribute):
            fname = node.func.attr
        if fname in CORE_INSERT:
            for a in _table_arg_names(node):
                if a in cls_names:
                    targets |= cls2tbl[a]
                    kind = "W2/W3-core-insert"
                elif a in tbl2cls:
                    targets.add(a)
                    kind = "W2/W3-core-insert"
        elif fname in BULK_INSERT:
            for a in _table_arg_names(node):
                if a in cls_names:
                    targets |= cls2tbl[a]
                    kind = "W4-bulk"

        for t in sorted(targets):
            out.append(Hit(table=t, file=rel, line=node.lineno, func=where, kind=kind))

    return out


def iter_source_files() -> list[pathlib.Path]:
    """待扫的 .py 全集（生产面 + scripts）。"""
    files: list[pathlib.Path] = []
    for r in SCAN_ROOTS:
        base = _BACKEND / r
        if base.is_dir():
            files.extend(p for p in base.rglob("*.py") if ".workbuddy" not in p.parts)
    for extra in SCAN_EXTRA_FILES:
        p = _BACKEND / extra
        if p.is_file():
            files.append(p)
    return files


def scan_writers() -> tuple[set[str], dict[str, list[Hit]], dict[str, set[str]]]:
    """走真实目录，返回 `(metadata 表名集合, 表名 -> [Hit], 类名 -> {表名})`。"""
    tables, cls2tbl = _load_registry()
    found: dict[str, list[Hit]] = {t: [] for t in tables}

    for f in iter_source_files():
        try:
            src = f.read_text(encoding="utf-8")
        except (OSError, UnicodeDecodeError):  # pragma: no cover
            continue
        rel = f.relative_to(ROOT).as_posix()
        for h in scan_source(rel, src, cls2tbl):
            if h.table in found:
                found[h.table].append(h)

    return tables, found, cls2tbl


# ------------------------------------------------------------------ 纯函数：判据
def evaluate(
    tables: set[str],
    found: dict[str, list[Hit]],
    allowlist: dict[str, str] | None = None,
) -> Report:
    """套用判据，返回 `Report`。**纯函数** —— 反向注入台架直接喂合成输入。

    ★ 门禁只需读 `Report.violations` / `Report.allowlist_stale`；
      不要在测试里重算一遍集合运算（那是「同一判定两份实现」）。
    """
    allow = FROZEN_ALLOWLIST if allowlist is None else allowlist

    unwritten = tuple(sorted(t for t, hits in found.items() if not hits))
    demo_only = tuple(
        sorted(t for t, hits in found.items() if hits and all(h.is_demo for h in hits))
    )
    unwritten_set = set(unwritten)
    allowlist_hit = tuple(sorted(unwritten_set & set(allow)))
    allowlist_stale = tuple(sorted(set(allow) - unwritten_set))
    violations = tuple(sorted(unwritten_set - set(allow)))

    return Report(
        tables=tuple(sorted(tables)),
        writers={t: tuple(hits) for t, hits in found.items()},
        unwritten=unwritten,
        demo_only=demo_only,
        allowlist_hit=allowlist_hit,
        allowlist_stale=allowlist_stale,
        violations=violations,
    )


# ------------------------------------------------------------------ 入口
def inventory() -> Report:
    """盘点 + 三道失明检查 + 判据。**失明即抛**，否则返回结构化结果。"""
    tables, found, cls2tbl = scan_writers()

    if len(tables) < MIN_PLAUSIBLE_TABLES:
        raise TableWritersError(
            f"只盘点到 {len(tables)} 张表（阈值 {MIN_PLAUSIBLE_TABLES}）—— 扫描疑似失明。"
            "先确认 register_all_models(MODEL_MODULES) 真的注册成功了，"
            "别把「注册 0 个模型」当成「全部合规」。"
        )

    # ★ 未映射检查：映射类覆盖不到的表 ⇒ 本模块看不见它的写入者。
    mapped_tables = {t for ts in cls2tbl.values() for t in ts}
    unmapped_tables = sorted(tables - mapped_tables)
    if unmapped_tables:
        raise TableWritersError(
            f"metadata 里有 {len(unmapped_tables)} 张表不属于任何映射类：{unmapped_tables}。"
            "本模块只从映射类出发识别写入者，这种表它会**看不见** —— "
            "此时任何「无写入者」的结论都是假的。请先给它们建映射类，或扩展本模块的识别面。"
        )

    unknown_allow = sorted(set(FROZEN_ALLOWLIST) - tables)
    if unknown_allow:
        raise TableWritersError(
            f"白名单引用了不存在的表：{unknown_allow} —— 表已被删/改名，"
            "请同步删除这些白名单条目（白名单正在腐化）。"
        )

    return evaluate(tables, found)


def _main() -> int:  # pragma: no cover - CLI
    rep = inventory()
    if "--json" in sys.argv:
        print(
            json.dumps(
                {
                    "tables": len(rep.tables),
                    "unwritten": list(rep.unwritten),
                    "demo_only": list(rep.demo_only),
                    "allowlist_hit": list(rep.allowlist_hit),
                    "allowlist_stale": list(rep.allowlist_stale),
                    "violations": list(rep.violations),
                    "writers": {
                        t: [str(h) for h in hits] for t, hits in rep.writers.items() if hits
                    },
                },
                ensure_ascii=False,
                indent=2,
            )
        )
    else:
        print("=" * 78)
        print(f"表总数 = {len(rep.tables)}   "
              f"有写入者 = {len(rep.tables) - len(rep.unwritten)}   "
              f"无写入者 = {len(rep.unwritten)}")
        print("=" * 78)
        print(f"【违规 · 无写入者且未登记】{len(rep.violations)} 张")
        for t in rep.violations:
            print(f"   !! {t}")
        print(f"【已登记欠债 · 白名单】{len(rep.allowlist_hit)} 张")
        for t in rep.allowlist_hit:
            print(f"   --  {t}")
        print(f"【白名单已失效 · 必须删条目】{len(rep.allowlist_stale)} 张")
        for t in rep.allowlist_stale:
            print(f"   ??  {t}")
        print(f"【仅有演示来源写入者 · 观测项，非判据】{len(rep.demo_only)} 张")
        for t in rep.demo_only:
            print(f"   ~   {t}")
        print("-" * 78)
        print("【写入者分布（前 12）】")
        for t in rep.tables[:12]:
            hits = rep.writers.get(t, ())
            mark = "  " if hits else "!!"
            files = sorted({h.file for h in hits})
            print(f" {mark} {t:<34} {len(hits):>3} 处  {', '.join(files[:2])}")
    return 1 if rep.violations else 0


if __name__ == "__main__":
    raise SystemExit(_main())
