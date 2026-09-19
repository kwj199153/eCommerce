# -*- coding: utf-8 -*-
"""意图识别「唯一真源」的机制契约 + 防回流门禁（批 D2）。

收敛前，全仓有 **6 份**「有序首命中的关键词路由」各写一遍：
`ad_analysis` / `aigc_media` / `competitor_intel` / `customer_service` /
`listing_generator` / `product_research`。

收敛后：**控制流只在 `ai_infra/intent.py` 出现一次**；
6 家的**关键词表 + 默认标签 + 组顺序**作为策略数据留在各自模块。

★ 为什么用**形态**而不用名单：名单会腐烂，而且**两个方向都会错**
  （记忆里实测过「说 6 套实际 3 套」与「说 2 套实际 4 套」）。
  形态不会。本文件的扫描器在收敛前跑出**恰好这 6 家**，收敛后跑出**恰好 0 处**，
  两次读数都是可复算的证据。

★ 光删旧实现不够 —— 还要钉住「6 家真的在用唯一真源」，
  否则下一次完全可以绕开它另写一份（`test_business_modules_call_the_single_source`）。

★ 本文件自带反向注入自检（`test_gate_is_not_vacuous`）：
  构造两种形态的违规样本喂给扫描器，必须报出来；否则「门禁」可能因判据写错而恒绿。
"""
import ast
import pathlib

from ai_infra.intent import Route, first_match

BACKEND = pathlib.Path(__file__).resolve().parents[1]

SCAN_SKIP_DIRS = {
    "tests", ".venv", "__pycache__", "node_modules", ".git", "logs", "data",
    ".pytest_cache", "_attic", ".mypy_cache", "htmlcov",
}

#: 唯一允许出现「有序首命中关键词路由」这种形态的文件
ALLOWED = {"ai_infra/intent.py"}

#: 一个函数里有几条这样的分支才算「又写了一份分类器」
MIN_BRANCHES = 3

#: 6 个业务 Agent：模块路径 -> 其分类器方法名
#: （`aigc_media` 的方法是**公开名** —— `modules/aigc_media/service.py` 直接
#:   `agent.classify_intent(...)` 调用它，不允许改名）
BUSINESS_AGENTS = {
    "modules/ad_analysis/agent_ad.py": "_classify_intent",
    "modules/aigc_media/agent_aigc.py": "classify_intent",
    "modules/competitor_intel/agent_competitor.py": "_classify_intent",
    "modules/customer_service/agent_cs.py": "_classify_intent",
    "modules/listing_generator/agent_listing.py": "_classify_intent",
    "modules/product_research/agent_product_research.py": "_classify_intent",
}


# ------------------------------------------------------------------ 形态扫描

def _is_str_const(node):
    return isinstance(node, ast.Constant) and isinstance(node.value, str)


def _returns_str_like(node):
    """`return "x"` 或 `return "a" if cond else "b"`。

    ★ 后者是真的：`competitor_intel` 有一组「同一组关键词、结果还要再判一次」
      的复合规则，返回值是 IfExp 而不是裸字面量。
    """
    if node is None:
        return False
    if _is_str_const(node):
        return True
    if isinstance(node, ast.IfExp):
        return _returns_str_like(node.body) and _returns_str_like(node.orelse)
    return False


def _body_returns_str_like(body):
    return (len(body) == 1
            and isinstance(body[0], ast.Return)
            and _returns_str_like(body[0].value))


def _compare_is_kw_in_query(test):
    """`<Name> in <Name|Attribute>` —— 左侧是关键词变量、右侧是被查的查询串。"""
    if not isinstance(test, ast.Compare):
        return False
    if not any(isinstance(op, ast.In) for op in test.ops):
        return False
    if not isinstance(test.left, ast.Name):
        return False
    if len(test.comparators) != 1:
        return False
    return isinstance(test.comparators[0], (ast.Name, ast.Attribute))


def _is_loop_route(node):
    """形态 A：

        for kw in KWS:
            if kw in q:
                return "label"
    """
    if not isinstance(node, ast.For):
        return False
    if len(node.body) != 1 or not isinstance(node.body[0], ast.If):
        return False
    inner = node.body[0]
    return _compare_is_kw_in_query(inner.test) and _body_returns_str_like(inner.body)


def _is_any_route(node):
    """形态 B：

        if any(kw in q for kw in KWS):
            return "label"
    """
    if not isinstance(node, ast.If):
        return False
    test = node.test
    if not isinstance(test, ast.Call) or not isinstance(test.func, ast.Name):
        return False
    if test.func.id != "any" or len(test.args) != 1:
        return False
    gen = test.args[0]
    if not isinstance(gen, ast.GeneratorExp):
        return False
    if not _compare_is_kw_in_query(gen.elt):
        return False
    return _body_returns_str_like(node.body)


def route_branches(fn):
    """统计函数体内『关键词路由分支』的条数（两种形态并列）。"""
    return sum(1 for n in ast.walk(fn)
               if _is_loop_route(n) or _is_any_route(n))


def _scan_tree():
    """返回 {相对路径: {函数名: 分支数}}。"""
    found = {}
    for path in sorted(BACKEND.rglob("*.py")):
        if any(part in SCAN_SKIP_DIRS for part in path.relative_to(BACKEND).parts):
            continue
        rel = path.relative_to(BACKEND).as_posix()
        try:
            tree = ast.parse(path.read_text(encoding="utf-8", errors="replace"))
        except SyntaxError:
            continue
        per_fn = {}
        for node in ast.walk(tree):
            if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
                n = route_branches(node)
                if n >= MIN_BRANCHES:
                    per_fn[node.name] = n
        if per_fn:
            found[rel] = per_fn
    return found


# ------------------------------------------------------------------ ① 形态门禁

