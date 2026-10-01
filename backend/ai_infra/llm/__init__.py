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
# ★ 第 351 轮 P0-7 B 档：提示词**覆写层**的应用侧（读表侧在 modules/prompt_versions）。
#   分两半的理由见该模块文件头：`ai_infra` 不得 import `modules.*`（硬红线），
#   所以「读表」住业务侧、「应用」住本侧，中间只过一个受控入口。
from .prompt_overrides import (  # noqa: E402
    PromptOverrideError,
    PromptOverrideRejected,
    applied_overrides,
    apply_override,
    describe_override,
    preview_override,
    registered_names,
    reset_override,
    source_fingerprint,
    validate_override,
    variables_of,
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
    "PromptOverrideError",
    "PromptOverrideRejected",
    "applied_overrides",
    "apply_override",
    "describe_override",
    "preview_override",
    "registered_names",
    "reset_override",
    "source_fingerprint",
    "validate_override",
    "variables_of",
]
