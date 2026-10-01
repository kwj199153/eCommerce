"""门禁：全仓 Python 源文件编译期**不得**产生 `SyntaxWarning`（L3-14）。

为什么值得单独钉一道
--------------------
`invalid escape sequence '\\d'` 这类警告**不影响运行** —— 代码照跑、测试照绿，
所以它只能靠「有人碰巧看了一眼 stderr」被发现。它的实际代价是**污染输出**：

  · `alembic heads` 每次都会多打一行 `SyntaxWarning`，
    于是「迁移链有没有异常」这件事被一句无关噪音稀释；
  · `pytest -W error` 一类 CI 步一旦打开，整个套件当场变红，
    而红的原因与业务无关，排查成本远高于修它（每个文件只要 1 个字符）。

★ 本仓既有判据：「声明承诺型假门禁 —— 注释/常量/已入库 ⇒ 逐个查**消费点**」。
  这条的反面就是本门禁：**不要把「运行时不报错」当成「源文件是干净的」**。

为什么判据是 `compile()` 而不是 grep `\\d`
------------------------------------------
grep 只能命中你**已经想到**的那几种转义（本轮就有 `\\``、`\\d`、`\\s` 三种）。
`compile()` 走的是 CPython 自己的词法分析器 ⇒ 判据天然覆盖**全部**未识别转义，
且不会把「合法转义」（`\\n`、`\\\\`）误报成问题。

★ 这也让本门禁**不需要维护一张转义表** —— 表一旦要靠人同步，就必然过期。
"""

from __future__ import annotations

import pathlib
import warnings

import pytest

BACKEND = pathlib.Path(__file__).resolve().parents[1]

#: 不进扫描的目录（第三方 / 缓存 / 生成物）
_SKIP_PARTS = {".venv", "venv", "__pycache__", "node_modules", ".mypy_cache", ".ruff_cache"}


def _iter_sources() -> list[pathlib.Path]:
    return sorted(
        p
        for p in BACKEND.rglob("*.py")
        if not (_SKIP_PARTS & set(p.parts)) and p.is_file()
    )


def _label(path: pathlib.Path) -> str:
    """展示用路径：在仓内给相对路径，仓外（如注入用的 tmp 文件）给文件名。

    ★ 不写成 `path.relative_to(BACKEND)`：反向注入用的是 `tmp_path`，
      那不在 BACKEND 之下 ⇒ 会抛 `ValueError: ... is not in the subpath of ...`。
      这条坑第一次就是这么踩到的 —— 门禁的**报错路径**也是被测代码的一部分。
    """
    try:
        return str(path.relative_to(BACKEND))
    except ValueError:
        return path.name


def _syntax_warnings(path: pathlib.Path) -> list[str]:
    """编译单个文件，返回其 `SyntaxWarning` 的可读描述（无则空列表）。"""
    with warnings.catch_warnings(record=True) as caught:
        warnings.simplefilter("always")
        try:
            compile(path.read_bytes(), str(path), "exec")
        except SyntaxError as exc:  # 真语法错误另有门禁管，这里不越权
            pytest.fail(f"{_label(path)} 存在语法错误：{exc}")
    return [
        f"{_label(path)}:{w.lineno}: {w.message}"
        for w in caught
        if issubclass(w.category, SyntaxWarning)
    ]


def test_no_syntax_warnings_across_backend():
    """
    正向：当前后端全部源文件编译零 `SyntaxWarning`。

    ★ 反向注入验证（本门禁已被证明有牙齿）：
      在任一 docstring 里写一句 `\\d`（不加 `r` 前缀）⇒ 本用例必须红。
      门禁的「红」只证明它读了内容，所以另有一条 `test_gate_detects_injected_warning`
      把这条注入**纳入常规执行**（不是一次性手工验证）。
    """
    sources = _iter_sources()
    assert len(sources) > 100, f"扫描面过窄（只找到 {len(sources)} 个文件），判据形同虚设"

    offenders: list[str] = []
    for p in sources:
        offenders.extend(_syntax_warnings(p))

    assert not offenders, (
        "以下源文件存在编译期 SyntaxWarning（多为 docstring 里未加 r 前缀的 "
        "正则/命令示例，修法是在该字符串前加 r）：\n  " + "\n  ".join(offenders)
    )


def test_gate_detects_injected_warning(tmp_path):
    """
    ★ 反向（证明判据有牙齿）：把「注入一处未识别转义」这件事**当场做一遍**。

    为什么要写成常规用例而不是一次性手工验证：
      本仓铁律「没被反向注入验证过的门禁 = 没有门禁」。手工验证只留痕在报告里，
      下一次有人重构本文件（例如把 compile 换成 grep、或把 filter 写错）时，
      报告里的那次验证**不会**重新执行 —— 门禁静默变成恒真。

    做法：在 tmp 目录造一个带 `\\d` 的文件，调用与正向用例**同一个**判定函数。
    """
    bad = tmp_path / "injected_bad_escape.py"
    bad.write_bytes(b'"""docstring with a bad escape: \\d{4}"""\n')

    found = _syntax_warnings(bad)
    assert any("invalid escape sequence" in f for f in found), (
        f"注入一处 `\\d` 后判定函数没报出来，说明判据失明（实际返回：{found}）"
    )

    # 反向对照：加上 r 前缀之后必须**不再**报警（否则门禁会误伤正常代码）
    good = tmp_path / "injected_good_raw.py"
    good.write_bytes(b'r"""docstring with a raw escape: \\d{4}"""\n')
    assert _syntax_warnings(good) == [], "加 r 前缀后仍报警 ⇒ 门禁会误伤正常写法"
