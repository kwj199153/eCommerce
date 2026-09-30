# -*- coding: utf-8 -*-
"""第 248 轮 · 反向注入台架：证明 `test_skill_shortcut_flag.py` 的断言**真的会红**。

==============================================================================
★ 为什么必须做（本仓铁律）
==============================================================================
「没被反向注入验证过的门禁 = 没有门禁」。
一条从来没红过的断言，无法区分「功能是对的」与「断言写错了/空跑」。

==============================================================================
★ 台架自身的五条纪律（逐条都是从本仓事故里换来的）
==============================================================================
① **pristine 基线必须落盘**（写进报告，不是只 print）：先跑**未注入**的用例，
   断言全绿。这一步失败 ⇒ 后面的"红"毫无意义。
② 每条注入**从原件现算副本 → 注入 → 跑 → 还原**，绝不链式叠加：
   上一条没还原干净会让下一条**假红**（红的原因不是它）。
③ 同时声明 `expect_hit` 与 `expect_green`：
   · `expect_hit` 用**子集**判定（必须红，允许连带红别的 —— 一条注入确实可能
     同时打穿多条断言，这本身是"断言之间有共享前置"的正常现象）；
   · 但**必须**额外断言 `actual` 非空且包含 expect，否则"注入把文件搞崩、
     整个文件全红"也会通过，而它证明不了任何事。
④ **注入本身失败要单独报**（`old` 没命中 = 探针坏了，不是门禁坏了）：
   两者混在一起会得出**相反**的结论。
⑤ **结果必须落盘成 JSON**，且还原用**全等副本**（byte copy）+ 校验 sha256：
   只靠"再跑一次是绿的"不足以证明源码干净（可能恰好没测到被改坏的那条路径）。

==============================================================================
★ 覆盖率判据（本台架真正的结论）
==============================================================================
不是"有红了"，而是：**新门禁里每一个可注入的用例，都至少被一条注入打中过**。
不可注入的两条（纯 schema 断言 / 纯数据契约断言）必须**显式登记**并写明原因 ——
否则"没被覆盖"会伪装成"覆盖了"。
"""
import hashlib
import json
import os
import re
import shutil
import subprocess
from pathlib import Path

BACKEND = Path(r"D:\ai\eCommerce\backend")
PY = r"C:\Users\Administrator\.workbuddy\binaries\python\envs\default\Scripts\python.exe"
TEST_REL = "tests/test_skill_shortcut_flag.py"

SERVICE = BACKEND / "modules" / "skills" / "service.py"
PROVIDER = BACKEND / "modules" / "skills" / "provider.py"
SEED = BACKEND / "modules" / "skills" / "seed.py"

#: 受管的被测文件（每条注入前都从这里**全量还原**，再单独注入）
FILES = {
    "service": SERVICE,
    "provider": PROVIDER,
    "seed": SEED,
}
BACKUPS = {k: BACKEND / "scripts" / f"_r248_backup_{k}.py" for k in FILES}

