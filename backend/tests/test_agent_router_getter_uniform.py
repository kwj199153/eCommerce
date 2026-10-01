# -*- coding: utf-8 -*-
"""7 个 Agent 的 `_get_router` 必须**逐字相同**（docstring 除外）—— 第 356 轮。

━━━ 为什么需要（以及为什么不是「收进基类」）━━━
`_get_router` 在 7 个 Agent 里各写一份，**函数体逐字相同**：

    if self._router is None:
        self._router = self._build_router()
    return self._router

只有 docstring 不同（括注的回退目标确实不一样，那是对的）。

表面上「逐字相同 ×7」就是该收口的信号，但本仓**已经论证过反方** ——
`modules/product_research/agent_routing.py` 的模块 docstring 写着：

    与第一刀（mixin）、第二刀（显式传参）同一条方法论：**藏进基类只会让耦合从
    「可以数的参数」变成「看不见的继承链」**，门禁再也数不出这个类实际依赖
    什么 —— 那是自欺。

而且 `_get_router` **持有** `self._router` 懒加载缓存（实例状态），
「哪个 Agent 依赖哪个注册表」正是通过这份显式代码可数的。

⇒ 本仓的选择：**保留 7 份，但钉住它们不许漂移**。这就是本文件。
   「防漂移」与「可数性」在这个符号上不可兼得，本仓选了后者，用门禁补前者。

━━━ 判据（六条）━━━
  W1 **宿主清单双向对账**：磁盘扫出的宿主集合 == 冻结表（分开报「新增」与「消失」）
  W2 **表自证**：冻结表非空，且每个条目在磁盘上都能解析出一个 `_get_router`
     （路径写错 / 文件改名 / 判据退化 ⇒ 红）
  W3 **逐字相同**：7 份「剥 docstring 后」的正文只允许**一种**（漂移 ⇒ 红）
  W4 **归一化非空转**：三小条自证 —— ①正文非平凡（含 `self._router` /
     `self._build_router` / `return self._router`）②变异体必须产出**不同**结果
     ③docstring 确实被剥掉（合成样本里不得残留 docstring 文本）
     ★ 少了 W4，一个「把一切都剥成空串」的 bug 会让 W3 **恒真**（假绿）。
  W5 **签名自证**：7 份都必须是无装饰器的实例方法，且形参只有 `self`
     （防止有人把它改成 `@staticmethod` —— 那会让 `self._router` 直接 NameError）
  W6 **回退目标只写在 docstring 里**（提示级，只看形态）：正文相同但 docstring
     不同 ⇒ 说明「差异被收敛在文档层」，这是**有意**的形态。

★ 反向注入见 `.workbuddy/probes/r356/inject_router_uniform.py`（四组 + 反例）。

━━━ 扫描面（显式，否则读数不可比）━━━
只扫 `backend/modules/**` 与 `backend/ai_infra/**`（Agent 就住在这两处；
`tests/` `scripts/` 里出现的 `_get_router` 是夹具/探针，不是产品）。
本文件**不**以 backend 根 `rglob("*.py")` 扫描 ⇒ 不触发
`test_ci_gate_coverage.py` 对 `.venv` / `.pytest-tmp*` 排除的要求；那个责任
在上一行限定的两个子目录里天然成立。
"""

import ast
from pathlib import Path

BACKEND = Path(__file__).resolve().parents[1]

#: 扫描面（Agent 住的两个包；不扫 tests/ 与 scripts/）。
SCAN_ROOTS = (BACKEND / "modules", BACKEND / "ai_infra")

#: 目标符号名。
GETTER = "_get_router"

#: 冻结宿主表 —— 7 个 Agent，每个都**显式持有**自己的 `self._router` 实例状态。
#: ★ 这份清单**不是**「旧形态」：它是「设计上每个 Agent 各持实例状态」的当前名册。
#:   新增 Agent 时请来登记（W1 会红并提示你）；若打算改设计（收进基类），
#:   先看本文件顶部引用的 `agent_routing.py` 那段论证。
FROZEN_HOSTS = {
    "modules/ad_analysis/agent_ad.py",
    "modules/aigc_media/agent_aigc.py",
    "modules/competitor_intel/agent_competitor.py",
    "modules/customer_service/agent_cs/core.py",
    "modules/listing_generator/agent_listing.py",
    "modules/product_research/agent_product_research.py",
    "modules/review_analyst/agent.py",
}

