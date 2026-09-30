"""技能注入 —— 渐进披露的**注册点**（第 181 轮 · 批 B）

==============================================================================
★ 这个模块只做一件事：把「机制」与「数据」接起来
==============================================================================
`ai_infra.skills` 是纯机制（解析 / 渲染 / 工具工厂），它**不知道**数据在哪。
本模块是业务侧的接线：

    ① `register_prompt_section("skills_catalog", …)`
       → 渐进披露**第一级**：每轮把「这个 Agent 可用的技能目录」拼进 system prompt

    ② `register_skill_reader("db", …)`
       → 渐进披露**第二级**：模型调 `load_skill(name)` 时，从这里取全文

    ③ `from . import selected_skill_section`（模块末尾）
       → **点名通道**（第 188 轮）：用户在界面上点了某条技能时，
         把那条技能的正文直接拼进 system prompt，不必等模型自己来调工具。
         ★ 它与 ② 共用 `read_skill_text` —— 两条通道**同一份过滤逻辑**，
           见该函数的 docstring（「同一判定两份实现 ⇒ 至少一份永远测不到」）。

★ 为什么必须由**业务侧**注册（而不是让 ai_infra 自己去读表）：
  本仓门禁 `tests/test_infra_layering.py` 断言 `ai_infra` 反向依赖 `modules` = 0。
  让基础设施层认识技能表 = 基础设施层开始认识业务，那是本仓真实发生过的泄漏形态。

==============================================================================
★ 幂等注册
==============================================================================
`register_prompt_section` / `register_skill_reader` 都对**重名直接报错**
（这是刻意的：重名会静默覆盖先注册者，两边都不报错）。

但在 pytest 里，测试可能 `importlib.reload()` 本模块 ⇒ 重复注册 ⇒ 抛异常。
所以这里先查 `registered_*()` 再注册 —— **不是**把报错吞掉，
而是「已经装好了就别再装一遍」，与那两个注册表的语义一致。

==============================================================================
★ 失败隔离
==============================================================================
两个 provider 都可能失败（DB 抖动 / 表还没建 / 用户不存在）。
它们**一律不向上抛** —— 技能是**增益**，不是门禁：
让增益的故障去否决整轮对话，是比"少注入一段"更差的选择。
（同 `ai_infra/prompt_sections.py` 判据 ③ 的论证。）
"""

import logging
from typing import Optional

from sqlalchemy import select

from ai_infra.prompt_sections import (
    PromptContext,
    register_prompt_section,
    registered_sections,
)
from ai_infra.skills import (
    register_skill_reader,
    registered_skill_readers,
    render_skill_catalog,
)
from core.database import async_session_factory
from core.identity.models import User

logger = logging.getLogger(__name__)

#: 段落名。改名等于「旧名不再注入」，所以它是契约的一部分。
SECTION_NAME = "skills_catalog"

#: 读取器名
READER_NAME = "db"


async def _resolve_user(db, user_id: Optional[str]) -> Optional[User]:
    """`user_id`（来自服务端上下文）→ `User` 行；空 ⇒ **演示账号主人**（可能仍为 None）。

    ★★★ 第 182 轮：空 `user_id` 不再直接当作"没有身份"。

      为什么这一处必须和路由层一起改（否则演示技能会**只读不生效**）：
      本模块是技能注入的**唯一取数点**（第一级目录 + 第二级正文都走它）。
      上一轮演示技能靠 `is_demo` 窄口"看得见"，但那时演示身份是 `None`
      ⇒ `filter_accessible_skills(None, …)` 只给 `is_demo` 行、
        `read_skill_for_agent(None, …)` 也只给 `is_demo` 行。
      第 182 轮把演示身份换成真主角之后，这里若仍返回 `None`，
      演示技能就会**降级成匿名可见**：本该走"账户归属"的判定退化成"标记位判定"，
      表现为演示账号自己新建的技能**对演示对话不可见**（建了却用不上）。

      ⇒ 空 id ⇒ 交给 `resolve_demo_user` 回答「那是不是演示身份」，
        与路由层**同一个函数**（单真源，不复制口径）。

    ★ 查不到用户 ⇒ 返回 None 而不是抛错：那等价于"没有身份"，
      而"没有身份"的可见性语义是明确的（只见演示技能）—— 副作用最小。
      `resolve_demo_user` 的三重守卫（demo_mode / 账号存在 / 非超管 / 未停用）
      任一不过也返回 None ⇒ 落到同一条 fail-closed 路径。
    """
    if not user_id:
        from core.auth.demo_identity import resolve_demo_user

        return await resolve_demo_user(db, allow_demo=True)
    return (
        await db.execute(select(User).where(User.id == str(user_id)))
    ).scalar_one_or_none()


