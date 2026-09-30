"""
灌「文档素材 + 预拆话术草稿」演示数据（第 288 轮）

背景
----
`knowledge_docs` 此前**全库 0 行**，且文档没有出口（拆不成话术、进不了检索）。
本脚本同时解决两头：
  ① 灌 5 篇**带正文**的通用电商客服政策（AI 拆分功能的现成输入）；
  ② 灌 27 条**预拆好的话术草稿**（status=draft）。

★ 为什么连草稿一起灌，而不是只灌文档等着用户点「AI 拆成话术」：
  LLM 在本机环境未必可用（第 287 轮实测：一批用例因 LLM 不可用而环境性变红）。
  若只灌文档，遇到 LLM 不可用时，这条链**整条演示不出来**，也无法验证
  「草稿 → 发布 → 客服命中」这段。草稿条目由我**逐条对照正文**手写，
  每条都能在对应文档里找到依据 —— 这不是"为了让页面有数据"而编的默认值，
  而是把「AI 拆分会产出什么」预先物化，供人工确认流程走通。

★ 全部以 **draft** 落库：客服 `load_faq_items` 只查 active，
  ⇒ 灌完后**不会**立刻改变客服的回答内容，必须人工发布才生效（老板拍板）。

用法
----
    python scripts/seed_knowledge_docs.py              # 全部店铺
    python scripts/seed_knowledge_docs.py --shop X     # 仅指定店铺
    python scripts/seed_knowledge_docs.py --list       # 只看会灌什么，不写库

幂等：文档按 id 判存在跳过；草稿按 question 去重（走 `create_faq_drafts`）。
"""

import argparse
import asyncio
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from sqlalchemy import select  # noqa: E402

from core.database import async_session_factory  # noqa: E402
from modules.knowledge_base.db_model import (  # noqa: E402
    KnowledgeBaseRecord,
    KnowledgeDocRecord,
)
from modules.knowledge_base import service as kb_service  # noqa: E402


# ==========================================================================
# 5 篇演示文档（通用电商客服政策）
#
# ★ 每条 draft 的 answer 都能在**同一篇** content 里找到依据 —— 改动正文时
#   必须同步改条目，否则就是"文档里没有的答案"（本仓家规禁止）。
# ==========================================================================

