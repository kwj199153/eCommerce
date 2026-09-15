"""
DashScope Qwen LLM 统一调用模块

支持能力：
- OpenAI-compatible 接口调用
- 流式/非流式输出
- 多模型切换 (qwen-max/qwen-plus/qwen-turbo)
- Token 统计 & 成本追踪
- 错误重试 & 降级
- Prompt 模板管理
"""

import os
import time
import json
import hashlib
from typing import Any, Optional, AsyncIterable, Dict, List, Union
from dataclasses import dataclass, field
from enum import Enum

import httpx

from core.logger import get_logger
from core.billing.llm_meter import record_llm_usage

logger = get_logger(__name__)


# ====== 配置 ======
def _load_config() -> Dict[str, Any]:
    """
    加载 LLM 全局配置。

    优先级：core.config.config（pydantic-settings 从 .env 读取）
            > os.getenv（进程环境变量）

    说明：pydantic-settings 会把 .env 读进 Settings 对象，但不会注入
    os.environ，因此直接 os.getenv 会读不到 .env 里的值（历史断链）。
    """
    cfg: Dict[str, Any] = {}
    try:
        from core.config import config as app_config
        cfg["api_key"] = app_config.dashscope_api_key or os.getenv("DASHSCOPE_API_KEY", "")
        cfg["default_model"] = app_config.llm_default_model or os.getenv("LLM_MODEL", "qwen-max")
        cfg["timeout"] = app_config.llm_timeout_seconds or int(os.getenv("LLM_TIMEOUT", "60"))
        # MAX_RETRIES 仅在 .env 中定义（config 无对应字段）
        cfg["max_retries"] = int(os.getenv("LLM_MAX_RETRIES", "3"))
    except Exception:
        cfg["api_key"] = os.getenv("DASHSCOPE_API_KEY", "")
        cfg["default_model"] = os.getenv("LLM_MODEL", "qwen-max")
        cfg["timeout"] = int(os.getenv("LLM_TIMEOUT", "60"))
        cfg["max_retries"] = int(os.getenv("LLM_MAX_RETRIES", "3"))

    cfg["base_url"] = os.getenv(
        "LLM_BASE_URL", "https://dashscope.aliyuncs.com/compatible-mode/v1"
    )
    return cfg


_CONFIG = _load_config()


class LLMConfig:
    """LLM 全局配置"""
    API_KEY: str = _CONFIG["api_key"]
    BASE_URL: str = _CONFIG["base_url"]
    DEFAULT_MODEL: str = _CONFIG["default_model"]
    TIMEOUT: int = int(_CONFIG["timeout"])
    MAX_RETRIES: int = int(_CONFIG["max_retries"])

    # Token 价格 (每千 token, 单位：元)
    PRICING: Dict[str, Dict[str, float]] = {
        "qwen-max": {"input": 0.02, "output": 0.06},
        "qwen-plus": {"input": 0.004, "output": 0.012},
        "qwen-turbo": {"input": 0.002, "output": 0.006},
        "qwen-long": {"input": 0.0005, "output": 0.0015},
    }


class ModelType(str, Enum):
    """支持的模型类型"""
    MAX = "qwen-max"          # 最强推理，复杂分析任务
    PLUS = "qwen-plus"        # 均衡性能，通用场景
    TURBO = "qwen-turbo"      # 快速响应，简单任务
    LONG = "qwen-long"        # 长文本，文档分析


@dataclass
class Message:
    """聊天消息"""
    role: str  # system/user/assistant
    content: str


@dataclass
class LLMResponse:
    """LLM 响应结果"""
    content: str
    model: str
    input_tokens: int = 0
    output_tokens: int = 0
    total_tokens: int = 0
    cost: float = 0.0
    latency_ms: float = 0.0
    finish_reason: str = ""
    raw_response: Optional[Dict] = None


@dataclass
class UsageStats:
    """使用统计"""
    total_calls: int = 0
    total_tokens: int = 0
    total_cost: float = 0.0
    errors: int = 0


# ====== Prompt 模板注册表（基础设施层只放**机制**，不放**内容**）======
# ★ 原先这里硬编码了 6 份业务提示词（选品 / Listing / 广告 / 客服 / 竞品 / AIGC），
#   等于把业务语义放在 `ai_infra`。现已下移到各业务模块的 `prompts.py`，
#   由它们在 **import 时**调用 `register_prompt_template()` 注册。
#   本模块只提供：注册表 + 读写接口（业务内容见 `modules/*/prompts.py`）。
PROMPT_TEMPLATES: Dict[str, str] = {}


