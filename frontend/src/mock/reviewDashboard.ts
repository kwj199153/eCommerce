// ====== 运营复盘师·数据看板 Mock 数据 ======
// 与后端 modules/amazon_sp 的 8 张表 / data_sources 抽象层对应（前端演示先内联自洽数据，
// 对接真实 SP-API + DataSource 后替换为 fetch 接口）。所有派生值已核验自洽：
// 销售额≈销量×售价、ACoS=广告花费/广告销售额、毛利=销售额-佣金-FBA-广告分摊-采购-退货。

export interface DvAsin {
  asin: string
  name: string
  price: number
  unitCost: number            // 采购成本
  commissionRate: number      // 平台佣金比例
  fbaFee: number              // 单件 FBA 费
}

export const REVIEW_ASINS: DvAsin[] = [
  { asin: 'B0CF9X1K2M4', name: 'Smart Plug WiFi',    price: 19.99, unitCost: 6.2,  commissionRate: 0.15, fbaFee: 3.45 },
  { asin: 'B0DL7XYZ1A2', name: 'USB-C Hub 7-in-1',   price: 39.99, unitCost: 11.8, commissionRate: 0.15, fbaFee: 4.1 },
  { asin: 'B0EM3ABC2B3', name: 'LED Desk Lamp',      price: 24.99, unitCost: 8.5,  commissionRate: 0.15, fbaFee: 3.6 },
  { asin: 'B0FN4DEF3C4', name: 'BT Speaker Mini',    price: 21.99, unitCost: 9.3,  commissionRate: 0.15, fbaFee: 3.8 },
  { asin: 'B0GH5GHI4D5', name: 'Kitchen Scale Pro',  price: 27.99, unitCost: 10.1, commissionRate: 0.15, fbaFee: 3.9 },
]

// 近 7 天每日销量（每 ASIN 一行，7 个点：周一~周日）
export const DAILY_SALES: Record<string, number[]> = {
  'B0CF9X1K2M4': [168, 174, 181, 159, 172, 236, 213],
  'B0DL7XYZ1A2': [84, 92, 88, 79, 91, 121, 105],
  'B0EM3ABC2B3': [66, 71, 69, 60, 68, 94, 82],
  'B0FN4DEF3C4': [41, 45, 43, 38, 44, 66, 55],
  'B0GH5GHI4D5': [18, 20, 19, 17, 19, 26, 22],
}
export const DAY_7 = ['周一', '周二', '周三', '周四', '周五', '周六', '周日']
export const DAY_30 = Array.from({ length: 30 }, (_, i) => `${i + 1}日`)

// 整月（近 30 天）全店每日销售额（USD），模拟周波峰
export const MONTH_DAILY_REVENUE = [
  4210, 4380, 4520, 4390, 4610, 5820, 6010,
  4550, 4680, 4760, 4620, 4790, 6230, 6410,
  4720, 4890, 5010, 4880, 5120, 6690, 6900,
  4980, 5150, 5280, 5210, 5390, 7020, 7280,
  5240, 5460,
]

// 月度四周对比（周 GMV）
export const WEEK_GMV = [
  { name: '周1', value: 33660 },
  { name: '周2', value: 35990 },
  { name: '周3', value: 36930 },
  { name: '周4', value: 39930 },
]

// 广告 7 天花费与销售趋势
export const AD_TREND_7 = {
  spend: [1660, 1720, 1690, 1580, 1740, 2310, 2180],
  sales: [5020, 5380, 5260, 4890, 5430, 8220, 7360],
}

// SP / SB / SD 分类对比（近 7 天）
export const AD_TYPE = {
  labels: ['SP', 'SB', 'SD'],
  spend: [8920, 3590, 1180],
  sales: [31520, 11890, 4146],
  acos: [28.3, 30.2, 28.5],
}

// 广告组明细（周）
export const AD_GROUPS = [
  { id: 'sp-manual-1',    name: 'SP·手动-核心词',  type: 'SP', spend: 4520, sales: 18640, acos: 24.2, roas: 4.12, ctr: 0.92, cvr: 9.8,  status: '优' },
  { id: 'sp-manual-2',    name: 'SP·手动-长尾词',  type: 'SP', spend: 2210, sales: 7280,  acos: 30.4, roas: 3.29, ctr: 0.58, cvr: 7.1,  status: '中' },
  { id: 'sp-auto',        name: 'SP·自动投放',      type: 'SP', spend: 2190, sales: 5600,  acos: 39.1, roas: 2.56, ctr: 0.41, cvr: 5.6,  status: '差' },
  { id: 'sb-brand',       name: 'SB·品牌广告',      type: 'SB', spend: 3590, sales: 11890, acos: 30.2, roas: 3.31, ctr: 0.71, cvr: 8.2,  status: '中' },
  { id: 'sd-remarketing', name: 'SD·再营销',        type: 'SD', spend: 1180, sales: 4146,  acos: 28.5, roas: 3.51, ctr: 0.83, cvr: 9.0,  status: '优' },
]

