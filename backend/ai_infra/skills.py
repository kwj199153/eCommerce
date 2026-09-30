"""技能（Skill）机制层 —— **渐进披露**内核（第 181 轮 · 批 B）

==============================================================================
★ 这一层解决什么
==============================================================================
在此之前的形态是「能力**全量常驻** system prompt」：新增一个能力 =
改一段提示词 + 重启；提示词只增不减；模型**没有「发现自己该用哪个技能」这一层**。

技能机制的要害不是「多一段提示词」，而是**两级披露**：

    第一级（目录）  只把 `name + description` 注入 system prompt
                    —— 让模型**知道有哪些技能存在**，但不付全文的 token
    第二级（正文）  模型判断需要某个技能时，调 `load_skill(name)` 取全文
                    —— 只有被真正用到的技能才付 token

所以「渐进披露」= 目录注入 + 按需加载，**两半缺一不可**：
只做目录 ⇒ 模型知道有这个技能却永远读不到正文（半成品）；
只做全文 ⇒ 那就是本层之前的老形态，换个名字而已。

==============================================================================
★ 与 Anthropic Agent Skills 规范的关系
==============================================================================
对齐该规范的三个关键点（本项目**自建**，不引第三方引擎）：

  ① 技能以 `SKILL.md` 为单元：**YAML frontmatter 元数据 + 正文**
  ② 元数据里 `description` 是**第一级披露的唯一依据**（模型只看它决定要不要加载）
  ③ 正文**按需加载**，不预先占满上下文

★ 为什么不直接引 `deepagents.SkillsMiddleware`（第 179/180 轮的实测结论）：
  · 那个实现从 **backend 文件树**读（`'/skills/user/'` 这种路径），
    而本项目的数据在 PostgreSQL ⇒ 要么让 DB 假装是文件系统，要么改数据模型；
  · 它是 `AgentMiddleware`，**只被 `create_agent()` 出来的图消费**，
    而本项目 `BaseAgent._build_graph()` 是**手写 `StateGraph`** ⇒ 吃不到；
  · 它最值钱的调优层（`profiles/`）不覆盖本项目用的模型族。
  ⇒ 结论：**照规范自建**。规范是公开的，引擎不必换。

==============================================================================
★ 分层：机制住本层，内容住业务层
==============================================================================
本模块**只做纯逻辑**，一个字节都不碰数据库：

    parse_skill_document()  —— frontmatter 解析（纯字符串 → 结构）
    render_skill_catalog()  —— 第一级披露的渲染
    render_skill_body()     —— 第二级披露的渲染
    build_skill_tools()     —— 第二级披露的**取数口**（注册表，默认空）

「读哪张表、按什么过滤、谁能看」全在业务层
（`modules/skills/`），通过 `register_skill_reader()` 注入进来。

★ 这条分界不是洁癖，是本仓的**门禁**：
  `tests/test_infra_layering.py` 断言本层「反向依赖 modules 数 = 0」
  且「字符串字面量里没有业务内容（剥掉 docstring 再扫）」。
  所以本模块里**不允许**出现任何具体业务词。

★ 注册表「默认必须为空」的理由同 `ai_infra.prompt_sections`：
  机制层自带内容 = 机制层开始认识业务 = L3/L4 那类泄漏。
  本仓真实发生过（`AgentState.metadata` 曾硬编码 tenant/shop 四个键，只写不读）。
"""

from __future__ import annotations

import contextlib
import contextvars
import logging
from dataclasses import dataclass, field
from typing import AsyncIterator, Awaitable, Callable, Iterable, Optional, Sequence

logger = logging.getLogger(__name__)


# ============================================================================
# 一、frontmatter 解析（纯字符串 → 结构）
# ============================================================================

#: 文档以该标记开头即视为带 frontmatter。必须**首行**出现，正文中间的 `---`
#: 一律当普通文本 —— 否则一份带水平分割线的正文会被误切成元数据。
_FRONTMATTER_FENCE = "---"


