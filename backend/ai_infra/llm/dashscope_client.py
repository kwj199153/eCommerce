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
from core.metering.llm_meter import record_llm_usage
# ★ P0-1（2026-09-16）：指标写入。本文件是**所有 Agent 的 LLM 唯一出口**
#   （base_agent.py / rag/hybrid_engine.py 都经 get_llm() 拿到 DashScopeLLM），
#   所以在这里埋点 = 一处覆盖全部调用方，业务模块一行都不用改。
from core.observability.metrics import LLM_CALLS, LLM_TOKENS
# ★ P0-3（2026-09-16）：重试策略收敛到 core/resilience.py（唯一真源）。
#   修复前本文件自己抄了一套 _call_with_retry，而**同一个文件的 chat_stream
#   完全没有任何重试** —— 策略知识没有落点，同一个文件里都能不一致。
from core.resilience import RetryPolicy, call_with_retry, retrying_stream

logger = get_logger(__name__)

def estimate_tokens(char_count: int) -> int:
    """字符数 → token 数的**估算**（中文场景经验值，**唯一真源**）。

    ★ 这是估算，**不是计费口径**：计费一律优先用服务端返回的 `usage`
      （见 `chat` / `chat_stream` 里的 `record_llm_usage` 调用点）。
      估算只在两种场合使用：
        ① 服务端没给 `usage` 时的兜底计量；
        ② 需要**在不发请求的前提下**预判输入大小 —— 上下文裁剪
           （`ai_infra.context.trim_history`）就是靠它做决策。

    口径：qwen 系列对中文约 1 token ≈ 1.5 字符，取下界估计（宁可高估 token）。
      · 0 字符 ⇒ 0（空内容不产生消耗）
      · 非空至少 1（否则「很短但非空」会被算成 0，让预算与裁剪判定失真）

    ★ 第 147 轮 · 批 C4：从 `DashScopeLLM._estimate_tokens` 提升而来。
      提升的原因是它开始有**第二个消费者**（上下文裁剪）；把口径留在私有方法里
      会逼着调用方要么直打私有实现、要么自己再写一份 —— 两条路都在制造问题。
    """
    return max(1, int(char_count / 1.5)) if char_count else 0



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


# ★ P0-3：本客户端的重试策略。
#   attempts 沿用 LLM_MAX_RETRIES，口径 = **总尝试次数**（不是"重试次数"）——
#   写成"重试 3 次"会变成 4 次调用，这是最容易埋进去的语义偏差。
#   429/5xx 重试并指数退避（1s→2s→4s…，上限 30s）；其余 4xx 立即失败：
#   请求体不合法/Bad key 这类确定性错误重试多少次都是一样的结果，只烧配额。
_RETRY_POLICY = RetryPolicy(
    attempts=max(1, LLMConfig.MAX_RETRIES),
    base_delay=1.0,
    multiplier=2.0,
    max_delay=30.0,
)