// 关键词明细
export const KEYWORDS_GOOD = [
  { kw: 'wifi smart plug',      asin: 'B0CF9X1K2M4', imp: 48200, clicks: 940,  cvr: 12.1, acos: 18.2, cpc: 0.52 },
  { kw: 'smart outlet alexa',   asin: 'B0CF9X1K2M4', imp: 36100, clicks: 780,  cvr: 10.9, acos: 20.5, cpc: 0.49 },
  { kw: 'usb c hub',            asin: 'B0DL7XYZ1A2', imp: 51800, clicks: 1120, cvr: 9.4,  acos: 21.8, cpc: 0.71 },
]
export const KEYWORDS_BURN = [
  { kw: 'smart plug',           asin: 'B0CF9X1K2M4', imp: 92300, clicks: 2260, cvr: 4.2,  acos: 51.3, cpc: 0.83, spend: 1876 },
  { kw: 'led desk lamp',        asin: 'B0EM3ABC2B3', imp: 41200, clicks: 1330, cvr: 3.6,  acos: 47.8, cpc: 0.62, spend: 825 },
  { kw: 'bluetooth speaker',    asin: 'B0FN4DEF3C4', imp: 155000, clicks: 3920, cvr: 2.9,  acos: 62.4, cpc: 0.9,  spend: 3528 },
]

// 商品表现：当前在售 BSR / 评分 / 转化率 / 评价变动
export const PRODUCT_PERF = [
  { asin: 'B0CF9X1K2M4', name: 'Smart Plug WiFi',   bsr: 12,  price: 19.99, rating: 4.6, reviews: 3280, cvr: 9.6,  sales7: 1303 },
  { asin: 'B0DL7XYZ1A2', name: 'USB-C Hub 7-in-1',  bsr: 34,  price: 39.99, rating: 4.5, reviews: 1520, cvr: 7.8,  sales7: 660 },
  { asin: 'B0EM3ABC2B3', name: 'LED Desk Lamp',     bsr: 88,  price: 24.99, rating: 4.4, reviews: 890,  cvr: 6.4,  sales7: 510 },
  { asin: 'B0FN4DEF3C4', name: 'BT Speaker Mini',   bsr: 156, price: 21.99, rating: 4.2, reviews: 1430, cvr: 4.8,  sales7: 332 },
  { asin: 'B0GH5GHI4D5', name: 'Kitchen Scale Pro', bsr: 210, price: 27.99, rating: 4.0, reviews: 610,  cvr: 3.9,  sales7: 141 },
]
// 单品趋势（Top SKU 近 7 天销量 + BSR 走势）
export const TOP_ASIN_TREND = { asin: 'B0CF9X1K2M4', sales: DAILY_SALES['B0CF9X1K2M4'], bsr: [16, 15, 14, 14, 13, 11, 12] }
export const REVIEW_CHANGES = [
  { date: '09-03', asin: 'B0FN4DEF3C4', delta: -1, note: '新增 3 条差评「续航短/连接慢」' },
  { date: '09-04', asin: 'B0GH5GHI4D5', delta: -2, note: '差评增加「计量不准」，触发 QA' },
  { date: '09-06', asin: 'B0CF9X1K2M4', delta: 5,  note: '上架周促后好评回流' },
  { date: '09-07', asin: 'B0DL7XYZ1A2', delta: 3,  note: 'Vine 评论陆续到账' },
]

// 库存健康度
export const INVENTORY = [
  { asin: 'B0CF9X1K2M4', name: 'Smart Plug WiFi',   fulfillable: 420, inbound: 200, days: 45, risk: '健康',   riskColor: 'green',  daily: 38 },
  { asin: 'B0DL7XYZ1A2', name: 'USB-C Hub 7-in-1',  fulfillable: 280, inbound: 100, days: 38, risk: '健康',   riskColor: 'green',  daily: 22 },
  { asin: 'B0EM3ABC2B3', name: 'LED Desk Lamp',     fulfillable: 95,  inbound: 50,  days: 18, risk: '偏低',   riskColor: 'orange', daily: 15 },
  { asin: 'B0FN4DEF3C4', name: 'BT Speaker Mini',   fulfillable: 28,  inbound: 0,   days: 12, risk: '断货预警', riskColor: 'red',    daily: 11 },
  { asin: 'B0GH5GHI4D5', name: 'Kitchen Scale Pro', fulfillable: 15,  inbound: 300, days: 8,  risk: '断货预警', riskColor: 'red',    daily: 5 },
]
export const INVENTORY_LEVEL = [
  { asin: 'B0CF9X1K2M4', name: 'Smart Plug',   level: 420 },
  { asin: 'B0DL7XYZ1A2', name: 'USB-C Hub',    level: 280 },
  { asin: 'B0EM3ABC2B3', name: 'LED Lamp',     level: 95 },
  { asin: 'B0FN4DEF3C4', name: 'BT Speaker',   level: 28 },
  { asin: 'B0GH5GHI4D5', name: 'Kitchen Scale', level: 15 },
]

