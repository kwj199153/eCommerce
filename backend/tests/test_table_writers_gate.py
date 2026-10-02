"""「表必须有写入者」门禁（第 357 轮 · L3-16）。

==============================================================================
★ 为什么要有这道门禁（r332 §8 建议 4 原文）
==============================================================================
  > 同时补一道"表必须有写入者"门禁（现在的 `test_schema_parity.py` 只判外键，
  > 不判写入者）。

`test_schema_parity.py` 判的是**外键目标可达**；**没有任何门禁**判「这张表到底
有没有人往里写」。于是「DDL 建好、迁移齐全、外键全对、生产代码零写入」的表可以
长期存在，而且**一声不响** —— 它不是表，是墓碑。

r357 实测：`Base.metadata.tables` 共 57 张，其中 5 张零写入者，全在
`modules/amazon_sp/db_model.py`（`amazon_daily_sales` / `amazon_ad_metrics` /
`amazon_listing_snapshots` / `amazon_report_tasks` / `amazon_inventory_health`）。
它们已按「②暂不处置」登记进 `scripts/table_writers.py::FROZEN_ALLOWLIST`
（**欠债台账**，不是永久豁免：一旦接上写入者，本门禁会红并要求删条目）。

==============================================================================
★ 口径与实现都在唯一真源
==============================================================================
`scripts/table_writers.py`（照 `scripts/route_inventory.py` 的范式：
盘点逻辑住 `scripts/`，门禁只 import 它做断言）。
**本文件不做任何集合运算** —— 判据全在 `Report` 上，避免「同一判定两份实现」。

==============================================================================
★ 自证（照 `test_schema_parity.py` 的体例）
==============================================================================
1. **非空转**：另起一个全新解释器子进程，独立问一遍 SQLAlchemy，表集合必须一致。
   （子进程只 import，不连库 —— 与 `test_schema_parity` 的做法同源。）
2. **反向注入**：证明本判据有牙齿 ——
   - 判据层：无写入者且不在台账 ⇒ `violations` 非空；台账条目一旦表有了写入者
     ⇒ `allowlist_stale` 非空；
   - 扫描层：W1–W5 五种写作形态都要认出来，而**注释 / docstring / 字符串里的
     同形文本 / 被赋值的同名局部变量**一个都不许算；
   - 失明层：三道「宁可炸不许猜」的检查各注入一次，必须抛 `TableWritersError`。
   ★ 本仓铁律：「没被反向注入验证过的门禁 = 没有门禁」。
"""

from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

import pytest

BACKEND_DIR = Path(__file__).resolve().parents[1]


# ============================================================================
# 一、判据本身（真树）
# ============================================================================
def test_no_unwritten_table_outside_allowlist():
    """每张表要么有生产写入者，要么在欠债台账里。"""
    from scripts.table_writers import inventory

    rep = inventory()
    assert rep.violations == (), (
        "这些表有 DDL、有迁移，却**没有任何生产写入者**（既没接线也没登记台账）：\n  "
        + "\n  ".join(rep.violations)
        + "\n\n处置二选一（r332 §8 建议 4）："
        "\n  ① 接线为真实写入者；"
        "\n  ② 移出 register_all_models() 并写迁移 drop。"
        "\n若暂时不处置，请登记进 scripts/table_writers.py::FROZEN_ALLOWLIST 并写明理由。"
    )


def test_allowlist_has_no_stale_entry():
    """台账是欠债清单：表一旦接上写入者（或表名消失），条目必须删掉。"""
    from scripts.table_writers import FROZEN_ALLOWLIST, inventory

    rep = inventory()
    assert rep.allowlist_stale == (), (
        "台账里这些条目已经失效（对应的表已接上写入者）：\n  "
        + "\n  ".join(rep.allowlist_stale)
        + "\n\n它们不再是欠债 —— 请从 FROZEN_ALLOWLIST 删除对应条目，"
        "否则台账会退化成「永久豁免名单」。"
    )
    assert len(rep.allowlist_hit) == len(FROZEN_ALLOWLIST), (
        "台账条目数 == 已登记欠债数 必须成立："
        f"台账 {len(FROZEN_ALLOWLIST)} 条 / 命中 {len(rep.allowlist_hit)} 条。"
        "两者不等说明 allowlist_hit 与 allowlist_stale 的划分漏了东西。"
    )


