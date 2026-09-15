"""
数据库引导入口（CI / 部署 / 本地一键起库）

==============================================================================
★ 与 CI 的分工 —— 两条路径合起来 == 「应用首次启动后数据库应有的状态」
==============================================================================
    schema    由 `alembic upgrade head` 建
              → 保证**迁移脚本真的被执行**（这才是「迁移验证」，create_all 做不到）
    base data 由本脚本灌
              → 与 `main.py` lifespan 共用 `core/bootstrap.py`（唯一真源）

★ 为什么需要它（血泪证据）
    在此之前 CI 的后端 job **完全没有建库步骤**，而本地跑 pytest 是有数据的
    开发库 ⇒ 「本地全绿」推不出「CI 全绿」。实测（探针
    `.workbuddy/probes/project-audit-20260915/script-r51_ci_e2e.py`）：
    在「33 张表建好但零数据」的空库上跑全量 pytest，大面积 ERROR，首个根因
        ForeignKeyViolationError: subscriptions ... plan_id=1
          is not present in table "subscription_plans"
    ⇒ 不加这一步，CI 一上线就是红的（或者说：它从来就没绿过）。

用法（工作目录 = backend/）
    python scripts/bootstrap_db.py            # 只灌基础数据（schema 已由 alembic 建好）
    python scripts/bootstrap_db.py --schema   # 顺带跑 alembic upgrade head（本地一键起库）

退出码
    0 = 成功
    1 = 参数错误 / 迁移失败
    2 = 订阅套餐（subscription_plans）未就绪 —— 这是**已知致命**项：
        注册与订阅链路的 plan_id 外键会直接失败，必须让 CI 立刻红，
        而不是等到 pytest 报一堆看不懂的外键错误。
"""

import argparse
import asyncio
import subprocess
import sys
from pathlib import Path

BACKEND_DIR = Path(__file__).resolve().parent.parent
if str(BACKEND_DIR) not in sys.path:
    sys.path.insert(0, str(BACKEND_DIR))


def _run_alembic_upgrade_head() -> int:
    """在 backend/ 目录下跑 `python -m alembic upgrade head`。"""
    print("[bootstrap] alembic upgrade head ...", flush=True)
    p = subprocess.run(
        [sys.executable, "-m", "alembic", "upgrade", "head"],
        cwd=str(BACKEND_DIR),
    )
    return p.returncode


async def _seed() -> dict:
    from core.bootstrap import seed_base_data
    from core.database import close_db

    try:
        return await seed_base_data()
    finally:
        # 释放连接池，避免脚本退出时残留连接（CI 上会让容器停不干净）
        try:
            await close_db()
        except Exception:  # noqa: BLE001
            pass


def main() -> int:
    # ★ 统一 stdout 编码：本地是 Windows 控制台（默认 cp936），
    #   直接 print 中文会 UnicodeEncodeError；CI 是 Linux(UTF-8)。
    try:
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
        sys.stderr.reconfigure(encoding="utf-8", errors="replace")
    except Exception:  # noqa: BLE001
        pass

    ap = argparse.ArgumentParser(description="数据库引导：建 schema（可选）+ 灌基础数据")
    ap.add_argument(
        "--schema", action="store_true",
        help="先跑 alembic upgrade head 再灌数据（本地一键起库用；CI 里分开跑，便于定位失败）",
    )
    args = ap.parse_args()

    if args.schema:
        rc = _run_alembic_upgrade_head()
        if rc != 0:
            print(f"[bootstrap] XX alembic upgrade head 失败 exit={rc}", flush=True)
            return 1

    result = asyncio.run(_seed())
    print(f"[bootstrap] seed 结果: {result}", flush=True)

    # ★ 已知致命项：套餐缺失 → 注册/订阅的外键必然失败
    if result.get("plans", 0) == 0:
        print(
            "[bootstrap] XX subscription_plans 未就绪 —— 注册/订阅链路会因 "
            "plan_id 外键失败，请检查上方告警原因",
            flush=True,
        )
        return 2

    print("[bootstrap] OK 数据库引导完成", flush=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
