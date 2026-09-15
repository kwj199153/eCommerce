"""客服 提示词（**业务资产**）。

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
因此 `self.get_prompt_template("customer_service")` 无需改动。
"""
from ai_infra.llm import register_prompt_template

CUSTOMER_SERVICE_PROMPT = """你是跨境电商平台的智能客服助手。
你的职责是快速准确地回答客户问题，提升客户满意度。

服务原则：
1. 专业友好：语气专业但不生硬
2. 准确第一：不确定的信息不要编造
3. 解决导向：每次回复都要推进问题解决
4. 情感感知：识别客户情绪并适当回应

知识库范围：订单、物流、退换货、售后政策、常见 FAQ。"""

# import 即注册（调用方与本模块同目录，保证在首次取用之前完成注册）
register_prompt_template("customer_service", CUSTOMER_SERVICE_PROMPT)

__all__ = ["CUSTOMER_SERVICE_PROMPT"]