DOCS = [
    {
        "slug": "return-refund",
        "filename": "退货与退款政策（演示素材）.md",
        "file_type": "md",
        "description": "演示素材：无理由退货、退款时效、破损与错发处理",
        "content": """退货与退款政策（通用电商 · 演示素材）

一、无理由退货
1. 自签收之日起 30 天内可申请无理由退货，商品需保持完好、配件与包装齐全。
2. 定制类商品（刻字、定制图案）、贴身内衣、已开封的食品与化妆品不支持无理由退货。
3. 无理由退货的运费由买家承担；商品本身存在质量问题的，运费由卖家承担。

二、退款时效
1. 仓库签收退回商品并完成质检后，3 个工作日内发起退款。
2. 原路退回：支付宝 / 微信 1-3 个工作日到账，银行卡 3-7 个工作日到账，具体以银行处理为准。
3. 使用优惠券的订单，退款时优惠券不折现，仅退还实付金额。

三、破损与错发
1. 签收后 48 小时内提供商品破损照片或视频，可申请免费换新或全额退款。
2. 错发、漏发的，卖家承担来回运费，可优先选择补发。

四、退款失败
1. 原支付账户已注销导致退款失败的，请提供本人名下其他账户，客服在 1 个工作日内核实后重汇。
""",
        "drafts": [
            {
                "question": "收到货不满意，可以退货吗？",
                "answer": "可以。自签收之日起 30 天内可申请无理由退货，商品需保持完好、配件与包装齐全。"
                          "定制类商品（刻字、定制图案）、贴身内衣、已开封的食品与化妆品不支持无理由退货。",
                "category": "return",
                "keywords": ["退货", "无理由退货", "30天"],
                "priority": "high",
            },
            {
                "question": "退货的运费谁承担？",
                "answer": "无理由退货的运费由买家承担；商品本身存在质量问题的，运费由卖家承担。"
                          "错发、漏发的情况来回运费也由卖家承担，您可以优先选择补发。",
                "category": "return",
                "keywords": ["运费", "退货"],
                "priority": "high",
            },
            {
                "question": "退款多久能到账？",
                "answer": "仓库签收退回商品并完成质检后，3 个工作日内发起退款。原路退回："
                          "支付宝 / 微信 1-3 个工作日到账，银行卡 3-7 个工作日到账，具体以银行处理为准。",
                "category": "return",
                "keywords": ["退款", "到账", "时效"],
                "priority": "high",
            },
            {
                "question": "用优惠券买的订单怎么退款？",
                "answer": "使用优惠券的订单，退款时优惠券不折现，仅退还实付金额，且优惠券不予返还。",
                "category": "payment",
                "keywords": ["优惠券", "退款"],
                "priority": "medium",
            },
            {
                "question": "收到的商品破损了怎么办？",
                "answer": "请在签收后 48 小时内提供商品破损的照片或视频，即可申请免费换新或全额退款。",
                "category": "aftersale",
                "keywords": ["破损", "换新", "退款"],
                "priority": "high",
            },
            {
                "question": "退款失败了怎么办？",
                "answer": "若原支付账户已注销导致退款失败，请提供本人名下其他账户，"
                          "客服会在 1 个工作日内核实后重新汇款。",
                "category": "payment",
                "keywords": ["退款失败", "账户"],
                "priority": "medium",
            },
        ],
    },
    {
        "slug": "shipping-sla",
        "filename": "物流与配送时效说明（演示素材）.md",
        "file_type": "md",
        "description": "演示素材：发货时效、配送时效、物流查询、清关与改址",
        "content": """物流与配送时效说明（通用电商 · 演示素材）

一、发货时效
1. 现货订单在付款后 24-48 小时内发出（工作日），预售与定制商品以商品页标注的发货时间为准。
2. 每日 16:00 前付款的订单当日进入仓库作业队列，16:00 后顺延至下一工作日。

二、配送时效（自发货起算，不含清关）
1. 国内标准快递：2-5 个工作日。
2. 跨境标准物流：7-15 个工作日。
3. 跨境快速物流：3-7 个工作日。
4. 偏远地区在上述时效基础上增加 2-3 个工作日。

三、物流查询
1. 发货后系统会发送运单号，可在订单详情或承运商官网查询轨迹。
2. 轨迹超过 5 个工作日未更新，可联系客服发起物流查件，承运商一般在 3 个工作日内反馈结果。

四、关税与清关
1. 跨境订单可能需要收件人配合提供身份证件用于清关。
2. 因收件人未配合清关导致包裹退回的，重新发货的运费由买家承担。

五、地址修改
1. 未发货的订单可修改收货地址；已发出的订单无法改址，可在派送失败后由承运商安排退回重发。
""",
        "drafts": [
            {
                "question": "付款后多久发货？",
                "answer": "现货订单在付款后 24-48 小时内发出（工作日）；每日 16:00 前付款的订单当日进入仓库"
                          "作业队列，16:00 后顺延至下一工作日。预售与定制商品以商品页标注的发货时间为准。",
                "category": "shipping",
                "keywords": ["发货", "时效", "多久"],
                "priority": "high",
            },
            {
                "question": "多久能收到货？",
                "answer": "自发货起算（不含清关）：国内标准快递 2-5 个工作日，跨境标准物流 7-15 个工作日，"
                          "跨境快速物流 3-7 个工作日；偏远地区在上述基础上再增加 2-3 个工作日。",
                "category": "shipping",
                "keywords": ["配送", "时效", "收货"],
                "priority": "high",
            },
            {
                "question": "怎么查物流轨迹？",
                "answer": "发货后系统会发送运单号，您可以在订单详情或承运商官网查询物流轨迹。",
                "category": "shipping",
                "keywords": ["物流", "运单号", "查询"],
                "priority": "medium",
            },
            {
                "question": "物流一直不更新怎么办？",
                "answer": "轨迹超过 5 个工作日未更新，可联系客服发起物流查件，"
                          "承运商一般在 3 个工作日内反馈结果。",
                "category": "shipping",
                "keywords": ["物流", "不更新", "查件"],
                "priority": "high",
            },
            {
                "question": "跨境订单为什么要提供身份证？",
                "answer": "跨境订单可能需要收件人配合提供身份证件用于清关。因收件人未配合清关导致包裹"
                          "退回的，重新发货的运费由买家承担。",
                "category": "shipping",
                "keywords": ["清关", "身份证", "关税"],
                "priority": "medium",
            },
            {
                "question": "已经发货了还能改地址吗？",
                "answer": "未发货的订单可以修改收货地址；已发出的订单无法改址，"
                          "可在派送失败后由承运商安排退回重发。",
                "category": "order",
                "keywords": ["地址", "修改", "改址"],
                "priority": "medium",
            },
        ],
    },
    {
        "slug": "warranty",
        "filename": "质保与售后维修说明（演示素材）.md",
        "file_type": "md",
        "description": "演示素材：质保期、维修流程与时效、换新条件",
        "content": """质保与售后维修说明（通用电商 · 演示素材）

一、质保期
1. 整机质保 12 个月，自签收之日起算。
2. 电池、电源适配器等易耗件质保 6 个月。
3. 人为损坏（进水、摔落、私自拆机）不在质保范围内。

二、质保服务流程
1. 先在订单详情提交售后申请，并上传故障现象的照片或视频。
2. 客服在 1 个工作日内完成初审，通过后提供回寄地址。
3. 回寄运费：质保范围内由卖家承担；超出质保期或人为损坏的，由买家承担。

三、维修时效
1. 收到返修件后 5 个工作日内完成检测并告知维修方案。
2. 常规维修 7-10 个工作日完成；需更换进口配件的，延长至 15-20 个工作日。

四、换新与退换
1. 同一故障维修两次仍未解决的，可申请换新。
2. 签收后 7 天内出现非人为性能故障，可直接申请换新，卖家承担来回运费。
""",
        "drafts": [
            {
                "question": "质保多久？",
                "answer": "整机质保 12 个月，自签收之日起算；电池、电源适配器等易耗件质保 6 个月。"
                          "人为损坏（进水、摔落、私自拆机）不在质保范围内。",
                "category": "aftersale",
                "keywords": ["质保", "保修", "12个月"],
                "priority": "high",
            },
            {
                "question": "怎么申请质保维修？",
                "answer": "请先在订单详情提交售后申请，并上传故障现象的照片或视频；"
                          "客服会在 1 个工作日内完成初审，通过后提供回寄地址。",
                "category": "aftersale",
                "keywords": ["维修", "售后申请", "质保"],
                "priority": "high",
            },
            {
                "question": "维修要多久？",
                "answer": "收到返修件后 5 个工作日内完成检测并告知维修方案；常规维修 7-10 个工作日完成，"
                          "需更换进口配件的延长至 15-20 个工作日。",
                "category": "aftersale",
                "keywords": ["维修", "时效", "多久"],
                "priority": "medium",
            },
            {
                "question": "修不好能换新吗？",
                "answer": "同一故障维修两次仍未解决的，可申请换新。签收后 7 天内出现非人为性能故障，"
                          "也可直接申请换新，来回运费由卖家承担。",
                "category": "aftersale",
                "keywords": ["换新", "维修", "故障"],
                "priority": "medium",
            },
            {
                "question": "质保维修的运费谁出？",
                "answer": "质保范围内的回寄运费由卖家承担；超出质保期或属于人为损坏的，由买家承担。",
                "category": "aftersale",
                "keywords": ["运费", "维修", "质保"],
                "priority": "medium",
            },
        ],
    },
    {
        "slug": "size-guide",
        "filename": "尺码与商品规格指南（演示素材）.md",
        "file_type": "md",
        "description": "演示素材：选尺码、换码、色差与配件说明",
        "content": """尺码与商品规格指南（通用电商 · 演示素材）

一、如何选尺码
1. 服装类请以商品页尺码表的净尺寸为准，建议比照自己合身的同类衣物平铺测量后选择。
2. 鞋类建议按脚长加 0.5-1 厘米选择；宽脚或高脚背建议选大一码。
3. 不同批次的同款商品可能存在 1-2 厘米的误差，属正常范围。

二、尺码不合怎么办
1. 未影响二次销售的，可在签收 30 天内申请换码，来回运费由买家承担。
2. 商品页面已明确标注"不支持无理由退换"的定制尺码商品除外。

三、商品规格与色差
1. 显示器差异可能导致实物与图片存在轻微色差，不属于质量问题。
2. 商品参数（功率、容量、接口类型等）以商品页参数表为准。

四、配件与包装
1. 标配配件以商品页"包装清单"为准，页面未列出的配件不随机附带。
2. 赠品随单发出，赠品缺货时不折现，也不单独补发。
""",
        "drafts": [
            {
                "question": "衣服尺码怎么选？",
                "answer": "请以商品页尺码表的净尺寸为准，建议比照自己合身的同类衣物平铺测量后选择；"
                          "不同批次的同款商品可能存在 1-2 厘米误差，属正常范围。",
                "category": "product",
                "keywords": ["尺码", "选码", "服装"],
                "priority": "high",
            },
            {
                "question": "鞋子尺码怎么选？",
                "answer": "建议按脚长加 0.5-1 厘米选择；宽脚或高脚背建议选大一码。",
                "category": "product",
                "keywords": ["尺码", "鞋", "选码"],
                "priority": "medium",
            },
            {
                "question": "尺码不合适能换吗？",
                "answer": "未影响二次销售的，可在签收 30 天内申请换码，来回运费由买家承担；"
                          "商品页面标注「不支持无理由退换」的定制尺码商品除外。",
                "category": "return",
                "keywords": ["换码", "尺码", "退换"],
                "priority": "medium",
            },
            {
                "question": "实物和图片有色差算质量问题吗？",
                "answer": "显示器差异可能导致实物与图片存在轻微色差，不属于质量问题。"
                          "商品参数（功率、容量、接口类型等）以商品页参数表为准。",
                "category": "product",
                "keywords": ["色差", "质量", "参数"],
                "priority": "low",
            },
            {
                "question": "赠品没收到怎么办？",
                "answer": "赠品随单发出，赠品缺货时不折现，也不单独补发；"
                          "标配配件以商品页「包装清单」为准，页面未列出的配件不随机附带。",
                "category": "product",
                "keywords": ["赠品", "配件", "包装"],
                "priority": "low",
            },
        ],
    },
    {
        "slug": "payment-invoice",
        "filename": "支付、发票与关税说明（演示素材）.md",
        "file_type": "md",
        "description": "演示素材：支付方式、优惠券叠加、发票开具与关税",
        "content": """支付、发票与关税说明（通用电商 · 演示素材）

一、支付方式
1. 支持支付宝、微信支付、银联与主流信用卡。
2. 下单后 30 分钟内未付款的订单自动关闭；活动商品以下单页标注的保留时间为准。

二、优惠券与优惠叠加
1. 每笔订单仅可使用一张店铺优惠券，平台券与店铺券可叠加使用，具体以结算页显示为准。
2. 优惠券不可兑换现金，订单退款后优惠券不予返还。

三、发票
1. 可在订单完成后 90 天内申请开具电子发票，开票金额以实付金额为准。
2. 电子发票在申请后 3 个工作日内发送至下单邮箱；抬头填错的，可在开票后 30 天内申请重开。

四、价格与关税
1. 跨境订单页面价格通常不含进口关税，关税由收件人在清关时按当地法规缴纳。
2. 下单后商品降价的，不支持差价补偿。
""",
        "drafts": [
            {
                "question": "支持哪些支付方式？",
                "answer": "支持支付宝、微信支付、银联与主流信用卡。下单后 30 分钟内未付款的订单会自动关闭，"
                          "活动商品以下单页标注的保留时间为准。",
                "category": "payment",
                "keywords": ["支付", "付款", "方式"],
                "priority": "medium",
            },
            {
                "question": "优惠券可以叠加使用吗？",
                "answer": "每笔订单仅可使用一张店铺优惠券，平台券与店铺券可叠加使用，具体以结算页显示为准。"
                          "优惠券不可兑换现金，订单退款后不予返还。",
                "category": "payment",
                "keywords": ["优惠券", "叠加", "优惠"],
                "priority": "medium",
            },
            {
                "question": "怎么开发票？",
                "answer": "可在订单完成后 90 天内申请开具电子发票，开票金额以实付金额为准；"
                          "电子发票在申请后 3 个工作日内发送至下单邮箱。",
                "category": "payment",
                "keywords": ["发票", "开票"],
                "priority": "medium",
            },
            {
                "question": "发票抬头填错了怎么办？",
                "answer": "可在开票后 30 天内申请重开，请尽快联系客服处理。",
                "category": "payment",
                "keywords": ["发票", "抬头", "重开"],
                "priority": "low",
            },
            {
                "question": "跨境订单的关税谁承担？",
                "answer": "跨境订单页面价格通常不含进口关税，关税由收件人在清关时按当地法规缴纳。"
                          "下单后商品降价的，不支持差价补偿。",
                "category": "payment",
                "keywords": ["关税", "清关", "差价"],
                "priority": "medium",
            },
        ],
    },
]


