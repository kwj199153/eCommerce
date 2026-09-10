"""
Amazon SP-API Mock Data Generator (CLI 入口)
============================================

这是一个**薄封装脚本**，实际数据生成逻辑已迁移到：
  modules/amazon_sp/data_sources/mock_source.py (MockAmazonDataSource 类)

架构分层：
  ┌─────────────────────────────────────┐
  │  本脚本 (CLI 入口 / JSON 输出)       │  ← 你在这里
  ├─────────────────────────────────────┤
  │  data_sources/mock_source.py         │  ← Mock 数据实现
  │  data_sources/base.py               │  ← 抽象接口定义
  ├─────────────────────────────────────┤
  │  db_model.py / models/amazon_sp.py   │  ← 数据模型 & Schema
  └─────────────────────────────────────┘

切换到真实 API 时：
  1. 新建 data_sources/spapi_source.py 实现 AmazonDataSource 接口
  2. 本脚本改一行：MockAmazonDataSource → SpApiDataSource
  3. 上层 Agent/Service 零改动

使用方式:
    python -m scripts.generate_amazon_mock_data                    # 默认30天
    python -m scripts.generate_amazon_mock_data --days 60          # 生成60天
    python -m scripts.generate_amazon_mock_data --seed 42          # 固定随机种子（可复现）
"""

import argparse
import json
import sys
from datetime import date, timedelta
from pathlib import Path

# 确保项目根目录在 sys.path 中（允许从 scripts/ 目录运行）
PROJECT_ROOT = Path(__file__).parent.parent
sys.path.insert(0, str(PROJECT_ROOT))

from modules.amazon_sp.data_sources import MockAmazonDataSource


def main():
    parser = argparse.ArgumentParser(description="Generate Amazon SP-API mock data")
    parser.add_argument("--days", type=int, default=30, help="Number of days to generate (default: 30)")
    parser.add_argument("--seed", type=int, default=None, help="Random seed for reproducibility")
    parser.add_argument("--output", type=str, default=None,
                        help="Output file path (default: auto-named in same directory)")
    args = parser.parse_args()

    # ---- 初始化数据源 ----
    source = MockAmazonDataSource(seed=args.seed)
    date_to = date.today()
    date_from = date_to - timedelta(days=args.days - 1)
    store_id = 1

    print("=" * 64)
    print("Amazon SP-API Mock Data Generator (v2 — Data Source Layer)")
    print("=" * 64)
    print(f"Source: {source.get_source_info()['name']}")
    print(f"Date range: {date_from} ~ {date_to} ({args.days} days)")
    print(f"Seed: {args.seed or 'random'}")
    print()

    # ---- 拉取全部数据 ----
    print("Fetching data from source...")

    credentials = source.fetch_credentials(store_id)
    daily_sales = source.fetch_daily_sales(store_id, date_from, date_to)
    ad_metrics = source.fetch_ad_metrics(store_id, date_from, date_to)
    listings = source.fetch_listings(store_id, date_from, date_to)
    inventory = source.fetch_inventory(store_id)
    competitors = source.fetch_competitors(store_id, date_from, date_to)  # 新增！
    report_tasks = source.fetch_report_tasks(store_id, date_from, date_to)

    # ---- 组装输出 ----
    output = {
        "_meta": {
            "generated_at": __import__("datetime").datetime.now().isoformat(),
            "source_type": "mock",
            "store_name": "TechHome Pro",
            "seller_id": SELLER_ID if 'SELLER_ID' in dir() else "A1B2C3D4E5F6G7",
            "marketplace": "us",
            "date_range": {"start": date_from.isoformat(), "end": date_to.isoformat(), "days": args.days},
            "product_count": len(set(s["asin"] for s in daily_sales)),
            "competitor_count": len(set(c["competitor_asin"] for c in competitors)),
            "campaign_count": len(set(m["campaign_name"] for m in ad_metrics)),
        },
        "amazon_credentials": credentials,
        "amazon_daily_sales": daily_sales,
        "amazon_ad_metrics": ad_metrics,
        "amazon_listing_snapshots": listings,
        "amazon_inventory_health": inventory,
        "amazon_competitor_snapshots": competitors,   # 新增！
        "amazon_report_tasks": report_tasks,
        "amazon_auth_logs": [],
    }

    # ---- 统计摘要 ----
    _print_summary(output)

    # ---- 写入文件 ----
    output_path = Path(args.output) if args.output else (
        Path(__file__).with_suffix(".data.json"))
    with open(output_path, "w", encoding="utf-8") as f:
        json.dump(output, f, ensure_ascii=False, indent=2, default=str)

    file_size = output_path.stat().st_size / 1024
    print(f"\n✅ Mock data written to: {output_path}")
    print(f"   File size: {file_size:.1f} KB")
    print(f"   Tables: {len(output) - 2} (excluding _meta + auth_logs)")

    return output


