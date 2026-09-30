"""技能仓库模块（第 181 轮 · 批 B）。

分层：
    agents.py    Agent 目录（后端 agent_name ↔ 前端 id 的唯一桥接真源）
    db_model.py  ORM（skills / skill_revisions）
    service.py   业务逻辑（CRUD / 版本 / 装配 / 供 load_skill 用的读口）
    provider.py  机制接线（渐进披露两级：目录注入 + 正文加载）
    selected_skill_section.py
                 **点名通道**：本次对话指定的技能，正文直注入（第 188 轮）
    seed.py      演示示例技能（与演示店铺同构的双向收敛）
    router.py    HTTP 端点

★ `provider` 必须被 import 到，否则技能会**静默不注入** ——
  见 `router.py` 顶部的显式 import 与其注释。
"""
# ============================================================================
# ★ 契约面（`__all__`）：其它模块只能 `from modules.skills import <此处列的名字>`
# ============================================================================
# 本仓有「包门面」门禁（`tests/test_module_facades.py` 条款 1）：跨模块引用
# **不得**写 `from modules.skills.tools_catalog import tool_title` ——
# 那是伸手进包内部，会把「包内怎么切文件」变成一份**未声明**的公开契约。
#
# `tool_title` 是「工具人话名」的**唯一查询口**。第 211 轮起，5 个 Agent 的
# 流式装配点用它注入 `title_resolver`（见 `ai_infra/sse.py::ToolTrace`），
# 故登记为对外出口。
#
# ★ 只登记**名字**，不登记子模块名：`__all__` 里若出现 `tools_catalog` 这类
#   子模块名，条款 1 会被架空（门禁条款 3 专门拦这个）。
# ★ re-export 会**复制绑定**（`modules.skills.tool_title` 与
#   `modules.skills.tools_catalog.tool_title` 是两个模块级绑定）⇒
#   打桩必须指向**契约面**（`modules.skills.tool_title`），否则拦不住。
#   全仓对账：当前没有任何测试 patch `tools_catalog.tool_title`，故本次安全。
from .tools_catalog import tool_title  # noqa: F401  ← re-export，供跨模块取用

__all__ = ["tool_title"]
