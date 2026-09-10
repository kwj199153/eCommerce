"""
RAG (Retrieval-Augmented Generation) 混合检索引擎

架构设计：
┌─────────────┐     ┌──────────────────┐     ┌─────────────┐
│  文档输入    │ ──▶ │  文档处理管道     │ ──▶ │  向量存储    │
│  (FAQ/知识库) │     │  分块→向量化      │     │  SKLearnVector │
└─────────────┘     └──────────────────┘     └──────┬──────┘
                                                           │
┌─────────────┐     ┌──────────────────┐     ┌─────────────┐
│  生成回答    │ ◀── │  LLM 上下文组装   │ ◀── │  混合检索   │
│  (引用来源)  │     │  Prompt + 检索结果 │     │  向量+关键词 │
└─────────────┘     └──────────────────┘     └─────────────┘

核心能力：
1. 基于 SKLearnVectorStore 的向量存储和相似度检索
2. BM25/TF-IDF 关键词检索（互补）
3. 混合评分融合（Reciprocal Rank Fusion）
4. DashScope Embedding API 向量化
5. FAQ 知识库自动构建与管理
6. 支持多领域知识库隔离
"""

import os
import re
import json
import hashlib
import asyncio
from typing import Any, Optional, List, Dict, Tuple, Union
from dataclasses import dataclass, field
from enum import Enum
from datetime import datetime

import numpy as np

from core.logger import get_logger

logger = get_logger(__name__)


# ====== 配置 ======
class RAGConfig:
    """RAG 全局配置"""
    # Embedding 模型
    EMBEDDING_MODEL: str = os.getenv("EMBEDDING_MODEL", "text-embedding-v3")
    EMBEDDING_DIM: int = int(os.getenv("EMBEDDING_DIM", "1024"))

    # 检索参数
    TOP_K: int = int(os.getenv("RAG_TOP_K", "5"))           # 向量检索返回数
    KEYWORD_TOP_K: int = int(os.getenv("RAG_KEYWORD_TOP_K", "5"))
    HYBRID_TOP_K: int = int(os.getenv("RAG_HYBRID_TOP_K", "5"))

    # 分块参数
    CHUNK_SIZE: int = int(os.getenv("RAG_CHUNK_SIZE", "500"))
    CHUNK_OVERLAP: int = int(os.getenv("RAG_CHUNK_OVERLAP", "50"))

    # 融合权重
    VECTOR_WEIGHT: float = float(os.getenv("RAG_VECTOR_WEIGHT", "0.6"))
    KEYWORD_WEIGHT: float = float(os.getenv("RAG_KEYWORD_WEIGHT", "0.4"))

    # RRF 参数（Reciprocal Rank Fusion）
    RRF_K: int = 60


# ====== 数据模型 ======

@dataclass
class Document:
    """文档单元"""
    page_content: str          # 文本内容
    metadata: Dict[str, Any] = field(default_factory=dict)
    embedding: Optional[np.ndarray] = None
    doc_id: str = ""

    def __post_init__(self):
        if not self.doc_id:
            raw = f"{self.page_content}:{json.dumps(self.metadata, sort_keys=True)}"
            self.doc_id = hashlib.md5(raw.encode()).hexdigest()[:12]


@dataclass
class RetrievalResult:
    """检索结果"""
    document: Document
    score: float               # 相似度得分 [0, 1]
    source: str = "hybrid"     # vector / keyword / hybrid
    rank: int = 0


@dataclass
class RAGResponse:
    """RAG 生成结果"""
    answer: str                # 生成的回答
    sources: List[RetrievalResult]  # 引用的源文档
    query: str                 # 原始查询
    confidence: float = 0.0    # 综合置信度
    fallback: bool = False     # 是否降级到无检索模式


# ====== 文档处理器 ======