def _print_summary(output: dict):
    """打印数据摘要"""
    sales = output["amazon_daily_sales"]
    metrics = output["amazon_ad_metrics"]
    competitors = output.get("amazon_competitor_snapshots", [])
    inventory = output["amazon_inventory_health"]

    total_spend = sum(m["spend"] for m in metrics)
    total_sales = sum(m["sales"] for m in metrics)
    total_orders = sum(s["units_ordered"] for s in sales)
    total_revenue = sum(s["ordered_revenue"] for s in sales)
    overall_acos = round(total_spend / total_sales * 100, 2) if total_sales > 0 else 0
    roas_val = round(total_sales / total_spend, 2) if total_spend > 0 else 0

    meta = output["_meta"]

    print("\n" + "=" * 64)
    print("DATA SUMMARY")
    print("=" * 64)
    print(f"  Products:     {meta['product_count']} ASINs")
    print(f"  Competitors:  {meta['competitor_count']} ASINs")
    print(f"  Campaigns:    {meta['campaign_count']} campaigns")
    print()
    print(f"  daily_sales:       {len(sales):>5d} rows  ({total_orders:,} orders, ${total_revenue:,.2f})")
    print(f"  ad_metrics:        {len(metrics):>5d} rows  (${total_spend:,.2f} spend, ${total_sales:,.2f} sales)")
    print(f"                           Overall ACoS: {overall_acos}% | RoAS: {roas_val}")
    print(f"  listing_snapshots: {len(output['amazon_listing_snapshots']):>5d} rows")
    print(f"  competitor_snaps:  {len(competitors):>5d} rows")
    print(f"  inventory_health:  {len(inventory):>5d} rows")
    print(f"  report_tasks:      {len(output['amazon_report_tasks']):>5d} rows")

    # 按 ASIN 销售排行
    print("\n--- Sales by ASIN (full period) ---")
    asin_sales: dict[str, dict] = {}
    for s in sales:
        a = s["asin"]
        if a not in asin_sales:
            asin_sales[a] = {"units": 0, "revenue": 0}
        asin_sales[a]["units"] += s["units_ordered"]
        asin_sales[a]["revenue"] += s["ordered_revenue"]
    for a, st in sorted(asin_sales.items(), key=lambda x: -x[1]["revenue"]):
        print(f"  {a}: {st['units']:>4d} units, ${st['revenue']:>10,.2f}")

    # 广告 Campaign 表现
    print("\n--- Ad Performance by Campaign ---")
    camp_stats: dict[str, dict] = {}
    for m in metrics:
        cn = m["campaign_name"]
        if cn not in camp_stats:
            camp_stats[cn] = {"impr": 0, "clk": 0, "spend": 0, "sales": 0, "orders": 0}
        camp_stats[cn]["impr"] += m["impressions"]
        camp_stats[cn]["clk"] += m["clicks"]
        camp_stats[cn]["spend"] += m["spend"]
        camp_stats[cn]["sales"] += m["sales"]
        camp_stats[cn]["orders"] += m["orders"]

    for cn, st in sorted(camp_stats.items(), key=lambda x: -x[1]["spend"]):
        acos = round(st["spend"] / st["sales"] * 100, 2) if st["sales"] > 0 else 100
        ctr = round(st["clk"] / st["impr"] * 100, 2) if st["impr"] > 0 else 0
        status = "✅" if acos < 25 else ("⚠️" if acos < 40 else "❌")
        print(f"  {status} {cn[:28]:28s} ACoS={acos:>5.1f}% RoAS={ctr:>4.1f}% Spend=${st['spend']:>8,.2f}")

    # 竞品价格对比（新增）
    if competitors:
        print("\n--- Competitor Price Positioning (latest snapshot) ---")
        latest_date = max(c["snapshot_date"] for c in competitors)
        latest_comps = [c for c in competitors if c["snapshot_date"] == latest_date]
        for c in sorted(latest_comps, key=lambda x: x["price_vs_own"]):
            arrow = "↑更贵" if c["price_vs_own"] > 1 else ("↓更便宜" if c["price_vs_own"] < -1 else "≈持平")
            print(f"  [{c['brand']:12s}] {c['competitor_asin']} vs {c['competes_with_asin']}: "
                  f"${c['price']:.2f} ({arrow:6s}) BSR#{c['bsr_rank']:,} ⭐{c['rating']} ({c['review_count']:,} reviews)")


if __name__ == "__main__":
    main()