async def build_catalog_for(agent_name: str, user_id: Optional[str]) -> str:
    """渲染某个 Agent 的**技能目录**（第一级披露）。

    过滤链（与 `service.read_skill_for_agent` 保持同一套语义）：
        ① 归属可见（`filter_accessible_skills`）
        ② 全局启用（`enabled`）
        ③ 对该 Agent 启用（`enabled_agents` 含本 Agent）

    ★ ①②③ 的②③ 在**本函数与 read 口各出现一次** —— 这看起来像「两份实现」，
      但它们判定的是**不同的通道**（目录披露 vs 正文加载），
      且都必须各自成立：只在目录过滤、不在正文过滤 ⇒ 模型知道名字就能读到
      未授权的正文（比不披露更糟）。所以这里**是刻意的重复**，
      抽成公共函数反而会掩盖"两条通道各自都要校验"这个事实。
      ⇒ 与之相对，`filter_accessible_skills`（①）**必须**共用 —— 它是同一个判定。
    """
    try:
        async with async_session_factory() as db:
            user = await _resolve_user(db, user_id)
            from core.auth.accounts import filter_accessible_skills
            from modules.skills.db_model import SkillRecord

            rows = (await db.execute(select(SkillRecord))).scalars().all()
            visible = await filter_accessible_skills(db, user, rows)
            usable = [
                s
                for s in visible
                if bool(s.enabled) and agent_name in list(s.enabled_agents or [])
            ]
            usable.sort(key=lambda s: s.name)
            return render_skill_catalog(usable)
    except Exception as exc:  # noqa: BLE001 —— 见模块 docstring「失败隔离」
        logger.warning(
            "技能目录渲染失败（本次不注入该段）: %s: %s", type(exc).__name__, exc
        )
        return ""


async def _catalog_provider(ctx: PromptContext) -> str:
    """`prompt_sections` 的段落提供者（每轮 LLM 调用都会调它）。"""
    # ★★★ 第 198 轮：工具化路由子层的 agent_name 是 `X_router`
    #   （见各 Agent 的 `_build_router()`），而技能启用存的是**业务**
    #   agent_name（`service._validate_agents` 只接受 `AGENT_CATALOG` 的值）
    #   ⇒ 不归一则技能目录对**走工具通道的 Agent 恒为空**，
    #     且一处日志都没有（第 197 轮实测到第 198 轮才定位）。
    #   归一函数是唯一真源（`agents.business_agent_name`），
    #   不要与本仓另一条通道（`selected_skill_section`）各写一份判定。
    from modules.skills.agents import business_agent_name

    return await build_catalog_for(business_agent_name(ctx.agent_name), ctx.user_id)


async def read_skill_text(
    user_id: Optional[str], agent_name: str, skill_name: str
) -> Optional[str]:
    """按技能名取「**已渲染好的正文**」—— 两条通道**唯一**的解析实现。

    ★ 谁在用（两份，共用同一个实现是本仓刻意的设计）：
      · `load_skill` 工具（模型主动加载 = 渐进披露第二级）；
      · `skills_selected` 段落（第 188 轮：用户在界面上点名了这条技能）。
      两处若各写一份过滤逻辑，必然出现「一处校验、一处漏掉」——
      而漏掉的那一份就是「知道名字就能读到未授权正文」。
      （同族判据：同一判定两份实现 ⇒ 至少一份永远测不到。）

    ★ 三重过滤都住在 `service.read_skill_for_agent`（归属 + 全局启用 +
      对该 Agent 启用），本函数只负责**开一个会话、解析身份、把异常收住**。

    ★ 失败与「本来就取不到」**都返回 `None`**（不抛、不区分）：两侧调用方
      都用同一句「取不到」文案回话 —— 区分它们等于给出一条可枚举的探测通道。
      可观测性由下面那条带异常类型的 WARNING 承担（不是静默吞掉）。
    """
    try:
        async with async_session_factory() as db:
            user = await _resolve_user(db, user_id)
            from modules.skills.service import read_skill_for_agent

            return await read_skill_for_agent(db, user, agent_name, skill_name)
    except Exception as exc:  # noqa: BLE001
        logger.warning(
            "技能正文读取失败 skill=%r agent=%r: %s: %s",
            skill_name, agent_name, type(exc).__name__, exc,
        )
        return None


def install() -> None:
    """把两个接口登记进机制层的注册表（**幂等**）。"""
    if SECTION_NAME not in registered_sections():
        register_prompt_section(SECTION_NAME, _catalog_provider)
    if READER_NAME not in registered_skill_readers():
        register_skill_reader(READER_NAME, read_skill_text)


# ★ 模块 import 时即装好。
#   触发链：`main.py` include 本模块的 router → import service → 本模块被 import。
#   ★ 若将来出现「router 不 import provider」的重构，技能会**静默不注入**
#     —— 由 `tests/test_skill_injection.py::test_section_registered` 钉住。
install()

# ★ 第三条注册：把「点名技能」段落也装上（第 188 轮）。
#   放在 provider 而不是 router：provider 已经是「技能注入的唯一装配点」，
#   让 import 它的人**一次拿到三条注册**，不必再多记一个模块名。
#   ★ 反向的那一侧不受影响：`selected_skill_section` 反过来要 `read_skill_text`，
#     所以它把那个 import 放在**函数体内**（延迟），本行因此不存在循环 import。
#   ★ 反向对照：删掉这一行 ⇒ 点名技能永不注入，而九个端点、技能仓库页、
#     目录注入全部照常工作，没有任何一处会报错 ——
#     由 `tests/test_skill_selection.py` 的注册断言钉住。
from modules.skills import selected_skill_section  # noqa: E402,F401 —— import 即注册