class DocumentProcessor:
    """文档分块与预处理"""

    @staticmethod
    def split_text(
        text: str,
        chunk_size: int = None,
        chunk_overlap: int = None,
        separators: List[str] = None,
    ) -> List[str]:
        """
        智能文本分块

        Args:
            text: 原始文本
            chunk_size: 每块最大字符数
            chunk_overlap: 块间重叠字符数
            separators: 分隔符优先级列表（从高到低）
        Returns:
            分块后的文本列表
        """
        chunk_size = chunk_size or RAGConfig.CHUNK_SIZE
        chunk_overlap = chunk_overlap or RAGConfig.CHUNK_OVERLAP
        separators = separators or ["\n\n", "\n", "。", ".", " ", ""]

        if len(text) <= chunk_size:
            return [text] if text.strip() else []

        chunks = []
        current_chunk = ""
        remaining_text = text

        for sep in separators:
            if sep == "":
                # 最后手段：按固定长度切分
                while len(remaining_text) > chunk_size:
                    split_point = remaining_text[:chunk_size].rfind(" ")
                    if split_point == -1 or split_point < chunk_size * 0.5:
                        split_point = chunk_size
                    chunks.append(remaining_text[:split_point].strip())
                    remaining_text = remaining_text[split_point - chunk_overlap:]
                if remaining_text.strip():
                    chunks.append(remaining_text.strip())
                break

            parts = remaining_text.split(sep)
            if all(len(p) <= chunk_size for p in parts if p.strip()):
                # 这个分隔符可以完美分割
                for part in parts:
                    part = part.strip()
                    if not part:
                        continue
                    if current_chunk:
                        current_chunk += sep + part
                    else:
                        current_chunk = part

                    if len(current_chunk) >= chunk_size * 0.8:
                        chunks.append(current_chunk)
                        current_chunk = ""
                if current_chunk:
                    remaining_text = current_chunk
                    current_chunk = ""
                else:
                    break
            else:
                # 当前分隔符不合适，尝试下一个
                continue

        return chunks or [text]

    @staticmethod
    def clean_text(text: str) -> str:
        """文本清洗"""
        text = re.sub(r'\s+', ' ', text)       # 多空白→单空格
        text = re.sub(r'[^\w\s\u4e00-\u9fff.,!?;:，。！？；：、""''（）【】《》]', '', text)
        return text.strip()

    @staticmethod
    def extract_keywords(text: str, top_n: int = 10) -> List[Tuple[str, float]]:
        """
        简易关键词提取（TF-based）

        Returns:
            [(keyword, score), ...]
        """
        from collections import Counter
        import jieba

        words = jieba.lcut(text)
        # 过滤停用词
        stop_words = {'的', '了', '是', '在', '我', '有', '和', '就', '不', '人', '都',
                      '一', '一个', '上', '也', '很', '到', '说', '要', '去', '你',
                      '会', '着', '没有', '看', '好', '自己', '这'}
        words = [w for w in words if len(w) > 1 and w not in stop_words and not w.isdigit()]

        counter = Counter(words)
        total = sum(counter.values())
        return [(word, count / total) for word, count in counter.most_common(top_n)]


# ====== Embedding 服务 ======

class DashScopeEmbedding:
    """DashScope 文本向量化"""

    def __init__(self, model: str = None):
        self.model = model or RAGConfig.EMBEDDING_MODEL
        self._client = None

    @property
    def client(self):
        if self._client is None:
            import httpx
            self._client = httpx.AsyncClient(
                timeout=httpx.Timeout(30),
                headers={
                    "Authorization": f"Bearer {os.getenv('DASHSCOPE_API_KEY', '')}",
                    "Content-Type": "application/json",
                },
            )
        return self._client

    async def embed_texts(self, texts: List[str]) -> np.ndarray:
        """批量向量化"""
        results = []

        # DashScope API 单次最多 6 条
        batch_size = 6
        for i in range(0, len(texts), batch_size):
            batch = texts[i:i + batch_size]
            response = await self.client.post(
                "https://dashscope.aliyuncs.com/compatible-mode/v1/embeddings",
                json={
                    "model": self.model,
                    "input": batch,
                    "encoding_format": "float",
                },
            )
            response.raise_for_status()
            data = response.json()

            for item in data["data"]:
                results.append(item["embedding"])

        return np.array(results)

    async def embed_query(self, query: str) -> np.ndarray:
        """单条查询向量化"""
        result = await self.embed_texts([query])
        return result[0]

    async def close(self):
        if self._client:
            await self._client.aclose()