# ============================================================================
# 二、非空转自证：全新解释器独立问一遍 SQLAlchemy
# ============================================================================
def test_fresh_interpreter_sees_the_same_table_set():
    """另起进程独立取一次表清单，必须与 `inventory()` 完全一致。

    ★ 为什么必须「另起进程」：本进程的 SQLAlchemy registry 已经被 import 过，
      同进程再问一遍等于自证「我把我的话又说了一遍」。
    ★ 子进程只 import 不连库 ⇒ 与其它测试并发安全。
    """
    script = (
        "import os, sys, json\n"
        f"root = r'{BACKEND_DIR}'\n"
        "os.chdir(root)\n"
        "sys.path.insert(0, root)\n"
        "from core.database import Base, register_all_models\n"
        "from wiring import MODEL_MODULES\n"
        "register_all_models(MODEL_MODULES)\n"
        "print('R357_TABLES=' + json.dumps(sorted(Base.metadata.tables)))\n"
    )
    proc = subprocess.run(
        [sys.executable, "-c", script],
        cwd=str(BACKEND_DIR),
        capture_output=True,
        text=True,
        timeout=300,
    )
    assert proc.returncode == 0, f"子进程失败：\n{proc.stdout}\n{proc.stderr}"
    hit = [ln for ln in proc.stdout.splitlines() if ln.startswith("R357_TABLES=")]
    assert hit, f"子进程没吐出表清单（扫描可疑）：\n{proc.stdout}\n{proc.stderr}"
    fresh = json.loads(hit[0].split("=", 1)[1])

    from scripts.table_writers import inventory

    rep = inventory()
    # inventory() 内部已挡住「表数 < MIN_PLAUSIBLE_TABLES」，所以这里
    # 不需要再写一遍阈值（那是同一判定两份实现）；两边一致即证明非空转。
    assert list(rep.tables) == fresh, (
        "两个独立口径看到的表集合不一致："
        f"本模块 {len(rep.tables)} 张 / 子进程 {len(fresh)} 张。"
        f"\n只在子进程里有的：{sorted(set(fresh) - set(rep.tables))}"
        f"\n只在模块里有的：{sorted(set(rep.tables) - set(fresh))}"
    )


# ============================================================================
# 三、扫描层反向注入：认哪些形态、不认哪些形态
# ============================================================================
def _cls2tbl() -> dict:
    return {"Widget": {"widgets"}, "Gadget": {"gadgets"}}


def test_scan_source_recognizes_every_writer_form():
    """W1–W5 五种写入形态，每一种都必须被认出来。"""
    from scripts.table_writers import scan_source

    forms = {
        "W1 实例化": "from m import Widget\n\n\ndef f():\n    return Widget()\n",
        "W1 模块级": "from m import Widget\n\nw = Widget()\n",
        "W1 带模块前缀": "from m import db\n\nw = db.Widget()\n",
        "W2 类名": "from m import Widget\nfrom sqlalchemy import insert\n\nq = insert(Widget)\n",
        "W2 表名字面量": "from sqlalchemy import insert\n\nq = insert('widgets')\n",
        "W2 __table__": "from m import Widget\nfrom sqlalchemy import insert\n\nq = insert(Widget.__table__)\n",
        "W3 pg_insert": (
            "from m import Widget\n"
            "from sqlalchemy.dialects.postgresql import insert as pg_insert\n\n"
            "q = pg_insert(Widget)\n"
        ),
        "W4 bulk_insert_mappings": "from m import Widget\n\ns.bulk_insert_mappings(Widget, [{'a': 1}])\n",
        "W4 bulk_save_objects": "from m import Widget\n\ns.bulk_save_objects([Widget()])\n",
        "W5 表对象 insert": "from m import Widget\n\nq = Widget.__table__.insert()\n",
    }
    for label, src in forms.items():
        hits = scan_source("probe.py", src, _cls2tbl())
        assert hits, f"[{label}] 没认出来（这就是「门禁失明」）:\n{src}"
        assert {h.table for h in hits} <= {"widgets", "gadgets"}, f"[{label}] 认到了别的表：{hits}"


