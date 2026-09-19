# -*- coding: utf-8 -*-
"""CI 门禁覆盖率门禁 —— 钉住「门禁文件存在 ≠ 门禁真的被执行」。

为什么需要它（第 161 轮，真实缺陷）：
    `.github/workflows/ci.yml` 的前端门禁步骤原来写的是

        for f in scripts/check-*.cjs; do ... done

    后缀被限定成 `.cjs`，于是 `frontend/scripts/` 下两道真实存在的 `.py` 门禁
    （`check-theme-boot.py` / `check-app-actions.py`）**从未在 CI 里执行过**。
    更隐蔽的一层：它们原名用**下划线**（`check_theme_boot.py`），连 `check-*`
    这个前缀都匹配不上 —— ⇒ 「存在却静默不执行」有两层原因（后缀 + 分隔符）。

    这与本项目已登记的另一条同源：第 155 轮 `check-plan-consumption.cjs`
    也曾经是 CI 里的死脚本（当时是「CI 绕过 build 脚本」）。
    ⇒ 同一类缺陷第二次出现，所以这次不靠人肉，改成**门禁自己证明覆盖率**。

本测试断言四件事：
  ① CI 的门禁 glob 必须能**逐个匹配到磁盘上每一个** `frontend/scripts/check-*` 文件
     （不限后缀）—— 谁被排除就红；
  ② 该 glob 的循环体必须**按后缀分派**（`.cjs` → node、`.py` → python），
     否则「匹配到」也执行不了；
  ③ 该循环必须带**覆盖率自证**（把 glob 命中数与该目录下 `check-*` 总数比对），
     否则下次换个写法又会静默漏掉；
  ④ `package.json` 与磁盘对账：`build` 里显式列出的门禁集合 == 全部 `.cjs` 门禁
     （防「加了门禁忘了挂」/「挂了不存在的门禁」）；每个 `check:*` 脚本指向的文件真实存在。

★ 为什么放在 `backend/tests/`：它是**配置的形态门禁**，跨前后端；
  放这里能借 backend job 每次都跑（不再新增一个 job）。
  同族可参照 `tests/test_memory_hygiene.py`（同样是「门禁的门禁」）。

★ 反向注入验证过（四条，见文件末尾 docstring）。

★ 解析纪律：**必须剥离 `#` 注释再断言**。本文件对应的 ci.yml 步骤里，
  解释「原来写成 `check-*.cjs` 是错的」的**注释**本身就含有那个旧串 ——
  不剥注释就会「判据被自己的注释绊倒」（本项目已登记的同族缺陷）。
"""
import fnmatch
import json
import re
import subprocess
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]
FRONTEND = ROOT / "frontend"
SCRIPTS = FRONTEND / "scripts"
CI_YML = ROOT / ".github" / "workflows" / "ci.yml"
PKG = FRONTEND / "package.json"
DOCKERFILE = FRONTEND / "Dockerfile"

GATE_PREFIX = "check-"
# ★ 必须**同时**接受 `check-` 与 `check_`：本轮的缺陷之一就是「下划线命名让 `check-*`
#   匹配不上」。若这里只收 `check-`，那么有人把一个门禁改回 `check_xxx.py` 时，
#   本门禁**看不见那个文件** ⇒ 覆盖率断言假绿（反向注入 RI-2 实测确认过这个漏洞）。
GATE_RE = re.compile(r"^check[-_]")


def _gate_files():
    """磁盘上全部门禁文件（**不限后缀、不限分隔符**）—— 排除说明性目录。"""
    if not SCRIPTS.is_dir():
        return []
    return sorted(p for p in SCRIPTS.iterdir()
                  if p.is_file() and GATE_RE.match(p.name))


