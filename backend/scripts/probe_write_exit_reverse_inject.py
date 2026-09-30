# -*- coding: utf-8 -*-
"""
双向注入自证 —— 证明 `check-disposition-write-exit.cjs` **既会红、也不会假红**。

方向 A（必须红）：新建一个 .vue，真的 `import { approveDisposition } from '@/api/trade'`
   ⇒ 期望门禁 FAIL 在 `C1 approveDisposition`，退出码非 0。
   证明：第二个 UI 出口会被拦住，这条门禁不是装饰。

方向 B（必须绿）：新建一个 .vue，**只在注释里**提 approveDisposition（不真 import）
   ⇒ 期望门禁仍然全绿。
   证明：判据不被注释喂饱 —— 这正是本仓反复踩的「源码字符串包含」坑。
   如果这一步变红，说明门禁会误伤含注释的普通文件；
   如果这一步变红而第一步不变红，那说明判据被别的东西顶住了（更糟）。

跑完务必恢复原状（删掉两个临时文件并复跑确认绿）。
"""
import shutil
import subprocess
import tempfile
from pathlib import Path

ROOT = Path(r"D:\ai\eCommerce")
SRC = ROOT / "frontend" / "src"
GATE = ROOT / "frontend" / "scripts" / "check-disposition-write-exit.cjs"
NODE = r"C:\Users\Administrator\.workbuddy\binaries\node\versions\22.22.2-3\node.exe"

TMP = SRC / "components" / "TaskConfigPanel" / "configs" / "_inj_tmp.vue"


def run_gate():
    p = subprocess.run(
        [NODE, str(GATE)], capture_output=True, text=True, encoding="utf-8", errors="replace"
    )
    return p.returncode, (p.stdout or "") + (p.stderr or "")


def report(tag, code, out):
    fails = [ln.strip() for ln in out.splitlines() if ln.strip().startswith("FAIL")]
    tail = [ln.strip() for ln in out.splitlines() if "门禁通过" in ln or "门禁失败" in ln]
    print("--- %s exit=%d" % (tag, code))
    for f in fails:
        print("      " + f)
    for t in tail:
        print("      " + t)
    return code, out, fails


ok_all = True

# ---------------------------------------------------------------- 方向 A：真的第二个出口
A_SRC = """<template><div>x</div></template>
<script setup lang="ts">
import { approveDisposition } from '@/api/trade'
void approveDisposition
</script>
"""
TMP.write_text(A_SRC, encoding="utf-8")
c1, o1, f1 = report("A 真第二个出口（应红）", *run_gate()[:2])
ok_a = c1 != 0 and any("C1 approveDisposition" in x for x in f1)
print("      => %s\n" % ("PASS：会被第二个出口点红 ✓" if ok_a else "FAIL：第二个出口竟然进来了"))
ok_all = ok_all and ok_a

# ---------------------------------------------------------------- 方向 B：只在注释里提
B_SRC = """<template><div>x</div></template>
<script setup lang="ts">
// 这里**不要**调 approveDisposition —— 它是不可逆的人审动作，
// 全仓只允许 ReviewDeskConfig.vue 一个出口（第 291 轮收敛的结论）。
// approveDisposition / rejectDisposition / issueDisposition 同。
</script>
"""
TMP.write_text(B_SRC, encoding="utf-8")
c2, o2, f2 = report("B 只写在注释里（应绿）", *run_gate()[:2])
ok_b = c2 == 0 and not f2
print("      => %s\n" % ("PASS：注释不喂饱判据 ✓" if ok_b else "FAIL：判据被注释喂饱了 ⇒ 将来必然假绿"))
ok_all = ok_all and ok_b

# ---------------------------------------------------------------- 恢复
TMP.unlink(missing_ok=True)
c3, o3, f3 = report("C 清理后恢复", *run_gate()[:2])
ok_c = c3 == 0 and not f3 and not TMP.exists()
print("      => 恢复全绿且临时文件已删：%s\n" % ("✓" if ok_c else "✗"))
ok_all = ok_all and ok_c

print("=== 结论 ===")
print("  A 第二个出口会红 =", ok_a)
print("  B 注释不吃判据   =", ok_b)
print("  C 已恢复         =", ok_c)
print("  RESULT:", "PASS" if ok_all else "FAIL")
raise SystemExit(0 if ok_all else 1)
