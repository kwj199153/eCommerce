"""
竞品监控池 - 时序快照生成器

**为什么生成器搬到了后端**：原实现是前端 `stores/monitorPool.ts` 里的确定性伪随机
（`seedRand` + `buildMockRecord`），每次进页面重算一遍 —— 数据不落库，刷新就"重掷"。
持久化后改为「入池时生成一次并写库」：

  · 同一 ASIN 的历史序列从此**固定**，刷新不再跳动
  · 面板拿到的仍是完整的 30 天序列，**前端展示逻辑零改动**
  · 将来接真实抓取（SP-API / 爬虫），**只需替换本模块**，表结构与前端契约都不动

确定性算法沿用前端那份（FNV-1a 哈希，ASIN 串作种子），所以同一 ASIN 生成的历史
曲线形状与改造前一致，视觉上不会突变。

**修掉了原实现的一个逻辑 bug**：`stock_status` 原写法是
`roll > 0.82 ? 'low_stock' : roll > 0.92 ? 'out_of_stock' : 'in_stock'` ——
第一个条件先命中，`out_of_stock` **永远不可达**，"缺货预警"面板从来没亮过。
这里按正确语义重排，所以 seed 数据里会首次出现缺货样本（属修复而非行为回归）。
"""

import math
from datetime import date, timedelta
from typing import Dict, List, Optional


# ====== 确定性伪随机（FNV-1a，对齐前端 seedRand）======

def _rand01(seed: str, salt: int = 0) -> float:
    """返回 [0, 1) 的确定性伪随机数。同一 (seed, salt) 永远得到同一个值。"""
    h = 2166136261
    for ch in f"{seed}{salt}":
        h ^= ord(ch)
        h = (h * 16777619) & 0xFFFFFFFF
    return (h % 1000) / 1000


def _r2(x: float) -> float:
    """保留两位小数（价格/百分比用）"""
    return round(x, 2)


def _round_int(x: float) -> int:
    """四舍五入取整（对齐 JS Math.round，不走 Python 的银行家舍入）"""
    return int(math.floor(x + 0.5))


def last_n_days(n: int, today: Optional[date] = None) -> List[str]:
    """近 n 天日期（YYYY-MM-DD，不含今天），与前端 lastNDays 一致"""
    base = today or date.today()
    return [(base - timedelta(days=i)).isoformat() for i in range(n, 0, -1)]


# ====== 各时序段 ======

def _build_price_history(asin: str, base: float, days: List[str]) -> List[Dict]:
    """价格历史：缓慢波动 + 随机优惠券/会员折扣 + 近 5 天偶发秒杀"""
    p0 = _rand01(asin, 1)
    out: List[Dict] = []
    for i, d in enumerate(days):
        wave = math.sin(i / 4 + p0 * 6) * 1.2
        price = _r2(base + wave)
        point: Dict = {"date": d, "price": price}
        r = _rand01(f"{asin}{d}", 2)
        if r > 0.72:
            point["coupon"] = _r2(price * 0.08)
        if r > 0.9:
            point["is_prime_deal"] = True
        # 近 5 天有较大概率做秒杀（价格打到 86 折）
        if i > len(days) - 6 and _rand01(asin, 3 + i) > 0.55:
            point["price"] = _r2(base * 0.86)
            point["deal_type"] = "ld" if _rand01(asin, 4 + i) > 0.5 else "7dd"
        out.append(point)
    return out


def _build_bsr_history(asin: str, base_bsr: int, days: List[str], idx: int) -> List[Dict]:
    """BSR 历史：围绕基准排名漂移"""
    out: List[Dict] = []
    for i, d in enumerate(days):
        drift = (_rand01(f"{asin}{d}", 5) - 0.5) * (base_bsr * 0.25)
        bsr = _round_int(base_bsr + drift + math.sin(i / 5 + idx) * base_bsr * 0.12)
        out.append({"date": d, "bsr": max(1, bsr)})
    return out


def _build_review_events(asin: str, month_sales: int, days: List[str]) -> List[Dict]:
    """评论事件：多数日为 0 新增，偶有新增，约 12% 触发差评预警"""
    out: List[Dict] = []
    for d in days:
        r = _rand01(f"{asin}{d}", 6)
        if r < 0.55:
            out.append({"date": d, "added": 0, "rating_delta": 0})
            continue
        ceiling = 9 if month_sales > 5000 else 3
        added = 1 + int(_rand01(f"{asin}{d}", 7) * ceiling)
        neg = _rand01(f"{asin}{d}", 8) > 0.88
        event: Dict = {
            "date": d,
            "added": added,
            "rating_delta": _r2(_rand01(f"{asin}{d}", 9) * 0.12 - 0.05),
        }
        if neg:
            event["negative"] = True
            event["snippet"] = "Product stopped working after a week, poor quality control."
        out.append(event)
    return out