def register_prompt_template(name: str, template: str) -> None:
    """注册一个 Prompt 模板（供业务模块在 import 时调用）。

    Args:
        name: 模板键（如 ``"customer_service"``）
        template: 模板正文（可含 ``{var}`` 占位符）
    """
    if not name or not template:
        raise ValueError("register_prompt_template: name / template 均不能为空")
    PROMPT_TEMPLATES[name] = template


def get_prompt_template(name: str, **kwargs) -> str:
    """按名取模板并填充占位符。

    ★ 未注册时**抛 KeyError**，不再返回空串。
      返回空串会让调用方拿着**空 system prompt** 去请求 LLM —— 不报错、不降级，
      症状是「回答风格突变 / 答非所问」，属静默失效。
      触发原因通常是：业务模块的 `prompts.py` 没被 import（注册未发生）。
    """
    if name not in PROMPT_TEMPLATES:
        raise KeyError(
            f"Prompt 模板 {name!r} 未注册。业务提示词在各业务模块的 `prompts.py`，"
            f"需 import 该模块以触发注册。当前已注册: {sorted(PROMPT_TEMPLATES)}"
        )
    template = PROMPT_TEMPLATES[name]
    if kwargs:
        try:
            return template.format(**kwargs)
        except KeyError as e:
            # 保留原语义：变量缺失只告警并返回未填充模板（不因少一个变量就整段失败）
            logger.warning(f"Missing template variable: {e}")
    return template



