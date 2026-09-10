/**
 * 平台规则库状态管理
 *
 * 管理各跨境电商平台（Amazon / Shopee / TikTok Shop / TEMU 等）的运营规则、
 * 政策条款、合规要求。支持按平台筛选、搜索、分类。
 * 数据源：mock 预置（后续可接后端 PG）。
 */

import { defineStore } from 'pinia'
import { ref, computed } from 'vue'

// ====== 类型定义 ======

export interface PlatformRule {
  id: string
  platform: string          // 平台标识：amazon / shopee / tiktok / temu / lazada ...
  category: string          // 规则分类：listing / policy / compliance / payment / logistics / review / ad
  title: string             // 规则标题
  content: string           // 规则正文
  effective_date: string    // 生效日期（YYYY-MM-DD）
  expiry_date?: string      // 失效日期（YYYY-MM-DD），空=永不过期
  /** 状态：auto=根据日期自动计算，active/upcoming/expired=手动覆盖 */
  status: 'auto' | 'active' | 'upcoming' | 'expired'
  tags: string[]
  source?: string           // 来源链接（外部 URL）
  source_doc_id?: string    // 关联的来源文档 ID（本地文档库）
  created_at: string
  updated_at: string
}

/** 平台规则文档素材（RAG 补充资料） */
export interface PlatformRuleDoc {
  id: string
  platform: string
  filename: string
  file_type: 'pdf' | 'md' | 'excel' | 'txt' | 'other'
  size: number              // bytes
  uploaded_at: string
  description: string
  /** 文档正文内容（上传时提取 / 用户粘贴；PDF 为 OCR/文本抽取结果） */
  content?: string
}

// ====== AI 拆分去重 ======

/** 去重状态 */
export type DupStatus = 'new' | 'duplicate' | 'update'

/** AI 拆分待确认规则（带去重标注） */
export interface PendingRuleWithDup extends Omit<PlatformRule, 'id' | 'created_at' | 'updated_at'> {
  _dupStatus: DupStatus
  _matchedRuleId?: string    /** 命中的已有规则 ID（duplicate/update 时有值） */
  _similarityScore?: number   /** 相似度分数 0-1 */
  _diffSummary?: string       /** 差异摘要（update 时：如 "字符限制从200→150"）*/
}

/** 去重配置 */
const DUP_CONFIG = {
  /** 关键词重叠率阈值（> 此值视为疑似重复） */
  keywordOverlapThreshold: 0.55,
  /** 高相似度阈值（> 此值直接判定为 duplicate） */
  highSimilarityThreshold: 0.75,
  /** 版本更新检测：同平台+同分类+标题相似，但 content 中数值/日期不同 */
  numericDiffPattern: /(\d+)\s*[-–—~～]\s*(\d+)/g,
} as const

// ====== 平台配置 ======

export const PLATFORMS: { key: string; label: string; icon: string; color: string }[] = [
  { key: 'amazon', label: 'Amazon', icon: '📦', color: '#ff9900' },
  { key: 'shopee', label: 'Shopee', icon: '🛍️', color: '#ee4d2d' },
  { key: 'tiktok', label: 'TikTok Shop', icon: '🎵', color: '#000000' },
  { key: 'temu', label: 'TEMU', icon: '🧺', color: '#fb7701' },
  { key: 'lazada', label: 'Lazada', icon: '🌏', color: '#0f146d' },
]

// ====== 规则分类 ======

export const RULE_CATEGORIES: { key: string; label: string; icon: string }[] = [
  { key: 'listing', label: 'Listing 规则', icon: '📝' },
  { key: 'policy', label: '平台政策', icon: '⚖️' },
  { key: 'compliance', label: '合规要求', icon: '🛡️' },
  { key: 'payment', label: '支付结算', icon: '💳' },
  { key: 'logistics', label: '物流仓储', icon: '🚚' },
  { key: 'review', label: '评价管理', icon: '⭐' },
  { key: 'ad', label: '广告投放', icon: '📢' },
]

// ====== 状态自动计算引擎 ======

/**
 * 根据生效日期 + 失效日期 自动判定规则状态
 *
 * 判定逻辑：
 *   effective_date > 今天 → upcoming（即将生效）
 *   effective_date <= 今天 && (expiry_date 为空 || expiry_date > 今天) → active（生效中）
 *   expiry_date <= 今天 → expired（已失效）
 */
export function computeStatus(
  effectiveDate: string,
  expiryDate?: string,
): 'active' | 'upcoming' | 'expired' {
  const today = new Date()
  today.setHours(0, 0, 0, 0)
  const eff = new Date(effectiveDate + 'T00:00:00')
  const exp = expiryDate ? new Date(expiryDate + 'T00:00:00') : null

  if (eff > today) return 'upcoming'
  if (exp && exp <= today) return 'expired'
  return 'active'
}

/** 获取规则的实际显示状态（手动覆盖优先，否则自动计算） */
export function getResolvedStatus(rule: PlatformRule): 'active' | 'upcoming' | 'expired' {
  if (rule.status !== 'auto') return rule.status
  return computeStatus(rule.effective_date, rule.expiry_date)
}

// ====== Mock 数据 ======

