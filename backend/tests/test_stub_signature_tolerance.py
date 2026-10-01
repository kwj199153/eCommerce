# -*- coding: utf-8 -*-
r'''门禁：**测试桩的签名必须接得住生产代码的关键字调用**。

为什么需要它（第 238 轮 P2 的真实事故）：
  P2 把调用点从 `self._llm_with_tools()` 改成
  `self._llm_with_tools(model=self._first_round_model(...))`，
  而 tests 里有 5 处把该方法替换成**零参 lambda**：
      monkeypatch.setattr(agent, "_llm_with_tools", lambda: _MeterStubLLM())
  ⇒ `TypeError: <lambda>() got an unexpected keyword argument 'model'`
  ⇒ 7 条用例红。

  ★ 最难发现的地方在于：**「定向回归」永远扫不到**。
    只有 `pytest tests/` 全量才会同时撞上「改了调用点」与「桩没同步」。
    一个纯签名问题，被伪装成「一堆散落的、看名字毫无关联的失败」
    （test_base_agent_unified / test_memory_injection / test_skill_selection）。
    ⇒ 判据必须**钉在形态上**（AST 比签名），不能等人肉发现。

判据（动态名单，从**生产代码**导出 ⇒ 新增调用点自动登记，不依赖人肉维护名单）：
  1. 扫 `backend/` 下所有非测试 .py，收集被 `self._x(kw=...)` **关键字调用**的私有方法
     → `{方法名: {关键字名}}`；
  2. 扫 `tests/` 下所有 `setattr` / `monkeypatch.setattr` 形式的打桩，解析被替换对象的签名
     （`lambda` 或同文件 `def`）；
  3. 对「名字出现在第 1 步」的桩，要求其签名满足任一：
     · 有 `**kwargs`（推荐）；或
     · 显式声明了需要的每个关键字名。
  4. 另加两条**防门禁空转**的正向对照（本仓铁律：没有反例的断言 = 没有断言）。

反面样本（这些**不该**被判红）：
  · `patch.object(a, "_llm_with_tools")` —— 只有 2 个参数，拿到 MagicMock，天然容忍 kwargs；
  · `setattr(BaseAgent, "_build_chat_model", _build)` —— 该方法在生产里是**位置调用**，
    不在第 1 步的集合里。
'''

import ast
from pathlib import Path

BACKEND = Path(__file__).resolve().parents[1]
TESTS = Path(__file__).resolve().parent
SELF_NAME = 'test_stub_signature_tolerance.py'


def _read(path: Path) -> str:
    """二进制读 + utf-8 解码：禁 `read_text` 的 universal-newline 转译（本仓铁律）。"""
    return path.read_bytes().decode('utf-8')


def _iter_py(root: Path, skip_tests: bool):
    for p in sorted(root.rglob('*.py')):
        parts = p.parts
        if '__pycache__' in parts or {'.venv', 'venv', 'site-packages'} & set(parts) or any(
            part.startswith(".pytest-tmp") for part in parts
        ):
            continue
        if skip_tests and 'tests' in parts:
            continue
        yield p


def _kwarg_called_private_methods() -> dict:
    """`{私有方法名: {关键字名, ...}}` —— 生产代码里被 `self._x(kw=...)` 调用的那些。"""
    found: dict = {}
    for p in _iter_py(BACKEND, skip_tests=True):
        try:
            tree = ast.parse(_read(p))
        except SyntaxError:
            continue
        for node in ast.walk(tree):
            if not isinstance(node, ast.Call):
                continue
            f = node.func
            if not isinstance(f, ast.Attribute) or not f.attr.startswith('_'):
                continue
            if not (isinstance(f.value, ast.Name) and f.value.id == 'self'):
                continue
            kws = {k.arg for k in node.keywords if k.arg}
            if kws:
                found.setdefault(f.attr, set()).update(kws)
    return found


def _signature_of(node):
    """返回 `(容忍任意 kwargs?, 声明的参数名集合)`；不是可解析的函数 → None。"""
    if isinstance(node, ast.Lambda):
        a = node.args
    elif isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
        a = node.args
    else:
        return None
    names = {x.arg for x in a.args}
    names |= {x.arg for x in a.kwonlyargs}
    if a.vararg is not None:
        names.add(a.vararg.arg)
    if a.kwarg is not None:
        names.add(a.kwarg.arg)
    return (a.kwarg is not None, names)


def _collect_stubs() -> list:
    """`[(文件, 行号, 被替换的方法名, 容忍任意kwargs?, 参数名集合)]`。"""
    stubs = []
    for p in _iter_py(TESTS, skip_tests=False):
        if p.name == SELF_NAME:
            continue
        try:
            tree = ast.parse(_read(p))
        except SyntaxError:
            continue
        top_funcs = {
            n.name: n for n in tree.body
            if isinstance(n, (ast.FunctionDef, ast.AsyncFunctionDef))
        }
        for node in ast.walk(tree):
            if not isinstance(node, ast.Call) or len(node.args) < 3:
                continue
            f = node.func
            is_setattr = (
                (isinstance(f, ast.Name) and f.id == 'setattr')
                or (isinstance(f, ast.Attribute) and f.attr == 'setattr')
            )
            if not is_setattr:
                continue
            name_node = node.args[1]
            if not (isinstance(name_node, ast.Constant)
                    and isinstance(name_node.value, str)
                    and name_node.value.startswith('_')):
                continue
            val = node.args[2]
            sig = _signature_of(val)
            if sig is None and isinstance(val, ast.Name):
                fn = top_funcs.get(val.id)
                if fn is not None:
                    sig = _signature_of(fn)
            if sig is None:
                continue
            stubs.append((p, node.lineno, name_node.value, sig[0], sig[1]))
    return stubs


def test_every_stub_signature_tolerates_the_keyword_calls_it_replaces():
    called = _kwarg_called_private_methods()
    stubs = _collect_stubs()

    # 正向对照 ①：门禁本身不能空转
    assert called, (
        '没扫到任何 `self._x(kw=...)` 调用 —— 门禁失去覆盖对象（扫描路径写错了？）'
    )
    # 正向对照 ②：至少要真的扫到桩，否则下面的循环恒真
    assert stubs, '没扫到任何 setattr 打桩点 —— 门禁空转'

    bad = []
    checked = 0
    for path, line, name, tolerant, params in stubs:
        need = called.get(name)
        if not need:
            continue  # 该方法在生产里只被位置调用 ⇒ 无需容忍 kwargs
        checked += 1
        if tolerant or need <= params:
            continue
        bad.append(f'{path.name}:{line} `{name}` 的桩接不住关键字参数 '
                   f'{sorted(need)}（声明了 {sorted(params)}）')

    assert not bad, (
        '生产代码用关键字调用了这些方法，但测试桩没同步（会 TypeError）：\n  '
        + '\n  '.join(bad)
    )
    assert checked > 0, (
        '没有任何桩落在「被关键字调用的方法」上 —— 判据恒真'
        f'（已扫描 {len(stubs)} 个桩 / {len(called)} 个关键字调用点）'
    )


def test_the_gate_really_covers_the_p2_injection_point():
    """防「生产代码改回位置调用 ⇒ 门禁静默失效」——钉子钉在本次事故的那个点上。"""
    called = _kwarg_called_private_methods()
    assert '_llm_with_tools' in called, (
        'P2 的关键字调用点 `self._llm_with_tools(model=...)` 不见了 —— '
        '要么被改回位置调用，要么被搬走；两种情况都必须让门禁的覆盖对象失效可见'
    )
    assert 'model' in called['_llm_with_tools'], called['_llm_with_tools']
