"""第 249 轮 · 反向注入：证明 L 组 9 条判据不是空跑。

纪律（本仓既有五条）：
  ① pristine 基线落盘（本例用 tempfile 副本树，真仓源码全程零触碰）；
  ② 每条注入**从原件现算副本**，绝不链式叠加；
  ③ 声明 `expect_hit` 并断言「实测红集 == 声明红集」；
  ④ 锚点命中数 ≠ 1 时**单独报**「注入本身失败」，与「注入没抓到」分开；
  ⑤ 收尾核对真仓两份源文件的 sha256 未变。

★ 台架必须用 Python `subprocess` 驱动 node —— 受管 node 不能再 spawn 受管 node
  （`.cjs` 台架里 `execFileSync(process.execPath, ...)` 必 `EBUSY errno=-4082`）。

★ 两条**探针自身的坑**（首跑踩到，都伪装成"注入没抓到"）：
  1. **锚点没做行尾归一化**：`replies/index.ts` 是 CRLF，LF 锚点命中 0 次
     ⇒ 8 条注入全报"注入本身失败"。修法：读入时 `\r\n`→`\n` 归一，写回按**各文件原样** EOL 还原。
  2. **L7 的扫描面写死在真 `src` 上**：注入改的是副本、扫描的是真文件 ⇒ L7 照旧绿。
     修法：门禁加 `PROD_SRC_DIR` 注入口，探针把**整棵 src 树**拷进临时目录。
"""
from __future__ import annotations

import hashlib
import os
import re
import shutil
import subprocess
import tempfile

ROOT = "D:/ai/eCommerce"
FRONT = os.path.join(ROOT, "frontend")
GATE = os.path.join(FRONT, "scripts", "check-chat-failure-path.cjs")
NODE = "C:/Users/Administrator/.workbuddy/binaries/node/versions/22.22.2-3/node.exe"

REPLIES = "frontend/src/composables/chat/replies/index.ts"
SHORTCUTS = "frontend/src/composables/chat/useAgentShortcuts.ts"

#: 两份被测源文件在**副本 src 根**下的相对路径
UNDER_SRC = {
    REPLIES: "composables/chat/replies/index.ts",
    SHORTCUTS: "composables/chat/useAgentShortcuts.ts",
}

# 每处锚点都必须**恰好命中 1 次**（命中 0 次 = 注入本身失败，不是"没抓到"）
INJECTIONS = [
    dict(
        id="M1", file=REPLIES, expect=["L1", "L4", "L5"],
        why="`turnProducedResult` 无条件 true（追问轮也当成产出）",
        old="): boolean {\n  // ★ 「取不到权威清单",
        new="): boolean {\n  if (true) return true\n  // ★ 「取不到权威清单",
    ),
    dict(
        id="M2", file=REPLIES, expect=["L2", "L4"],
        why="`turnProducedResult` 无条件 false（任务永不结束 ⇒ 点名永不清理）",
        old="): boolean {\n  // ★ 「取不到权威清单",
        new="): boolean {\n  return false\n  // ★ 「取不到权威清单",
    ),
    dict(
        id="M3", file=REPLIES, expect=["L4"],
        why="删掉 `if (last.data) return true` ⇒ 判据只剩 displayType 那一半",
        old="  if (last.data) return true\n",
        new="",
    ),
    dict(
        id="M4", file=REPLIES, expect=["L4"],
        why="末行改成 `return false` ⇒ 判据只剩 data 那一半",
        old="  return !!last.displayType && last.displayType !== 'text'\n",
        new="  return false\n",
    ),
    dict(
        id="M5", file=REPLIES, expect=["L5"],
        why="删掉「读不到就按未产出」的守卫 ⇒ 桩缺 messagesByAgent 时直接崩",
        old="  const list = byAgent ? byAgent[agentId || 'default'] : null\n",
        new="  const list = chatStore.messagesByAgent[agentId || 'default']\n",
    ),
    dict(
        id="M6", file=REPLIES, expect=["L1", "L3", "L4", "L5", "L6"],
        why="清除改成**无条件** ⇒ 退回「一次性」语义（形态与行为同时红）",
        old="    if (skill && turnProducedResult(chatStore, agentId)) ctx.clearPendingSkill()\n",
        new="    ctx.clearPendingSkill()\n",
    ),
    dict(
        id="M7", file=SHORTCUTS, expect=["L7", "L9"],
        why="删掉 watch(currentBackendAgent) 里的清点名 ⇒ 点名跨 Agent 残留",
        old="  watch(currentBackendAgent, () => {\n    ctx.clearPendingSkill()\n  })\n",
        new="  watch(currentBackendAgent, () => {\n  })\n",
    ),
    dict(
        id="M8", file=REPLIES, expect=["L6", "L8"],
        why="读取点改成 `ctx['peekPendingSkill']()` ⇒ 绕过形态判据（行为不变）",
        old="  const skill = ctx.peekPendingSkill()\n",
        new="  const skill = ctx['peekPendingSkill']()\n",
    ),
]

L_IDS = [f"L{i}" for i in range(1, 10)]


def sha(path: str) -> str:
    return hashlib.sha256(open(path, "rb").read()).hexdigest()


def read_norm(path: str):
    """读成 (LF 归一化文本, 原 EOL) —— 锚点匹配必须行尾归一化（本仓 CRLF/LF 混存）。"""
    raw = open(path, "rb").read()
    eol = "\r\n" if b"\r\n" in raw else "\n"
    return raw.decode("utf-8").replace("\r\n", "\n"), eol


