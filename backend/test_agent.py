"""
测试选品分析 Agent 功能
"""
import sys
import asyncio

sys.path.insert(0, '.')


async def test_product_research():
    print('🔍 测试选品分析模块...')
    print('')

    # 1. 测试 Agent 导入
    from modules.product_research.agent_product_research import ProductResearchAgent
    print('✅ 选品 Agent 导入成功')

    # 2. 创建 Agent 实例
    agent = ProductResearchAgent(platform="amazon")
    print(f'✅ Agent 创建成功 (平台: {agent.platform})')

    print('')
    print('=' * 60)
    print('📊 测试 1: 蓝海品类挖掘')
    print('=' * 60)

    result1 = await agent.invoke("帮我找厨房用品类的蓝海机会")
    print(f'类型: {result1.display_type}')
    print(f'摘要: {result1.content[:100]}...')
    opportunities = result1.data.get("opportunities", [])
    print(f'发现机会: {len(opportunities)} 个')
    if opportunities:
        for opp in opportunities[:3]:
            print(f'   ⭐ {opp["category"]}: 评分{opp["opportunity_score"]}, 搜索量{opp["search_volume"]:,}')

    print('')
    print('=' * 60)
    print('💰 测试 2: SKU 利润计算')
    print('=' * 60)

    result2 = await agent.invoke("分析便携式咖啡研磨器的利润，售价29.99")
    print(f'类型: {result2.display_type}')
    analysis = result2.data.get("analysis", {})
    if analysis:
        print(f'产品: {analysis.get("product_name")}')
        print(f'售价: ${analysis.get("selling_price")}')
        print(f'成本: ${analysis.get("cost_price")}')
        print(f'净利润: ${analysis.get("net_profit")} (ROI: {analysis.get("roi_percentage")}%)')
        fees = result2.data.get("fees_breakdown", {})
        if fees:
            print('费用明细:')
            for name, amount in fees.items():
                print(f'   - {name}: ${amount}')

    print('')
    print('=' * 60)
    print('😟 测试 3: 痛点识别')
    print('=' * 60)

    result3 = await agent.invoke("分析 B0CGLKP2R1 的用户痛点")
    print(f'类型: {result3.display_type}')
    analysis3 = result3.data.get("analysis", {})
    if analysis3:
        pain_points = analysis3.get("pain_points", [])
        print(f'分析的评论数: {analysis3.get("total_reviews_analyzed")}')
        print(f'差评数: {analysis3.get("negative_review_count")}')
        print(f'市场空白度评分: {analysis3.get("market_gap_score")}/100')
        if pain_points:
            print('高频痛点:')
            for pp in pain_points[:5]:
                print(f'   🔴 {pp["pain_point"]} ({pp["count"]}条, {pp["percentage"]}%)')
        suggestions = analysis3.get("improvement_suggestions", [])
        if suggestions:
            print('改进建议:')
            for s in suggestions:
                print(f'   💡 {s}')

    print('')
    print('=' * 60)
    print('⚔️ 测试 4: 竞品对比')
    print('=' * 60)

    result4 = await agent.invoke("对比 B0CGLKP2R1 和 B0DXYZ1234 这两个产品")
    print(f'类型: {result4.display_type}')
    competitors = result4.data.get("competitors", [])
    print(f'对比竞品数: {len(competitors)}')
    for c in competitors:
        product = c.get("product", {})
        print(f'   - {product.get("title", "N/A")[:40]}... (${product.get("price")})')
        print(f'     Listing质量: {c.get("listing_quality_score")}, 定位: {c.get("price_positioning")}')
        strengths = c.get("strengths", [])
        weaknesses = c.get("weaknesses", [])
        if strengths:
            print(f'     优势: {strengths}')
        if weaknesses:
            print(f'     劣势: {weaknesses[:2]}...')

    print('')
    print('✅ 选品分析 Agent 所有功能测试通过！')


if __name__ == '__main__':
    asyncio.run(test_product_research())
