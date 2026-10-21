"""注册后置钩子 —— **只提供机制，不含任何业务**（第 387 轮）

==============================================================================
为什么需要这一层（而不是直接在 `router.register()` 里调播种）
==============================================================================
`core/` 顶层**禁止** import `modules/`（`tests/test_core_layering.py`）。
而「注册完之后给他的账号建一家店」是业务，只能住在 `modules/onboarding`。

    router.register()（core）  ──需要──>  modules.onboarding.bootstrap_new_user

这条边方向是反的。于是把「注册后要做什么」抽成**注册表**：
core 定义机制与调用时机，组合根（`main.py`）注入具体函数。
这与 `core/bootstrap.py::seed_base_data(steps=...)` 是同一套思路
（那里也是 core 只做顺序/标签，业务步骤由组合根给出）。

==============================================================================
★★ 失败策略：**不许**让播种失败挡住注册
==============================================================================
用户已经建好了（`users` + `subscriptions` 已 commit）。因为他没拿到示例店铺
就把注册整体回滚，属于过度反应 —— 他连登录都不行了，而他根本不知道
"示例店铺"是什么。

但也不许静默：钩子的失败要**记日志 + 回给调用方一条 `ok: false`**，
让 `POST /auth/register` 的响应里能看出"店铺没建出来"，
而不是让用户面对一个空白的店铺列表去猜。归因信息必须留在响应里。
"""

from __future__ import annotations

import logging
from typing import Any, Awaitable, Callable, Dict, List

from sqlalchemy.ext.asyncio import AsyncSession

from core.identity.models import User

logger = logging.getLogger(__name__)

#: 钩子签名：拿到同一个 session 与刚建好的 user，返回一段可序列化的结果。
PostRegisterHook = Callable[[AsyncSession, User], Awaitable[Dict[str, Any]]]

_HOOKS: List[PostRegisterHook] = []


def register_post_register_hook(hook: PostRegisterHook) -> None:
    """装配期登记一个后置钩子（组合根专用，不要在业务代码里调）。"""
    if hook in _HOOKS:
        # 幂等：模块被重复 import（测试里的 reload / 多进程 fork）不该跑两遍
        return
    _HOOKS.append(hook)
    logger.debug("已登记注册后置钩子：%s", getattr(hook, "__module__", "?"))


def clear_post_register_hooks() -> None:
    """清空登记（仅测试用）。"""
    _HOOKS.clear()


def registered_hooks() -> List[PostRegisterHook]:
    """当前登记的钩子（只读副本；测试与探针用）。"""
    return list(_HOOKS)


async def run_post_register_hooks(db: AsyncSession, user: User) -> List[Dict[str, Any]]:
    """依次执行钩子，逐个兜住异常。

    Returns:
        每个钩子一条结果：成功是钩子自己的返回（含 `ok: True` 由本函数补上），
        失败是 `{"hook": <模块名>, "ok": False, "error": "hook_failed"}`。

    ★ 错误详情只进日志、不进响应：钩子的异常串里可能带 SQL / 路径 / 内部表名。
      响应里给一个稳定的标记，运维按 user id 去日志里对。
    """
    results: List[Dict[str, Any]] = []
    for hook in _HOOKS:
        name = getattr(hook, "__module__", "?")
        try:
            payload = await hook(db, user) or {}
            results.append({"hook": name, "ok": True, **payload})
        except Exception as exc:  # noqa: BLE001 —— 见文件头「失败策略」
            logger.exception("注册后置钩子失败 hook=%s user=%s: %s", name, user.id, exc)
            results.append({"hook": name, "ok": False, "error": "hook_failed"})
    return results
