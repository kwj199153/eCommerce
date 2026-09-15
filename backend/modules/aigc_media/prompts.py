"""AIGC 媒体 提示词（**业务资产**）。

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
因此 `self.get_prompt_template("aigc_media")` 无需改动。
"""
from ai_infra.llm import register_prompt_template

AIGC_MEDIA_PROMPT = """你是电商内容创作专家，擅长 AI 辅助的营销内容生成。
你的任务是生成高质量的产品文案、品牌故事、营销素材。

创作原则：
1. 转化导向：所有内容以促进购买为目标
2. 品牌一致性：保持统一的品牌调性和视觉风格
3. 本地化适配：针对目标市场文化优化表达
4. 合规安全：符合平台规则和广告法"""

# import 即注册（调用方与本模块同目录，保证在首次取用之前完成注册）
register_prompt_template("aigc_media", AIGC_MEDIA_PROMPT)

__all__ = ["AIGC_MEDIA_PROMPT"]
