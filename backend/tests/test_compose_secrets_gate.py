"""门禁：docker-compose.yml 不得明文口令 / 数据库不得对公网暴露（P0-4）。

为什么用 pytest 驱动一个 scripts/ 脚本，而不是把断言抄进用例
-----------------------------------------------------------
门禁的真源必须是**一份**实现。抄一份到测试里，两份必然各自演进 ——
典型结局是「脚本守住了，测试守的还是旧形态」，两边都不报错。
所以这里只做两件事：跑脚本 + 断言退出码；**判据本身完全住在脚本里**
（同 `test_agent_session_memory.py` 对 `scripts/check_multi_turn_memory.py` 的做法）。

为什么门禁本身是必需的
----------------------
`127.0.0.1:5432:5432` 被改回 `5432:5432`、或插值被改回写死口令，
两件事都**不会让服务报错** —— 只会静默地把库暴露到公网 / 把口令写进 git。
静态门禁是唯一能在合并前拦住它们的关卡。
"""

from __future__ import annotations

import subprocess
import sys
from pathlib import Path

BACKEND = Path(__file__).resolve().parents[1]
SCRIPT = BACKEND / "scripts" / "check_compose_secrets.py"


def _run(*args: str) -> subprocess.CompletedProcess:
    return subprocess.run(
        [sys.executable, "-X", "utf8", str(SCRIPT), *args],
        cwd=str(BACKEND),
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
    )


def test_compose_has_no_plaintext_credentials_or_public_db_port():
    """正向：当前 compose 必须 5/5 通过门禁。"""
    assert SCRIPT.is_file(), f"门禁脚本缺失：{SCRIPT}"
    r = _run()
    assert r.returncode == 0, f"门禁未通过（退出码 {r.returncode}）：\n{r.stdout}\n{r.stderr}"
    assert "RESULT: PASS" in r.stdout


def test_gate_exit_code_is_not_constant(tmp_path):
    """
    反向（证明链路连通）：指定一个不存在的 compose ⇒ 必须以退出码 2 报错。

    ★ 为什么需要这一条：上面那条正向用例只断言「退出码 == 0」。
      若脚本因为任何原因**恒返回 0**（例如参数没接上、main 被吞掉），
      正向用例照样绿 —— 那就是没有门禁。这条钉住「退出码会随输入变化」。
    """
    missing = tmp_path / "definitely-not-here.yml"
    r = _run("--compose", str(missing))
    assert r.returncode == 2, f"期望退出码 2，实际 {r.returncode}：\n{r.stdout}\n{r.stderr}"
    assert "找不到" in r.stdout