def write_eol(path: str, text: str, eol: str) -> None:
    with open(path, "wb") as fh:
        fh.write(text.replace("\n", eol).encode("utf-8"))


def run_gate(src_root: str):
    env = dict(os.environ)
    env["PROD_SRC_DIR"] = src_root
    env["PROD_REPLIES_INDEX"] = os.path.join(src_root, "composables/chat/replies/index.ts")
    env["PROD_AGENT_SHORTCUTS"] = os.path.join(src_root, "composables/chat/useAgentShortcuts.ts")
    p = subprocess.run([NODE, GATE], cwd=FRONT, env=env,
                       capture_output=True, text=True, encoding="utf-8", errors="replace")
    out = (p.stdout or "") + (p.stderr or "")
    if not out.strip():
        return None, out            # 空输出 = 台架坏了，与「没红」分开报
    failed = set(re.findall(r"^FAIL\s+(L\d+)\b", out, re.M))
    passed = set(re.findall(r"^PASS\s+(L\d+)\b", out, re.M))
    return (failed, passed), out


def main() -> int:
    tmp = tempfile.mkdtemp(prefix="probe249_")
    src_root = os.path.join(tmp, "src")
    shutil.copytree(os.path.join(FRONT, "src"), src_root)

    sha_before = {rel: sha(os.path.join(ROOT, rel)) for rel in (REPLIES, SHORTCUTS)}
    pristine = {}
    for rel in (REPLIES, SHORTCUTS):
        pristine[rel] = read_norm(os.path.join(src_root, UNDER_SRC[rel]))
        print(f"  {rel}  EOL={'CRLF' if pristine[rel][1] == chr(13) + chr(10) else 'LF'}  "
              f"sha={sha_before[rel][:12]}  {len(pristine[rel][0])} chars")
    print(f"pristine 副本树 {src_root}")

    # ---- 基线（未注入）必须全绿，且 9 条 L 都在场 ----
    res, out = run_gate(src_root)
    if res is None:
        print("✗ 基线：门禁**零输出** ⇒ 台架本身坏了（不是判据的问题）")
        return 2
    base_fail, base_pass = res
    print(f"\n基线：PASS(L 组)={len(base_pass)}  FAIL(L 组)={len(base_fail)}")
    if base_fail:
        print(f"✗ 基线不是全绿，无法归因：{sorted(base_fail)}")
        print(out[-2000:])
        return 2
    missing = set(L_IDS) - base_pass
    if missing:
        print(f"✗ 基线里缺少这些 L 判据：{sorted(missing)} ⇒ 判据集不自洽")
        return 2

    # ---- 逐条注入（每条都从 pristine 现算，不叠加）----
    print("\n" + "=" * 92)
    print(f"{'#':4s}{'预期红':30s}{'实测红':30s}判定")
    print("=" * 92)
    bad = 0
    for inj in INJECTIONS:
        # ★ 每轮都从 pristine 重算两个文件（绝不链式叠加）
        for rel in (REPLIES, SHORTCUTS):
            write_eol(os.path.join(src_root, UNDER_SRC[rel]), pristine[rel][0], pristine[rel][1])

        target_rel = inj["file"]
        path = os.path.join(src_root, UNDER_SRC[target_rel])
        text = pristine[target_rel][0]
        n = text.count(inj["old"])
        if n != 1:
            # ④ 注入本身失败 —— 与「注入没抓到」分开报
            print(f"{inj['id']:4s}{'':30s}{'':30s}✗ 注入本身失败：锚点命中 {n} 次（须 1）")
            bad += 1
            continue
        write_eol(path, text.replace(inj["old"], inj["new"]), pristine[target_rel][1])

        res, out = run_gate(src_root)
        if res is None:
            print(f"{inj['id']:4s}{'':30s}{'':30s}✗ 台架零输出（基础设施故障，非判据结论）")
            bad += 1
            continue
        got_fail, _ = res
        exp = set(inj["expect"])
        ok = got_fail == exp
        if not ok:
            bad += 1
        print(f"{inj['id']:4s}{','.join(sorted(exp)):30s}"
              f"{','.join(sorted(got_fail)) or '(无)':30s}{'✓ 命中且只命中声明的' if ok else '✗ 不符'}")
        if not ok:
            print(f"      ↳ {inj['why']}")
            extra, miss = got_fail - exp, exp - got_fail
            if miss:
                print(f"        声明了但没红：{sorted(miss)} ⇒ 该判据没在守这件事")
            if extra:
                print(f"        没声明但红了：{sorted(extra)} ⇒ 声明不全（判据之间有耦合）")

    sha_after = {rel: sha(os.path.join(ROOT, rel)) for rel in (REPLIES, SHORTCUTS)}
    print("\n" + "=" * 92)
    touched = [rel for rel in sha_before if sha_before[rel] != sha_after[rel]]
    print(f"真仓源码核对：{'✗ 被改动 ' + str(touched) if touched else '✓ 两份源文件 sha256 未变（全程只动临时副本树）'}")
    shutil.rmtree(tmp, ignore_errors=True)
    print(f"结果：{'✓ 8 条注入全部命中且只命中声明的那几条' if bad == 0 else f'✗ {bad} 条异常'}")
    return 1 if bad else 0


if __name__ == "__main__":
    raise SystemExit(main())