const MOCK_RULES: PlatformRule[] = [
  {
    id: 'rule-001',
    platform: 'amazon',
    category: 'listing',
    title: '商品标题字符数限制（2026 更新）',
    content: 'Amazon 商品标题最多 200 字符，部分类目（如服饰鞋包）建议控制在 80 字符以内。禁止包含促销信息（如"best sale"、"free shipping"）、主观夸大词、特殊符号。标题格式建议：品牌 + 型号 + 核心卖点 + 规格 + 颜色。',
    effective_date: '2026-01-15',
    status: 'auto',
    tags: ['标题', '字符限制', 'Listing'],
    source: 'https://sellercentral.amazon.com',
    source_doc_id: 'doc-amazon-listing-2026',
    created_at: '2026-01-10T00:00:00Z',
    updated_at: '2026-01-10T00:00:00Z',
  },
  {
    id: 'rule-002',
    platform: 'amazon',
    category: 'compliance',
    title: '亚马逊合规要求：电子产品 FCC 认证',
    content: '所有无线电子设备（含蓝牙/WiFi）需提供 FCC 认证编号，否则将被下架或限制销售。需在 Listing 图片或描述中展示 FCC ID。新品上架前务必确认合规文档齐全。',
    effective_date: '2025-07-01',
    status: 'auto',
    tags: ['FCC', '合规', '电子产品'],
    source_doc_id: 'doc-amazon-compliance-2025',
    created_at: '2025-06-20T00:00:00Z',
    updated_at: '2025-06-20T00:00:00Z',
  },
  {
    id: 'rule-003',
    platform: 'shopee',
    category: 'logistics',
    title: 'Shopee 跨境物流时效与超时赔付',
    content: 'SLS 标准物流承诺时效：东南亚 5-15 天。若超过承诺时效 3 天未妥投，买家可申请退款，卖家承担运费。建议使用 SLS 官方仓或海外仓降低时效风险。',
    effective_date: '2025-10-01',
    expiry_date: '2026-06-30',
    status: 'auto',
    tags: ['物流', 'SLS', '时效'],
    source_doc_id: 'doc-shopee-logistics-2025',
    created_at: '2025-09-15T00:00:00Z',
    updated_at: '2025-09-15T00:00:00Z',
  },
  {
    id: 'rule-004',
    platform: 'tiktok',
    category: 'ad',
    title: 'TikTok Shop 广告素材审核规范',
    content: '广告素材禁止使用虚假夸大宣传、前后对比夸张效果、未授权明星/网红肖像。视频需包含真实产品展示，禁止纯文字堆砌。违规将被限流或封禁广告账户。',
    effective_date: '2026-10-01',
    status: 'auto',
    tags: ['广告', '素材审核', 'TikTok'],
    source_doc_id: 'doc-tiktok-ad-2026',
    created_at: '2026-01-25T00:00:00Z',
    updated_at: '2026-01-25T00:00:00Z',
  },
  {
    id: 'rule-005',
    platform: 'temu',
    category: 'policy',
    title: 'TEMU 半托管模式佣金与结算规则',
    content: '半托管模式下平台佣金率 8%-15%（按类目），结算周期 T+15。卖家需自行负责海外仓储与尾程物流。注意：低价引流品佣金优惠期有限，需关注类目政策变动。',
    effective_date: '2025-12-01',
    status: 'auto',
    tags: ['佣金', '结算', '半托管'],
    source_doc_id: 'doc-temu-policy-2025',
    created_at: '2025-11-20T00:00:00Z',
    updated_at: '2025-11-20T00:00:00Z',
  },
  {
    id: 'rule-006',
    platform: 'amazon',
    category: 'review',
    title: '亚马逊评价政策：禁止刷单与诱导好评（旧版）',
    content: '严禁通过折扣、返现、礼品等方式诱导买家留好评（包括第三方刷单服务）。违反将导致账号冻结、Listing 下架甚至永久封店。允许通过合规的"早期评论者计划"获取评价。',
    effective_date: '2024-06-01',
    expiry_date: '2025-12-31',
    status: 'expired',  // 手动标记为已失效（已被新政策替代）
    tags: ['评价', '刷单', '合规', '已作废'],
    source_doc_id: 'doc-amazon-compliance-2025',
    created_at: '2024-05-15T00:00:00Z',
    updated_at: '2025-12-31T00:00:00Z',
  },
]

// ====== Store ======