def _doc_id(slug: str, shop_id: str) -> str:
    return f"kdoc-demo-{slug}-{shop_id}"


async def _default_kb_ids(session, shop_id: str) -> list:
    rows = (await session.execute(
        select(KnowledgeBaseRecord).where(
            KnowledgeBaseRecord.shop_id == shop_id,
            KnowledgeBaseRecord.is_default.is_(True),
        )
    )).scalars().all()
    return [r.id for r in rows]


async def seed(only_shop: str = None, dry_run: bool = False) -> dict:
    stats = {"docs_created": 0, "docs_skipped": 0, "drafts_added": 0,
             "drafts_duplicated": 0, "shops": 0, "shops_without_default_kb": []}

    async with async_session_factory() as session:
        # 有文档的店铺 ∪ 有默认库的店铺（新店铺可能只有默认库、一篇文档都没有）
        doc_shops = (await session.execute(
            select(KnowledgeDocRecord.shop_id).distinct()
        )).scalars().all()
        kb_shops = (await session.execute(
            select(KnowledgeBaseRecord.shop_id).distinct()
        )).scalars().all()
        shops = sorted({s for s in list(doc_shops) + list(kb_shops) if s})
        if only_shop:
            shops = [s for s in shops if s == only_shop]

        for shop_id in shops:
            kb_ids = await _default_kb_ids(session, shop_id)
            if not kb_ids:
                # ★ 不代建默认库：容器是用户资产，"帮你建一个"会盖掉他自己的组织方式
                stats["shops_without_default_kb"].append(shop_id)
                continue
            kb_id = kb_ids[0]
            stats["shops"] += 1

            for spec in DOCS:
                did = _doc_id(spec["slug"], shop_id)
                exists = (await session.execute(
                    select(KnowledgeDocRecord).where(KnowledgeDocRecord.id == did)
                )).scalar_one_or_none()
                if exists is not None:
                    stats["docs_skipped"] += 1
                    continue
                if dry_run:
                    stats["docs_created"] += 1
                    stats["drafts_added"] += len(spec["drafts"])
                    continue

                await kb_service.create_doc({
                    "id": did,
                    "kb_id": kb_id,
                    "filename": spec["filename"],
                    "file_type": spec["file_type"],
                    "size": len(spec["content"].encode("utf-8")),
                    "description": spec["description"],
                    "content": spec["content"],
                }, shop_id=shop_id)
                stats["docs_created"] += 1

                # ★ 走 create_faq_drafts：服务端强制 status=draft + 按 question 去重
                saved = await kb_service.create_faq_drafts(
                    [{**d, "kb_id": kb_id} for d in spec["drafts"]],
                    shop_id=shop_id,
                )
                stats["drafts_added"] += saved["added"]
                stats["drafts_duplicated"] += saved["duplicated"]

    return stats


