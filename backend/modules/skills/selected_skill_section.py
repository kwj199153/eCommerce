"""读口：把「**本次对话点名的技能**」接进 system prompt（第 188 轮）。

==============================================================================
★ 这条通道补的是什么
==============================================================================
第 181 轮建的技能机制只有**一条**取用路径：把「技能目录」注入 system prompt，
模型自己判断该用哪条、再调 `load_skill(name)` 取全文（渐进披露两级）。

那条路径的前提是「**模型自己挑**」。但界面上还给了另一个能力：用户直接点一张
快捷卡片 —— 那意味着**他已经挑好了**。此时若仍只走目录那条路，等于把用户的
显式选择降级成一条建议：模型完全可能挑另一条，或者干脆不加载。

本文件把「用户已经挑好」变成**第三段注入**：本次对话指定了哪条技能，就把它的
正文直接拼进 system prompt（不必等模型来调工具）。

==============================================================================
★ 它不新建取数逻辑（唯一共享解析器）
==============================================================================
正文解析**完全复用** `provider.read_skill_text` —— 与 `load_skill` 工具走的是
同一个函数、同一套三重过滤（归属 + 全局启用 + 对该 Agent 启用）。
理由是本仓那条判据：「同一判定两份实现 ⇒ 至少一份永远测不到」。
「只看名字就能读到未授权正文」比不披露更糟，所以两条通道必须在**同一处**校验。

==============================================================================
★★ 取不到时必须**显式**，绝不静默跳过（本文件最要紧的判据）
==============================================================================
点名通道的失败模式是**静默退化**：

    用户点了技能 → 正文取不到 → 什么都不说 → 模型按默认方式回答
    ⇒ 用户看到的是一份"没按我选的技能做"的答案，
      而界面、日志、测试**全绿**。

所以三态分明：
  · **没点名**       ⇒ 返回**空串**（正常语义：本次不需要这一段，
                        注册表那一层会把它丢掉）；
  · **点名且取到**   ⇒ 返回「抬头 + 正文」；
  · **点名但取不到** ⇒ 返回一段**显式说明**（"你被点名用 X 但取不到，
                        请如实告知用户"），**不是**空串。
渲染本身住在机制层 `ai_infra.skills.render_selected_skill_block`
（措辞通用，不触本仓对 `ai_infra` 的零业务词门禁）；本文件只负责把
「ContextVar 里的名字」与「DB 里的正文」接起来。

★ 已知的口径合并（**刻意**，不是遗漏）：DB 抖动导致的取数失败，与「技能不存在 /
未启用 / 不属于本账号」在本层**合并**成同一句「取不到」。三个原因合成一句是本仓
既有判据（不可给出一条可枚举的探测通道）；把 DB 故障也并进来是它的代价，
可观测性由 `read_skill_text` 里那条**带异常类型**的 WARNING 承担。

==============================================================================
★ 注册为什么写在模块级、又套一层 `ensure_registered()`
==============================================================================
与 `modules/memory/prompt_section.py` 完全同源：注册是 import 副作用；
而重名注册会 raise，`importlib.reload` 又是本仓测试的常规手段
⇒ 直接裸写在模块级的话，reload 即崩。
"""

from __future__ import annotations

import logging

from ai_infra.prompt_sections import (
    PromptContext,
    register_prompt_section,
    registered_sections,
)
from ai_infra.skills import current_requested_skill, render_selected_skill_block

logger = logging.getLogger(__name__)

#: 注册名。与业务语义绑定的字符串只能出现在业务层
#: （`ai_infra` 的字符串层有零业务内容的硬门禁）。
SECTION_NAME = "skills_selected"


async def selected_skill_prompt_section(ctx: PromptContext) -> str:
    """把本次被点名的技能渲染成一段注入文本；**没人点名时返回空串**。

    ★ 身份与 Agent 名都取自 `ctx`（服务端上下文），**不取** ContextVar 里的
      其它东西 —— 点名的名字是本次请求的业务选择，归属判定所需的身份仍然
      只能来自服务端（同族判据：归属只能服务端注入）。
    """
    name = current_requested_skill()
    if not name:
        return ""

    # ★ 延迟 import 有两个理由：
    #   ① 避免 provider ↔ 本模块的顶层循环（provider 在模块末尾 import 本模块）；
    #   ② 与 provider 自己的写法一致（它也在函数体里 import service）。
    from modules.skills.provider import read_skill_text

    try:
        # ★★★ 第 198 轮：与目录通道同源 —— 路由子层的 `X_router` 必须
        #   归一回业务名，否则**点名**技能在工具通道里读不到正文。
        #   那种形态比不披露更糟：目录里明明列着这个名字，模型却取不到内容。
        from modules.skills.agents import business_agent_name

        text = await read_skill_text(
            ctx.user_id, business_agent_name(ctx.agent_name), name
        )
    except Exception as exc:  # noqa: BLE001
        # ★★★ 这里**绝不向上抛**，理由是这一条通道特有的：
        #   注册表 `collect_prompt_sections` 对单段失败是「隔离 + 丢弃」
        #   （那对长期记忆是对的：少注入一段增益而已）。但**点名**不是增益 ——
        #   它是用户的显式指令。整段被丢掉 ⇒ 模型完全不知道用户点过技能，
        #   用户看到的就是一份"没按我选的技能做"的答案，而链接全绿。
        #   ⇒ 把异常转成「取不到」的**显式文案**，模型才能如实告知用户。
        #   （同族判据：降级路径禁用「全 0」兜底 —— 兜底值必须能被识别。）
        logger.warning(
            "点名技能解析失败（转为显式不可用文案）skill=%r agent=%r: %s: %s",
            name, ctx.agent_name, type(exc).__name__, exc,
        )
        text = None

    return render_selected_skill_block(name, text)


def ensure_registered() -> None:
    """幂等注册（理由见模块 docstring 末段）。"""
    if SECTION_NAME in registered_sections():
        return
    register_prompt_section(SECTION_NAME, selected_skill_prompt_section)


ensure_registered()


__all__ = [
    "SECTION_NAME",
    "selected_skill_prompt_section",
    "ensure_registered",
]
