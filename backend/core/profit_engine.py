"""
通用利润计算引擎 (Phase 10)

支持多平台（Amazon / Shopee）的利润测算：
- 正向计算：已知售价 → 算利润
- 逆向定价：已知目标利润 → 反推原价

设计原则：
- 纯函数引擎，不依赖 Store 模型
- 通过 context dict 注入费率配置（解耦）
- Agent 只接收 context，不知道店铺存在
"""

from enum import Enum
from typing import Optional, Dict, Any, List
from pydantic import BaseModel, Field


# ====== 枚举 ======

class PlatformFeeType(str, Enum):
    """费用平台类型"""
    AMAZON = "amazon"
    SHOPEE = "shopee"


# ====== 费率配置模型 ======

class AmazonFeeConfig(BaseModel):
    """Amazon 费率配置模板"""
    referral_fee_pct: float = Field(default=15.0, description="佣金比例 (%)")
    fba_fulfillment_fee: float = Field(default=3.22, description="FBA 配送费")
    storage_fee_monthly: float = Field(default=0.87, description="月仓储费 (USD/立方英尺)")
    closing_fee: Optional[float] = Field(default=None, description="结算费（仅媒体类目）")
    vat_rate: float = Field(default=0.0, description="VAT 税率 (%)")
    withdrawal_fee_rate: float = Field(default=0.0, description="提现手续费率 (%)")

    # FBA 尺寸分级（可选覆盖）
    size_tier: str = Field(default="standard", description="尺寸等级: standard/oversize/large")


class ShopeeFeeConfig(BaseModel):
    """
    Shopee 费率配置模板

    基于 Shopee 实际费用结构：
    - Commission Fee: 按类目 2%-6%
    - Transaction Fee: 固定金额或比例
    - Growth Fee: 商业增长费（Shopee 独有）
    - Infrastructure Fee: 基础设施费（Shopee 独有）
    - Withdrawal Fee: 提现手续费
    - Logistics Cost: SLS 物流运费
    """
    commission_pct: float = Field(default=5.5, description="佣金比例 (%)")
    transaction_fee: float = Field(default=4.74, description="交易费 (固定金额)")
    growth_fee_pct: float = Field(default=6.41, description="商业增长费比例 (%)")
    infrastructure_fee: float = Field(default=1.07, description="基础设施费 (固定金额)")
    vat_rate: float = Field(default=0.0, description="VAT/消费税税率 (%)")
    withdrawal_fee_rate: float = Field(default=1.0, description="提现手续费率 (%)")
    logistics_cost: float = Field(default=12.50, description="物流成本 (SLS 运费)")


class DiscountRule(BaseModel):
    """折扣规则（支持多层折扣叠加）"""
    coupon_discount_pct: float = Field(default=10.0, description="优惠券/平台券折扣 (%)")
    flash_sale_discount_pct: float = Field(default=45.0, description="闪购/商品折扣 (%)")
    bundle_discount_pct: float = Field(default=0.0, description="打包优惠折扣 (%)")


# ====== 请求/响应模型 ======

