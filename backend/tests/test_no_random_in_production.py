# -*- coding: utf-8 -*-
"""
后端 random 使用棘轮门禁（任务 #730）

背景
----
第 164 轮盘查发现：生产 agent 里有大量「用 random 编造业务数据」的代码 ——
同一张主图每次调用得到不同的合规报告、随机编出订单状态/运单号、
随机决定广告指标。这类代码的危害不是「假」，而是**静默的假**：
调用方拿到的 dict 长得和真数据一模一样，没有任何信号说这是编的。

本门禁把「生产模块里的 random 用量」变成**只减不增**的棘轮：
新代码加不进来，已有存量逐项归零（见任务 #723）。

判据形态
--------
一律走 **AST**，不用字符串匹配 —— 源码字符串会骗过判据
（第 164 轮三次实例：自己写的修复说明 docstring 让 `marker in source` 型判据假绿/假红）。

扫描范围（显式口径，不许含糊）
------------------------------
**纳入**：`backend/` 全树下的 .py

**排除**（每一条都必须有理由，不许用模糊通配）：
  1. 目录 `tests/` —— 测试可以用随机数造夹具
  2. 目录 `__pycache__/` `.pytest_cache/` `node_modules/` `.venv/` `venv/` —— 非源码
  3. 目录 `alembic/` `migrations/` —— 迁移脚本 + `versions/` 是生成物
  4. 文件名 `conftest.py` / `test_*.py` / `*_test.py`
  5. **显式 mock 模块**：文件名含 `mock` 的 .py（当前恰有 2 个，见
     `_KNOWN_MOCK_MODULES`）。理由：这些模块的「假」写在名字里、是公开的，
     而且它们的唯一入口 `modules.amazon_sp.get_data_source()` 在缺凭据时会
     `logger.warning`（「有声的假数据」）。与之相对，`platforms/amazon/client.py`
     的假数据是**静默**的 —— 所以它在基线里、必须归零。
     ★ 这份清单被 `test_excluded_mock_modules_are_exactly_the_known_list` 钉住：
       想要靠「新建一个 mock_xxx.py 把 random 藏进去」绕过门禁 ⇒ 直接红。

定位声明（读基线前必读）
------------------------
★ **`_BASELINE` 不是"缺陷清单"，是"现状快照"。**

本门禁管的是「生产模块里出现 random」这个**事实**，不区分用途。基线的存量里既有
「编造业务数据」（必须接真源），也有「用 random 挑文案 / 生成编号」—— 后者严格说不是
业务数据缺陷，但同一输入每次跑出不同结果，同样是不可复现的坏味道，该用 `uuid4()` /
常量替掉。所以**归零是统一目标**，不必为每一处争"算不算缺陷"。

归零进度（任务 #723）
--------------------
  - 建门禁时（第 165 轮实测）：**40** 处 / 4 文件。
  - 第 166 轮第一层（已落地，-15）：
      * 生成 ID / 编号 4 处 → `uuid4().hex[:6]`（ticket_id / conv_id / asset id / image id）
      * 模板池挑选 8 处 → `_stable_pick(md5(key) % n)`：**保留多样性、消除不可复现**
      * 图片 seed 1 处 → `uuid4().int % 99999 + 1`（语义不变，不再往业务数据塞 random）
      * A+ 的 `product_asin` 1 处 → 改为从请求取（不再凭空编 `B0<randint>`）
      * 翻译的关键词位置 1 处 → 改为在译文里**真检测**（并新增 `absent` 状态）
  - **当前：25 处 / 2 文件**
      * `modules/aigc_media/agent_aigc.py` 11 处 —— 视觉评分 5 + CTR 预测 3 +
        A/B 预期增幅 2 + A+ 模块 SEO 评分 1。归宿是「接真源，或改成显式的『未测』状态」
        （与 `#728` 对合规子块的处置同形）。
      * `platforms/amazon/client.py` 14 处 —— 旧适配器的编数（已逐点打 MOCK 告警）。
        归宿不是改这个文件，而是**消费方改走 `modules.amazon_sp.get_data_source()`**；
        在此之前它们留在基线里，靠 `test_no_file_exceeds_baseline` 冻结住。
  - 目标：**0**。

口径差异提示：第 164 轮登记的任务口径是「55 处 random 待处置」，比这里的初始 40 处大，
差额来自 —— 本门禁排除了 `tests/`、排除了显式 mock 模块（`mock_source.py` 等），
以及白名单里的退避抖动。对账时请以本文件 `_scan_backend()` 的实测为准。

白名单（上限 2 项，按 (文件, 函数) 精确匹配）
--------------------------------------------
只有「产出的根本不是业务数据」才配进白名单，且每项必须写明理由。
白名单项**不计入基线**。
"""