def _emit_llm_metrics(
    model: Optional[str],
    status: str,
    *,
    input_tokens: int = 0,
    output_tokens: int = 0,
) -> None:
    """
    LLM 指标的**唯一写入点**（★ P0-1，2026-09-16）。

    修复前的状态（第 94 轮横切审计实测）：
        `LLM_CALLS` / `LLM_TOKENS` 在 metrics.py 里定义、
        在 observability/__init__.py 里导出、在 _REGISTRY 里注册，
        而**全仓 0 个 `.inc()`**。连 `main.py::_probe_llm` 的 docstring 都写着
        "模型是否可用由 llm_calls_total{{status="error"}} 反映" ——
        那个指标永远是 0，也就是**文档引用了一个根本不存在的数据源**。
        这属于项目里"假门禁"的同一形态，只不过它长在可观测性模块自己身上。

    标签口径（一句话定死，避免各处各写一套）::

        llm_calls_total{{model, status}}      status ∈ {{"success", "error"}}
        llm_tokens_total{{model, direction}}  direction ∈ {{"input", "output"}}

    ★ token 为 0 时**不写** LLM_TOKENS：让"这条路径漏了埋点"表现为
      "时间序列不存在"，而不是"值恒为 0"。后者会被当成"真的没消耗"，
      前者查 /metrics 一眼就能看出来 —— 静默的 0 比缺失更难发现。
    """
    label = model or "unknown"
    LLM_CALLS.inc(model=label, status=status)
    if input_tokens:
        LLM_TOKENS.inc(float(input_tokens), model=label, direction="input")
    if output_tokens:
        LLM_TOKENS.inc(float(output_tokens), model=label, direction="output")


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

        try:
            response = await self._call_with_retry(
                f"{LLMConfig.BASE_URL}/chat/completions",
                payload,
            )
        except Exception:
            # ★ P0-1：失败也要计数 —— 否则 `status="error"` 这条时间序列
            #   永远不存在，"失败率"这个唯一有用的告警信号就无从计算。
            _emit_llm_metrics(payload["model"], "error")
            raise

        result = self._parse_response(response, start_time)
        self._update_stats(result)   # ← 成功指标在 _update_stats 里打
        return result

    async def chat_stream(
        self,
        messages: Union[str, List[Message], List[Dict]],
        system_prompt: str = None,
        **kwargs,
    ) -> AsyncIterable[str]:
        """
        流式对话（逐 token 返回）

        ★ P0-3（2026-09-16）：**建立连接**这一步现在会重试。
          修复前的事实：同一个文件的 `chat()` 有重试、`chat_stream()` **没有** ——
          流式接口遇到一次连接抖动就直接失败，非流式却会自己恢复。

          只重试"拿到响应头"那一步：正文一旦开始流给上层就**永不重试**
          （否则会把用户已经看到的正文再发一遍，比干脆失败更难排查）。
          详见 `core/resilience.retrying_stream` 的 docstring。

        Yields:
            文本片段
        """
        formatted_messages = self._format_messages(messages, system_prompt)

        # ★ P0-1：提前取 model —— 失败路径也要能打指标（model 是标签之一）
        model = kwargs.get("model", self.model)
        payload = {
            "model": model,
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

        try:
            # ★ P0-3：只重试"建立连接"这一步（拿到响应头之前）。
            async with retrying_stream(
                lambda: self.client.stream(
                    "POST",
                    f"{LLMConfig.BASE_URL}/chat/completions",
                    json=payload,
                ),
                policy=_RETRY_POLICY,
                what=f"LLM stream ({model})",
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

        except Exception:
            # ★ P0-1：失败也要计数 —— 否则 `status="error"` 这条时间序列
            #   永远不存在，"LLM 失败率"这个唯一有用的告警信号无从计算。
            #   ★ 只会接住**本生成器自己**抛出的异常：消费方（上层 SSE 转发）
            #   的异常不经过这里；生成器被关闭时抛的是 GeneratorExit
            #   （BaseException，不被 Exception 捕获），语义正确。
            _emit_llm_metrics(model, "error")
            raise

        # 记录统计
        latency = (time.time() - start_time) * 1000
        logger.info(f"Stream completed: {len(full_content)} chars, {latency:.0f}ms")

        # 计量：优先用服务端 usage，缺失则按字符数估算
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
        # ★ P0-1：流式成功指标出口（与非流式共用同一个写入点，保证标签口径一致）
        _emit_llm_metrics(
            model,
            "success",
            input_tokens=input_tokens,
            output_tokens=output_tokens,
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
        """
        带重试的 API 调用。

        ★ P0-3（2026-09-16）：重试**逻辑**已收敛到 `core/resilience.py`，
          这里只保留三件本客户端特有的事：

            ① 组装"一次调用"（`_once`）—— 传**工厂**而不是协程对象，
               因为协程只能 await 一次，第二次重试会撞
               `cannot reuse already awaited coroutine`；
            ② 用本客户端的策略（`_RETRY_POLICY`，次数取自 LLM_MAX_RETRIES）；
            ③ 失败时把本地 `_stats.errors` 计数 +1，并把异常包装成调用方
               （`ai_infra/llm/integration.py`）一直依赖的那句话 ——
               它会被写进"降级到 mock"的原因里给用户看，保持原文避免可读性回退。

        ⚠️ 与修复前的一处**有意**的行为扩大：非重试类 4xx（如 400/401）现在
          也会让 `_stats.errors` +1。修复前只有"重试耗尽"才计数，
          于是配置错误（Bad key）连错误计数都不涨 —— 那才是真正要报警的情况。
        """

        async def _once() -> Dict:
            response = await self.client.post(url, json=payload)
            response.raise_for_status()
            return response.json()

        try:
            return await call_with_retry(
                _once,
                policy=_RETRY_POLICY,
                what=f"LLM call ({payload.get('model')})",
                wrap=lambda attempts, exc: RuntimeError(
                    f"LLM call failed after {attempts} retries: {exc}"
                ),
            )
        except Exception:
            self._stats.errors += 1
            raise

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
        """【兼容包装】真源已提升为模块级 `estimate_tokens`（第 147 轮 · 批 C4）。

        ★ 保留这个私有名的唯一理由：`tests/test_llm_client.py::test_estimate_tokens`
          直接钉住了它（`DashScopeLLM._estimate_tokens(150) == 100`）。
          它**不构成第二份实现** —— 只有一行转发，口径永远只有一处。
        ★ 新增调用方请用模块级 `estimate_tokens`，不要直打私有名。
        """
        return estimate_tokens(char_count)

    def _update_stats(self, response: LLMResponse):
        """更新使用统计"""
        # ★ P0-1：非流式调用的**成功指标出口** —— `chat()` 成功时唯一会走到这里。
        #   放在这里而不是 chat() 里，是为了让"记本地 stats"与"记全局指标"
        #   始终成对发生（少写一个就少一半信息，而没人会发现）。
        _emit_llm_metrics(
            response.model,
            "success",
            input_tokens=response.input_tokens,
            output_tokens=response.output_tokens,
        )
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