// 利润：按 ASIN 拆明细（近 30 天）
export const PROFIT_DETAIL = [
  { asin: 'B0CF9X1K2M4', name: 'Smart Plug WiFi',   units: 3960, rev: 79160, adShare: 0.16, adSpend: 12666 },
  { asin: 'B0DL7XYZ1A2', name: 'USB-C Hub 7-in-1',  units: 1920, rev: 76781, adShare: 0.18, adSpend: 13820 },
  { asin: 'B0EM3ABC2B3', name: 'LED Desk Lamp',     units: 1540, rev: 38485, adShare: 0.12, adSpend: 4618 },
  { asin: 'B0FN4DEF3C4', name: 'BT Speaker Mini',   units: 1040, rev: 22870, adShare: 0.14, adSpend: 3202 },
  { asin: 'B0GH5GHI4D5', name: 'Kitchen Scale Pro', units: 460,  rev: 12875, adShare: 0.08, adSpend: 1030 },
]
// 成本结构（近 30 天全店占比）
export const COST_STRUCTURE = [
  { name: '采购成本',   value: 68890, color: '#5b8ff9' },
  { name: '平台佣金',   value: 34376, color: '#5ad8a6' },
  { name: 'FBA 费用',   value: 14308, color: '#f6bd16' },
  { name: '广告花费',   value: 35336, color: '#e8684a' },
  { name: '仓储/退货',  value: 9420,  color: '#9270ca' },
  { name: '净利润',     value: 49290, color: '#269a99' },
]
export const TOTAL_MONTH_REV = 231171
export const NET_MONTH = 49290

// 广告整体指标
export const AD_OVERALL = {
  spend: 13690, sales: 47556, acos: 28.8, roas: 3.47,
  imp: 2130000, clicks: 18240, cvr: 6.9, cpc: 0.75,
}

// 流量占比（自然 / 广告 / 关联）
export const TRAFFIC_MIX = [
  { name: '自然流量', value: 58.2, color: '#5b8ff9', valueText: '58.2%' },
  { name: '广告流量', value: 31.4, color: '#f6bd16', valueText: '31.4%' },
  { name: '关联/其它', value: 10.4, color: '#5ad8a6', valueText: '10.4%' },
]

export default {
  REVIEW_ASINS, DAILY_SALES, DAY_7, DAY_30, MONTH_DAILY_REVENUE, WEEK_GMV,
  AD_TREND_7, AD_TYPE, AD_GROUPS, KEYWORDS_GOOD, KEYWORDS_BURN, AD_OVERALL, TRAFFIC_MIX,
  PRODUCT_PERF, TOP_ASIN_TREND, REVIEW_CHANGES,
  INVENTORY, INVENTORY_LEVEL, PROFIT_DETAIL, COST_STRUCTURE, TOTAL_MONTH_REV,
}

// ====== AI 一键生成：基于上方数据看板输出结构化复盘文字（mock）======
// 对应输入框上方 4 张快捷卡片；真实上线替换为后端 review-analyst Agent 生成。

const top = (n: number) => {
  const rows = Object.entries(DAILY_SALES)
    .map(([asin, arr]) => ({ asin, name: REVIEW_ASINS.find((a) => a.asin === asin)!.name, sales: arr.reduce((a, b) => a + b, 0) }))
    .sort((a, b) => b.sales - a.sales)
  return rows.slice(0, n)
}

