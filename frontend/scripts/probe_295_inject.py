# -*- coding: utf-8 -*-
"""第 295 轮 · 前端反向注入台架：证明 `check-skill-filter-logic.cjs` 新增的
F40 / F40b / F40c 三条断言**真的会红**。

为什么需要它：这三条判的是**界面文案**（撤卡片 chip 的措辞）。文案判据是本仓
最容易"空跑"的一类 —— 断言写错成 `includes('')`、或读了不存在的文件、
或环境变量没生效读了真仓，都会让它**永远绿**而没人发现。

★ 三条注入的**区分度**是这台架的重点（不只是"能红"）：

    S1  把 chip 改回「仅方法论」（两处）      ⇒ F40 红（引入禁词）+ F40b 红（计数不变）
    S2  只改一处（列表视图改成「无卡片」）    ⇒ **只** F40b 红 —— 它**没有**引入禁词，
                                                所以 F40 不红 ⇒ 证明 F40b 不是 F40 的附庸
    S3  两处 tooltip 都去掉「仍照常生效」      ⇒ **只** F40c 红

  若 S2 / S3 也把 F40 带红，说明三条判据其实在判同一件事（那么留一条就够）。

★ 台架纪律（与 `probe_248_inject.py` 同一套）：
   ① pristine 基线落盘；② 每条注入从原件现算副本，绝不链式叠加；
   ③ 声明期望红集合并用**子集**判定 + 断言"确实红了"；
   ④ 锚点没命中要单独报（探针坏了 ≠ 门禁坏了）；⑤ 结束校验真仓 sha 未变。

★ 为什么用 Python 而不是 Node 驱动：受管 node **不能 spawn 自身**（第 248 轮实测
   `EBUSY`, errno=-4082）。症状像"门禁输出为空"，会被误读成"注入没被拦住"。
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
    # ★ 三个都要复制进副本树：门禁会**同时**读它们（F39 读 cards、F40 读 mgr、
    #   store 的表单逻辑也在读集里）。少复制一个 ⇒ 基线就红，看着像"门禁坏了"。
    "store": "src/stores/skills.ts",
    "cards": "src/composables/chat/useAgentShortcuts.ts",
    "mgr": "src/components/SkillStore/SkillManager.vue",
}

#: 真仓里的 chip 形态（两处相同）
CHIP_OLD = 'title="对话页不给它快捷卡片（它仍照常生效：Agent 会在需要时自行加载完整步骤，也能被别的技能正文引用）">不设卡片</span>'
CHIP_BAD = 'title="对话页不给它快捷卡片：它是「怎么写」的规矩，不是一份成品（仍照常生效、可被引用）">仅方法论</span>'
CHIP_ALT = 'title="对话页不给它快捷卡片（它仍照常生效：Agent 会在需要时自行加载完整步骤，也能被别的技能正文引用）">无卡片</span>'
TIP_OLD = '（它仍照常生效：Agent 会在需要时自行加载完整步骤，也能被别的技能正文引用）'
TIP_GONE = '（对话页不给它快捷卡片）'

INJECTIONS = [
    (
        "S1", "mgr",
        "chip 文案改回「仅方法论」+ 旧 tooltip（第 295 轮前的措辞）",
        (CHIP_OLD, CHIP_BAD, 2),
        ["F40 ★ 撤卡片的 chip 不含「仅方法论」（那个词只对「规矩型」为真）"],
    ),
    (
        "S2", "mgr",
        "只改一处（列表视图那份 chip 换成别的词）—— 两个视图不一致",
        # ★ 只替换**第 2 处**（列表视图）。这里刻意换成「无卡片」：
        #   它**不**引入禁词，所以 F40 不该红，只有 F40b（计数）该红 ——
        #   这样才证明 F40b 有独立于 F40 的判别力。
        ("__SECOND_ONLY__", CHIP_ALT, 1),
        ["F40b ★ 两个视图都改了（卡片视图 + 列表视图，同一 chip 渲染两遍）"],
    ),
    (
        "S3", "mgr",
        "两处 tooltip 都删掉「仍照常生效」承诺 —— chip 不再说明「能力还在」",
        (TIP_OLD, TIP_GONE, 2),
        ["F40c chip 的 tooltip 承诺「仍照常生效」"],
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


def inject(text: str, spec) -> tuple:
    """按 (old, new, want) 注入；`__SECOND_ONLY__` 表示只替换第 2 次出现。

    :return: (新文本, 命中数, 错误说明或 None)
    """
    old, new, want = spec
    if old == "__SECOND_ONLY__":
        # 第 2 处 = 列表视图那份。用 find 定位后只替换那一段。
        first = text.find(CHIP_OLD)
        second = text.find(CHIP_OLD, first + 1)
        if first < 0 or second < 0:
            return text, 0, "真仓里找不到两处 chip（F40b 的前提不成立）"
        end = second + len(CHIP_OLD)
        return text[:second] + new + text[end:], 1, None
    hits = text.count(old)
    if hits != want:
        return text, hits, None
    return text.replace(old, new), hits, None


def main() -> int:
    pristine = {k: sha(FRONTEND / rel) for k, rel in TARGETS.items()}
    report = {"pristine_sha": pristine, "steps": [], "failures": 0}
    bad = 0
    tmp = Path(tempfile.mkdtemp(prefix="r295-fe-"))

    try:
        # ---------- ⓪ 基线 ----------
        make_tree(tmp)
        base = run_gate(tmp)
        base_ok = base["rc"] == 0 and not base["red"] and base["total"] > 0
        report["pristine"] = {
            "rc": base["rc"], "pass": base["pass"], "total": base["total"],
            "red": sorted(base["red"]), "baseline_ok": base_ok,
            "out_head": base["out_head"],
        }
        print(f"[{'OK' if base_ok else 'BAD'}] 基线（未注入，走副本树）："
              f"{base['pass']}/{base['total']} 通过 rc={base['rc']}")
        if not base_ok:
            print("   ⇒ 基线不绿（若是 spawn EBUSY / 输出空，先修台架，别改结论）")
            bad += 1

        # ---------- 逐条注入 ----------
        for code, target, desc, spec, expect in INJECTIONS:
            shutil.rmtree(tmp, ignore_errors=True)
            make_tree(tmp)

            p = tmp / TARGETS[target]
            text = p.read_text(encoding="utf-8")
            new_text, hits, err = inject(text, spec)
            if err or hits != spec[2]:
                report["steps"].append(
                    {"code": code, "desc": desc,
                     "status": "INJECTION_FAILED", "anchor_hits": hits, "err": err}
                )
                print(f"[BAD] {code} {desc} —— 注入锚点问题：{err or f'命中 {hits} 次（期望 {spec[2]}）'}"
                      f"（④ 探针坏了，不是门禁坏）")
                bad += 1
                continue

            p.write_text(new_text, encoding="utf-8", newline="")
            res = run_gate(tmp)
            actual = res["red"]
            missing = [n for n in expect if n not in actual]
            # ③ 子集 + 非空。★ S2/S3 还额外要求"**只**红声明的那条"（区分度）。
            ok = (not missing) and bool(actual)
            if code in ("S2", "S3") and ok and len(actual) != len(expect):
                ok = False
            report["steps"].append({
                "code": code, "desc": desc,
                "status": "OK" if ok else "MISMATCH",
                "expected_hit": expect, "actual_red": sorted(actual),
                "missing": missing,
                "extra": sorted(n for n in actual if n not in expect),
                "pass": res["pass"], "total": res["total"],
            })
            if ok:
                extra = sorted(actual - set(expect))
                note = f"（连带红 {len(extra)} 条：{extra}）" if extra else "（且只红了这些）"
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