class ProfitCalculationRequest(BaseModel):
    """利润计算请求

    ⚠️ 所有金额/费率字段默认值必须是 falsy（0.0 / None）。
    右栏面板与对话结果卡共用这一份请求，任何非 falsy 的默认值都会让
    「用户没填」与「用户填了默认值」无法区分 —— 本项目踩过这个坑：
    mock 里写 `params.shippingCost || 3.2`，用户填 0 也被换成 3.2，凭空多算一笔头程运费。
    """
    product_cost: float = Field(..., gt=0, description="产品成本（采购价）")
    listing_price: Optional[float] = Field(default=None, description="原价/定价（正向计算用）")
    target_profit: Optional[float] = Field(default=None, description="目标毛利（逆向定价用）")
    ad_cost: float = Field(default=0.0, ge=0, description="广告费用")
    quantity: int = Field(default=1, ge=1, description="数量")

    # ===== 通用成本项 =====
    # 此前引擎只认 product_cost，导致同一份输入在面板与引擎下口径不一致
    # （面板算了头程/包装/退货损耗/汇率损失，引擎全部丢弃）。这里补齐。
    shipping_cost: float = Field(default=0.0, ge=0, description="头程运费（/单件）")
    packaging_cost: float = Field(default=0.0, ge=0, description="包装成本（/单件）")
    return_rate_pct: float = Field(default=0.0, ge=0, lt=100, description="退货损耗率 (%)")
    exchange_loss_pct: float = Field(default=0.0, ge=0, lt=100, description="汇率损失率 (%)")
    discount_pct: Optional[float] = Field(
        default=None,
        ge=0,
        lt=100,
        description="促销折扣 (%)。None = 没传，走店铺折扣模板；0 = 显式无折扣",
    )

    # ===== 费率覆盖 =====
    # 面板手改的费率优先于店铺模板。键用「前端表单字段名」——面板不感知平台，
    # 由 apply_fee_overrides 按平台翻译（见下方 _PLATFORM_OVERRIDE_MAP）。
    overrides: Optional[Dict[str, float]] = Field(
        default=None,
        description="覆盖店铺费率模板，如 {'referralFeePct': 12.0}",
    )


class FeeBreakdownItem(BaseModel):
    """单项费用明细"""
    name: str = Field(..., description="费用名称")
    amount: float = Field(..., description="金额")
    is_percentage: bool = Field(default=False, description="是否为比例费用")
    percentage_value: Optional[float] = Field(default=None, description="比例值（如适用）")


class ProfitCalculationResult(BaseModel):
    """利润计算结果"""
    # 平台信息
    platform: str = Field(..., description="平台类型: amazon | shopee")
    currency: str = Field(..., description="货币单位")

    # 价格信息
    listing_price: float = Field(..., description="原价/定价")
    final_price: float = Field(..., description="成交价（扣除折扣后）")

    # 费用明细
    fee_breakdown: List[FeeBreakdownItem] = Field(default_factory=list, description="费用明细列表")
    total_fees: float = Field(default=0.0, description="平台与运营费用合计（不含采购/头程/包装）")
    total_cost: float = Field(default=0.0, description="全部成本 = 采购 + 头程 + 包装 + total_fees")

    # 利润指标
    gross_profit: float = Field(default=0.0, description="毛利额")
    net_profit: float = Field(default=0.0, description="净利润（扣除广告后）")
    profit_margin_pct: float = Field(default=0.0, description="毛利率 (%)")
    roi: float = Field(default=0.0, description="ROI (%)")

    # 折扣信息
    discount_applied: bool = Field(default=False, description="是否应用了折扣")
    effective_discount_pct: float = Field(default=0.0, description="实际综合折扣率 (%)")
    coupon_discount_pct: float = Field(default=0.0, description="优惠券折扣率 (%)")
    flash_sale_discount_pct: float = Field(default=0.0, description="闪购折扣率 (%)")

    # 元数据
    calculation_mode: str = Field(default="forward", description="计算模式: forward | reverse")
    formula_summary: str = Field(default="", description="公式摘要（用于展示）")


# ====== 内置费率模板 ======

# Amazon 各站点默认费率
AMAZON_FEE_TEMPLATES: Dict[str, AmazonFeeConfig] = {
    "amazon_us": AmazonFeeConfig(
        referral_fee_pct=15.0,
        fba_fulfillment_fee=3.22,
        storage_fee_monthly=0.87,
        closing_fee=None,
        vat_rate=0.0,
    ),
    "amazon_uk": AmazonFeeConfig(
        referral_fee_pct=15.99,
        fba_fulfillment_fee=4.08,
        storage_fee_monthly=1.23,
        closing_fee=None,
        vat_rate=20.0,  # 英国 VAT 20%
    ),
    "amazon_de": AmazonFeeConfig(
        referral_fee_pct=15.0,
        fba_fulfillment_fee=3.84,
        storage_fee_monthly=1.19,
        closing_fee=None,
        vat_rate=19.0,  # 德国 VAT 19%
    ),
    "amazon_jp": AmazonFeeConfig(
        referral_fee_pct=10.0,
        fba_fulfillment_fee=2.96,
        storage_fee_monthly=0.65,
        closing_fee=None,
        vat_rate=10.0,  # 日本 JCT 10%
    ),
}

