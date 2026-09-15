"""竞品监控 提示词（**业务资产**）。

★ 归属说明
原先这 6 份提示词硬编码在 `ai_infra/llm/dashscope_client.py` 的
`PROMPT_TEMPLATES` 里 —— 基础设施层因此承载了选品/Listing/广告/客服/竞品/AIGC
的业务语义。它既不会报错、也 grep 不到 `from modules`，是最容易被漏掉的一类
分层泄漏（本仓已按「维度 15.11」三层查法收敛）。

现在分工：

    基础设施层（`ai_infra/llm`）→  只提供**机制**：
                                  `PROMPT_TEMPLATES` 注册表
                                  `register_prompt_template(name, text)`
                                  `get_prompt_template(name, **kwargs)`
    业务层（本模块）            →  **内容**：提示词正文

本模块在 **import 时**即注册；调用方（同目录的 agent）import 本模块即生效，
因此 `self.get_prompt_template("competitor_intel")` 无需改动。
"""
from ai_infra.llm import register_prompt_template

COMPETITOR_INTEL_PROMPT = """你是竞品情报分析专家。
你的任务是监控竞争对手动态、分析市场格局、提供竞争策略建议。

分析维度：
- 价格策略与变动趋势
- Listing 变化（图片、标题、描述）
- 评论情感与痛点
- 新进入者威胁
- Buy Box 竞争态势"""

# import 即注册（调用方与本模块同目录，保证在首次取用之前完成注册）
register_prompt_template("competitor_intel", COMPETITOR_INTEL_PROMPT)

__all__ = ["COMPETITOR_INTEL_PROMPT"]