@dataclass(frozen=True)
class SkillDocument:
    """一份技能文档的解析结果。

    ★ `body` 与 `meta` **分开存**，就是为了让「目录」与「正文」能分别渲染 ——
      这是渐进披露在数据结构上的落点。把两者捏成一个字符串，
      第一级披露就必然要把全文读出来再截断（等于没省 token）。
    """

    meta: dict = field(default_factory=dict)
    body: str = ""

    def get(self, key: str, default=None):
        return self.meta.get(key, default)


def parse_skill_document(text: str) -> SkillDocument:
    """把 `SKILL.md` 形态的文本解析成 `SkillDocument`。

    ★ 解析器**刻意手写**、不引 YAML 库：
      只需要支持三种形态（`k: v` / `k: [a, b]` / 块列表），
      而引入一个解析库会把它变成**本层的运行期依赖** —— 对本项目这种
      「一份依赖升版本要动全链」的环境，收益不值这个价。
      遇到不认识的写法一律**降级为字符串**，绝不抛异常：
      一份技能文档的格式瑕疵不该让整轮对话挂掉（同 `prompt_sections` 判据 ③）。

    支持的写法：
        key: value                  → "value"（两端空白剥掉；可选被引号包住）
        key: [a, b, c]              → ["a", "b", "c"]
        key:
          - a
          - b                      → ["a", "b"]（块列表）
        key: |                      → 多行块（保留换行）
          line1
          line2
    """
    if not isinstance(text, str) or not text.strip():
        return SkillDocument(meta={}, body="")

    lines = text.replace("\r\n", "\n").split("\n")

    # 首行必须是围栏且后面还有闭合围栏 —— 否则整篇当正文。
    if lines[0].strip() != _FRONTMATTER_FENCE:
        return SkillDocument(meta={}, body=text.strip())

    close = None
    for idx in range(1, len(lines)):
        if lines[idx].strip() == _FRONTMATTER_FENCE:
            close = idx
            break
    if close is None:
        # 有开头没结尾 ⇒ 这是正文里的分割线，不是 frontmatter。
        # ★ 这里若"容错地"把整篇当元数据，会把正文静默吃掉 —— 宁可当无元数据。
        return SkillDocument(meta={}, body=text.strip())

    meta = _parse_meta_block(lines[1:close])
    body = "\n".join(lines[close + 1:]).strip()
    return SkillDocument(meta=meta, body=body)


def _parse_meta_block(block_lines: Sequence[str]) -> dict:
    """解析 frontmatter 的键值区（支持标量 / 行内列表 / 块列表 / 多行块）。"""
    meta: dict = {}
    i = 0
    n = len(block_lines)

    while i < n:
        raw = block_lines[i]
        stripped = raw.strip()

        # 跳过空行与注释
        if not stripped or stripped.startswith("#"):
            i += 1
            continue

        if ":" not in raw:
            # 不认识的写法：不抛错，记一条 WARNING（内容层可自行修正）
            logger.warning("skill frontmatter: 忽略无法解析的行 %r", stripped[:80])
            i += 1
            continue

        key, _, value = raw.partition(":")
        key = key.strip()
        value = value.strip()
        if not key:
            i += 1
            continue

        # 多行块 `key: |`
        if value in ("|", ">"):
            i += 1
            chunk: list[str] = []
            while i < n:
                nxt = block_lines[i]
                if nxt.strip() and not nxt.startswith((" ", "\t")):
                    break
                chunk.append(nxt)
                i += 1
            # 去掉整体缩进
            meta[key] = _dedent("\n".join(chunk)).rstrip()
            continue

        # 行内列表 `key: [a, b]`
        if value.startswith("[") and value.endswith("]"):
            meta[key] = _split_inline_list(value[1:-1])
            i += 1
            continue

        # 空值 + 后续缩进项 ⇒ 块列表
        if value == "" and i + 1 < n and block_lines[i + 1].strip().startswith("- "):
            i += 1
            items: list[str] = []
            while i < n and block_lines[i].strip().startswith("- "):
                items.append(_unquote(block_lines[i].strip()[2:].strip()))
                i += 1
            meta[key] = items
            continue

        meta[key] = _unquote(value)
        i += 1

    return meta


