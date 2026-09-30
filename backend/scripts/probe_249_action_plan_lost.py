"""探针 · 「行动计划」永远拿不到 —— 点名跨轮丢失的 A/B 取证（第 249 轮）

老板报障（原话）：
    点了「行动计划」卡 → Agent 反问「基于哪份复盘（周报/月度复盘/广告效果复盘）」
    → 答「基于月报」→ **吐出来的是月度复盘卡**
    → 「是否有bug，永远无法获得行动计划」

本探针把「永远」这两个字钉成事实，而不是推断。三个读数：

    A. 点名在轮内是否有效（`is_skill_requested()` 的作用域语义）
    B. 第二轮「基于月报」在没有点名时被分类成什么意图（关键词短路）
    C. A/B 对照：第二轮带 / 不带点名，`display_type` 分别是什么

★ 必须在 `backend/` 下跑（`.env` 是相对 CWD 找的；跑到别处会静默退回默认值）。
★ 选 `_run_one` 那条路不需要 LLM（纯 service 直连）——
  所以「不带点名 ⇒ 月报卡」这个结论**与 LLM 可用性无关**，是确定性的。
"""

from __future__ import annotations

import asyncio
import os
import sys

os.chdir(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.path.insert(0, os.getcwd())

from ai_infra.skills import (  # noqa: E402
    bind_requested_skill,
    is_skill_requested,
)

SHOP = "store_c3529ab1"          # 老板截图里那张月报卡的店铺
SKILL = "review-action-plan"     # 老板点的那张卡
ANSWER = "基于月报"              # 老板对追问的回答


async def main() -> int:
    from modules.review_analyst.agent import get_review_analyst_agent

    agent = get_review_analyst_agent()
    print("=" * 78)
    print("探针 249 · 点名跨轮丢失 A/B")
    print("=" * 78)

    # ---- A. 点名的作用域语义（这是整件事的机制底座）----
    #
    # ★ 这里**刻意不读**「原始技能名」那个读取器：全仓只有两处允许读它
    #   （机制层自身 + 技能段渲染点），见
    #   `tests/test_skill_shortcut_compat.py::RAW_JUDGMENT_ALLOWED`。
    #   探针要诊断的也不是"名字是什么"，而是"有没有点名" ⇒ 用 `is_skill_requested()`。
    #   （那个白名单是**刻意收窄**的，不该为诊断脚本加第三条 —— 本门禁连注释里的
    #    字面量都会命中，这正是"同一判定不许有第二份实现"的执行方式。）
    print("\n[A] `is_skill_requested()` 的作用域语义")
    print(f"    作用域外            : {is_skill_requested()!r}")
    async with bind_requested_skill(SKILL):
        print(f"    作用域内            : {is_skill_requested()!r}")
    print(f"    退出作用域后        : {is_skill_requested()!r}")
    print("    ⇒ 点名是**每次请求各自绑定的**，不落任何会话状态 ⇒ 第二轮无人绑 = 无点名")

    # ---- B. 第二轮那句回答会被分类成什么 ----
    print("\n[B] `_classify_intent(%r)`" % ANSWER)
    intent = await agent._classify_intent(ANSWER)
    print(f"    → {intent!r}")
    print("    ⇒ 命中关键词表（'月报' → monthly_review）⇒ 走 `_run_one` 直连 service，")
    print("      而 `_run_one` **不构造 system prompt** ⇒ 用户点的那条技能一次都渲染不到")

    # ---- C. A/B 对照：带上 / 不带点名 ----
    print("\n[C] A/B 对照（同一句话、同一店铺、同一会话）")
    print("    不带点名那一档走 `_run_one` 直连 service，**不需要 LLM** ⇒ 与 LLM 可用性无关")

    without = await agent.invoke(ANSWER, session_id="probe249-sess", shop_id=SHOP)
    print(f"    轮2 不带点名（旧前端行为）: display_type={without.display_type!r}  "
          f"reply[:34]={without.reply[:34]!r}  degraded={without.degraded}"
          f"{' reason=' + without.degraded_reason if without.degraded_reason else ''}")

    async with bind_requested_skill(SKILL):
        with_skill = await agent.invoke(ANSWER, session_id="probe249-sess", shop_id=SHOP)
    print(f"    轮2 带点名（本轮修法）    : display_type={with_skill.display_type!r}  "
          f"reply[:34]={with_skill.reply[:34]!r}  degraded={with_skill.degraded}"
          f"{' reason=' + with_skill.degraded_reason if with_skill.degraded_reason else ''}")

    # ---- 判定 ----
    # ★ 判据不许写成 `display_type == 'monthly_review'` —— 月报那条直连走 `_wrap`，
    #   给的是**报告型** display_type（实测 `review_report`）。首跑我就把卡名判错了 ⇒
    #   探针报「未复现」，而 reply 其实与老板截图**逐字相同**。
    #   判据取「回复内容是不是那份月报」这一客观事实，不猜类型名。
    MONTHLY_MARK = "近 30 天月 GMV"
    print("\n" + "=" * 78)
    lost = MONTHLY_MARK in without.reply and without.display_type != "text"
    kept = MONTHLY_MARK in with_skill.reply or with_skill.display_type == "text"
    print(f"[结论] 轮2 不带点名 ⇒ 被关键词短路成月报卡？  {'是 ⇒ 复现' if lost else '否 ⇒ 未复现'}")
    print(f"[结论] 轮2 带点名   ⇒ 仍被短路成月报卡？      "
          f"{'是 ⇒ 修法无效' if not kept else '否 ⇒ 已让路给工具环路（不再被短路吃掉）'}")
    print("=" * 78)
    return 0 if lost else 1


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))
