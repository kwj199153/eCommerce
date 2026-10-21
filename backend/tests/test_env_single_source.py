# -*- coding: utf-8 -*-
"""r388 · 环境单一真源门禁。

三条不变式，每条都对应一个**实测过的**坑：

I1  启动器里的 Python 解释器赋值必须指向 `backend/.venv`，且用 `%~dp0` 相对路径。
    历史：`start-backend.bat` / `start-celery.bat` 写死
    `D:\\work\\anaconda\\anaconda3\\envs\\reactAgents\\python.exe`（3.11.15），
    而 `backend/Dockerfile` = `python:3.12-slim`、CI `PYTHON_VERSION` = 3.12、
    `backend/.venv` = 3.12.14 ⇒ **本地起的服务与 CI/线上差一个 minor**。
    这就是「测试全绿、服务起不来 / 线上炸」的起点，而且不报错、只表现为
    「哪一边都不是我改的」。

I2  生成器与产物同源（防 drift）。
    历史：`start-celery.bat` 的 `LOG_SINK_ROLE`（P0-2 日志治理）是**手工**加的，
    `gen-start-celery-bat.py` 的 TEXT 里没有 ⇒ 任何人重跑一次生成器，
    P0-2 的修复连同 5 行「为什么 loguru 不是多进程安全」的实测记录一起被静默抹掉。

I3  仓内脚本不得借外部解释器。
    历史：`backend/scripts/probe_248_inject.py` 写死
    `C:\\Users\\...\\.workbuddy\\binaries\\python\\envs\\default\\Scripts\\python.exe`
    ⇒ 探针跑在哪个环境取决于「谁先装的」，与仓内依赖无关。

判据形态（本仓铁律）
====================
· 解释器赋值走**锚定正则** `^set "PY=`，不是「文件里含 anaconda」——
  注释里**必须**能解释「为什么不用 conda」，用字符串判据会把这条注释判成违规。
· 生成器文本走 **AST**（`TEXT = \"\"\"...\"\"\"` 的字符串常量），不是扫源码：
  源码里反斜杠是双写的，扫源码只会得到 `\\\\.venv`，与产物永远对不上。
"""

from __future__ import annotations

import ast
import re
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent.parent  # backend/tests/ -> repo root

#: 启动器里唯一允许的写法。`%~dp0` 末尾自带反斜杠，故其后是 `backend\`。
EXPECTED_PY_LINE = r'set "PY=%~dp0backend\.venv\Scripts\python.exe"'

#: 只有这两个启动器会 `set "PY=`；start-frontend.bat 用 node，不该出现。
EXPECTED_PY_OWNERS = {"start-backend.bat", "start-celery.bat"}

#: 仓根所有启动器的**精确**清单。新增 .bat/.ps1 时这条会红 —— 故意如此：
#: 新人加了启动器，必须顺手确认它用的是哪个解释器（否则永远没人看）。
EXPECTED_LAUNCHERS = {
    "start-backend.bat",
    "start-celery.bat",
    "start-frontend.bat",
    "ensure-docker-deps.ps1",
}

PY_ASSIGN_RE = re.compile(r'^[ \t]*set\s+"PY=([^"]*)"[ \t]*$', re.MULTILINE)


def _read(p: Path) -> str:
    # newline=None：把 CRLF 归一成 LF，判据对 EOL 免疫。
    with p.open("r", encoding="utf-8", newline=None) as fh:
        return fh.read()


def _launchers() -> list[Path]:
    files = [p for p in ROOT.glob("*.bat")] + [p for p in ROOT.glob("*.ps1")]
    return sorted(files, key=lambda p: p.name)


def _generator_text(py_path: Path) -> str:
    """取出生成器里 `TEXT = \"\"\"...\"\"\"` 的**字符串值**（单反斜杠形态）。"""
    tree = ast.parse(_read(py_path), filename=str(py_path))
    for node in ast.walk(tree):
        if isinstance(node, ast.Assign):
            names = [t.id for t in node.targets if isinstance(t, ast.Name)]
            if "TEXT" in names and isinstance(node.value, ast.Constant) \
                    and isinstance(node.value.value, str):
                return node.value.value
    raise AssertionError("%s 里找不到 TEXT = \"\"\"...\"\"\" 常量" % py_path.name)


# ---------------------------------------------------------------- I0 防空跑
def test_i0_launcher_inventory_is_exactly_known():
    """扫描面必须等于已知清单。

    为什么单列一条：`for p in glob("*.bat")` 一个都没匹配到时，I1 会**全绿**
    （没有文件 → 没有违规）。本仓铁律：只断言「> 0」防不住「少扫了」，
    必须与独立口径（精确集合）对齐。
    """
    actual = {p.name for p in _launchers()}
    assert actual == EXPECTED_LAUNCHERS, (
        "启动器清单变了：多了 %s，少了 %s —— 请确认新增的那个用的是哪个解释器，"
        "然后同步本清单" % (sorted(actual - EXPECTED_LAUNCHERS),
                            sorted(EXPECTED_LAUNCHERS - actual))
    )


