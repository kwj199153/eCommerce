"""
Agent LLM 集成混入类

为所有业务 Agent 提供 LLM 调用能力的统一接口。
支持：
- 自动 LLM 调用（带缓存和降级）
- RAG 检索增强（可选）
- 流式输出代理
- Token 用量统计

使用方式：
    from ai_infra.llm.integration import LLMEnabledAgent

    class MyAgent(LLMEnabledAgent):
        async def my_analysis(self, query):
            # 使用 LLM 增强分析
            result = await self.llm_call(
                prompt=f"分析: {query}",
                system_prompt=self.get_prompt_template("my_domain"),
                output_format="json",
            )
            return result
"""

import json
import time
from typing import Any, Optional, Dict, List, Union
from dataclasses import dataclass

from core.logger import get_logger

logger = get_logger(__name__)


@dataclass
class LLMCallResult:
    """LLM 调用结果"""
    success: bool
    content: Union[str, Dict, List] = ""
    raw_text: str = ""
    tokens_used: int = 0
    cost: float = 0.0
    latency_ms: float = 0.0
    fallback: bool = False       # 是否使用了降级响应
    error: Optional[str] = None


class LLMEnabledAgent:
    """
    LLM 能力混入类

    提供统一的 LLM 调用接口，支持自动降级到模拟响应。
    """

    # 子类可覆盖这些配置
    DEFAULT_MODEL: str = "qwen-plus"     # 默认模型（均衡性能）
    ANALYSIS_MODEL: str = "qwen-max"      # 复杂分析任务模型
    ENABLE_LLM: bool = True              # 总开关（关闭则全部走模拟）
    ENABLE_RAG: bool = False             # 是否启用 RAG（客服等场景）
    FALLBACK_TO_MOCK: bool = True        # LLM 失败时是否降级

    def __init__(self):
        self._llm_client = None
        self._rag_engine = None
        self._llm_stats = {
            "total_calls": 0,
            "llm_calls": 0,
            "mock_calls": 0,
            "errors": 0,
            "total_tokens": 0,
            "total_cost": 0.0,
        }

    @property
    def llm_client(self):
        """懒加载 LLM 客户端"""
        if self._llm_client is None and self.ENABLE_LLM:
            try:
                from ai_infra.llm import get_llm
                self._llm_client = get_llm(model=self.DEFAULT_MODEL)
            except Exception as e:
                logger.warning(f"[{getattr(self, 'agent_name', 'Agent')}] LLM init failed: {e}")
        return self._llm_client

    @property
    def rag_engine(self):
        """懒加载 RAG 引擎（仅当 ENABLE_RAG=True 时）"""
        if self._rag_engine is None and self.ENABLE_RAG:
            try:
                from ai_infra.rag import HybridRAGEngine, KnowledgeBaseBuilder
                import asyncio

                domain = getattr(self, 'agent_name', 'default').replace(" ", "_")
                self._rag_engine = HybridRAGEngine(domain=domain)

                # 异步初始化（如果事件循环已在运行）
                try:
                    loop = asyncio.get_event_loop()
                    if loop.is_running():
                        # 在异步上下文中，需要用 create_task
                        pass  # 由调用方负责初始化
                    else:
                        loop.run_until_complete(self._rag_engine.initialize())
                except RuntimeError:
                    pass  # 事件循环未运行，稍后初始化

            except Exception as e:
                logger.warning(f"[{getattr(self, 'agent_name', 'Agent')}] RAG init failed: {e}")
        return self._rag_engine

    async def initialize_rag(self, faq_items: List[Dict] = None):
        """
        初始化 RAG 引擎并加载知识库

        Args:
            faq_items: FAQ 列表 [{"question": "...", "answer": "...", "category": "..."}]
        """
        if not self.ENABLE_RAG or not self.rag_engine:
            return

        try:
            await self.rag_engine.initialize()

            if faq_items:
                count = await self.rag_engine.add_faq_knowledge_base(faq_items)
                logger.info(f"[{getattr(self, 'agent_name', 'Agent')}] RAG loaded {count} FAQ entries")
            else:
                # 尝试从预置知识库加载
                from ai_infra.rag import KnowledgeBaseBuilder
                if hasattr(KnowledgeBaseBuilder, 'CUSTOMER_SERVICE_FAQ'):
                    count = await KnowledgeBaseBuilder.build_customer_service_kb(self.rag_engine)
                    logger.info(f"[{getattr(self, 'agent_name', 'Agent')}] RAG loaded default KB: {count} entries")

        except Exception as e:
            logger.error(f"[{getattr(self, 'agent_name', 'Agent')}] RAG init error: {e}")

    # ====== 核心 LLM 调用方法 ======

    async def llm_chat(
        self,
        user_message: str,
        system_prompt: str = None,
        model: str = None,
        temperature: float = 0.7,
        max_tokens: int = 2048,
        **kwargs,
    ) -> LLMCallResult:
        """
        标准 LLM 对话调用

        Returns:
            LLMCallResult (success/content/fallback/error)
        """
        start_time = time.time()
        self._llm_stats["total_calls"] += 1

        # 检查 LLM 是否可用
        if not self.ENABLE_LLM or not self.llm_client:
            return self._mock_result(user_message, "LLM disabled")

        try:
            response = await self.llm_client.chat(
                user_message,
                system_prompt=system_prompt,
                model=model,
                temperature=temperature,
                max_tokens=max_tokens,
                **kwargs,
            )

            latency = (time.time() - start_time) * 1000
            self._update_llm_stats(response.total_tokens, response.cost, latency)

            return LLMCallResult(
                success=True,
                content=response.content,
                raw_text=response.content,
                tokens_used=response.total_tokens,
                cost=response.cost,
                latency_ms=latency,
                fallback=False,
            )

        except Exception as e:
            logger.error(f"[{getattr(self, 'agent_name', 'Agent')}] LLM call error: {e}")
            self._llm_stats["errors"] += 1

            if self.FALLBACK_TO_MOCK:
                return self._mock_result(user_message, str(e))
            return LLMCallResult(
                success=False,
                error=str(e),
                latency_ms=(time.time() - start_time) * 1000,
            )

    async def llm_structured(
        self,
        user_message: str,
        system_prompt: str,
        output_format: str = "json",
        model: str = None,
        **kwargs,
    ) -> LLMCallResult:
        """
        结构化输出调用（JSON/表格/列表）

        Returns:
            LLMCallResult (content 是解析后的 dict/list)
        """
        if not self.ENABLE_LLM or not self.llm_client:
            return self._mock_result(user_message, "LLM disabled", structured=True)

        try:
            result = await self.llm_client.structured_chat(
                user_message=user_message,
                system_prompt=system_prompt,
                output_format=output_format,
                model=model or self.ANALYSIS_MODEL,
                **kwargs,
            )

            return LLMCallResult(
                success=True,
                content=result,
                raw_text=json.dumps(result, ensure_ascii=False) if isinstance(result, (dict, list)) else str(result),
                fallback=False,
            )

        except Exception as e:
            logger.error(f"[{getattr(self, 'agent_name', 'Agent')}] Structured LLM error: {e}")
            self._llm_stats["errors"] += 1

            if self.FALLBACK_TO_MOCK:
                return self._mock_result(user_message, str(e), structured=True)
            return LLMCallResult(success=False, error=str(e))

    async def llm_rag_answer(
        self,
        query: str,
        system_prompt: str = None,
        top_k: int = 3,
    ) -> LLMCallResult:
        """
        RAG 增强回答（先检索再生成）

        仅在 ENABLE_RAG=True 且 RAG 引擎已初始化时生效，
        否则退化为普通 LLM 调用。
        """
        start_time = time.time()
        self._llm_stats["total_calls"] += 1

        if not self.ENABLE_RAG or not self.rag_engine:
            # 无 RAG → 普通调用
            return await self.llm_chat(query, system_prompt=system_prompt)

        try:
            from ai_infra.rag import RAGResponse

            rag_response: RAGResponse = await self.rag_engine.answer(
                query=query,
                llm_client=self.llm_client,
                system_prompt=system_prompt,
                top_k=top_k,
            )

            latency = (time.time() - start_time) * 1000

            return LLMCallResult(
                success=True,
                content=rag_response.answer,
                raw_text=rag_response.answer,
                fallback=rag_response.fallback,
                latency_ms=latency,
                # 将 sources 附加到 metadata
                _sources=[
                    {"doc_id": s.document.doc_id, "score": s.score, "source": s.source}
                    for s in rag_response.sources
                ],
            )

        except Exception as e:
            logger.error(f"[{getattr(self, 'agent_name', 'Agent')}] RAG answer error: {e}")
            # 降级到普通 LLM
            return await self.llm_chat(query, system_prompt=system_prompt)

    async def llm_stream(self, user_message: str, **kwargs):
        """
        流式输出（返回异步迭代器）

        Usage:
            async for chunk in agent.llm_stream("讲个故事"):
                print(chunk, end="")
        """
        if not self.ENABLE_LLM or not self.llm_client:
            yield "[LLM 未启用，使用模拟响应]"
            return

        try:
            async for chunk in self.llm_client.chat_stream(user_message, **kwargs):
                yield chunk
        except Exception as e:
            logger.error(f"[{getattr(self, 'agent_name', 'Agent')}] Stream error: {e}")
            yield f"[错误: {e}]"

    # ====== Prompt 模板管理 ======

    def get_prompt_template(self, name: str, **kwargs) -> str:
        """获取 Prompt 模板"""
        try:
            from ai_infra.llm import PROMPT_TEMPLATES
            template = PROMPT_TEMPLATES.get(name, "")
            if template and kwargs:
                return template.format(**kwargs)
            return template
        except ImportError:
            return ""

    # ====== 内部方法 ======

    def _mock_result(self, original_query: str, reason: str, structured: bool = False) -> LLMCallResult:
        """
        生成降级（模拟）结果

        当 LLM 不可用时返回此结果。
        子类可以覆盖此方法提供更好的降级逻辑。
        """
        self._llm_stats["mock_calls"] += 1

        logger.info(
            f"[{getattr(self, 'agent_name', 'Agent')}] Using mock response ({reason})"
        )

        # 尝试调用子类的 _generate_mock_response 方法
        mock_generator = getattr(self, '_generate_mock_response', None)
        if mock_generator:
            try:
                content = mock_generator(original_query)
                if structured and isinstance(content, str):
                    try:
                        content = json.loads(content)
                    except:
                        content = {"raw_text": content}
                return LLMCallResult(
                    success=True,
                    content=content,
                    raw_text=json.dumps(content, ensure_ascii=False) if isinstance(content, (dict, list)) else str(content),
                    fallback=True,
                )
            except Exception as e:
                logger.warning(f"Mock generator error: {e}")

        # 默认降级响应
        return LLMCallResult(
            success=True,
            content=f"[模拟响应] 由于 {reason}，暂时无法连接真实 LLM。原始查询：{original_query}",
            raw_text=original_query,
            fallback=True,
        )

    def _update_llm_stats(self, tokens: int, cost: float, latency: float):
        """更新统计"""
        self._llm_stats["llm_calls"] += 1
        self._llm_stats["total_tokens"] += tokens
        self._llm_stats["total_cost"] += cost

    @property
    def llm_stats(self) -> Dict:
        """获取 LLM 使用统计"""
        return {
            **self._llm_stats,
            "agent_name": getattr(self, 'agent_name', 'Unknown'),
            "llm_enabled": self.ENABLE_LLM,
            "rag_enabled": self.ENABLE_RAG,
        }

    def reset_stats(self):
        """重置统计"""
        self._llm_stats = {
            "total_calls": 0,
            "llm_calls": 0,
            "mock_calls": 0,
            "errors": 0,
            "total_tokens": 0,
            "total_cost": 0.0,
        }


__all__ = ["LLMEnabledAgent", "LLMCallResult"]