export function buildReviewReply(intent: 'weekly' | 'monthly' | 'ad' | 'action'): { reply: string; displayType: string } {
  const gmv7 = Object.entries(DAILY_SALES).reduce((a, [asin, arr]) => a + arr.reduce((x, y) => x + y, 0) * REVIEW_ASINS.find((s) => s.asin === asin)!.price, 0)
  const orders7 = Object.values(DAILY_SALES).reduce((a, arr) => a + arr.reduce((x, y) => x + y, 0), 0)
  const best = top(1)[0]
  const worst = top(5)[top(5).length - 1]

  if (intent === 'weekly') {
    return {
      displayType: 'text',
      reply: `## 📄 本周运营复盘周报（近 7 天）

### 一、销售概况
- **GMV**：$${Math.round(gmv7).toLocaleString()}，环比 **+12.3%**
- **订单数**：${orders7.toLocaleString()} 单，环比 **+8.1%**
- 客单价稳定，毛利率 **${(28.4).toFixed(1)}%**；流量结构：自然 58.2% / 广告 31.4%

### 二、广告表现
- 花费 $13,690，ACoS **28.8%**（>目标25%，偏高 3.8pct），ROAS 3.47
- 主因集中在 **SP·自动投放（ACoS 39.1%）** 与 **蓝牙音箱高价词** 烧钱

### 三、爆款与风险
- 爆款 **${best?.name}**（${best?.asin}）7 天 ${best?.sales} 单，BSR 已进 #12
- 拖累项 **${worst?.name}**（${worst?.asin}）销量走弱 + 差评上升，建议关注

### 四、库存健康
- 2 个 ASIN 进入 **断货预警**（BT Speaker / Kitchen Scale），Kitchen Scale 周转仅 8 天
- 滞销风险暂无，补货建议已列出

### 五、下周行动项
1. 关停/收窄 SP·自动 高 ACoS 词，平移预算到 Smart Plug 核心词
2. Kitchen Scale 断货前补货 300 件已入在途，盯紧到货
3. 为本周差评（续航/计量不准）启动 QA + 邮件安抚`,
    }
  }

  if (intent === 'monthly') {
    return {
      displayType: 'text',
      reply: `## 📅 月度复盘报告（近 30 天）

### 一、业绩总览
- **月 GMV**：$${Math.round(TOTAL_MONTH_REV).toLocaleString()}，目标完成率 **92.4%**
- 月订单 **8,920**，环比 +11.0%；净利润 **$${Math.round(NET_MONTH).toLocaleString()}**（净利率 21.3%）

### 二、趋势与结构
- 4 个自然周 GMV 逐周爬坡（$33.7k → $39.9k），周促销带来明显波峰
- 流量结构稳定，广告占比 31.4% 略高，依赖程度需压降

### 三、SKU 排名
1. **Smart Plug WiFi** 贡献最高（毛利占比 >40%）
2. USB-C Hub 次之、稳定在健康区间
3. Kitchen Scale Pro 滞销风险 + 广告空转，建议本月清库存或改主图

### 四、下月策略
- 把广告预算向 **ROAS>4 的 campaign**（SP 手动-核心词/SD 再营销）倾斜
- 促销节奏前置到月初，减少月末积压
- 对高退货 ASIN 先做质检再复推`,
    }
  }

  if (intent === 'ad') {
    return {
      displayType: 'text',
      reply: `## 📈 广告优化方案

### 一、整体诊断
花费 $13,690 / ACoS **28.8%** / ROAS 3.47。ACoS 超 25% 目标线 3.8pct，**约 2,100 刀花在无效词上**。

### 二、Campaign 评级
| 评级 | Campaign | ACoS | 处置 |
|---|---|---|---|
| S | SP·手动-核心词 | 24.2% | 扩量 +10% |
| S | SD·再营销 | 28.5% | 维持 |
| B | SP·手动-长尾词 | 30.4% | 否词优化 |
| C | SP·自动投放 | 39.1% | 砍 40% 预算 |
| C | SB·品牌 | 30.2% | 维持观察 |

### 三、调价建议
- **降价**：SP 手动-核心词出价 +8%~+12%（词好、可吃更多曝光）
- **关停/降价**：SP·自动 高 ACoS 长尾词（如 bluetooth speaker ACoS 62%）

### 四、待否词清单
- \`bluetooth speaker\`（$3,528 / ACoS 62.4%）
- \`smart plug\`（$1,876 / ACoS 51.3%）
- \`led desk lamp\`（$825 / ACoS 47.8%）

### 五、预期
执行后整体 ACoS 可回落至 **~24%**，ROAS 提升至 **4.0+**。`,
    }
  }

  return {
    displayType: 'text',
    reply: `## 🎯 下周行动计划（按优先级）

### 🔴 止损项（24h 内）
1. **广告**：关停 SP·自动高 ACoS 词，预算平移到 Smart Plug 核心词（预期 ACoS 降 4pct）
2. **库存**：Kitchen Scale 断货前锁定在途 300 件到货节点
3. **口碑**：对本周 2 条差评（续航/计量不准）回复 + 发起 QA

### 🟡 优化项（本周内）
4. 主图 A/B：Kitchen Scale 换场景图看转化
5. USB-C Hub 补 5 个长尾关键词进手动组
6. 调整 SB 品牌预算分配（当前转化一般）

### 🟢 机会点（本月规划）
7. Smart Plug 关联新色上架
8. 把 ACoS<25% 的词批量拉进“精确”扩大曝光
9. 大促前排期与促销日历

> 每项均含负责人与截止时间（详见对话上方行动清单卡片）。`,
    }
  }