# Shopee 各站点默认费率
SHOPEE_FEE_TEMPLATES: Dict[str, ShopeeFeeConfig] = {
    "shopee_my": ShopeeFeeConfig(
        commission_pct=5.5,
        transaction_fee=4.74,
        growth_fee_pct=6.41,
        infrastructure_fee=1.07,
        vat_rate=0.0,  # 马来西亚目前无 VAT
        withdrawal_fee_rate=1.0,
        logistics_cost=12.50,
    ),
    "shopee_tw": ShopeeFeeConfig(
        commission_pct=6.0,
        transaction_fee=5.00,
        growth_fee_pct=7.0,
        infrastructure_fee=1.20,
        vat_rate=5.0,  # 台湾营业税 5%
        withdrawal_fee_rate=1.5,
        logistics_cost=15.00,
    ),
    "shopee_ph": ShopeeFeeConfig(
        commission_pct=5.8,
        transaction_fee=3.50,
        growth_fee_pct=5.5,
        infrastructure_fee=0.90,
        vat_rate=12.0,  # 菲律宾 VAT 12%
        withdrawal_fee_rate=1.0,
        logistics_cost=10.00,
    ),
    "shopee_th": ShopeeFeeConfig(
        commission_pct=4.9,
        transaction_fee=3.20,
        growth_fee_pct=5.0,
        infrastructure_fee=0.85,
        vat_rate=7.0,  # 泰国 VAT 7%
        withdrawal_fee_rate=1.0,
        logistics_cost=11.00,
    ),
    "shopee_sg": ShopeeFeeConfig(
        commission_pct=5.16,
        transaction_fee=3.80,
        growth_fee_pct=5.5,
        infrastructure_fee=0.90,
        vat_rate=8.0,  # 新加坡 GST 8%（2023年起）
        withdrawal_fee_rate=1.0,
        logistics_cost=8.00,
    ),
    "shopee_vn": ShopeeFeeConfig(
        commission_pct=6.0,
        transaction_fee=2.80,
        growth_fee_pct=6.0,
        infrastructure_fee=0.70,
        vat_rate=10.0,  # 越南 VAT 10%
        withdrawal_fee_rate=1.0,
        logistics_cost=13.00,
    ),
    "shopee_id": ShopeeFeeConfig(
        commission_pct=5.6,
        transaction_fee=3.60,
        growth_fee_pct=5.8,
        infrastructure_fee=0.80,
        vat_rate=11.0,  # 印尼 PPN 11%
        withdrawal_fee_rate=1.0,
        logistics_cost=14.00,
    ),
    "shopee_br": ShopeeFeeConfig(
        commission_pct=10.0,
        transaction_fee=5.00,
        growth_fee_pct=8.0,
        infrastructure_fee=1.20,
        vat_rate=17.0,  # 巴西 ICMS ~17%
        withdrawal_fee_rate=1.5,
        logistics_cost=18.00,
    ),
}

# 默认折扣规则
DEFAULT_DISCOUNT_RULES: Dict[str, DiscountRule] = {
    "default": DiscountRule(
        coupon_discount_pct=10.0,
        flash_sale_discount_pct=45.0,
    ),
    "aggressive": DiscountRule(
        coupon_discount_pct=15.0,
        flash_sale_discount_pct=55.0,
    ),
    "conservative": DiscountRule(
        coupon_discount_pct=5.0,
        flash_sale_discount_pct=30.0,
    ),
    "no_discount": DiscountRule(
        coupon_discount_pct=0.0,
        flash_sale_discount_pct=0.0,
    ),
}


