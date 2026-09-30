# -*- coding: utf-8 -*-
"""
反向注入自证：证明第 291 轮新加的门禁 D8 **是可红的**（不是恒真的装饰）。

做法：只把 `"dispositions"` 塞回 `ViewId = Literal[...]`（**另一份清单 VIEW_IDS 不动**），
      再跑 `check-review-library-view.cjs` —— 期望：
        · 退出码 != 0
        · 输出里出现 `FAIL  D8`
      然后还原，再跑一遍 —— 期望恢复 49/49 PASS。

★ 为什么必须做这一步：门禁最容易犯的错是「两个集合都抽空 ⇒ 空集 == 空集恒真」，
  看起来天天绿，其实什么都没守。反向注入是唯一的解药。
"""
import subprocess
import sys
from pathlib import Path

ROOT = Path(r"D:\ai\eCommerce")
nav = ROOT / "backend" / "modules" / "secretary" / "navigation_tools.py"
gate = ROOT / "frontend" / "scripts" / "check-review-library-view.cjs"
NODE = r"C:\Users\Administrator\.workbuddy\binaries\node\versions\22.22.2-3\node.exe"

raw = nav.read_bytes().decode("utf-8")
NL = "\r\n" if "\r\n" in raw else "\n"

# ★ 这条线在 VIEW_IDS 与 ViewId Literal 里**各出现一次** —— 只改后者：
#   先定位 `ViewId = Literal[`，再取它**之后**的那处（否则会误伤运行时清单，
#   注入就变成"两边同步改"了，D8 照样绿，得出完全相反的结论）。
vid = raw.index("ViewId = Literal[")
pos = raw.index('"competitors", "monitor",', vid)
LINE = raw[pos : raw.index("\n", pos)]
assert '"dispositions"' not in LINE, LINE


def run_gate(tag):
    p = subprocess.run(
        [NODE, str(gate)], capture_output=True, text=True, encoding="utf-8", errors="replace"
    )
    out = (p.stdout or "") + (p.stderr or "")
    fails = [ln.strip() for ln in out.splitlines() if ln.strip().startswith("FAIL")]
    passed = [ln for ln in out.splitlines() if "通过" in ln or "失败" in ln]
    print("--- %s: exit=%d" % (tag, p.returncode))
    for ln in fails:
        print("      " + ln)
    for ln in passed:
        print("      " + ln.strip())
    return p.returncode, out


print("=== [1] 反向注入：把 dispositions 塞回 ViewId Literal ===")
bad = raw[:pos] + LINE.replace('"competitors"', '"dispositions", "competitors"', 1) + raw[pos + len(LINE):]
nav.write_bytes(bad.encode("utf-8"))
code1, out1 = run_gate("注入后")
ok1 = code1 != 0 and "D8" in out1 and out1.count("FAIL") >= 1
print("      => D8 是否被注入打红：%s\n" % ("是（可证伪 ✓）" if ok1 else "否 —— 门禁是装饰"))

print("=== [2] 还原 ===")
nav.write_bytes(raw.encode("utf-8"))
code2, out2 = run_gate("还原后")
ok2 = code2 == 0 and "49 条形态断言" in out2
print("      => 恢复绿且断言数仍是 49：%s\n" % ("是 ✓" if ok2 else "否"))

print("=== 结论 ===")
print("  D8 反向注入可红 =", ok1)
print("  还原后全绿      =", ok2)
print("  文件已还原      =", nav.read_bytes().decode("utf-8") == raw)
sys.exit(0 if (ok1 and ok2) else 1)