def test_scan_source_ignores_text_that_is_not_a_writer():
    """注释 / docstring / 字符串 / 被赋值的同名局部变量，一个都不许算。"""
    from scripts.table_writers import scan_source

    non_writers = {
        "注释": "# from m import Widget\n# db.add(Widget())\n",
        "docstring": '"""用法示例：\n\n    from m import Widget\n    db.add(Widget())\n    insert("widgets")\n"""\n',
        "普通字符串": "s = 'Widget()'\nt = 'insert(\"widgets\")'\n",
        "被赋值的同名局部变量": "Widget = object\n\nw = Widget()\n",
        "只是函数名叫 insert_other": "def insert_other(x):\n    return x\n\ny = insert_other('widgets')\n",
    }
    for label, src in non_writers.items():
        hits = scan_source("probe.py", src, _cls2tbl())
        assert not hits, f"[{label}] 被误判成写入者（假绿方向是允许的，但假命中会掩盖死表）:\n{src}"


def test_scan_source_reports_where_it_found_it():
    """命中要带得上文件 / 行号 / 所属函数 —— 报告得能定位到人。"""
    from scripts.table_writers import scan_source

    src = "from m import Widget\n\n\ndef save_widget():\n    db.add(Widget())\n"
    hits = scan_source("pkg/mod.py", src, _cls2tbl())
    assert len(hits) == 1
    h = hits[0]
    assert (h.table, h.file, h.func, h.kind) == ("widgets", "pkg/mod.py", "save_widget", "W1-instantiate")
    assert h.line == 5


# ============================================================================
# 四、判据层反向注入：「删掉唯一写入者 ⇒ 必须红」
# ============================================================================
def test_evaluate_flags_table_that_lost_its_only_writer():
    from scripts.table_writers import Hit, evaluate

    hit = Hit(table="widgets", file="a.py", line=1, func="f", kind="W1-instantiate")

    # 有写入者 ⇒ 不违规
    ok = evaluate({"widgets"}, {"widgets": [hit]}, allowlist={})
    assert ok.violations == () and ok.unwritten == ()

    # ★ 删掉唯一写入者 ⇒ 立刻违规
    bad = evaluate({"widgets"}, {"widgets": []}, allowlist={})
    assert bad.unwritten == ("widgets",)
    assert bad.violations == ("widgets",), "删掉唯一写入者后没能转红 —— 门禁没有牙齿"

    # 登记进台账 ⇒ 从 violations 移出，变成「已登记欠债」
    logged = evaluate({"widgets"}, {"widgets": []}, allowlist={"widgets": "在台账里"})
    assert logged.violations == ()
    assert logged.allowlist_hit == ("widgets",)


def test_evaluate_marks_allowlist_entry_stale_once_table_gets_written():
    """台账条目反向失效：表接上写入者后，条目必须报 stale。"""
    from scripts.table_writers import Hit, evaluate

    hit = Hit(table="widgets", file="a.py", line=1, func="f", kind="W1-instantiate")
    rep = evaluate({"widgets"}, {"widgets": [hit]}, allowlist={"widgets": "曾经是欠债"})
    assert rep.allowlist_stale == ("widgets",), "台账条目失效了却没报 stale —— 台账会烂在文件里"
    assert rep.allowlist_hit == ()


def test_evaluate_separates_demo_only_writers_from_real_ones():
    """只有 seed/bootstrap 写入者的表要单独标出来（观测项，当前不作判据）。"""
    from scripts.table_writers import Hit, evaluate

    demo = Hit(table="widgets", file="backend/scripts/seed_demo.py", line=1, func="f", kind="W1-instantiate")
    prod = Hit(table="gadgets", file="backend/modules/x/repo.py", line=1, func="f", kind="W1-instantiate")
    rep = evaluate({"widgets", "gadgets"}, {"widgets": [demo], "gadgets": [prod]}, allowlist={})
    assert rep.demo_only == ("widgets",)
    assert rep.unwritten == ()


