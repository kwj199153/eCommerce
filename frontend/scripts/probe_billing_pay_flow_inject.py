#!/usr/bin/env python
"""扫码支付前端门禁的反向注入台架（第 270 轮）。

    python scripts/probe_billing_pay_flow_inject.py

★ 为什么必须有它：`scripts/check-billing-pay-flow.cjs` 的全部力度都压在
  "正则能不能在源码里找到 / 找不到某个形态"上。没有反向注入，一个把锚点写错
  （或写成恒真）的门禁**看起来完全一样** —— 都是满屏 PASS。

★ 为什么走**副本树**（而不改真文件）：
  `check-billing-pay-flow.cjs` 读 `BILLING_PAY_SRC_ROOT` 指向的树。改真文件再复跑：
    ① 中途崩溃会留下一份被改坏的源码（本仓踩过：注入态没还原 ⇒ 后续全乱）；
    ② 与"真实改动"混在 `git status` 里，分不清谁是谁。
  副本树把两件事都消掉，也让台架可以无人值守地跑。

★ 判据用的是**精确失败集**（不是"红了就算赢"）：
  "整体红了"可能只是碰巧炸了别的断言。这里要求转红的那一组**恰好等于**
  预期的那几条 —— 多一条少一条都算失败。注释掉这条要求，台架就会退化成
  "只要有 FAIL 就欢呼"，那它自己也需要被反向注入了。

★ 踩过的两个坑（都写进断言，防复发）：
  1. `Path.write_text()` 在 Windows 上把 `\\n` 翻成 `\\r\\n` ⇒ 下一轮 `functionBody()`
     按 `lines[i] === '}'` 找不到行首顶格的 `}` ⇒ 三条 A4 **假红**。
     本仓铁律：写盘一律走**二进制**。
  2. 锚点必须**唯一**且**指向被测判据真正读的那个东西**：
     · `await onPaySucceeded()\\n      return` 在文件里有 2 处（409 分支 + 轮询分支）
       ⇒ 台架直接报"锚点命中 2 次"并中止（不许猜）；
     · 改 `v-if="payQr"` 不会让 B5 红 —— B5 读的是 `:src="payQr"`。
       "改了但判据不红"如果不追因，就会被误读成"判据失效"。
"""

from __future__ import annotations

import os
import pathlib
import shutil
import subprocess
import sys
import tempfile

FRONTEND = pathlib.Path(__file__).resolve().parents[1]
CHECKER = FRONTEND / "scripts" / "check-billing-pay-flow.cjs"
# ★ 默认用 PATH 上的 node；受管 node 不能 spawn 自身，故只在需要时用环境变量指定。
NODE = os.environ.get("NODE_BIN") or "node"

API_REL = "src/api/billing.ts"
VIEW_REL = "src/views/Subscription.vue"


def run_checker(root: pathlib.Path) -> tuple[int, str]:
    env = dict(os.environ, BILLING_PAY_SRC_ROOT=str(root))
    p = subprocess.run(
        [NODE, str(CHECKER)], capture_output=True, text=True, env=env, cwd=str(FRONTEND)
    )
    return p.returncode, p.stdout + p.stderr


def read(p: pathlib.Path) -> str:
    """读源码并**归一化行尾为 LF**。

    ★ 为什么必须归一化（坑 3）：真仓里 `Subscription.vue` 是 **CRLF**、
      `api/billing.ts` 是 **LF** —— 同一个仓两种行尾并存。
      跨行的锚点（如 409 分支那两行）在 CRLF 文本里永远命中 0 次，
      台架会报"源码已变"，而源码根本没变（归因反向）。
      `check-billing-pay-flow.cjs` 的正则与 `indexOf` 对行尾不敏感
      ⇒ 归一化不改变门禁的判定结果，只是让锚点可比。
    """
    return p.read_bytes().decode("utf-8").replace("\r\n", "\n")


def write(p: pathlib.Path, text: str) -> None:
    """写盘。★ 必须二进制：`write_text` 在 Windows 上会把 `\\n` 翻成 `\\r\\n`（坑 1）。"""
    p.write_bytes(text.encode("utf-8"))


def must_replace(text: str, old: str, new: str, tag: str) -> str:
    n = text.count(old)
    if n != 1:
        print(f"  ✗ [{tag}] 锚点命中 {n} 次（期望 1）—— 源码已变，台架需更新")
        sys.exit(2)
    return text.replace(old, new, 1)


def failed_names(out: str) -> list[str]:
    return [l[len("FAIL  ") :].split("  |  ")[0].strip() for l in out.splitlines() if l.startswith("FAIL  ")]


