"""「本次请求的**作用对象**」通道 —— 机制层（第 251 轮）。

==============================================================================
★ 它补的是什么洞
==============================================================================
实测（第 250 轮老板报告，已复现）：选品分析师里**没有**载入选品，点「上架建议」
卡片，系统却答「好的，我们已经确定了评估对象：<某个商品>」并按技能格式给出了
完整上架建议。而那个商品是**上一轮**对话里出现过的。

根因不是模型乱编，而是**前置条件没有真源**：

  · 前端把「本次针对谁」表达成**一句话**拼进用户消息
    （`（评估对象：X）` / `（未载入选品（…））`）；
  · 后端**既不解析、也不校验**这句话；
  · 点名技能时又强制走工具环路 ⇒ **带全量会话历史** ⇒
    历史里上一轮同一技能已确定过对象，模型就把它「续」了上来。

于是出现了一个很难看的状态：输出格式完美、商品名正确，
**唯一错的是「这个对象用户从没选过」**，而界面、日志、测试全绿。

本模块给出的是一条**结构化**通道：谁来告诉后端「本次作用对象是谁」，
就通过它，而不是通过一句自然的句子。

==============================================================================
★★ 为什么必须区分「没提供」与「明确没有」
==============================================================================
这两种状态在处置上完全相反，压成同一个 `None` 就有一条会永远错：

  · **没提供**（老客户端 / 其它 Agent / 测试）⇒ 本机制**不参与**，
    一段都不注入。凭空说一句「本次没有作用对象」会污染本来正常的对话。
  · **明确没有**（前端说「本次未载入选品」）⇒ **必须注入**，
    而且要写明「不得从历史里挑一个顶上」—— 这正是本洞的现场。

所以 `bind_context_target()` 收的不是 `Optional[dict]`，而是
`Optional[ContextTarget]`，并且 `None` 只表示前者、`specified=False` 表示后者。

==============================================================================
★ 为什么住机制层、又走 ContextVar
==============================================================================
与 `ai_infra.skills._REQUESTED_SKILL` 完全同源（同族先例共 6 个）：
写入点在业务模块的路由里，而业务模块之间不能顶层互相 import
⇒ 通道必须落在双方都已依赖的层；且 ContextVar 天然覆盖
「路由 → 图节点 → 工具」整条异步调用链，不必沿途每个函数多带一个参数。

★ 本模块的**四个出口**（一个机制要的全部零件，别在业务侧再补一份）
==============================================================================
  · `ContextTarget` / `ContextTargetPayload` —— 形状（内部视图 / 请求体视图）；
  · `context_target_payload(request)`        —— 请求体 → 原始载荷（**唯一解析**）；
  · `bind_context_target()` / `current_context_target()` —— 存取（请求级）；
  · `render_context_target_block()`          —— 渲染成一段**权威说明**。

  ★ 唯一不在本模块的是「注册」：`register_prompt_section()` 的调用点在
    `modules/context_target_section.py`（业务层）。这不是遗漏，是硬红线 ——
    机制层自己注册一段内容等于内容住进基础设施层（判据见
    `tests/test_memory_injection.py` 的 ①）。第 257 轮把该注册从选品模块
    上提到 `modules/` 根的公共注册点，本模块**一行都没动**。

★ 本模块的**字符串层零业务内容**（本仓对 `ai_infra` 的硬红线）：
  「类型 / 名称 / 标识」三个标签是通用的；具体是什么类型（候选选品 / 商品）
  由**调用方**填在 `label` 里。判据见 `tests/test_infra_layering.py`。
"""

from __future__ import annotations

import contextlib
import contextvars
import json
from dataclasses import dataclass, field
from typing import AsyncIterator, Optional

from pydantic import BaseModel, Field

__all__ = [
    "ContextTarget",
    "ContextTargetPayload",
    "bind_context_target",
    "context_target_payload",
    "current_context_target",
    "is_context_target_missing",
    "normalize_context_target",
    "render_context_target_block",
]