#: 正文里必须出现的三个要素（W4①：「非平凡」的可观测定义）。
MUST_CONTAIN = ("if self._router is None", "self._build_router()", "return self._router")


def _fn_node(tree, name: str):
    for n in ast.walk(tree):
        if isinstance(n, (ast.FunctionDef, ast.AsyncFunctionDef)) and n.name == name:
            return n
    return None


def _norm_from_source(src: str, name: str = GETTER) -> str:
    """剥掉 docstring 后，把函数**正文**归一化成**可重新解析**的文本。

    · 从 `node.body[0].lineno` 起算（**不含 `def` 行**）：签名由 W5 单独判；
    · 剥掉主体 docstring（多行也剥）；
    · 删**公共前导缩进**、去首尾空行，但**保留相对缩进** —— 归一化结果因此仍是
      一段合法语句序列，W4 才能把它嵌回合成方法里做**往返自证**；
      ★ 这也是「逐字」的一部分：把某个嵌套行提出 `if` 之外，必须能被发现。
    · 用 `splitlines()` 而不是 `split("\\n")`：前者天然吃掉 CRLF 的 `\\r`
      （本仓同一文件树里 CRLF / LF 混存，见 `.gitattributes` 与
      `probes/r356/out-eol-truth.txt`）。
    """
    tree = ast.parse(src)
    node = _fn_node(tree, name)
    if node is None:
        raise LookupError(f"{name} 不在该源码里")
    if not node.body:
        return ""
    first = node.body[0]
    start = first.lineno
    lines = src.splitlines()[start - 1: node.end_lineno]
    drop = set()
    if (isinstance(first, ast.Expr) and isinstance(first.value, ast.Constant)
            and isinstance(first.value.value, str)):
        drop = set(range(first.lineno - start, first.end_lineno - start + 1))
    kept = [ln.rstrip() for i, ln in enumerate(lines) if i not in drop]
    indents = [len(ln) - len(ln.lstrip()) for ln in kept if ln.strip()]
    base = min(indents) if indents else 0
    normed = [ln[base:] if ln.strip() else "" for ln in kept]
    while normed and not normed[0].strip():
        normed.pop(0)
    while normed and not normed[-1].strip():
        normed.pop()
    return "\n".join(normed)


def _indent(text: str, pad: str = "        ") -> str:
    """把扁平正文缩进成方法体（供 W4 造合成样本）。"""
    return "\n".join((pad + ln) if ln else ln for ln in text.splitlines())


#: W4 用的合成模块：哨兵 docstring + 占位正文（`{body}` 会被缩进后填入）。
_SYNTHETIC = (
    "class _Synthetic:\n"
    "    def _get_router(self):\n"
    '        """哨兵 DOCSTRING_SENTINEL"""\n'
    "{body}\n"
)


def _scan():
    """扫出所有宿主：{相对路径: 源码文本}。"""
    out = {}
    for root in SCAN_ROOTS:
        for p in sorted(root.rglob("*.py")):
            if "__pycache__" in p.parts:
                continue
            src = p.read_bytes().decode("utf-8", "replace")
            if GETTER not in src:      # 纯优化；判定走下面的 AST
                continue
            if _fn_node(ast.parse(src), GETTER) is not None:
                out[p.relative_to(BACKEND).as_posix()] = src
    return out


# ============================================================
# W2 表自证
# ============================================================

