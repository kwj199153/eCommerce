"""FAQ：话术加载（真源 `knowledge_faqs` 表）、RAG 问答、FAQ 搜索引擎、知识库检索。

本文件由 `modules/customer_service/agent_cs.py` 拆分而来（第 356 轮），代码**逐行搬运**、未改写逻辑。
"""
# @generated-by: split_agent_cs.py (第 356 轮)

import re
from typing import List, Dict, Optional
from ._base import (
    AgentResponse,
    ConversationContext,
    FAQItem,
    FAQMatchResult,
    SentimentAnalysis,
    logger,
)

class MixinFaq:
    """FAQ：话术加载（真源 `knowledge_faqs` 表）、RAG 问答、FAQ 搜索引擎、知识库检索。"""

    # ---- 话术加载（真源：knowledge_faqs 表） ----

    async def ensure_faq(self, shop_id: Optional[str]) -> str:
        """把**当前店铺**的话术读进 `self.faq_database`。

        ★ 每次调用都读库，**不做进程内缓存**：运营在资料库里改了一条话术，
          下一次问答就该生效；一次查询只有几十行，成本可忽略。
          （`_faq_shop` 只用于诊断 —— 标明这批话术属于哪个店铺。）

        Returns:
            失败原因（"" = 成功）。**不抛**：「话术读不出来」不该让整段
            对话 500，它只是一部分能力不可用，由调用方决定怎么表达。
        """
        # 惰性 import：`faq_source` 带数据库依赖，而本模块在**导入期**就被
        #   bind_tools 装配 —— 模块级 import 会把 DB 依赖提前到启动路径。
        from ..faq_source import load_faq_items

        try:
            items = await load_faq_items(shop_id)
        except Exception as e:  # noqa: BLE001
            self.faq_database = []
            self._faq_shop = None
            self._faq_error = str(e)
            self._faq_error_exc = e
            logger.warning(f"[customer_service] 话术库加载失败 shop={shop_id}: {e}")
            return self._faq_error

        self.faq_database = [FAQItem(**item) for item in items]
        self._faq_shop = shop_id
        self._faq_error = ""
        self._faq_error_exc = None
        return ""

    def _faq_unavailable_response(self, query: str, reason: str) -> AgentResponse:
        """话术库**读不出来**时的回复。

        ★ 与「没有这条话术」**严格分开**：前者是数据源没读到（要修数据源），
          后者是内容没配（去资料库补一条）。混成一句「没找到答案」，
          会让运营往错的地方使劲 —— 这正是以前内存 mock 掩盖掉的事。
        """
        reply = (
            "**话术库暂时读不出来** ⚠️\n\n"
            f"原因：{reason}\n\n"
            "这与「没有这条话术」不是一回事：前者是数据源没读到，"
            "后者可以在【资料库 → 业务话术库】里补一条。\n\n"
            "您可以换个说法再问我，或联系人工客服：support@example.com"
        )
        return AgentResponse(
            content=reply,
            data={"type": "faq_unavailable", "reason": reason, "query": query},
            display_type="text",
        )

    def _faq_empty_response(self, query: str) -> AgentResponse:
        """店铺**还没配话术**（表里 0 行）时的回复。"""
        reply = (
            "这个店铺**还没有配置话术** 📚\n\n"
            "我现在只能按通用规则回答，给不出针对您店铺的准确答复。\n\n"
            "请在【资料库 → 业务话术库】添加问答条目，添加后立刻生效。\n\n"
            f"（您问的是：{query}）"
        )
        return AgentResponse(
            content=reply,
            data={"type": "faq_empty", "query": query},
            display_type="text",
        )


    # ---- 各意图处理器 ----

    async def _handle_faq_query(
        self,
        query: str,
        context: Optional[Dict],
        conv: ConversationContext,
        sentiment: SentimentAnalysis
    ) -> AgentResponse:
        """处理 FAQ 查询（支持 RAG + LLM 增强）"""

        # ★ 先把三种「没答上来」分清：**读不出来** / **没配** / **没命中**。
        if self._faq_error:
            return self._faq_unavailable_response(query, self._faq_error)
        if not self.faq_database:
            return self._faq_empty_response(query)

        # ====== 升级：优先使用 RAG + LLM ======
        if self.ENABLE_RAG and self.rag_engine:
            try:
                return await self._handle_faq_with_rag(query, context, conv, sentiment)
            except Exception as e:
                logger.warning(f"RAG 处理失败，降级到关键词匹配: {e}")

        # ====== 降级方案：原始关键词匹配 ======

        # 1. 在知识库中检索匹配
        match_result = self._search_faq(query)

        # 2. 如果有高置信度匹配，直接返回答案
        if match_result.confidence >= 0.7 and match_result.best_match:
            faq = match_result.best_match

            # 个性化回复
            reply = f"**找到了相关问题解答** 👇\n\n{faq.answer}\n\n"
            reply += "---\n*这个回答对您有帮助吗？*\n"

            # 追加相关问题建议
            if match_result.suggested_questions:
                reply += "\n**您可能还想知道**：\n"
                for sq in match_result.suggested_questions[:3]:
                    reply += f"- {sq}\n"

            return AgentResponse(
                content=reply,
                data={
                    "type": "faq_match",
                    "query": query,
                    "match": faq.model_dump(),
                    "confidence": match_result.confidence,
                    "suggested": match_result.suggested_questions[:5],
                    "source": "keyword_match",  # 标记来源
                },
                display_type="faq_answer"
            )

        # 3. 低置信度：返回多个可能相关的 FAQ
        if match_result.matches:
            reply = "我找到几个可能与您问题相关的内容：\n\n"
            for i, m in enumerate(match_result.matches[:3], 1):
                reply += f"**{i}. {m.question}**\n"
                reply += f"{m.answer[:100]}...\n\n"

            reply += "请问以上哪个更符合您的情况？或者您可以详细描述一下问题。"

            return AgentResponse(
                content=reply,
                data={
                    "type": "faq_suggestions",
                    "matches": [m.model_dump() for m in match_result.matches[:3]],
                    "confidence": match_result.confidence,
                    "source": "keyword_match",
                },
                display_type="faq_list"
            )

        # 4. 无匹配：尝试 LLM 或生成通用回复
        if self.llm_client:
            try:
                llm_result = await self.llm_chat(
                    user_message=query,
                    system_prompt=self.get_prompt_template("customer_service"),
                )
                return AgentResponse(
                    content=llm_result.content,
                    data={"type": "llm_generated", "fallback": llm_result.fallback},
                    display_type="text",
                )
            except Exception as e:
                logger.warning(f"LLM FAQ fallback error: {e}")

        return await self._handle_general(query, context, conv, sentiment)

    async def _handle_faq_with_rag(
        self,
        query: str,
        context: Optional[Dict],
        conv: ConversationContext,
        sentiment: SentimentAnalysis
    ) -> AgentResponse:
        """使用 RAG 引擎处理 FAQ 查询"""

        # 确保 RAG 已初始化
        if not self._rag_initialized:
            await self.initialize_rag(faq_items=[
                {"question": f.question, "answer": f.answer, "category": f.category}
                for f in self.faq_database
            ])
            self._rag_initialized = True

        # 调用 RAG 回答
        rag_result = await self.llm_rag_answer(
            query=query,
            system_prompt=self.get_prompt_template("customer_service"),
            top_k=3,
        )

        # 构建响应
        # ★ 原写法 `hasattr(rag_result, '_sources')` —— 该属性在 LLMCallResult 上
        # 从来不存在（字段名是 `sources`，无下划线前缀）。hasattr 恒 False ⇒
        # sources_info 恒 [] ⇒ 「参考了 N 条知识库文献」永不追加，RAG 引用来源
        # 静默丢失（不报错、不降级、测试全绿）。改为直接读真实字段：字段若改名会
        # 立刻 AttributeError，而不是悄悄退化成空列表。
        sources_info = list(rag_result.sources or [])

        reply = rag_result.content

        # 如果有引用来源，追加说明
        if sources_info and not rag_result.fallback:
            reply += "\n\n---\n*📚 参考了 {} 条知识库文献*".format(len(sources_info))

        # 根据情感调整语气后缀
        # ★ 原写法 `sentiment.level` —— SentimentAnalysis 没有该字段（字段是
        # `sentiment`，取值 positive/neutral/negative/angry）。此处必抛
        # AttributeError，被 _handle_faq_query 的 except 吞掉 ⇒ 每次客服 FAQ 都
        # 静默降级到关键词匹配，RAG 路径从未真正生效。同文件 1126 行用的就是
        # 正确的 `sentiment.sentiment`。
        if sentiment.sentiment == "negative":
            reply += "\n\n如果您的问题没有得到解决，可以点击下方「转人工」按钮。"
        elif sentiment.sentiment == "angry":
            reply += "\n\n非常抱歉给您带来不好的体验，我已将您的问题标记为紧急，会有专人尽快跟进。"

        return AgentResponse(
            content=reply,
            data={
                "type": "rag_answer",
                "query": query,
                "confidence": rag_result.confidence,
                "sources": sources_info,
                "fallback": rag_result.fallback,
                "source": "rag_hybrid",  # 标记为 RAG 来源
            },
            display_type="faq_answer"
        )


    # ---- FAQ 搜索引擎 ----

    def _search_faq(self, query: str, threshold: float = 0.3) -> FAQMatchResult:
        """
        在 FAQ 数据库中搜索匹配项

        使用关键词匹配 + 类别权重算法
        （生产环境替换为向量相似度检索）
        """
        query_lower = query.lower()
        # ★ 中文没有空格：`\w+` 会把「我要退货」当成**一个词**，于是「标题精确
        #   匹配」对中文几乎永不生效（整串自然不在标题里）。保留它只为英文；
        #   中文的主信号是下面的**关键词命中**（那正是 `knowledge_faqs.keywords`
        #   这一列存在的意义 —— 运营为每条话术标了「买家会怎么问」）。
        query_terms = re.findall(r'\w+', query_lower)

        scored_matches = []

        for faq in self.faq_database:
            score = 0.0

            # 1. 标题精确匹配（权重最高；英文有效、中文基本无效，见上）
            if any(term in faq.question.lower() for term in query_terms):
                score += 0.5
                # 完全包含得分更高
                if query_lower in faq.question.lower():
                    score += 0.3

            # 2. 关键词匹配 —— **中文场景的主信号**
            #    ★ 改造前每个关键词只加 0.1，而阈值是 0.3 ⇒ 买家说「我要退货」
            #      命中 1 个关键词也只拿 0.1×权重，永远够不到阈值，界面上就是
            #      「没找到答案」。把单个关键词提到 0.3（命中即过线），
            #      多个叠加最高 0.9。
            keyword_matches = sum(
                1 for kw in faq.keywords if kw and kw.lower() in query_lower
            )
            score += min(0.9, keyword_matches * 0.3)

            # 3. 类别热门度加权
            category_weight = {"物流": 1.1, "退换货": 1.15, "订单": 1.05}.get(faq.category, 1.0)
            score *= category_weight

            # 4. 优先级加权
            score *= (1 + faq.priority / 1000)

            if score >= threshold:
                scored_matches.append((score, faq))

        # 按分数排序
        scored_matches.sort(key=lambda x: x[0], reverse=True)

        matches = [m[1] for m in scored_matches[:5]]
        best_match = scored_matches[0][1] if scored_matches else None
        confidence = scored_matches[0][0] if scored_matches else 0.0

        # 生成相关问题建议
        suggested = [m.question for m in matches[1:4]] if len(matches) > 1 else []

        return FAQMatchResult(
            query=query,
            matches=matches,
            best_match=best_match,
            confidence=min(1.0, confidence),
            suggested_questions=suggested
        )

    def _find_best_faq_match(self, query: str,
                             faq_list: List[FAQItem]) -> Optional[FAQItem]:
        """从指定列表中找最佳匹配（列表为空 ⇒ None，不抛 IndexError）"""
        result = self._search_faq(query, threshold=0.1)
        # 过滤只在列表中的
        for m in result.matches:
            if m in faq_list:
                return m
        return faq_list[0] if faq_list else None


    # ---- 公开 API 方法 ----

    async def search_knowledge_base(
        self, query: str, limit: int = 5, shop_id: Optional[str] = None
    ) -> List[Dict]:
        """公开接口：搜索知识库 —— **真源是 `knowledge_faqs` 表**。

        ★ 第 286 轮之前，这个函数搜的是**内存里 12 条硬编码 FAQ**：
          名叫「知识库」，却与库里那 24 条真话术毫无关系（命名欺骗）。
          现在走 `ensure_faq` ⇒ `faq_source.load_faq_items`。

        Raises:
            PermissionError: 缺店铺上下文（话术是租户隔离数据）⇒ 端点转 400。
            RuntimeError:    数据库不可用 ⇒ 端点转 503。
                ★ 两种都**不返回空列表**：那会把「读不出来」伪装成「没有相关话术」。
        """
        err = await self.ensure_faq(shop_id)
        if err:
            # ★ 保类型抛出：让调用方能按类型分码，而不是靠字符串猜
            if isinstance(self._faq_error_exc, PermissionError):
                raise self._faq_error_exc
            raise RuntimeError(err)
        result = self._search_faq(query)
        return [m.model_dump() for m in result.matches[:limit]]
