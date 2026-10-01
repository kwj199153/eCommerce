"""订单：订单追踪、物流段渲染、取数（自有库优先 / 平台适配层）、字段映射。

本文件由 `modules/customer_service/agent_cs.py` 拆分而来（第 356 轮），代码**逐行搬运**、未改写逻辑。
"""
# @generated-by: split_agent_cs.py (第 356 轮)

import asyncio
import re
from typing import Dict, Any, Optional
from ._base import (
    AgentResponse,
    ConversationContext,
    SentimentAnalysis,
    _ORDER_STATUS_LABELS,
    logger,
)

class MixinOrders:
    """订单：订单追踪、物流段渲染、取数（自有库优先 / 平台适配层）、字段映射。"""

    @staticmethod
    def _render_shipping_block(info: Dict[str, Any]) -> str:
        """把订单字典里的物流字段渲染成一段文本。

        ★ **物流段只有这一份实现**：订单追踪（买家问订单）与物流咨询
          （买家问货到哪了）渲染的是同一批字段。若各写一份，改一个字段
          （比如新增「预计派送时间」）就会只改一处 —— 同一个订单两种说法。

        Returns:
            渲染文本；**没有任何物流信息时返回空串**（调用方据此另说一句）。
        """
        if not any(info.get(k) for k in (
                "tracking_number", "carrier", "ship_status_text",
                "last_location", "last_event_text")):
            return ""

        out = "\n**物流** 🚚\n"
        if info.get("carrier"):
            out += f"- 承运商：{info['carrier']}\n"
        if info.get("tracking_number"):
            out += f"- 运单号：`{info['tracking_number']}`\n"
        if info.get("ship_status_text"):
            out += f"- 物流状态：**{info['ship_status_text']}**\n"
        if info.get("last_location"):
            out += f"- 最新位置：{info['last_location']}\n"
        if info.get("last_event_text"):
            out += f"- 最新轨迹：{info['last_event_text']}\n"

        delay = info.get("delay_days")
        if isinstance(delay, int) and delay > 0:
            extra = (f"（实际在途 {info['transit_days']} 天）"
                     if info.get("transit_days") is not None else "")
            out += f"\n⚠️ 比承诺时效晚了 **{delay} 天**{extra}\n"
        return out

    async def _handle_order_tracking(
        self,
        query: str,
        context: Optional[Dict],
        conv: ConversationContext,
        sentiment: SentimentAnalysis
    ) -> AgentResponse:
        """处理订单追踪"""

        # 尝试从查询或上下文中提取订单号
        order_id = self._extract_order_id(query) or (context or {}).get("order_id")

        if order_id:
            # ★ fail-closed：查真源，拿不到就如实说拿不到。
            #   历史实现 `_mock_order_info()` 会随机生成状态 / 商品名 /
            #   金额 / 运单号并渲染成下面这张表 —— 等于把编造的订单
            #   直接告诉终端消费者。
            #
            # ★★ 第 285 轮：取数顺序改成「**自有订单库 → 平台适配层**」。
            #   自有库（`modules.trade` 的 `orders` / `shipments`）是**唯一真源**：
            #   平台适配层（SP-API Orders）不返回运单号与承运商，而演示剧本里
            #   那条差评的根因证据正是物流事件 —— 只有自有库给得出。
            #
            # ★ 店铺归属必须**显式传参**，不能靠 `_current_shop_id` 这个
            #   ContextVar：本方法在范式 B（`invoke()`）下被调用，而范式 B
            #   **从不设置**那个 ContextVar（只有 `stream_chat` 的 418/466 行设）。
            #   读它会拿到上一次范式 A 留下的值 ⇒ 跨调用串味，查到别家店铺的订单。
            shop_id = (context or {}).get("store_id") or None
            order_info, failure_reason = await self._fetch_order_info(order_id, shop_id)

            if order_info is None:
                reply = "**未能查到该订单** ⚠️\n\n"
                reply += f"订单号 `{order_id}` 查询失败。\n\n"
                reply += f"原因：{failure_reason}\n\n"
                reply += "请确认订单号是否正确（Amazon 订单号形如 `123-1234567-1234567`）。"
                return AgentResponse(
                    content=reply,
                    data={
                        "type": "order_not_found",
                        "order_id": order_id,
                        "reason": failure_reason,
                    },
                    display_type="text"
                )

            reply = f"**订单信息** 📦\n\n"
            reply += f"| 项目 | 详情 |\n|------|------|\n"
            reply += f"| 订单号 | `{order_info['order_id']}` |\n"
            reply += f"| 状态 | **{order_info['status_text']}** |\n"
            reply += f"| 下单时间 | {order_info['created_at']} |\n"
            reply += f"| 商品 | {order_info['product_name']} |\n"
            reply += f"| 金额 | {order_info['total_text']} |\n"

            if order_info.get("shipping_to"):
                reply += f"| 收货地 | {order_info['shipping_to']} |\n"

            # ---- 自有库才有的字段：运单号 / 承运商 / 迟到天数 ----
            # ★ 走 `_render_shipping_block`（与物流咨询**同一份实现**）。
            #   只有走 trade 域才会产出这几个键（SP-API Orders 接口不返回
            #   运单号与承运商），没有就整段不渲染 —— 不编、也不留空标题。
            reply += self._render_shipping_block(order_info)

            delay = order_info.get("delay_days")
            if isinstance(delay, int) and delay > 0:
                reply += "，如因此产生差评可在后续处理中作为证据。\n"

            if order_info.get("estimated_delivery"):
                reply += f"\n承诺送达：{order_info['estimated_delivery']}\n"

            # ★ 演示数据必须让消费者看得见 —— 与 trade 域 `is_mock_source` 同口径
            if order_info.get("is_mock_data"):
                reply += ("\n> ℹ️ 以上为**演示数据**（来源：mock_seed），"
                          "店铺接入平台接口后将自动切换为真实订单。\n")

            reply += f"\n---\n还有其他关于这个订单的问题吗？"

            return AgentResponse(
                content=reply,
                data={
                    "type": "order_detail",
                    "order": order_info
                },
                display_type="order_info"
            )

        # 无订单号时引导用户提供
        # ★ 只引导订单号：按邮箱 / 手机号检索需要卖家后台授权，尚未开放。
        #   历史文案列出了这两个选项，但那是配合「编造订单号」的假功能
        #   （service.track_order 曾用 hash(email) 造一个 ORD- 号去查）。
        reply = "我可以帮您查询订单状态！请提供**订单号**"
        reply += "（Amazon 订单号形如 `123-1234567-1234567`）。\n\n"
        reply += "如需按邮箱 / 手机号后四位检索，请转人工客服核验身份后查询。"

        return AgentResponse(
            content=reply,
            data={"type": "order_query_prompt"},
            display_type="text"
        )


    def _extract_order_id(self, text: str) -> Optional[str]:
        """从文本提取订单号。

        ★ 第 286 轮补了第 2 条：库里 seed 的订单号就是 `AMZN123456789` 这种
          「平台前缀 + 数字」形态，而此前的规则只认 Amazon 的真实格式
          （`123-1234567-1234567`）和 `ORD-` 开头 —— 于是在演示环境里，
          买家把订单号**原样贴进来也提取不出来**，物流/退货两条分支
          就都掉回「请提供订单号」那句。缺陷不会报错，只会让人以为没接数据。
        """
        patterns = [
            r'\d{3}-\d{7}-\d{7}',   # Amazon 真实订单号，如 112-1234567-8901234
            r'AMZN[-_]?\d{6,}',     # 演示库 / 内部单号（seed 落的就是这一类）
            r'ORD[-–]?\d{8,}',      # 本项目历史演示格式（保留兼容）
            r'order[- ]?(\d{8,})',
            r'[A-Za-z]{2,6}[-_]?\d{6,}',  # 其它平台前缀单号（如 SP / SHOPEE 前缀）
            r'(\d{10,})',  # 纯数字长串
        ]
        for pattern in patterns:
            match = re.search(pattern, text, re.IGNORECASE)
            if match:
                return match.group(0) if match.lastindex is None else f"ORD-{match.group(1)}"
        return None

    def _extract_entities(self, text: str) -> Dict[str, str]:
        """提取实体信息"""
        entities = {}

        # 订单号
        order_id = self._extract_order_id(text)
        if order_id:
            entities["order_id"] = order_id

        # ASIN
        asin_match = re.search(r'B\d[A-Z0-9]{9}', text.upper())
        if asin_match:
            entities["asin"] = asin_match.group(0)

        # 邮箱
        email_match = re.search(r'[\w.-]+@[\w.-]+\.\w+', text)
        if email_match:
            entities["email"] = email_match.group(0)

        # 金额
        amount_match = re.search(r'\$(\d+\.?\d*)', text)
        if amount_match:
            entities["amount"] = amount_match.group(0)

        return entities

    async def _fetch_order_info(
        self, order_id: str, shop_id: Optional[str] = None
    ) -> "tuple[Optional[Dict[str, Any]], str]":
        """
        查询订单信息（真实数据源，fail-closed）。

        ★ 历史实现 `_mock_order_info()` 用 random 生成状态 / 商品名 / 金额 /
          运单号，把假数据直接回复给终端消费者 —— 本项目最恶劣的一处伪数据，
          已整体删除，不再留任何 mock 回退。

        ============================================================
        ★★ 取数顺序（第 285 轮定）：自有订单库 → 平台适配层
        ============================================================
        ① **自有订单库**（`modules.trade` 的 `orders` / `shipments`）—— 唯一真源。
           数据由「订单落库同步任务」从平台适配层拉回来后**按我们自己的数据模型**
           落库，字段是平台无关的：运单号 / 承运商 / 物流事件轨迹 / 迟到天数
           都在这里。演示阶段由 `seed` 灌入 mock 数据（带 `source=mock_seed`
           标记，界面必须如实标注）。

        ② **平台适配层**（SP-API Orders）—— 只在①查不到时兜底。
           定位是「**上游取数**」：它给的是平台原生字段，信息量**少于**自有库
           （Orders 接口不返回运单号与承运商，那是 Shipping API 的活）。

        ★ 为什么①查不到还要回退②，而不是像 `modules/trade/tools.py` 头部注释
          写的那样「表是唯一真源、查不到就如实说查不到」：
            那条纪律管的是**同一个工具内部**不许出现两种答案。而这里是**同步
            任务尚未跑过**（或该订单还没落库）的情形 —— 平台上有、我们库里暂时
            没有。此时回退适配层是「补拉」，不是「给第二个答案」：
            两条路径的产出都带 `data_source`，上层看得到差别。

        ★ 不落库：本方法是**查询**路径（`fetch_order_tracking` 标记为 READ_ONLY），
          在查询里写库会让「读」产生副作用。把平台数据变成自有数据的正确落点是
          `modules/trade.sync.sync_orders_from_source`（订单同步任务）。

        约定：
          - 两个源都拿不到 ⇒ 返回 (None, 原因)，**绝不编造**
          - 查得到 ⇒ 返回 (订单字典, "")，字段沿用历史上消费者依赖的键名

        Args:
            order_id: 平台订单号或内部订单 id
            shop_id: 当前店铺。**显式传参**，不读 `_current_shop_id`
                     （范式 B 从不设置它，读了会串味到别的店铺）

        Returns:
            (order_info | None, 失败原因)
        """
        # ---- ① 自有订单库（真源） ----
        if shop_id:
            try:
                own = await self._fetch_order_from_trade(shop_id, order_id)
            except Exception as e:
                # ★ 自有库查询失败**不能**被当成「没有这笔订单」而静默回退：
                #   那会把「数据库连不上」伪装成「平台没有这笔订单」，归因反向。
                #   这里如实记录，并继续走②（②失败时会带上①的原因一起报）。
                logger.warning(f"自有订单库查询异常 order={order_id} shop={shop_id}: {e}")
                own = None
                own_error = f"自有订单库查询失败：{e}"
            else:
                own_error = ""
            if own is not None:
                return own, ""
            # ★ 库里**查无此单**也要记一笔（它不是异常，但是一条独立的失败线索）：
            #   最终若两个源都没查到，只报平台那条会让「还没同步进库」与
            #   「库里根本没有」混成同一句话 —— 归因会指向错的地方。
            if not own_error:
                own_error = "自有订单库中查无此订单"
        else:
            own_error = "未携带店铺上下文，跳过自有订单库"

        # ---- ② 平台适配层（兜底） ----
        try:
            # 走数据源工厂（唯一入口）——门禁 test_import_boundaries §1 强制
            from modules.amazon_sp import get_data_source
        except Exception as e:  # pragma: no cover
            return None, f"订单数据源模块不可用：{e}"

        def _query() -> Dict[str, Any]:
            # prefer="sp_api"：凭据缺失时工厂**抛 RuntimeError**，不静默回退 Mock
            source = get_data_source(prefer="sp_api")
            return source.fetch_order_tracking(order_id)

        try:
            raw = await asyncio.to_thread(_query)
        except RuntimeError as e:
            # ★ 插值口径：本文件用的是 `core.logger.get_logger()`（loguru），
            #   它按 `str.format` 插值 —— 写 `%s` 会把参数**静默丢掉**
            #   并原样打出 "%s"。loguru 用 f-string / `{}`，
            #   标准库 `logging.getLogger` 才用 `%s`。
            logger.warning(f"订单查询不可用（未接入 SP-API，不编造订单内容）order={order_id}: {e}")
            # ★ 两个源都失败时**两个原因都要说**：只报平台那条，会把
            #   「库里有但连不上」和「压根没同步过」混成同一句。
            detail = f"当前店铺未接入 SP-API 订单数据源（{e}）"
            return None, (f"{own_error}；且{detail}" if own_error else detail)
        except Exception as e:
            logger.warning(f"订单查询失败 order={order_id}: {e}")
            detail = f"平台订单接口调用失败：{e}"
            return None, (f"{own_error}；且{detail}" if own_error else detail)

        if not raw or not raw.get("found"):
            why = (raw or {}).get("error") or "平台侧查不到这笔订单"
            return None, (f"{own_error}；且{why}" if own_error else why)

        # ★ 走适配层拿到的数据，`data_source` 必须标成平台来源 —— 上层靠它
        #   区分「我们自己的库」与「平台实时拉回来的」，不标就等于两种答案
        #   长得一样，正是 `modules/trade/tools.py` 头部警告的那件事。
        info = self._map_order_info(order_id, raw)
        info["data_source"] = "platform_api"
        info["is_mock_data"] = False
        return info, ""

    async def _fetch_order_from_trade(
        self, shop_id: str, order_id: str
    ) -> Optional[Dict[str, Any]]:
        """在**自有订单库**里查一笔订单（取数顺序①）。

        ★ 走 `modules.trade` 包门面，不深引用 `modules.trade.service` / `db_model`
          —— 本仓铁律：跨包引用走 `__init__`，否则模型搬家变成全仓搜索。

        Returns:
            订单字典 | None（None = **库里没有**，调用方可继续走适配层）
        """
        from core.database import async_session_factory

        # 函数内 import：`modules.trade` 依赖 `core.database`，而本模块被
        # `bind_tools` 在**导入期**就装配，模块级 import 会把数据库依赖
        # 提前到进程启动路径上（与 `modules/trade/tools.py` 同款处理）。
        # ★ 走**门面**取函数，不取子模块：`modules.trade` 是跨模块契约面
        #   （`tests/test_facade_monkeypatch_targets.py` 钉的就是这件事）。
        #   取子模块时，测试把桩打在门面上 ⇒ 桩永远不生效 ⇒ 真函数照跑
        #   ⇒ 轻则断言红、重则「测试因错误的原因通过」。
        from modules.trade import get_order_context

        async with async_session_factory() as session:
            ctx = await get_order_context(session, shop_id, order_id)

        if not ctx.get("found"):
            return None
        return self._map_order_from_trade(order_id, ctx)

    @staticmethod
    def _map_order_from_trade(order_id: str, ctx: Dict[str, Any]) -> Dict[str, Any]:
        """把自有订单库的上下文映射成客服回复所用的字段名。

        ★ 与 `_map_order_info`（平台适配层版）**共用同一套对外键名** —— 上层
          渲染逻辑写一次即可，换取数源不需要改渲染。差异只在「多出来的键」：
          自有库有运单号 / 承运商 / 迟到天数 / 演示数据标记，平台版没有。

        ★ 只做改名与搬运，不补任何没拿到的字段：缺就是缺，如实留空。
        """
        order = ctx.get("order") or {}
        items = ctx.get("items") or []
        ship = ctx.get("shipment") or {}

        if len(items) > 1:
            first = items[0].get("title") or items[0].get("sku") or "\u2014"
            product_name = f"{first} 等 {len(items)} 件商品"
        elif items:
            product_name = items[0].get("title") or items[0].get("sku") or "\u2014"
        else:
            product_name = "\u2014"

        amount = order.get("order_total")
        currency = order.get("currency") or "USD"
        if amount is None:
            total_text = "\u2014"
        elif currency == "USD":
            total_text = f"${amount:.2f}"
        else:
            total_text = f"{amount:.2f} {currency}"

        status_code = order.get("order_status") or ""
        ship_code = ship.get("ship_status") or ""
        source = order.get("source") or ""

        # ★ 中文标签只在这里查表：见 `_ORDER_STATUS_LABELS` 的注释
        where = " / ".join(
            x for x in (order.get("ship_state"), order.get("ship_country")) if x
        )

        return {
            "order_id": order.get("external_order_id") or order_id,
            "status": status_code,
            "status_text": _ORDER_STATUS_LABELS.get(status_code, status_code or "\u2014"),
            "created_at": order.get("purchase_at") or "\u2014",
            "product_name": product_name,
            "quantity": sum(int(i.get("quantity") or 0) for i in items),
            "total": amount,
            "total_text": total_text,
            "estimated_delivery": order.get("promised_at") or "",
            "shipping_to": where,
            # ↓ 退货窗口要按**签收日**起算（不是下单日），见 `_handle_return_refund`
            "shipped_at": order.get("shipped_at") or "",
            "delivered_at": order.get("delivered_at") or "",
            # ↓ 以下为自有库专属（平台适配层给不出）
            "tracking_number": ship.get("tracking_no") or "",
            "carrier": ship.get("carrier") or "",
            "ship_status_text": _ORDER_STATUS_LABELS.get(ship_code, ship_code or "\u2014")
            if ship_code else "",
            "transit_days": order.get("transit_days"),
            "delay_days": order.get("delay_days"),
            "last_location": ship.get("last_location") or "",
            "last_event_text": ship.get("last_event_text") or "",
            # ↓ 谁给的这批数据，上层必须看得见（演示数据不得冒充真实数据）
            "data_source": source,
            "is_mock_data": source == "mock_seed",
        }

    @staticmethod
    def _map_order_info(order_id: str, raw: Dict[str, Any]) -> Dict[str, Any]:
        """
        把 SP-API 的订单追踪结果映射成客服回复所用的字段名。

        ★ 只做「改名 / 取首项」这类搬运，**不补任何平台没给的字段**：
          运单号与承运商 Orders 接口不返回，因此这里也不产出
          `tracking_number` / `carrier` 两个键（历史 mock 会编）。
        """
        items = raw.get("items") or []
        total = raw.get("order_total") or {}
        amount = total.get("amount")
        currency = total.get("currency") or "USD"

        if len(items) > 1:
            first = items[0].get("title") or items[0].get("asin") or "—"
            product_name = f"{first} 等 {len(items)} 件商品"
        elif items:
            product_name = items[0].get("title") or items[0].get("asin") or "—"
        else:
            product_name = "—"

        if amount is None:
            total_text = "—"
        elif currency == "USD":
            total_text = f"${amount:.2f}"
        else:
            total_text = f"{amount:.2f} {currency}"

        current = raw.get("current_status") or {}
        info: Dict[str, Any] = {
            "order_id": order_id,
            "status": current.get("code", ""),
            "status_text": current.get("label", ""),
            "created_at": raw.get("purchase_date") or "—",
            "product_name": product_name,
            "quantity": raw.get("item_count") or 0,
            "total": amount,
            "total_text": total_text,
        }
        if raw.get("estimated_delivery"):
            info["estimated_delivery"] = raw["estimated_delivery"]
        if raw.get("shipping_to") and raw["shipping_to"] != "N/A":
            info["shipping_to"] = raw["shipping_to"]
        return info
