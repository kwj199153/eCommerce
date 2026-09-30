#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""门禁：告警规则引用的指标必须**真实存在**且**真的会被写入**（P0-3）。

它守两种「假告警」，两种都不会报错、只会安静地不响
----------------------------------------------------
  ① **名字写错**：规则引用了 `_REGISTRY` 里不存在的指标名。
     Prometheus 对这种规则不报错 —— 它只是永远得到空结果，于是永不触发。
     这一条只能靠「名字 ⊆ 注册表」的结构化比对发现。
  ② **指标没人写**：名字存在，但全仓没有任何 `.inc()/.set()/.observe()` 调用点。
     值恒为 0（或序列根本不存在）⇒ 基于它的阈值是死规则。
     ★ 前身实测踩到：`quota_rejections_total` 在 `_REGISTRY` 里有登记、
       `__init__` 里也导出了，但**全仓 0 个 `.inc()`**。若照着"指标列表"
       给它写规则，写出来的就是一条永远不会响的告警。

判据全部走 **AST**（读 Python 源码时不做文本包含判断）：
  · 指标名 ← 解析 `core/observability/metrics.py` 里
    `X = _Counter("name", ...)` 这种赋值的**第一个位置参数**
  · 调用点 ← 解析生产源码里 `X.inc(...)` / `X.set(...)` 这类 `Attribute` 调用

