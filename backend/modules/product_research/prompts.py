"""选品分析 提示词（**业务资产**）。

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
因此 `self.get_prompt_template("product_research")` 无需改动。
"""
from ai_infra.llm import register_prompt_template

PRODUCT_RESEARCH_PROMPT = """你是一位资深的跨境电商选品分析师，专注于 {market} 市场。
你的任务是帮助卖家发现高潜力产品机会、评估市场竞争力。

分析原则：
1. 数据驱动：基于搜索量、竞争度、利润率等量化指标
2. 趋势洞察：识别季节性趋势和新兴需求
3. 风险意识：标注潜在风险（专利、合规、物流等）

请用中文回答，输出结构化结果。"""

# import 即注册（调用方与本模块同目录，保证在首次取用之前完成注册）
register_prompt_template("product_research", PRODUCT_RESEARCH_PROMPT)

__all__ = ["PRODUCT_RESEARCH_PROMPT"]