# ====== 向量存储 ======

class SKLearnVectorStore:
    """
    基于 scikit-learn 的内存向量存储

    特点：
    - 轻量级，无需外部数据库服务
    - 支持 cosine similarity 检索
    - 支持持久化到本地文件
    - 支持多集合（collection）隔离
    """

    def __init__(self, collection_name: str = "default"):
        self.collection_name = collection_name
        self.documents: List[Document] = []
        self.embeddings: Optional[np.ndarray] = None
        self.embedding_service = DashScopeEmbedding()

    async def add_documents(self, documents: List[Document]) -> List[str]:
        """添加文档并自动向量化"""
        texts = [doc.page_content for doc in documents]

        # 批量向量化
        embeddings = await self.embedding_service.embed_texts(texts)

        for doc, emb in zip(documents, embeddings):
            doc.embedding = emb
            self.documents.append(doc)

        # 更新嵌入矩阵
        if self.embeddings is not None:
            self.embeddings = np.vstack([self.embeddings, embeddings])
        else:
            self.embeddings = embeddings

        return [doc.doc_id for doc in documents]

    async def add_texts(
        self,
        texts: List[str],
        metadatas: List[Dict] = None,
    ) -> List[str]:
        """便捷方法：添加纯文本"""
        docs = [
            Document(
                page_content=text,
                metadata=(metadatas or [{}])[i] if metadatas else {},
            )
            for i, text in enumerate(texts)
        ]
        return await self.add_documents(docs)

    async def similarity_search(
        self,
        query: str,
        k: int = None,
        filter_func=None,
    ) -> List[RetrievalResult]:
        """
        向量相似度检索

        Args:
            query: 查询文本
            k: 返回数量
            filter_func: 可选的过滤函数 (metadata) -> bool
        Returns:
            检索结果列表（按相似度降序）
        """
        if not self.documents or self.embeddings is None:
            return []

        k = k or RAGConfig.TOP_K

        # 查询向量化
        query_embedding = await self.embedding_service.embed_query(query)

        # 计算余弦相似度
        similarities = self._cosine_similarity(query_embedding, self.embeddings)

        # 排序 + 过滤
        indexed_similarities = sorted(
            enumerate(similarities),
            key=lambda x: x[1],
            reverse=True,
        )

        results = []
        for idx, sim in indexed_similarities:
            if filter_func and not filter_func(self.documents[idx].metadata):
                continue
            results.append(RetrievalResult(
                document=self.documents[idx],
                score=float(sim),
                source="vector",
            ))
            if len(results) >= k:
                break

        # 设置排名
        for i, r in enumerate(results):
            r.rank = i + 1

        return results

    def _cosine_similarity(
        self,
        vec_a: np.ndarray,
        vec_b: np.ndarray,
    ) -> np.ndarray:
        """计算余弦相似度"""
        norm_a = np.linalg.norm(vec_a)
        norms_b = np.linalg.norm(vec_b, axis=1)

        if norm_a == 0 or np.any(norms_b == 0):
            return np.zeros(len(vec_b))

        dot_product = np.dot(vec_b, vec_a)
        return dot_product / (norm_a * norms_b)

    def save(self, path: str):
        """持久化到文件"""
        data = {
            "collection_name": self.collection_name,
            "documents": [
                {
                    "page_content": d.page_content,
                    "metadata": d.metadata,
                    "doc_id": d.doc_id,
                    "embedding": d.embedding.tolist() if d.embedding is not None else None,
                }
                for d in self.documents
            ],
        }

        with open(path, "w", encoding="utf-8") as f:
            json.dump(data, f, ensure_ascii=False, indent=2)

        logger.info(f"Saved {len(self.documents)} documents to {path}")

    @classmethod
    def load(cls, path: str) -> "SKLearnVectorStore":
        """从文件加载"""
        with open(path, "r", encoding="utf-8") as f:
            data = json.load(f)

        store = cls(collection_name=data["collection_name"])

        for doc_data in data["documents"]:
            doc = Document(
                page_content=doc_data["page_content"],
                metadata=doc_data.get("metadata", {}),
                doc_id=doc_data.get("doc_id", ""),
                embedding=np.array(doc_data["embedding"]) if doc_data.get("embedding") else None,
            )
            store.documents.append(doc)

        if store.documents:
            store.embeddings = np.array([d.embedding for d in store.documents if d.embedding is not None])

        logger.info(f"Loaded {len(store.documents)} documents from {path}")
        return store

    @property
    def document_count(self) -> int:
        return len(self.documents)


