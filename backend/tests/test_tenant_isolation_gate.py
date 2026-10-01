"""门禁：多租户归属校验（`scripts/check_tenant_isolation.py`）—— 把它接进 CI。

为什么这个文件必须存在（L3-17，第 353 轮）
------------------------------------------
这道门禁此前**不在任何自动入口**：

  · `tests/` 里对它的 3 处提及全是注释 / docstring / assert 样例字符串
    （`tests/test_import_boundaries.py` 把它当作"跨包 import 私有符号"的**反面教材路径**），
    **没有任何一处执行它**；
  · CI 也不跑它（backend job 走 pytest，直接跑脚本的只有 frontend glob
    与 assets job 的 `check-cd-assets.py`）。

后果不是"少跑一条"，而是**一条已经变红的门禁可以无限期红下去而无人知晓**
（本轮实测 1/2 通过）。本仓原则二：**门禁的价值不由「写了」决定**。

★ 与「门禁红不了」（L3-11）是两个方向的问题，别混：
  L3-11 = 有入口、但注入空源仍绿（没有牙齿）；
  L3-17 = 有牙齿、但红了没人看（没接上流程）。本文件治的是后者。

为什么用 pytest 驱动脚本，而不是把断言抄进用例
----------------------------------------------
门禁的真源必须是**一份**实现。抄一份进来，两份必然各自演进 ——
典型结局是「脚本守住了，测试守的还是旧形态」，两边都不报错。
所以这里只做三件事：**跑脚本 + 解析它自己的汇总行 + 断言退出码**；
判据本身完全住在脚本里（同 `test_compose_secrets_gate.py` 的做法）。

为什么两个模式都要跑
--------------------
脚本有两套用例：`AUTH_REQUIRED=true` 走 10 条（真实身份之间的越权拦截），
`AUTH_REQUIRED=false` 走 5 条（演示身份：演示店 200 / 真实店 403）。
本地 `.env` 是 `false` ⇒ 若只跑一次，**那 10 条生产用例永远不会被执行**。
两份都跑，且各自断言"跑满 N 条且全过"。
"""

from __future__ import annotations

import os
import re
import subprocess
import sys
from pathlib import Path

BACKEND = Path(__file__).resolve().parents[1]
SCRIPT = BACKEND / "scripts" / "check_tenant_isolation.py"

#: 脚本自己的汇总行（唯一权威口径 —— 不看退出码一个数，要看它跑了多少条）
_RESULT = re.compile(r"结果:\s*(\d+)/(\d+)\s*通过")
#: ★ 注意这两个正则里的 `^\s*`：明细行是**带缩进**的 `  [PASS] …`，
#:   写成 `startswith("PASS")` 会恒不匹配（本仓踩过的坑）。故用 `re.M` + `^\s*`。
_PASS_LINE = re.compile(r"^\s*\[PASS\]", re.M)
_FAIL_LINE = re.compile(r"^\s*\[FAIL\]", re.M)


def _run(**env: str) -> subprocess.CompletedProcess:
    """在当前解释器下跑门禁脚本；`env` 用于覆盖 `AUTH_REQUIRED` 一类的开关。

    ★ 显式传 `env=`（而不是 `os.environ` 的原地副本 + pop）：
      `.env` 里 AUTH_REQUIRED=false，但**环境变量优先级高于 .env**
      （pydantic-settings 的既定顺序）⇒ 这样才真的能切模式。
    """
    merged = dict(os.environ)
    merged.update(env)
    return subprocess.run(
        [sys.executable, "-X", "utf8", str(SCRIPT)],
        cwd=str(BACKEND),
        env=merged,
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
    )


def _summary(out: str, *, min_cases: int) -> tuple[int, int]:
    """解析汇总行并做"跑满了没有"的健全性检查。"""
    m = _RESULT.search(out)
    assert m, f"脚本没有输出 `结果: N/M 通过` 汇总行，无法对账：\n{out[-2000:]}"
    passed, total = int(m.group(1)), int(m.group(2))

    # ★ 健全性：总量必须达标。否则「删掉用例」会让门禁变成绿的空壳
    #   （这与"注入空源仍是绿"同源：判据的**分母**被动了，比判据写错更隐蔽）。
    assert total >= min_cases, f"用例总数只有 {total}，少于预期的 {min_cases}：\n{out}"
    return passed, total