# ============================================================================
# 五、失明层反向注入：三道「宁可炸不许猜」的检查
# ============================================================================
def _fake_registry(n: int = 40, extra_tables: set | None = None):
    tables = {f"t{i}" for i in range(n)} | (extra_tables or set())
    cls2tbl = {f"C{i}": {f"t{i}"} for i in range(n)}
    return tables, cls2tbl


def _synthetic_registry():
    """40 张占位表 + widgets / gadgets 两张有映射类的表。

    ★ 规模必须**高于 MIN_PLAUSIBLE_TABLES**，否则会先撞上「盘点失明」那道检查
      —— 第一次写这个用例时就撞了，而那恰好证明那道检查真的有牙齿。
    """
    tables, cls2tbl = _fake_registry(40)
    cls2tbl = dict(cls2tbl, Widget={"widgets"}, Gadget={"gadgets"})
    return tables | {"widgets", "gadgets"}, cls2tbl


def test_inventory_raises_when_scan_is_blind(monkeypatch):
    """注册 0 个模型时，绝不能得出「0 张表 ⇒ 全部合规」。"""
    from scripts import table_writers as tw

    monkeypatch.setattr(tw, "_load_registry", lambda: (set(), {}))
    with pytest.raises(tw.TableWritersError, match="失明"):
        tw.inventory()


def test_inventory_raises_when_a_metadata_table_has_no_mapped_class(monkeypatch):
    """未映射的表本模块看不见 ⇒ 任何「无写入者」的结论都是假的。"""
    from scripts import table_writers as tw

    monkeypatch.setattr(tw, "_load_registry", lambda: _fake_registry(40, {"ghost"}))
    monkeypatch.setattr(tw, "iter_source_files", lambda: [])
    with pytest.raises(tw.TableWritersError, match="不属于任何映射类"):
        tw.inventory()


def test_inventory_raises_when_allowlist_names_a_missing_table(monkeypatch):
    """台账里留着已被删/改名的表 ⇒ 这是台账腐化的信号。"""
    from scripts import table_writers as tw

    monkeypatch.setattr(tw, "_load_registry", lambda: _fake_registry(40))
    monkeypatch.setattr(tw, "iter_source_files", lambda: [])
    monkeypatch.setattr(tw, "FROZEN_ALLOWLIST", {"t0": "在", "已删掉的表": "还在台账里"})
    with pytest.raises(tw.TableWritersError, match="不存在的表"):
        tw.inventory()


def test_inventory_end_to_end_on_a_synthetic_tree(monkeypatch, tmp_path):
    """端到端注入：合成 registry + 合成源码，走完整 `inventory()` 链路。

    ★ 用合成输入而不是真树：真树注入要么得改真实仓库文件（慢且危险），
      要么得复制扫描面。纯函数 + 可注入入口已经把这两条路都免了。
    """
    from scripts import table_writers as tw

    probe = tmp_path / "probe.py"
    probe.write_text(
        "from m import Widget\n"
        "from sqlalchemy import insert\n"
        "\n"
        "\n"
        "def save():\n"
        "    db.add(Widget())\n"
        "    return insert('gadgets')\n",
        encoding="utf-8",
    )

    registry = _synthetic_registry()
    monkeypatch.setattr(tw, "ROOT", tmp_path)
    monkeypatch.setattr(tw, "iter_source_files", lambda: [probe])
    monkeypatch.setattr(tw, "_load_registry", lambda: registry)
    monkeypatch.setattr(tw, "FROZEN_ALLOWLIST", {"gadgets": "台账里的一条"})

    rep = tw.inventory()
    assert rep.tables == tuple(sorted(registry[0]))
    assert "widgets" not in rep.unwritten, "W1 实例化没被认出来"
    assert "gadgets" not in rep.unwritten, "W2 表名字面量 insert 没被认出来"
    assert rep.allowlist_stale == ("gadgets",), "表已接上写入者，台账条目应当失效"