# ====== 关键词检索器 ======

class KeywordRetriever:
    """基于 TF-IDF/BM25 的关键词检索"""

    def __init__(self, documents: List[Document] = None):
        self.documents = documents or []
        self._tfidf_matrix = None
        self._feature_names = None
        self._vectorizer = None
        self._initialized = False

    def build_index(self, documents: List[Document]):
        """构建 TF-IDF 索引"""
        from sklearn.feature_extraction.text import TfidfVectorizer
        import jieba

        self.documents = documents
        texts = [d.page_content for d in documents]

        # 中文分词
        def tokenize(text):
            return list(jieba.cut(text))

        self._vectorizer = TfidfVectorizer(
            tokenizer=tokenize,
            max_features=5000,
            ngram_range=(1, 2),  # unigram + bigram
        )
        self._tfidf_matrix = self._vectorizer.fit_transform(texts)
        self._feature_names = self._vectorizer.get_feature_names_out()
        self._initialized = True

        logger.info(f"Built TF-IDF index: {len(documents)} docs, {len(self._feature_names)} features")

    async def search(
        self,
        query: str,
        k: int = None,
    ) -> List[RetrievalResult]:
        """关键词检索"""
        if not self._initialized or not self.documents:
            return []

        k = k or RAGConfig.KEYWORD_TOP_K
        import jieba

        # 查询向量化
        query_terms = list(jieba.cut(query))
        query_vec = self._vectorizer.transform([" ".join(query_terms)])

        # 计算余弦相似度
        from sklearn.metrics.pairwise import cosine_similarity
        similarities = cosine_similarity(query_vec, self._tfidf_matrix).flatten()

        # 排序取 top-k
        top_indices = similarities.argsort()[::-1][:k]

        results = []
        for rank, idx in enumerate(top_indices):
            if similarities[idx] > 0:
                results.append(RetrievalResult(
                    document=self.documents[idx],
                    score=float(similarities[idx]),
                    source="keyword",
                    rank=rank + 1,
                ))

        return results


# ====== 混合检索引擎 ======

