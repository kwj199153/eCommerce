"""
测试平台适配层功能
"""
import sys
import asyncio

sys.path.insert(0, '.')


async def test_platforms():
    print('🔍 测试平台适配层...')
    print('')

    # 1. 测试工厂方法
    from platforms import get_platform_adapter, PlatformType

    amazon = get_platform_adapter('amazon')
    print(f'✅ Amazon 适配器: {amazon.platform_type.value}')

    tiktok = get_platform_adapter(PlatformType.TIKTOK)
    print(f'✅ TikTok 适配器: {tiktok.platform_type.value}')

    shopify = get_platform_adapter('shopify')
    print(f'✅ Shopify 适配器: {shopify.platform_type.value}')

    print('')

    # 2. 测试 Amazon 功能（模拟数据）
    products = await amazon.search_products('coffee grinder')
    print(f'✅ 搜索产品: 找到 {len(products)} 个结果')
    for p in products[:2]:
        print(f'   - {p.title[:50]}... (${p.price})')

    print('')

    # 3. 测试关键词数据
    keyword_data = await amazon.get_keyword_data('portable coffee maker')
    print(f'✅ 关键词数据:')
    print(f'   - 搜索量: {keyword_data.search_volume:,}')
    print(f'   - 竞争度: {keyword_data.competition:.0%}')
    print(f'   - 趋势: {keyword_data.trend_direction}')

    print('')

    # 4. 测试 FBA 费用计算（真实算法！）
    fees = amazon.calculate_fees(price=29.99, category='Home & Kitchen', weight_lbs=1.5)
    referral = fees.referral_fee_pct * 29.99 / 100
    print(f'✅ FBA 费用计算 (售价 $29.99):')
    print(f'   - 佣金 ({fees.referral_fee_pct}%): ${referral:.2f}')
    print(f'   - FBA 配送费: ${fees.fba_fulfillment_fee:.2f}')
    print(f'   - 月仓储费: ${fees.storage_fee_monthly:.2f}')
    print(f'   - 总费用: ${fees.total_fees:.2f} ({fees.fee_percentage:.1f}%)')

    print('')

    # 5. 测试评论分析
    reviews = await amazon.get_reviews('B0CGLKP2R1', rating_filter=2)
    negative_count = len([r for r in reviews if r.sentiment == 'negative'])
    print(f'✅ 评论分析: 获取 {len(reviews)} 条，其中 {negative_count} 条差评')
    if reviews:
        pain_points = reviews[0].pain_points
        if pain_points:
            print(f'   提取的痛点: {pain_points}')

    print('')
    print('✅ 平台适配层测试通过！')


if __name__ == '__main__':
    asyncio.run(test_platforms())