B_PENDING = 'B2/B3/B4 未付款分支：把二维码交给用户，且不许说"成功 / 已切换"'
B1 = "B1 charged 分支排在 requires_confirmation 之前（演示身份要走同步分支）"
B5 = "B5 模板里二维码真的被渲染（拿到数据 ≠ 画出来）"
B6 = 'B6 取码撞 409 被当作"已支付成功"处理（不是"二维码加载失败"）'
B7 = "B7 定时器在组件卸载时被清理（否则离开页面后还在每 3 秒打后端）"
A2 = "A2 changePlan 返回类型声明了 payment（二维码从这条通道下来）"
A3 = "A3 PendingPayment 契约存在且含 expires_at（倒计时的唯一来源）"

#: (标签, 目标文件, 旧文本, 新文本, 预期转红的断言名集合)
CASES: list[tuple[str, str, str, str, set[str]]] = [
    (
        "未付款分支里写成功提示",
        VIEW_REL,
        "      await openPayModal(res.payment)",
        "      message.success('已切换为年付套餐')\n      await openPayModal(res.payment)",
        {B_PENDING},
    ),
    (
        "未付款分支不把二维码交给用户",
        VIEW_REL,
        "      await openPayModal(res.payment)",
        "      // 忘了把二维码交给用户",
        {B_PENDING},
    ),
    (
        "锚点被改名（不许静默放行）",
        VIEW_REL,
        "res.requires_confirmation && res.payment",
        "res.needPay && res.payment",
        {B1, B_PENDING},
    ),
    (
        "模板不再渲染二维码",
        VIEW_REL,
        ':src="payQr"',
        ':src="qrFallback"',
        {B5},
    ),
    (
        "409 不再被当成支付成功",
        VIEW_REL,
        "    if (err?.response?.status === 409) {\n      await onPaySucceeded()",
        "    if (err?.response?.status === 409) {\n      payQrFailed.value = '该账单已完成支付'",
        {B6},
    ),
    (
        "卸载时不清理定时器",
        VIEW_REL,
        "onUnmounted(stopPayPolling)",
        "// onUnmounted(stopPayPolling)",
        {B7},
    ),
    (
        "changePlan 丢掉 silentError",
        API_REL,
        "    { silentError: true }\n  )\n}",
        "    undefined\n  )\n}",
        {"A4 changePlan 声明了 silentError（否则同一个失败\"拦截器弹一条 + 调用点再弹一条\"）"},
    ),
    (
        "返回类型丢掉 payment 字段",
        API_REL,
        "  payment?: PendingPayment | null\n",
        "",
        {A2},
    ),
    (
        "契约丢掉 expires_at",
        API_REL,
        "  expires_at: string | null\n",
        "",
        {A3},
    ),
]


def main() -> None:
    work = pathlib.Path(tempfile.mkdtemp(prefix="billing_pay_inject_"))
    try:
        for rel in (API_REL, VIEW_REL):
            dst = work / rel
            dst.parent.mkdir(parents=True, exist_ok=True)
            write(dst, read(FRONTEND / rel))

        baseline = {rel: read(work / rel) for rel in (API_REL, VIEW_REL)}

        code, out = run_checker(work)
        if code != 0:
            print("✗ 基准态就没过 —— 先修门禁或源码，再谈反向注入")
            print(out)
            sys.exit(2)
        print("✓ 基准态通过（后续每组注入都必须让它转红）\n")

        ok = 0
        for tag, rel, old, new, expect in CASES:
            # 每轮从基准态重新出发（注入之间不叠加，否则归因不清）
            for r, body in baseline.items():
                write(work / r, body)

            target = work / rel
            write(target, must_replace(read(target), old, new, tag))

            code, out = run_checker(work)
            hits = set(failed_names(out))

            # ★ 精确失败集：多一条（炸了别的）或没有（判据失明）都不算通过
            if code != 0 and hits == expect:
                ok += 1
                print(f"✓ {tag}  ⇒ 恰好转红：{sorted(expect)[0][:52]}…")
            elif code == 0:
                print(f"✗ {tag}  ⇒ **门禁仍是绿的**（这条注入没被任何断言咬住）")
            elif not hits:
                print(f"✗ {tag}  ⇒ 红了但没有 FAIL 行（门禁自身崩了？）")
            else:
                extra = hits - expect
                missing = expect - hits
                print(f"✗ {tag}  ⇒ 失败集不符")
                if missing:
                    print(f"      少了预期：{sorted(missing)}")
                if extra:
                    print(f"      多了意外：{sorted(extra)}")

        print(f"\n---- 反向注入 {ok}/{len(CASES)} 通过 ----")
        if ok != len(CASES):
            sys.exit(1)
    finally:
        shutil.rmtree(work, ignore_errors=True)


if __name__ == "__main__":
    main()