def _build_variations(asin: str, base: float) -> List[Dict]:
    """变体：1-4 个子 ASIN"""
    count = 1 + int(_rand01(asin, 10) * 4)
    colors = ["Black", "White", "Silver", "Blue", "Rose Gold"]
    return [
        {
            "child_asin": f"{asin[:-1]}{v}",
            "color": colors[v % 5],
            "size": "Standard" if v % 2 == 0 else "Large",
            "price": _r2(base + (v * 3 - (count / 2))),
            "in_stock": _rand01(asin, 11 + v) > 0.25,
        }
        for v in range(count)
    ]


def _build_listing_changes(asin: str, days: List[str]) -> List[Dict]:
    """Listing 变更日志：近 30 天 1-3 条"""
    field_pool = [
        ("title", "标题"),
        ("bullet", "五点描述"),
        ("a_plus", "A+ 页面"),
        ("main_image", "主图"),
        ("video", "主图视频"),
        ("description", "描述"),
    ]
    count = 1 + int(_rand01(asin, 12) * 3)
    out: List[Dict] = []
    for ci in range(count):
        field, field_name = field_pool[int(_rand01(asin, 13 + ci) * len(field_pool)) % len(field_pool)]
        # days 长 30，offset 落在 6..25，恒有效
        changed_at = days[6 + int(_rand01(asin, 20 + ci) * 20)]
        out.append({
            "id": f"{asin}-lc-{ci}",
            "changed_at": changed_at,
            "field": field,
            "field_name": field_name,
            "old_preview": "旧版本内容……",
            "new_preview": f"{field_name}已更新：优化关键词 / 调整卖点表达",
        })
    return out


def _build_inventory(asin: str) -> Dict:
    """库存态 + 剩余可售估算。缺货时剩余量为 None（无从估算）。"""
    roll = _rand01(asin, 30)
    if roll > 0.92:
        return {"stock_status": "out_of_stock", "estimated_units_remaining": None}
    if roll > 0.82:
        return {
            "stock_status": "low_stock",
            "estimated_units_remaining": _round_int(80 + _rand01(asin, 31) * 400),
        }
    return {
        "stock_status": "in_stock",
        "estimated_units_remaining": _round_int(1500 + _rand01(asin, 32) * 9000),
    }


# ====== 对外接口 ======

def derive_baseline(asin: str, payload: Optional[Dict] = None) -> Dict:
    """
    推导价格 / BSR 基准。

    入池时用户往往**只填一个 ASIN**（「添加竞品」弹窗就一个输入框），没有价格与
    排名基准可依。此时按 ASIN 确定性推导一组合理值 —— 同一个 ASIN 永远得到同一
    组基准，不会每次入池都换一份画像。
    """
    payload = payload or {}
    price = payload.get("latest_price")
    bsr = payload.get("latest_bsr")
    if not price or price <= 0:
        price = _r2(19.99 + _rand01(asin, 101) * 80)      # 19.99 ~ 99.99
    if not bsr or bsr <= 0:
        bsr = _round_int(200 + _rand01(asin, 102) * 5000)  # 200 ~ 5200
    return {"base_price": float(price), "base_bsr": int(bsr)}


def build_time_series(
    asin: str,
    base_price: float,
    base_bsr: int,
    month_sales: int = 0,
    idx: int = 0,
    days: int = 30,
) -> Dict:
    """
    为一个 ASIN 生成完整的 30 天时序 + 派生快照。

    入池时调用一次，结果整体写入 monitors 表的 JSON 列。

    Returns:
        {
          price_history, bsr_history, review_events, variations, listing_changes,
          latest_price, price_change_7d, latest_bsr, bsr_change_7d,
          reviews_added_7d, stock_status, estimated_units_remaining
        }
    """
    day_list = last_n_days(days)

    price_history = _build_price_history(asin, base_price, day_list)
    latest_price = price_history[-1]["price"]
    price_7d_ago = price_history[-8]["price"] if len(price_history) >= 8 else base_price
    price_change_7d = _r2((latest_price - price_7d_ago) / price_7d_ago * 100) if price_7d_ago else 0.0

    bsr_history = _build_bsr_history(asin, base_bsr, day_list, idx)
    latest_bsr = bsr_history[-1]["bsr"]
    bsr_7d_ago = bsr_history[-8]["bsr"] if len(bsr_history) >= 8 else base_bsr
    bsr_change_7d = latest_bsr - bsr_7d_ago

    review_events = _build_review_events(asin, month_sales, day_list)
    reviews_added_7d = sum(e["added"] for e in review_events[-7:])

    inventory = _build_inventory(asin)

    return {
        "price_history": price_history,
        "bsr_history": bsr_history,
        "review_events": review_events,
        "variations": _build_variations(asin, base_price),
        "listing_changes": _build_listing_changes(asin, day_list),
        "latest_price": latest_price,
        "price_change_7d": price_change_7d,
        "latest_bsr": latest_bsr,
        "bsr_change_7d": bsr_change_7d,
        "reviews_added_7d": reviews_added_7d,
        **inventory,
    }
