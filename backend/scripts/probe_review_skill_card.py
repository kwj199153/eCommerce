# -*- coding: utf-8 -*-
"""读取「差评处理」技能卡正文 —— 判断它与对话框的功能栏按钮是不是同一件事。

★ 中文 filter 必须走参数绑定（放在 SQL 字面量里会被 shell/git-bash 编码搞坏）。
"""
import asyncio
import json
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

OUT = Path(BACKEND_ROOT) / "out-probe-review-skill.txt"
lines = []


def p(s=""):
    lines.append(str(s))
    print(s, flush=True)


async def main():
    async with async_session_factory() as s:
        rows = (await s.execute(
            text("select id, name, title, description, content, tools, enabled_agents,"
                 " enabled, as_shortcut, visibility from skills"
                 " where coalesce(title, '') like :kw order by id"),
            {"kw": "%差评%"},
        )).all()
        if not rows:
            p("!! 没查到 title 含「差评」的技能 —— 清单为空还是 filter 写错，须区分")
        for r in rows:
            p("=" * 70)
            p(f"id            = {r[0]}")
            p(f"name          = {r[1]}")
            p(f"title         = {r[2]}")
            p(f"description   = {r[3]}")
            p(f"enabled_agents= {r[6]}")
            p(f"enabled       = {r[7]}   as_shortcut = {r[8]}   visibility = {r[9]}")
            tools = r[5]
            if isinstance(tools, str):
                try:
                    tools = json.loads(tools)
                except Exception:  # noqa: BLE001
                    pass
            p(f"tools         = {tools}")
            p("--- content ---")
            p(r[4])
            p("--- end content ---")

        p()
        p("=== 附：customer_service tools.py 里登记的工具名（供对照 skills.tools）===")
        try:
            import importlib

            mod = importlib.import_module("modules.customer_service.tools")
            names = sorted(
                n for n in dir(mod)
                if callable(getattr(mod, n)) and not n.startswith("_")
                and getattr(getattr(mod, n), "__module__", "") == mod.__name__
            )
            for n in names:
                p(f"  {n}")
        except Exception as e:  # noqa: BLE001
            p(f"  （反射失败：{e}）")

    OUT.write_text("\n".join(lines) + "\n", encoding="utf-8")


asyncio.run(main())
print("DONE ->", OUT)
