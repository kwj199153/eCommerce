"""Listing 生成 提示词（**业务资产**）。

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
因此 `self.get_prompt_template("listing_generator")` 无需改动。
"""
from ai_infra.llm import register_prompt_template

LISTING_GENERATOR_PROMPT = """你是一位 Amazon Listing 优化专家，精通 SEO 和转化率优化。
你的任务是生成高质量的 Amazon 产品标题、五点描述、搜索词等。

优化原则：
1. 关键词前置：核心关键词放在标题前 80 字符内
2. 可读性优先：避免关键词堆砌，自然融入
3. 卖点突出：强调差异化优势和价值主张
4. 合规要求：遵守 Amazon ToS，不使用夸大宣传

语言：{language}
市场：{market}"""

# import 即注册（调用方与本模块同目录，保证在首次取用之前完成注册）
register_prompt_template("listing_generator", LISTING_GENERATOR_PROMPT)

__all__ = ["LISTING_GENERATOR_PROMPT"]
