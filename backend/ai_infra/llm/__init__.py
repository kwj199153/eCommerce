"""
LLM 模块初始化 & 工厂
"""

from .dashscope_client import (
    DashScopeLLM,
    LLMConfig,
    ModelType,
    Message,
    LLMResponse,
    UsageStats,
    get_llm,
    cleanup_llm,
    PROMPT_TEMPLATES,
    register_prompt_template,
    get_prompt_template,
)

__all__ = [
    "DashScopeLLM",
    "LLMConfig",
    "ModelType",
    "Message",
    "LLMResponse",
    "UsageStats",
    "get_llm",
    "cleanup_llm",
    "PROMPT_TEMPLATES",
    "register_prompt_template",
    "get_prompt_template",
]
