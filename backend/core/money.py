"""金额单位与换算 —— **全项目唯一出口**（第 378 轮）。

==============================================================================
★ 为什么金额的单位是「分」（int），不是「元」（float）
==============================================================================
改前本仓 `invoices.amount` / `subscription_plans.price_monthly` 都是 float 元，
于是有两类**不会报错**的缺陷：

  ① 折算漂移 —— 年付 = 月付 × 10，月付一旦是小数，`,2` 取整前就已经带着
     `2999.0000000000005` 这种尾巴；每一步都在赌"这个数恰好没漂"。
  ② 比对只能带容差 —— 支付宝回调给的是元字符串 `"2990.00"`，本地是 float，
     "金额对不对"只能写成 `abs(a-b) < 0.01` ⇒ **少收一分钱也算对账通过**。

存整数分之后：折算全在整数域、与网关的比对是 `int == int`（零容差）、
与外部网关的元形态只经过本文件的两个函数。

==============================================================================
★ 谁该用、谁不该用（刻意的例外）
==============================================================================
该用：**收款金额** —— `invoices` / `subscription_plans` / 网关 DTO / 前端。
不该用：**内部成本计量**（`subscriptions.llm_cost_used`，元 + 6 位小数）。
    单次 LLM 调用常见 0.0003 元 = 0.03 分，存整数分会被四舍五入成 0 ——
    计量直接归零，比浮点误差危险得多。

==============================================================================
★ 为什么放在 `core/` 而不是 `modules/billing/`
==============================================================================
外部适配层（`platforms/payment/alipay.py`）**不许** import 业务模块
（`modules/billing/pricing.py` 属于计费域）。把换算放在 `core/` 后，
适配层与业务层引用的是**同一份实现**，而不是各自复制一份 ——
「分 ↔ 元」一旦有两份实现，两份的取整方向迟早不同，
而那笔差额会出现在**账单**上（本仓 repeatedly 禁止的"同一口径两份实现"）。
"""

from decimal import Decimal, InvalidOperation, ROUND_HALF_UP
from typing import Optional

__all__ = ["fen_to_yuan_text", "yuan_to_fen", "fen_text"]


def fen_to_yuan_text(fen: int) -> str:
    """分 → 元（两位小数字符串）。**唯一**一处「分 → 元」的实现。

    只有外部网关需要元的形态（支付宝 `total_amount` 要两位小数字符串）。
    ★ 用 Decimal 而不是 `fen / 100`：后者先落到 float，299000/100 虽然恰好
      是 2990.0，但金额一旦变大或带小数就会漂 —— 收款金额不许靠
      "这个数恰好没漂"这种巧合。
    """
    return str((Decimal(int(fen)) / 100).quantize(Decimal("0.01")))


def yuan_to_fen(raw: object) -> Optional[int]:
    """元（字符串 / 数字）→ 分（整数）。**唯一**一处「元 → 分」的实现。

    ★ 解析失败返回 `None`，**不**兜底成 0：
      0 会让「回调金额与账单不符」的校验静默通过（0 == 0），
      而那正是这道校验要拦的东西。
    """
    try:
        d = Decimal(str(raw).strip())
    except (InvalidOperation, ValueError, TypeError, AttributeError):
        return None
    return int((d * 100).to_integral_value(rounding=ROUND_HALF_UP))


def fen_text(fen: int, *, symbol: str = "¥") -> str:
    """分 → **给人看**的短文本（整数元不带小数，否则两位小数）。

    这是前端 `fenText()` 的后端等价物（口径必须一致：`¥0` / `¥299` / `¥12.34`）。
    后端目前只在通知/日志类文案里用它；页面渲染由前端做。
    """
    n = int(fen or 0)
    if n == 0:
        return f"{symbol}0"
    yuan = Decimal(n) / 100
    if yuan == yuan.to_integral_value():
        return f"{symbol}{int(yuan)}"
    return f"{symbol}{yuan.quantize(Decimal('0.01'))}"