用法：python scripts/check_alert_rules.py [--rules PATH] [--quiet]
退出码：0 = 通过；1 = 有假告警；2 = 文件缺失/解析失败。
"""

from __future__ import annotations

import argparse
import ast
import re
import sys
from pathlib import Path

BACKEND = Path(__file__).resolve().parents[1]
REPO = BACKEND.parent
METRICS_PY = BACKEND / "core" / "observability" / "metrics.py"
RULES_DEFAULT = REPO / "observability" / "alert_rules.yml"

METRIC_CTORS = {"_Counter", "_Gauge", "_Histogram"}
WRITE_METHODS = {"inc", "set", "observe", "dec"}
#: Prometheus 自带、不属于本项目注册表的指标
BUILTIN_METRICS = {"up", "scrape_duration_seconds", "scrape_samples_scraped"}

#: PromQL 函数与关键字（不是指标名）。没列到的会以「未知标识符」被报出来，
#: 那是刻意的：宁可让人补一次白名单，也不要静默放过一个真指标名。
PROMQL_KEYWORDS = {
    "sum", "avg", "min", "max", "count", "stddev", "stdvar", "topk", "bottomk",
    "rate", "irate", "increase", "delta", "idelta", "deriv", "predict_linear",
    "histogram_quantile", "quantile", "clamp_min", "clamp_max", "clamp",
    "absent", "absent_over_time", "vector", "scalar", "time", "timestamp",
    "changes", "resets", "sort", "sort_desc", "label_replace", "label_join",
    "by", "without", "on", "ignoring", "group_left", "group_right",
    "offset", "bool", "and", "or", "unless",
}
#: 直方图在 /metrics 里导出的后缀
HIST_SUFFIXES = ("_bucket", "_sum", "_count")
#: 扫描生产代码的根（不含 tests/、scripts/：那里的引用不算"真的会被写入"）
SCAN_ROOTS = ("core", "modules", "ai_infra", "platforms")
SCAN_FILES = ("main.py", "worker.py", "beat.py")

EXIT_OK, EXIT_FAIL, EXIT_USAGE = 0, 1, 2


# ---------------------------------------------------------------------------
def registry_metrics() -> dict[str, str]:
    """从 metrics.py 解析出 {指标名: 常量名}（AST，不做字符串包含）。"""
    tree = ast.parse(METRICS_PY.read_text(encoding="utf-8"))
    out: dict[str, str] = {}
    for node in tree.body:
        if not isinstance(node, ast.Assign) or not isinstance(node.value, ast.Call):
            continue
        fn = node.value.func
        if not (isinstance(fn, ast.Name) and fn.id in METRIC_CTORS):
            continue
        if not node.value.args or not isinstance(node.value.args[0], ast.Constant):
            continue
        name = node.value.args[0].value
        const = node.targets[0]
        if isinstance(const, ast.Name) and isinstance(name, str):
            out[name] = const.id
    return out


def write_sites() -> dict[str, set[str]]:
    """扫描生产源码，返回 {常量名: {文件相对路径, ...}}，只认真正的属性调用。"""
    sites: dict[str, set[str]] = {}
    files: list[Path] = []
    for root in SCAN_ROOTS:
        d = BACKEND / root
        if d.is_dir():
            files.extend(p for p in d.rglob("*.py") if "__pycache__" not in p.parts)
    for fname in SCAN_FILES:
        p = BACKEND / fname
        if p.is_file():
            files.append(p)

    for path in files:
        try:
            tree = ast.parse(path.read_text(encoding="utf-8", errors="replace"))
        except SyntaxError:
            continue
        for node in ast.walk(tree):
            if (
                isinstance(node, ast.Call)
                and isinstance(node.func, ast.Attribute)
                and node.func.attr in WRITE_METHODS
                and isinstance(node.func.value, ast.Name)
            ):
                sites.setdefault(node.func.value.id, set()).add(
                    str(path.relative_to(REPO)).replace("\\", "/")
                )
    return sites


# ---------------------------------------------------------------------------
def extract_exprs(rules_text: str) -> list[tuple[int, str]]:
    """
    从 YAML 里取出所有 `expr:` 的正文（行号, 文本）。

    为什么不用 PyYAML：`backend/requirements.txt` **没有** pyyaml（实测），
    而本门禁必须在 CI 的依赖集合里跑得起来。这里只关心 `expr:`，
    格式可控（单行或 `|` block），自解析是唯一真源、不引入第二份实现。
    """
    lines = rules_text.splitlines()
    exprs: list[tuple[int, str]] = []
    i = 0
    pat = re.compile(r"^(\s*)expr:\s*(.*)$")
    while i < len(lines):
        m = pat.match(lines[i])
        if not m:
            i += 1
            continue
        indent, rest = len(m.group(1)), m.group(2).strip()
        start = i + 1
        if rest in ("|", ">", "|-", ">-", "|+", ">+"):
            body: list[str] = []
            j = i + 1
            while j < len(lines):
                ln = lines[j]
                if ln.strip() and (len(ln) - len(ln.lstrip())) <= indent:
                    break
                body.append(ln.strip())
                j += 1
            exprs.append((start, " ".join(body)))
            i = j
        else:
            exprs.append((start, rest.strip('"\'')))
            i += 1
    return exprs


def strip_labels_and_strings(expr: str) -> str:
    """
    剥掉一切不是「指标名」的东西，只留下候选标识符。

    ★ 必须逐类剥，否则会造出**假阳性**（实测踩过，一版就报了 9 条）：
      · `"..."`      —— 标签值（如 status=~"5.."）
      · `{...}`      —— 选择器里的标签名与值
      · `[5m]`/`[1h]`—— 范围选择器。不剥的话裸 `m` / `h` 会被当成指标名。
      · `by (le)`    —— 聚合分组标签。不剥的话 `le` 会被当成指标名。
    假阳性和假阴性一样有害：门禁天天红，最后所有人学会无视它。
    """
    expr = re.sub(r'"[^"]*"', " ", expr)                                 # 标签值
    expr = re.sub(r"\{[^}]*\}", " ", expr)                               # 选择器
    expr = re.sub(r"\[[^\]]*\]", " ", expr)                              # [5m] / [1h]
    expr = re.sub(
        r"\b(?:by|without|on|ignoring|group_left|group_right)\s*\([^)]*\)", " ", expr
    )                                                                    # 聚合分组
    return expr


def identifiers(expr: str) -> set[str]:
    return set(re.findall(r"[A-Za-z_:][A-Za-z0-9_:]*", strip_labels_and_strings(expr)))


def normalise(name: str, known: set[str]) -> str:
    """把直方图导出名（xxx_bucket/_sum/_count）折回基础指标名。"""
    if name in known:
        return name
    for suf in HIST_SUFFIXES:
        if name.endswith(suf) and name[: -len(suf)] in known:
            return name[: -len(suf)]
    return name


# ---------------------------------------------------------------------------
def main() -> int:
    ap = argparse.ArgumentParser(description="告警规则 ↔ 指标注册表 一致性门禁")
    ap.add_argument("--rules", default=str(RULES_DEFAULT))
    ap.add_argument("--quiet", action="store_true")
    args = ap.parse_args()

    rules_path = Path(args.rules)
    if not rules_path.is_file():
        print(f"[ERROR] 找不到规则文件：{rules_path}")
        return EXIT_USAGE
    if not METRICS_PY.is_file():
        print(f"[ERROR] 找不到指标注册表：{METRICS_PY}")
        return EXIT_USAGE

    registry = registry_metrics()
    known = set(registry) | BUILTIN_METRICS
    sites = write_sites()
    exprs = extract_exprs(rules_path.read_text(encoding="utf-8"))

    if not registry:
        print("[ERROR] 指标注册表解析结果为 0 —— 解析器失效，拒绝给出结论")
        return EXIT_USAGE
    if not exprs:
        print("[ERROR] 规则文件里没有解析到任何 expr —— 解析器失效，拒绝给出结论")
        return EXIT_USAGE

    if not args.quiet:
        print(f"规则文件  : {rules_path.relative_to(REPO) if rules_path.is_relative_to(REPO) else rules_path}")
        print(f"注册表指标: {len(registry)} 个 -> {', '.join(sorted(registry))}")
        print(f"解析到 expr: {len(exprs)} 条")
        print("-" * 72)

    problems: list[str] = []
    used: set[str] = set()

    # ---- ① 名字必须存在于注册表（或内建白名单）---------------------------
    for lineno, expr in exprs:
        for ident in identifiers(expr):
            if ident in PROMQL_KEYWORDS:
                continue
            base = normalise(ident, known)
            if base not in known:
                problems.append(
                    f"规则第 {lineno} 行引用了不存在的指标 `{ident}`"
                    f" —— Prometheus 不会报错，它只是永远不触发"
                )
            else:
                used.add(base)

    # ---- ② 被引用的自定义指标必须有写入点 --------------------------------
    for name in sorted(used):
        if name in BUILTIN_METRICS:
            continue
        const = registry.get(name)
        where = sites.get(const or "", set())
        if not where:
            problems.append(
                f"指标 `{name}`（常量 {const}）被规则引用，但全仓**没有任何 "
                f"inc()/set()/observe() 调用点** ⇒ 值恒为 0 或序列不存在，"
                f"这条告警永远不会响"
            )

    if problems:
        print(f"RESULT: FAIL（{len(problems)} 条假告警风险）")
        for p in problems:
            print(f"  ✗ {p}")
        return EXIT_FAIL

    print(f"RESULT: PASS（{len(exprs)} 条规则引用的 {len(used)} 个指标全部真实且有人写入）")
    return EXIT_OK


if __name__ == "__main__":
    sys.exit(main())
