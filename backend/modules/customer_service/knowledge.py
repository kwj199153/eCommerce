"""客服预置知识库（**业务资产**）。

★ 归属说明
原先这份语料 + `build_customer_service_kb` 放在 `ai_infra/rag/hybrid_engine.py`
的 `KnowledgeBaseBuilder` 里，于是**基础设施层承载了「客服」这一业务语义**：
它既不报错、也 grep 不到 `from modules`，是最容易被漏掉的一类分层泄漏。

现在分工是：

    基础设施层（`ai_infra/rag`）  →  只提供**读写接口**：
                                     `HybridRAGEngine.initialize()`
                                     `HybridRAGEngine.add_faq_knowledge_base(items, category)`
    业务层（本模块）              →  **内容**：语料 + 灌库编排

用法::

    from modules.customer_service.knowledge import build_customer_service_kb
    from ai_infra.rag import HybridRAGEngine

    engine = HybridRAGEngine(domain="customer_service")
    await engine.initialize()
    count = await build_customer_service_kb(engine)      # -> 12

注：`agent_cs` 走的是另一条路 —— 它把自己 `faq_database` 里的条目经
`BaseAgent.initialize_rag(faq_items=...)` 传入，不使用本模块的预置语料。
本模块保留给「冷启动 / 测试 / 脚本灌库」场景。
"""
from typing import Any, Dict, List

from core.logger import get_logger

logger = get_logger(__name__)


# 客服 FAQ 知识库（12 条，覆盖物流/支付/退换货/订单/税费/账号/会员）
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

async def build_customer_service_kb(engine: Any) -> int:
    """把预置客服 FAQ 灌入给定 RAG 引擎。

    Args:
        engine: `HybridRAGEngine` 实例（需已完成 `initialize()`）

    Returns:
        入库条数
    """
    count = await engine.add_faq_knowledge_base(
        CUSTOMER_SERVICE_FAQ,
        category="customer_service",
    )
    logger.info(f"Built customer service KB: {count} entries")
    return count


__all__ = ["CUSTOMER_SERVICE_FAQ", "build_customer_service_kb"]
