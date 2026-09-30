# -*- coding: utf-8 -*-
"""第 250 轮 · 反向注入台架：证明 `tests/test_review_clarification_answer.py` 会转红。

本仓五条纪律（逐条落实在代码里）：
 ① **pristine 基线落盘** + sha256（`_snapshot()`；已有基线时**先还原再采**）；
 ② 每条注入**从原件现算副本**，绝不链式叠加（每轮先 `_restore()` 再 `_apply()`）；
 ③ 声明 `expect`，并断言「实测红集 == 声明红集」，且**总数要相等**（防空跑混过）；
 ④ 「锚点命中数 ≠ 1」**单独报** —— 「注入本身失败」与「注入没抓到」是两件事；
 ⑤ 还原用**全等副本** + 校验 sha256（`_restore()` + 终态复核 + `try/finally`）。

为什么是「改真文件 → 跑 → 还原」而不是「拷贝整棵 backend 到临时目录」：
  backend 下有上千个文件与本地 `.env`；拷贝会改变相对路径解析（`.env` 按 CWD
  找），把「环境没配好」误判成「注入没抓到」。

用法：
    python scripts/probe_250_clarification_answer.py            # 跑全套（8 条注入）
    python scripts/probe_250_clarification_answer.py --refresh   # 重新采基线（源改动后用）
"""
from __future__ import annotations

import hashlib
import os
import subprocess
import sys
import xml.etree.ElementTree as ET

PY = sys.executable
ROOT = "D:/ai/eCommerce"
BACKEND = os.path.join(ROOT, "backend")
TMP = os.path.join(ROOT, ".workbuddy/tmp/probe_250")
GATE_REL = "tests/test_review_clarification_answer.py"

FILES = {
    "base_agent": "ai_infra/base_agent.py",
    "review": "modules/review_analyst/agent.py",
}

PRISTINE: dict = {}
ORIG_EOL: dict = {}


def _p(key: str) -> str:
    return os.path.join(BACKEND, FILES[key])


def _read_raw(key: str) -> bytes:
    with open(_p(key), "rb") as f:
        return f.read()


def _sha(b: bytes) -> str:
    return hashlib.sha256(b).hexdigest()


def _snapshot(refresh: bool = False) -> None:
    """① 基线落盘；⑤ 已有基线时先还原。

    ★ 为什么「已有基线 ⇒ 先还原再采」：若上一轮崩在还原之前，磁盘上留的是**注入态**；
      此时重新采基线等于把缺陷当成正常 —— 后面每条注入都以它为起点，读数全废
      （本仓第 236 轮的教训：「备份只有在源还在时才是备份」）。
      要重新采必须显式 `--refresh`。
    """
    os.makedirs(TMP, exist_ok=True)
    for key in FILES:
        pri_path = os.path.join(TMP, key + ".pristine.py")
        if os.path.exists(pri_path) and not refresh:
            with open(pri_path, "rb") as f:
                raw = f.read()
            with open(_p(key), "wb") as f:
                f.write(raw)
        else:
            raw = _read_raw(key)
            with open(pri_path, "wb") as f:
                f.write(raw)
        PRISTINE[key] = raw
        ORIG_EOL[key] = "\r\n" in raw.decode("utf-8")


def _restore() -> None:
    for key in FILES:
        with open(_p(key), "wb") as f:
            f.write(PRISTINE[key])


def _apply(key: str, old: str, new: str):
    """从**原件**现算副本并写盘。返回 (是否成功, 说明)。"""
    src = PRISTINE[key].decode("utf-8")
    crlf = ORIG_EOL[key]
    norm = src.replace("\r\n", "\n")
    hits = norm.count(old)
    if hits != 1:
        return False, f"锚点命中 {hits} 次（要求 1）"            # ④ 单独报
    norm = norm.replace(old, new)
    out = norm.replace("\n", "\r\n") if crlf else norm
    with open(_p(key), "wb") as f:
        f.write(out.encode("utf-8"))
    return True, f"锚点命中 1 次；{len(src.encode())} -> {len(out.encode())} B"


