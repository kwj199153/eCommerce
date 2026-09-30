"""门禁：告警规则引用的指标必须真实存在且真的会被写入（P0-3）。

为什么用 pytest 驱动一个 scripts/ 脚本，而不是把断言抄进用例
-----------------------------------------------------------
判据必须只有**一份**实现（住在 `scripts/check_alert_rules.py`）。
抄进用例的话，两份会各自演进 —— 最后脚本守住了、测试守的却是旧形态，
而且两边都不报错。这里只做「跑脚本 + 判退出码」。

这道门禁守的是什么
------------------
两种「假告警「都不会报错、只会安静地不响：
  ① 规则引用了注册表里不存在的指标名；
  ② 指标名存在，但全仓没有任何 `.inc()/set()/observe()` 调用点
     （实测案例：`quota_rejections_total` 登记在 _REGISTRY 里，却 0 个调用点）。
"永不触发的告警"比"没有告警"更坏：它让人以为已经有监控了。
"""

from __future__ import annotations

import subprocess
import sys
from pathlib import Path

BACKEND = Path(__file__).resolve().parents[1]
SCRIPT = BACKEND / "scripts" / "check_alert_rules.py"


def _run(*args: str) -> subprocess.CompletedProcess:
    return subprocess.run(
        [sys.executable, "-X", "utf8", str(SCRIPT), *args],
        cwd=str(BACKEND),
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
    )


def test_alert_rules_reference_real_and_written_metrics():
    """正向：当前告警规则必须通过门禁。"""
    assert SCRIPT.is_file(), f"门禁脚本缺失：{SCRIPT}"
    r = _run()
    assert r.returncode == 0, f"告警门禁未通过（退出码 {r.returncode}）：\n{r.stdout}\n{r.stderr}"
    assert "RESULT: PASS" in r.stdout


def test_gate_rejects_rule_with_no_metrics_at_all(tmp_path):
    """
    反向（证明链路连通）：一个没有任何 expr 的规则文件必须以退出码 2 报错。

    ★ 为什么需要这条：上面那条只断言「退出码 == 0」。
      若脚本因任何原因**恒返回 0**（参数没接上、main 被吞掉），正向用例照样绿 ——
      那就是没有门禁。这条钉住「退出码会随输入变化」。
      选"空规则文件"而不是"写错指标名"作为注入，是因为它同时验证了
      「解析器失效时必须拒绝给结论，而不是报告一切正常」。
    """
    empty = tmp_path / "empty_rules.yml"
    empty.write_text("groups: []\n", encoding="utf-8")
    r = _run("--rules", str(empty))
    assert r.returncode == 2, f"期望退出码 2，实际 {r.returncode}：\n{r.stdout}\n{r.stderr}"
    assert "解析器失效" in r.stdout
