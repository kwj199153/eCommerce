"""会话持久化模块（决策层 B：跨会话记忆）门面包。

★ 门面契约（第 140 轮 T-684 门禁钉住）：
  1. 跨模块引用**只允许** `from modules.conversation import <name>`；
     `from modules.conversation.<子模块> import ...` 一律禁止（那是伸手进包内部）。
  2. `<name>` 必须在下面的 `__all__` 里 —— `__all__` 就是**本包允许被
     其它 `modules/*` 取用**的名字全集（新增出口必须同步扩它）。
  3. `__all__` 里的名字**不得是子模块**（防「re-export 一个模块」把门禁架空）。

★ 为什么这不只是「re-export 一个 service 模块」：把函数名显式列出来，
  契约就看得见 —— 消费者依赖的是这几个**动作**（取、读、建、追加，
  以及第 145 轮批 C1 新增的 hydrate/persist），而不是「整个 service 模块」
  这种模糊承诺。service 内部重构时，只要这些名字还在，消费者不受影响。
"""
from modules.conversation.service import (
    active_owner_ids,
    append_message,
    create_conversation,
    get_owned_conversation,
    history_of,
    recent_messages_of_owner,
)
from modules.conversation.state_store import (
    hydrate_state,
    persist_state,
)

__all__ = [
    "append_message",
    # 第 149 轮批 C2-4：长期记忆夜间整理的两个**只读**原语
    # （跨会话取消息 / 取最近活跃的人）。它们是本包对外暴露的
    # "读口"，而不是让消费方自己去查 conversation 的表 ——
    # 后者会让归属口径出现第二份实现。
    "recent_messages_of_owner",
    "active_owner_ids",
    "create_conversation",
    "get_owned_conversation",
    "history_of",
    # 第 145 轮批 C1：Agent 内部槽位（指代 / 多轮补齐）的读写
    "hydrate_state",
    "persist_state",
]