#: 预期必须变红的用例（子集判定）
INJECTIONS = [
    # ---------------- service.py ----------------
    (
        "I1",
        "service",
        "serialize 不再下发 isShortcut（前端恒拿不到 ⇒ 卡片区靠兜底蒙对）",
        '        "isShortcut": getattr(skill, "as_shortcut", True) is not False,\n',
        "",
        {"test_the_flag_travels_through_the_wire_contract"},
    ),
    (
        "I2",
        "service",
        "serialize 的缺属性兜底方向反了（True → False）",
        'getattr(skill, "as_shortcut", True) is not False',
        'getattr(skill, "as_shortcut", False) is not False',
        {"test_serialize_assumes_true_when_the_column_is_missing"},
    ),
    (
        "I3",
        "service",
        "read_skill_for_agent 的过滤链加上了 as_shortcut（★ 关卡片被误实现成关注入）",
        "    agents = list(row.enabled_agents or [])\n"
        "    if agent_name not in agents:\n        return None\n",
        "    agents = list(row.enabled_agents or [])\n"
        "    if agent_name not in agents:\n        return None\n"
        "    if not bool(row.as_shortcut):\n        return None\n",
        {"test_turning_the_card_off_never_touches_injection"},
    ),
    (
        "I4a",
        "service",
        "update_skill 的『不提交就不动』退化成无条件赋值"
        "（★ 编辑一次标题 ⇒ 关掉的卡片静默长回来）",
        "    if any(k in data for k in SHORTCUT_KEYS):\n"
        "        row.as_shortcut = _read_shortcut(data)\n",
        "    row.as_shortcut = _read_shortcut(data)\n",
        {"test_update_without_the_field_does_not_touch_it"},
    ),
    (
        "I4b",
        "service",
        "update_skill 的三态判定退化成真值判定（显式 False 被当成『没提交』）",
        "    if any(k in data for k in SHORTCUT_KEYS):\n"
        "        row.as_shortcut = _read_shortcut(data)\n",
        '    if data.get("isShortcut"):\n'
        "        row.as_shortcut = _read_shortcut(data)\n",
        {"test_update_can_turn_the_card_off_and_back_on"},
    ),
    (
        "I5a",
        "service",
        "create_skill 的默认值反了（True → False）",
        "        as_shortcut=_read_shortcut(payload),\n",
        "        as_shortcut=False,\n",
        {"test_create_defaults_to_a_visible_card"},
    ),
    (
        "I5b",
        "service",
        "create_skill 忽略显式提交的 False（新建路径上开关失效）",
        "        as_shortcut=_read_shortcut(payload),\n",
        "        as_shortcut=True,\n",
        {"test_create_adopts_an_explicit_false"},
    ),
    (
        "I6",
        "service",
        "SHORTCUT_KEYS 收窄成只剩 camelCase 一个名字（DB 列名静默落默认值）",
        'SHORTCUT_KEYS = ("isShortcut", "asShortcut", "as_shortcut")',
        'SHORTCUT_KEYS = ("isShortcut",)',
        {
            "test_write_accepts_every_documented_alias[asShortcut]",
            "test_write_accepts_every_documented_alias[as_shortcut]",
        },
    ),
    (
        "I8",
        "service",
        "update_skill 只能写 True（卡片再也关不掉）",
        "        row.as_shortcut = _read_shortcut(data)\n",
        "        row.as_shortcut = True\n",
        {"test_update_can_turn_the_card_off_and_back_on"},
    ),
    # ---------------- provider.py ----------------
    (
        "I7",
        "provider",
        "build_catalog_for 的目录过滤加上了 as_shortcut（★ 第一级披露也断）",
        "                if bool(s.enabled) and agent_name in list(s.enabled_agents or [])\n",
        "                if bool(s.enabled) and agent_name in list(s.enabled_agents or [])\n"
        "                and bool(s.as_shortcut)\n",
        {
            "test_turning_the_card_off_never_touches_injection",
            # ★ 第 295 轮：这条注入现在**同时**打中新用例的 ④（端到端目录可达）。
            "test_the_demo_triage_skill_has_no_card_but_stays_reachable",
        },
    ),
    # ---------------- seed.py ----------------
    (
        "I9b",
        "seed",
        "规格表里「差评应对」的 as_shortcut 被删掉（撤卡片这个产品决策被回滚）",
        # ★ 锚点取紧随其后的那句手写工具注释，确保只命中这一条
        #   （`"as_shortcut": False,` 本身已不再唯一）。
        '        "as_shortcut": False,\n'
        '        # ★ 手写 5 个工具：本技能的取证是**一条链**（差评上下文 → 订单物流 →',
        '        # ★ 手写 5 个工具：本技能的取证是**一条链**（差评上下文 → 订单物流 →',
        {"test_the_demo_triage_skill_has_no_card_but_stays_reachable"},
    ),
    (
        "I9",
        "seed",
        "规格表里「复盘结论写法」被标回 as_shortcut=True（需求被回滚）",
        # ★ 第 295 轮改锚点：`"as_shortcut": False,` 从此**不再是全表唯一**
        #   （「差评应对」也撤了卡片）⇒ 必须带上紧随其后的 `"tools": []` 才唯一。
        #   不改的话台架会报 INJECTION_FAILED —— 而那会被误读成"门禁坏了"，
        #   实际是"探针锚点过时"（④ 注入失败要与注入没抓到分开报）。
        '        "as_shortcut": False,\n        "tools": [],\n',
        '        "as_shortcut": True,\n        "tools": [],\n',
        {"test_the_demo_narrative_skill_has_no_card_but_stays_enabled"},
    ),
]

