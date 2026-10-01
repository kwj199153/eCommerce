"""`if __name__ == "__main__"` 必须是文件的**最后一个顶级语句**（第 200 轮）

==============================================================================
★ 这条钉的是一类缺陷：**模块级定义被入口语句截断**
==============================================================================
`python -m <pkg>.<mod>` 执行到 `if __name__ == "__main__": raise SystemExit(...)`
就退出了 —— 那一行**后面**的所有模块级定义（常量、数据表、模块级调用）
在这条路径下**根本不存在**。而 `import <pkg>.<mod>` 路径完全正常，
所以「跑测试全绿、跑 CLI 就炸」，且炸得很不像这一行的错。

==============================================================================
★★ 第 200 轮的**真现场**（`modules/skills/seed.py`）
==============================================================================
入口语句写在第 19 个顶级语句（共 26 个 ⇒ **后面还有 6 个**），而后面是：

    DEMO_SKILL_COUNT / RETIRED_DEMO_SKILLS /
    DEMO_SKILL_ANCHOR_TOOLS / DEMO_SKILL_BACKFILLED（回填调用）

后果（两个都装得像成功）：

  · `--ensure` → `NameError: name 'RETIRED_DEMO_SKILLS' is not defined`
    （★ 报错落在 `ensure_demo_skills()` **里面**，根因却在这一行的**位置**；
      第 195 轮加的退役清理因此在 CLI 路径上**从未生效**）；
  · `--resync` → 看不到锚工具表 ⇒ 回填过的 9 条技能同步不到库里，
    只报 5 条（那 5 条是手工写死在 `DEMO_SKILLS` 里的）——**看起来成功**。

★★ 归因为什么会错：`NameError` 指向的是**使用处**（另一个函数里），
   而缺陷在**语句顺序**。这类「报错点与根因不在同一处」的形态，
   只能靠一条**扫全仓的形态门禁**兜住 —— 名单式修补必然漏掉下一处。

==============================================================================
★ 判据为什么走 AST 而不是源码字符串
==============================================================================
字符串判据会被 docstring / 注释骗过（本文件自己的 docstring 就在讲这件事，
它一出现就足以让 `"__main__" in src` 恒真）。AST 看的是**语句顺序**这个事实。

★ 反向注入（必须能转红，已实测）：
  把 `modules/skills/seed.py` 末尾的入口语句剪回 `_main()` 定义之后
  ⇒ 本条转红，红在 `stmts_after` 那一行。
"""
import ast
import pathlib

BACKEND = pathlib.Path(__file__).resolve().parents[1]

#: 不扫的目录（第三方 / 缓存）——按目录名整段排除。
SKIP_DIRS = {
    ".venv", "venv", "__pycache__", "node_modules",
    ".mypy_cache", ".pytest_cache", ".ruff_cache",
}


def _is_main_guard(node: ast.stmt) -> bool:
    """该语句是不是 `if __name__ == "__main__":`。

    ★ 用 AST 比较而不是 `src.contains("__main__")`：后者连注释都会命中
      （本模块的 docstring 就含 `__main__` 字样 ⇒ 会让判据恒真）。
      同时接受两个操作数顺序（`"__main__" == __name__` 也合法）。
    """
    if not isinstance(node, ast.If):
        return False
    t = node.test
    if not isinstance(t, ast.Compare) or len(t.ops) != 1 or not isinstance(t.ops[0], ast.Eq):
        return False
    operands = (t.left, t.comparators[0])
    names = {getattr(x, "id", None) for x in operands}
    consts = {x.value for x in operands if isinstance(x, ast.Constant)}
    return "__name__" in names and "__main__" in consts


def _python_files():
    for p in sorted(BACKEND.rglob("*.py")):
        if any(part in SKIP_DIRS or part.startswith(".pytest-tmp") for part in p.parts):
            continue
        yield p


def test_main_guard_is_the_last_top_level_statement():
    """每一个入口语句都必须是该文件的最后一个顶级语句。"""
    offenders = []
    guards_seen = 0

    for path in _python_files():
        rel = path.relative_to(BACKEND).as_posix()
        try:
            tree = ast.parse(path.read_bytes().decode("utf-8"))
        except SyntaxError as e:                      # 语法错的文件不该被本用例掩盖
            offenders.append(f"{rel}: SyntaxError {e}")
            continue

        for i, node in enumerate(tree.body):
            if not _is_main_guard(node):
                continue
            guards_seen += 1
            after = len(tree.body) - 1 - i
            if after:
                tail = [type(tree.body[j]).__name__ for j in range(i + 1, len(tree.body))]
                offenders.append(
                    f"{rel}: 入口语句在第 {i} 个顶级语句（共 {len(tree.body)} 个），"
                    f"**后面还有 {after} 个** ⇒ 用 `python -m` 跑时它们不存在。"
                    f"（后续节点的 AST 类型：{tail}）"
                )

    # ★ 防「两边都是空」的假绿：本仓确实有多处入口语句（CLI 脚本），
    #   扫描若一个都没找到，说明 rglob / 排除规则写坏了 ⇒ 判据空跑。
    assert guards_seen > 0, (
        "全仓一个 `if __name__ == \"__main__\"` 都没扫到 —— "
        "本判据**空跑**（`BACKEND` 路径或 SKIP_DIRS 写错了？）"
    )

    assert not offenders, (
        "入口语句后面还有模块级定义 —— `python -m` 路径下那些定义**根本不存在**：\n  "
        + "\n  ".join(offenders)
        + "\n⇒ 把 `if __name__ == \"__main__\":` 整块剪到**文件末尾**。\n"
        "  这类缺陷的报错点通常**不在**这一行（落在某个引用了未定义常量的函数里，"
        "如 `NameError: name 'X' is not defined`），归因方向极易搞错。"
    )