def _split_inline_list(inner: str) -> list[str]:
    return [_unquote(x.strip()) for x in inner.split(",") if x.strip()]


def _unquote(value: str) -> str:
    value = value.strip()
    if len(value) >= 2 and value[0] == value[-1] and value[0] in ("'", '"'):
        return value[1:-1]
    return value


def _dedent(text: str) -> str:
    """去掉块文本的公共前导缩进（保留相对层级）。"""
    lines = text.split("\n")
    indents = [len(l) - len(l.lstrip()) for l in lines if l.strip()]
    if not indents:
        return text.strip("\n")
    cut = min(indents)
    return "\n".join(l[cut:] if l.strip() else "" for l in lines)


# ============================================================================
# 二、两级披露的渲染
# ============================================================================

#: 注入 system prompt 的技能用法说明。
#:
#: ★ 措辞必须**通用**（本层不许出现具体业务词，有 AST 门禁）——
#:   它对全部业务 Agent 生效，不假设任何一条业务线的语义。
SKILLS_GUIDE = (
    "## 可用技能（Skills）\n\n"
    "下面的「技能目录」列出了你当前可用的技能。**目录里只有名称与描述**；"
    "技能正文按需加载，不预先占用上下文。\n\n"
    "使用方式：\n"
    "1. 先读目录，判断当前任务**是否**落在某个技能的适用范围内；\n"
    "2. 需要时调用 `load_skill` 工具，参数就是技能名，取回该技能的完整说明；\n"
    "3. 取回后**按该技能说明的步骤执行**；它会给出更具体的做法、判断条件与注意事项。\n\n"
    "判断规则：\n"
    "- 目录里没有相关技能时，按你原有的能力直接作答，不要凭空臆造技能名；\n"
    "- 一个任务可能同时适用多个技能，按需逐个加载；\n"
    "- 技能说明与你的默认习惯冲突时，**以技能说明为准**（那是针对该场景的专门约定）。"
)


def render_skill_catalog(skills: Iterable) -> str:
    """**第一级披露**：把技能渲染成「目录」（只含名称 + 描述）。

    `skills` 里的元素可以是 `SkillDocument`、dict、或任何带
    `name` / `description` 属性的对象 —— 本函数只按这三个名字取值
    （duck typing，与 `core.auth.accounts` 的归属访问器同一套路）。
    取不到名字的行**被跳过**而不是渲染成空条目：一条没有名字的技能
    在对话里毫无用处，渲染出来只会污染上下文。

    ★ 返回空串表示「本次没有可披露的技能」——调用方据此**不加**这一段，
      而不是加一段光秃秃的标题（那会白占 token 并暗示"你有技能但都是空的"）。
    """
    rows: list[str] = []
    for item in skills or []:
        name = _pick(item, "name")
        if not name:
            continue
        desc = str(_pick(item, "description") or "").strip()
        title = str(_pick(item, "title") or "").strip()
        label = name if not title or title == name else "%s（%s）" % (name, title)
        rows.append("- **%s** — %s" % (label, desc or "（无描述）"))

    if not rows:
        return ""
    return "%s\n\n%s" % (SKILLS_GUIDE, "\n".join(rows))


#: 「本技能配套工具」指引的抬头。
#:
#: ★ 措辞必须**通用**（本层不许出现具体业务词，有 AST 门禁）——
#:   它对全部业务 Agent 生效，不假设任何一条业务线的语义。
#: ★ 为什么强调「只用这些」：模型的 `bind_tools` 清单通常**比技能声明的更宽**
#:   （同一 Agent 上挂着 5–9 个工具），而技能的作用正是把这一次执行
#:   **收窄**到该场景该用的那个 —— 不说"只用这些"，收窄就不会真的发生。
_TOOLS_GUIDE_HEAD = (
    "## 本技能配套工具\n\n"
    "执行上面的步骤需要取数或计算时，请调用下列工具"
    "（**只用这些**；不要调用清单之外的工具，也不要凭记忆编造工具名）："
)