# ====== 核心计算函数 ======

# 前端面板「语义字段名」→ 各平台费率字段名。
# 面板只发语义名（它不感知当前店铺是 Amazon 还是 Shopee），按平台在这里翻译；
# 语义无法等价的项直接丢弃（Shopee 没有 FBA 配送费，面板的 fbaFee 对它无意义）。
_PLATFORM_OVERRIDE_MAP: Dict[str, Dict[str, str]] = {
    "amazon": {
        "referralFeePct": "referral_fee_pct",
        "fbaFee": "fba_fulfillment_fee",
        "storageFee": "storage_fee_monthly",
        "vatRate": "vat_rate",
        "withdrawalFeePct": "withdrawal_fee_rate",
    },
    "shopee": {
        "referralFeePct": "commission_pct",
        "withdrawalFeePct": "withdrawal_fee_rate",
        "vatRate": "vat_rate",
        "shippingCost": "logistics_cost",
    },
}


def apply_fee_overrides(fee_config, platform: str, overrides: Optional[Dict[str, float]]):
    """
    把面板手改的费率覆盖到店铺模板上，返回**新实例**。

    模板对象是模块级单例，就地修改会污染其他店铺/其他请求 —— 必须 model_copy。
    """
    if not overrides:
        return fee_config
    mapping = _PLATFORM_OVERRIDE_MAP.get(platform, {})
    allowed = type(fee_config).model_fields
    patch: Dict[str, float] = {}
    for form_key, value in overrides.items():
        if value is None:
            continue
        field = mapping.get(form_key)
        if field and field in allowed:
            patch[field] = float(value)
    if not patch:
        return fee_config
    return fee_config.model_copy(update=patch)


def _discount_pct(req: ProfitCalculationRequest, disc: DiscountRule, layered: bool) -> float:
    """
    综合折扣率 (%)。面板显式传了 discount_pct 就以它为准（含 0 = 无折扣），
    没传（None）才回落到店铺折扣模板。
    layered=True 表示该平台有多层折扣叠加（Shopee：券 × 闪购 × 打包）。
    """
    if req.discount_pct is not None:
        return req.discount_pct
    if not layered:
        return disc.coupon_discount_pct
    keep = (
        (1 - disc.coupon_discount_pct / 100)
        * (1 - disc.flash_sale_discount_pct / 100)
        * (1 - disc.bundle_discount_pct / 100)
    )
    return (1 - keep) * 100


def _reverse_price(
    req: ProfitCalculationRequest,
    platform_fixed_fees: float,
    platform_rate_pct: float,
    discount_pct: float,
) -> float:
    """
    逆向定价：已知目标毛利 → 反推标价。

    推导与正向**逐项对应**（这是「同源」的关键：两向必须用同一套成本构成，
    否则同一个目标毛利会算出两个不同的售价）：
        固定成本 F = 采购 + 头程 + 包装 + 广告 + 平台固定费
        退货损耗   = F × rr/(1-rr)        ⇒ F + 退货损耗 = F/(1-rr)
        比例费用   = 成交价 × (平台比例费率 + 汇率损失率)
        毛利 = 成交价 − F/(1-rr) − 成交价 × 比例费率
        ⇒ 成交价 = (目标毛利 + F/(1-rr)) / (1 − 比例费率合计)
        ⇒ 标价   = 成交价 / (1 − 折扣率)
    """
    fixed = (
        req.product_cost
        + req.shipping_cost
        + req.packaging_cost
        + req.ad_cost
        + platform_fixed_fees
    )
    rr = req.return_rate_pct / 100.0
    if rr >= 1:
        raise ValueError("退货损耗率必须小于 100%")
    fixed_with_return = fixed / (1 - rr) if rr > 0 else fixed

    rate_sum = (platform_rate_pct + req.exchange_loss_pct) / 100.0
    denominator = 1 - rate_sum
    if denominator <= 0:
        raise ValueError(f"费率合计 ({rate_sum * 100:.1f}%) 已达 100%，无法反推出有效价格")

    actual_price = (req.target_profit + fixed_with_return) / denominator
    if discount_pct > 0:
        return round(actual_price / (1 - discount_pct / 100), 2)
    return round(actual_price, 2)


