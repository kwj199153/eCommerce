"""
平台适配层契约测试。

★ 本文件为何存在（第 132 轮）：
    `backend/test_platforms.py` 是项目早期的**手工冒烟脚本**（`sys.path.insert('.')`
    + `asyncio.run` + emoji print），因为 `pytest.ini` 的 `testpaths = tests`
    而**从未被收集**，成了根目录的散落死文件。删它之前做了一次覆盖等价性复核
    （AST 数「对同名方法的调用点」，见 `.workbuddy/probes/_r132_b3_coverage_equiv.py`），
    结果发现它承载的 3 个行为在 `tests/` 里**调用点为 0**：

      · 适配器工厂 `get_platform_adapter`（4 个平台 + 未知平台报错）
      · `calculate_fees`（**真实算法**，不是 mock —— 出参直接影响报价建议）
      · `get_reviews`（评价 + 情感 + 痛点提取）

    也就是说它不是「可删的死文件」，而是「错放了位置的唯一覆盖」。
    本文件把它搬进 tests/ 并**补上边界断言**：原脚本只 print 不 assert，
    所以即使算错也不会失败；这里断言的是真正的不变量。

★ 断言为什么这么写（避免「期望值写死 = 假门禁」）：
    不硬编码 4.59 / 9.26 这类数字（那是把**当前实现**固化成契约，
    以后合理调整费率表就会假红）。只断言**自洽性与方向性**：
      · 总额 == 各部分之和（抓「公式改坏」）
      · 费率 == 总额/售价（抓「百分比算错」）
      · 越重运费越贵（抓「重量参数被忽略」）
      · 售价越高费率越低（佣金同比、固定费摊薄的必然结果）
    期望值全部来自探针实测（`.workbuddy/probes/out-r132-c4-platform-probe.txt`）。
"""

import pytest

from platforms import PlatformType, get_platform_adapter
from platforms.base import ProductData, ReviewData

# mock 商品库里真实存在的 ASIN（见 platforms/amazon/client.py 的 MOCK_PRODUCTS）
MOCK_ASIN = "B0CGLKP2R1"


# ====== 1. 工厂方法（原脚本「测试 1」）======

@pytest.mark.parametrize(
    "name,expected",
    [
        ("amazon", PlatformType.AMAZON),
        # ★ 原脚本漏了 shopee —— 工厂里有这一支，属于「加了分支但没人验」
        ("shopee", PlatformType.SHOPEE),
        ("tiktok", PlatformType.TIKTOK),
        ("shopify", PlatformType.SHOPIFY),
    ],
)
def test_factory_returns_adapter_for_every_platform(name, expected):
    """工厂对每个已注册平台都要返回**对应类型**的适配器"""
    adapter = get_platform_adapter(name)
    assert adapter.platform_type is expected, (
        f"get_platform_adapter({name!r}) 返回 {adapter.platform_type}，"
        f"与 PlatformType.{expected.name} 不符 —— 工厂分支接错线了"
    )


def test_factory_accepts_platform_type_enum():
    """入参给枚举值也要能用（文档里的第二种用法）"""
    adapter = get_platform_adapter(PlatformType.TIKTOK)
    assert adapter.platform_type is PlatformType.TIKTOK


def test_factory_is_case_insensitive():
    """平台名大小写不敏感（内部 .lower()）"""
    assert get_platform_adapter("AMAZON").platform_type is PlatformType.AMAZON


def test_factory_rejects_unknown_platform():
    """
    未知平台必须**显式报错**，而不是静默返回一个 Amazon 适配器。

    静默兜底是这类工厂最危险的失效方式：用户在 tiktok 店铺上选品，
    数据其实来自 Amazon 的 mock 库，界面一切正常。
    """
    with pytest.raises(ValueError):
        get_platform_adapter("nonexistent-platform")


# ====== 2. 产品搜索（原脚本「测试 2」）======

async def test_search_products_returns_product_data():
    """搜索返回的是 ProductData 对象（不是 dict），且字段可用于下游计算"""
    products = await get_platform_adapter("amazon").search_products("coffee grinder")
    assert products, "搜索无结果 —— mock 数据源不应为空"
    first = products[0]
    assert isinstance(first, ProductData)
    assert first.product_id, "product_id 为空（下游按它去重/回查）"
    assert first.price > 0, "价格必须为正，否则利润计算会得出荒谬结论"
    # ★ 用 ==/PlatformType() 而不是 `is`：ProductData 把 str-Enum 存成了字符串
    #   （pydantic 的 use_enum_values 行为），`is` 比较在两种形态下不可靠。
    assert PlatformType(first.platform) is PlatformType.AMAZON


# ====== 3. 关键词数据（原脚本「测试 3」）======