def render_skill_tools(raw) -> str:
    """把技能声明的配套工具渲染成一段使用指引（**无工具时返回空串**）。

    ★ 返回空串而不是"本技能无配套工具"：一段空宣告只是白占 token，
      并暗示"这个技能本该有工具但没配"（同 `render_skill_catalog` 的判据）。

    ★ 这是「技能绑定工具」这件事**唯一真正生效的地方**（第 185 轮）：
      在此之前 `tools` 字段只被存进数据库、下发到界面，**没有任何执行侧消费者**
      ⇒ 勾了等于没勾。现在它随正文一起在 `load_skill` 时交给模型。

    ★ 接受多种输入形态（list / tuple / set / 逗号分隔字符串 / None）——
      数据可能来自 DB 的 `tools` 列，也可能来自一份手写的技能文档；
      解析不了的一律降级为空（技能是**增益**，格式瑕疵不该让加载失败，
      同 `parse_skill_document` 判据 ③）。
    """
    if raw is None:
        return ""
    if isinstance(raw, str):
        items = [x.strip() for x in raw.replace("，", ",").split(",")]
    elif isinstance(raw, (list, tuple, set)):
        items = [str(x).strip() for x in raw]
    else:
        return ""

    # 去重保序：DB 里理论上已去重，但本函数不该假设 —— 重复条目会渲染两遍。
    seen: list = []
    for name in items:
        if name and name not in seen:
            seen.append(name)
    if not seen:
        return ""
    return "\n\n%s\n\n%s" % (_TOOLS_GUIDE_HEAD, "\n".join("- `%s`" % n for n in seen))


def render_skill_body(skill) -> str:
    """**第二级披露**：把某个技能的**正文**渲染成可直接喂给模型的文本。

    ★ 正文为空时返回一段**显式说明**，而不是空串：
      「加载成功但正文是空的」与「加载失败」必须可分 ——
      返回空串会让模型以为工具坏了，进而放弃这个技能。

    ★ 技能若声明了**配套工具**，在正文之后附一段指引（`render_skill_tools`）。
      那一小段不是装饰：工具是**按 Agent 装配**的，模型每轮只从 `bind_tools`
      拿到自己的工具清单；技能正文若只写"去算利润"而没写"用 `analyze_profit`"，
      模型会在自己的工具表里**猜**一个名字 —— 猜错就是一次无效调用。
      附上清单等于把「这个技能该用哪个工具」从猜测变成给定。

      ★ 空正文与工具段是**正交**的：正文缺失时照样附工具清单
        （一个只登记了工具绑定、还没写正文的技能，不该连工具提示也一起丢）。
    """
    name = str(_pick(skill, "name") or "").strip()
    title = str(_pick(skill, "title") or "").strip()
    version = str(_pick(skill, "version") or "").strip()
    body = str(_pick(skill, "content") or _pick(skill, "body") or "").strip()

    header_parts = [f"# 技能：{title or name}"]
    if version:
        header_parts.append(f"（版本 {version}）")
    header = " ".join(header_parts)

    if not body:
        tail = (
            "该技能当前**没有配置正文**（只有元数据）。"
            "请按你原有的能力处理，并如实告知用户该技能尚未填写内容。"
        )
    else:
        tail = body

    return f"{header}\n\n{tail}{render_skill_tools(_pick(skill, 'tools'))}"


def _pick(item, key: str):
    """从 dict / dataclass / 任意对象里取一个字段（取不到返回 None）。"""
    if isinstance(item, dict):
        return item.get(key)
    return getattr(item, key, None)


