# -*- coding: utf-8 -*-
"""第 248 轮 · 前端反向注入台架：证明 `check-skill-filter-logic.cjs` 新增的
F38 / F39 / F39b / F39c 四条断言**真的会红**。

==============================================================================
★★ 为什么这个台架用 Python 而不是 Node（踩坑记录，别再改回去）
==============================================================================
最初写成 `probe-248-inject.cjs`，用 `child_process.execFileSync(process.execPath, …)`
去拉起门禁 —— 实测在**本机沙箱**下必然 `EBUSY`：

    code=EBUSY errno=-4082 syscall=spawnSync
    <…>\\node\\versions\\22.22.2-3\\node.exe

即"受管 node 不能再 spawn 受管 node"。症状非常像"门禁输出为空"（`out` 是空串、
FAIL 一条没抽到、基线 0/0），很容易被误读成"注入没被拦住" ——
**探针基础设施故障伪装成被测对象缺陷**，正是本仓那条"注入失败要与注入没抓到分开报"
的反面教材。⇒ 改成 Python `subprocess` 驱动（本机实测可正常拉起 node）。

==============================================================================
★ 纪律（与 `backend/scripts/probe_248_inject.py` 同一套）
==============================================================================
① pristine 基线必须落盘（未注入时必须全绿）；② 每条注入从原件现算副本，
绝不链式叠加；③ 声明 expect_hit 并用**子集**判定 + 断言"确实红了"；
④ 锚点没命中要**单独报**（探针坏了 ≠ 门禁坏了）；⑤ 结束时校验真仓 sha 未变。
"""
import hashlib
import json
import os
import re
import shutil
import subprocess
import tempfile
from pathlib import Path

FRONTEND = Path(r"D:\ai\eCommerce\frontend")
NODE = r"C:\Users\Administrator\.workbuddy\binaries\node\versions\22.22.2-3\node.exe"
GATE = "scripts/check-skill-filter-logic.cjs"

TARGETS = {
    "store": "src/stores/skills.ts",
    "cards": "src/composables/chat/useAgentShortcuts.ts",
}

INJECTIONS = [
    (
        "M1", "store",
        "把 isShortcut 过滤搬进 skillsOfAgent（「生效于」被污染 ⇒ 管理页分组凭空少条目）",
        "return items.value.filter((s) => s.enabled && s.enabledAgents.includes(agentName))",
        "return items.value.filter((s) => s.enabled && s.enabledAgents.includes(agentName) "
        "&& s.isShortcut !== false)",
        ["F38 ★ skillsOfAgent（「生效于」）不受 isShortcut 影响（含 isShortcut:false 诱饵行）"],
    ),
    (
        "M2", "cards",
        "删掉卡片派生的 isShortcut 过滤（卡片区不再摘掉规矩型技能）",
        "      .filter((c) => c.isShortcut !== false)\n",
        "",
        ["F39 卡片派生（skillCards）按 isShortcut 过滤"],
    ),
    (
        "M3", "cards",
        "把过滤方向取严（!== false → === true ⇒ 缺字段的旧响应丢光卡片）",
        ".filter((c) => c.isShortcut !== false)",
        ".filter((c) => c.isShortcut === true)",
        ["F39b ★ 过滤方向是 `!== false`（缺字段按「显示」处理，取宽）"],
    ),
    (
        "M4", "cards",
        "卡片派生自己重写「启用 + 归属 Agent」判定（第二份实现）",
        "[...skillStore.skillsOfAgent(currentBackendAgent.value)]",
        "[...skillStore.items.filter((s) => s.enabled && "
        "s.enabledAgents.includes(currentBackendAgent.value))]",
        ["F39c 卡片派生仍复用 store 的 skillsOfAgent（没有第二份「启用 + 归属 Agent」判定）"],
    ),
]


