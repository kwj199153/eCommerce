"""计费金额单位门禁：全链路必须是**整数分**（第 378 轮）。

==============================================================================
★ 为什么需要这个门禁
==============================================================================
「单位」是最容易**静默**出错的东西：改错了不会报错，只会让金额差 100 倍，
而差 100 倍的 2990 与 299000 在界面上**都像真的**（一个有 ¥、一个没有；
一个说 2990，一个说 29.9 万）。

更麻烦的是它**只改一半也能跑**：只改模型不改网关 DTO ⇒ mock 网关把「元」
当成「分」存进 `amount_fen` ⇒ 299 元变成 2.99 元。全程零报错。

⇒ 本文件把「单位」拆成 7 条可执行的判据：
  ① 模型列的**类型**（Integer，不是 Float）；
  ② 字段**名**带 `_fen`（改单位不改名 ⇒ 消费方静默按元渲染）；
  ③ 网关 DTO 同样是 `*_fen`（只改模型不改 DTO = 上面那个 100 倍坑）；
  ④ 折算函数返回 int（不是 float）；
  ⑤ 分↔元的唯一换算点（往返精确、解析失败返回 None 而不是 0）；
  ⑥ 金额比对**零容差**（用 AST 判形态，防"把 1 分容差加回来"）；
  ⑦ 支付宝适配层只能经 `fen_to_yuan_text`（AST 判，防手写 `:.2f`）。

★ 不连数据库：这些都是**形态事实**，用不到 client 夹具。
  本仓 `tests/` 直连共享生产库，能不进库的用例就别进（少一份互相干扰）。
"""

from __future__ import annotations

import ast
import os
from dataclasses import fields
from pathlib import Path
from types import SimpleNamespace

import pytest
import sqlalchemy as sa

from core.money import fen_text, fen_to_yuan_text, yuan_to_fen
from modules.billing.models import Invoice, Subscription, SubscriptionPlan
from modules.billing.payments import amount_matches
from modules.billing.pricing import plan_amount, yearly_price
from platforms.payment.gateway import ChargeIntent, InvoiceDraft

BACKEND = Path(__file__).resolve().parents[1]

#: AST 判据读哪个根 —— 供变异自证（`mutate-billing-units.py`）指向临时副本，
#: 这样"证明门禁会红"不需要改真源。默认就是真源。
SRC_ROOT = Path(os.environ.get("BILLING_UNITS_ROOT") or BACKEND)


def _tree(rel: str) -> ast.Module:
    return ast.parse((SRC_ROOT / rel).read_text(encoding="utf-8"))


def _func(tree: ast.Module, name: str) -> ast.FunctionDef:
    for node in ast.walk(tree):
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)) and node.name == name:
            return node
    raise AssertionError(f"找不到函数 {name}")


def _calls(node: ast.AST) -> set[str]:
    """函数体内**直接调用**到的函数名集合（不含 docstring / 注释）。"""
    out: set[str] = set()
    for sub in ast.walk(node):
        if isinstance(sub, ast.Call):
            f = sub.func
            if isinstance(f, ast.Name):
                out.add(f.id)
            elif isinstance(f, ast.Attribute):
                out.add(f.attr)
    return out


# ============================================================================
# ①② 模型列：类型与列名
# ============================================================================

def test_invoice_amount_is_integer_fen():
    cols = Invoice.__table__.c
    assert "amount_fen" in cols, "invoices 必须有 amount_fen（单位：分）"
    assert isinstance(cols["amount_fen"].type, sa.Integer), (
        f"amount_fen 必须是 Integer（分），实际 {cols['amount_fen'].type}"
    )
    assert "amount" not in cols, (
        "旧的 `amount`（元 float）列必须**删掉**：两列并存 ⇒ 总有一处读到过时的那个"
    )


def test_plan_price_is_integer_fen():
    cols = SubscriptionPlan.__table__.c
    assert "price_monthly_fen" in cols, "subscription_plans 必须有 price_monthly_fen"
    assert isinstance(cols["price_monthly_fen"].type, sa.Integer), (
        f"price_monthly_fen 必须是 Integer（分），实际 {cols['price_monthly_fen'].type}"
    )
    assert "price_monthly" not in cols, "旧的 `price_monthly`（元 float）列必须删掉"


def test_llm_cost_stays_yuan_float():
    """★ 刻意的例外：**内部成本计量**不跟着改成分。

    单次 LLM 调用常见 0.0003 元 = 0.03 分，存整数分会被四舍五入成 0 ⇒
    计量归零，界面显示"用了很多、成本 0"。这比浮点误差危险得多。
    这条判据防的是「有人为了统一，顺手把它也改了」。
    """
    col = Subscription.__table__.c["llm_cost_used"]
    assert isinstance(col.type, sa.Float), (
        f"llm_cost_used 必须保持 Float（元，6 位小数），实际 {col.type}；"
        "它是内部成本计量，不是收款金额"
    )


# ============================================================================
# ③ 网关 DTO 与模型同名同单位
# ============================================================================

def test_gateway_dto_uses_fen():
    for cls in (ChargeIntent, InvoiceDraft):
        names = {f.name for f in fields(cls)}
        assert "amount_fen" in names, f"{cls.__name__} 必须用 amount_fen（单位分）"
        assert "amount" not in names, (
            f"{cls.__name__} 里不许再有 `amount`："
            "只改模型不改 DTO ⇒ 网关把元当分落库，金额差 100 倍且零报错"
        )