/** 预置文档数据（与 MOCK_RULES 的 source_doc_id 对应） */
const MOCK_DOCS: PlatformRuleDoc[] = [
  {
    id: 'doc-amazon-listing-2026',
    platform: 'amazon',
    filename: 'Amazon_Listing_Guidelines_2026.pdf',
    file_type: 'pdf',
    size: 2457600,
    uploaded_at: '2026-01-10T00:00:00Z',
    description: 'Amazon 2026 Listing 完整规范（标题/图片/描述/搜索词）',
    content: `Amazon Listing Guidelines — 2026 Edition

1. TITLE REQUIREMENTS (商品标题规范)

1.1 Character Limits
- Maximum length: 200 characters
- Recommended length for Apparel/Shoes/Bags categories: 80 characters or fewer
- Each word in the title must contribute to search relevance

1.2 Prohibited Content in Titles
The following are NOT allowed in product titles:
- Promotional phrases such as "best seller", "free shipping", "100% quality", "guaranteed"
- Subjective claims like "amazing", "high quality" (unless part of registered brand name)
- Price or quantity information (e.g., "2-pack", "$9.99")
- Special characters: !, ?, *, ~, etc.
- All CAPS words (except brand acronyms)

1.3 Title Format Guidelines
Recommended structure:
[Brand Name] + [Model/Series] + [Core Feature] + [Specification] + [Color/Size]

Examples:
✓ "Sony WH-1000XM5 Wireless Noise Cancelling Headphones - Black"
✓ "Anker PowerCore 26800mAh Portable Charger, High-Capacity External Battery Pack"
✗ "BEST SELLER!!! Premium Quality Amazing Bluetooth Headphones Black FREE SHIPPING"

2. IMAGE REQUIREMENTS (图片要求)

2.1 Main Image (主图)
- Must be a professional product photograph on pure white background (RGB 255,255,255)
- Minimum resolution: 1000 x 1000 pixels for zoom capability
- Product must occupy ≥85% of the image frame
- No text, logos, watermarks, or borders on main image
- No accessories shown unless they are included with the product

2.2 Secondary Images (附图)
- Up to 8 additional images allowed
- Show product from multiple angles, in use, lifestyle context, and detail shots
- Infographics showing dimensions, features, and comparisons are permitted
- Text on secondary images should be minimal and informative only

3. PRODUCT DESCRIPTION (商品描述)

3.1 Key Product Features (五点描述)
- Exactly 5 bullet points required
- Each bullet point: max 500 characters
- Start each bullet with CAPITAL LETTER (no lowercase start)
- Focus on product benefits, not just features
- Include key search terms naturally

3.2 Product Description (长描述)
- HTML formatting supported (<b>, <br>, <p> tags)
- Max 2000 characters recommended
- Use clear paragraphs with headers
- Include care instructions, warranty info where applicable

4. SEARCH TERMS (后台搜索词)
- Backend search terms field (not visible to customers)
- Limit: 249 bytes total
- Do NOT repeat words already in title
- Use generic descriptive terms, not brand names
- Separate terms by spaces (commas not needed)

5. CATEGORY-SPECIFIC RULES
5.1 Electronics: Must display FCC/CE certification info if applicable
5.2 Food/Supplements: Must include ingredients, allergen warnings, nutrition facts
5.3 Beauty Products: Full ingredient list required; no unverified medical claims
5.4 Toys: Age appropriatement labeling mandatory; safety compliance docs required
5.5 Dietary Supplements: Cannot make disease treatment claims per FDA guidelines

6. ENFORCEMENT & PENALTIES
- First violation: Listing suppressed, warning issued
- Repeated violations: Account health score degradation
- Severe/pattern violations: ASIN suspension or account deactivation

Document Version: 2026.01 | Last Updated: 2026-01-10 | Source: Seller Central`,
  },
  {
    id: 'doc-amazon-compliance-2025',
    platform: 'amazon',
    filename: 'Amazon_Compliance_Policies_2025.pdf',
    file_type: 'pdf',
    size: 5242880,
    uploaded_at: '2025-06-20T00:00:00Z',
    description: '亚马逊合规政策全集：认证要求、禁售品、知识产权',
    content: `Amazon Compliance Policies — Complete Reference (2025)

SECTION A: PRODUCT CERTIFICATION REQUIREMENTS

A.1 Electronic Devices (电子产品认证)
All electronic products sold on Amazon MUST comply with:

| Certification | Applicable Region | Required For |
|--------------|-------------------|-------------|
| FCC ID | USA market | All wireless devices (Bluetooth, WiFi, cellular) |
| CE Marking | EU market | All electronic products sold to EU |
| RoHS Directive | EU market | Products containing restricted substances |
| UL/ETL Listing | USA market | Plug-in electrical devices |
| FDA Registration | Global | Medical devices, food contact products |

A.2 How to Submit Certifications
1. Navigate to Seller Central → Catalog → Manage Your Compliance
2. Upload documentation for each applicable ASIN
3. Documents accepted: PDF, JPG, PNG (max 10MB each)
4. Processing time: 3-5 business days
5. Expired certifications will trigger listing suppression

A.3 Consequences of Non-Compliance
- Day 1-7: Warning email + listing suppression option
- Day 8-30: Mandatory listing suppression until compliant
- Day 30+: Account review possible; repeated offenses = account suspension

SECTION B: PROHIBITED PRODUCTS (禁售品清单)

B.1 Absolutely Prohibited (永久禁售)
- Counterfeit products of any kind
- Illegal drugs and controlled substances
- Weapons (firearms, ammunition, certain knives)
- Stolen property
- Products promoting hate speech, violence, or discrimination
- Endangered species products (CITES protected)
- Human remains/body parts

B.2 Restricted (需审批/特殊许可)
- Dietary supplements (require proper labeling, no disease claims)
- Cosmetics (must list all ingredients, no false advertising)
- Batteries (lithium batteries require UN38.3 testing + proper packaging)
- GPS jammers / signal blockers (illegal in most jurisdictions)
- Lock-picking devices (age-gated in many markets)

B.3 Condition-Specific Restrictions
- Used products: Must be accurately described as used/refurbished
- Hazardous materials: Require SDS (Safety Data Sheet) submission
- Food products: Must have proper expiration date labeling

SECTION C: INTELLECTUAL PROPERTY (知识产权)

C.1 Trademark Infringement
Using another company's registered trademark without permission constitutes infringement, including:
- Using trademark in product title/description
- Using similar-sounding brand names (passing off)
- Selling counterfeit versions of branded products

C.2 Copyright Infringement
- Copying product images from other sellers without permission
- Using copyrighted text descriptions
- Selling unauthorized replicas of copyrighted designs

C.3 Patent Infringement
- Selling products that infringe utility/design patents
- Neutral evaluation process available through Amazon Patent Evaluation Express

C.4 Reporting IP Violations
Rights owners can report via Amazon Brand Registry or Brand Protection
- Average response time: 24-48 hours
- Evidence required: registration numbers, test buy results, side-by-side comparisons

SECTION D: REVIEW MANIPULATION POLICY (评价政策)

D.1 What is PROHIBITED (严禁行为):
- Offering refunds/discounts/gifts in exchange for positive reviews
- Using third-party services to generate fake reviews
- Asking friends/family to leave reviews
- Creating multiple buyer accounts to review own products
- Manipulating review ranking/suppression

D.2 What IS ALLOWED (合规方式):
- Amazon Vine program (invited trusted reviewers)
- Early Reviewer Program (for new ASINs < 1 year old)
- Request a Review button (one per order, Amazon-generated timing)
- Including unbiased product insert cards (NO incentive language)

D.3 Penalties for Review Manipulation
- Detected manipulation: immediate review suppression
- Pattern behavior: ASIN review privileges revoked
- Severe cases: permanent account suspension + legal action

SECTION E: ACCOUNT HEALTH METRICS (账户健康指标)

E.1 Key Metrics Thresholds
| Metric | Healthy Target | Warning Zone | Critical |
|--------|---------------|-------------|----------|
| Order Defect Rate (ODR) | < 1% | 1% - 2% | > 2% |
| Late Shipment Rate | < 4% | 4% - 6% | > 6% |
| Valid Tracking Rate | > 95% | 90-95% | < 90% |
| Return Dissatisfaction Rate | < 2.5% | 2.5-4% | > 4% |

E.2 Account Health Score
- Scale: 0-1000 (higher = better)
- Below 200: Risk of deactivation
- Below 100: Immediate action required

Document Version: 2025.06 | Last Updated: 2025-06-20 | Source: Amazon Seller Policies`,
  },
  {
    id: 'doc-shopee-logistics-2025',
    platform: 'shopee',
    filename: 'Shopee_SLS_Logistics_Policy_2025.pdf',
    file_type: 'pdf',
    size: 1572864,
    uploaded_at: '2025-09-15T00:00:00Z',
    description: 'Shopee 跨境物流 SLS 时效、赔付、海外仓规范',
    content: `Shopee Logistics Service (SLS) Policy — Cross-Border Operations (2025)

1. SLS SERVICE OVERVIEW (服务概述)

Shopee Logistics Service (SLS) is the official cross-border logistics solution connecting sellers to buyers across Southeast Asia.

Supported Markets:
- Singapore (SG), Malaysia (MY), Philippines (PH), Vietnam (VN)
- Thailand (TH), Indonesia (ID), Brazil (BR), Mexico (MX)

2. SHIPPING TIME STANDARDS (时效标准)

2.1 Standard SLS Delivery Timeframes
| Destination | Standard Delivery | First Mile Pickup |
|------------|------------------|-------------------|
| Singapore | 5-7 days | 1-2 days |
| Malaysia | 6-12 days | 1-2 days |
| Philippines | 8-15 days | 2-3 days |
| Vietnam | 8-15 days | 2-3 days |
| Thailand | 6-12 days | 1-2 days |
| Indonesia | 8-18 days | 2-3 days |

2.2 Late Delivery Compensation (超时赔付)
If delivery exceeds promised time by MORE than 3 business days:
- Buyer can request full refund at NO cost to buyer
- Seller bears the return shipping cost (if any)
- Seller's late delivery rate metric increases (affects shop rating)

2.3 First Mile Collection (揽收规则)
- Seller prepares package → SLS courier pickup OR self-drop at designated point
- Pickup window: 09:00-20:00 local time
- Package must be ready before pickup time slot
- Maximum weight per package: depends on destination (typically ≤30kg)

3. PACKAGING REQUIREMENTS (包装要求)

3.1 General Rules
- Use sturdy corrugated boxes (no damaged/reused boxes)
- Internal cushioning required for fragile items
- No excessive packaging (environmental policy)
- Shipping label affixed flat on largest surface

3.2 Prohibited Packaging Materials
- Newspaper (ink may stain products)
- Loose fill peanuts (not eco-friendly in some markets)
- Used/recycled bags that may have odors

3.3 Label Requirements
- Shopee-provided SLS label MANDATORY
- Barcode must be scannable (no creases/folds over barcode)
- Invoice/packing list inside package (customs requirement)

4. OVERSEAS WAREHOUSE (海外仓)

4.1 Shopee Warehouse Options
- Local Fulfillment Warehouse (LFW): Store inventory locally in destination country
- Benefits: Faster delivery (1-3 days), lower shipping costs, better buyer experience
- Eligibility: Shop rating ≥ 4.5, on-time shipment rate ≥ 90%

4.2 Inventory Management
- Real-time stock sync via API
- Low-stock alerts when inventory falls below 7-day sales volume
- Shelf-life tracking for perishables

5. PROHIBITED ITEMS FOR SHIPMENT (物流禁运品)

5.1 Not Accepted by SLS
- Lithium batteries (use specialized channel)
- Liquids > 500ml per item
- Compressed gases/aerosols
- Magnetic materials affecting aviation safety
- Currency, precious metals, securities
- Live animals and plants
- Items requiring cold chain (perishable foods)

5.2 Special Handling Categories
- Cosmetics: MSDS required for liquids
- Powders: Non-hazardous certificate needed
- Textiles: Fumigation cert for some destinations

6. DISPUTE & CLAIM PROCESS (纠纷处理)

6.1 Lost Package Claims
- File claim within 7 days of expected delivery
- Proof of handover to SLS required
- Compensation: Actual product value (max claim limit varies by tier)

6.2 Damaged Package Claims
- Photo evidence required (package + product damage)
- File within 48 hours of delivery
- SLS investigation: 5-10 business days

Document Version: 2025.Q3 | Source: Shopee Seller Center`,
  },
  {
    id: 'doc-tiktok-ad-2026',
    platform: 'tiktok',
    filename: 'TikTok_Shop_Ad_Policy_2026.pdf',
    file_type: 'pdf',
    size: 3145728,
    uploaded_at: '2026-01-25T00:00:00Z',
    description: 'TikTok Shop 广告素材审核规范与违规处罚细则',
    content: `TikTok Shop Advertising Content Policy — 2026 Update

1. ADVERTISING CONTENT STANDARDS (广告内容标准)

1.1 Core Principles
All advertising content on TikTok Shop MUST be:
- TRUTHFUL: No false or misleading claims about product performance
- AUTHENTIC: Show real product, real usage scenarios
- SAFE: No dangerous activities or prohibited content
- RESPECTFUL: No discrimination, harassment, or inappropriate content

1.2 Video Ad Requirements
- Minimum duration: 6 seconds | Maximum: 180 seconds
- Product must appear within first 3 seconds
- Audio must be clear and synchronized with video
- Text overlays must remain on screen long enough to read (≥2 seconds)

2. PROHIBITED CONTENT IN ADS (广告禁止内容)

2.1 Misleading Claims (虚假宣传)
❌ Before/after exaggeration (extreme photo editing)
❌ Unrealistic results ("lose 10kg in 3 days")
❌ False scarcity ("only 2 left!" when not true)
❌ Fake endorsements (paid actors as "real users")
❌ Comparative bashing competitors by name

2.2 Visual Deception (视觉欺骗)
❌ Showing wrong product in ad vs what's actually sold
❌ Using stock photos without disclosure
❌ Excessive filters that misrepresent product appearance
❌ CGI/rendered images presented as real photos

2.3 Unauthorized Content (未授权内容)
❌ Celebrity/influencer likeness without written consent
❌ Music without commercial license
❌ Branded content from other platforms' exclusive creators
❌ User Generated Content (UGC) reposted without permission

2.4 Prohibited Categories (禁止品类)
- Tobacco, e-cigarettes, vaping products
- Alcohol (varies by region)
- Weapons and dangerous items
- Adult content and suggestive material
- Gambling and betting services
- Cryptocurrency investment schemes
- Unregulated health supplements making medical claims

3. CREATIVE GUIDELINES BY FORMAT (各格式创意指南)

3.1 In-Feed Ads (信息流广告)
- Aspect ratio: 9:16 (vertical) or 1:1 (square)
- Resolution: min 720p, recommended 1080p
- Duration: 5-60 seconds optimal
- Hook (first 3 seconds): Critical for engagement

3.2 Spark Ads (原生广告)
- Must use organic TikTok content style
- Branded content disclosure REQUIRED
- No overly polished "TV commercial" feel
- Encourage comments and engagement

3.3 Collection Ads (Collection 广告)
- Product card image: white background, high quality
- Price must match actual selling price (±5% tolerance)
- Stock availability must be accurate in real-time

4. REVIEW & APPROVAL PROCESS (审核流程)

4.1 Automated Pre-Check (AI 初审)
- Submitted ads scanned by AI within minutes
- Common rejections: prohibited keywords, low quality, policy violations
- Resolution: Edit and resubmit

4.2 Human Review (人工复审)
- Triggered for: new advertisers, flagged content, high-spend campaigns
- Turnaround: 24-48 hours
- Feedback provided for rejected ads

5. PENALTY FRAMEWORK (处罚框架)

5.1 First Violation
- Ad disapproval with explanation
- Warning notification to advertiser account
- No financial penalty

5.2 Repeated Violations (within 30 days)
- Ad account spending limit reduction
- Temporary ad creation suspension (3-7 days)
- Mandatory advertising policy training

5.3 Severe/Persistent Violations
- Permanent ad account ban
- Associated TikTok Shop account review
- Legal action for fraudulent advertising practices

5.4 Appeal Process
- Submit appeal within 15 days of penalty
- Provide corrective evidence
- Second-level review by senior moderation team

Document Version: 2026.Q1 | Source: TikTok Shop Ads Help Center`,
  },
  {
    id: 'doc-temu-policy-2025',
    platform: 'temu',
    filename: 'TEMU_Semi_Managed_Policy_2025.pdf',
    file_type: 'pdf',
    size: 2097152,
    uploaded_at: '2025-11-20T00:00:00Z',
    description: 'TEMU 半托管模式佣金、结算、物流政策说明',
    content: `TEMU Semi-Managed Mode Policy Guide — November 2025

1. SEMI-MANAGED MODE OVERVIEW (半托管模式概述)

TEMU's Semi-Managed mode allows sellers to manage their own overseas warehousing and last-mile delivery while leveraging TEMU's traffic and customer service infrastructure.

Key Differences from Full-Managed:
| Aspect | Full-Managed | Semi-Managed |
|--------|-------------|--------------|
| Warehousing | TEMU warehouse | Seller-managed overseas warehouse |
| Last-mile delivery | TEMU handles | Seller arranges |
| Pricing | TEMU sets final price | Seller suggests, TEMU approves |
| Customer service | TEMU fully handles | Shared responsibility |
| Commission | Higher base | Lower base (reward for logistics capability) |

2. COMMISSION STRUCTURE (佣金结构)

2.1 Base Commission Rates (by Category)
| Category | Commission Rate | Notes |
|----------|----------------|-------|
| Electronics | 12-15% | High-value items |
| Fashion/Apparel | 10-13% | Volume-based discounts available |
| Home & Garden | 8-11% | Bulky items surcharge may apply |
| Beauty & Health | 10-14% | Cosmetic regulations vary by market |
| Sports & Outdoors | 9-12% | Equipment category specific |
| General Merchandise | 8-10% | Default rate |

2.2 Additional Fees
- Payment processing fee: 1.5% per transaction
- Return handling fee: $2-5 per returned item (category dependent)
- Overseas warehouse storage fee: $0.15-0.40/cubic foot/day
- Long-tail storage fee (>90 days): 3x standard rate

2.3 Settlement Cycle
- Standard settlement: T+15 (15 days after order delivery)
- Fast-track settlement: T+7 (requires premium seller status, 0.5% fee)
- Minimum payout threshold: $20 USD
- Payment methods: Payoneer / PingPong / Wire Transfer

3. LOGISTICS REQUIREMENTS (物流要求)

3.1 Overseas Warehouse Standards
- Location: Must be in target market country (US/EU/etc.)
- Processing SLA: Order shipped within 24 hours of receipt
- Tracking integration: Real-time tracking API connection required
- Accuracy: Pick error rate < 0.5%

3.2 Last-Mile Delivery Partners
- Approved carriers list maintained by TEMU
- Sellers must use approved carriers for TEMU orders
- Delivery SLA: Domestic delivery within 3-5 days
- On-time delivery rate target: ≥ 95%

3.3 Quality Control (入仓质检)
- Random inspection rate: 5-15% of shipments
- Inspection criteria: Packaging integrity, correct SKU, no damage
- Non-compliant items: Returned at seller expense or disposed
- Dispute process: 48-hour response window for QC appeals

4. PRICING RULES (定价规则)

4.1 Price Setting
- Seller submits suggested retail price (SRP)
- TEMU reviews and sets final selling price (may adjust ±20%)
- Price changes require 48-hour advance notice
- Flash sale prices cannot exceed 30% discount from regular price

4.2 Price Floor Protection
- TEMU guarantees minimum margin for sellers
- If market price drops below cost floor, TEMU absorbs difference (limited)
- Price protection period: 30 days from listing approval

5. LOW-PRICE INCENTIVE PROGRAM (低价引流政策)

5.1 Current Promotion (Q4 2025)
- New listings under $10: 50% commission reduction for first 60 days
- Bestseller items: Volume-based commission rebates
- Program ends: December 31, 2025 (subject to extension)

5.2 Eligibility
- Seller rating ≥ 4.5 stars
- On-time delivery rate ≥ 98%
- Return rate ≤ 5%
- No active policy violations

6. PERFORMANCE METRICS & CONSEQUENCES (绩效指标)

6.1 KPI Dashboard Metrics
| Metric | Target | Warning | Penalty |
|--------|--------|---------|---------|
| Order fulfillment rate | ≥ 98% | 95-98% | < 95% |
| On-time shipping | ≥ 96% | 93-96% | < 93% |
| Return rate | ≤ 5% | 5-8% | > 8% |
| Customer complaint rate | ≤ 1% | 1-2% | > 2% |
| QC pass rate | ≥ 97% | 94-97% | < 94% |

6.2 Consequence Ladder
Level 1 (Warning): Performance improvement plan required
Level 2 (Restriction): New listing quota reduced by 50%
Level 3 (Suspension): Semi-managed privilege suspended for 14 days
Level 4 (Termination): Permanent removal from program

Document Version: 2025.11 | Source: TEMU Seller Portal`,
  },
]