def _gate_run_block() -> str:
    """取出 CI 里「前端门禁」那一步的 `run:` 脚本正文，**已剥掉 `#` 注释行**。"""
    text = CI_YML.read_text(encoding="utf-8")
    m = re.search(r"-\s*name:\s*前端门禁[^\n]*\n(.*?)(?=\n      - name:|\Z)",
                  text, re.S)
    if not m:
        pytest.fail("ci.yml 里找不到「前端门禁」这一步（步骤名被改动了？）")
    step = m.group(1)
    if "run:" not in step:
        pytest.fail("「前端门禁」步骤里没有 run:")
    body = step.split("run:", 1)[1]
    out = []
    for line in body.split("\n"):
        s = line.strip()
        if not s:
            continue
        if s.startswith("#"):
            continue                      # ★ 剥注释：判据不能被注释绊倒
        if s.endswith(":") or s in ("|", ">"):
            continue
        out.append(s)
    return "\n".join(out)


def test_gate_glob_covers_every_gate_file():
    """① 磁盘上每个门禁文件都必须被 CI 的 glob 匹配到（此处是本轮的核心修）

    ★ 提取 glob 必须锚定**循环头**（`for X in <glob>`）这一句法位置。
      反向注入 RI-1 实测过这个坑的代价：先在整段 run 脚本里搜 `scripts/check-\\S+`，
      结果把**覆盖率自证那行**的 `ls -1 scripts/check-*` 也当成 glob 收了进来 ——
      而 `scripts/check-*` 是宽匹配，恰好能匹配到 `.py` 门禁 ⇒
      「把 glob 改回 `.cjs` 后缀限定」这个注入**没能让判据变红**（假绿）。
      ⇒ 判据取值的「集合」必须只包含**该判据真正要判的那个东西**。
    """
    run = _gate_run_block()
    globs = re.findall(r"for\s+\w+\s+in\s+([^\s;]+)", run)
    assert globs, ("CI 门禁步骤里没有 `for X in <glob>` 形态的循环头：%r" % run)
    assert len(globs) == 1, (
        "门禁循环头应只有一条 glob，实测 %d 条 %s —— 多条会让覆盖率结论不可判"
        % (len(globs), globs))

    gates = _gate_files()
    assert len(gates) >= 2, "磁盘上找不到门禁文件，测试前提不成立（路径变了？）"

    unmatched = [p.name for p in gates
                 if not any(fnmatch.fnmatch("scripts/" + p.name, g) for g in globs)]
    assert not unmatched, (
        "以下门禁文件**从未被 CI 执行**（循环 glob 命中不了它们）：%s\n"
        "循环 glob = %s\n"
        "★ 这正是第 161 轮修掉的缺陷形态：存在但在 CI 里静默不执行。"
        % (unmatched, globs))


def test_gate_loop_dispatches_by_extension():
    """② 循环体必须按后缀分派：.cjs → node，.py → python，未知后缀直接失败"""
    run = _gate_run_block()
    assert re.search(r"\.cjs\)", run), "缺少 .cjs 分支"
    assert re.search(r"\bnode\b", run), "缺少 node 调用（.cjs 门禁跑不了）"
    assert re.search(r"\.py\)", run), "缺少 .py 分支"
    assert re.search(r"\bpython\b", run), "缺少 python 调用（.py 门禁跑不了）"
    assert re.search(r"\*\)", run) and "exit 1" in run, \
        "缺少「未知后缀 ⇒ 非零退出」兜底：新增门禁可能被静默跳过"


def test_gate_loop_self_asserts_coverage():
    """③ 循环必须自证覆盖率（命中数 vs 目录里 check-* 总数）——
    否则以后换成别的写法又会静默漏掉门禁（本条把「怎么修」也钉住）"""
    run = _gate_run_block()
    assert re.search(r"ls\s+-1\s+scripts/check-\*", run), \
        "缺少「目录里 check-* 总数」的现算（如 `ls -1 scripts/check-* | wc -l`）"
    assert re.search(r"-ne\s+\"?\$\{?total", run) and "exit 1" in run, \
        "缺少 total 与实际执行数的比对（有比对才会红，否则自证是摆设）"
    assert re.search(r"wc\s+-l", run), "缺少计数（wc -l）"