@dataclass(frozen=True)
class ContextTarget:
    """本次请求的作用对象（**结构化**，不是一句话）。

    :param specified: 用户本次**是否指定了**作用对象。
        `False` 是**一个有效值**（"本次明确没有指定"），不是"没数据" ——
        调用方拿它去挡「前置缺失仍执行」的路径。
    :param label: 人话的类型名（如「候选选品」）。由**业务侧**填，
        机制层只负责原样渲染 —— 于是本层不必认识任何业务词。
    :param title: 展示名（如商品标题）。
    :param ref: 机器可识别的标识（如 ASIN / 主键）。**判"有没有"只看 title/ref**。
    :param detail: 本次作用对象的**补充数据**（可选 dict）。由业务侧填，
        机制层**只原样渲染、不解析** —— 本层不认识任何业务字段（类目/价格/
        库存等），它们对机制层只是一张需要转述给模型的键值表。
        第 272 轮为「终检清单」类技能加的：此前只传 label/title/ref，
        模型拿不到要核对的字段（类目/五点/库存/价格），只能反过来问用户。
    """

    specified: bool
    label: str = ""
    title: str = ""
    ref: str = ""
    detail: Optional[dict] = None

    def as_dict(self) -> dict:
        """渲染用视图（不含 `specified`：它不是一个展示字段）。"""
        # ★ 第 346 轮：显式声明为 `dict` —— 原先是裸字面量，mypy 推断成
        #   `dict[str, str]`，随后 `out["detail"] = self.detail`（值是 dict）就报
        #   assignment。`as_dict()` 的返回注解本就是 `dict`，这里只是写实。
        out: dict = {"label": self.label, "title": self.title, "ref": self.ref}
        if self.detail:
            out["detail"] = self.detail
        return out


class ContextTargetPayload(BaseModel):
    """请求体里那个字段的**形状**（唯一定义，供各业务模块的请求模型复用）。

    ★ 为什么形状也归机制层，而不是某一个业务模块的 `schemas`：
      第 251 轮只有一条链路下发该字段，把它跟着那条链路的模块放没问题；
      一旦扩到多条链路，「每个模块各写一份同样的三个字段」立刻变成
      **同一形状的多份实现** —— 本仓反复咬过人的形态，且漂移方向恰好是
      某一侧少一个字段（少的那侧静默拿不到对象，不报任何错）。
      业务侧要做的只有一件事：往 `label` 里填**哪个词**。

    ★ 三态（**不能压成两态**，见模块 docstring）：
      · 整个字段不出现 ⇒ 本客户端未参与该机制（不注入任何提示段）；
      · 传 `null` ⇒ 本次**明确没有**对象；
      · `{...}` ⇒ 本次的作用对象。
      前两者在 Pydantic 取值上都是 `None`，靠 `model_fields_set` 区分 ——
      所以**不要**给这个字段任何非 None 默认值，否则第三态会消失。
    ★ 字段描述刻意不含任何业务词：本层是硬红线（见模块 docstring 末段）。
    """

    label: Optional[str] = Field(default=None, description="类型的人话名（由调用方填）")
    title: Optional[str] = Field(default=None, description="展示名")
    ref: Optional[str] = Field(default=None, description="机器可识别的标识")
    detail: Optional[dict] = Field(default=None, description="补充数据（机制层原样渲染，不解析）")


def _text(value) -> str:
    """统一成去空白的字符串；非字符串一律转成字符串再 strip（不抛）。"""
    if value is None:
        return ""
    return str(value).strip()