class HybridRAGEngine:
    """
    RAG 混合检索引擎（主入口）

    使用方式：
        engine = HybridRAGEngine("customer_service")
        await engine.initialize()

        # 添加文档
        await engine.add_knowledge_base(faq_list)

        # 检索
        results = await engine.search("如何退货？")

        # 生成回答
        answer = await engine.answer("如何退货？", llm_client)
    """

    def __init__(
        self,
        domain: str = "default",
        config: RAGConfig = None,
    ):
        self.domain = domain
        self.config = config or RAGConfig()

        # 存储层
        self.vector_store = SKLearnVectorStore(collection_name=f"{domain}_vectors")
        self.keyword_retriever = KeywordRetriever()

        # 状态
        self._initialized = False
        self._doc_count = 0

    async def initialize(self):
        """初始化引擎"""
        logger.info(f"[{self.domain}] Initializing RAG engine...")
        self._initialized = True
        logger.info(f"[{self.domain}] RAG engine ready")

    async def add_documents(
        self,
        documents: List[Document],
        rebuild_keyword_index: bool = True,
    ) -> int:
        """
        添加文档到知识库

        Returns:
            添加的文档数量
        """
        if not self._initialized:
            await self.initialize()

        # 向量存储
        doc_ids = await self.vector_store.add_documents(documents)

        # 重建关键词索引
        if rebuild_keyword_index:
            all_docs = self.vector_store.documents
            self.keyword_retriever.build_index(all_docs)

        self._doc_count = self.vector_store.document_count
        logger.info(f"[{self.domain}] Added {len(doc_ids)} documents (total: {self._doc_count})")

        return len(doc_ids)

    async def add_faq_knowledge_base(
        self,
        faq_items: List[Dict[str, str]],
        category: str = "general",
    ) -> int:
        """
        添加 FAQ 知识库

        Args:
            faq_items: [{"question": "...", "answer": "..."}, ...]
            category: 分类标签
        Returns:
            添加的数量
        """
        documents = []
        for item in faq_items:
            q = item.get("question", "")
            a = item.get("answer", "")
            content = f"问题：{q}\n答案：{a}"
            documents.append(Document(
                page_content=content,
                metadata={
                    "type": "faq",
                    "category": category,
                    "question": q,
                    "source": item.get("source", "knowledge_base"),
                },
            ))

        return await self.add_documents(documents)

    async def search(
        self,
        query: str,
        top_k: int = None,
        mode: str = "hybrid",
        min_score: float = 0.1,
    ) -> List[RetrievalResult]:
        """
        混合检索

        Args:
            query: 查询文本
            top_k: 返回数量
            mode: "hybrid" | "vector" | "keyword"
            min_score: 最低分数阈值
        Returns:
            融合后的检索结果
        """
        if not self._initialized or self._doc_count == 0:
            return []

        top_k = top_k or self.config.HYBRID_TOP_K

        # 并行执行两种检索
        vector_results: List[RetrievalResult] = []
        keyword_results: List[RetrievalResult] = []

        if mode in ("hybrid", "vector"):
            try:
                vector_results = await self.vector_store.similarity_search(
                    query, k=top_k * 2  # 多取一些用于融合
                )
            except Exception as e:
                logger.error(f"[{self.domain}] Vector search error: {e}")

        if mode in ("hybrid", "keyword"):
            try:
                keyword_results = await self.keyword_retriever.search(query, k=top_k * 2)
            except Exception as e:
                logger.error(f"[{self.domain}] Keyword search error: {e}")

        # 融合
        if mode == "hybrid":
            return self._reciprocal_rank_fusion(
                vector_results,
                keyword_results,
                top_k,
                min_score,
            )
        elif mode == "vector":
            return [r for r in vector_results[:top_k] if r.score >= min_score]
        else:
            return [r for r in keyword_results[:top_k] if r.score >= min_score]

    def _reciprocal_rank_fusion(
        self,
        vector_results: List[RetrievalResult],
        keyword_results: List[RetrievalResult],
        top_k: int,
        min_score: float,
    ) -> List[RetrievalResult]:
        """
        Reciprocal Rank Fusion (RRF) 算法

        score(d) = Σ 1/(k + rank_i(d))
        其中 k 是平滑参数（通常为 60）
        """
        rrf_scores: Dict[str, Dict] = {}

        # 处理向量检索结果
        weight = self.config.VECTOR_WEIGHT
        for result in vector_results:
            doc_id = result.document.doc_id
            if doc_id not in rrf_scores:
                rrf_scores[doc_id] = {
                    "result": result,
                    "score": 0.0,
                    "sources": [],
                }
            rrf_scores[doc_id]["score"] += weight * (1 / (self.config.RRF_K + result.rank))
            rrf_scores[doc_id]["sources"].append(("vector", result.score, result.rank))

        # 处理关键词检索结果
        weight = self.config.KEYWORD_WEIGHT
        for result in keyword_results:
            doc_id = result.document.doc_id
            if doc_id not in rrf_scores:
                rrf_scores[doc_id] = {
                    "result": result,
                    "score": 0.0,
                    "sources": [],
                }
            rrf_scores[doc_id]["score"] += weight * (1 / (self.config.RRF_K + result.rank))
            rrf_scores[doc_id]["sources"].append(("keyword", result.score, result.rank))

        # 归一化 & 排序
        max_score = max((s["score"] for s in rrf_scores.values()), default=1.0)
        final_results = []
        for doc_id, data in rrf_scores.items():
            normalized_score = data["score"] / max_score if max_score > 0 else 0
            if normalized_score < min_score:
                continue

            result = data["result"]
            result.score = normalized_score
            result.source = "hybrid"
            final_results.append(result)

        final_results.sort(key=lambda x: x.score, reverse=True)

        # 重设排名
        for i, r in enumerate(final_results[:top_k]):
            r.rank = i + 1

        return final_results[:top_k]

    async def answer(
        self,
        query: str,
        llm_client,  # DashScopeLLM 实例
        system_prompt: str = None,
        top_k: int = 3,
    ) -> RAGResponse:
        """
        RAG 生成回答

        流程：
        1. 检索相关文档
        2. 组装上下文 Prompt
        3. 调用 LLM 生成回答
        4. 返回带引用的回答
        """
        # 1. 检索
        sources = await self.search(query, top_k=top_k)

        if not sources:
            # 无相关文档 → 直接用 LLM 回答（降级模式）
            logger.info(f"[{self.domain}] No relevant docs found, using LLM only")
            response = await llm_client.chat(
                query,
                system_prompt=system_prompt or "你是一个有帮助的助手。",
            )
            return RAGResponse(
                answer=response.content,
                sources=[],
                query=query,
                fallback=True,
            )

        # 2. 组装上下文
        context_parts = []
        for i, source in enumerate(sources, 1):
            meta = source.document.metadata
            preview = source.document.page_content[:200]
            context_parts.append(f"[参考资料{i}] ({meta.get('type', 'doc')}): {preview}...")

        context_text = "\n\n".join(context_parts)

        rag_prompt = f"""你是一个基于知识库回答问题的智能助手。
请根据以下参考资料回答用户的问题。

参考资料：
{context_text}

回答要求：
1. 基于参考资料内容回答，不要编造信息
2. 如果参考资料中没有相关信息，请明确说明
3. 在回答中标注引用来源，如 [参考资料1]
4. 用简洁清晰的语言回答

用户问题：{query}"""

        # 3. 调用 LLM
        full_system = system_prompt or ""
        full_system += "\n\n" + rag_prompt if rag_prompt else rag_prompt

        response = await llm_client.chat(
            "",
            system_prompt=full_system.strip(),
        )

        # 4. 计算置信度
        confidence = sum(s.score for s in sources) / len(sources) if sources else 0

        return RAGResponse(
            answer=response.content,
            sources=sources,
            query=query,
            confidence=round(confidence, 3),
            fallback=False,
        )

    def get_stats(self) -> Dict:
        """获取引擎统计信息"""
        return {
            "domain": self.domain,
            "document_count": self._doc_count,
            "initialized": self._initialized,
            "vector_store_docs": self.vector_store.document_count,
            "keyword_index_ready": self.keyword_retriever._initialized,
        }

    async def save_to_disk(self, directory: str):
        """持久化到磁盘"""
        import os.path
        os.makedirs(directory, exist_ok=True)

        # 保存向量存储
        vector_path = os.path.join(directory, f"{self.domain}_vectors.json")
        self.vector_store.save(vector_path)

        stats = self.get_stats()
        stats_path = os.path.join(directory, f"{self.domain}_stats.json")
        with open(stats_path, "w") as f:
            json.dump(stats, f, indent=2)

        logger.info(f"[{self.domain}] Saved to {directory}")