from __future__ import annotations

import ast
from pathlib import Path

BACKEND_ROOT = Path(__file__).resolve().parent.parent

# ---------------------------------------------------------------------------
# 排除口径
# ---------------------------------------------------------------------------
_SKIP_DIR_NAMES = frozenset({
    "tests",
    "__pycache__", ".pytest_cache", "node_modules", ".venv", "venv",
    "alembic", "migrations",
})
_SKIP_FILE_NAMES = frozenset({"conftest.py"})


def _is_test_file(name: str) -> bool:
    return name.startswith("test_") or name.endswith("_test.py")


def _is_mock_module(rel: str) -> bool:
    """显式 mock 模块：文件名（含路径末段）里带 mock 的 .py。"""
    return "mock" in Path(rel).name.lower()


#: 被排除的显式 mock 模块 —— 必须**恰好**等于这个集合（元判据钉死）
_KNOWN_MOCK_MODULES = frozenset({
    "modules/amazon_sp/data_sources/mock_source.py",
    "scripts/generate_amazon_mock_data.py",
})

# ---------------------------------------------------------------------------
# 白名单：只有「产物不是业务数据」的 random 才能进来
# ---------------------------------------------------------------------------
_WHITELIST: dict[tuple[str, str], str] = {
    ("core/resilience.py", "delay_for"): (
        "退避抖动：raw *= 1.0 + random.uniform(-jitter, jitter)，用于打散重试时刻、"
        "避免多点同时重试造成惊群（thundering herd）。它产出的不是业务数据，"
        "不进入任何响应体；且 RetryPolicy.jitter 默认 0.0 ⇒ 默认路径下这个分支根本不执行，"
        "连随机都不产生。"
    ),
}
_WHITELIST_LIMIT = 2

# ---------------------------------------------------------------------------
# 基线：**现测现算**（第 164 轮三次修复后重测），只许减不许增
# ---------------------------------------------------------------------------
#: 逐文件快照。任何文件实测 > 基线 ⇒ 红；不在表里却有 random 的文件 ⇒ 红。
#: ★ 这张表里的每一处都是「编造业务数据」，归宿是 0（任务 #723 逐项处理）。
#: ★ 归零一处就同步下调一次；降到 0 的文件必须**整条删掉** —— 不许留 0 值空壳，
#:   `test_baseline_has_no_empty_entries` 守着。已归零并删除的条目：
#:   `modules/customer_service/agent_cs.py`（3 → 0）、`modules/aigc_media/asset_gen.py`（1 → 0）。
_BASELINE: dict[str, int] = {
    "modules/aigc_media/agent_aigc.py": 11,   # 视觉评分 5 + CTR 预测 3 + A/B 预期 2 + SEO 评分 1
    "platforms/amazon/client.py": 14,         # 旧适配器编商品/关键词/评论（已有告警，待退役）
}

#: 冻结上限：`_BASELINE` 只允许**往下降**（记录归零进度），任何时候都不许超过这里的值。
#: 冻结值 = 建门禁那天的实测快照，之后不动。
_BASELINE_HARD_CAP: dict[str, int] = {
    "modules/aigc_media/agent_aigc.py": 22,
    "platforms/amazon/client.py": 14,
}
#: ★ 已归零的两个文件**从上限表里删掉**（而不是填 0）—— 它们现在受
#:   `test_no_new_file_gains_random` 管：一旦有人再往它们里加 random，直接红。

# ---------------------------------------------------------------------------
# 扫描器
# ---------------------------------------------------------------------------


class _ScanResult:
    __slots__ = ("hits", "star_import_lines", "scanned_files")

    def __init__(self) -> None:
        self.hits: list[dict] = []          # {file, func, line, code}
        self.star_import_lines: list[int] = []
        self.scanned_files: int = 0


