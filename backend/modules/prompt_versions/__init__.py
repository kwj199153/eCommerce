"""提示词覆写层（第 351 轮 · P0-7 B 档）。

==============================================================================
★ 本包解决什么
==============================================================================
A 档（第 283 轮）给提示词加了 `version` + `fingerprint`，但正文仍只住在
`.py` 常量里 —— **改一个词就要改代码 + 重新发布**。本包把「当前生效的正文」
从源码解耦：平台超管可以不动代码就换上一版正文，每次留痕、可回退、可对账。

==============================================================================
★ 分层：机制住在 `ai_infra/`，本包只管「内容 + 表 + HTTP 契约面」
==============================================================================
    ai_infra/llm/prompt_spec.py       A 档：注册表 / 渲染 / 指纹（**唯一渲染实现**）
    ai_infra/llm/prompt_overrides.py  B 档**应用侧** —— 把一条覆写盖上注册表，
                                      并设两道闸门（基线必须对上当前源码、
                                      变量集必须与源码完全一致）
    modules/prompt_versions/
        db_model.py   表 `prompt_versions`（一行一条覆写）
        service.py    表 ↔ 内存注册表的**唯一同步点**（`apply_all_overrides`）
        schemas.py    API 契约
        router.py     管理端点（平台超管专属）

★ 为什么「读表」不能在 `ai_infra/` 里做：`ai_infra` **不得 import `modules.*`**
  —— 那是本仓的硬红线（`tests/test_infra_layering.py` 拦下过 4 处真实泄漏）。
  于是这里把一件事切成两半：**读表 + 落库**住在 `modules/`（本包），
  **应用**住在 `ai_infra/llm/prompt_overrides.py`，中间只过一个受控入口
  （`apply_override(...)` —— 签名与两道闸门都在那一侧，本包拿不到绕过它的路径）。

==============================================================================
★ 渲染路径上一个数据库往返都没有
==============================================================================
`get_prompt_template()` 打的是**内存注册表**（`ai_infra.llm.PROMPT_TEMPLATES`），
不是表。所以：

    改库 ≠ 立刻生效 —— 中间要一次 `apply_all_overrides()`

这个中间状态不是设计缺陷，是刻意的取舍：渲染发生在**每一次 LLM 调用**上，
不能让配置读取变成链路延迟。代价是必须有一个明确的收敛点：

  · 启动期 —— `main.py` 的 `lifespan` 调一次；
  · 改完配置 —— 管理端点 `POST /api/v1/prompt-versions/apply` 显式调一次。

★ 两者都走**同一个** `apply_all_overrides()`，且它本身是「先撤回全部、
  再按库重新应用」的可重放等式 —— 见 `service.py` 里那段论证
  （增量维护会在「删了一行」「改了名字」时留下**幽灵覆写**）。

==============================================================================
★ 门面契约（`__all__`）：其它模块只能 `from modules.prompt_versions import <此处列的名字>`
==============================================================================
本仓有「包门面」门禁（`tests/test_module_facades.py` 条款 1/2/3）：跨模块引用
**不得**写 `from modules.prompt_versions.service import apply_all_overrides`
—— 那是伸手进包内部，会把「包内怎么切文件」变成一份未声明的公开契约。

★ 只登记**名字**、不登记子模块名（`service` / `router` / `db_model` / `schemas`
  一律不进 `__all__`）：登记子模块名等于把条款 1 变成一句空话。
★ re-export 会**复制绑定**（`modules.prompt_versions.apply_all_overrides` 与
  `modules.prompt_versions.service.apply_all_overrides` 是两个模块级绑定）⇒
  打桩必须指向本门面，否则拦不住（见 `tests/test_facade_monkeypatch_targets.py`）。
"""

from .db_model import PromptVersion
from .service import (
    STATUS_ACTIVE,
    STATUS_DISABLED,
    STATUS_NOT_OVERRIDDEN,
    STATUS_STALE,
    STATUS_UNKNOWN_NAME,
    InvalidOverride,
    UnknownPromptName,
    apply_all_overrides,
    delete_version,
    describe,
    list_status,
    set_enabled,
    upsert_version,
)

__all__ = [
    # ---- ORM 实体（组合根 `wiring.MODEL_MODULES` 之外的读口可能需要） ----
    "PromptVersion",
    # ---- 五态常量：status 的**唯一真源**（前端与 service 共用，禁在别处再抄一份） ----
    "STATUS_NOT_OVERRIDDEN",
    "STATUS_ACTIVE",
    "STATUS_STALE",
    "STATUS_DISABLED",
    "STATUS_UNKNOWN_NAME",
    # ---- 写口（未注册的模板名 / 过不了闸门的正文 ⇒ 硬拒绝） ----
    "UnknownPromptName",
    "InvalidOverride",
    "upsert_version",
    "set_enabled",
    "delete_version",
    # ---- 读口 ----
    "list_status",
    "describe",
    # ---- 同步：库 → 内存注册表（启动期与 apply 端点共用同一个实现） ----
    "apply_all_overrides",
]
