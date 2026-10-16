"""店铺术语表 —— 把用户固化的译法注入划词提示词（第 369 轮 P0）。

━━━ 它解决什么 ━━━
`prompts.py` 的 `AIGC_SELECTION_TRANSLATE_SYSTEM` 第 5 条已经写了「专业术语按中国
电商惯例（Noise Cancelling → 主动降噪 …）」，但那是**通用**惯例。真实店铺有自己的
固定叫法（自家品牌的中文名、「Gift Box」在本店一律叫「礼盒装」而不是「礼品盒」），
通用惯例覆盖不到，表现为**同一批文案里同一个词两种译法**。

术语表就是给这个洞打补丁：用户在设置页写死 `原文=译文`，划词时随请求带上，
由本模块渲染成提示词里的一段**硬约束**。

━━━ 契约（三条，改实现前先看这里）━━━
1. **空表 ⇒ 渲染出空串**（连标题都不拼）⇒ 提示词与「术语表上线前」**逐字相同**。
   基线是实测取的，不是手写的：见 `.workbuddy/probes/r369/baseline_prompt.py`
   的输出（`目标语言：{名}\\n上下文：{ctx}\\n\\n原文：\\n{text}`）。
   这条同时是「没配术语表的用户零成本、零行为变化」的保证。
2. **术语表是 user prompt 的一段，不进 system prompt**。
   `register_prompt_template` 会**按正文反解** `{var}` 占位符并在缺变量时抛
   `PromptVariableMissing`；把 `{glossary}` 写进 system 模板 ⇒ 全仓所有调用方都被
   迫传参，且提示词指纹会因一个默认空串而变化。放 user prompt 段既动态又不扰指纹。
3. **解析是宽松的、渲染是确定的**：非法行跳过（不报错、不注入），同名词取首次出现，
   条数有上限。理由见 `parse_glossary` docstring。

━━━ 为什么整个提示词拼装也住这里，而不是留在 agent ━━━
`agent_aigc.py` 在体量棘轮冻结表里（`tests/test_source_size_ratchet.py`，冻结值
**1849**），而本轮开工时它实测**恰好 1849 行 —— 零余量**：给它加一行 `glossary`
参数就会红。所以本模块同时承载 `build_selection_prompt`，让 agent 那边的改动变成
「去掉 4 行拼装 + 加 1 行参数 + 加 1 行 import」= **净减 2 行**。
本仓对这类「逻辑需要一个家」的既有范式是**外移模块 + 顶层函数 + 显式传参**
（同目录 `lang_guard.py` / `asset_gen.py` / `image_client.py` 是同一手法）。
本模块**不 import 任何项目模块**（连 agent 都不碰，全是纯函数）⇒ 不可能有循环导入，
且可以在不建 Agent 实例的前提下被测试。

━━━ 判据只住一处 ━━━
本模块**不做语言判定**（那是 `AIGCMediaAgent.detect_lang` 的职责）、**不做同语言短路**
（那是 `lang_guard` 的职责）。它只做「文本 → 提示词」这一件事。
"""

from __future__ import annotations

from typing import List, Tuple

#: 单次注入的术语条数上限。防呆：设置页是一个自由文本域，贴错一份大 CSV 进来
#: 会让每次划词都多烧一大段 token，而划词的核心价值恰恰是「快」。
MAX_ENTRIES = 100

#: `原文=译文` 的分隔符。半角与全角都认 —— 中文输入法下 `＝` 是很容易打出来的。
_SEPARATORS = ("=", "＝")

#: 渲染出的段落标题。措辞刻意写「必须采用」而不是「参考」：术语表的价值就在于
#: 它**压过**第 5 条的一般惯例，写成「参考」模型会两头兼顾，等于没用。
_BLOCK_TITLE = "术语表（以下为本店固定译法，必须采用，优先于通用惯例）："


def parse_glossary(raw: str) -> List[Tuple[str, str]]:
    """把设置页的文本解析成 `[(原文, 译文), ...]`。

    格式（每行一条，与老板自用划词翻译扩展的术语表口径一致）：:

        # 注释行（以 # 开头，可用来分组标注）
        Noise Cancelling=主动降噪
        Gift Box＝礼盒装

    ★ 为什么**宽松跳错**而不抛异常：这一段的输入是用户在设置页手打的自由文本，
      一行打错就整表失效、还让划词直接报错，是把用户的笔误升级成故障。
      跳过的行不会静默——设置页的预览区会显示「已识别 N 条」（消费方口径见前端
      `utils/glossary.ts`）。
    ★ 为什么同名词**取首次出现**：用户刻意把新写法写在上面（覆盖下面误留的旧行）是
      更常见的用法；取最后一条则要让用户逐行删除历史残留。
    ★ 空原文/空译文**不算一条**：`=foo` / `foo=` 这类残行渲染成 `-  → foo` 只会
      污染提示词。
    """
    entries: List[Tuple[str, str]] = []
    seen = set()
    for line in (raw or "").splitlines():
        body = line.strip()
        if not body or body.startswith("#"):
            continue
        for sep in _SEPARATORS:
            idx = body.find(sep)
            if idx > 0:
                src, dst = body[:idx].strip(), body[idx + len(sep):].strip()
                if src and dst and src not in seen:
                    seen.add(src)
                    entries.append((src, dst))
                break
        if len(entries) >= MAX_ENTRIES:
            break
    return entries


def render_glossary_block(raw: str) -> str:
    """渲染成提示词里的一段；**表空时返回空串**（连标题都不拼）。

    返回串自带尾部的空行，因此调用方只需把它插在「上下文」与「原文」之间，
    两种情况下（有表 / 无表）排版都正确 —— 空串时衔接出的还是原来的
    `\\n\\n原文：`（见模块 docstring 契约 1）。
    """
    entries = parse_glossary(raw)
    if not entries:
        return ""
    lines = [f"- {src} → {dst}" for src, dst in entries]
    return _BLOCK_TITLE + "\n" + "\n".join(lines) + "\n\n"


def build_selection_prompt(
    target_name: str,
    context: str,
    text: str,
    glossary: str = "",
) -> str:
    """拼出划词翻译的 user prompt。

    `glossary` 缺省为空 ⇒ 输出与第 369 轮之前**逐字相同**（契约 1）。

    Args:
        target_name: 目标语言的**中文名**（如「简体中文」）—— 语言名到中文名的映射
            仍住 `AIGCMediaAgent._LANG_NAMES`，本模块不复制一份。
        context: 翻译上下文（如 `ecommerce` / `listing`）。
        text: 待翻译原文。
        glossary: 术语表原始文本（设置页原文，未解析）。
    """
    return (
        f"目标语言：{target_name}\n"
        f"上下文：{context}\n\n"
        f"{render_glossary_block(glossary)}"
        f"原文：\n{text}"
    )