# ============================================================================
# ④ 折算函数返回整数分
# ============================================================================

def test_price_helpers_return_int_fen():
    assert yearly_price(29900) == 299000
    assert isinstance(yearly_price(29900), int)

    plan = SubscriptionPlan(name="pro", display_name="专业版", price_monthly_fen=29900)
    assert plan_amount(plan, "monthly") == 29900
    assert plan_amount(plan, "yearly") == 299000
    assert isinstance(plan_amount(plan, "yearly"), int), "折算结果必须是 int（分），不能是 float"

    free = SubscriptionPlan(name="free", display_name="免费版", price_monthly_fen=0)
    assert plan_amount(free, "yearly") == 0


# ============================================================================
# ⑤ 分 ↔ 元：唯一换算点，往返精确
# ============================================================================

@pytest.mark.parametrize(
    "fen,text",
    [(0, "0.00"), (1, "0.01"), (29900, "299.00"), (299000, "2990.00"), (-1234, "-12.34")],
)
def test_fen_to_yuan_text(fen, text):
    assert fen_to_yuan_text(fen) == text


@pytest.mark.parametrize(
    "raw,fen",
    [("0.01", 1), ("2990.00", 299000), ("2990", 299000), (12.34, 1234), ("-12.34", -1234)],
)
def test_yuan_to_fen(raw, fen):
    assert yuan_to_fen(raw) == fen


@pytest.mark.parametrize("raw", ["", "abc", None, "1,234.00"])
def test_yuan_to_fen_returns_none_not_zero(raw):
    """★ 解析失败必须是 `None`，**不许**兜底成 0。

    兜底 0 会让「回调金额与账单不符」的校验静默通过（0 == 0），
    而那正是这道校验存在的理由。
    """
    assert yuan_to_fen(raw) is None


def test_fen_text_display_matches_frontend():
    """显示口径必须与前端 `api/billing.ts::fenText` 一致。"""
    assert fen_text(0) == "¥0"
    assert fen_text(29900) == "¥299"      # 整数元不带小数
    assert fen_text(1234) == "¥12.34"


# ============================================================================
# ⑥ 金额比对：零容差（AST 形态判据）
# ============================================================================

def test_amount_matches_is_exact():
    inv = SimpleNamespace(amount_fen=299000)
    assert amount_matches(inv, 299000) is True
    assert amount_matches(inv, 299001) is False, "多收 1 分也算不符"
    assert amount_matches(inv, 298999) is False, "少收 1 分必须拦下（容差就会漏这里）"
    assert amount_matches(inv, 0) is False
    assert amount_matches(inv, None) is False, "金额缺失不能当通过"


def test_amount_matches_has_no_tolerance():
    """★ 形态判据：函数体里**不许出现 `abs(...)`**。

    改前是 `abs(a - b) < 0.01`（浮点容差）。只看行为的话，
    容差写成 `< 1`（1 分）时 299000 vs 299001 仍会通过 —— 而它正是要拦的。
    用 AST 而不是 `"abs(" in source`：docstring 里提到 abs 会骗过字符串判据。
    """
    fn = _func(_tree("modules/billing/payments.py"), "amount_matches")
    assert "abs" not in _calls(fn), (
        "amount_matches 里出现了 abs() ⇒ 又变成带容差的比对了；"
        "整数分必须 `int(a) == int(b)`"
    )


# ============================================================================
# ⑦ 支付宝适配层：只经唯一换算点
# ============================================================================

def test_alipay_charge_converts_through_core_money():
    fn = _func(_tree("platforms/payment/alipay.py"), "charge")
    calls = _calls(fn)
    assert "fen_to_yuan_text" in calls, (
        "支付宝下单必须用 core.money.fen_to_yuan_text 把分转成元字符串；"
        "手写 f-string 迟早把 `2990`（少两位）或 float 尾巴送出去"
    )
    assert "round" not in calls, "charge 里不该再有 round() —— 金额已是整数分"


def test_alipay_notify_uses_shared_parser():
    """回调金额解析必须走 `yuan_to_fen`（Decimal），不许自己 float(...)。"""
    tree = _tree("platforms/payment/alipay.py")
    fn = _func(tree, "amount_fen")
    assert "yuan_to_fen" in _calls(fn)


def test_no_float_money_in_billing_router():
    """`/billing` 出参不许把 `price_monthly` / `amount` 这类旧字段再吐出去。

    ★ 判据看的是**函数里返回的字典键**（AST 常量），不是源码字符串：
      docstring 里写着「不要返回 amount」不会让这条变红。
    """
    tree = _tree("modules/billing/router.py")
    bad_keys = {"amount", "price_monthly", "price_yearly"}
    hits: list[str] = []
    for node in ast.walk(tree):
        if isinstance(node, ast.Dict):
            for k in node.keys:
                if isinstance(k, ast.Constant) and k.value in bad_keys:
                    hits.append(str(k.value))
    assert not hits, (
        f"modules/billing/router.py 仍在输出无单位的金额键 {hits}；"
        "必须用 amount_fen / price_monthly_fen / price_yearly_fen"
    )
