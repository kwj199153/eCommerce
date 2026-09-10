"""
LLM + RAG 集成测试脚本

测试内容：
1. DashScope LLM 客户端连接
2. RAG 引擎初始化和检索
3. 各 Agent 的 LLM 增强功能
4. 降级机制验证

使用方式：
    python tests/test_llm_rag_integration.py

环境要求：
    - DASHSCOPE_API_KEY 已配置在 .env 中
    - 依赖已安装: httpx, numpy, scikit-learn, jieba
"""

import asyncio
import os
import sys
import time

# 添加项目根目录到路径
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))


def print_separator(title: str):
    print(f"\n{'='*60}")
    print(f"  {title}")
    print('='*60)


async def test_llm_client():
    """测试 1: LLM 客户端基本功能"""
    print_separator("Test 1: DashScope LLM Client")

    try:
        from ai_infra.llm import DashScopeLLM, get_llm, LLMConfig

        # 检查 API Key 配置
        if not LLMConfig.API_KEY or LLMConfig.API_KEY.startswith("your-"):
            print("⚠️ DASHSCOPE_API_KEY 未配置，使用模拟模式")
            return False

        # 创建客户端
        llm = get_llm(model="qwen-plus")
        print(f"✅ LLM 客户端创建成功 (model={llm.model})")

        # 测试简单对话
        start = time.time()
        response = await llm.chat("你好，请用一句话介绍你自己")
        latency = (time.time() - start) * 1000

        print(f"✅ 对话成功:")
        print(f"   内容: {response.content[:100]}...")
        print(f"   Token: {response.total_tokens} (in={response.input_tokens}, out={response.output_tokens})")
        print(f"   费用: ¥{response.cost:.6f}")
        print(f"   延迟: {latency:.0f}ms")

        # 统计信息
        print(f"\n📊 LLM 统计: {llm.stats}")

        await llm.close()
        return True

    except Exception as e:
        print(f"❌ LLM 测试失败: {e}")
        import traceback
        traceback.print_exc()
        return False


async def test_rag_engine():
    """测试 2: RAG 混合检索引擎"""
    print_separator("Test 2: RAG Hybrid Engine")

    try:
        from ai_infra.rag import (
            HybridRAGEngine,
            SKLearnVectorStore,
            KnowledgeBaseBuilder,
            Document,
            DocumentProcessor,
            RAGConfig,
        )

        # 创建引擎
        engine = HybridRAGEngine(domain="test_customer_service")
        await engine.initialize()
        print(f"✅ RAG 引擎初始化成功")

        # 加载预置 FAQ 知识库
        count = await KnowledgeBaseBuilder.build_customer_service_kb(engine)
        print(f"✅ 知识库加载完成: {count} 条 FAQ")

        # 测试向量检索
        results = await engine.search("如何退货？", top_k=3, mode="vector")
        print(f"\n📌 向量检索测试 ('如何退货？'):")
        for r in results:
            print(f"   [{r.score:.3f}] {r.document.page_content[:50]}... (source={r.source})")

        # 测试关键词检索
        results = await engine.search("退款流程", top_k=3, mode="keyword")
        print(f"\n📌 关键词检索测试 ('退款流程'):")
        for r in results:
            print(f"   [{r.score:.3f}] {r.document.page_content[:50]}... (source={r.source})")

        # 测试混合检索
        results = await engine.search("运费怎么算", top_k=3, mode="hybrid")
        print(f"\n📌 混合检索测试 ('运费怎么算'):")
        for r in results:
            print(f"   [{r.score:.3f}] {r.document.page_content[:50]}... (source={r.source})")

        # 统计信息
        stats = engine.get_stats()
        print(f"\n📊 RAG 统计: {stats}")

        return True

    except Exception as e:
        print(f"❌ RAG 测试失败: {e}")
        import traceback
        traceback.print_exc()
        return False


async def test_agent_integration():
    """测试 3: Agent LLM 集成"""
    print_separator("Test 3: Agent LLM Integration")

    try:
        from modules.customer_service.agent_cs import CustomerServiceAgent
        from modules.product_research.agent_product_research import ProductResearchAgent

        # 测试客服 Agent
        print("\n--- Customer Service Agent ---")
        cs_agent = CustomerServiceAgent()
        print(f"✅ 客服 Agent 创建成功")
        print(f"   LLM enabled: {cs_agent.ENABLE_LLM}")
        print(f"   RAG enabled: {cs_agent.ENABLE_RAG}")
        print(f"   Stats: {cs_agent.llm_stats}")

        # 测试选品 Agent
        print("\n--- Product Research Agent ---")
        pr_agent = ProductResearchAgent()
        print(f"✅ 选品 Agent 创建成功")
        print(f"   LLM enabled: {pr_agent.ENABLE_LLM}")
        print(f"   Model: {pr_agent.DEFAULT_MODEL}")
        print(f"   Stats: {pr_agent.llm_stats}")

        return True

    except Exception as e:
        print(f"❌ Agent 集成测试失败: {e}")
        import traceback
        traceback.print_exc()
        return False


async def test_fallback_mechanism():
    """测试 4: 降级机制"""
    print_separator("Test 4: Fallback Mechanism")

    try:
        from modules.listing_generator.agent_listing import ListingGeneratorAgent

        # 创建 Agent 并强制关闭 LLM
        agent = ListingGeneratorAgent()
        original_enable = agent.ENABLE_LLM
        agent.ENABLE_LLM = False  # 模拟 LLM 不可用

        print(f"✅ 强制关闭 LLM (原始值: {original_enable})")

        # 调用应该使用降级响应
        result = await agent.llm_chat("测试消息")
        print(f"✅ 降级调用成功:")
        print(f"   Fallback: {result.fallback}")
        print(f"   Content: {result.content[:80]}...")

        # 恢复设置
        agent.ENABLE_LLM = original_enable

        return True

    except Exception as e:
        print(f"❌ 降级测试失败: {e}")
        import traceback
        traceback.print_exc()
        return False


async def main():
    """运行所有测试"""
    print("=" * 60)
    print("  LLM + RAG 集成测试套件")
    print(f"  时间: {time.strftime('%Y-%m-%d %H:%M:%S')}")
    print("=" * 60)

    results = {}

    # 运行测试
    results["llm_client"] = await test_llm_client()
    results["rag_engine"] = await test_rag_engine()
    results["agent_integration"] = await test_agent_integration()
    results["fallback"] = await test_fallback_mechanism()

    # 汇总结果
    print_separator("Test Summary")

    passed = sum(1 for v in results.values() if v)
    total = len(results)

    for name, ok in results.items():
        status = "✅ PASS" if ok else "❌ FAIL"
        print(f"  {status}: {name}")

    print(f"\n总计: {passed}/{total} 通过")

    if passed == total:
        print("\n🎉 所有测试通过！LLM + RAG 集成就绪。")
    else:
        print("\n⚠️ 部分测试失败，请检查错误信息。")

    return passed == total


if __name__ == "__main__":
    success = asyncio.run(main())
    sys.exit(0 if success else 1)