#: 全树扫描结果缓存（见 `_scan_backend` docstring）
_SCAN_CACHE: "tuple[_ScanResult, set[str]] | None" = None


def _enclosing_scopes(tree: ast.AST) -> dict[int, str]:
    """
    建立 `节点id -> 最近的外层作用域名`（函数名优先，其次类名，顶层为 `<module>`）。

    ★ 不能用「先后 setdefault」的 BFS 写法：`ast.walk` 是 BFS，遇到 ClassDef 时会把
      类里所有后代（含方法体内的节点）一次性标成类名，于是方法名永远盖不上去，
      白名单想按方法精确匹配就永远匹配不到。
    """
    owner: dict[int, str] = {}

    def visit(node: ast.AST, scope: str) -> None:
        for child in ast.iter_child_nodes(node):
            if isinstance(child, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)):
                child_scope = child.name
            else:
                child_scope = scope
            owner[id(child)] = child_scope
            visit(child, child_scope)

    visit(tree, "<module>")
    return owner


def _collect_random_bindings(tree: ast.AST, src: str):
    """
    收集本文件里所有「指向 random 的名字」：

      - `import random`            -> module_alias {"random"}
      - `import random as rnd`     -> module_alias {"rnd"}
      - `from random import randint [as ri]` -> from_names {"randint"} / {"ri"}
      - `from random import *`     -> star_import（反模式，单独断言）
      - `X = random.Random(seed)`  -> rng_alias {"X"}（后续 `X.uniform(...)` 也要算命中，
                                      否则把随机数藏进实例方法就绕过了模块级扫描）
    """
    module_alias: set[str] = set()
    from_names: set[str] = set()
    rng_alias: set[str] = set()
    star_line: list[int] = []

    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            for a in node.names:
                if a.name == "random":
                    module_alias.add(a.asname or "random")
        elif isinstance(node, ast.ImportFrom) and node.module == "random":
            for a in node.names:
                if a.name == "*":
                    star_line.append(node.lineno)
                else:
                    from_names.add(a.asname or a.name)
        elif isinstance(node, ast.Assign) and isinstance(node.value, ast.Call):
            fn = node.value.func
            if (
                isinstance(fn, ast.Attribute)
                and fn.attr in {"Random", "seed"}
                and isinstance(fn.value, ast.Name)
                and fn.value.id in module_alias
            ):
                for tgt in node.targets:
                    seg = ast.get_source_segment(src, tgt)
                    if seg:
                        rng_alias.add(seg)

    return module_alias, from_names, rng_alias, star_line


def _scan_source(src: str, rel: str) -> tuple[list[dict], list[int]]:
    """扫一段源码，返回 (命中列表, `from random import *` 的行号列表)。"""
    tree = ast.parse(src)
    owner = _enclosing_scopes(tree)
    module_alias, from_names, rng_alias, star_lines = _collect_random_bindings(tree, src)

    hits: list[dict] = []
    for node in ast.walk(tree):
        hit = False
        if isinstance(node, ast.Attribute):
            if isinstance(node.value, ast.Name) and node.value.id in module_alias:
                hit = True
            elif rng_alias:
                seg = ast.get_source_segment(src, node.value)
                if seg and seg in rng_alias:
                    hit = True
        elif isinstance(node, ast.Name) and node.id in from_names:
            hit = True

        if hit:
            code = (ast.get_source_segment(src, node) or "").splitlines()[0][:90]
            hits.append({
                "file": rel,
                "func": owner.get(id(node), "<module>"),
                "line": node.lineno,
                "code": code,
            })

    # 去重：同一行同一表达式可能被 Attribute/Name 两条通路各命中一次
    dedup: dict[tuple, dict] = {}
    for h in hits:
        dedup.setdefault((h["file"], h["line"], h["code"]), h)
    return sorted(dedup.values(), key=lambda h: h["line"]), star_lines


def _iter_source_files():
    for path in sorted(BACKEND_ROOT.rglob("*.py")):
        rel = path.relative_to(BACKEND_ROOT).as_posix()
        parts = rel.split("/")
        if any(p in _SKIP_DIR_NAMES for p in parts[:-1]):
            continue
        name = parts[-1]
        if name in _SKIP_FILE_NAMES or _is_test_file(name):
            continue
        yield rel, path