export const usePlatformRulesStore = defineStore('platformRules', () => {
  const items = ref<PlatformRule[]>([])
  const docs = ref<PlatformRuleDoc[]>([...MOCK_DOCS])
  const isLoading = ref(false)

  // 过滤状态（初始 undefined，避免 a-select allow-clear 清空后被误判）
  const searchQuery = ref('')
  const filterPlatform = ref<string | undefined>(undefined)
  const filterCategory = ref<string | undefined>(undefined)
  const filterStatus = ref<string | undefined>(undefined)

  // ====== Getters ======

  /** 带解析后状态的规则列表（供表格展示用） */
  const itemsWithResolvedStatus = computed(() =>
    items.value.map(item => ({
      ...item,
      _resolvedStatus: getResolvedStatus(item),
    })),
  )

  const filteredItems = computed(() => {
    let result = items.value

    if (filterPlatform.value && filterPlatform.value !== 'all') {
      result = result.filter(item => item.platform === filterPlatform.value)
    }
    if (filterCategory.value && filterCategory.value !== 'all') {
      result = result.filter(item => item.category === filterCategory.value)
    }
    if (filterStatus.value && filterStatus.value !== 'all') {
      // 按解析后的实际状态过滤（而非原始 status 字段）
      result = result.filter(item => getResolvedStatus(item) === filterStatus.value)
    }
    if (searchQuery.value.trim()) {
      const q = searchQuery.value.toLowerCase()
      result = result.filter(item =>
        item.title.toLowerCase().includes(q) ||
        item.content.toLowerCase().includes(q) ||
        item.tags.some(t => t.toLowerCase().includes(q))
      )
    }

    // 按生效日期倒序
    return [...result].sort((a, b) => b.effective_date.localeCompare(a.effective_date))
  })

  const totalCount = computed(() => items.value.length)
  const platformCount = computed(() => new Set(items.value.map(i => i.platform)).size)

  /** 按解析后状态统计各状态数量 */
  const statusCounts = computed(() => {
    const counts = { active: 0, upcoming: 0, expired: 0 }
    for (const item of items.value) {
      counts[getResolvedStatus(item)]++
    }
    return counts
  })

  /** 根据 ID 查找文档 */
  function getDocById(docId: string): PlatformRuleDoc | undefined {
    return docs.value.find(d => d.id === docId)
  }

  /** 当前是否启用了任何过滤条件 */
  const hasActiveFilters = computed(() =>
    Boolean(searchQuery.value.trim()) ||
    (filterPlatform.value && filterPlatform.value !== 'all') ||
    (filterCategory.value && filterCategory.value !== 'all') ||
    (filterStatus.value && filterStatus.value !== 'all')
  )

  /** 当前已应用的过滤条件数 */
  const activeFilterCount = computed(() => {
    let n = 0
    if (searchQuery.value.trim()) n++
    if (filterPlatform.value && filterPlatform.value !== 'all') n++
    if (filterCategory.value && filterCategory.value !== 'all') n++
    if (filterStatus.value && filterStatus.value !== 'all') n++
    return n
  })

  // ====== Actions ======

  async function fetchItems() {
    isLoading.value = true
    try {
      // TODO: 替换为真实 API get('/api/v1/platform-rules')
      await new Promise(resolve => setTimeout(resolve, 200))
      items.value = [...MOCK_RULES]
    } finally {
      isLoading.value = false
    }
  }

  async function addItem(data: Omit<PlatformRule, 'id' | 'created_at' | 'updated_at'>): Promise<PlatformRule> {
    const newItem: PlatformRule = {
      ...data,
      id: `rule-${Date.now()}`,
      created_at: new Date().toISOString(),
      updated_at: new Date().toISOString(),
    }
    items.value.unshift(newItem)
    return newItem
  }

  async function updateItem(id: string, data: Partial<Omit<PlatformRule, 'id' | 'created_at'>>): Promise<void> {
    const index = items.value.findIndex(i => i.id === id)
    if (index !== -1) {
      items.value[index] = { ...items.value[index], ...data, updated_at: new Date().toISOString() }
    }
  }

  async function deleteItem(id: string): Promise<void> {
    items.value = items.value.filter(i => i.id !== id)
  }

  function clearAllFilters() {
    searchQuery.value = ''
    filterPlatform.value = undefined
    filterCategory.value = undefined
    filterStatus.value = undefined
  }

  // ====== 文档素材 Actions ======

  /** 上传规则文档（RAG 补充素材） */
  async function uploadDoc(file: File, platform: string = 'amazon', description: string = ''): Promise<PlatformRuleDoc> {
    const ext = file.name.split('.').pop()?.toLowerCase() || 'other'
    const fileTypeMap: Record<string, PlatformRuleDoc['file_type']> = {
      pdf: 'pdf', md: 'md', txt: 'txt',
      xlsx: 'excel', xls: 'excel', csv: 'excel',
    }
    const newDoc: PlatformRuleDoc = {
      id: `doc-${Date.now()}`,
      platform,
      filename: file.name,
      file_type: fileTypeMap[ext] || 'other',
      size: file.size,
      uploaded_at: new Date().toISOString(),
      description,
    }
    docs.value.push(newDoc)
    return newDoc
  }

  /** 删除文档 */
  async function deleteDoc(docId: string): Promise<void> {
    docs.value = docs.value.filter(d => d.id !== docId)
  }

  /**
   * 批量导入规则（JSON / CSV / TXT）
   * JSON：数组，每项含 platform/category/title/content
   * CSV：platform, category, title, content
   * TXT：每行 "标题 /// 内容"
   */
  async function parseAndImport(file: File): Promise<{ success: number; failed: number; errors: string[] }> {
    const text = await file.text()
    const imported: Omit<PlatformRule, 'id' | 'created_at' | 'updated_at'>[] = []
    const errors: string[] = []
    const ext = file.name.split('.').pop()?.toLowerCase()

    const today = new Date().toISOString().slice(0, 10)

    try {
      if (ext === 'json') {
        const json = JSON.parse(text)
        const arr = Array.isArray(json) ? json : [json]
        for (const row of arr) {
          if (row.title && row.content) {
            imported.push({
              platform: row.platform || 'amazon',
              category: row.category || 'policy',
              title: String(row.title),
              content: String(row.content),
              effective_date: row.effective_date || today,
              status: row.status || 'auto',
              tags: row.tags ? (Array.isArray(row.tags) ? row.tags : [row.tags]) : [],
              source: row.source || '',
            })
          } else {
            errors.push(`缺少 title 或 content 字段: ${JSON.stringify(row).slice(0, 80)}`)
          }
        }
      } else if (ext === 'csv') {
        const lines = text.split('\n').filter(l => l.trim())
        const startIdx = lines[0].toLowerCase().includes('title') ? 1 : 0
        for (let i = startIdx; i < lines.length; i++) {
          const cols = lines[i].split(',').map(c => c.trim().replace(/^"|"$/g, ''))
          if (cols.length >= 2 && cols[0] && cols[1]) {
            imported.push({
              platform: cols[2] || 'amazon',
              category: cols[3] || 'policy',
              title: cols[0],
              content: cols[1],
              effective_date: today,
              status: 'auto',
              tags: [],
              source: '',
            })
          } else if (lines[i].trim()) {
            errors.push(`第 ${i + 1} 行格式错误`)
          }
        }
      } else if (ext === 'txt') {
        const lines = text.split('\n').filter(l => l.trim())
        for (const line of lines) {
          let title = '', content = ''
          if (line.includes('///')) {
            const parts = line.split('///')
            title = parts[0].trim()
            content = parts.slice(1).join('///').trim()
          } else if (line.includes('|')) {
            const parts = line.split('|')
            title = parts[0].trim()
            content = parts.slice(1).join('|').trim()
          }
          if (title && content) {
            imported.push({
              platform: 'amazon',
              category: 'policy',
              title,
              content,
              effective_date: today,
              status: 'auto',
              tags: [],
              source: '',
            })
          } else if (line.trim()) {
            errors.push(`无法解析: ${line.slice(0, 60)}`)
          }
        }
      } else {
        errors.push(`不支持的文件格式: .${ext}`)
      }

      for (const item of imported) {
        await addItem(item)
      }

      return { success: imported.length, failed: errors.length, errors }
    } catch (e) {
      return { success: 0, failed: 1, errors: [`文件解析失败: ${e instanceof Error ? e.message : String(e)}`] }
    }
  }

  /**
   * ====== 去重引擎（三层校验之 Layer 1 + Layer 3 共用） ======
   *
   * 对单条待入库规则与现有规则库做查重
   * 策略：
   *   1. 先按 platform + category 过滤（同平台同分类才可能重复）
   *   2. 关键词提取 + 重叠率计算（中英文分词）
   *   3. 数值/日期 diff 检测 → 判定为「版本更新」而非「重复」
   */

  /** 简易中文分词：按非词字符切分 + 过滤停用词 */
  function extractKeywords(text: string): Set<string> {
    const stopWords = new Set([
      '的', '了', '在', '是', '和', '与', '或', '等', '及', '对',
      '从', '到', '被', '把', '让', '给', '为', '以', '可', '需',
      '应', '将', '已', '此', '该', '其', '它', '之', '所', '不',
      'a', 'an', 'the', 'is', 'are', 'was', 'were', 'be', 'been',
      'to', 'of', 'in', 'for', 'on', 'with', 'at', 'by', 'from',
      'and', 'or', 'not', 'must', 'should', 'may', 'can', 'will',
      '产品', '商品', '规则', '要求', '规定', '需要', '包括', '包含',
    ])
    // 提取中文词汇（2字以上连续中文）+ 英文单词 + 数字+单位组合
    const tokens = text
      .toLowerCase()
      .replace(/[^\u4e00-\u9fa5a-z0-9%°]/g, ' ')
      .split(/\s+/)
      .filter(t => t.length >= 2 && !stopWords.has(t))
    return new Set(tokens)
  }

  /** 计算两个关键词集合的 Jaccard 相似度 */
  function jaccardSimilarity(a: Set<string>, b: Set<string>): number {
    if (a.size === 0 || b.size === 0) return 0
    let intersection = 0
    for (const word of a) {
      if (b.has(word)) intersection++
    }
    return intersection / (a.size + b.size - intersection)
  }

  /** 从文本中提取数值范围，用于版本更新检测 */
  function extractNumericPatterns(text: string): string[] {
    const matches: string[] = []
    let m: RegExpExecArray | null
    const re = /(\d+(?:\.\d+)?)\s*[%°个天小时分钟字节KBMBGB]?(?:\s*[-–—~～]\s*(\d+(?:\.\d+)?))?/g
    while ((m = re.exec(text)) !== null) {
      matches.push(m[0])
    }
    return matches
  }

  /**
   * 核心查重函数：对比一条新规则与已有规则库
   * @returns 去重状态 + 匹配到的规则信息
   */
  function checkDuplicate(
    newRule: Omit<PlatformRule, 'id' | 'created_at' | 'updated_at'>,
  ): { status: DupStatus; matchedRule?: PlatformRule; similarity: number; diffSummary?: string } {
    // 同平台 + 同分类的候选规则
    const candidates = items.value.filter(
      r => r.platform === newRule.platform && r.category === newRule.category,
    )

    if (candidates.length === 0) {
      return { status: 'new', similarity: 0 }
    }

    const newKeywords = extractKeywords(newRule.title + ' ' + newRule.content)
    let bestMatch: PlatformRule | undefined
    let bestSim = 0

    for (const candidate of candidates) {
      const candKeywords = extractKeywords(candidate.title + ' ' + candidate.content)
      const sim = jaccardSimilarity(newKeywords, candKeywords)
      if (sim > bestSim) {
        bestSim = sim
        bestMatch = candidate
      }
    }

    // 高相似度 → 检测是否为版本更新（数值/日期变化）
    if (bestSim >= DUP_CONFIG.keywordOverlapThreshold && bestMatch) {
      const newNumerics = extractNumericPatterns(newRule.content)
      const oldNumerics = extractNumericPatterns(bestMatch.content)

      // 有数值但数值不同 → 版本更新
      const hasNumericDiff =
        newNumerics.length > 0 &&
        oldNumerics.length > 0 &&
        !newNumerics.every(n => oldNumerics.includes(n))

      if (hasNumericDiff || bestSim >= DUP_CONFIG.highSimilarityThreshold) {
        if (hasNumericDiff) {
          // 找出具体差异
          const diffParts: string[] = []
          for (const nn of newNumerics) {
            if (!oldNumerics.includes(nn)) {
              diffParts.push(nn)
            }
          }
          return {
            status: 'update',
            matchedRule: bestMatch,
            similarity: bestSim,
            diffSummary: diffParts.length > 0 ? `参数变更: ${diffParts.join(', ')}` : '内容有数值/日期更新',
          }
        }
        return {
          status: 'duplicate',
          matchedRule: bestMatch,
          similarity: bestSim,
        }
      }
    }

    // 低相似度 → 全新规则
    return { status: 'new', similarity: bestSim }
  }

  /**
   * AI 拆分文档 → 提取结构化规则（带去重标注，待人工确认）
   *
   * 流程：
   *   1. 调用 AI（或模拟）从文档提取 N 条规则
   *   2. 对每条规则执行 Layer 1 预查重（checkDuplicate）
   *   3. 标注 _dupStatus / _matchedRuleId / _similarityScore / _diffSummary
   *   4. 返回带标注的结果，由 Vue 弹窗展示
   */
  async function aiSplitFromDoc(
    docId: string,
    options?: { onProgress?: (msg: string) => void },
  ): Promise<{ extracted: number; rules: PendingRuleWithDup[] }> {
    const doc = docs.value.find(d => d.id === docId)
    if (!doc) throw new Error(`文档不存在: ${docId}`)

    options?.onProgress?.(`正在分析文档「${doc.filename}」...`)

    // TODO: 替换为真实 API 调用 POST /api/v1/platform-rules/ai-split
    await new Promise(resolve => setTimeout(resolve, 1200))

    options?.onProgress?.('AI 正在提取结构化规则...')

    // 根据文档平台生成模拟拆分结果
    const templateMap: Record<string, Partial<Omit<PlatformRule, 'id' | 'created_at' | 'updated_at'>>[]> = {
      amazon: [
        { category: 'listing', title: `${doc.filename.replace('.pdf', '')} - 标题规范`, content: `从文档「${doc.filename}」中自动提取：商品标题需包含品牌名、核心关键词、规格参数，禁止使用促销性文字。标题长度建议 80-200 字符。`, tags: ['标题', 'Listing', 'AI提取'] },
        { category: 'compliance', title: `${doc.filename.replace('.pdf', '')} - 认证要求`, content: `从文档「${doc.filename}」中自动提取：电子产品需提供 FCC/CE/ROHS 等认证，食品接触品需 FDA 认证。新品上架前需确认所有合规文件齐全。`, tags: ['合规', '认证', 'AI提取'] },
        { category: 'policy', title: `${doc.filename.replace('.pdf', '')} - 账户健康指标`, content: `从文档「${doc.filename}」中自动提取：账户健康评分需保持在 200+，订单缺陷率 < 1%，迟发率 < 4%，退货率因类目而异。`, tags: ['账户健康', '政策', 'AI提取'] },
      ],
      shopee: [
        { category: 'logistics', title: `${doc.filename.replace('.pdf', '')} - SLS 时效要求`, content: `从文档「${doc.filename}」中自动提取：SLS 标准时效东南亚 5-15 天，超时 3 天可申请退款。建议使用海外仓缩短妥投时间。`, tags: ['物流', 'SLS', 'AI提取'] },
        { category: 'policy', title: `${doc.filename.replace('.pdf', '')} - 禁售品类清单`, content: `从文档「${doc.filename}」中自动提取：仿冒品、侵权商品、危险物品（锂电池需认证）、动植物制品等属于禁售范围。`, tags: ['禁售', '合规', 'AI提取'] },
      ],
      tiktok: [
        { category: 'ad', title: `${doc.filename.replace('.pdf', '')} - 广告素材规范`, content: `从文档「${doc.filename}」中自动提取：广告视频需展示真实产品，禁止前后对比夸大效果，禁止未授权肖像。违规将限流或封号。`, tags: ['广告', '素材审核', 'AI提取'] },
        { category: 'policy', title: `${doc.filename.replace('.pdf', '')} - 直播带货要求`, content: `从文档「${doc.filename}」中自动提取：直播需实名认证，禁止虚假宣传价格/功效，商品需与直播间展示一致。`, tags: ['直播', '政策', 'AI提取'] },
      ],
      temu: [
        { category: 'policy', title: `${doc.filename.replace('.pdf', '')} - 佣金费率表`, content: `从文档「${doc.filename}」中自动提取：半托管佣金率 8%-15% 按类目浮动，结算周期 T+15。低价引流品有佣金优惠期限制。`, tags: ['佣金', '结算', 'AI提取'] },
        { category: 'logistics', title: `${doc.filename.replace('.pdf', '')} - 入仓质检标准`, content: `从文档「${doc.filename}」中自动提取：入仓商品需通过 TEMU 质检，包装完好、标签清晰、无破损污渍。不合格将退回或销毁。`, tags: ['质检', '物流', 'AI提取'] },
      ],
      lazada: [
        { category: 'listing', title: `${doc.filename.replace('.pdf', '')} - Listing 优化要求`, content: `从文档「${doc.filename}」中自动提取：主图需白底、≥1000px，标题含核心关键词，描述支持多语言（印尼语/泰语/越南语等）。`, tags: ['Listing', '优化', 'AI提取'] },
        { category: 'policy', title: `${doc.filename.replace('.pdf', '')} - 售后政策`, content: `从文档「${doc.filename}」中自动提取：无忧售后（FFR）需 15 天无理由退货，退货率过高将影响店铺权重。`, tags: ['售后', '政策', 'AI提取'] },
      ],
    }

    const templates = templateMap[doc.platform] || templateMap.amazon
    const today = new Date().toISOString().slice(0, 10)

    // 生成原始规则
    const rawRules: Omit<PlatformRule, 'id' | 'created_at' | 'updated_at'>[] = templates.map((t) => ({
      platform: doc.platform,
      category: t.category || 'policy',
      title: t.title || 'AI 提取规则',
      content: t.content || '',
      effective_date: today,
      status: ('auto' as const),
      tags: t.tags || ['AI提取'],
      source_doc_id: docId,
      source: '',
    }))

    options?.onProgress?.('正在与现有规则库比对查重...')

    // Layer 1：逐条预查重，标注去重状态
    const annotatedRules: PendingRuleWithDup[] = rawRules.map((rule) => {
      const dupResult = checkDuplicate(rule)
      return {
        ...rule,
        _dupStatus: dupResult.status,
        _matchedRuleId: dupResult.matchedRule?.id,
        _similarityScore: dupResult.similarity,
        _diffSummary: dupResult.diffSummary,
      }
    })

    const summary = annotatedRules.reduce(
      (acc, r) => { acc[r._dupStatus]++; return acc },
      { new: 0, duplicate: 0, update: 0 } as Record<DupStatus, number>,
    )

    options?.onProgress?.(
      `完成！提取 ${annotatedRules.length} 条（全新 ${summary.new} / 重复 ${summary.duplicate} / 更新 ${summary.update}），请确认后添加`,
    )

    return { extracted: annotatedRules.length, rules: annotatedRules }
  }

  /**
   * Layer 3：提交前的最终防重校验
   * 对用户勾选的规则再做一次检查，对仍为 duplicate 的弹出警告
   * @returns { ok, warnings, toAdd }
   */
  function prePersistCheck(
    rules: PendingRuleWithDup[],
  ): { ok: boolean; warnings: string[]; safeRules: PendingRuleWithDup[] } {
    const warnings: string[] = []
    const safeRules: PendingRuleWithDup[] = []

    for (const rule of rules) {
      // 重新跑一次查重（防止用户确认期间有人新增了类似规则）
      const freshCheck = checkDuplicate(rule)

      if (freshCheck.status === 'duplicate' && freshCheck.similarity >= DUP_CONFIG.highSimilarityThreshold) {
        const matchedTitle = freshCheck.matchedRule?.title || '未知规则'
        warnings.push(`「${rule.title}」与已有规则「${matchedTitle}」高度相似（${(freshCheck.similarity * 100).toFixed(0)}%）`)
        // 仍然放入 safeRules（允许用户强制添加），但标记上警告
        safeRules.push({ ...rule, _dupStatus: 'duplicate', _matchedRuleId: freshCheck.matchedRule?.id })
      } else if (freshCheck.status === 'update') {
        // 版本更新 → 正常放行，后续由调用方决定是否覆盖旧版
        safeRules.push({ ...rule, _dupStatus: 'update', _matchedRuleId: freshCheck.matchedRule?.id })
      } else {
        safeRules.push(rule)
      }
    }

    return { ok: warnings.length === 0, warnings, safeRules }
  }

  /** 用新规则覆盖旧版本（版本管理） */
  async function replaceOldVersion(oldRuleId: string, newRuleData: Omit<PlatformRule, 'id' | 'created_at' | 'updated_at'>): Promise<void> {
    // 将旧规则标记为 expired（保留历史记录，不作物理删除）
    const oldRule = items.value.find(r => r.id === oldRuleId)
    if (oldRule) {
      await updateItem(oldRule.id, { status: 'expired', tags: [...oldRule.tags, '已作废-版本更新'] })
    }
    // 新规则作为 active 入库
    await addItem(newRuleData)
  }

  return {
    // State
    items,
    docs,
    isLoading,
    searchQuery,
    filterPlatform,
    filterCategory,
    filterStatus,

    // Getters
    filteredItems,
    itemsWithResolvedStatus,
    totalCount,
    platformCount,
    statusCounts,
    hasActiveFilters,
    activeFilterCount,
    getDocById,

    // Actions
    fetchItems,
    addItem,
    updateItem,
    deleteItem,
    clearAllFilters,
    uploadDoc,
    deleteDoc,
    parseAndImport,
    aiSplitFromDoc,
    prePersistCheck,
    replaceOldVersion,
  }
})
