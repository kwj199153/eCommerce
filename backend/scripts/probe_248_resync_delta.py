# -*- coding: utf-8 -*-
"""探针：逐列对账「演示技能库行 vs 规格表」，看清楚 `--resync` 到底会改哪一列。

★ 为什么先探再跑：`resync_demo_skills()` 的 docstring 明确写着它会覆盖
  `enabled_agents`（**用户能在界面上勾的列**），"老板在演示里勾掉的 Agent 会在
  重启后静默长回来 —— 比不生效更糟"。所以跑之前必须知道：这次的 5 条改动里，
  有几条是 `enabled_agents` 驱动的。
★ 必须在 `backend/` 下跑（`.env` 按 CWD 解析）。
"""
import asyncio
import json
import os
import sys

os.chdir(r"D:\ai\eCommerce\backend")
sys.path.insert(0, r"D:\ai\eCommerce\backend")

from sqlalchemy import select
from core.database import async_session_factory
from modules.skills.db_model import SkillRecord
from modules.skills.seed import DEMO_SKILLS, demo_account_row


async def main():
    spec = {s["name"]: s for s in DEMO_SKILLS}
    acct = await demo_account_row()
    if acct is None:
        print("RESULT_JSON: " + json.dumps({"error": "演示账号不存在"}))
        return

    rows = []
    async with async_session_factory() as session:
        db_rows = (
            await session.execute(
                select(SkillRecord).where(SkillRecord.account_id == acct.id)
            )
        ).scalars().all()
        for r in db_rows:
            rows.append(
                {
                    "name": r.name,
                    "enabled_agents": list(r.enabled_agents or []),
                    "tools": [str(t) for t in (r.tools or [])],
                    "as_shortcut": bool(r.as_shortcut),
                    "icon_empty": not (r.icon or "").strip(),
                }
            )

    detail = []
    for r in sorted(rows, key=lambda x: x["name"]):
        s = spec.get(r["name"])
        if s is None:
            detail.append({"name": r["name"], "in_spec": False})
            continue
        want_agents = list(s["agents"])
        want_tools = [str(t) for t in (s.get("tools") or [])]
        want_short = bool(s.get("as_shortcut", True))
        d = {}
        if r["enabled_agents"] != want_agents:
            d["enabled_agents"] = {"db": r["enabled_agents"], "spec": want_agents}
        if r["tools"] != want_tools:
            d["tools"] = {"db": r["tools"], "spec": want_tools}
        if r["as_shortcut"] != want_short:
            d["as_shortcut"] = {"db": r["as_shortcut"], "spec": want_short}
        if r["icon_empty"]:
            d["icon"] = "空（resync 会出网补）"
        if d:
            detail.append({"name": r["name"], "diff": d})

    print(
        "RESULT_JSON: "
        + json.dumps(
            {
                "演示行数": len(rows),
                "规格表条数": len(spec),
                "有差异的行数": len(detail),
                "驱动列直方图": {
                    k: sum(1 for x in detail if "diff" in x and k in x["diff"])
                    for k in ("enabled_agents", "tools", "as_shortcut", "icon")
                },
                "明细": detail,
            },
            ensure_ascii=False,
            indent=2,
        )
    )


if __name__ == "__main__":
    asyncio.run(main())