def _finalize(
    *,
    req: ProfitCalculationRequest,
    platform: str,
    currency: str,
    listing_price: float,
    final_price: float,
    platform_fixed_items: List[FeeBreakdownItem],
    rate_items: List[FeeBreakdownItem],
    disc_meta: Dict[str, Any],
    formula_prefix: str,
) -> ProfitCalculationResult:
    """
    统一结果组装 —— 两平台一致，也与右栏面板口径一致。

        固定成本 = 采购 + 头程 + 包装 + 广告 + 平台固定费
        退货损耗 = 固定成本 × rr/(1-rr)
        比例费用 = 成交价 × (佣金 + VAT + 提现 + 汇率损失)
        总成本   = 固定成本 + 退货损耗 + 比例费用
        净利润   = 成交价 − 总成本
    """
    base_fixed = req.product_cost + req.shipping_cost + req.packaging_cost + req.ad_cost
    # 只有**不随售价变化**的费用才能进固定成本基数 —— 退货损耗按它计算。
    # 把佣金这类按成交价比例收取的费用算进来，会凭空放大退货损耗。
    fixed_cost = base_fixed + sum(item.amount for item in platform_fixed_items)

    rr = req.return_rate_pct / 100.0
    return_loss = fixed_cost * rr / (1 - rr) if rr > 0 else 0.0
    if return_loss > 0:
        rate_items = rate_items + [
            FeeBreakdownItem(
                name=f"退货损耗 ({req.return_rate_pct}%)",
                amount=return_loss,
                is_percentage=True,
                percentage_value=req.return_rate_pct,
            )
        ]

    exchange_loss = final_price * req.exchange_loss_pct / 100.0
    if exchange_loss > 0:
        rate_items = rate_items + [
            FeeBreakdownItem(
                name=f"汇率损失 ({req.exchange_loss_pct}%)",
                amount=exchange_loss,
                is_percentage=True,
                percentage_value=req.exchange_loss_pct,
            )
        ]

    items: List[FeeBreakdownItem] = [
        FeeBreakdownItem(name="采购成本", amount=req.product_cost),
    ]
    if req.shipping_cost > 0:
        items.append(FeeBreakdownItem(name="头程运费", amount=req.shipping_cost))
    if req.packaging_cost > 0:
        items.append(FeeBreakdownItem(name="包装成本", amount=req.packaging_cost))
    items.extend(platform_fixed_items)
    if req.ad_cost > 0:
        items.append(FeeBreakdownItem(name="广告费用", amount=req.ad_cost))
    items.extend(rate_items)

    # 计算全程保留全精度，只在输出前统一取到「分」——中间项先舍入会把误差累计放大，
    # 面板与引擎必须给出同一个数字，这种 0.01 级的口径差也算「两个结果」。
    items = [item.model_copy(update={"amount": round(item.amount, 2)}) for item in items]
    # 总成本 = 明细之和（而不是增量累加）—— 保证「明细能加出合计」，用户自己减也对得上
    total_cost = sum(item.amount for item in items)
    net_profit = round(final_price - total_cost, 2)

    return ProfitCalculationResult(
        platform=platform,
        currency=currency,
        listing_price=round(listing_price, 2),
        final_price=round(final_price, 2),
        fee_breakdown=items,
        total_fees=round(
            total_cost - req.product_cost - req.shipping_cost - req.packaging_cost, 2
        ),
        total_cost=round(total_cost, 2),
        gross_profit=round(net_profit, 2),
        net_profit=round(net_profit, 2),
        profit_margin_pct=round(net_profit / final_price * 100, 2) if final_price > 0 else 0.0,
        roi=round(net_profit / req.product_cost * 100, 2) if req.product_cost > 0 else 0.0,
        discount_applied=bool(disc_meta.get("applied")),
        effective_discount_pct=round(disc_meta.get("effective_pct", 0.0), 2),
        coupon_discount_pct=disc_meta.get("coupon_pct", 0.0),
        flash_sale_discount_pct=disc_meta.get("flash_pct", 0.0),
        calculation_mode=disc_meta.get("mode", "forward"),
        formula_summary=f"{formula_prefix}；成本合计 {total_cost:.2f}，净利润 {net_profit:.2f}",
    )