def test_frozen_table_is_nonempty_and_every_entry_is_really_there():
    """① 防空转：表非空；② 每个冻结路径都能解析出一个 `_get_router`。

    ★ 这条是 W1 的**前提**：若「解析 `_get_router`」的判据本身退化了（比如
      `_fn_node` 写坏），W1 会因为「两边都空」而恒真。这里把前提钉住。
    """
    assert FROZEN_HOSTS, "冻结表是空的 —— 判据恒真"
    missing, empty = [], []
    for rel in sorted(FROZEN_HOSTS):
        p = BACKEND / rel
        if not p.is_file():
            missing.append(rel)
            continue
        if _fn_node(ast.parse(p.read_bytes().decode("utf-8", "replace")), GETTER) is None:
            empty.append(rel)
    assert not missing, f"冻结表里的文件在磁盘上不存在（改名了？）：{missing}"
    assert not empty, f"冻结表里的文件里解析不出 `{GETTER}`：{empty}"


# ============================================================
# W1 宿主清单双向对账（两类失败分开报）
# ============================================================

def test_no_new_get_router_hosts():
    """磁盘上出现了**表外**的 `_get_router` ⇒ 红（引导式：来本文件登记）。

    ★ 为什么新增也要红、而不是「自动纳入比较」：新 Agent 完全可能写一个
      **语义不同**的 `_get_router`（比如不做懒加载）。自动纳入就永远发现不了
      —— 那正是漂移的入口。
    """
    added = sorted(set(_scan()) - FROZEN_HOSTS)
    assert not added, (
        f"磁盘上多出 {len(added)} 个 `{GETTER}` 宿主（不在冻结表里）：{added}\n"
        "⇒ 请确认它的正文与其余 7 份**逐字相同**，再把它加进本文件的 "
        "`FROZEN_HOSTS`；若它有意不同，请先回答「为什么这个 Agent 的懒加载"
        "语义与别人不一样」——那是一个设计决定，不是随手一笔。"
    )


def test_no_vanished_get_router_hosts():
    """冻结表里某项在磁盘上消失了 ⇒ 红（引导式：从表里删掉并同步注释）。"""
    gone = sorted(FROZEN_HOSTS - set(_scan()))
    assert not gone, (
        f"冻结表里有 {len(gone)} 个 `{GETTER}` 宿主在磁盘上扫不到了：{gone}\n"
        "⇒ 若是**删除**：请从 `FROZEN_HOSTS` 删掉它们并同步本文件注释；\n"
        "   若是**改名/搬家**：改回表里的路径，或按新路径更新本表。"
    )


# ============================================================
# W3 逐字相同（docstring 除外）
# ============================================================

def test_all_bodies_are_word_for_word_identical():
    """★ 核心判据：7 份「剥 docstring 后的正文」只允许**一种**形态。

    打红它：任一 Agent 的 `_get_router` 被改动一个字符（比如改成
    `if not self._router:`，或漏掉 `return`）。★ 那条「漏 `return`」的形态
    （`def` 紧贴上一行、连空行都没有）正是本仓登记过的指纹。
    """
    hosts = _scan()
    normed = {rel: _norm_from_source(src) for rel, src in sorted(hosts.items())}
    variants = {}
    for rel, body in normed.items():
        variants.setdefault(body, []).append(rel)
    assert len(variants) == 1, (
        f"`{GETTER}` 的正文出现 {len(variants)} 种形态（应恰好 1 种）：\n"
        + "\n".join(
            f"  --- 形态 {i}（{len(rels)} 份：{rels}）---\n{body}"
            for i, (body, rels) in enumerate(variants.items(), 1)
        )
        + "\n⇒ 这 7 份是**有意**各写一份（见本文件顶部引用的 agent_routing 论证），"
          "但必须**逐字相同**。"
    )


# ============================================================
# W4 归一化非空转（W3 的前提自证）
# ============================================================