# ============================================================================
# 三、第二级披露的取数口（注册表 · 默认空）
# ============================================================================

#: 技能正文读取器：给一个身份与技能名，返回该技能的文本（或空串 / None）。
#:
#: 签名固定为 `(user_id, agent_name, skill_name)`：
#:   · `user_id`  —— 服务端身份（**不是**模型生成的工具入参）；空 = 匿名演示
#:   · `agent_name`—— 哪个 Agent 在问（业务层可据此校验「这个技能是否对它启用」）
#:   · `skill_name`—— 模型给出的技能名（**唯一**来自模型的一个参数）
#:
#: ★ 身份**不由模型提供**，这条是刻意的：工具入参由 LLM 生成，
#:   让它参与归属判定等于把越权口交给模型。
SkillReader = Callable[[Optional[str], str, str], Awaitable[Optional[str]]]

#: 注册表（模块级）。★ 定义处必须为空 —— 机制层不自带任何内容。
_READERS: dict = {}


def register_skill_reader(name: str, reader: SkillReader) -> None:
    """登记一个技能正文读取器（业务层 import 时调用）。

    ★ 重名**直接拒绝**（同 `prompt_sections.register_prompt_section` 判据 ②）：
      静默覆盖会让先注册者的内容消失，且两边都不报错。
    """
    key = str(name or "").strip()
    if not key:
        raise ValueError("读取器名不能为空 —— 空名会让出错时无法指出是谁")
    if not callable(reader):
        raise TypeError(f"读取器 {key!r} 不可调用：{reader!r}")
    if key in _READERS:
        raise ValueError(
            f"读取器名 {key!r} 已被注册（{_READERS[key]!r}）—— 重名会静默覆盖先注册的，"
            f"所以这里直接拒绝。"
        )
    _READERS[key] = reader
    logger.debug("skill reader registered: %s", key)


def registered_skill_readers() -> tuple:
    """已登记的读取器名（有序）。返回元组以防调用方绕过 `register_*` 直接改 dict。"""
    return tuple(_READERS)


def _combined_reader() -> Optional[SkillReader]:
    """把多个读取器合成一个：**按注册顺序取第一个非空结果**。

    ★ 为什么允许多个：同一份技能可能来自多个来源（内置 / 用户自建 / 团队共享），
      合并逻辑放在这里，业务层每加一个来源只需再注册一个读取器。
    ★ 全失败 / 全空 ⇒ 返回 None（调用方据此给出「没找到」的明确文案）。
    """
    readers = list(_READERS.values())
    if not readers:
        return None

    async def _read(user_id: Optional[str], agent_name: str, skill_name: str):
        for fn in readers:
            try:
                text = await fn(user_id, agent_name, skill_name)
            except Exception as exc:  # noqa: BLE001 —— 一个来源坏了不该拖垮其余的
                logger.warning(
                    "skill reader %r 失败（已跳过，尝试下一个来源）: %s: %s",
                    getattr(fn, "__qualname__", fn), type(exc).__name__, exc,
                )
                continue
            if isinstance(text, str) and text.strip():
                return text
        return None

    return _read