def calculate_profit(
    req: ProfitCalculationRequest,
    context: Dict[str, Any],
) -> ProfitCalculationResult:
    """
    通用利润计算入口

    Args:
        req: 计算请求参数
        context: 由 API 中间件注入的上下文：
            - platform: "amazon" | "shopee"
            - fee_config: AmazonFeeConfig 或 ShopeeFeeConfig 实例
            - currency: "USD" | "MYR" | "TWD" 等
            - discount_rules: DiscountRule 实例

    Returns:
        ProfitCalculationResult 包含完整计算结果
    """
    platform = context.get("platform", "amazon")
    fee_config = context.get("fee_config")
    currency = context.get("currency", "USD")
    discount_rules = context.get("discount_rules", DEFAULT_DISCOUNT_RULES["default"])

    if not fee_config:
        raise ValueError("context 中缺少 fee_config（费率配置）")

    # 面板手改的费率优先于店铺模板（模板仍是基准值）
    fee_config = apply_fee_overrides(fee_config, platform, req.overrides)

    if platform == PlatformFeeType.AMAZON:
        return _calculate_amazon(req, fee_config, currency, discount_rules)
    elif platform == PlatformFeeType.SHOPEE:
        return _calculate_shopee(req, fee_config, currency, discount_rules)
    else:
        raise ValueError(f"不支持的平台类型: {platform}")