# ====== 预置知识库构建器 ======

class KnowledgeBaseBuilder:
    """预置知识库构建工具"""

    # 客服 FAQ 知识库
    CUSTOMER_SERVICE_FAQ: List[Dict[str, str]] = [
        {
            "question": "订单发货需要多长时间？",
            "answer": "一般情况下，订单在支付成功后 24-48 小时内发货。预售商品以商品详情页标注的发货时间为准。节假日订单可能延迟 1-2 天。",
            "category": "物流配送",
        },
        {
            "question": "如何查看物流信息？",
            "answer": "您可以通过以下方式查看物流：1) 登录账户 → 我的订单 → 点击\"查看物流\"；2) 在订单详情页会显示物流公司和运单号；3) 部分订单支持物流实时轨迹追踪。",
            "category": "物流配送",
        },
        {
            "question": "支持哪些付款方式？",
            "answer": "我们支持的付款方式包括：信用卡/借记卡（Visa/MasterCard/AE）、PayPal、支付宝、微信支付等。不同地区可能有所差异，请以结账页面显示为准。",
            "category": "支付",
        },
        {
            "question": "如何申请退款？",
            "answer": "退款流程：1) 进入\"我的订单\"找到目标订单；2) 点击\"申请售后\"选择\"退款\"；3) 选择退款原因并提交申请；4) 我们会在 1-3 个工作日审核。审核通过后，原路退回支付账户，到账时间 3-7 个工作日。",
            "category": "退换货",
        },
        {
            "question": "退货运费谁承担？",
            "answer": "退货运费规则：1) 商品质量问题 → 卖家承担全部运费；2) 尺码/颜色等个人原因 → 买家承担（除非有免费退换货服务）；3) 发错货/漏发 → 卖家承担。具体以售后审核结果为准。",
            "category": "退换货",
        },
        {
            "question": "收到商品有损坏怎么办？",
            "answer": "请按以下步骤操作：1) 立即拍照留证（含外包装和商品损坏处）；2) 不要丢弃包装和面单；3) 在订单中申请售后，上传照片；4) 选择\"质量问题\"原因。我们会在 24 小时内处理，提供换货或全额退款方案。",
            "category": "退换货",
        },
        {
            "question": "如何修改收货地址？",
            "answer": "地址修改规则：1) 未发货订单 → 可直接在订单详情页修改；2) 已发货但未签收 → 尽快联系客服拦截，但不保证成功；3) 已签收 → 无法修改。建议下单前仔细核对地址信息。",
            "category": "订单管理",
        },
        {
            "question": "可以取消订单吗？",
            "answer": "取消规则：1) 未发货订单 → 可在订单页面直接取消，款项原路退回；2) 已发货订单 → 需要先拒收或申请退货；3) 预售商品 → 生产前可取消，生产开始后无法取消。建议尽快操作以避免发货。",
            "category": "订单管理",
        },
        {
            "question": "什么是关税和进口税？",
            "answer": "跨境购物可能产生进口关税，由目的地国家海关收取。税费金额取决于商品类别、申报价值和当地税率。部分商品享受免税额度（如欧盟 22 欧元以下）。具体税费以海关实际收取为准，卖家不代收关税。",
            "category": "税费",
        },
        {
            "question": "如何联系客服？",
            "answer": "客服渠道：1) 在线客服：网站右下角聊天窗口（工作时间即时回复）；2) 工单系统：帮助中心 → 提交工单（24小时内回复）；3) 邮箱：support@example.com（1-2个工作日）。紧急问题建议使用在线客服。",
            "category": "账号与服务",
        },
        {
            "question": "账号被锁定了怎么办？",
            "answer": "账号锁定通常由于安全异常触发。解锁步骤：1) 尝试登录时会提示锁定原因；2) 按提示进行身份验证（邮箱/手机验证码）；3) 如无法自助解锁，请联系客服并提供注册邮箱。为避免锁定，请勿频繁更换登录 IP 或设备。",
            "category": "账号与服务",
        },
        {
            "question": "如何追踪我的会员积分？",
            "answer": "积分查询方式：1) 登录后进入\"我的账户\" → \"积分中心\"查看余额和历史明细；2) 积分有效期通常为 1 年，过期自动清零；3) 积分可用于抵扣现金（100积分=1元）或兑换优惠券。消费、签到、评价均可获得积分。",
            "category": "会员权益",
        },
    ]

    @classmethod
    async def build_customer_service_kb(cls, engine: HybridRAGEngine) -> int:
        """构建客服知识库"""
        count = await engine.add_faq_knowledge_base(
            cls.CUSTOMER_SERVICE_FAQ,
            category="customer_service",
        )
        logger.info(f"Built customer service KB: {count} entries")
        return count


__all__ = [
    # 配置
    "RAGConfig",
    # 数据模型
    "Document",
    "RetrievalResult",
    "RAGResponse",
    # 核心组件
    "DocumentProcessor",
    "DashScopeEmbedding",
    "SKLearnVectorStore",
    "KeywordRetriever",
    "HybridRAGEngine",
    # 工具
    "KnowledgeBaseBuilder",
]