def build_skill_tools(agent_name: str) -> list:
    """构造「按需加载技能」的工具（第二级披露的入口）。

    ★ **恒返回 1 个** `load_skill`，与「有没有读取器」无关。

      这里原先写的是「未注册读取器 ⇒ 返回 `[]`」。那个写法有一个致命性质：
      `BaseAgent.tools` 的**内容取决于本进程有没有 import 到业务模块** ——
      同一份代码，单跑某个测试文件时是 4 个工具、全量跑时是 5 个，
      于是断言只能写"松"，或者变成「单跑绿 / 全量红」。
      本仓明令禁止这种顺序敏感的真值：那等于没有判据。

      ⇒ 工具恒在，「有没有技能可加载」降级成**运行期返回值**问题，
        而不是**装配形态**问题。返回 `[]` 的原始理由（"装一个永远查不到
        东西的工具比不装更糟"）在「读取器尚未注册」这一档仍然成立，
        但它的代价（装配不确定）远大于收益，故改成**显式回话**。

    ★ `metadata=READ_ONLY_METADATA` 是**必须**的，不是装饰：
      `has_side_effects()` 是 fail-closed（未声明 ⇒ True）⇒ 不声明的工具
      会被判成"有副作用"、每次调用都弹人工审批。加载一段技能说明是**可逆的
      只读动作**，把它挂进审批面等于让这个能力事实上不可用。

    ★ `agent_name` 在**构造期**绑定成闭包，而不是让工具运行期去猜：
      工具对象是模块级共享的（`bind_tools` 只读它），
      工具自己无从知道"是哪个 Agent 在调我"。

    ★ 读取器**每次调用时现取**，不在构造期缓存：注册是 import 副作用，
      构造期完全可能早于业务模块 import 完成。

    ★ 工具的 docstring 就是它给模型看的**说明**，必须说清「参数是技能名」
      且「技能名只能来自目录」—— 否则模型会开始编造技能名。
    """
    from langchain_core.tools import StructuredTool

    from ai_infra.tools.side_effects import READ_ONLY_METADATA

    bound_agent = str(agent_name or "")

    async def _load_skill(skill_name: str) -> str:
        """加载指定技能的完整说明。

        参数 `skill_name` 必须是「可用技能」目录里列出的技能名（原样照抄，
        不要翻译、不要改写）。返回该技能的完整步骤与注意事项。

        只有当你判断当前任务落在某个技能的适用范围内时才调用它。
        """
        name = str(skill_name or "").strip()
        if not name:
            return "技能名不能为空。请从「可用技能」目录里选一个技能名。"

        reader = _combined_reader()
        if reader is None:
            # ★ 说清这是**功能未启用**，而不是"技能不存在" ——
            #   两者对模型的含义不同：前者该放弃这条路径，后者该换个名字再试。
            return (
                "当前没有可加载的技能（技能功能未启用）。"
                "请按你原有的能力继续作答，不要重复调用本工具。"
            )

        # ★ 身份只从服务端上下文取，绝不从工具入参取（见 SkillReader 注释）。
        from core.observability.context import current_user_id

        try:
            text = await reader(current_user_id() or None, bound_agent, name)
        except Exception as exc:  # noqa: BLE001
            logger.warning("load_skill(%r) 读取失败: %s: %s", name, type(exc).__name__, exc)
            return f"技能 {name!r} 读取失败（{type(exc).__name__}）。请按你原有的能力继续。"

        if not text:
            # ★ 「找不到」必须说清，并且**明确禁止编造**：
            #   不说清的话模型会自己"补"出一份技能内容 —— 那是纯幻觉。
            return (
                f"没有找到名为 {name!r} 的技能（它可能未启用、不存在、或不属于当前账号）。"
                f"请只使用「可用技能」目录里列出的技能名；不要凭记忆编造技能内容。"
            )
        return text

    return [
        StructuredTool.from_function(
            coroutine=_load_skill,
            name="load_skill",
            description=_load_skill.__doc__,
            metadata=dict(READ_ONLY_METADATA),
        )
    ]