def _scan_backend() -> tuple[_ScanResult, set[str]]:
    """
    跑全仓扫描，返回 (扫描结果, 被排除的显式 mock 模块集合)。

    ★ 结果在一次 pytest 进程内缓存：全树扫描要对数百个 .py 做 `ast.parse`，
       14 条用例各扫一遍会让这个门禁慢到没人愿意跑（而没人跑的判据等于没有）。
       缓存不会掩盖改动 —— 反向注入是由外部脚本改完文件后**新起进程**跑的。
       调用方一律只读返回对象，不得原地修改 `res.hits`。
    """
    global _SCAN_CACHE
    if _SCAN_CACHE is not None:
        return _SCAN_CACHE

    res = _ScanResult()
    excluded_mock: set[str] = set()

    for rel, path in _iter_source_files():
        if _is_mock_module(rel):
            excluded_mock.add(rel)
            continue
        try:
            src = path.read_bytes().decode("utf-8", errors="replace")
            hits, star_lines = _scan_source(src, rel)
        except SyntaxError as exc:  # 语法都过不了的 .py 不进统计（另有编译门禁管它）
            print(f"[gate-730] 跳过语法错误文件 {rel}: {exc}")
            continue
        res.scanned_files += 1
        res.hits.extend(hits)
        res.star_import_lines.extend((rel, ln) for ln in star_lines)

    _SCAN_CACHE = (res, excluded_mock)
    return _SCAN_CACHE


# ---------------------------------------------------------------------------
# 派生视图
# ---------------------------------------------------------------------------


def _whitelisted_hits(hits: list[dict]) -> list[dict]:
    return [h for h in hits if (h["file"], h["func"]) in _WHITELIST]


def _counted_hits(hits: list[dict]) -> list[dict]:
    """扣掉白名单后的「要计入棘轮」的命中。"""
    return [h for h in hits if (h["file"], h["func"]) not in _WHITELIST]


def _by_file(hits: list[dict]) -> dict[str, list[dict]]:
    out: dict[str, list[dict]] = {}
    for h in hits:
        out.setdefault(h["file"], []).append(h)
    return out


def _fmt(hits: list[dict]) -> str:
    return "\n".join(f"    {h['file']}:{h['line']} [{h['func']}] {h['code']}" for h in hits)


# ---------------------------------------------------------------------------
# 门禁
# ---------------------------------------------------------------------------


def test_detector_is_not_vacuous():
    """
    ★ 常驻正向对照：把「已知含 random 的合成源码」喂给扫描器，必须精确命中。

    没有这一条，扫描器一旦静默失效（别名没收集到 / walk 写错 / 路径不通），
    全仓就会「零命中 ⇒ 恒绿」—— 门禁看起来一直在跑，实际什么都没查。
    这是「没被反向注入验证过的门禁 = 没有门禁」的自动化版本。
    """
    sample = (
        "import random\n"
        "import random as rnd\n"
        "from random import randint\n"
        "from random import choice as pick\n"
        "\n"
        "def f():\n"
        "    a = random.randint(1, 9)\n"
        "    b = rnd.uniform(0.0, 1.0)\n"
        "    c = randint(1, 3)\n"
        "    d = pick([1, 2, 3])\n"
        "    return a, b, c, d\n"
        "\n"
        "def g():\n"
        "    r = random.Random(7)\n"
        "    return r.uniform(0.0, 1.0)\n"
    )
    hits, star = _scan_source(sample, "<synthetic>")
    assert star == [], "合成源码不该触发通配导入判据"
    got = {(h["func"], h["line"]) for h in hits}
    assert len(hits) == 6, (
        f"正向对照失败：合成源码里恰好有 6 处 random 使用"
        f"（f 里 4 处 + g 里 Random 构造与实例方法各 1 处），实际命中 {len(hits)}:\n{_fmt(hits)}"
    )
    assert ("f", 7) in got and ("f", 10) in got, f"裸名导入未被识别：\n{_fmt(hits)}"
    assert ("g", 15) in got, (
        f"`RNG 实例方法`未被追到 —— 把 random 藏进 `r = random.Random(7)` 再 `r.uniform()` "
        f"就会绕过扫描：\n{_fmt(hits)}"
    )
    assert ("g", 14) in got, f"`random.Random(...)` 构造本身也该命中：\n{_fmt(hits)}"


