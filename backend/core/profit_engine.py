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
    """利润计算请求"""
    product_cost: float = Field(..., gt=0, description="产品成本")
    listing_price: Optional[float] = Field(default=None, description="原价/定价（正向计算用）")
    target_profit: Optional[float] = Field(default=None, description="目标毛利（逆向定价用）")
    ad_cost: float = Field(default=0.0, ge=0, description="广告费用")
    quantity: int = Field(default=1, ge=1, description="数量")


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
    total_fees: float = Field(default=0.0, description="总费用")

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

    Amazon 通常无折扣（或仅 Coupon），费用基于售价直接计算。
    """
    # 逆向定价模式：已知目标利润 → 反推原价
    if req.target_profit is not None and req.listing_price is None:
        listing_price = _reverse_pricing_amazon(
            product_cost=req.product_cost,
            target_profit=req.target_profit,
            ad_cost=req.ad_cost,
            cfg=cfg,
            disc=disc,
        )
        # 用反推出的价格重新正向计算
        new_req = ProfitCalculationRequest(
            product_cost=req.product_cost,
            listing_price=listing_price,
            ad_cost=req.ad_cost,
            quantity=req.quantity,
        )
        result = _calculate_amazon(new_req, cfg, currency, disc)
        result.calculation_mode = "reverse"
        result.formula_summary = (
            f"逆向定价: 目标毛利 {req.target_profit}{currency} → "
            f"反推原价 {listing_price:.2f}{currency}"
        )
        return result

    price = req.listing_price or 0.0

    # === 费用计算（基于售价） ===
    breakdown: List[FeeBreakdownItem] = []

    # 1. 佣金 Referral Fee
    referral = round(price * cfg.referral_fee_pct / 100, 2)
    breakdown.append(FeeBreakdownItem(
        name=f"佣金 ({cfg.referral_fee_pct}%)",
        amount=referral,
        is_percentage=True,
        percentage_value=cfg.referral_fee_pct,
    ))

    # 2. FBA 配送费
    breakdown.append(FeeBreakdownItem(
        name="FBA 配送费",
        amount=cfg.fba_fulfillment_fee,
        is_percentage=False,
    ))

    # 3. 仓储费
    breakdown.append(FeeBreakdownItem(
        name="月仓储费",
        amount=cfg.storage_fee_monthly,
        is_percentage=False,
    ))

    # 4. 结算费（如有）
    if cfg.closing_fee and cfg.closing_fee > 0:
        breakdown.append(FeeBreakdownItem(
            name="结算费",
            amount=cfg.closing_fee,
            is_percentage=False,
        ))

    # 5. VAT（如有）
    if cfg.vat_rate > 0:
        vat = round(price * cfg.vat_rate / 100, 2)
        breakdown.append(FeeBreakdownItem(
            name=f"VAT ({cfg.vat_rate}%)",
            amount=vat,
            is_percentage=True,
            percentage_value=cfg.vat_rate,
        ))

    # 6. 广告费用
    if req.ad_cost > 0:
        breakdown.append(FeeBreakdownItem(
            name="广告费用",
            amount=req.ad_cost,
            is_percentage=False,
        ))

    total_fees = sum(item.amount for item in breakdown)
    gross_profit = price - req.product_cost - total_fees + req.ad_cost  # 广告已计入费用
    net_profit = gross_profit  # Amazon 无额外扣除

    # 折扣处理（Amazon 通常只有优惠券）
    final_price = price
    discount_applied = False
    effective_disc_pct = 0.0
    if disc.coupon_discount_pct > 0:
        final_price = price * (1 - disc.coupon_discount_pct / 100)
        discount_applied = True
        effective_disc_pct = disc.coupon_discount_pct

    return ProfitCalculationResult(
        platform="amazon",
        currency=currency,
        listing_price=round(price, 2),
        final_price=round(final_price, 2),
        fee_breakdown=breakdown,
        total_fees=round(total_fees, 2),
        gross_profit=round(gross_profit, 2),
        net_profit=round(net_profit, 2),
        profit_margin_pct=round(gross_profit / price * 100, 2) if price > 0 else 0,
        roi=round(gross_profit / req.product_cost * 100, 2) if req.product_cost > 0 else 0,
        discount_applied=discount_applied,
        effective_discount_pct=round(effective_disc_pct, 2),
        coupon_discount_pct=disc.coupon_discount_pct,
        flash_sale_discount_pct=0.0,
        calculation_mode="forward",
        formula_summary=(
            f"毛利 = 售价({price:.2f}) - 成本({req.product_cost}) - 总费用({total_fees:.2f}) = {gross_profit:.2f}"
        ),
    )


def _calculate_shopee(
    req: ProfitCalculationRequest,
    cfg: ShopeeFeeConfig,
    currency: str,
    disc: DiscountRule,
) -> ProfitCalculationResult:
    """
    Shopee 利润计算（含完整的多层折扣逻辑）

    Shopee 特殊之处：
    1. 两道折扣叠加：Coupon OFF × Flash Sale OFF
    2. 费用基于「成交价」而非「原价」计算
    3. 有商业增长费、基础设施费等 Shopee 独有费用项
    """
    # 逆向定价模式：已知目标利润 → 反推原价
    if req.target_profit is not None and req.listing_price is None:
        original_price = _reverse_pricing_shopee(
            product_cost=req.product_cost,
            target_profit=req.target_profit,
            ad_cost=req.ad_cost,
            cfg=cfg,
            disc=disc,
        )
        # 用反推出的价格重新正向计算
        new_req = ProfitCalculationRequest(
            product_cost=req.product_cost,
            listing_price=original_price,
            ad_cost=req.ad_cost,
            quantity=req.quantity,
        )
        result = _calculate_shopee(new_req, cfg, currency, disc)
        result.calculation_mode = "reverse"
        result.formula_summary = (
            f"逆向定价: 目标毛利 {req.target_profit}{currency} -> "
            f"反推原价 {original_price:.2f}{currency} -> "
            f"成交价 {result.final_price:.2f}{currency} (折扣 {result.effective_discount_pct:.1f}%)"
        )
        return result

    original_price = req.listing_price or 298.0  # 默认原价

    # === 折扣计算（两道叠加） ===
    coupon_factor = 1 - disc.coupon_discount_pct / 100      # 如 0.90
    flash_factor = 1 - disc.flash_sale_discount_pct / 100     # 如 0.55
    bundle_factor = 1 - disc.bundle_discount_pct / 100       # 如 1.00
    discount_factor = coupon_factor * flash_factor * bundle_factor  # 综合折扣因子

    final_price = original_price * discount_factor

    # === 费用计算（基于成交价 final_price） ===
    breakdown: List[FeeBreakdownItem] = []

    # 1. 佣金 Commission
    commission = round(final_price * cfg.commission_pct / 100, 2)
    breakdown.append(FeeBreakdownItem(
        name=f"佣金 ({cfg.commission_pct}%)",
        amount=commission,
        is_percentage=True,
        percentage_value=cfg.commission_pct,
    ))

    # 2. 交易费 Transaction Fee
    breakdown.append(FeeBreakdownItem(
        name="交易费",
        amount=cfg.transaction_fee,
        is_percentage=False,
    ))

    # 3. 商业增长费 Growth Fee（Shopee 独有）
    growth = round(final_price * cfg.growth_fee_pct / 100, 2)
    breakdown.append(FeeBreakdownItem(
        name=f"商业增长费 ({cfg.growth_fee_pct}%)",
        amount=growth,
        is_percentage=True,
        percentage_value=cfg.growth_fee_pct,
    ))

    # 4. 基础设施费 Infrastructure Fee（Shopee 独有）
    breakdown.append(FeeBreakdownItem(
        name="基础设施费",
        amount=cfg.infrastructure_fee,
        is_percentage=False,
    ))

    # 5. VAT / 消费税
    if cfg.vat_rate > 0:
        vat = round(final_price * cfg.vat_rate / 100, 2)
        breakdown.append(FeeBreakdownItem(
            name=f"VAT/税费 ({cfg.vat_rate}%)",
            amount=vat,
            is_percentage=True,
            percentage_value=cfg.vat_rate,
        ))
    else:
        breakdown.append(FeeBreakdownItem(
            name="VAT/税费",
            amount=0.0,
            is_percentage=True,
            percentage_value=cfg.vat_rate,
        ))

    # 6. 提现手续费 Withdrawal Fee
    withdrawal = round(final_price * cfg.withdrawal_fee_rate / 100, 2)
    breakdown.append(FeeBreakdownItem(
        name=f"提现手续费 ({cfg.withdrawal_fee_rate}%)",
        amount=withdrawal,
        is_percentage=True,
        percentage_value=cfg.withdrawal_fee_rate,
    ))

    # 7. 物流成本 Logistics（SLS 运费）
    breakdown.append(FeeBreakdownItem(
        name="物流成本 (SLS)",
        amount=cfg.logistics_cost,
        is_percentage=False,
    ))

    # 8. 广告费用
    if req.ad_cost > 0:
        breakdown.append(FeeBreakdownItem(
            name="广告费用",
            amount=req.ad_cost,
            is_percentage=False,
        ))

    total_fees = sum(item.amount for item in breakdown)
    gross_profit = final_price - req.product_cost - total_fees
    net_profit = gross_profit  # 已包含所有费用

    # 综合折扣率
    effective_disc_pct = (1 - discount_factor) * 100
    discount_applied = effective_disc_pct > 0.01

    return ProfitCalculationResult(
        platform="shopee",
        currency=currency,
        listing_price=round(original_price, 2),
        final_price=round(final_price, 2),
        fee_breakdown=breakdown,
        total_fees=round(total_fees, 2),
        gross_profit=round(gross_profit, 2),
        net_profit=round(net_profit, 2),
        profit_margin_pct=round(gross_profit / final_price * 100, 2) if final_price > 0 else 0,
        roi=round(gross_profit / req.product_cost * 100, 2) if req.product_cost > 0 else 0,
        discount_applied=discount_applied,
        effective_discount_pct=round(effective_disc_pct, 2),
        coupon_discount_pct=disc.coupon_discount_pct,
        flash_sale_discount_pct=disc.flash_sale_discount_pct,
        calculation_mode="forward",
        formula_summary=(
            f"原价{original_price:.2f} x (1-{disc.coupon_discount_pct}%) x (1-{disc.flash_sale_discount_pct}%)"
            f" = 成交价{final_price:.2f}; "
            f"毛利 = {final_price:.2f} - 成本{req.product_cost} - 费用{total_fees:.2f} = {gross_profit:.2f}"
        ),
    )


# ====== 逆向定价算法 ======

def _reverse_pricing_amazon(
    product_cost: float,
    target_profit: float,
    ad_cost: float,
    cfg: AmazonFeeConfig,
    disc: DiscountRule,
) -> float:
    """
    Amazon 逆向定价：已知目标利润 → 反推所需售价

    公式推导：
    profit = price - cost - fees
    其中 fees = price * (referral% + vat%) + fixed_fees (fba + storage + closing + ad)

    设 rate_sum = referral% + vat%，fixed = fba + storage + closing + ad
    profit = price * (1 - rate_sum) - cost - fixed
    => price = (profit + cost + fixed) / (1 - rate_sum)
    """
    rate_sum = (cfg.referral_fee_pct + cfg.vat_rate) / 100.0
    fixed_fees = cfg.fba_fulfillment_fee + cfg.storage_fee_monthly + (cfg.closing_fee or 0) + ad_cost

    denominator = 1.0 - rate_sum
    if denominator <= 0:
        raise ValueError(f"费率总和 ({rate_sum*100:.1f}%) >= 100%，无法计算有效价格")

    price = (target_profit + product_cost + fixed_fees) / denominator

    # 如果有优惠券折扣，需要把价格调高以补偿
    if disc.coupon_discount_pct > 0:
        price = price / (1 - disc.coupon_discount_pct / 100)

    return round(price, 2)


def _reverse_pricing_shopee(
    product_cost: float,
    target_profit: float,
    ad_cost: float,
    cfg: ShopeeFeeConfig,
    disc: DiscountRule,
) -> float:
    """
    Shopee 逆向定价：已知目标利润 → 反推原价

    公式推导（考虑两道折扣叠加）：

    设原价为 P，综合折扣因子 D = (1-d1)*(1-d2)*(1-d3)
    成交价 = P * D

    成交价上的比例费用率 R = (commission% + growth% + vat% + withdrawal%) / 100
    固定费用 F = tx_fee + infra_fee + logistics + ad_cost

    毛利 = P*D - cost - P*D*R - F = target_profit
    => P * D * (1 - R) = target_profit + cost + F
    => P = (target_profit + cost + F) / (D * (1 - R))
    """
    d1 = disc.coupon_discount_pct / 100.0
    d2 = disc.flash_sale_discount_pct / 100.0
    d3 = disc.bundle_discount_pct / 100.0
    discount_factor = (1 - d1) * (1 - d2) * (1 - d3)

    # 所有按成交价收取的比例费率之和
    rate_sum = (
        cfg.commission_pct +
        cfg.growth_fee_pct +
        cfg.vat_rate +
        cfg.withdrawal_fee_rate
    ) / 100.0

    # 固定费用（不随价格变化）
    fixed_fees = (
        cfg.transaction_fee +
        cfg.infrastructure_fee +
        cfg.logistics_cost +
        ad_cost
    )

    denominator = discount_factor * (1 - rate_sum)
    if denominator <= 0.001:
        raise ValueError(
            f"无效参数组合: 折扣因子={discount_factor:.4f}, 费率之和={rate_sum*100:.1f}%"
        )

    original_price = (target_profit + product_cost + fixed_fees) / denominator

    return round(original_price, 2)


# ====== 辅助函数 ======

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