class DashScopeLLM:
    """
    DashScope Qwen LLM 客户端

    使用方式：
        llm = DashScopeLLM()
        response = llm.chat("你好")
        async for chunk in llm.chat_stream("讲个故事"):
            print(chunk, end="")
    """

    def __init__(
        self,
        model: str = None,
        temperature: float = 0.7,
        max_tokens: int = 2048,
        top_p: float = 0.9,
    ):
        self.model = model or LLMConfig.DEFAULT_MODEL
        self.temperature = temperature
        self.max_tokens = max_tokens
        self.top_p = top_p
        self._client: Optional[httpx.AsyncClient] = None
        self._stats = UsageStats()

    @property
    def client(self) -> httpx.AsyncClient:
        if self._client is None or self._client.is_closed:
            self._client = httpx.AsyncClient(
                timeout=httpx.Timeout(LLMConfig.TIMEOUT),
                headers={
                    "Authorization": f"Bearer {LLMConfig.API_KEY}",
                    "Content-Type": "application/json",
                },
            )
        return self._client

    async def close(self):
        if self._client and not self._client.is_closed:
            await self._client.aclose()

    # ====== 核心调用方法 ======

    async def chat(
        self,
        messages: Union[str, List[Message], List[Dict]],
        system_prompt: str = None,
        **kwargs,
    ) -> LLMResponse:
        """
        非流式对话

        Args:
            messages: 用户消息（字符串自动转为 user role）
            system_prompt: 系统提示词
            **kwargs: 覆盖默认参数 (temperature, max_tokens 等)
        Returns:
            LLMResponse 对象
        """
        start_time = time.time()

        # 构建消息列表
        formatted_messages = self._format_messages(messages, system_prompt)

        payload = {
            "model": kwargs.get("model", self.model),
            "messages": formatted_messages,
            "temperature": kwargs.get("temperature", self.temperature),
            "max_tokens": kwargs.get("max_tokens", self.max_tokens),
            "top_p": kwargs.get("top_p", self.top_p),
            "stream": False,
        }

        response = await self._call_with_retry(
            f"{LLMConfig.BASE_URL}/chat/completions",
            payload,
        )

        result = self._parse_response(response, start_time)
        self._update_stats(result)
        return result

    async def chat_stream(
        self,
        messages: Union[str, List[Message], List[Dict]],
        system_prompt: str = None,
        **kwargs,
    ) -> AsyncIterable[str]:
        """
        流式对话（逐 token 返回）

        Yields:
            文本片段
        """
        formatted_messages = self._format_messages(messages, system_prompt)

        payload = {
            "model": kwargs.get("model", self.model),
            "messages": formatted_messages,
            "temperature": kwargs.get("temperature", self.temperature),
            "max_tokens": kwargs.get("max_tokens", self.max_tokens),
            "top_p": kwargs.get("top_p", self.top_p),
            "stream": True,
            # 请求服务端在最后一个 chunk 返回 usage，便于精确计量
            "stream_options": {"include_usage": True},
        }

        full_content = ""
        stream_usage: Dict = {}
        start_time = time.time()

        async with self.client.stream(
            "POST",
            f"{LLMConfig.BASE_URL}/chat/completions",
            json=payload,
        ) as response:
            async for line in response.aiter_lines():
                if line.startswith("data: ") and line != "data: [DONE]":
                    try:
                        chunk = json.loads(line[6:])
                        # 部分兼容端点把 usage 放在最后一个 chunk
                        if chunk.get("usage"):
                            stream_usage = chunk["usage"] or {}
                        # ⚠️ 不能写 `chunk.get("choices", [{}])[0]`：
                        # 开了 `stream_options.include_usage=True` 后，**最后一个 chunk
                        # 的 `choices` 是空数组**（只带 usage）。`.get(key, default)` 的
                        # 默认值只在 key **缺失**时生效，key 存在但值为 `[]` → `[][0]` 越界。
                        # 实测后果：正文 8 个 chunk 已全部流给老板，最后解析 usage chunk 时
                        # 抛 IndexError，被上层 `llm_stream` 的 except 接住 →
                        # 在完整回答末尾甩一句 `[错误: list index out of range]`。
                        # 实证抓包：`{"choices": [], "usage": {...}}`（8 chunk 中恰有 1 个）。
                        choices = chunk.get("choices") or []
                        if not choices:
                            continue
                        delta = choices[0].get("delta") or {}
                        content = delta.get("content", "")
                        if content:
                            full_content += content
                            yield content
                    except json.JSONDecodeError:
                        continue

        # 记录统计
        latency = (time.time() - start_time) * 1000
        logger.info(f"Stream completed: {len(full_content)} chars, {latency:.0f}ms")

        # 计量：优先用服务端 usage，缺失则按字符数估算
        model = payload["model"]
        if stream_usage:
            input_tokens = int(stream_usage.get("prompt_tokens", 0) or 0)
            output_tokens = int(stream_usage.get("completion_tokens", 0) or 0)
        else:
            prompt_chars = sum(len(str(m.get("content", ""))) for m in formatted_messages)
            input_tokens = self._estimate_tokens(prompt_chars)
            output_tokens = self._estimate_tokens(len(full_content))

        record_llm_usage(
            input_tokens=input_tokens,
            output_tokens=output_tokens,
            cost=self._compute_cost(model, input_tokens, output_tokens),
            model=model,
        )

    # ====== 便捷方法 ======

    async def simple_chat(self, user_message: str, **kwargs) -> str:
        """简化接口：只返回文本"""
        response = await self.chat(user_message, **kwargs)
        return response.content

    async def structured_chat(
        self,
        user_message: str,
        system_prompt: str,
        output_format: str = "json",
        **kwargs,
    ) -> Union[Dict, List]:
        """
        结构化输出

        Args:
            output_format: "json" | "markdown_table" | "list"
        Returns:
            解析后的结构化数据
        """
        format_instruction = {
            "json": "请严格以 JSON 格式输出，不要包含其他文字。",
            "markdown_table": "请以 Markdown 表格格式输出。",
            "list": "请以列表格式输出，每项一行。",
        }.get(output_format, "")

        full_prompt = f"{system_prompt}\n\n{format_instruction}\n\n{user_message}"
        response = await self.chat(full_prompt, **kwargs)

        if output_format == "json":
            try:
                # 提取 JSON（处理可能的 markdown 包裹）
                text = response.content.strip()
                if text.startswith("```"):
                    text = text.split("\n", 1)[1].rsplit("```", 1)[0]
                return json.loads(text)
            except json.JSONDecodeError:
                logger.warning(f"Failed to parse JSON from LLM response")
                return {"raw_text": response.content}

        return response.content

    def get_prompt_template(self, name: str, **kwargs) -> str:
        """获取并填充 Prompt 模板。

        ★ 委托给模块级 `get_prompt_template()`，保证「缺键 → KeyError」的语义
          只有**一处**实现（原先类方法用 `.get(name, "")` 返回空串，与模块级
          函数会形成两套语义 ⇒ 又是「同一指标多套」）。
        """
        return get_prompt_template(name, **kwargs)

    # ====== 内部方法 ======

    def _format_messages(
        self,
        messages: Union[str, List[Message], List[Dict]],
        system_prompt: str = None,
    ) -> List[Dict]:
        """统一消息格式"""
        result = []

        if system_prompt:
            result.append({"role": "system", "content": system_prompt})

        if isinstance(messages, str):
            result.append({"role": "user", "content": messages})
        elif isinstance(messages, list):
            for msg in messages:
                if isinstance(msg, Message):
                    result.append({"role": msg.role, "content": msg.content})
                elif isinstance(msg, dict):
                    result.append(msg)
                else:
                    result.append({"role": "user", "content": str(msg)})
        else:
            result.append({"role": "user", "content": str(messages)})

        return result

    async def _call_with_retry(self, url: str, payload: Dict) -> Dict:
        """带重试的 API 调用"""
        last_error = None

        for attempt in range(LLMConfig.MAX_RETRIES):
            try:
                response = await self.client.post(url, json=payload)
                response.raise_for_status()
                return response.json()
            except httpx.HTTPStatusError as e:
                last_error = e
                if e.response.status_code == 429:  # Rate limit
                    wait = 2 ** attempt
                    logger.warning(f"Rate limited, waiting {wait}s...")
                    await asyncio.sleep(wait)
                elif e.response.status_code >= 500:  # Server error
                    await asyncio.sleep(1)
                else:
                    raise
            except Exception as e:
                last_error = e
                logger.error(f"LLM call error (attempt {attempt + 1}): {e}")
                await asyncio.sleep(1)

        self._stats.errors += 1
        raise RuntimeError(f"LLM call failed after {LLMConfig.MAX_RETRIES} retries: {last_error}")

    def _parse_response(self, data: Dict, start_time: float) -> LLMResponse:
        """解析 API 响应"""
        usage = data.get("usage", {})
        choices = data.get("choices", [{}])
        message = choices[0].get("message", {}) if choices else {}

        input_tokens = usage.get("prompt_tokens", 0)
        output_tokens = usage.get("completion_tokens", 0)
        model = data.get("model", self.model)

        cost = self._compute_cost(model, input_tokens, output_tokens)

        return LLMResponse(
            content=message.get("content", ""),
            model=model,
            input_tokens=input_tokens,
            output_tokens=output_tokens,
            total_tokens=input_tokens + output_tokens,
            cost=cost,
            latency_ms=(time.time() - start_time) * 1000,
            finish_reason=choices[0].get("finish_reason", "") if choices else "",
            raw_response=data,
        )

    @staticmethod
    def _compute_cost(model: str, input_tokens: int, output_tokens: int) -> float:
        """按模型定价计算成本（元）"""
        pricing = LLMConfig.PRICING.get(model, {"input": 0.01, "output": 0.03})
        cost = (input_tokens / 1000) * pricing["input"] + (output_tokens / 1000) * pricing["output"]
        return round(cost, 6)

    @staticmethod
    def _estimate_tokens(char_count: int) -> int:
        """
        无 usage 时的 token 估算（中文场景经验值）。

        qwen 系列对中文约 1 token ≈ 1.5 字符，这里做保守估计，
        仅用于流式接口服务端未返回 usage 时的兜底计量。
        """
        return max(1, int(char_count / 1.5)) if char_count else 0

    def _update_stats(self, response: LLMResponse):
        """更新使用统计"""
        self._stats.total_calls += 1
        self._stats.total_tokens += response.total_tokens
        self._stats.total_cost += response.cost
        # 记入请求级计费计量器（当前请求未开启计量时自动忽略）
        record_llm_usage(
            input_tokens=response.input_tokens,
            output_tokens=response.output_tokens,
            cost=response.cost,
            model=response.model,
        )

    @property
    def stats(self) -> UsageStats:
        return self._stats

    def reset_stats(self):
        self._stats = UsageStats()


# ====== 单例管理 ======
_instances: Dict[str, DashScopeLLM] = {}


def get_llm(model: str = None, **kwargs) -> DashScopeLLM:
    """获取 LLM 实例（按模型缓存）"""
    key = model or LLMConfig.DEFAULT_MODEL
    if key not in _instances:
        _instances[key] = DashScopeLLM(model=model, **kwargs)
    return _instances[key]


async def cleanup_llm():
    """清理所有 LLM 实例"""
    for instance in _instances.values():
        await instance.close()
    _instances.clear()


# 兼容 asyncio
import asyncio
