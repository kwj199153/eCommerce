# Amazon SP-API 集成指南

## 概述

本项目已完整集成 **Amazon Selling Partner API (SP-API)**，支持获取真实的商品、订单、广告数据。

## 架构设计

```
┌─────────────────────────────────────────────────────┐
│                   业务 Agent 层                       │
│  ProductResearch | ListingGen | AdAnalysis | CS      │
│       ↓              ↓           ↓          ↓        │
├─────────────────────────────────────────────────────┤
│              platforms/amazon/sp_api/                 │
│                                                      │
│  ┌──────────┐  ┌──────────┐  ┌──────────────────┐   │
│  │  auth.py │  │ client.py│  │  业务封装模块       │   │
│  │ LWA+AWS  │→ │ 统一请求 │  │ products/orders/  │   │
│  │ 签名认证  │  │ 错误重试 │  │ reports/advertising│   │
│  └──────────┘  └──────────┘  └──────────────────┘   │
│                      ↓                               │
│              models.py (25+ 数据模型)                │
└─────────────────────────────────────────────────────┘
```

## 快速开始

### 1. 获取 SP-API 凭证

#### 步骤 A：创建 Amazon Developer 应用

1. 访问 [Amazon Developer Portal](https://developer.amazon.com/)
2. 注册开发者账号（需要 Professional 卖家账号）
3. 创建新应用，选择 **Selling Partner API**
4. 记录下 **Client ID** 和 **Client Secret**

#### 步骤 B：配置 IAM 用户

1. 在 AWS Console 创建 IAM 用户
2. 附加策略：`AmazonSPAPIFullAccess` 或自定义最小权限
3. 记录下 **Access Key ID** 和 **Secret Access Key**
4. 注意 Region 必须是 `us-east-1`（SP-API 要求）

#### 步骤 C：完成 LWA 授权

1. 使用 OAuth 2.0 授权流程获取 **Refresh Token**
2. 授权范围：`sellingpartnerapi::migration`
3. 可使用官方 [Authorization Helper](https://sellercentral.amazon.com/apps/authorize/consent) 或自行实现

### 2. 配置环境变量

编辑 `.env` 文件：

```bash
# ====== Amazon SP-API 配置 ======
SPAPI_LWA_CLIENT_ID=amzn1.application-oa2-client.xxxxxxxx
SPAPI_LWA_CLIENT_SECRET=xxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxx
SPAPI_REFRESH_TOKEN=Atzr|xxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxx
SPAPI_AWS_ACCESS_KEY=AKIAIOSFODNN7EXAMPLE
SPAPI_AWS_SECRET_KEY=wJalrXUtnFEMI/K7MDENG/bPxRfiCYEXAMPLEKEY
SPAPI_AWS_REGION=us-east-1
SPAPI_USE_SANDBOX=false    # true=Sandbox(测试), false=Production(正式)
```

### 3. 使用示例

```python
from platforms.amazon.sp_api import (
    SPAPIClient,
    ProductsAPI,
    OrdersAPI,
    ReportsAPI,
    AdvertisingAPI,
    Marketplace,
)

async def main():
    # 初始化客户端
    client = SPAPIClient(default_marketplace=Marketplace.US)

    # 商品操作
    products = ProductsAPI(client)

    # 获取商品详情
    detail = await products.get_product_detail("B0CGLKP2R1")
    print(f"商品: {detail['title']}")
    print(f"价格: {detail['pricing']['buy_box_price']}")

    # 批量获取竞品信息
    competitors = await products.get_competitor_listings([
        "B0CGLKP2R1",
        "B0DXYZ1234",
        "B0FABC5678",
    ])

    for c in competitors:
        print(f"{c.asin}: ${c.price} | BuyBox: ${c.buy_box_price}")

    # Buy Box 分析
    buy_box = await products.analyze_buy_box("B0CGLKP2R1")
    print(f"Buy Box 赢家: {buy_box.winner_seller_id}")
    print(f"FBA 报价: {buy_box.fba_offers}个")

    # 订单操作
    orders = OrdersAPI(client)

    # 追踪订单（客服场景）
    tracking = await orders.track_order("112-1234567-8901234")
    if tracking["found"]:
        print(f"订单状态: {tracking['current_status']['label']}")

    # 获取订单统计
    stats = await orders.get_order_statistics(days_back=7)
    print(f"7日订单: {stats['total_orders']}单, 收入: ${stats['total_revenue']}")

    # 报告操作
    reports = ReportsAPI(client)

    # 获取销售流量报告
    sales_data = await reports.get_sales_traffic_report(days_back=7)
    for day in sales_data[:3]:
        print(f"日期: {day.get('date')} | 销售: ${day.get('totalSales', 0)}")

    # 广告搜索词分析
    ad_api = AdvertisingAPI(client)
    search_analysis = await ad_api.analyze_search_terms(days_back=30)
    print(f"总花费: ${search_analysis['summary']['total_spend']}")
    print(f"浪费金额: ${search_analysis['summary']['waste_amount']}")

    # 关闭客户端
    await client.close()
```

## API 覆盖范围

### Products API (v2022-05-01)

| 方法 | 说明 |
|------|------|
| `get_item_by_asin()` | 通过 ASIN 获取商品详情 |
| `get_item_offers()` | 获取商品报价列表 |
| `get_batch_item_offers()` | 批量获取报价 |
| `get_inventory_summaries()` | 获取库存摘要 |
| `search_catalog_items()` | 目录商品搜索 |

### Orders API (v0)

| 方法 | 说明 |
|------|------|
| `get_orders_by_date_range()` | 按日期范围获取订单 |
| `get_order_detail()` | 获取完整订单详情 |
| `track_order()` | 订单状态追踪（客服用） |
| `get_order_statistics()` | 订单统计汇总 |

### Reports API (2021-06-30)

| 报告类型 | 说明 |
|----------|------|
| `GET_SALES_AND_TRAFFIC_REPORT` | 销售和流量报告 |
| `GET_FBA_INVENTORY_HEALTH_DATA` | FBA 库存健康度 |
| `SP_SEARCH_TERM_REPORT` | SP 搜索词报告 |
| `SP_KEYWORDS_REPORT` | SP 关键词报告 |
| `SP_CAMPAIGN_REPORT` | SP 广告活动报告 |

共支持 **25 种**报告类型。

### Advertising API

| 方法 | 说明 |
|------|------|
| `get_campaigns()` | 获取广告活动列表 |
| `analyze_search_terms()` | 搜索词表现分析 |
| `generate_bid_suggestions()` | 出价优化建议 |
| `monitor_competitor_ads()` | 竞品广告监控 |
| `suggest_budget_reallocation()` | 预算分配建议 |

## 支持的市场 (Marketplace)

| 市场 | Code | 区域 |
|------|------|------|
| 美国 | ATVPDKIKX0DER | North America |
| 加拿大 | A2EUQ1WTGCTBG2 | North America |
| 墨西哥 | A1AM78C64UM0Y8 | North America |
| 英国 | A1F83G8C2ARO7P | Europe |
| 德国 | A1PA6795UKMFR9 | Europe |
| 法国 | A13V1IB3VIYZZH | Europe |
| 意大利 | APJ6JRA9NG5V4 | Europe |
| 西班牙 | A1RKKUPIHCS9HS | Europe |
| 日本 | A1VC38T7YXB528 | Far East |
| 澳大利亚 | A39IBJ37TRP1C6 | Pacific |

## 认证流程

```
┌─────────────┐     ┌─────────────┐     ┌──────────────────┐
│  LWA OAuth  │────▶│ Access Token │────▶│ AWS Signature V4  │
│  Refresh    │     │ (60min 有效) │     │ 请求签名          │
│  Token      │     └─────────────┘     └────────┬─────────┘
└─────────────┘                                   │
                                                   ▼
                                          ┌──────────────────┐
                                          │   SP-API 端点     │
                                          │  sandbox/prod     │
                                          └──────────────────┘
```

### Token 自动刷新

- Access Token 有效期 **60 分钟**
- 系统在 Token 过期前 **5 分钟**自动刷新
- 无需手动管理 Token 生命周期

### 限流处理

- 自动检测 HTTP 429 (Too Many Requests)
- 根据 `Retry-After` 头等待后重试
- 最大重试次数：**3 次**

## Mock 兜底机制

当 SP-API 凭证未配置或请求失败时，系统会：
1. 尝试调用真实 API
2. 失败时降级到 Mock 数据（现有逻辑）
3. 在响应中标记数据来源 (`source: "mock"` / `"sp-api"`)

这确保了在开发阶段无需真实凭证也能运行。

## 文件结构

```
platforms/amazon/
├── client.py              # 原 Mock 适配器（保留兼容）
└── sp_api/                # ★ 新增 SP-API 模块
    ├── __init__.py        # 统一导出
    ├── auth.py            # LWA + AWS Signature V4 认证 (~400行)
    ├── models.py          # 25+ 数据模型 (~500行)
    ├── client.py          # 核心客户端 + 所有 API 方法 (~500行)
    ├── products.py        # Products API 高级封装 (~300行)
    ├── orders.py          # Orders API 高级封装 (~250行)
    ├── reports.py         # Reports API 高级封装 (~300行)
    └── advertising.py     # Advertising API 高级封装 (~350行)
```

**总计**: ~2600 行代码，完整的 SP-API 集成。

## 参考文档

- [SP-API 官方文档](https://developer-docs.amazon.com/sp-api/docs)
- [LWA 授权指南](https://developer-docs.amazon.com/sp-api/docs/authorization-api-use-case-guide)
- [AWS Signature V4](https://docs.aws.amazon.com/general/latest/gr/signature-version-4.html)
- [Reports API 参考](https://developer-docs.amazon.com/sp-api/reference/reports-api-2021-06-30.html)
