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
    get_prompt_spec,
    registered_prompts,
    estimate_tokens,
    is_llm_parse_failed,
    LLM_PARSE_FAILED_KEY,
)
# ★ 第 283 轮 A 档：提示词规格（版本 / 指纹 / 变量契约）
from .prompt_spec import (  # noqa: E402  —— 与上面同包，放在后面只为阅读顺序
    PromptSpec,
    PromptSpecError,
    PromptVariableMissing,
    RenderedPrompt,
    extract_required_vars,
    render_prompt,
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
    "get_prompt_spec",
    "registered_prompts",
    "estimate_tokens",
    "is_llm_parse_failed",
    "LLM_PARSE_FAILED_KEY",
    "PromptSpec",
    "PromptSpecError",
    "PromptVariableMissing",
    "RenderedPrompt",
    "extract_required_vars",
    "render_prompt",
]