def sha(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()[:16]


def make_tree(tmp: Path) -> None:
    for rel in TARGETS.values():
        dst = tmp / rel
        dst.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(FRONTEND / rel, dst)


def run_gate(src_root: Path) -> dict:
    env = dict(os.environ)
    env["SKILL_FILTER_SRC_ROOT"] = str(src_root)
    proc = subprocess.run(
        [NODE, GATE],
        cwd=str(FRONTEND),
        env=env,
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
        timeout=300,
    )
    out = (proc.stdout or "") + "\n" + (proc.stderr or "")
    red = set()
    for line in out.splitlines():
        m = re.match(r"^FAIL\s+(.+?)(?:\s+\|.*)?$", line.strip())
        if m:
            red.add(m.group(1).strip())
    pm = re.search(r"---- (\d+)/(\d+) 通过 ----", out)
    return {
        "red": red,
        "rc": proc.returncode,
        "pass": int(pm.group(1)) if pm else 0,
        "total": int(pm.group(2)) if pm else 0,
        "out_head": "\n".join(out.strip().splitlines()[:3]),
    }


def main() -> int:
    pristine = {k: sha(FRONTEND / rel) for k, rel in TARGETS.items()}
    report = {"pristine_sha": pristine, "steps": [], "failures": 0}
    bad = 0
    tmp = Path(tempfile.mkdtemp(prefix="r248-fe-"))

    try:
        # ---------- ⓪ 基线（同样走副本树：证明"副本机制本身"不改变结论）----------
        make_tree(tmp)
        base = run_gate(tmp)
        base_ok = base["rc"] == 0 and not base["red"] and base["total"] > 0
        report["pristine"] = {
            "rc": base["rc"], "pass": base["pass"], "total": base["total"],
            "red": sorted(base["red"]), "baseline_ok": base_ok, "out_head": base["out_head"],
        }
        print(f"[{'OK' if base_ok else 'BAD'}] 基线（未注入，走副本树）："
              f"{base['pass']}/{base['total']} 通过 rc={base['rc']}")
        if not base_ok:
            print("   ⇒ 基线不绿（若是 spawn EBUSY / 输出空，先修台架，别改结论）")
            bad += 1

        # ---------- 逐条注入 ----------
        for code, target, desc, old, new, expect in INJECTIONS:
            shutil.rmtree(tmp, ignore_errors=True)
            make_tree(tmp)

            rel = TARGETS[target]
            p = tmp / rel
            text = p.read_text(encoding="utf-8")
            hits = text.count(old)
            if hits != 1:
                report["steps"].append(
                    {"code": code, "desc": desc, "status": "INJECTION_FAILED", "anchor_hits": hits}
                )
                print(f"[BAD] {code} {desc} —— 注入锚点命中 {hits} 次（④ 探针坏了，不是门禁问题）")
                bad += 1
                continue

            p.write_text(text.replace(old, new, 1), encoding="utf-8", newline="")
            res = run_gate(tmp)
            actual = res["red"]
            missing = [n for n in expect if n not in actual]
            ok = not missing and bool(actual)
            report["steps"].append({
                "code": code, "desc": desc,
                "status": "OK" if ok else "MISMATCH",
                "expected_hit": expect, "actual_red": sorted(actual),
                "missing": missing,
                "extra": sorted(n for n in actual if n not in expect),
                "pass": res["pass"], "total": res["total"],
            })
            if ok:
                extra = len(actual) - len(expect)
                note = f"（连带红 {extra} 条）" if extra else "（且只红了这些）"
                print(f"[OK]  {code} {desc} —— 命中 {len(expect)} 条{note}")
            else:
                bad += 1
                print(f"[BAD] {code} {desc}")
                print(f"      期望红={expect}")
                print(f"      实际红={sorted(actual)}  （通过 {res['pass']}/{res['total']}）")
                if missing:
                    print(f"      ⑤ 漏抓（注入没被拦住）={missing}")
    finally:
        shutil.rmtree(tmp, ignore_errors=True)

    after = {k: sha(FRONTEND / rel) for k, rel in TARGETS.items()}
    report["after_sha"] = after
    report["pristine_untouched"] = after == pristine
    if not report["pristine_untouched"]:
        bad += 1

    print("")
    print(f"[{'OK' if report['pristine_untouched'] else 'BAD'}] 真仓源码未被触碰"
          f"（sha 与基线一致：{report['pristine_untouched']}）")
    report["failures"] = bad
    print("")
    print("RESULT_JSON: " + json.dumps(report, ensure_ascii=False))
    return 1 if bad else 0


if __name__ == "__main__":
    raise SystemExit(main())