def test_keyword_route_form_only_in_intent_module():
    """★ 形态门禁：『有序首命中关键词路由』只许写在 `ai_infra/intent.py`。

    失败信息直接给出**文件 + 函数名 + 分支数**，比维护一份名单有用得多。
    """
    offenders = {rel: fns for rel, fns in _scan_tree().items() if rel not in ALLOWED}
    assert not offenders, (
        "发现唯一真源（ai_infra/intent.py）之外又写了一份关键词路由：\n  "
        + "\n  ".join(f"{rel}: {fns}" for rel, fns in sorted(offenders.items()))
        + "\n应改为：把它变成 `Route(label, keywords)` 策略数据 + 调用 `first_match()`。"
    )


# --------------------------------------------------- ② 6 家真的在用唯一真源

def test_business_modules_call_the_single_source():
    """★ 只删旧实现不够：6 家必须**真的**通过唯一真源做判定。

    逐家断言三件事：① 导入了 `ai_infra.intent`；② 分类器里调用了 `first_match`；
    ③ 分类器里**不再有**内联的关键词路由分支。
    """
    bad = []
    for rel, meth in BUSINESS_AGENTS.items():
        path = BACKEND / rel
        src = path.read_text(encoding="utf-8", errors="replace")
        if "from ai_infra.intent import" not in src:
            bad.append(f"{rel}: 未 import 唯一真源")
        fn = None
        for node in ast.walk(ast.parse(src)):
            if (isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef))
                    and node.name == meth):
                fn = node
        if fn is None:
            bad.append(f"{rel}: 找不到分类器 {meth}")
            continue
        called = {n.func.id for n in ast.walk(fn)
                  if isinstance(n, ast.Call) and isinstance(n.func, ast.Name)}
        if "first_match" not in called:
            bad.append(f"{rel}: {meth} 没有调用 first_match")
        n_inline = route_branches(fn)
        if n_inline:
            bad.append(f"{rel}: {meth} 里仍有 {n_inline} 条内联关键词路由")
    assert not bad, "未真正使用唯一真源：\n  " + "\n  ".join(bad)


# ------------------------------------------------------ ③ 机制行为（语义契约）

def test_ordered_first_match_wins():
    """顺序即优先级：查询里同时命中多组时，**先声明的那组**胜出，与词在句中的位置无关。"""
    routes = (Route("a", ("x",)), Route("b", ("y",)))
    assert first_match("x y", routes, "d") == "a"
    assert first_match("y x", routes, "d") == "a"      # 位置无关
    assert first_match("only y", routes, "d") == "b"
    swapped = (Route("b", ("y",)), Route("a", ("x",)))
    assert first_match("x y", swapped, "d") == "b"     # 声明顺序一换，结果就换
    assert first_match("zzz", routes, "d") == "d"


def test_query_is_lowered_but_keywords_are_compared_verbatim():
    assert first_match("PLEASE JOIN NOW", (Route("j", ("join",)),), "d") == "j"
    # ★ 关键词原样比较 ⇒ 写成大写的关键词在小写化的查询里永不命中。
    #   这是收敛前就存在的现象（原实现同样 `query.lower()` 后比对），**原样保留**、
    #   没有顺手「修好」—— 改它会改变线上判定结果，不属本轮收敛范围。
    assert first_match("fba 费用", (Route("p", ("FBA",)),), "d") == "d"


def test_empty_keyword_is_skipped():
    """★ 顺手修掉的缺陷：空串是任何字符串的子串 ⇒ 不过滤会让该组永远命中，
    把后面所有组全遮住。收敛前 6 份实现都没有这个保护。"""
    assert first_match("anything at all", (Route("a", ("",)),), "d") == "d"
    # 空串与真关键词混在一组时，真关键词仍然生效
    assert first_match("kw", (Route("a", ("", "kw")),), "d") == "a"


def test_label_fn_runs_only_after_a_hit_and_gets_lowered_query():
    seen = []

    def fn(lowered):
        seen.append(lowered)
        return "composite"

    routes = (Route("placeholder", ("kw",), label_fn=fn),)
    assert first_match("NO MATCH HERE", routes, "d") == "d"
    assert seen == [], "未命中时不得调用 label_fn（否则会把未命中提前判成某个标签）"
    assert first_match("Has KW Inside", routes, "d") == "composite"
    assert seen == ["has kw inside"], "label_fn 应收到已小写归一的查询"


# ---------------------------------------------------------- ④ 门禁非空跑自检

def test_gate_is_not_vacuous():
    """★ 反向注入：两种形态的违规样本都必须被扫出来；干净样本不得误报。"""
    loop_form = (
        'def f(q):\n'
        '    for kw in A:\n'
        '        if kw in q:\n'
        '            return "a"\n'
        '    for kw in B:\n'
        '        if kw in q:\n'
        '            return "b"\n'
        '    for kw in C:\n'
        '        if kw in q:\n'
        '            return "c"\n'
    )
    any_form = (
        'def f(q):\n'
        '    if any(kw in q for kw in A):\n'
        '        return "x"\n'
        '    if any(kw in q for kw in B):\n'
        '        return "y" if q else "z"\n'
        '    if any(kw in q for kw in C):\n'
        '        return "w"\n'
    )
    assert route_branches(ast.parse(loop_form).body[0]) >= MIN_BRANCHES, "形态 A 漏报"
    assert route_branches(ast.parse(any_form).body[0]) >= MIN_BRANCHES, "形态 B 漏报"

    clean = ('def f(q):\n'
             '    hits = []\n'
             '    for kw in A:\n'
             '        if kw in q:\n'
             '            hits.append(kw)\n'
             '    return hits\n')
    assert route_branches(ast.parse(clean).body[0]) == 0, "把「收集」误判成「路由」"
