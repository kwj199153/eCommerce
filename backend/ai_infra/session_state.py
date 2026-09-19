"""有界、可追踪脏改动的会话级状态容器（第 145 轮批 C1）。

问题形态
--------
业务 Agent 的「会话级状态」（供指代解析用的上一轮结果、多轮槽位填充的待补项）
原先是挂在实例上的一个普通 dict：

    self._session_state: dict = {}
    return self._session_state.setdefault(context_id or "_default", {})

它有三个后果：

  1. **多进程不可见** —— 进程数 > 1 时，同一会话的两次请求若落到不同进程，
     第二次就"忘了"第一次留下的槽位；
  2. **重启即丢** —— 消息历史在 PG（由 checkpointer 承担），槽位却只在内存里，
     两处寿命不同，表现为「聊天记录还在，但 AI 忘了我在补什么」；
  3. **无上界** —— 键是会话 ID，只增不减，长跑进程持续吃内存。

本模块只提供**机制**，不做任何 IO、也不认识任何一个键的业务含义：

  · `SessionState`          —— 一个 `MutableMapping`，记住「哪些键被改过 / 被删过」；
  · `SessionStateRegistry`  —— `scope_id -> SessionState` 的**有界**缓存，
    并能回答「哪些 scope 有未落盘的改动」。

何时读、何时写、写失败怎么办，全部由调用方决定。

为什么保留「同步读接口」
------------------------
消费者（业务 Agent 的 `_session()` 及其调用方）**全是同步代码**，其中一部分还在
纯计算的私有方法里（同步方法里没法 await）。所以容器必须是同步可读可写的
`MutableMapping`，异步只出现在**入口的读**与**出口的写**两端。
把 `_session()` 改成 async 会沿着调用链把 8 个消费点一起掀翻，收益为零。
"""

from __future__ import annotations

import logging
from collections import OrderedDict
from collections.abc import Iterable, Iterator, MutableMapping
from typing import Any, Optional

logger = logging.getLogger(__name__)


def _changed(old: Any, new: Any) -> bool:
    """两个值是否「不一样」。

    ★ 为什么要包一层：`old != new` 并不保证返回 bool —— 例如某个字段装的是
      numpy 数组或 pandas Series 时，返回的是**逐元素比较的结果**，拿去 `if`
      会抛 `ValueError: truth value of an array is ambiguous`。
      那种异常会从 `__setitem__` 里冒出来，位置离真正的原因很远
      （"我只是给状态赋了个值"）。这里统一收敛：比不出来就**当作变了**
      （多写一次库，不会丢数据）。
    """
    try:
        return bool(old != new)
    except Exception:  # noqa: BLE001 —— 见 docstring：比不出来时按"变了"处理
        return True


class SessionState(MutableMapping):
    """一个会话的状态容器：`MutableMapping` + 脏追踪。

    「脏」的记录粒度是**键**，不是整个容器 —— 因为落盘是逐键 upsert：
    `last_result` 可能是几百 KB，`pending_step` 只有几十字节，没必要为了改一个
    小键把大键重写一遍。

    ★ 脏键在**落盘成功后**才由调用方清除（`mark_persisted`），且只清它实际写过的
      那些键。这一点很重要：`await` 落盘期间可能有新的改动进来，若落盘后无差别
      清空，那笔新改动就**永远不会被写出去**（也不会报错）。
    """

    __slots__ = ("scope_id", "_data", "_dirty", "_deleted")

    def __init__(self, initial: Optional[dict] = None, *, scope_id: str = "") -> None:
        self.scope_id = scope_id
        self._data: dict[str, Any] = dict(initial or {})
        self._dirty: set[str] = set()
        self._deleted: set[str] = set()

    # ------------------------------------------------------------ 映射协议

    def __getitem__(self, key: str) -> Any:
        return self._data[key]

    def __setitem__(self, key: str, value: Any) -> None:
        if key not in self._data or _changed(self._data[key], value):
            self._dirty.add(key)
            self._deleted.discard(key)
        self._data[key] = value

    def __delitem__(self, key: str) -> None:
        del self._data[key]
        self._dirty.discard(key)
        self._deleted.add(key)

    def __iter__(self) -> Iterator[str]:
        return iter(self._data)

    def __len__(self) -> int:
        return len(self._data)

    def __repr__(self) -> str:  # pragma: no cover - 仅调试
        return (
            f"SessionState(scope_id={self.scope_id!r}, keys={sorted(self._data)}, "
            f"dirty={sorted(self._dirty)}, deleted={sorted(self._deleted)})"
        )

    # ------------------------------------------------------------ 脏追踪

    @property
    def dirty_keys(self) -> frozenset:
        return frozenset(self._dirty)

    @property
    def deleted_keys(self) -> frozenset:
        return frozenset(self._deleted)

    @property
    def is_dirty(self) -> bool:
        return bool(self._dirty or self._deleted)

    def pending_writes(self) -> dict:
        """本次待写入的 `键 -> 值`（只含改动过的键）。"""
        return {k: self._data[k] for k in self._dirty if k in self._data}

    def mark_persisted(self, *, keys: Iterable[str], deleted: Iterable[str] = ()) -> None:
        """落盘**成功后**清除对应的脏标记（只清传入的那些键）。"""
        for k in keys:
            self._dirty.discard(k)
        for k in deleted:
            self._deleted.discard(k)

    def reset(self, initial: Optional[dict] = None) -> None:
        """用外部权威值**整体替换**内容，并清空脏标记。

        这是「从库读回来」的语义：读到的就是全部，没有待写增量。
        """
        self._data = dict(initial or {})
        self._dirty.clear()
        self._deleted.clear()


