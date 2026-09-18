"""
多轮记忆端到端探针（第 131 轮）

★ 为什么单独一个**子进程**脚本，而不是直接写在 pytest 用例里：

  本机实测，`langgraph` 的 `AsyncPostgresSaver` 走 psycopg3 异步 ⇒ **不能用
  Windows 的默认 ProactorEventLoop**，否则连接池永远拿不到连接：

      Psycopg cannot use the 'ProactorEventLoop' to run in async mode.
      ... psycopg_pool.PoolTimeout: couldn't get a connection after 30.00 sec

  而 `backend/pytest.ini` 把事件循环 scope 设成了 **session**（整个会话共用
  一个循环）⇒ 在用例里改 `event_loop_policy` 等于**改全局**，会波及全部测试。
  所以这里把「设成 SelectorEventLoopPolicy + 真跑 checkpointer」整体关进子进程，
  对测试会话零副作用。

★ 为什么不用真实 LLM：本探针要证明的是 **checkpointer 是否真按 thread_id 累积历史**，
  与模型能力无关。打桩掉 LLM 节点 ⇒ CI 里稳定复现、零花费、零配额消耗。

★ 第 131 轮 item 3 起，本探针覆盖 **5 条**判据（`out["checks"]`）：
  ① 同会话同身份：第二轮看得见第一轮（记忆真的在工作）；
  ② 换会话：看不见（thread 隔离）；
  ②b 同会话**换用户**：看不见（**按人隔离**，item 3 的核心）；
  ②c 只有会话、没有身份：不留记忆（不得落进"公共"thread）；
  ③ 无会话：不留记忆。

用法（必须 cwd = backend，`.env` 是相对 CWD 解析的）::

    python -X utf8 scripts/check_multi_turn_memory.py

输出最后一行固定为 `RESULT_JSON: {...}`，由 `tests/test_agent_session_memory.py` 解析断言。
"""

import asyncio
import json
import os
import sys
import traceback
import uuid

BACKEND = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))

# ★ 顺序不能变：先切事件循环策略，再 import 任何会建循环的东西。
if sys.platform == "win32":
    asyncio.set_event_loop_policy(asyncio.WindowsSelectorEventLoopPolicy())

os.chdir(BACKEND)
if BACKEND not in sys.path:
    sys.path.insert(0, BACKEND)


def _build_echo_agent():
    """最小 BaseAgent 子类：只换三个节点，图结构与鉴权链保持原样。"""
    from langchain_core.messages import AIMessage

    from ai_infra.base_agent import BaseAgent

    class _Echo(BaseAgent):
        ENABLE_LLM = False

        async def _llm_call_node(self, state):
            return {"messages": [AIMessage(content=f"ack#{len(state['messages'])}")]}

        def _should_continue(self, state):
            return "respond"

        async def _respond_node(self, state):
            return {}

    return _Echo


async def _main() -> dict:
    from langchain_core.messages import HumanMessage

    from core.checkpoint import close_checkpoint, setup_checkpoint

    out = {"ok": False, "checks": {}}
    cp = await setup_checkpoint()
    out["checks"]["checkpointer"] = type(cp).__name__

    sess = f"probe-mem-{uuid.uuid4().hex[:10]}"
    # 两个身份：item 3 的判据是「同一 session_id 换用户 ⇒ 读不到别人历史」
    USER_A = f"user-a-{uuid.uuid4().hex[:6]}"
    USER_B = f"user-b-{uuid.uuid4().hex[:6]}"
    agent = _build_echo_agent()(agent_name="memprobe", checkpoint_ns="memprobe")
    agent.attach_checkpointer(cp)

    # ① 同一会话 + 同一身份两轮：第二轮必须看得见第一轮
    await agent.run_session(
        {"messages": [HumanMessage(content="第一轮的暗号-ALPHA")]},
        session_id=sess,
        user_id=USER_A,
    )
    r2 = await agent.run_session(
        {"messages": [HumanMessage(content="第二轮的暗号-BETA")]},
        session_id=sess,
        user_id=USER_A,
    )
    humans = [m.content for m in r2["messages"] if isinstance(m, HumanMessage)]
    out["checks"]["turn2_sees_turn1"] = any("ALPHA" in c for c in humans)
    out["checks"]["turn2_human_count"] = len(humans)
    out["checks"]["turn2_raw"] = humans[:6]

    # ② 换一个会话：**不得**看见上面那段历史（不同 thread）
    other = await agent.run_session(
        {"messages": [HumanMessage(content="另一会话的暗号-OMEGA")]},
        session_id=f"{sess}-other",
        user_id=USER_A,
    )
    ohumans = [m.content for m in other["messages"] if isinstance(m, HumanMessage)]
    out["checks"]["other_session_isolated"] = not any("ALPHA" in c for c in ohumans)

    # ②b 同一会话、**换一个用户**：不得看见别人的历史（item 3 的核心判据）
    cross = await agent.run_session(
        {"messages": [HumanMessage(content="另一个用户的暗号-SIGMA")]},
        session_id=sess,
        user_id=USER_B,
    )
    chumans = [m.content for m in cross["messages"] if isinstance(m, HumanMessage)]
    out["checks"]["other_user_isolated"] = not any("ALPHA" in c for c in chumans)
    out["checks"]["other_user_human_count"] = len(chumans)

    # ②c 只有会话、**没有身份**：同样不留记忆（不得落进一个"公共"thread）
    await agent.run_session(
        {"messages": [HumanMessage(content="无身份暗号-MU")]}, session_id=sess
    )
    n2 = await agent.run_session(
        {"messages": [HumanMessage(content="无身份暗号-NU")]}, session_id=sess
    )
    nhumans = [m.content for m in n2["messages"] if isinstance(m, HumanMessage)]
    out["checks"]["no_identity_leaves_no_memory"] = not any("MU" in c for c in nhumans)

    # ③ 无会话两轮：互不可见（否则就是"拿默认 thread_id 兜底"= 跨用户串记忆）
    await agent.run_session({"messages": [HumanMessage(content="匿名暗号-GAMMA")]})
    a2 = await agent.run_session({"messages": [HumanMessage(content="匿名暗号-DELTA")]})
    ahumans = [m.content for m in a2["messages"] if isinstance(m, HumanMessage)]
    out["checks"]["no_session_leaves_no_memory"] = not any(
        "GAMMA" in c for c in ahumans
    )
    out["checks"]["anon_human_count"] = len(ahumans)

    out["ok"] = all(
        (
            out["checks"]["turn2_sees_turn1"],
            out["checks"]["other_session_isolated"],
            out["checks"]["no_session_leaves_no_memory"],
            out["checks"]["other_user_isolated"],
            out["checks"]["no_identity_leaves_no_memory"],
        )
    )

    # 收尾：清掉本探针造的行
    for tid in (
        f"memprobe:{USER_A}:{sess}",
        f"memprobe:{USER_B}:{sess}",
        f"memprobe:{USER_A}:{sess}-other",
        f"memprobe:{sess}",  # 旧口径的键：清一下，防历史残留
    ):
        try:
            await cp.adelete_thread(tid)
        except Exception:  # noqa: BLE001
            pass
    await close_checkpoint()
    return out


if __name__ == "__main__":
    try:
        res = asyncio.run(_main())
    except Exception as e:  # noqa: BLE001
        traceback.print_exc()
        res = {"ok": False, "error": f"{type(e).__name__}: {e}"}
    print("RESULT_JSON: " + json.dumps(res, ensure_ascii=False))
    sys.exit(0 if res.get("ok") else 2)