def test_normalizer_is_not_vacuous():
    """★ 三小条自证：没有它们，W3 可能因为「一切都剥成空串」而**恒真**。"""
    hosts = _scan()
    rel, src = next(iter(sorted(hosts.items())))
    canonical = _norm_from_source(src)

    # ① 正文非平凡：三个要素都在（归一化不能把它剥没了）
    for needle in MUST_CONTAIN:
        assert needle in canonical, (
            f"[{rel}] 归一化后的正文缺少 `{needle}` ⇒ 归一化剥多了：\n{canonical}"
        )

    # ② 往返自证 + docstring 剥除自证：把正文缩进回一个合成方法里，
    #    归一化结果必须**逐字还原**成 canonical（哨兵 docstring 不得残留）
    probe = _SYNTHETIC.format(body=_indent(canonical))
    assert "DOCSTRING_SENTINEL" in probe, "合成样本构造失败（哨兵串丢了）"
    got = _norm_from_source(probe)
    assert got == canonical, (
        "合成样本的归一化结果与 canonical 不一致 —— 要么 docstring 没剥干净，"
        "要么归一化对缩进/空行不稳：\n--- 期望 ---\n%s\n--- 实测 ---\n%s"
        % (canonical, got)
    )
    assert "DOCSTRING_SENTINEL" not in got, (
        "docstring 没有被剥掉 ⇒ W3 会因为「docstring 不同」而假红"
    )

    # ③ 变异自证：逐条扰动**必须**让归一化结果改变（否则 W3 对该变异失明）
    mutations = {
        "换构建器": canonical.replace("self._build_router()", "self._other_router()"),
        "漏 return": canonical.replace("return self._router", "pass"),
        "真值判断": canonical.replace("if self._router is None:", "if not self._router:"),
    }
    blind = []
    for label, mutated in mutations.items():
        if mutated == canonical:
            blind.append(f"{label}（变异体与规范体相同 ⇒ 该变异没生效）")
            continue
        if _norm_from_source(_SYNTHETIC.format(body=_indent(mutated))) == canonical:
            blind.append(f"{label}（归一化对它不敏感）")
    assert not blind, (
        "以下变异**没有**被归一化反映出来 ⇒ W3 对它们失明（假绿）：" + "；".join(blind)
    )


# ============================================================
# W5 签名自证
# ============================================================

def test_signature_is_instance_method_with_self_only():
    """7 份都必须是无装饰器的实例方法，形参恰好 `self`。

    ★ 打红它：把它改成 `@staticmethod` / `@classmethod`（`self._router` 会直接
      炸在运行期），或加/改形参。这类改动**静态判据以外的门禁都看不见**。
    """
    bad = []
    for rel, src in sorted(_scan().items()):
        node = _fn_node(ast.parse(src), GETTER)
        args = [a.arg for a in node.args.args]
        if node.decorator_list or args != ["self"] or node.args.kwonlyargs \
                or node.args.vararg or node.args.kwarg or node.args.defaults:
            bad.append(f"{rel}: decorators={len(node.decorator_list)} args={args}")
    assert not bad, (
        "`%s` 必须是**实例方法**且形参只有 `self`（它要读写 `self._router`）：\n  %s"
        % (GETTER, "\n  ".join(bad))
    )


# ============================================================
# W6 差异只在 docstring 层（提示级：形态判据）
# ============================================================

def test_each_host_has_a_docstring_and_a_docstring_that_is_actually_dropped():
    """每份都得有 docstring，且它**确实**是 W3 里被剥掉的那部分。

    ★ 为什么单列：W3 是「剥掉 docstring 后相同」。若某一份干脆**没有**
      docstring，`_norm_from_source` 会退化成「整段正文」—— 仍然可能通过
      W3，但那说明「回退目标（关键词路由 / 关键词表 / 直连引导）」这条信息
      丢了。所以把「有 docstring」单独钉住。
    """
    hosts = _scan()
    no_doc = []
    for rel, src in sorted(hosts.items()):
        node = _fn_node(ast.parse(src), GETTER)
        first = node.body[0] if node.body else None
        if not (isinstance(first, ast.Expr) and isinstance(first.value, ast.Constant)
                and isinstance(first.value.value, str)):
            no_doc.append(rel)
            continue
        assert first.value.value.strip(), f"{rel}: docstring 是空的"
    assert not no_doc, (
        f"这些宿主的 `{GETTER}` 没有 docstring（回退目标就丢了）：{no_doc}"
    )