async def test_keyword_data_is_well_formed():
    """关键词指标的取值域必须合理（越界会直接污染蓝海评分）"""
    kd = await get_platform_adapter("amazon").get_keyword_data("portable coffee maker")
    assert kd.keyword == "portable coffee maker"
    assert kd.search_volume >= 0
    assert 0.0 <= kd.competition <= 1.0, f"竞争指数必须落在 0~1，实际 {kd.competition}"
    assert kd.trend_direction in ("rising", "stable", "declining")


# ====== 4. 费用计算（原脚本「测试 4」——真实算法，最该有门禁的一块）======

def _fees(price=29.99, category="Home & Kitchen", weight_lbs=1.5):
    return get_platform_adapter("amazon").calculate_fees(
        price=price, category=category, weight_lbs=weight_lbs
    )


def test_fees_total_equals_sum_of_its_parts():
    """
    总额必须等于「佣金 + FBA 配送 + 仓储」——抓「加了一项却忘了进总额」。

    容差 0.02 用于吸收四舍五入（实测差 0.0085）。
    """
    f = _fees()
    expected = 29.99 * f.referral_fee_pct / 100 + f.fba_fulfillment_fee + f.storage_fee_monthly
    assert abs(f.total_fees - expected) < 0.02, (
        f"总额 {f.total_fees} != 佣金({29.99}*{f.referral_fee_pct}%) "
        f"+ 配送 {f.fba_fulfillment_fee} + 仓储 {f.storage_fee_monthly} = {expected}"
    )


def test_fee_percentage_is_total_over_price():
    """费用占比必须真等于 总额/售价 ——抓「百分比字段写死或漏算」"""
    f = _fees()
    assert abs(f.fee_percentage - f.total_fees / 29.99 * 100) < 0.05, (
        f"fee_percentage={f.fee_percentage} 与 total_fees/price="
        f"{f.total_fees / 29.99 * 100:.2f} 不一致"
    )


def test_heavier_item_costs_more_to_fulfill():
    """
    FBA 配送费必须随重量单调上升（重量参数被忽略时这条会红）。

    实测 0.5lb -> 3.22，5lb -> 5.79。
    """
    light = _fees(weight_lbs=0.5)
    heavy = _fees(weight_lbs=5.0)
    assert heavy.fba_fulfillment_fee > light.fba_fulfillment_fee, (
        "越重配送费反而没涨 —— weight_lbs 很可能没接进费率表"
    )


def test_fee_percentage_falls_as_price_rises():
    """
    售价越高、费用占比越低（佣金按比例、配送与仓储是固定额）。

    实测 9.99 -> 62.71%，29.99 -> 30.89%，99.99 -> 19.77%。
    这条同时是「总费用公式没被改成常数」的哨兵。
    """
    cheap = _fees(price=9.99).fee_percentage
    mid = _fees(price=29.99).fee_percentage
    pricey = _fees(price=99.99).fee_percentage
    assert cheap > mid > pricey, (
        f"费用占比未随售价下降：9.99->{cheap} 29.99->{mid} 99.99->{pricey}"
    )


def test_commission_rate_is_a_sane_percentage():
    """佣金比例必须在合理区间（Amazon 各类目 8%~45%，落到区间外必是算错）"""
    f = _fees()
    assert 0 < f.referral_fee_pct <= 45, f"佣金比例 {f.referral_fee_pct}% 不合理"


# ====== 5. 评论分析（原脚本「测试 5」）======

@pytest.mark.parametrize("rating", [1, 2, 5])
async def test_get_reviews_honors_rating_filter(rating):
    """
    rating_filter 必须真的生效。

    ★ 这条在评审时最容易「看起来对」：不带 filter 也返回 10 条，
    只看条数会误判成「filter 没生效」。所以断言的是**每条 rating 都等于目标值**，
    而不是条数（实测 mock 数据每种星级各有 10 条）。
    """
    reviews = await get_platform_adapter("amazon").get_reviews(
        MOCK_ASIN, rating_filter=rating
    )
    assert reviews, f"rating_filter={rating} 返回空 —— 中差评是痛点分析的输入，不能为空"
    assert all(r.rating == rating for r in reviews), (
        f"rating_filter={rating} 却混入了其他星级："
        f"{sorted({r.rating for r in reviews})}"
    )


async def test_get_reviews_unfiltered_covers_multiple_ratings():
    """不带 filter 时应当拿到跨星级样本（否则痛点分析只能看到单一视角）"""
    reviews = await get_platform_adapter("amazon").get_reviews(MOCK_ASIN)
    assert reviews
    assert all(isinstance(r, ReviewData) for r in reviews)
    assert len({r.rating for r in reviews}) > 1, (
        "未筛选的评论全是同一星级 —— 样本退化，痛点结论会失真"
    )


async def test_get_product_detail_returns_none_for_unknown_asin():
    """
    查不到的 ASIN 返回 None，而不是抛异常或返回空壳对象。

    调用方（利润/痛点分析）都按 `if product is None` 分支处理，
    这里改成抛错会把这批分支全部变成死代码。
    """
    assert await get_platform_adapter("amazon").get_product_detail("B0NOTEXIST00") is None