def _calculate_amazon(
    req: ProfitCalculationRequest,
    cfg: AmazonFeeConfig,
    currency: str,
    disc: DiscountRule,
) -> ProfitCalculationResult:
    """
    Amazon 利润计算

    佣金/VAT 等按比例的费用基于**成交价**（折后价）计算；FBA、仓储、广告等
    与售价无关的费用直接计入固定成本。
    """
    discount_pct = _discount_pct(req, disc, layered=False)

    # 逆向定价：给了目标毛利、没给标价 → 先反推标价，再按正向完整走一遍
    if req.target_profit is not None and req.listing_price is None:
        listing_price = _reverse_price(
            req,
            platform_fixed_fees=(
                cfg.fba_fulfillment_fee + cfg.storage_fee_monthly + (cfg.closing_fee or 0)
            ),
            platform_rate_pct=cfg.referral_fee_pct + cfg.vat_rate + cfg.withdrawal_fee_rate,
            discount_pct=discount_pct,
        )
        result = _calculate_amazon(
            req.model_copy(update={"listing_price": listing_price, "target_profit": None}),
            cfg,
            currency,
            disc,
        )
        result.calculation_mode = "reverse"
        result.formula_summary = (
            f"逆向定价：目标毛利 {req.target_profit}{currency} → 反推标价 "
            f"{listing_price:.2f}{currency}"
            + (f"（含 {discount_pct:.1f}% 折扣）" if discount_pct > 0 else "")
        )
        return result

    listing_price = req.listing_price or 0.0
    final_price = listing_price * (1 - discount_pct / 100)

    platform_fixed_items: List[FeeBreakdownItem] = [
        FeeBreakdownItem(name="FBA 配送费", amount=cfg.fba_fulfillment_fee),
        FeeBreakdownItem(name="月仓储费", amount=cfg.storage_fee_monthly),
    ]
    if cfg.closing_fee and cfg.closing_fee > 0:
        platform_fixed_items.append(FeeBreakdownItem(name="结算费", amount=cfg.closing_fee))

    # 佣金按成交价比例收取 → 属于「比例费用」，不能混进固定成本基数
    rate_items: List[FeeBreakdownItem] = [
        FeeBreakdownItem(
            name=f"平台佣金 ({cfg.referral_fee_pct}%)",
            amount=final_price * cfg.referral_fee_pct / 100,
            is_percentage=True,
            percentage_value=cfg.referral_fee_pct,
        ),
    ]
    if cfg.vat_rate > 0:
        rate_items.append(
            FeeBreakdownItem(
                name=f"VAT ({cfg.vat_rate}%)",
                amount=final_price * cfg.vat_rate / 100,
                is_percentage=True,
                percentage_value=cfg.vat_rate,
            )
        )
    if cfg.withdrawal_fee_rate > 0:
        rate_items.append(
            FeeBreakdownItem(
                name=f"提现手续费 ({cfg.withdrawal_fee_rate}%)",
                amount=final_price * cfg.withdrawal_fee_rate / 100,
                is_percentage=True,
                percentage_value=cfg.withdrawal_fee_rate,
            )
        )

    return _finalize(
        req=req,
        platform="amazon",
        currency=currency,
        listing_price=listing_price,
        final_price=final_price,
        platform_fixed_items=platform_fixed_items,
        rate_items=rate_items,
        disc_meta={
            "applied": discount_pct > 0,
            "effective_pct": discount_pct,
            "coupon_pct": (
                discount_pct if req.discount_pct is not None else disc.coupon_discount_pct
            ),
            "flash_pct": 0.0,
        },
        formula_prefix=(
            f"成交价 {final_price:.2f} = 标价 {listing_price:.2f}"
            + (f" × (1-{discount_pct}%)" if discount_pct > 0 else "")
        ),
    )