def _run_gate(tag: str):
    """跑门禁，从 junitxml 取**失败/错误**的用例名。"""
    xp = os.path.join(TMP, f"{tag}.xml")
    bt = os.path.join(TMP, f"bt_{tag}")
    if os.path.exists(xp):
        os.remove(xp)
    proc = subprocess.run(
        [PY, "-m", "pytest", GATE_REL, "--tb=no", "-q",
         f"--junitxml={xp}", f"--basetemp={bt}"],
        cwd=BACKEND, capture_output=True, text=True,
        encoding="utf-8", errors="replace", timeout=600,
    )
    if not os.path.exists(xp):
        return None, f"junitxml 未落盘（rc={proc.returncode}）：{proc.stdout[-400:]}{proc.stderr[-400:]}"
    reds, total = set(), 0
    for tc in ET.parse(xp).iter("testcase"):
        total += 1
        if [c for c in tc if c.tag in ("failure", "error")]:
            reds.add(tc.get("name"))
    return reds, f"{total - len(reds)}/{total} 通过（rc={proc.returncode}）"


# ================================================================ 注入清单

INJECTIONS = [
    dict(
        name="M1 判定出现第二份实现",
        file="review",
        old='logger = get_logger(__name__)\n',
        new=('logger = get_logger(__name__)\n'
             '\n\n'
             'def previous_turn_was_clarification(messages):  # 注入：另写一份\n'
             '    return False\n'),
        expect={"test_judgment_has_a_single_implementation"},
        why="判定出现两份实现 ⇒ 至少一份永远测不到",
    ),
    dict(
        name="M2 薄壳变成有副作用（改调 ainvoke）",
        file="base_agent",
        old='            snapshot = await graph.aget_state(cfg)\n',
        new='            snapshot = await graph.ainvoke({}, config=cfg)\n',
        expect={"test_read_shell_is_read_only"},
        why="只读口顺手推进图 ⇒ 老板这轮问题会被先跑一遍再跑一遍",
    ),
    dict(
        name="M3 摘掉让路（defer 恒 False）",
        file="review",
        old=('            if intent != "general" and session_id and user_id:\n'
             '                router = self._get_router()\n'
             '                if router is not None:\n'
             '                    defer_to_tools = await router.last_turn_was_clarification(\n'
             '                        session_id, user_id\n'
             '                    )\n'),
        new='            defer_to_tools = False  # 注入：摘掉让路\n',
        expect={
            "test_review_analyst_defers_on_clarification",
            "test_review_analyst_asks_the_instance_that_actually_runs_the_graph",
            "test_answer_to_clarification_defers_to_tools",
            "test_answer_to_clarification_falls_back_when_tools_miss",
            "test_keyword_hit_still_short_circuits_normally",
            "test_wired_agents_ratchet",
        },
        why="遗留项 A 未接线（答案又被当成新任务）；"
            "`router.asked == 1` 随之红 = 连「问过没有」也没了",
    ),
    dict(
        name="M4 让路改成无条件（去掉会话/身份守卫）",
        file="review",
        old='            if intent != "general" and session_id and user_id:\n',
        new='            if intent != "general":  # 注入：去掉守卫\n',
        expect={
            "test_no_session_never_defers",
            "test_no_identity_never_defers",
        },
        why="拿不到会话证据也让路 ⇒ 行为不可解释、且白多一次 LLM 往返",
    ),
    dict(
        name="M5 删掉「工具环路没接住 ⇒ 退回直连」",
        file="review",
        old=('            if intent != "general" and defer_to_tools:\n'
             '                direct = await self._run_one(intent, context)\n'
             '                if direct is not None:\n'
             '                    return direct\n'),
        new='',
        expect={
            "test_review_analyst_defers_on_clarification",
            "test_answer_to_clarification_falls_back_when_tools_miss",
        },
        why="让路后没有兜底 ⇒ 比改造前更差（答案是直连，现在变引导语）",
    ),
    dict(
        name="M6 判定忽略「有没有调工具」",
        file="base_agent",
        old='        return has_reply and not has_tool\n',
        new='        return has_reply  # 注入：忽略工具活动\n',
        expect={"test_pure_judgment_tool_call_means_not_clarification"},
        why="把「干活的轮次」也判成追问 ⇒ 每轮都让路",
    ),
    dict(
        name="M7 问错对象（问自己而不是跑图的实例）",
        file="review",
        old='                    defer_to_tools = await router.last_turn_was_clarification(\n',
        new='                    defer_to_tools = await self.last_turn_was_clarification(\n',
        expect={
            "test_review_analyst_defers_on_clarification",
            "test_review_analyst_asks_the_instance_that_actually_runs_the_graph",
            "test_answer_to_clarification_defers_to_tools",
            "test_answer_to_clarification_falls_back_when_tools_miss",
            "test_keyword_hit_still_short_circuits_normally",
        },
        why="主实例没绑 checkpointer ⇒ 看着接了线、其实从不生效（静默失效）",
    ),
    dict(
        name="M8 早退守卫漏掉身份（只判会话）",
        file="base_agent",
        old=('        if not session_id or not user_id:\n'
             '            return False\n'),
        new=('        if not session_id:  # 注入：漏判身份\n'
             '            return False\n'),
        expect={"test_read_shell_refuses_without_session_or_identity"},
        why="thread_id 空段会被跳过 ⇒ 可能读到别人的上一轮",
    ),
]


