"""读口：把「**本次请求的作用对象**」接进 system prompt（第 251 轮建 · 第 257 轮上提）。

==============================================================================
★ 这条通道补的是什么
==============================================================================
与 `modules/skills/selected_skill_section.py` 是一对：那条告诉模型
「用户这次点了哪条技能」，这条告诉模型「**这次是冲着哪个对象来的**」。

缺了后者，模型只能从两处猜：用户消息里那句人话，或者**对话历史**。
实测（第 250 轮）它选了历史 —— 于是「没载入选品」的一轮，模型把上一轮
确定过的商品当作本次的评估对象，给出了一份格式完美、商品名正确的
上架建议，而那个商品用户从没选过。

==============================================================================
★ 三态分明（最要紧的判据，完整论证见 `ai_infra/context_target.py`）
==============================================================================
  · **本客户端未提供**（老客户端 / 其它 Agent / 测试）⇒ 返回**空串**。
    凭空写一句「本次没有作用对象」会污染本来正常的对话 —— 那是负增益。
  · **明确有对象**   ⇒ 注入对象三要素 + 「只认这一段，历史里的不算」。
  · **明确没有对象** ⇒ 注入「（无）」+ 「**不得**从历史里挑一个顶上」。

★ 判据为什么要求"明确没有"也注入：这正是本洞的现场形态。
  只注入"有对象"那一支，等于把最容易出错的一支留成静默 ——
  界面、日志、测试全绿，只有用户看出结论打在别的品上。

==============================================================================
★ 分工：渲染在机制层、注册在业务层（这条分工是硬红线）
==============================================================================
  · 渲染 `ai_infra.context_target.render_context_target_block`：措辞通用、
    零业务词，业务词（类型名如「候选选品」/「工作商品」）由**前端**随请求带上，
    机制层原样渲染 —— 于是 `ai_infra` 的字符串层保持零业务内容。
  · `register_prompt_section()` 的调用点**必须**在业务层：机制层自己注册一段
    内容等于内容住进基础设施层（判据见 `tests/test_memory_injection.py` 的 ①）。
  ⇒ 所以本文件存在，而不是把这两件事都塞进 `ai_infra/context_target.py`。
    这是**唯一**一份动机：本文件里没有一行渲染逻辑。

==============================================================================
★★ 第 257 轮：本文件为什么从 `modules/product_research/` 上提到 `modules/` 根
==============================================================================
起因（老板报障 + 截图）：选品分析师那一条链路的「上下文条」写着评估对象，
而**Listing 优化师 / AIGC 媒体生成器**都显示「（无上下文参数）」——
可这两个 Agent 同样要先选一个商品才能开工。

取证结论：**不是取舍，是疏漏**。第 251 轮建的这条链是五层结构，而五层
**全部**只在选品一条链路上接了线：

  ① 前端产出对象（`contextTarget` computed）
  ② 前端塞进请求体（`context_target`）
  ③ 后端端点绑定（`bind_context_target(...)`）
  ④ 本段注册（读口）
  ⑤ 前端上下文条文案

②③ 的接线本轮各自补到了 Listing / AIGC；而 **④ 的位置本身**是第 1 条病根：
注册写在 `modules/product_research/context_target_section.py` 里 —— 于是
「这条机制属于选品」成了一个看得见、却从未被声明的约定，谁也不会想到
去那个文件里给 Listing 加线。

上提后的形态：

  · 注册点 = **本文件**（`modules/` 根，横切位置，不隶属任何业务域）；
  · 触发点 = `modules/__init__.py` 的那一行 import（**任何**业务模块被 import
    都会先执行包初始化 ⇒ 注册必然发生，不再依赖"某个特定 Agent 的 router 被导入"）；
  · 渲染与形状仍留在 `ai_infra/context_target.py`（机制层，一行没动）。

★ 为什么不做成 `ai_infra` 里自注册：那会击穿上面那条硬红线。机制层"能不能自己
  注册一段"是**结构问题**，与"这一段有没有业务词"无关 —— 后者随时可能变。

==============================================================================
★ 为什么注册写在模块级、又套一层 `ensure_registered()`
==============================================================================
与 `modules/skills/selected_skill_section.py`、`modules/memory/prompt_section.py`
完全同源：注册是 import 副作用；而重名注册会 raise，`importlib.reload`
又是本仓测试的常规手段 ⇒ 直接裸写在模块级的话，reload 即崩。

★ 注册本身是**进程级**的：注册表是全局的，一旦本模块被 import，
  它对全部 Agent 都生效（对没下发该字段的 Agent 返回空串，无副作用）。

★ 谁参与本机制 ≠ 谁有拒答门禁（两件事，别混）
  · 参与（前端下发字段）：选品分析师 / Listing 优化师 / AIGC 媒体生成器 /
    客服（差评应对）；
  · 拒答门禁（`TARGET_REQUIRED_SKILLS`，前置缺失就不进 LLM）：**只有选品**。
  理由：选品那批候选类技能的正文逐字假定"对象已存在"，缺了就只能从历史里续；
  而 Listing / AIGC / 客服的关键词挖掘、类目分析、FAQ 检索这类技能是按类目
  或全市场作答的，对它们挂 fail-closed 是**误伤**（把一次正常提问变成一句拒答）。
  即：第 257 轮起对 Listing / AIGC、第 298 轮起对客服都是"**只注入、不拒答**"。
"""

from __future__ import annotations

from ai_infra.context_target import (
    current_context_target,
    render_context_target_block,
)
from ai_infra.prompt_sections import (
    PromptContext,
    register_prompt_section,
    registered_sections,
)

#: 注册名。与业务语义绑定的字符串只能出现在业务层
#: （`ai_infra` 的字符串层有零业务内容的硬门禁）。
SECTION_NAME = "request_context_target"


async def request_context_target_section(ctx: PromptContext) -> str:
    """把本次请求的作用对象渲染成一段注入文本。

    ★ `ctx`（身份）在这里**不参与判定**：作用对象是"本次请求选了谁"，
      与"谁在问"无关 —— 归属校验不在本段，而在取对象的那一刻
      （前端只会把**自己已校验过归属**的对象带上来）。
    """
    return render_context_target_block(current_context_target())


def ensure_registered() -> None:
    """幂等注册（理由见模块 docstring 末段）。"""
    if SECTION_NAME in registered_sections():
        return
    register_prompt_section(SECTION_NAME, request_context_target_section)


ensure_registered()


__all__ = [
    "SECTION_NAME",
    "request_context_target_section",
    "ensure_registered",
]