def normalize_context_target(payload) -> Optional[ContextTarget]:
    """把请求体里的原始值规范成 `ContextTarget`（**唯一**入口）。

    三种输入、三种结果 —— 三态分明是本模块的地基：

    ==========================  ==============================
    输入                         结果
    ==========================  ==============================
    `None`（字段不存在）         `None` ⇒ 本机制**不参与**
    `{}` / `{"label": "…"}`      `ContextTarget(specified=False)`
    含 title 或 ref              `ContextTarget(specified=True, …)`
    ==========================  ==============================

    ★ 「`specified` 由**内容**决定，不由调用方声明」：
      一个 label 是"候选选品"、title/ref 全空的对象，与"没有对象"在
      **可判定性**上没有区别（后端拿它既做不了前缀，也判不了归属）。
      让它算作 `specified=True` 等于把一句空话当真 —— 那正是本洞的形状。
    """
    if payload is None:
        return None
    if isinstance(payload, ContextTarget):
        return payload
    if isinstance(payload, str):
        # 容忍纯字符串（老调用方把标题直接丢进来）；空串 ⇒ 明确没有
        title = _text(payload)
        return ContextTarget(specified=bool(title), title=title)
    if not isinstance(payload, dict):
        # 没见过的东西不当成"有对象"（fail-closed 的一侧）
        return ContextTarget(specified=False)

    label = _text(payload.get("label"))
    title = _text(payload.get("title"))
    ref = _text(payload.get("ref"))
    detail = payload.get("detail")
    if not isinstance(detail, dict):
        detail = None
    return ContextTarget(
        specified=bool(title or ref), label=label, title=title, ref=ref, detail=detail
    )


def context_target_payload(request):
    """请求体 → 机制层的原始载荷（**唯一实现**：所有下发该字段的端点都用它）。

    端点里写的是 `bind_context_target(context_target_payload(request))` ——
    这一行是「本次请求带上对象」的全部动作，没有别的步骤。

    :return:
        · `None` —— 请求体里**没有**这个字段 ⇒ 本客户端未参与该机制；
        · `{}`   —— 传了 `null` ⇒ 本次**明确没有**对象；
        · `dict` —— 本次的作用对象。

    ★ 为什么要 `model_fields_set`：传 `null` 与"字段不存在"在取值上都是 `None`，
      只有 `model_fields_set` 记得住区别。少了这一步，「本次没有对象」会被读成
      "客户端没参与" ⇒ **门禁永不触发** —— 拦得住新客户端、拦不住老客户端，
      而两种客户端在界面上完全同形。

    ★ 为什么必须只有一处实现：第 251 轮只有一条链路做这件事；扩到多条链路的
      正确做法是**把它们都指向这里**，而不是每个端点抄一份。抄一份的代价不是
      "多几行"：漏掉 `model_fields_set` 那一次判断的版本**不会报任何错**，
      它只是安静地让门禁失效（本仓「同一判定两份实现 ⇒ 至少一份永远测不到」）。

    ★ 不做「取不到就退回默认值」的兜底：请求模型没有该字段是**编码错误**
      （写错模型 / 忘了给新端点加字段），必须当场炸，不能静默当成"没参与"。
    """
    if "context_target" not in request.model_fields_set:
        return None
    target = request.context_target
    return target.model_dump() if target is not None else {}


#: 「本次请求的作用对象」的请求级存储。
#:
#: 默认 `None` == **没人设置过** == 本客户端不参与该机制（见模块 docstring）。
_CONTEXT_TARGET: contextvars.ContextVar[Optional[ContextTarget]] = contextvars.ContextVar(
    "context_target", default=None
)


def current_context_target() -> Optional[ContextTarget]:
    """取本次请求的作用对象；`None` 表示**本客户端未提供**（非"没有对象"）。"""
    return _CONTEXT_TARGET.get()