def test_scanner_actually_walked_the_backend_tree():
    """
    ★ 元判据：扫描器必须真的遍历到了一批文件。

    防的失败模式：`BACKEND_ROOT` 算错 / rglob 模式写错 ⇒ 零文件 ⇒ 零命中 ⇒ 恒绿。
    """
    res, _ = _scan_backend()
    assert res.scanned_files >= 100, (
        f"只扫到 {res.scanned_files} 个 .py，明显不对（backend 有数百个模块）—— "
        f"检查 BACKEND_ROOT={BACKEND_ROOT} 与 _SKIP_DIR_NAMES 口径"
    )


def test_no_star_import_of_random_in_production():
    """`from random import *` 会让所有裸名（randint/uniform/...）隐身，直接判红。"""
    res, _ = _scan_backend()
    assert not res.star_import_lines, (
        "生产代码不得 `from random import *`（通配导入让后续裸名调用无法被 AST 判据识别）：\n"
        + "\n".join(f"    {rel}:{ln}" for rel, ln in res.star_import_lines)
    )


def test_excluded_mock_modules_are_exactly_the_known_list():
    """
    ★ 元判据：显式 mock 模块的排除清单必须**恰好**等于已知的 2 个。

    否侧「文件名含 mock 就排除」是一条人为后门 —— 新建一个 `mock_xxx.py`
    把 random 藏进去就绕过了门禁。
    """
    _, excluded_mock = _scan_backend()
    assert excluded_mock == set(_KNOWN_MOCK_MODULES), (
        "被排除的 mock 模块清单变了。若这是有意新增的显式 mock 模块，"
        "请同步更新 _KNOWN_MOCK_MODULES 并在 PR 里说明"
        "「为什么它的假数据是公开可接受的」；否则说明有人用 mock 命名把 random 藏起来了。\n"
        f"  实际排除：{sorted(excluded_mock)}\n"
        f"  预期清单：{sorted(_KNOWN_MOCK_MODULES)}"
    )


def test_no_file_exceeds_baseline():
    """
    ★ 棘轮主判据：逐文件实测 ≤ 基线（扣白名单后）。

    这是本门禁存在的意义 —— 存量只许减不许增。
    """
    res, _ = _scan_backend()
    counted = _counted_hits(res.hits)
    actual = {f: len(hs) for f, hs in _by_file(counted).items()}

    offenders: list[str] = []
    for rel, n in sorted(actual.items()):
        base = _BASELINE.get(rel)
        if base is None:
            offenders.append(f"    {rel}: 新增 {n} 处（该文件不在基线里）")
        elif n > base:
            extra = [h for h in _by_file(counted)[rel]][base:]
            offenders.append(
                f"    {rel}: {n} 处 > 基线 {base} 处（多出 {n - base} 处）：\n"
                + "\n".join(f"       + L{h['line']} [{h['func']}] {h['code']}" for h in extra)
            )

    assert not offenders, (
        "生产模块里的 random 用量**只许减不许增**。新增的 random 请改成接真数据源；"
        "确实不是业务数据的（如退避抖动）请加进 _WHITELIST 并写明理由。\n"
        + "\n".join(offenders)
    )


def test_no_new_file_gains_random():
    """单独一条：不在基线里的文件必须完全干净（便于定位「新文件引入了随机数」）。"""
    res, _ = _scan_backend()
    counted = _counted_hits(res.hits)
    fresh = {
        f: hs for f, hs in _by_file(counted).items()
        if f not in _BASELINE
    }
    assert not fresh, "以下文件不在基线里却出现了 random：\n" + "\n".join(
        f"  {f} ({len(hs)} 处)\n{_fmt(hs)}" for f, hs in sorted(fresh.items())
    )


def test_baseline_files_still_exist_on_disk():
    """防基线烂掉：基线里的文件路径必须仍然存在（文件被改名/挪走 ⇒ 基线静默失效）。"""
    missing = [rel for rel in _BASELINE if not (BACKEND_ROOT / rel).is_file()]
    assert not missing, (
        "基线里的文件已不存在，说明路径变了 —— 请同步更新 _BASELINE，"
        "否则这些存量会脱离棘轮监管：\n" + "\n".join(f"    {m}" for m in missing)
    )