def _run_loop(rows, failures) -> None:
    for i, inj in enumerate(INJECTIONS):
        _restore()                                              # ② 从原件现算
        ok, how = _apply(inj["file"], inj["old"], inj["new"])
        tag = f"M{i + 1}"
        if not ok:
            rows.append((inj["name"], "注入本身失败", how, "—", "—"))
            failures.append(f"{inj['name']}: {how}")             # ④ 单独归类
            continue
        reds, note = _run_gate(tag)
        if reds is None:
            rows.append((inj["name"], "跑不起来", how, "—", note))
            failures.append(f"{inj['name']}: {note}")
            continue
        got = sorted(reds)
        want = sorted(inj["expect"])
        want_set = set(want)
        verdict = "✔ 命中" if (reds == want_set and len(got) == len(want)) else "✘ 不符"
        if verdict != "✔ 命中":
            failures.append(
                f"{inj['name']}: 实测 {got} / 声明 {want}"
                f"（漏={sorted(want_set - reds)} 多={sorted(reds - want_set)}）"
            )
        rows.append((inj["name"], verdict, how, f"{len(got)} 红", ",".join(got)))


def main() -> int:
    _snapshot(refresh="--refresh" in sys.argv)
    print(f"pristine 基线落盘 → {TMP}")
    for key in FILES:
        print(f"  {FILES[key]:45s} sha256={_sha(PRISTINE[key])[:16]}…  "
              f"EOL={'CRLF' if ORIG_EOL[key] else 'LF'}")

    rows: list = []
    failures: list = []
    try:
        print("\n== 0. 基线（未注入）应当全绿 ==")
        reds, note = _run_gate("baseline")
        if reds is None:
            print("  !! 基线跑不起来：" + note)
            return 2
        print(f"  基线：{note}；红集={sorted(reds)}")
        if reds:
            print("  !! 基线就红 —— 先修门禁，注入无意义。")
            return 3

        _run_loop(rows, failures)
    finally:
        _restore()                                              # ⑤ 崩溃也还原

    print("\n== 逐条读数 ==")
    w0 = max(len(r[0]) for r in rows) if rows else 0
    for name, verdict, how, nred, detail in rows:
        print(f"  {name:<{w0}}  {verdict:<10} {how:<34} {nred:<6} {detail}")

    print("\n== 终态复核 ==")
    bad = False
    for key in FILES:
        same = _read_raw(key) == PRISTINE[key]
        bad |= not same
        print(f"  {FILES[key]:45s} {'✔ 与基线全等' if same else '✘ 与基线不一致'}")
    if bad:
        print("  !! 还原失败 —— 用 .workbuddy/tmp/probe_250/*.pristine.py 覆盖")
        return 4

    hit = sum(1 for r in rows if r[1] == "✔ 命中")
    print(f"\n== 汇总：{hit}/{len(INJECTIONS)} 条注入被门禁抓到，红集与声明完全一致 ==")
    if failures:
        print("失败明细：")
        for f in failures:
            print("  - " + f)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