#: 明确**不可**用源码注入打中的用例（必须登记原因，否则"没覆盖"会伪装成"覆盖了"）
NOT_INJECTABLE = {
    "test_the_column_exists_in_the_database_with_the_right_shape":
        "它断言的是**库里的列形态**（类型/NOT NULL/无 server_default/有注释），"
        "改源码不改变已建好的列 ⇒ 只能用 DDL 注入，不在本台架范围。"
        "★ 它的守门人是 CI 的 `alembic check`（本轮实测抓到过一次真偏差：漏写 comment）"
        "与迁移的幂等守卫。",
}

#: ★ 第 295 轮：12 → 13（新增 `test_the_demo_triage_skill_has_no_card_but_stays_reachable`）
EXPECTED_PARAM_COUNT = 13


def sha(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()[:16]


def restore_all() -> dict:
    for key, backup in BACKUPS.items():
        shutil.copy2(backup, FILES[key])
    return {k: sha(FILES[k]) for k in FILES}


def run_pytest() -> dict:
    proc = subprocess.run(
        [PY, "-m", "pytest", TEST_REL, "-q", "--tb=no", "-rf", "-p", "no:cacheprovider"],
        cwd=str(BACKEND),
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
        timeout=900,
    )
    out = (proc.stdout or "") + "\n" + (proc.stderr or "")
    red = set()
    for line in out.strip().splitlines():
        m = re.match(r"FAILED\s+\S+::(?P<t>[\w\[\]\-\.]+)", line.strip())
        if m:
            red.add(m.group("t"))
    m = re.search(r"(\d+) passed", out)
    if m:
        passed = int(m.group(1))
    else:
        # ★ 本仓的 pytest **不保证**打印「N passed」汇总行（只给进度点串）⇒
        #   数进度点。这是本仓已有的一条判据：脚本计数须数 `.FEsx` 进度串。
        passed = 0
        for line in out.splitlines():
            pm = re.match(r"^([.FEsxXup]+)\s*\[\s*\d+%\]$", line.strip())
            if pm:
                passed += pm.group(1).count(".")
    return {
        "red": red,
        "passed": passed,
        "rc": proc.returncode,
        "tail": "\n".join(out.strip().splitlines()[-3:]),
    }


def main() -> int:
    if not all(p.exists() for p in FILES.values()):
        print("被测文件缺失：" + ", ".join(str(p) for p in FILES.values()))
        return 2

    os.chdir(BACKEND)
    pristine = {k: sha(FILES[k]) for k in FILES}
    for key, backup in BACKUPS.items():
        shutil.copy2(FILES[key], backup)

    report = {"pristine_sha": pristine, "steps": [], "failures": 0}
    all_red: set = set()
    bad = 0

    try:
        # ---------- ⓪ pristine 基线 ----------
        base = run_pytest()
        baseline_ok = base["rc"] == 0 and not base["red"] and base["passed"] == EXPECTED_PARAM_COUNT
        report["pristine"] = {
            "rc": base["rc"], "passed": base["passed"],
            "red": sorted(base["red"]), "baseline_ok": baseline_ok, "tail": base["tail"],
        }
        print(f"[{'OK' if baseline_ok else 'BAD'}] 基线（未注入）："
              f"passed={base['passed']}/{EXPECTED_PARAM_COUNT} rc={base['rc']}")
        if not baseline_ok:
            print("   ⇒ 基线不是全绿，后面的『红』没有意义。先修基线。")
            bad += 1

        # ---------- 逐条注入 ----------
        for code, filekey, desc, old, new, expect in INJECTIONS:
            restore_all()  # ② 每条都先全量还原，绝不链式叠加
            path = FILES[filekey]
            text = path.read_text(encoding="utf-8")
            hits = text.count(old)
            if hits != 1:
                report["steps"].append(
                    {"code": code, "file": filekey, "desc": desc,
                     "status": "INJECTION_FAILED", "anchor_hits": hits}
                )
                print(f"[BAD] {code} ({filekey}) {desc} —— 注入锚点命中 {hits} 次"
                      f"（④ 探针坏了，不是门禁问题）")
                bad += 1
                continue

            path.write_text(text.replace(old, new, 1), encoding="utf-8", newline="")
            res = run_pytest()
            actual = res["red"]
            all_red |= actual

            missing = expect - actual
            ok = (not missing) and bool(actual)  # ③ 子集 + 非空
            step = {
                "code": code, "file": filekey, "desc": desc,
                "status": "OK" if ok else "MISMATCH",
                "expected_hit": sorted(expect), "actual_red": sorted(actual),
                "missing": sorted(missing), "extra": sorted(actual - expect),
                "passed": res["passed"], "tail": res["tail"],
            }
            report["steps"].append(step)
            if ok:
                extra = sorted(actual - expect)
                note = f"（连带红 {len(extra)} 条：{extra}）" if extra else "（且只红了这些）"
                print(f"[OK]  {code} ({filekey}) {desc} —— 命中 {len(expect)} 条{note}")
            else:
                bad += 1
                print(f"[BAD] {code} ({filekey}) {desc}")
                print(f"      期望红={sorted(expect)}  实际红={sorted(actual)}")
                if missing:
                    print(f"      ⑤ 漏抓（注入没被拦住）={sorted(missing)}")
                if not actual:
                    print("      ⑤ 一条都没红 ⇒ 这条注入没被任何断言覆盖")
    finally:
        restored = restore_all()

    report["restored_sha"] = restored
    report["restored_exact"] = restored == pristine

    # ---------- 还原后再跑，证明源码干净 ----------
    final = run_pytest()
    report["after_restore"] = {
        "rc": final["rc"], "passed": final["passed"],
        "red": sorted(final["red"]),
        "green_again": final["rc"] == 0 and not final["red"]
        and final["passed"] == EXPECTED_PARAM_COUNT,
    }

    # ---------- 覆盖率判据 ----------
    declared = set(NOT_INJECTABLE)
    mismatched = sorted(declared & all_red)
    report["coverage"] = {
        "hit_by_injection": sorted(all_red),
        "not_injectable_declared": sorted(declared),
        "declared_but_actually_hit": mismatched,
    }
    coverage_bad = bool(mismatched)
    if coverage_bad:
        print(f"\n[BAD] 被登记为『不可注入』的用例其实被打中了：{mismatched}"
              f" ⇒ 登记理由过时，必须更正（否则会掩盖真实覆盖）")

    for key, backup in BACKUPS.items():
        backup.unlink(missing_ok=True)

    print("")
    print(f"[{'OK' if report['restored_exact'] else 'BAD'}] 源码按**全等副本**还原"
          f"（sha 与基线一致：{report['restored_exact']}）")
    print(f"[{'OK' if report['after_restore']['green_again'] else 'BAD'}] 还原后复跑："
          f"passed={final['passed']}/{EXPECTED_PARAM_COUNT} rc={final['rc']}")
    print(f"[{'OK' if not coverage_bad else 'BAD'}] 覆盖率：被注入打中的用例 "
          f"{len(all_red)} 条；登记为不可注入 {len(declared)} 条")
    print(f"       被打中：{sorted(all_red)}")

    bad += (0 if report["restored_exact"] else 1)
    bad += (0 if report["after_restore"]["green_again"] else 1)
    bad += (1 if coverage_bad else 0)
    report["failures"] = bad

    print("")
    print("RESULT_JSON: " + json.dumps(report, ensure_ascii=False))
    return 1 if bad else 0


if __name__ == "__main__":
    raise SystemExit(main())
