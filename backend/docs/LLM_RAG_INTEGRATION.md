# LLM + RAG 集成指南 (Phase 8)

## 概述

Phase 8 为跨境电商 AI SaaS 项目接入了两大核心能力：

1. **DashScope Qwen LLM** - 真实大语言模型调用
2. **SKLearnVectorStore RAG** - 混合检索增强生成

## 架构设计

```
┌─────────────────────────────────────────────────────────────┐
│                      业务 Agent 层                          │
│  ┌──────────┐ ┌──────────┐ ┌──────────┐ ┌──────────┐      │
│  │ 选品分析  │ │ Listing  │ │ 广告分析  │ │ 智能客服  │ ...   │
│  └─────┬────┘ └─────┬────┘ └─────┬────┘ └─────┬────┘      │
│        │           │           │           │              │
│        ▼           ▼           ▼           ▼              │
│  ┌──────────────────────────────────────────────────┐      │
│  │            LLMEnabledAgent (混入类)                │      │
│  │  - llm_chat()       标准对话                       │      │
│  │  - llm_structured() 结构化输出                     │      │
│  │  - llm_rag_answer() RAG 增强回答                   │      │
│  │  - 自动降级到模拟响应                              │      │
│  └─────────────────────┬────────────────────────────┘      │
│                        │                                    │
│  ┌─────────────────────▼────────────────────────────┐      │
│  │                  AI 中台层                         │      │
│  │  ┌─────────────────┐  ┌────────────────────────┐  │      │
│  │  │ DashScopeLLM     │  │ HybridRAGEngine        │  │      │
│  │  │ - qwen-max/plus │  │ - SKLearnVectorStore   │  │      │
│  │  │ - 流式输出       │  │ - TF-IDF 关键词检索    │  │      │
│  │  │ - Token 统计     │  │ - RRF 融合算法         │  │      │
│  │  └─────────────────┘  └────────────────────────┘  │      │
│  └──────────────────────────────────────────────────┘      │
└─────────────────────────────────────────────────────────────┘
```

## 快速开始

### 1. 配置 API Key

编辑 `.env` 文件：

```bash
# 必填：DashScope API Key（从阿里云控制台获取）
DASHSCOPE_API_KEY=sk-xxxxxxxxxxxxxxxx

# 可选：模型选择
LLM_MODEL=qwen-plus  # qwen-max(最强) / qwen-plus(均衡) / qwen-turbo(快速)
```

### 2. 安装依赖

```bash
pip install -r requirements.txt
```

核心依赖：
- `httpx` - HTTP 客户端（DashScope API 调用）
- `numpy` - 向量计算
- `scikit-learn` - TF-IDF / 余弦相似度
- `jieba` - 中文分词

### 3. 运行测试

```bash
python tests/test_llm_rag_integration.py
```

## 使用示例

### 基本 LLM 调用

```python
from ai_infra.llm import get_llm

# 获取客户端
llm = get_llm(model="qwen-plus")

# 非流式调用
response = await llm.chat("帮我分析这个产品的市场机会")
print(response.content)

# 流式调用
async for chunk in llm.chat_stream("讲一个关于电商的故事"):
    print(chunk, end="")
```

### RAG 检索增强

```python
from ai_infra.rag import HybridRAGEngine, KnowledgeBaseBuilder

# 创建引擎
engine = HybridRAGEngine(domain="customer_service")
await engine.initialize()

# 加载知识库
await KnowledgeBaseBuilder.build_customer_service_kb(engine)

# 检索
results = await engine.search("如何退货？", top_k=3)

# RAG 生成回答
answer = await engine.answer("如何退货？", llm_client=llm)
print(answer.answer)        # 生成的回答
print(answer.sources)       # 引用来源
```

### Agent 集成

所有 Agent 已自动集成 LLM 能力，无需额外代码：

```python
from modules.customer_service.agent_cs import CustomerServiceAgent

agent = CustomerServiceAgent()

# 自动使用 LLM + RAG（如果已配置）
response = await agent.invoke("客户问如何退款")

# 查看统计
print(agent.llm_stats)
```

## 各 Agent LLM 配置

| Agent | 默认模型 | LLM | RAG | 说明 |
|-------|---------|-----|-----|------|
| 选品分析 | qwen-max | ✅ | ❌ | 复杂分析用最强模型 |
| Listing 生成 | qwen-plus | ✅ | ❌ | 文本生成均衡性能 |
| 广告分析 | qwen-max | ✅ | ❌ | 数据分析需强推理 |
| 智能客服 | qwen-plus | ✅ | ✅ | FAQ 检索+LLM 生成 |
| 竞品监控 | qwen-max | ✅ | ❌ | 竞争分析复杂 |
| AIGC 媒体 | qwen-plus | ✅ | ❌ | 文案创作 |

## 降级机制

当 LLM 不可用时，系统自动降级：

```
用户请求 → Agent.invoke()
    ↓
检查 LLM 是否可用？
    ├─ ✅ 可用 → 调用 DashScope Qwen → 返回真实响应
    └─ ❌ 不可用 → 使用规则引擎/模板 → 返回模拟响应（标记 fallback=True）
```

降级场景：
1. `DASHSCOPE_API_KEY` 未配置
2. 网络不可达
3. API 配额耗尽
4. 手动设置 `agent.ENABLE_LLM = False`

## RAG 混合检索算法

采用 **Reciprocal Rank Fusion (RRF)** 融合两种检索结果：

```
score(d) = W_vector × 1/(k + rank_vector) + W_keyword × 1/(k + rank_keyword)

其中：
- k = 60 (平滑参数)
- W_vector = 0.6 (向量权重)
- W_keyword = 0.4 (关键词权重)
```

优势：
- **向量检索**：语义理解，同义词/近义词匹配
- **关键词检索**：精确匹配，专有名词/数字
- **混合融合**：兼顾两者优点

## 成本估算

| 模型 | 输入价格 | 输出价格 | 适用场景 |
|------|---------|---------|---------|
| qwen-max | ¥0.02/千token | ¥0.06/千token | 复杂分析 |
| qwen-plus | ¥0.004/千token | ¥0.012/千token | 通用场景 |
| qwen-turbo | ¥0.002/千token | ¥0.006/千token | 快速响应 |

## 后续优化方向

1. **接入 Amazon SP-API** 替换模拟数据
2. **向量数据库升级** 从 SKLearnVectorStore 到 Milvus/Pinecone
3. **Prompt 优化** 基于 A/B 测试持续迭代
4. **缓存层** 相似查询复用结果
5. **流式输出** 前端 SSE 实时展示