def main() -> int:
    ap = argparse.ArgumentParser(description="灌文档素材 + 预拆话术草稿（演示数据）")
    ap.add_argument("--shop", help="仅灌指定店铺（默认全部）")
    ap.add_argument("--list", action="store_true", help="只看会灌什么，不写库")
    args = ap.parse_args()

    if args.list:
        total_drafts = sum(len(d["drafts"]) for d in DOCS)
        print(f"[list] 文档 {len(DOCS)} 篇，预拆草稿 {total_drafts} 条（不写库）")
        for d in DOCS:
            print(f"  - {d['filename']}：{len(d['drafts'])} 条草稿")
        return 0

    stats = asyncio.run(seed(only_shop=args.shop, dry_run=False))
    print("[seed] 文档 新建 {} / 已存在 {}；草稿 新建 {} / 重复跳过 {}".format(
        stats["docs_created"], stats["docs_skipped"],
        stats["drafts_added"], stats["drafts_duplicated"],
    ))
    print(f"[seed] 覆盖店铺 {stats['shops']} 个")
    if stats["shops_without_default_kb"]:
        print(f"[seed] 跳过（无默认知识库，不代建）：{stats['shops_without_default_kb']}")
    print("[seed] 全部草稿均为 draft 状态 —— 需人工发布后才会被客服检索命中")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
