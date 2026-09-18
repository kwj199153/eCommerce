# -*- coding: utf-8 -*-
"""记忆体系门禁：把 `check_budget.py` 挂进 pytest。

为什么挂在 pytest 而不是 git hook：
    `.githooks/pre-commit` 有硬约束「只用 shell 内建、不调任何外部命令」
    （本机实测 hook 里 head / grep / cat 全 command not found），
    量文件字节数在纯 shell 里做不到。而全量 pytest 每轮都在跑，等于零额外成本。

★ 判据不在本文件重写：这里只 importlib 加载 `check_budget.py` 的 `check()`。
  「同一指标出现两份实现 ⇒ 至少一份永远测不到」是本项目铁律。

★ 已知边界：`.workbuddy/` 被 .gitignore 忽略（本机工具数据，不随仓库分发）
  ⇒ 在 CI / 全新 clone 上目录不存在，此时**跳过而不是失败** ——
  它依赖的是本机数据而非仓库内容。这属于「不需要 = 显式跳过」，
  而不是「漏配 = 起不来」（后者才应该硬拒绝启动）。

★ 它拦的是什么（第 111 轮的病）：
  MEMORY.md 是每轮都写的热区，注入上限是硬限（实测 ≈14700 B）。超限**没有报错**，
  只是尾部整段消失 —— 判据静默失效。所以需要一条能在 CI / 每轮回归里
  对这个维度**说不**的断言。
"""
import importlib.util
import pathlib
import re

import pytest

MEM_DIR = pathlib.Path(__file__).resolve().parents[2] / ".workbuddy" / "memory"
GATE = MEM_DIR / "check_budget.py"
ALARM = MEM_DIR / "check_inject_alarm.py"   # 宿主「超限」告警分诊（第 134 轮）

pytestmark = pytest.mark.skipif(
    not GATE.is_file(),
    reason="本机无 .workbuddy/memory（被 gitignore，CI 上必然如此）⇒ 本地门禁跳过",
)


def _load_gate():
    spec = importlib.util.spec_from_file_location("mem_check_budget", GATE)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def test_memory_budget_has_no_violation():
    """热区不超预算、判据行不超长、结构件齐全、留底存在、暂存不积压。"""
    mod = _load_gate()
    items, summary = mod.check(MEM_DIR)
    assert summary.get("exists") is True, "走到这里说明记忆目录应存在（不存在已被 skip）"
    fails = [(name, detail) for level, name, detail in items if level == mod.FAIL]
    assert not fails, "记忆预算违规：\n" + "\n".join("  - %s：%s" % f for f in fails)


def test_tier_files_are_present():
    """四层必须齐：热区 + 目录 + 暂存 + 冷区。

    少任何一层，机制就退化成「只有一个大文件」—— 也就是第 111 轮之前的病：
    热数据和冷数据共用同一条写路径、每次都得全量压缩。
    """
    for rel in ("MEMORY.md", "INDEX.md", "_pending/README.md", "DETAILS", "check_budget.py"):
        assert (MEM_DIR / rel).exists(), "缺分层件 %s" % rel
    assert list((MEM_DIR / "DETAILS").glob("*.md")), "DETAILS 下应有主题分片"


def test_index_and_shards_match_both_ways():
    """目录与分片双向对账。

    ★ 只查一个方向是不够的（这条本身就是被反向注入逼出来的）：
      - 分片没被 INDEX 收录 ⇒ **不可发现**（文件在，但没人会去读）
      - INDEX 指向不存在的分片 ⇒ **指向空气**（照着目录去 Read 会扑空）
      两个方向都不会报错，所以必须各有一条断言。
    """
    idx = (MEM_DIR / "INDEX.md").read_text(encoding="utf-8")
    names = sorted(p.name for p in (MEM_DIR / "DETAILS").glob("*.md"))
    assert names, "DETAILS 下应有主题分片"

    unindexed = [n for n in names if n not in idx]
    assert not unindexed, "INDEX.md 未收录这些分片（= 不可发现）：%s" % unindexed

    linked = set(re.findall(r"\(DETAILS/([^)]+\.md)\)", idx))
    dangling = sorted(n for n in linked if not (MEM_DIR / "DETAILS" / n).is_file())
    assert not dangling, "INDEX.md 指向不存在的分片（= 指向空气）：%s" % dangling


def test_inject_alarm_script_matches_hot_line():
    """★ 反回归：`check_inject_alarm.py` 的计数锚点必须仍能匹配热区那一行。

    第 134 轮实测的坑：热区措辞从「（已 N 次）」改成「（已 N 次；零动作，…）」后，
    脚本里的 `COUNT_RE = （已 (\d+) 次）` **静默失配** —— `--record` 会直接报
    「找不到计数点」而拒绝工作。改热区措辞的人不会想到去看脚本
    ⇒ 必须由门禁来说这一声「不」（同源于「注释承诺型假门禁」）。

    ★ 反向注入已验：把 COUNT_RE 改回带右括号的旧式 ⇒ 本条断言变红。
    """
    if not ALARM.is_file():
        pytest.skip("本机无 check_inject_alarm.py（.workbuddy 被 gitignore）")
    spec = importlib.util.spec_from_file_location("inject_alarm", ALARM)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)

    assert mod.hot_count() is not None, (
        "COUNT_RE 匹配不到热区的「（已 N 次」计数行 —— 热区措辞与脚本失配，"
        "`--record` 会拒绝工作"
    )
    assert isinstance(mod.CAP_BYTES, int) and mod.CAP_BYTES > 0, "CAP_BYTES 必须是正整数常量"

    verdict, hot, margin = mod.verdict()
    assert verdict in ("MISREPORT", "REAL"), "verdict 只能两值之一"
    assert margin == mod.CAP_BYTES - hot, "余量口径必须是 cap - 磁盘字节"
