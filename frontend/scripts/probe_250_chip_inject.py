"""第 250 轮 · 反向注入：证明 **L7（扩到 3 处）** 与 **L10（chip 全链）** 不是空跑。

背景：老板本轮批准「给残留窗口加一个可见的撤销 chip」⇒ `clearPendingSkill()` 的合法
调用点从 2 个变 3 个。旧断言（恰好 2）在此从**资产**变**负资产**，所以 L7 被显式扩写；
同时新增 L10 钉住 chip 的上下游四段。本台架要证明的正是**这两处改动真的有牙**。

纪律（本仓既有五条，逐条落实）：
  ① pristine 基线落盘（用 tempfile 副本树，真仓源码全程零触碰）；
  ② 每条注入**从原件现算副本**，绝不链式叠加；
  ③ 声明 `expect_hit` 并断言「实测红集 == 声明红集」（另加一条**对照**：只动注释必须全绿）；
  ④ 锚点命中数 ≠ 1 时**单独报**「注入本身失败」，与「注入没抓到」分开；
  ⑤ 收尾核对真仓四份源文件的 sha256 未变，且 `try/finally` 兜崩溃。

★ 台架必须用 Python `subprocess` 驱动 node —— 受管 node 不能再 spawn 受管 node
  （`.cjs` 台架里 `execFileSync(process.execPath, ...)` 必 `EBUSY errno=-4082`）。

★ 两条探针自身的坑（第 249 轮踩过，本轮沿用修法）：
  1. **锚点没做行尾归一化**：`check` 侧生产文件 CRLF/LF 混存 ⇒ 读入归一，写回按**各文件原样** EOL 还原。
  2. **判据的扫描面写死在真 `src` 上**：注入改副本、扫描真文件 ⇒ 判据照旧绿。
     修法：本门禁已有 `PROD_SRC_DIR` 注入口，探针把**整棵 src 树**拷进临时目录。
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
SHELL = "frontend/src/composables/useChatOrchestrator.ts"
PANEL = "frontend/src/components/ChatPanel/index.vue"

FILES = [REPLIES, SHORTCUTS, SHELL, PANEL]

#: 四份被测源文件在**副本 src 根**下的相对路径
UNDER_SRC = {
    REPLIES: "composables/chat/replies/index.ts",
    SHORTCUTS: "composables/chat/useAgentShortcuts.ts",
    SHELL: "composables/useChatOrchestrator.ts",
    PANEL: "components/ChatPanel/index.vue",
}

DISMISS_FN = "  function dismissPendingSkill(): void {\n    ctx.clearPendingSkill()\n  }\n"

# 每处锚点都必须**恰好命中 1 次**（命中 0 次 = 注入本身失败，不是"没抓到"）
INJECTIONS = [
    dict(
        id="M1", file=SHORTCUTS, expect=["L10"],
        why="chip 的数据源被改名 ⇒ L10 必须报「没有 pendingSkillCard」",
        old="  const pendingSkillCard = computed<PendingSkillChip | null>(() => {",
        new="  const renamedPendingSkillCard = computed<PendingSkillChip | null>(() => {",
    ),
    dict(
        id="M2", file=SHORTCUTS, expect=["L7", "L10"],
        why="dismissPendingSkill 变成空壳（不真清点名）⇒ "
            "L7 少一处调用点、L10 的「真的清了」那一腿也断",
        old=DISMISS_FN,
        new="  function dismissPendingSkill(): void {\n  }\n",
    ),
    dict(
        id="M3", file=SHELL, expect=["L10"],
        why="壳的 return 里把两个键删掉（解构行仍在）⇒ "
            "L10 必须报「组件解构到 undefined」——这正是它从「标识符出现过」收紧成"
            "「在 return 对象里」的原因：旧写法此处会假绿",
        old="    pendingSkillCard,\n    dismissPendingSkill,\n  }\n}",
        new="  }\n}",
    ),
    dict(
        id="M4", file=SHORTCUTS, expect=["L7", "L10"],
        why="dismiss 改写成**一行式箭头** ⇒ L7 的 `!/=>/` 过滤把它排除（少一处）、"
            "L10 也不认 `function` 形态。这条注入正面证明「为什么必须写花括号体」",
        old=DISMISS_FN,
        new="  const dismissPendingSkill = (): void => ctx.clearPendingSkill()\n",
    ),
    dict(
        id="M5", file=PANEL, expect=["L10"],
        why="chip 的 v-if 改成 false（元素还在、但永不渲染）",
        old='          <div v-if="pendingSkillCard" class="pending-skill-chip">',
        new='          <div v-if="false" class="pending-skill-chip">',
    ),
    dict(
        id="M6", file=PANEL, expect=["L10"],
        why="× 没绑到撤销口 ⇒「看得见但撤不掉」",
        old='              @click="dismissPendingSkill()"',
        new='              @click="() => {}"',
    ),
    dict(
        id="M7", file=SHORTCUTS, expect=["L7"],
        why="多插一个**无条件**的 ctx.clearPendingSkill() ⇒ 退回「一次性」语义，"
            "L7 必须报「多一处」（4 处）。注意 L10 不该红：它的切片从 function 起算",
        old="  function dismissPendingSkill(): void {",
        new="  ctx.clearPendingSkill()\n  function dismissPendingSkill(): void {",
    ),
    dict(
        id="M8", file=SHORTCUTS, expect=["L10"],
        why="chip 不再回查技能目录（直接把 kebab-case 的 name 显示到界面上）",
        old="    const card = skillStore.skillsOfAgent(currentBackendAgent.value).find((c) => c.name === name)",
        new="    const card = undefined",
    ),
]

#: 对照：只动注释，必须**一条都不红**（否则「红」是台架噪声而非注入命中）
CONTROL = dict(
    id="C1", file=SHELL,
    why="只改一行注释（把「25 键 → 27 键」这句改成别的措辞）",
    old="    // 点名可见 chip（第 250 轮：把",
    new="    // 【对照】只动注释 第 250 轮：把",
)

L_IDS = [f"L{i}" for i in range(1, 11)]


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
    env["PROD_SHELL"] = os.path.join(src_root, "composables/useChatOrchestrator.ts")
    env["PROD_PANEL"] = os.path.join(src_root, "components/ChatPanel/index.vue")
    p = subprocess.run([NODE, GATE], cwd=FRONT, env=env,
                       capture_output=True, text=True, encoding="utf-8", errors="replace")
    out = (p.stdout or "") + (p.stderr or "")
    if not out.strip():
        return None, out            # 空输出 = 台架坏了，与「没红」分开报
    failed = set(re.findall(r"^FAIL\s+(L\d+)\b", out, re.M))
    passed = set(re.findall(r"^PASS\s+(L\d+)\b", out, re.M))
    return (failed, passed), out


def main() -> int:
    tmp = tempfile.mkdtemp(prefix="probe250_")
    src_root = os.path.join(tmp, "src")
    shutil.copytree(os.path.join(FRONT, "src"), src_root)

    sha_before = {rel: sha(os.path.join(ROOT, rel)) for rel in FILES}
    pristine = {}
    for rel in FILES:
        pristine[rel] = read_norm(os.path.join(src_root, UNDER_SRC[rel]))
        tag = "CRLF" if pristine[rel][1] == "\r\n" else "LF"
        print(f"  {rel}\n      EOL={tag}  sha={sha_before[rel][:16]}  {len(pristine[rel][0])} chars")
    print(f"pristine 副本树 {src_root}")

    def restore_all():
        for r in FILES:
            write_eol(os.path.join(src_root, UNDER_SRC[r]), pristine[r][0], pristine[r][1])

    try:
        # ---- 基线（未注入）必须全绿，且 10 条 L 都在场 ----
        res, out = run_gate(src_root)
        if res is None:
            print("✗ 基线：门禁**零输出** ⇒ 台架本身坏了（不是判据的问题）")
            return 2
        base_fail, base_pass = res
        print(f"\n基线：PASS(L 组)={len(base_pass)}  FAIL(L 组)={len(base_fail)}")
        if base_fail:
            print(f"✗ 基线不是全绿，无法归因：{sorted(base_fail)}")
            print(out[-2500:])
            return 2
        missing = set(L_IDS) - base_pass
        if missing:
            print(f"✗ 基线里缺少这些 L 判据：{sorted(missing)} ⇒ 判据集不自洽")
            return 2
        print(f"基线 L 判据齐备：{','.join(sorted(base_pass, key=lambda s: int(s[1:])))}")

        # ---- 对照：只动注释，必须一条都不红 ----
        restore_all()
        path = os.path.join(src_root, UNDER_SRC[CONTROL["file"]])
        text = pristine[CONTROL["file"]][0]
        n = text.count(CONTROL["old"])
        control_bad = 0
        if n != 1:
            print(f"\n✗ 对照注入本身失败：锚点命中 {n} 次（须 1）")
            control_bad = 1
        else:
            write_eol(path, text.replace(CONTROL["old"], CONTROL["new"]),
                      pristine[CONTROL["file"]][1])
            res, out = run_gate(src_root)
            if res is None:
                print("\n✗ 对照：台架零输出")
                control_bad = 1
            else:
                got, _ = res
                ok = len(got) == 0
                if not ok:
                    control_bad = 1
                print(f"\n对照 {CONTROL['id']} 只动注释 ⇒ 实测红={sorted(got) or '(无)'}  "
                      f"{'✓ 全绿' if ok else '✗ 注释改动也判红 ⇒ 判据在扫注释（假红源）'}")

        # ---- 逐条注入（每条都从 pristine 现算，不叠加）----
        print("\n" + "=" * 96)
        print(f"{'#':5s}{'预期红':22s}{'实测红':22s}判定")
        print("=" * 96)
        bad = control_bad
        for inj in INJECTIONS:
            restore_all()
            path = os.path.join(src_root, UNDER_SRC[inj["file"]])
            text = pristine[inj["file"]][0]
            n = text.count(inj["old"])
            if n != 1:
                # ④ 注入本身失败 —— 与「注入没抓到」分开报
                print(f"{inj['id']:5s}{'':22s}{'':22s}✗ 注入本身失败：锚点命中 {n} 次（须 1）")
                bad += 1
                continue
            write_eol(path, text.replace(inj["old"], inj["new"]), pristine[inj["file"]][1])

            res, out = run_gate(src_root)
            if res is None:
                print(f"{inj['id']:5s}{'':22s}{'':22s}✗ 台架零输出（基础设施故障，非判据结论）")
                bad += 1
                continue
            got_fail, _ = res
            exp = set(inj["expect"])
            ok = got_fail == exp
            if not ok:
                bad += 1
            print(f"{inj['id']:5s}{','.join(sorted(exp)):22s}"
                  f"{','.join(sorted(got_fail)) or '(无)':22s}"
                  f"{'✓ 命中且只命中声明的' if ok else '✗ 不符'}")
            if not ok:
                print(f"       ↳ {inj['why']}")
                extra, miss = got_fail - exp, exp - got_fail
                if miss:
                    print(f"         声明了但没红：{sorted(miss)} ⇒ 该判据没在守这件事")
                if extra:
                    print(f"         没声明但红了：{sorted(extra)} ⇒ 声明不全（判据之间有耦合）")
    finally:
        restore_all()

    sha_after = {rel: sha(os.path.join(ROOT, rel)) for rel in FILES}
    print("\n" + "=" * 96)
    touched = [rel for rel in FILES if sha_before[rel] != sha_after[rel]]
    print("真仓源码核对：" + ("✗ 被改动 " + str(touched) if touched
                           else f"✓ 四份源文件 sha256 未变（全程只动临时副本树）"))
    shutil.rmtree(tmp, ignore_errors=True)
    total = len(INJECTIONS) + 1
    print(f"结果：{'✓ ' + str(total) + ' 条（1 对照 + ' + str(len(INJECTIONS)) +
          ' 注入）全部符合声明' if bad == 0 else f'✗ {bad} 条异常'}")
    return 1 if bad else 0


if __name__ == "__main__":
    raise SystemExit(main())