def is_context_target_missing() -> bool:
    """「本次请求**没有**可用的作用对象」—— 供业务侧的 fail-closed 门禁调用。

    ★ 为什么要有这个具名判定、而不是各家自己写
      `(current_context_target() or ContextTarget(False)).specified`：
      本仓的「同一判定两份实现 ⇒ 至少一份永远测不到」是反复咬过人的形态。
      各业务模块要判的是**同一个问题**，判定必须只有一处。

    ★ 三种状态在这里收敛成两档，**且空档选在"缺失"这一侧**：
      · `None`（未提供）          ⇒ 缺失 —— 拿不到权威信息就不能假定有对象；
      · `specified=False`（明确没有）⇒ 缺失；
      · `specified=True`          ⇒ 不缺失。
      这一刀是**故意的安全失败方向**：把「不知道」判成「有」，就是本洞；
      判成「没有」的代价只是要求用户先选一个对象，可恢复。
    """
    target = _CONTEXT_TARGET.get()
    return target is None or not target.specified


@contextlib.asynccontextmanager
async def bind_context_target(target) -> AsyncIterator[None]:
    """在 `async with` 作用域内把「本次作用对象」置上，退出时**无条件还原**。

    :param target: `None` / dict / `ContextTarget` —— 一律过
        `normalize_context_target` 规范化，调用方不必自己判。

    ★ 必须有自己的作用域，不能"设了就不管"：ContextVar 的写入会顺着任务
      继承下去 —— 一次请求设过之后不复位，同进程后续请求会**继续沿用上一次
      的选择**（本仓真实咬过人的形态：跨身份残留的上下文）。
    ★ 用上下文管理器而不是裸 `set`/`reset`：路由里提前 return 或抛异常时，
      复位才不会漏（`finally` 语义由 `asynccontextmanager` 保证）。
    ★ **流式端点的写入点必须在生成器体内**，不能包在返回 `StreamingResponse`
      的外层语句上 —— 外层 `async with` 在生成器被第一次迭代之前就已经退出，
      那样等于根本没设（同族判据见 `ai_infra.skills.bind_requested_skill`）。
    """
    token = _CONTEXT_TARGET.set(normalize_context_target(target))
    try:
        yield
    finally:
        _CONTEXT_TARGET.reset(token)


def render_context_target_block(target: Optional[ContextTarget]) -> str:
    """把作用对象渲染成一段**权威说明**（没参与时返回空串，绝不静默塞内容）。

    这段的措辞承担一条判据：**只有本段算数，历史里的不算**。
    少了这句，模型就会像实测那样把上一轮的对象「续」上来 ——
    而且它看起来完全合理，因为它确实是这个会话里出现过的。
    """
    if target is None:
        return ""

    lines = ["## 本次请求的作用对象", ""]
    if target.specified:
        if target.label:
            lines.append(f"· 类型：{target.label}")
        if target.title:
            lines.append(f"· 名称：{target.title}")
        if target.ref:
            lines.append(f"· 标识：{target.ref}")
        if target.detail:
            lines.append("")
            lines.append("补充数据（本次作用对象的具体字段，可直接用于核对）：")
            for k, v in target.detail.items():
                if v is None or v == "":
                    continue
                # 值可能是标量 / list / dict：统一转成可读文本，不假设类型。
                if isinstance(v, (dict, list)):
                    v = json.dumps(v, ensure_ascii=False)
                lines.append(f"  - {k}: {v}")
        lines.append("")
        lines.append(
            "★ 上表就是**本次请求**指定的作用对象，**只认这一段**。"
            "对话历史里出现过的对象、结论、数字，都**不算**本次的作用对象 ——"
            "历史里出现过，不等于用户这一次又选了它。"
            "若需要历史的某个对象，先向用户确认，不要直接拿来用。"
        )
    else:
        lines.append("（无）")
        lines.append("")
        lines.append(
            "★ 用户在**本次请求**里没有指定作用对象。"
            "必须停下来向用户确认要针对哪个对象，"
            "**不得**从对话历史里挑一个顶上、也不得假装已经确定 ——"
            "历史里出现过不等于用户这一次选了它。"
        )
    return "\n".join(lines)