def test_package_json_build_lists_exactly_the_cjs_gates():
    """④a `build` 里显式列的门禁 == 磁盘上全部 .cjs 门禁（防漂移）"""
    obj = json.loads(PKG.read_text(encoding="utf-8"))
    build = obj["scripts"]["build"]
    listed = set(re.findall(r"scripts/(check-[\w.-]+)", build))
    on_disk = {p.name for p in _gate_files() if p.suffix == ".cjs"}
    assert listed == on_disk, (
        "package.json build 的门禁名单与磁盘不一致：\n"
        "  只在 build 里（挂了不存在/已改名的门禁）: %s\n"
        "  只在磁盘上（新增但忘了挂进 build）    : %s"
        % (sorted(listed - on_disk), sorted(on_disk - listed)))


def test_package_json_check_scripts_point_at_real_files():
    """④b 每个 `check:*` 脚本引用的文件必须真实存在（防「脚本指向空气」）"""
    obj = json.loads(PKG.read_text(encoding="utf-8"))
    bad = []
    for name, cmd in obj["scripts"].items():
        for rel in re.findall(r"(scripts/[\w.-]+)", cmd):
            if not (FRONTEND / rel).is_file():
                bad.append((name, rel))
    assert not bad, "以下 npm 脚本指向不存在的文件：%s" % bad


def test_py_gates_are_not_in_build_unless_docker_has_python():
    """④c 不变式：`build` 里若出现 `.py` 门禁，则 Dockerfile 必须装了 python。

    为什么单列一条：`frontend/Dockerfile` 构建阶段是 `node:22-alpine`（**无 python**），
    把 `.py` 门禁并进 `npm run build` 会让 `RUN npm run build` 失败、镜像构建挂掉。
    ⇒ 本断言把「当时为什么没有并进 build」变成一个**会自己检查前提**的结论：
      要么别并，要么并了就把 python 装进镜像 —— 不允许「并了但镜像没 python」的中间态。
    """
    obj = json.loads(PKG.read_text(encoding="utf-8"))
    build = obj["scripts"]["build"]
    py_in_build = re.findall(r"scripts/check-[\w.-]+\.py", build)
    if not py_in_build:
        pytest.skip("build 未包含 .py 门禁（当前设计如此，理由见 docstring）")
    df = DOCKERFILE.read_text(encoding="utf-8") if DOCKERFILE.is_file() else ""
    assert re.search(r"apk add[^\n]*python|setup-python|apt-get install[^\n]*python", df), (
        "`npm run build` 里含 .py 门禁（%s），但 frontend/Dockerfile 没装 python ⇒ "
        "镜像构建会失败" % py_in_build)


def test_py_gates_actually_pass():
    """⑤ 端到端真跑：两道 .py 门禁必须真的能跑通（退出码 0）。

    「门禁存在」与「门禁会跑」与「门禁跑得过」是三件事；前四条只覆盖前两件。
    """
    py = [p for p in _gate_files() if p.suffix == ".py"]
    if not py:
        pytest.skip("没有 .py 门禁（已改写成别的形态？）")
    for p in py:
        r = subprocess.run([sys.executable, "-X", "utf8", str(p)],
                           capture_output=True, text=True,
                           encoding="utf-8", errors="replace", cwd=str(FRONTEND))
        assert r.returncode == 0, (
            "%s 退出码 %s（应 0）\n--- 尾部输出 ---\n%s"
            % (p.name, r.returncode, (r.stdout or "")[-1500:]))


# ------------------------------------------------------------------
# 反向注入验证（第 161 轮实测，四条）
#   RI-1 ci.yml 的 glob 改回 `check-*.cjs`
#        ⇒ test_gate_glob_covers_every_gate_file 红（.py 门禁匹配不上）
#   RI-2 把某个 .py 门禁改名回下划线（`check_theme_boot.py`）
#        ⇒ 同上一条红（连 `check-*` 都匹配不上）
#   RI-3 删掉循环里的覆盖率自证
#        ⇒ test_gate_loop_self_asserts_coverage 红
#   RI-4 从 build 里删掉一道门禁
#        ⇒ test_package_json_build_lists_exactly_the_cjs_gates 红
# 全部逐字节还原后本文件仍绿。
# ------------------------------------------------------------------
