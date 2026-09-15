"""广告分析 提示词（**业务资产**）。

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
因此 `self.get_prompt_template("ad_analysis")` 无需改动。
"""
from ai_infra.llm import register_prompt_template

AD_ANALYSIS_PROMPT = """你是 Amazon PPC 广告分析专家。
你的任务是诊断广告账户表现、识别浪费机会、提供优化建议。

分析维度：
- ACoS / RoAS / TACoS 表现
- 关键词表现分级（高效/浪费/机会/低量）
- 竞价策略建议
- 预算分配优化
- 异常检测（花费激增/转化下降）"""

# import 即注册（调用方与本模块同目录，保证在首次取用之前完成注册）
register_prompt_template("ad_analysis", AD_ANALYSIS_PROMPT)

__all__ = ["AD_ANALYSIS_PROMPT"]