class SessionStateRegistry:
    """`scope_id -> SessionState` 的**有界**缓存（LRU）。

    之所以要上界：`scope_id` 的取值面是「所有会话」，只增不减就是内存泄漏。
    上限之外的历史会话会被丢掉 —— 那是**可以接受**的：状态本来就有持久层，
    丢掉内存副本只意味着下次要靠 `hydrate` 读回来。

    但**脏容器不驱逐** —— 见 `_make_room()`。
    """

    #: 默认上限。取值理由：单容器最大也就几百 KB 量级，256 个 ≈ 几十 MB 上界；
    #: 同时远大于「同一进程内并发活跃会话数」（并发受 worker 数与 DB 连接池约束）。
    DEFAULT_MAX_SCOPES: int = 256

    def __init__(self, *, max_scopes: Optional[int] = None) -> None:
        self._max = max(1, int(max_scopes or self.DEFAULT_MAX_SCOPES))
        self._items: "OrderedDict[str, SessionState]" = OrderedDict()
        self._evicted = 0

    # ------------------------------------------------------------ 读

    def scope(self, scope_id: str) -> SessionState:
        """取（必要时创建）该作用域的容器。命中已有容器时按 LRU 续期。"""
        st = self._items.get(scope_id)
        if st is None:
            self._make_room()
            st = SessionState(scope_id=scope_id)
            self._items[scope_id] = st
        else:
            self._items.move_to_end(scope_id)
        return st

    def has(self, scope_id: str) -> bool:
        return scope_id in self._items

    # ------------------------------------------------------------ 观测

    def dirty_scopes(self) -> tuple:
        """当前有未落盘改动的 scope（调用方据此决定要 flush 谁）。"""
        return tuple(s for s, st in self._items.items() if st.is_dirty)

    @property
    def max_scopes(self) -> int:
        return self._max

    @property
    def evicted(self) -> int:
        """被驱逐的**干净**容器数量（可观测；正常情况下应该很小）。"""
        return self._evicted

    # ------------------------------------------------------------ 维护

    def forget(self, scope_id: str) -> None:
        """丢掉某个作用域的内存副本（丢弃内容，不落盘）。"""
        self._items.pop(scope_id, None)

    def clear(self) -> None:
        self._items.clear()
        self._evicted = 0

    def __len__(self) -> int:
        return len(self._items)

    def __contains__(self, scope_id: object) -> bool:
        return scope_id in self._items

    def _make_room(self) -> None:
        """容量满时**只驱逐干净的**容器。

        ★ 为什么不能驱逐脏的：脏 = 「有改动还没落盘」。驱逐它等于把用户刚补上的
          槽位**静默丢掉** —— 不报错、不告警，下次 hydrate 读回一份旧状态，
          用户看到的是「我刚说的它又忘了」。
          极端情况（全部脏）下宁可让缓存暂时超出上限：那是内存问题，而丢状态是
          正确性问题。两类问题的代价不对称，所以选安全的那一侧。
        """
        while len(self._items) >= self._max:
            victim = next((s for s, st in self._items.items() if not st.is_dirty), None)
            if victim is None:
                logger.warning(
                    "会话状态缓存全部为脏（%d 个）而无法驱逐，本次允许暂时超出上限 %d",
                    len(self._items),
                    self._max,
                )
                return
            self._items.pop(victim, None)
            self._evicted += 1
