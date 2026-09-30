# -*- coding: utf-8 -*-
"""盘点「差评」相关的**入口**：对话页快捷卡片栏到底有几张卡。

★ agent-scoped：skills 表是账号级的，但 `agent_ids` 决定它在哪个 Agent 的对话页出现。
"""
import asyncio
import logging
import os
import sys
from pathlib import Path

logging.getLogger("sqlalchemy.engine").setLevel(logging.WARNING)
logging.getLogger("sqlalchemy.pool").setLevel(logging.WARNING)

BACKEND_ROOT = str(Path(__file__).resolve().parent.parent)
if BACKEND_ROOT not in sys.path:
    sys.path.insert(0, BACKEND_ROOT)

os.environ.setdefault(
    "DATABASE_URL", "postgresql+asyncpg://kevin:123456@localhost:5432/postgres")

from sqlalchemy import text  # noqa: E402

from core.database import async_session_factory  # noqa: E402

OUT = Path(BACKEND_ROOT) / "out-probe-review-entries.txt"
lines = []


def p(s=""):
    lines.append(str(s))
    print(s, flush=True)


async def main():
    async with async_session_factory() as s:
        p("=== A. skills 表里名字含「差评」的技能 ===")
        rows = (await s.execute(text(
            "select id, name, as_shortcut, enabled_agents, enabled "
            "from skills where name ilike '%差评%' order by id"))).all()
        cols = (await s.execute(text(
            "select column_name from information_schema.columns "
            "where table_name='skills' order by ordinal_position"))).all()
        p(f"  表列: {[c[0] for c in cols]}")
        if not rows:
            p("  （无）")
        for r in rows:
            p(f"  id={r[0]} name={r[1]!r} is_shortcut={r[2]} agent_ids={r[3]} enabled={r[4]}")

        p()
        p("=== B. 每个 Agent 对话页会出现几张快捷卡片 ===")
        p("  ★ enabled_agents 存的是**中文 Agent 名**（如「智能客服」），不是英文 slug；")
        p("    按 '%customer%' 过滤会得到 0 条 ⇒ 误判成「清单为空」（本轮第一版就踩了）。")
        rows2 = (await s.execute(text(
            "select name, title, as_shortcut, enabled_agents from skills "
            "where enabled = true order by name"))).all()
        by_agent = {}
        no_owner = []
        for r in rows2:
            title = r[1] or r[0]
            agents = r[3] or []
            if not agents:
                no_owner.append(f"{r[0]} :: {title}")
                continue
            for a in agents:
                by_agent.setdefault(str(a), []).append(
                    ("[卡片]" if r[2] is not False else "[不设卡片]") + f" {title}")
        for a in sorted(by_agent):
            p(f"  {a}：{len(by_agent[a])} 条")
            for t in by_agent[a]:
                p(f"    {t}")
        if no_owner:
            p(f"  未绑定任何 Agent（enabled_agents 为空）{len(no_owner)} 条：")
            for t in no_owner:
                p(f"    {t}")

        p()
        p("=== C. 名字含「差评」的 Agent 工具 / tool registry ===")
        for t in ("tool_registry", "tools"):
            exists = (await s.execute(text(
                "select count(*) from information_schema.tables where table_name=:t"),
                {"t": t})).scalar()
            if not exists:
                continue
            rows3 = (await s.execute(text(
                f"select * from {t} limit 0"))).keys()
            p(f"  表 {t} 列: {list(rows3)}")

        p()
        p("=== D. 差评处置台账行数（资料库入口看的同一份数据）===")
        try:
            n = (await s.execute(text("select count(*) from review_dispositions"))).scalar()
            p(f"  review_dispositions = {n}")
        except Exception as e:  # noqa: BLE001
            p(f"  查询失败: {e}")

    OUT.write_text("\n".join(lines) + "\n", encoding="utf-8")


asyncio.run(main())
print("DONE ->", OUT)
