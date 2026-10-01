"""售后：退换货与 30 天窗口判定、物流咨询、支付问题。

本文件由 `modules/customer_service/agent_cs.py` 拆分而来（第 356 轮），代码**逐行搬运**、未改写逻辑。
"""
# @generated-by: split_agent_cs.py (第 356 轮)

from typing import Dict, Optional
from datetime import datetime, timezone
from ._base import AgentResponse, ConversationContext, SentimentAnalysis

class MixinAftersale:
    """售后：退换货与 30 天窗口判定、物流咨询、支付问题。"""

    #: 退货窗口天数。
    #:
    #: ★ 当前是**常量**，与话术里写的「收到商品 30 天内」保持一致。
    #:   将来它应当是**店铺可配置**的售后政策（不同类目 / 不同站点窗口不同），
    #:   那时这里要换成「读政策表」，而不是让话术文案与判断逻辑各说一套 ——
    #:   两套口径一旦漂移，买家就会得到「话术说能退、系统说不能退」的矛盾答复。
    RETURN_WINDOW_DAYS: int = 30


    async def _handle_return_refund(
        self,
        query: str,
        context: Optional[Dict],
        conv: ConversationContext,
        sentiment: SentimentAnalysis
    ) -> AgentResponse:
        """处理退换货请求 —— **先查订单，再判断在不在退货窗口内**。

        ★ 第 286 轮之前：这里把一条写死的退货指南原样吐出来，
          **完全不校验这笔订单** —— 于是「买了两年的东西」和「昨天刚签收」
          得到同一份答复，窗口 / 是否已签收一概不管。
          现在用 `delivered_at`（**签收日**，不是下单日）起算窗口，
          **算不出来就如实说算不出来**（不猜、不默认放行）。
        """
        order_id = self._extract_order_id(query) or (context or {}).get("order_id")
        shop_id = (context or {}).get("store_id") or None

        verdict, verdict_data = await self._judge_return_window(order_id, shop_id)

        if self._faq_error:
            # ★ 话术读不出来时**照给判断**（判断来自订单数据，与话术无关），
            #   但要写明文档没读到 —— 不能让「流程细节缺失」看起来像「没有流程」。
            guide = (f"\n> ⚠️ 退货流程文档暂时读不出来（{self._faq_error}），"
                     "以下判断来自订单数据，不受影响。\n")
        elif self.faq_database:
            return_faqs = [f for f in self.faq_database if f.category == "退换货"]
            best = self._find_best_faq_match(query, return_faqs)
            guide = f"\n**退换货流程** 🔄\n\n{best.answer}\n" if best else ""
        else:
            guide = "\n（这个店铺还没配置退换货话术，流程细节请转人工确认。）\n"

        reply = f"**退换货判断** 🔄\n\n{verdict}\n" + guide

        if sentiment.sentiment in ("negative", "angry"):
            reply += "\n非常抱歉给您带来不好的体验 😔 我会尽快帮您处理。\n"

        reply += "\n---\n需要我帮您**创建退换货工单**吗？请告诉我：\n"
        reply += "- 订单号\n" if not order_id else ""
        reply += "- 退换原因（质量问题/不喜欢/发错货/其他）"

        data = {"type": "return_guide", "sentiment": sentiment.sentiment}
        data.update(verdict_data)
        return AgentResponse(content=reply, data=data,
                             display_type="return_guide")

    async def _judge_return_window(
        self, order_id: Optional[str], shop_id: Optional[str],
    ) -> "tuple[str, Dict[str, Any]]":
        """判断一笔订单在不在退货窗口内。

        Returns:
            (给买家看的结论, 结构化数据)

        ★ 三种**必须分开**的结局：还在窗口内 / 已超窗口 / **算不出来**。
          第三种最容易糊 —— 签收时间解析失败时若默认「可以退」，
          就是把「不知道」包装成「批准」（fail-open，本仓禁止）。
        """
        if not order_id:
            return (
                "请先提供**订单号**：我需要看这笔订单的签收时间，"
                f"才能判断它是否还在 {self.RETURN_WINDOW_DAYS} 天退货窗口内"
                "（不同订单的签收时间不同，不能笼统答复）。",
                {"need_order_id": True},
            )

        info, why = await self._fetch_order_info(order_id, shop_id)
        if info is None:
            return (
                f"订单 `{order_id}` 没查到，无法判断退货窗口。\n\n"
                f"原因：{why}",
                {"order_id": order_id, "reason": why,
                 "order_found": False},
            )

        delivered = info.get("delivered_at") or ""
        if not delivered:
            # ★ 没签收 ⇒ 还没进入退货窗口；该走的是「未收到货 / 物流异常」
            return (
                f"这笔订单**尚未签收**（当前状态：{info.get('status_text') or '—'}），"
                "退货窗口从签收日起算，因此现在还谈不上超期。\n\n"
                "如果您是「**没收到货**」，请告诉我，我按未收到货的流程处理。",
                {"order_id": order_id, "order_found": True,
                 "delivered": False},
            )

        from modules.trade import parse_iso  # 跨包走门面，不深引用 service

        dt = parse_iso(delivered)
        if dt is None:
            return (
                f"签收时间 `{delivered}` 解析不出来，我**不据此判断**是否可以退 —— "
                "请转人工核对（宁可多问一句，也不拿猜测当结论）。",
                {"order_id": order_id, "order_found": True,
                 "delivered": True, "window_unknown": True},
            )

        # ★ 平台同步来的时间戳可能带时区（`...Z` / `+08:00`），自有库的是 naive。
        #   一个 aware、一个 naive 直接相减会 TypeError ⇒ 整个分支崩掉。
        #   统一按 **UTC 挂钟**比较（库里存的就是 UTC 串）。
        if dt.tzinfo is not None:
            dt = dt.astimezone(timezone.utc).replace(tzinfo=None)

        days = (datetime.utcnow() - dt).days
        left = self.RETURN_WINDOW_DAYS - days
        if days > self.RETURN_WINDOW_DAYS:
            text = (
                f"这笔订单已签收 **{days} 天**，超出 {self.RETURN_WINDOW_DAYS} 天"
                f"退货窗口 **{days - self.RETURN_WINDOW_DAYS} 天** ⇒ "
                "标准退货流程可能不适用，需要人工审核。\n\n"
                "⚠️ 质量问题 / 运输破损通常**不受**这个窗口限制，"
                "如果是这两种情况请说明。"
            )
        else:
            text = (
                f"这笔订单已签收 **{days} 天**，"
                f"**仍在 {self.RETURN_WINDOW_DAYS} 天退货窗口内**"
                f"（还剩 {left} 天）⇒ 可以走标准退货流程。"
            )
        return (text, {"order_id": order_id, "order_found": True,
                       "delivered": True, "days_since_delivery": days,
                       "days_left": left,
                       "within_window": days <= self.RETURN_WINDOW_DAYS})


    async def _handle_shipping_inquiry(
        self,
        query: str,
        context: Optional[Dict],
        conv: ConversationContext,
        sentiment: SentimentAnalysis
    ) -> AgentResponse:
        """处理物流询问 —— **有订单号就查真实物流**。

        ★ 第 286 轮之前：这里只从话术库里挑一条「物流」分类的静态文案，
          于是买家问「我的货到哪了」，系统回「登录账户 → 我的订单 →
          查看物流」—— 让他自己去别处看，而 `shipments` 表里那几行连
          运单号、轨迹、迟到天数都存好了（审查见 cs-data-source-audit-r285）。

        ★ 现在的顺序：**订单号 ⇒ 查自有订单库（`_fetch_order_info`）**；
          查不到 / 没给订单号 ⇒ 才回话术，并**明确告诉他给订单号能查到什么**。
        """
        order_id = self._extract_order_id(query) or (context or {}).get("order_id")
        shop_id = (context or {}).get("store_id") or None

        if order_id:
            info, why = await self._fetch_order_info(order_id, shop_id)
            if info is None:
                reply = (
                    f"**没能查到订单 {order_id} 的物流** ⚠️\n\n"
                    f"原因：{why}\n\n"
                    "请确认订单号是否正确（Amazon 订单号形如 "
                    "`123-1234567-1234567`）。"
                )
                return AgentResponse(
                    content=reply,
                    data={"type": "shipping_order_not_found",
                          "order_id": order_id, "reason": why},
                    display_type="text",
                )

            block = self._render_shipping_block(info)
            if not block:
                # ★ 查到了订单但还没有运单信息 ⇒ 如实说「系统里没有」，
                #   不用「请登录账户自行查看」这类话把缺口糊过去。
                block = (
                    "\n**物流** 🚚\n"
                    "- 目前物流系统里**还没有这笔订单的运单信息**\n"
                    f"- 订单状态：{info.get('status_text') or '—'}\n"
                )
            reply = f"**订单 {info['order_id']} 的物流进度** 🚚\n" + block
            if info.get("estimated_delivery"):
                reply += f"\n承诺送达：{info['estimated_delivery']}\n"
            if info.get("is_mock_data"):
                reply += ("\n> ℹ️ 以上为**演示数据**，店铺接入平台接口后"
                          "自动切换为真实物流。\n")
            return AgentResponse(
                content=reply,
                data={"type": "shipping_tracking", "order": info},
                display_type="order_info",
            )

        # ---- 没给订单号：回话术 + 明说「给订单号能查到什么」 ----
        if self._faq_error:
            return self._faq_unavailable_response(query, self._faq_error)
        if not self.faq_database:
            return self._faq_empty_response(query)

        shipping_faqs = [f for f in self.faq_database if f.category == "物流"]
        reply = ""
        best = self._find_best_faq_match(query, shipping_faqs)
        if best is not None:
            reply += f"**关于物流问题** 📦\n\n{best.answer}\n\n"
            others = [f for f in shipping_faqs if f.id != best.id][:2]
            if others:
                reply += "**其他物流常见问题**：\n"
                for f in others:
                    reply += f"- Q: {f.question}\n"
                reply += "\n"
            return AgentResponse(
                content=reply +
                    "---\n给我**订单号**，我可以帮您查这笔订单的实时轨迹"
                    "（承运商 / 运单号 / 最新位置 / 是否迟到）。",
                data={"type": "shipping_info", "faq_id": best.id,
                      "need_order_id": True},
                display_type="faq_answer",
            )

        return await self._handle_faq_query(query, context, conv, sentiment)

    async def _handle_payment_issue(
        self,
        query: str,
        context: Optional[Dict],
        conv: ConversationContext,
        sentiment: SentimentAnalysis
    ) -> AgentResponse:
        """处理支付问题"""

        payment_faq = next(
            (f for f in self.faq_database if f.id == "faq-007"), None
        )

        if payment_faq:
            reply = f"**支付相关问题** 💳\n\n{payment_faq.answer}"

            return AgentResponse(
                content=reply,
                data={"type": "payment_info", "faq_id": payment_faq.id},
                display_type="faq_answer"
            )

        return AgentResponse(content="关于支付问题，请联系客服或查看帮助中心。")