# ------------------------------------------------------------------- I1
def test_i1_every_launcher_pins_backend_venv():
    """所有 `set "PY=..."` 必须精确等于 backend/.venv 的相对路径。"""
    owners: set[str] = set()
    for f in _launchers():
        for value in PY_ASSIGN_RE.findall(_read(f)):
            owners.add(f.name)
            assert value == r"%~dp0backend\.venv\Scripts\python.exe", (
                "%s 的 PY 指向 %r\n"
                "⇒ 必须写成 %r：写死盘符/conda 会让本地服务与 Dockerfile(3.12)/"
                "CI(3.12) 跑不同 minor，且换机即失效。"
                % (f.name, value, r"%~dp0backend\.venv\Scripts\python.exe")
            )
    assert owners == EXPECTED_PY_OWNERS, (
        "带 PY 赋值的启动器集合变了：%s（期望 %s）—— 少了说明判据没扫到，"
        "多了说明新启动器没走本门禁" % (sorted(owners), sorted(EXPECTED_PY_OWNERS))
    )


# ------------------------------------------------------------------- I2
def test_i2_generator_and_artifact_agree():
    """生成器的 TEXT 与产物 bat 的关键行必须**双向**一致。

    单向不够：只查「生成器有的 bat 也有」抓不到「bat 手工多了东西」，
    而 P0-2 那次事故正是后者（bat 多出 LOG_SINK_ROLE，生成器没有）。
    """
    gen = ROOT / "gen-start-celery-bat.py"
    bat = ROOT / "start-celery.bat"
    text = _generator_text(gen)

    def key_lines(s: str) -> list[str]:
        out = []
        for ln in s.splitlines():
            t = ln.strip()
            if t.startswith('set "PY=') or t.startswith("start ") or "LOG_SINK_ROLE" in t:
                out.append(t)
        return out

    gen_key = key_lines(text)
    bat_key = key_lines(_read(bat))
    assert gen_key, "生成器 TEXT 里一行关键行都没提取到 ⇒ 判据失效"

    # ① 生成器里唯一的 PY 行必须就是期望值（AST 取值是单反斜杠形态）
    py_lines = [l for l in gen_key if l.startswith('set "PY=')]
    assert py_lines == [EXPECTED_PY_LINE], (
        "生成器的 PY 行 = %r，期望 %r" % (py_lines, EXPECTED_PY_LINE))

    # ② 双向包含
    missing_in_bat = [l for l in gen_key if l not in bat_key]
    missing_in_gen = [l for l in bat_key if l not in gen_key]
    assert not missing_in_bat, (
        "生成器有、bat 没有 ⇒ 产物过期，请重跑 gen-start-celery-bat.py：\n  %s"
        % "\n  ".join(missing_in_bat))
    assert not missing_in_gen, (
        "bat 有、生成器没有 ⇒ **drift**，重跑生成器会静默抹掉这些行：\n  %s\n"
        "修法：把它们回写进 gen-start-celery-bat.py 的 TEXT，不要只改 bat。"
        % "\n  ".join(missing_in_gen))


def test_i2b_p0_2_log_sink_role_still_present():
    """P0-2 的 LOG_SINK_ROLE 必须在**两边**都在（显式钉住这条历史修复）。"""
    gen_text = _generator_text(ROOT / "gen-start-celery-bat.py")
    bat_text = _read(ROOT / "start-celery.bat")
    for role in ("worker", "beat"):
        needle = 'set LOG_SINK_ROLE=%s&&' % role
        assert needle in gen_text, "生成器丢了 LOG_SINK_ROLE=%s（P0-2 回归）" % role
        assert needle in bat_text, "bat 丢了 LOG_SINK_ROLE=%s（P0-2 回归）" % role


# ------------------------------------------------------------------- I3
def test_i3_repo_scripts_do_not_borrow_external_interpreter():
    """仓内脚本不得出现外部解释器的绝对路径（AST 取字符串常量，注释免疫）。"""
    banned = ("binaries\\python", "binaries/python", "anaconda3\\envs", "anaconda3/envs")
    offenders = []
    scripts = sorted((ROOT / "backend" / "scripts").glob("*.py"))
    assert len(scripts) >= 5, "backend/scripts 只扫到 %d 个 .py，判据可能没扫到" % len(scripts)
    for f in scripts:
        tree = ast.parse(_read(f), filename=str(f))
        for node in ast.walk(tree):
            if isinstance(node, ast.Constant) and isinstance(node.value, str):
                v = node.value
                if any(b in v for b in banned) and "python" in v.lower():
                    offenders.append((f.name, node.lineno, v[:60]))
    assert not offenders, (
        "这些脚本借了外部解释器（应指向 backend/.venv 或 sys.executable）：\n  %s"
        % "\n  ".join("%s:%d %r" % o for o in offenders))