# ============================================================================
# 四、点名通道：本次对话「用哪条技能」（第 188 轮）
# ============================================================================
#: 本次调用链上被**点名**的技能名。
#:
#: ★ 为什么需要它：上面的 `load_skill` 走的是「模型自己挑」那一条路 ——
#:   目录注入给模型看，模型判断该用哪条、再自己调工具取全文。
#:   但还有另一种情形：**用户已经挑好了**（界面上点了一张卡片）。
#:   这时不该再让模型从目录里重挑一遍 —— 那是把用户的选择降级成建议。
#:
#: ★ 为什么住机制层、且走 ContextVar 而不是给 `PromptContext` 加字段：
#:   ① 写入点在各个业务模块的路由里，而业务模块之间**不能顶层互相 import**
#:      （本仓 PLUGIN→PLUGIN 门禁）⇒ 通道必须落在一个双方都已依赖的层；
#:   ② `PromptContext` 的字段是**服务端身份**（`agent_name` / `user_id`），
#:      而"这次要哪条技能"是**本次请求的业务选择**。把它塞进身份 dataclass
#:      会让机制层开始认识业务参数 —— 同族论证见 `ai_infra/prompt_sections.py`
#:      里「只有两个字段」那一段（那里拒绝的是店铺/平台/商品维度，判据同源）；
#:   ③ ContextVar 天然覆盖「路由 → 图节点 → 工具」整条异步调用链，
#:      不必沿途每个函数多带一个参数（本仓已有 5 个 ContextVar 同源先例）。
_REQUESTED_SKILL: contextvars.ContextVar[Optional[str]] = contextvars.ContextVar(
    "requested_skill", default=None
)


def _normalize_selection(skill_name) -> Optional[str]:
    """空串 / 纯空白 / None 统一收敛成 None —— 「没点名」只有一种表示。"""
    text = str(skill_name or "").strip()
    return text or None


def current_requested_skill() -> Optional[str]:
    """当前是否有人点名了技能（没人点名 ⇒ None）。"""
    return _REQUESTED_SKILL.get()


def is_skill_requested() -> bool:
    """本次是否有人点名了技能 —— 供业务模块决定「是否让路给点名通道」。

    ★ 为什么要有这个具名判定、而不是各家自己写
      `current_requested_skill() is not None`：本仓的
      「同一判定两份实现 ⇒ 至少一份永远测不到」是反复咬过人的形态。
      6 个业务模块要做的是**同一个判断**（点名 ⇒ 跳过关键词短路），
      判定必须只有一处 —— 它被改错时所有业务点同时受影响，
      也同时被同一条门禁覆盖。

    ★ 返回语义：True 只表示「有人点了名」，**不保证这条技能取得到**。
      取不到时的处置属于渲染层（见 `render_selected_skill_block`：
      显式说明、绝不静默跳过），不在这里合并。
    """
    return _REQUESTED_SKILL.get() is not None


@contextlib.asynccontextmanager
async def bind_requested_skill(skill_name) -> AsyncIterator[None]:
    """在 `async with` 作用域内把「本次点名」置上，退出时**无条件还原**。

    ★ 必须有自己的作用域，不能"设了就不管"：ContextVar 的写入会顺着任务
      继承下去 —— 一次请求设过之后不复位，同进程后续请求会**继续沿用上一次
      的选择**（本仓真实咬过人的形态：跨身份残留的上下文）。
    ★ 用上下文管理器而不是裸 `set`/`reset`：路由里提前 return 或抛异常时，
      复位才不会漏（`finally` 语义由 `asynccontextmanager` 保证）。
    ★ **流式端点的写入点必须在生成器体内**，不能包在返回
      `StreamingResponse` 的外层语句上 —— 外层 `async with` 在生成器被
      第一次迭代之前就已经退出，那样等于根本没设。
    """
    token = _REQUESTED_SKILL.set(_normalize_selection(skill_name))
    try:
        yield
    finally:
        _REQUESTED_SKILL.reset(token)


#: 点名技能段的抬头与执行约定。
#:
#: ★ 措辞必须**通用**（本层不许出现具体业务词，有 AST 门禁）——
#:   它对全部业务 Agent 生效，不假设任何一条业务线的语义。
#: ★ 为什么要点明「取不到就如实说」：点名通道的失败模式是**静默退化** ——
#:   正文取不到却照常回答，用户看到的是一份"没按我选的技能做"的答案，
#:   而界面、日志、测试**全绿**。所以取不到时必须显式写进 prompt
#:   （见 `render_selected_skill_block`），并让模型也对用户说出来。
SELECTED_SKILL_GUIDE = (
    "## 本次对话指定的技能\n\n"
    "用户已经为**本次对话**指定了一条技能，它的完整说明附在下面。\n"
    "请直接**按这条技能的步骤执行**；它与你的默认习惯冲突时，以它为准。\n\n"
    "如果下面明确写出这条技能当前取不到，请按你原有的能力作答，"
    "并**如实告知用户该技能当前不可用** —— 不要假装已经按它执行。"
)