def _assert_all_pass(r: subprocess.CompletedProcess, *, min_cases: int, mode: str) -> None:
    passed, total = _summary(r.stdout, min_cases=min_cases)
    assert r.returncode == 0, (
        f"[{mode}] 门禁未通过（退出码 {r.returncode}，{passed}/{total}）：\n{r.stdout}"
    )
    assert passed == total, f"[{mode}] 汇总行自相矛盾：{passed}/{total} 却退出码 0"
    assert len(_PASS_LINE.findall(r.stdout)) == total, (
        f"[{mode}] 明细 [PASS] 行数与汇总行不符 ⇒ 汇总行可能是手写的：\n{r.stdout}"
    )
    assert not _FAIL_LINE.search(r.stdout), f"[{mode}] 存在 [FAIL] 明细：\n{r.stdout}"


def test_gate_passes_in_auth_required_mode():
    """生产模式分支：真实身份之间的越权拦截，10 条必须全过。"""
    assert SCRIPT.is_file(), f"门禁脚本缺失：{SCRIPT}"
    _assert_all_pass(_run(AUTH_REQUIRED="true"), min_cases=10, mode="AUTH_REQUIRED=true")


def test_gate_passes_in_demo_mode():
    """
    演示模式分支：**演示身份只放行演示店铺**。

    ★ 这里钉住的是第 353 轮修掉的那个错误期望。修复前脚本断言
      「演示身份 + 真实店 ⇒ 200」，与 `core/tenant/middleware.py:256-262`
      （第 177 轮删掉「user is None ⇒ 直接放行」）直接矛盾。
      ⇒ 本用例同时钉住**两个方向**（只钉一个方向会漏掉真回归）：
          演示店 ⇒ 放行；真实店 ⇒ 403。
    """
    r = _run(AUTH_REQUIRED="false")
    _assert_all_pass(r, min_cases=5, mode="AUTH_REQUIRED=false")

    # 语义钉：修正后的那条期望必须**字面**是 403（防有人把它改回 200 而用例靠
    # 「反正当时库状态恰好让它过」蒙混 —— 那种绿是假绿）。
    line = next(
        (ln for ln in r.stdout.splitlines() if "演示身份 + 真实店铺" in ln),
        None,
    )
    assert line is not None, f"演示模式分支缺少「演示身份 + 真实店铺」这条用例：\n{r.stdout}"
    assert "期望 403" in line, f"该用例的期望值被改回非 403 ⇒ 第 177 轮的口径丢了：{line}"


def test_gate_exit_code_is_not_constant():
    """
    ★ 反向（证明链路连通，且**演示店缺失时是记红而不是崩**）：

    把 `DEMO_ACCOUNT_EMAIL` 置空（配置里判作「关闭演示身份」的降级开关）
    ⇒ `ensure_demo_store()` 造不出演示店 ⇒ 脚本必须**以退出码 1 结束**。

    ★ 为什么需要这一条：上面两条正向用例只断言「退出码 == 0」。
      若脚本因任何原因**恒返回 0**（例如 `main()` 的返回值被吞掉、
      或汇总行是手写的），正向用例照样绿 —— 那就是没有门禁。
      这一条钉住「退出码会随输入变化」。

    ★ 顺带钉住第二件事：这条路径以前会 `AttributeError` 崩（`store_demo.id`）。
      崩 = 无汇总行 = 包装解析不到 `结果:` 而报"无法对账"，**看起来像包装坏了**；
      而"静默少跑两条"更糟（`3/3 通过` 与 `5/5 通过` 一样漂亮）。
      ⇒ 现在它必须是**有汇总行的红**。
    """
    r = _run(AUTH_REQUIRED="false", DEMO_ACCOUNT_EMAIL="")
    assert r.returncode == 1, (
        f"演示账号被关闭后仍返回 0 ⇒ 退出码是常量，门禁无效：\n{r.stdout}\n{r.stderr}"
    )
    passed, total = _summary(r.stdout, min_cases=3)
    assert passed < total, f"有失败用例却没记红：{passed}/{total}"
    assert _FAIL_LINE.search(r.stdout), f"缺 [FAIL] 明细行：\n{r.stdout}"