def _calculate_shopee(
    req: ProfitCalculationRequest,
    cfg: ShopeeFeeConfig,
    currency: str,
    disc: DiscountRule,
) -> ProfitCalculationResult:
    """
    Shopee 利润计算

    Shopee 特殊之处：
    1. 折扣多层叠加：Coupon OFF × Flash Sale OFF × Bundle OFF
    2. 费用基于「成交价」而非「原价」
    3. 有商业增长费、基础设施费等 Shopee 独有费用项
    """
    discount_pct = _discount_pct(req, disc, layered=True)

    if req.target_profit is not None and req.listing_price is None:
        original_price = _reverse_price(
            req,
            platform_fixed_fees=cfg.transaction_fee + cfg.infrastructure_fee + cfg.logistics_cost,
            platform_rate_pct=(
                cfg.commission_pct
                + cfg.growth_fee_pct
                + cfg.vat_rate
                + cfg.withdrawal_fee_rate
            ),
            discount_pct=discount_pct,
        )
        result = _calculate_shopee(
            req.model_copy(update={"listing_price": original_price, "target_profit": None}),
            cfg,
            currency,
            disc,
        )
        result.calculation_mode = "reverse"
        result.formula_summary = (
            f"逆向定价：目标毛利 {req.target_profit}{currency} → 反推原价 "
            f"{original_price:.2f}{currency}"
            + (f"（含 {discount_pct:.1f}% 综合折扣）" if discount_pct > 0 else "")
        )
        return result

    original_price = req.listing_price or 0.0
    final_price = original_price * (1 - discount_pct / 100)

    platform_fixed_items: List[FeeBreakdownItem] = [
        FeeBreakdownItem(name="交易费", amount=cfg.transaction_fee),
        FeeBreakdownItem(name="基础设施费", amount=cfg.infrastructure_fee),
        FeeBreakdownItem(name="物流成本 (SLS)", amount=cfg.logistics_cost),
    ]

    rate_items: List[FeeBreakdownItem] = [
        FeeBreakdownItem(
            name=f"佣金 ({cfg.commission_pct}%)",
            amount=final_price * cfg.commission_pct / 100,
            is_percentage=True,
            percentage_value=cfg.commission_pct,
        ),
        FeeBreakdownItem(
            name=f"商业增长费 ({cfg.growth_fee_pct}%)",
            amount=final_price * cfg.growth_fee_pct / 100,
            is_percentage=True,
            percentage_value=cfg.growth_fee_pct,
        ),
    ]
    if cfg.vat_rate > 0:
        rate_items.append(
            FeeBreakdownItem(
                name=f"VAT/税费 ({cfg.vat_rate}%)",
                amount=final_price * cfg.vat_rate / 100,
                is_percentage=True,
                percentage_value=cfg.vat_rate,
            )
        )
    if cfg.withdrawal_fee_rate > 0:
        rate_items.append(
            FeeBreakdownItem(
                name=f"提现手续费 ({cfg.withdrawal_fee_rate}%)",
                amount=final_price * cfg.withdrawal_fee_rate / 100,
                is_percentage=True,
                percentage_value=cfg.withdrawal_fee_rate,
            )
        )

    return _finalize(
        req=req,
        platform="shopee",
        currency=currency,
        listing_price=original_price,
        final_price=final_price,
        platform_fixed_items=platform_fixed_items,
        rate_items=rate_items,
        disc_meta={
            "applied": discount_pct > 0.01,
            "effective_pct": discount_pct,
            "coupon_pct": (
                discount_pct if req.discount_pct is not None else disc.coupon_discount_pct
            ),
            "flash_pct": (
                0.0 if req.discount_pct is not None else disc.flash_sale_discount_pct
            ),
        },
        formula_prefix=(
            f"原价 {original_price:.2f} → 成交价 {final_price:.2f}"
            + (f"（综合折扣 {discount_pct:.1f}%）" if discount_pct > 0 else "")
        ),
    )




def get_fee_template(platform_key: str):
    """
    根据平台 key 获取费率模板

    Args:
        platform_key: 如 "amazon_us", "shopee_my"

    Returns:
        AmazonFeeConfig 或 ShopeeFeeConfig 实例
    """
    if platform_key in AMAZON_FEE_TEMPLATES:
        return AMAZON_FEE_TEMPLATES[platform_key]
    elif platform_key in SHOPEE_FEE_TEMPLATES:
        return SHOPEE_FEE_TEMPLATES[platform_key]
    else:
        raise ValueError(
            f"未知的平台 key: {platform_key}。"
            f"Amazon: {list(AMAZON_FEE_TEMPLATES.keys())}, "
            f"Shopee: {list(SHOPEE_FEE_TEMPLATES.keys())}"
        )


def get_platform_type_from_key(platform_key: str) -> str:
    """从 platform_key 判断是 amazon 还是 shopee"""
    if platform_key.startswith("amazon"):
        return "amazon"
    elif platform_key.startswith("shopee"):
        return "shopee"
    else:
        return "unknown"


def get_currency_for_marketplace(platform_key: str) -> str:
    """根据站点返回默认币种"""
    currency_map = {
        "amazon_us": "USD", "amazon_uk": "GBP", "amazon_de": "EUR",
        "amazon_jp": "JPY",
        "shopee_my": "MYR", "shopee_tw": "TWD", "shopee_ph": "PHP",
        "shopee_th": "THB", "shopee_sg": "SGD", "shopee_vn": "VND",
        "shopee_id": "IDR", "shopee_br": "BRL",
    }
    return currency_map.get(platform_key, "USD")


def list_supported_markets() -> Dict[str, List[str]]:
    """列出所有支持的站点"""
    return {
        "amazon": list(AMAZON_FEE_TEMPLATES.keys()),
        "shopee": list(SHOPEE_FEE_TEMPLATES.keys()),
    }