#: 点名技能、但**技能通道不可用**时的统一文案（唯一实现）。
#:
#: ★ 为什么必须有它 —— 点名通道的失败模式是**静默退化**：用户点了卡片，
#:   系统却按关键词表或通用闲聊作答，界面、日志、测试**全绿**，只有用户
#:   发现自己拿到的不是他点的那一份。
#: ★ 它与 `render_selected_skill_block` 里那句「取不到」分工不同：
#:   · 那里是 **prompt 已经构造出来**、只是技能正文取不到 ⇒ 模型能看见、
#:     由模型转述给用户；
#:   · 这里是 **prompt 根本没构造**（关键词短路抢在前面 / 工具环路不可用）
#:     ⇒ 模型没有任何机会知道这件事，只能由代码直接下发。
#:     两者都必须留痕，缺一个就有一条静默通道。
#: ★ 文案不含业务词（机制层有 AST 门禁）⇒ 对全部业务 Agent 通用。
SKILL_CHANNEL_UNAVAILABLE = (
    "你点名的这条技能没能执行：执行它需要模型工具环路，而它当前不可用"
    "（模型未启用、未配置，或工具层构建失败）。\n\n"
    "请检查模型配置后重试。我不会改用别的方式替你作答 —— "
    "那样你拿到的会是一份「不是你点的那份」的结果。"
)


def render_selected_skill_block(skill_name, text: Optional[str]) -> str:
    """渲染「被点名的技能」这一段（**取不到时显式说明，绝不静默跳过**）。

    `text` 是已经渲染好的技能正文（业务侧读取器给出的成品，
    通常已含自己的标题与配套工具清单）—— 本函数**再加标题会重复**，
    所以成功档只做拼接。

    ★ 返回空串**只**代表「本次没人点名」这一种情形。一旦有名字，就一定会
      返回一段文本，**包括"名字有、正文取不到"那一档**。
      这是本函数与 `render_skill_catalog` 的关键差别：目录取不到内容可以
      整段不注入（那只是少一份增益），点名取不到内容**必须留痕** ——
      否则"用户点了技能却没生效"在整条链路上完全不可见
      （同族判据：降级路径禁用「全 0」兜底，兜底值必须能被识别）。

    ★ 「取不到」的三种原因（未启用 / 不存在 / 不属于当前账号）在此**合并成
      一句**、不向模型区分：区分它们等于给出一条可枚举的探测通道
      （同族判据：「不存在」与「不属于你」必须给出同一响应）。
    """
    name = str(skill_name or "").strip()
    if not name:
        return ""
    body = str(text or "").strip()
    if not body:
        return (
            "%s\n\n"
            "**注意**：用户指定了技能 %r，但这条技能当前**取不到**"
            "（可能未启用、不存在、或不属于当前账号）。"
            "请按你原有的能力作答，并如实告知用户该技能当前不可用。"
            % (SELECTED_SKILL_GUIDE, name)
        )
    return "%s\n\n%s" % (SELECTED_SKILL_GUIDE, body)


__all__ = [
    "SkillDocument",
    "SkillReader",
    "SKILLS_GUIDE",
    "SELECTED_SKILL_GUIDE",
    "SKILL_CHANNEL_UNAVAILABLE",
    "bind_requested_skill",
    "build_skill_tools",
    "current_requested_skill",
    "is_skill_requested",
    "parse_skill_document",
    "register_skill_reader",
    "registered_skill_readers",
    "render_selected_skill_block",
    "render_skill_body",
    "render_skill_catalog",
    "render_skill_tools",
]