def test_baseline_has_no_empty_entries():
    """基线里不许有 0 值空壳（0 值应该直接删掉，留 0 只会让读者误以为「还有存量」）。"""
    dead = [rel for rel, n in _BASELINE.items() if n <= 0]
    assert not dead, "基线里出现了 0 值条目（应删除）：\n" + "\n".join(f"    {d}" for d in dead)


def test_baseline_is_actually_loaded_and_non_trivial():
    """总基线必须等于各文件之和且 > 0 —— 防手写表被整体改空。"""
    assert _BASELINE, "基线表是空的：棘轮退化成「任何 random 都红」，会让存量无法逐步归零"
    assert sum(_BASELINE.values()) == 25, (
        f"基线总数变了（当前 {sum(_BASELINE.values())}，期望 25）。"
        f"减少是好事，请同步改掉这个数字；增加则说明有人在往回填 random。"
    )


def test_baseline_never_exceeds_hard_cap():
    """
    ★ 基线只许往下降。

    ★ 这条和「棘轮本身可以被改」的边界在哪：
      任何门禁都能靠"直接改门禁文件"绕过 —— 那是 Git 历史 + code review 的职责，
      不是门禁自己能解决的。这条挡的是**无意识的放水**：CI 报红时顺手把基线数字调大
      让它变绿。冻结上限钉在建成那天的实测快照上，要动它就必须显式改这张表，
      改动的意图也就暴露在 diff 里了。
    """
    over = {
        rel: (n, _BASELINE_HARD_CAP[rel])
        for rel, n in _BASELINE.items()
        if rel in _BASELINE_HARD_CAP and n > _BASELINE_HARD_CAP[rel]
    }
    assert not over, (
        "基线被调高了（只许往下降）：\n"
        + "\n".join(f"    {rel}: 基线 {n} > 冻结上限 {cap}" for rel, (n, cap) in over.items())
    )
    assert set(_BASELINE) == set(_BASELINE_HARD_CAP), (
        "基线与冻结上限表的文件集合必须完全一致（否则有文件脱离了上限保护）：\n"
        f"    只在基线里：{sorted(set(_BASELINE) - set(_BASELINE_HARD_CAP))}\n"
        f"    只在上限表里：{sorted(set(_BASELINE_HARD_CAP) - set(_BASELINE))}"
    )


def test_whitelist_is_minimal():
    """白名单上限 2 项 —— 它是「例外」，不是「豁免区」。"""
    assert len(_WHITELIST) <= _WHITELIST_LIMIT, (
        f"白名单有 {len(_WHITELIST)} 项，超过上限 {_WHITELIST_LIMIT}。"
        f"白名单是给「产物根本不是业务数据」的极少数情况用的，不是给存量 random 开后门：\n"
        + "\n".join(f"    {k}" for k in _WHITELIST)
    )


def test_whitelist_entries_are_documented():
    """每项白名单必须写明理由（≥20 字），否则白名单会退化成「不想改就加进去」。"""
    bad = [k for k, why in _WHITELIST.items() if not why or len(why.strip()) < 20]
    assert not bad, "白名单条目缺少充分理由：\n" + "\n".join(f"    {k}" for k in bad)


def test_whitelist_entries_still_present():
    """
    ★ 白名单不许腐烂：每一项都必须在源码里**真的还有** random 命中。

    否则它会变成一枚永久后门 —— 原代码早被改掉了，白名单还挂着，
    将来同一个函数里新加的 random 会被静默放过。
    """
    res, _ = _scan_backend()
    live = {(h["file"], h["func"]) for h in res.hits}
    stale = [k for k in _WHITELIST if k not in live]
    assert not stale, (
        "白名单条目已失效（对应文件/函数里已经没有 random 了）—— 请删除这些条目：\n"
        + "\n".join(f"    {k}" for k in stale)
    )


def test_whitelisted_files_are_not_in_baseline():
    """白名单文件不该同时出现在基线里（口径重叠会让「归零进度」读不准）。"""
    overlap = {rel for rel, _ in _WHITELIST} & set(_BASELINE)
    assert not overlap, (
        f"以下文件既在白名单又在基线里：{sorted(overlap)}。"
        f"白名单是整体豁免（其命中不计入棘轮），基线是「还有存量待归零」，两者语义冲突。"
    )
