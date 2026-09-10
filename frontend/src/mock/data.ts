/**
 * 统一 Mock 数据层
 *
 * 覆盖所有模块的数据需求：
 * - 商品基础数据（蓝海挖掘、利润测算）
 * - 评论数据（痛点分析）
 * - 竞品对比数据
 * - BSR/销量趋势数据
 * - Listing 质量评分
 *
 * MVP 阶段使用，后续接入真实 API 后替换。
 */

// ====== 类型定义 ======

export interface MockProduct {
  asin: string
  title: string
  brand: string
  price: number
  currency: string
  category: string
  category_path: string[]
  marketplace: string

  // 销售数据
  estimated_monthly_sales: number
  bsr_rank: number
  bsr_category: string

  // 评论数据
  review_count: number
  rating: number           // 1-5 星
  reviews: MockReview[]

  // 尺寸重量
  weight_lbs: number
  dimensions: string       // "LxWxH inch"

  // 图片
  main_image: string
  images: string[]

  // Listing 质量
  title_score: number      // 0-100
  bullet_score: number     // 0-100
  image_score: number      // 0-100
  overall_listing_score: number  // 0-100

  // 利润相关
  cost_price: number       // 采购成本
  fba_fees: number         // FBA 配送费
  referral_fee_pct: number // 佣金比例
  roi_estimated: number    // ROI %
  net_profit: number       // 净利润

  // 蓝海评分
  blue_ocean_score: number // 0-100

  // ===== Listing 文本信息（Amazon 商品页抓取） =====
  selling_points?: string[]                  // 核心卖点（产品宣称的优势/特色）
  bullet_points?: Array<{ title: string; content: string }>  // 五点描述（Bullet Points）
  description?: string                        // 商品描述（Product Description）
  keywords?: string[]                         // 后台搜索词 / 高频关键词
  competitor_asins?: string[]                 // 关联竞品 ASIN（同类目对标）
  rating_breakdown?: { 5: number; 4: number; 3: number; 2: number; 1: number }  // 星级分布（百分比）
  has_a_plus?: boolean                        // 是否有 A+ Content
  has_video?: boolean                         // 是否有产品视频

  // 时间戳
  listed_date: string
  last_updated: string

  // ===== 蓝海扩展字段（变体 / 成本明细 / 竞争结构，部分可选、随 getter 增强注入） =====
  /** 变体数量（父 ASIN 下子 SKU 数）：变体多=竞争复杂开发成本高，少变体=优质蓝海 */
  variation_count?: number
  /** 头程单件物流成本（USD） */
  freight_cost?: number
  /** 卖家数量（Listing 上在售卖家数）：独占/少卖家=真蓝海 */
  seller_count?: number
  /** 是否亚马逊自营 Amazon.com（自营占位需避开） */
  is_amazon_owned?: boolean
  /** 近 30 天价格波动 %（正=涨价） */
  price_trend_30d?: number
  /** 近 30 天销量波动 %（正=需求上涨） */
  sales_trend_30d?: number
  /** 一级类目名（可从 category_path 推导，冗余便于展示） */
  category_l1?: string
  /** 二级类目名 */
  category_l2?: string
}

export interface MockReview {
  review_id: string
  asin: string
  author: string
  rating: number            // 1-5
  title: string
  body: string
  date: string
  verified_purchase: boolean
  helpful_count: number

  // 痛点标签（AI 分析结果）
  pain_points?: string[]   // 提取的痛点关键词
  sentiment: 'positive' | 'negative' | 'neutral'
  category?: string        // 痛点分类：质量/物流/功能/服务等
}

export interface MockCompetitor {
  asin: string
  title: string
  brand: string
  price: number
  rating: number
  review_count: number
  bsr_rank: number

  // Listing 质量
  listing_quality_score: number
  title_score: number
  image_score: number
  bullet_score: number
  a_plus_content: boolean

  // 定位策略
  price_positioning: 'premium' | 'mid-range' | 'budget'
  strengths: string[]
  weaknesses: string[]

  // 广告数据
  sponsored_rank?: number
  estimated_ppc?: number
}

export interface MockBSRTrend {
  date: string
  bsr_rank: number
  category_rank: number
  estimated_sales: number
  price_history: number
}

export interface MockPainPointAnalysis {
  product_asin: string
  total_reviews_analyzed: number
  negative_review_count: number
  positive_review_count: number
  pain_points: PainPointItem[]
  improvement_suggestions: string[]
  market_gap_score: number     // 0-100，市场空白度
  competitor_weaknesses: string[]
}

export interface PainPointItem {
  pain_point: string
  count: number
  percentage: number
  severity: 'high' | 'medium' | 'low'
  category: string
  example_review_id: string
}

export interface MockCompetitorCompareResult {
  compared_asins: string[]
  comparison_summary: string
  recommendation: string
  competitors: MockCompetitor[]
  price_range: { min: number; max: number }
  avg_rating: number
  market_leader: string
  opportunity_areas: string[]
}


// ====== 辅助函数（必须在 MOCK_PRODUCTS 之前定义）======

interface ReviewTemplate {
  type: string
  keywords: string[]
}

const POSITIVE_TEMPLATES = [
  'Great product! Works exactly as described.',
  'Exceeded my expectations. Highly recommend!',
  'Perfect for what I needed. Good quality.',
  'Fast shipping and the item is amazing!',
  'Love it! Will buy again from this seller.',
  'Better than expected for the price.',
  'My family loves this product!',
  'Easy to use right out of the box.',
]

const NEGATIVE_TEMPLATES_BASE = [
  'Disappointed with the quality. Expected better.',
  'Stopped working after a few weeks.',
  'Not worth the money. Returning it.',
  'The description is misleading.',
  'Poor packaging, arrived damaged.',
  'Does not work as advertised.',
  'Cheap materials, feels flimsy.',
  'Customer service was unhelpful.',
]

function randomDate(start: string, end: string): string {
  const startDate = new Date(start).getTime()
  const endDate = new Date(end).getTime()
  const randomTime = startDate + Math.random() * (endDate - startDate)
  return new Date(randomTime).toISOString().split('T')[0]
}

function generateReviews(
  asin: string,
  totalReviews: number,
  avgRating: number,
  templates: ReviewTemplate[]
): MockReview[] {
  const reviews: MockReview[] = []

  // 根据平均评分计算好评/差评比例
  const positiveRatio = (avgRating - 1) / 4  // 1星=0%, 5星=100%
  const positiveCount = Math.round(totalReviews * positiveRatio)
  const negativeCount = totalReviews - positiveCount

  // 生成好评
  for (let i = 0; i < positiveCount; i++) {
    const template = POSITIVE_TEMPLATES[i % POSITIVE_TEMPLATES.length]
    const rating = avgRating >= 4 ? [4, 5][Math.floor(Math.random() * 2)] : [3, 4][Math.floor(Math.random() * 2)]
    reviews.push({
      review_id: `${asin}_R${i + 1}`,
      asin,
      author: `Customer${String(i + 1).padStart(3, '0')}`,
      rating,
      title: template.split('.')[0],
      body: template + ` This is review #${i + 1} for ${asin}.`,
      date: randomDate('2025-03-01', '2026-08-31'),
      verified_purchase: Math.random() > 0.15,
      helpful_count: Math.floor(Math.random() * 20),
      sentiment: 'positive' as const,
      pain_points: [],
    })
  }

  // 生成差评（含痛点标签）
  for (let i = 0; i < negativeCount; i++) {
    const templateIdx = i % NEGATIVE_TEMPLATES_BASE.length
    const template = NEGATIVE_TEMPLATES_BASE[templateIdx]
    const templateConfig = templates[i % templates.length]
    const keyword = templateConfig.keywords[i % templateConfig.keywords.length]

    const rating = avgRating <= 3 ? [1, 2][Math.floor(Math.random() * 2)] : [2, 3][Math.floor(Math.random() * 2)]

    // 根据模板类型分配痛点分类
    let category: string
    switch (templateConfig.type) {
      case 'quality': category = '产品质量'; break
      case 'function': category = '功能体验'; break
      case 'logistics': category = '物流包装'; break
      case 'service': category = '售后服务'; break
      default: category = '其他问题'
    }

    reviews.push({
      review_id: `${asin}_R${positiveCount + i + 1}`,
      asin,
      author: `Customer${String(positiveCount + i + 1).padStart(3, '0')}`,
      rating,
      title: `${keyword} - ${template.split('.')[0]}`,
      body: `${template} Issue: ${keyword}. I noticed problems with ${templateConfig.type}. Review #${positiveCount + i + 1}.`,
      date: randomDate('2025-03-01', '2026-08-31'),
      verified_purchase: Math.random() > 0.2,
      helpful_count: Math.floor(Math.random() * 35),
      sentiment: 'negative' as const,
      pain_points: [keyword],
      category,
    })
  }

  return reviews.sort(() => Math.random() - 0.5)  // 打乱顺序
}


// ====== 商品 Mock 数据池 ======

export const MOCK_PRODUCTS: MockProduct[] = [
  // ========== Home & Kitchen 类目 ==========
  {
    asin: 'B0CXXXX001',
    title: 'Portable Mini Humidifier for Bedroom Desk USB Cool Mist, 500ml Quiet Ultrasonic Humidifier for Baby Plants Office Travel, Auto Shut-Off, 2 Mist Modes',
    brand: 'AquaMist',
    price: 24.99,
    currency: 'USD',
    category: 'kitchen_dining',
    category_path: ['Home & Kitchen', 'Kitchen & Dining', 'Humidifiers'],
    marketplace: 'amazon_us',
    estimated_monthly_sales: 1200,
    bsr_rank: 12543,
    bsr_category: 'Humidifiers',
    review_count: 45,
    rating: 4.3,
    weight_lbs: 0.85,
    dimensions: '6x6x8',
    main_image: '/mock/products/B0CXXXX001.png',
    images: [
      '/mock/products/B0CXXXX001.png',
      '/mock/products/B0CXXXX001.png',
      '/mock/products/B0CXXXX001.png',
    ],
    title_score: 82,
    bullet_score: 75,
    image_score: 88,
    overall_listing_score: 82,
    cost_price: 4.50,
    fba_fees: 3.22,
    referral_fee_pct: 15.0,
    roi_estimated: 35.2,
    net_profit: 13.52,
    blue_ocean_score: 68,
    selling_points: [
      '500ml 大容量水箱，整夜加湿无需加水',
      '双雾量模式（持续/间歇）适应不同场景',
      'USB 供电 + 静音运行，办公/卧室两不误',
      '智能自动断电保护，水位低自动停机',
    ],
    bullet_points: [
      { title: '500ML LARGE CAPACITY', content: 'Top-fill 500ml tank delivers up to 10 hours of continuous cool mist, perfect for all-night bedroom use without frequent refills.' },
      { title: '2 MIST MODES & QUIET OPERATION', content: 'Switch between continuous and intermittent mist modes. Ultrasonic technology keeps noise below 30dB — quieter than a library.' },
      { title: 'USB POWERED & PORTABLE', content: 'Powered by any USB port (5V/2A) — laptop, power bank, or wall adapter. Compact design fits in your bag for travel and office use.' },
      { title: 'AUTO SHUT-OFF PROTECTION', content: 'Built-in water level sensor automatically powers off when tank is empty, preventing dry-burn damage and ensuring safety.' },
      { title: 'MULTI-SCENE USE', content: 'Suitable for bedrooms, baby rooms, offices, plants, and travel. Relieves dry skin, sinus congestion, and protects wooden furniture.' },
    ],
    description: 'The AquaMist Portable Mini Humidifier is your personal moisture companion. Whether you need relief from dry winter air, want to keep your houseplants thriving, or simply prefer a quieter sleeping environment, this 500ml ultrasonic humidifier delivers. Two mist modes (continuous/intermittent) adapt to your needs, while the whisper-quiet 30dB operation ensures it never disturbs your work or rest. USB-powered design means you can take it anywhere — bedroom, office, hotel, or even your car. The smart auto shut-off feature provides peace of mind: the unit powers down automatically when water runs out.',
    keywords: ['mini humidifier', 'usb humidifier', 'bedroom humidifier', 'cool mist humidifier', 'ultrasonic humidifier', 'plant humidifier', 'travel humidifier', 'quiet humidifier', '500ml humidifier', 'auto shut off humidifier'],
    competitor_asins: ['B08XYZ1234', 'B09ABC5678', 'B07DEF9012'],
    rating_breakdown: { 5: 62, 4: 22, 3: 9, 2: 4, 1: 3 },
    has_a_plus: true,
    has_video: false,
    listed_date: '2025-06-15',
    last_updated: '2026-08-28',
    reviews: generateReviews('B0CXXXX001', 45, 4.3, [
      { type: 'quality', keywords: ['漏水', 'leak', 'noise', '噪音', '容量小'] },
      { type: 'function', keywords: ['雾量', 'mist', '自动关机', 'auto shut-off', 'USB供电'] },
      { type: 'service', keywords: ['客服', 'customer service', '退换货', 'return'] },
    ]),
  },
  {
    asin: 'B0CXXXX002',
    title: 'Silicone Kitchen Utensil Set 43 Pcs Cooking Utensils with Holder, Non-Stick Cookware Heat Resistant Spatula Set, Kitchen Gadgets Tools (Khaki)',
    brand: 'ChefCraft',
    price: 29.99,
    currency: 'USD',
    category: 'kitchen_dining',
    category_path: ['Home & Kitchen', 'Kitchen & Dining', 'Cooking Utensils'],
    marketplace: 'amazon_us',
    estimated_monthly_sales: 890,
    bsr_rank: 8921,
    bsr_category: 'Cooking Utensil Sets',
    review_count: 78,
    rating: 4.5,
    weight_lbs: 2.8,
    dimensions: '12x10x6',
    main_image: '/mock/products/B0CXXXX002.png',
    images: [
      '/mock/products/B0CXXXX002.png',
      '/mock/products/B0CXXXX002.png',
      '/mock/products/B0CXXXX002.png',
    ],
    title_score: 78,
    bullet_score: 80,
    image_score: 85,
    overall_listing_score: 81,
    cost_price: 5.20,
    fba_fees: 4.15,
    referral_fee_pct: 15.0,
    roi_estimated: 28.5,
    net_profit: 11.34,
    blue_ocean_score: 53,
    selling_points: [
      '43 件套完整厨房工具，一套解决所有烹饪场景',
      '食品级硅胶 + 耐高温 230°C，不伤不粘锅涂层',
      '旋转收纳架设计，节省台面空间',
      '可拆洗结构，整套洗碗机安全',
    ],
    bullet_points: [
      { title: '43-PIECE COMPLETE SET', content: 'Includes spatulas, ladles, tongs, whisks, measuring spoons, and more — everything you need for daily cooking in one set.' },
      { title: 'FOOD-GRADE SILICONE', content: 'Premium BPA-free silicone heads withstand heat up to 446°F (230°C). Safe for non-stick cookware, won\'t scratch surfaces.' },
      { title: 'ROTATING STORAGE HOLDER', content: '360° rotating stainless steel holder keeps tools organized and within reach. Frees up valuable counter space.' },
      { title: 'DISHWASHER SAFE', content: 'All pieces detach easily for thorough cleaning. Top-rack dishwasher safe for hassle-free maintenance.' },
      { title: 'KHAKI MODERN DESIGN', content: 'Neutral khaki color matches any kitchen décor. Perfect housewarming or wedding gift for new homeowners.' },
    ],
    description: 'Upgrade your kitchen with the ChefCraft 43-Piece Silicone Utensil Set. Designed for both functionality and style, this comprehensive set includes every tool you need — from flipping pancakes to serving pasta. The food-grade silicone construction protects your non-stick pans while withstanding high-heat cooking. The 360° rotating holder keeps your countertops clutter-free and tools within easy reach. Whether you\'re a home cook or a culinary enthusiast, this set brings restaurant-quality tools to your everyday cooking.',
    keywords: ['silicone kitchen utensils', 'cooking utensil set', 'non stick spatula set', 'kitchen gadgets', '43 piece kitchen set', 'kitchen tools with holder', 'heat resistant utensils', 'cooking tools set', 'bpa free kitchen utensils', 'spatula set with holder'],
    competitor_asins: ['B09KITCHEN1', 'B08SPOON01', 'B07WHISK99'],
    rating_breakdown: { 5: 71, 4: 18, 3: 7, 2: 3, 1: 1 },
    has_a_plus: true,
    has_video: true,
    listed_date: '2025-04-20',
    last_updated: '2026-08-25',
    reviews: generateReviews('B0CXXXX002', 78, 4.5, [
      { type: 'quality', keywords: ['硅胶味', 'smell', '变形', 'deform', '易断', 'break'] },
      { type: 'function', keywords: ['耐高温', 'heat resistant', '不粘', 'non-stick', '清洗', 'clean'] },
      { type: 'logistics', keywords: ['包装', 'packaging', '缺失', 'missing pieces'] },
    ]),
  },
  {
    asin: 'B0CXXXX003',
    title: 'LED Plant Grow Light Full Spectrum for Indoor Plants, Adjustable Gooseneck 3/9/12H Timer 10 Dimmable Levels Small Grow Lamp for Seedlings Succulents',
    brand: 'GrowPro',
    price: 34.99,
    currency: 'USD',
    category: 'home_decor',
    category_path: ['Home & Kitchen', 'Home Decor', 'Grow Lights'],
    marketplace: 'amazon_us',
    estimated_monthly_sales: 650,
    bsr_rank: 6542,
    bsr_category: 'Plant Growing Lamps',
    review_count: 32,
    rating: 4.6,
    weight_lbs: 0.65,
    dimensions: '4x4x12',
    main_image: '/mock/products/B0CXXXX003.png',
    images: [
      '/mock/products/B0CXXXX003.png',
      '/mock/products/B0CXXXX003.png',
    ],
    title_score: 85,
    bullet_score: 82,
    image_score: 90,
    overall_listing_score: 86,
    cost_price: 7.80,
    fba_fees: 2.88,
    referral_fee_pct: 15.0,
    roi_estimated: 42.1,
    net_profit: 16.21,
    blue_ocean_score: 68,
    selling_points: [
      '全光谱 LED，模拟自然阳光促进光合作用',
      '10 档亮度 + 3/9/12 小时定时，自动化养护',
      '鹅颈软管 + 夹子设计，任意角度任意位置',
      '低能耗 30W，覆盖 2-3 盆植物',
    ],
    bullet_points: [
      { title: 'FULL SPECTRUM GROW LIGHT', content: '660nm red + 460nm blue + 3000K/6500K white LEDs mimic natural sunlight, accelerating photosynthesis at all growth stages.' },
      { title: '10 DIMMABLE LEVELS', content: 'Adjustable brightness from 10% to 100% to meet different plants\' light requirements — seedlings, succulents, herbs, and flowering plants.' },
      { title: 'AUTO TIMER 3/9/12H', content: 'Built-in timer cycles on/off automatically. Set once and the light maintains your schedule even when you\'re away.' },
      { title: 'FLEXIBLE GOOSENECK & CLIP', content: '360° adjustable gooseneck and sturdy clip mount on any pot up to 2.5 inches. Position light exactly where plants need it.' },
      { title: 'ENERGY EFFICIENT', content: 'Consumes only 30W while providing equivalent light output of 150W traditional bulbs. Saves energy and lasts 50,000+ hours.' },
    ],
    description: 'Give your indoor garden the light it craves with the GrowPro LED Plant Grow Light. Whether you\'re growing succulents on your windowsill, starting seedlings for spring planting, or maintaining tropical houseplants in a low-light apartment, this full-spectrum grow light provides the wavelengths your plants need. The flexible gooseneck and clip design lets you position light at any angle, while the 3/9/12-hour automatic timer takes the guesswork out of plant care. With 10 dimmable brightness levels, you can tailor light intensity to each plant\'s specific needs.',
    keywords: ['led grow light', 'plant light', 'indoor grow light', 'full spectrum grow light', 'grow lamp for indoor plants', 'seedling light', 'succulent grow light', 'plant light with timer', 'gooseneck grow light', 'clip on grow light'],
    competitor_asins: ['B08PLANT01', 'B07GROW99', 'B09LIGHT2'],
    rating_breakdown: { 5: 68, 4: 21, 3: 7, 2: 3, 1: 1 },
    has_a_plus: true,
    has_video: false,
    listed_date: '2025-09-01',
    last_updated: '2026-08-30',
    reviews: generateReviews('B0CXXXX003', 32, 4.6, [
      { type: 'quality', keywords: ['亮度', 'brightness', '散热', 'heat', '寿命', 'lifespan'] },
      { type: 'function', keywords: ['定时器', 'timer', '光谱', 'spectrum', '植物生长', 'growth'] },
    ]),
  },
  {
    asin: 'B0CXXXX004',
    title: 'Electric Milk Frother Handheld Foam Maker for Coffee, Latte, Cappuccino, Hot Chocolate, Battery Operated Drink Mixer with Stainless Steel Whisk',
    brand: 'FrothMax',
    price: 12.99,
    currency: 'USD',
    category: 'kitchen_dining',
    category_path: ['Home & Kitchen', 'Kitchen & Dining', 'Milk Frothers'],
    marketplace: 'amazon_us',
    estimated_monthly_sales: 2100,
    bsr_rank: 3210,
    bsr_category: 'Milk Frothers',
    review_count: 156,
    rating: 4.1,
    weight_lbs: 0.15,
    dimensions: '2x2x9',
    main_image: '/mock/products/B0CXXXX004.png',
    images: [
      '/mock/products/B0CXXXX004.png',
      '/mock/products/B0CXXXX004.png',
    ],
    title_score: 76,
    bullet_score: 70,
    image_score: 82,
    overall_listing_score: 76,
    cost_price: 2.10,
    fba_fees: 1.25,
    referral_fee_pct: 15.0,
    roi_estimated: 22.3,
    net_profit: 5.14,
    blue_ocean_score: 42,
    selling_points: [
      '强力 15000 RPM 电机，10 秒打出绵密奶泡',
      '手持便携 + 不锈钢打蛋头，多用途（咖啡/奶昔/蛋液）',
      'AA 电池供电，无需充电即开即用',
      '人体工学防滑手柄，使用舒适',
    ],
    bullet_points: [
      { title: 'POWERFUL 15000 RPM MOTOR', content: 'High-speed motor whips rich, velvety foam in 10-15 seconds. Perfect for cappuccinos, lattes, macchiatos, and matcha.' },
      { title: 'MULTI-PURPOSE USE', content: 'More than just a milk frother — also works as an egg beater, sauce mixer, and protein shake blender. One tool, endless uses.' },
      { title: 'BATTERY OPERATED', content: 'Runs on 2 AA batteries (included) for instant use. No charging cables, no downtime. Always ready when you need it.' },
      { title: 'PREMIUM STAINLESS STEEL', content: 'Food-grade 304 stainless steel whisk is rust-resistant, easy to clean, and BPA-free. Dishwasher safe.' },
      { title: 'ERGONOMIC GRIP', content: 'Lightweight design with non-slip handle reduces hand fatigue. Comfortable for daily use at home or in the office.' },
    ],
    description: 'Transform your morning coffee into a café-quality experience with the FrothMax Handheld Milk Frother. In just 10-15 seconds, this powerful 15000 RPM frother creates rich, creamy foam that makes lattes, cappuccinos, and hot chocolates taste professionally made. But it doesn\'t stop at coffee — use it to whip eggs for omelets, blend protein shakes, or mix sauces and dressings. Battery-operated convenience means no charging downtime, and the stainless steel construction ensures years of reliable use.',
    keywords: ['milk frother', 'handheld milk frother', 'coffee frother', 'electric whisk', 'foam maker', 'cappuccino maker', 'matcha whisk', 'battery operated frother', 'drink mixer', 'mini blender'],
    competitor_asins: ['B07FROTH1', 'B09MILK99', 'B08FOAM02'],
    rating_breakdown: { 5: 75, 4: 16, 3: 5, 2: 2, 1: 2 },
    has_a_plus: false,
    has_video: true,
    listed_date: '2025-02-10',
    last_updated: '2026-08-20',
    reviews: generateReviews('B0CXXXX004', 156, 4.1, [
      { type: 'quality', keywords: ['电池', 'battery', '生锈', 'rust', '马达', 'motor'] },
      { type: 'function', keywords: ['打泡', 'frothing', '功率', 'power', '耐用性', 'durability'] },
      { type: 'logistics', keywords: ['包装破损', 'damaged', '到货慢', 'slow delivery'] },
    ]),
  },
  {
    asin: 'B0CXXXX005',
    title: 'Acrylic Organizer Makeup Storage Drawer Cosmetic Box, Clear Makeup Organizers and Storage for Vanity Bathroom Bedroom Skincare Jewelry Lipstick Brushes (Large)',
    brand: 'ClearSpace',
    price: 19.99,
    currency: 'USD',
    category: 'home_decor',
    category_path: ['Home & Kitchen', 'Home Decor', 'Storage Organizers'],
    marketplace: 'amazon_us',
    estimated_monthly_sales: 1800,
    bsr_rank: 4567,
    bsr_category: 'Cosmetic Bags',
    review_count: 89,
    rating: 4.4,
    weight_lbs: 2.2,
    dimensions: '12x8x6',
    main_image: '/mock/products/B0CXXXX005.png',
    images: [
      '/mock/products/B0CXXXX005.png',
      '/mock/products/B0CXXXX005.png',
      '/mock/products/B0CXXXX005.png',
    ],
    title_score: 80,
    bullet_score: 77,
    image_score: 86,
    overall_listing_score: 81,
    cost_price: 4.80,
    fba_fees: 3.45,
    referral_fee_pct: 15.0,
    roi_estimated: 31.8,
    net_profit: 8.49,
    blue_ocean_score: 65,
    selling_points: [
      '透明亚克力材质，所有物品一目了然',
      '多格抽屉设计，分类收纳口红/刷具/护肤',
      '大容量三层结构，节省梳妆台空间',
      '防尘防潮设计，化妆品使用寿命更长',
    ],
    bullet_points: [
      { title: 'CLEAR ACRYLIC DESIGN', content: 'Premium crystal-clear acrylic lets you see all your cosmetics at a glance. No more digging through drawers to find what you need.' },
      { title: 'MULTI-DRAWER STORAGE', content: 'Multiple sized compartments organize lipsticks, brushes, skincare bottles, and jewelry. Customize your storage layout.' },
      { title: 'SPACE-SAVING 3-TIER', content: 'Vertical 3-tier design maximizes storage while minimizing counter footprint. Holds 30+ lipsticks and 20+ brushes.' },
      { title: 'DUST & MOISTURE PROTECTION', content: 'Sealed drawers keep dust and humidity away from your cosmetics, extending product life and maintaining hygiene.' },
      { title: 'VERSATILE USE', content: 'Perfect for vanity, bathroom, bedroom, or dresser. Also great for organizing craft supplies, office stationery, or kitchen gadgets.' },
    ],
    description: 'Bring order to your beauty collection with the ClearSpace Acrylic Makeup Organizer. This thoughtfully designed 3-tier storage solution features multiple drawer sizes to accommodate everything from lipsticks and brushes to skincare bottles and jewelry. The crystal-clear acrylic construction makes finding products effortless, while the sealed drawers protect your cosmetics from dust and moisture. Whether you\'re a makeup enthusiast with hundreds of products or simply want a clutter-free vanity, this organizer adapts to your needs.',
    keywords: ['makeup organizer', 'cosmetic organizer', 'acrylic makeup storage', 'makeup drawer', 'vanity organizer', 'lipstick holder', 'brush holder', 'skincare organizer', 'clear makeup organizer', 'makeup storage box'],
    competitor_asins: ['B08COSMETIC', 'B07VANITY1', 'B09ORGANIZ'],
    rating_breakdown: { 5: 73, 4: 17, 3: 6, 2: 3, 1: 1 },
    has_a_plus: true,
    has_video: false,
    listed_date: '2025-05-18',
    last_updated: '2026-08-27',
    reviews: generateReviews('B0CXXXX005', 89, 4.4, [
      { type: 'quality', keywords: ['亚克力划痕', 'scratch', '裂纹', 'crack', '抽屉卡顿', 'drawer stuck'] },
      { type: 'function', keywords: ['容量', 'capacity', '分层', 'layer', '透明度', 'transparency'] },
    ]),
  },

  // ========== Sports & Outdoors ==========
  {
    asin: 'B0CXXXX006',
    title: 'Resistance Bands Set Exercise Workout Bands Fitness Bands with Door Anchor Handles Legs Ankle Straps for Resistance Training Physical Therapy Home Workouts',
    brand: 'FitFlex',
    price: 15.99,
    currency: 'USD',
    category: 'fitness',
    category_path: ['Sports & Outdoors', 'Fitness Accessories', 'Resistance Bands'],
    marketplace: 'amazon_us',
    estimated_monthly_sales: 3200,
    bsr_rank: 1890,
    bsr_category: 'Resistance Bands',
    review_count: 234,
    rating: 4.2,
    weight_lbs: 1.5,
    dimensions: '10x6x3',
    main_image: '/mock/products/B0CXXXX006.png',
    images: [
      '/mock/products/B0CXXXX006.png',
      '/mock/products/B0CXXXX006.png',
    ],
    title_score: 74,
    bullet_score: 72,
    image_score: 84,
    overall_listing_score: 77,
    cost_price: 3.20,
    fba_fees: 2.35,
    referral_fee_pct: 15.0,
    roi_estimated: 18.6,
    net_profit: 4.09,
    blue_ocean_score: 32,
    selling_points: [
      '5 档阻力等级（10-50 lbs），覆盖初学到进阶',
      '天然乳胶材质，弹性持久不易断裂',
      '配套门锚 + 手柄 + 脚踝带，居家全身训练',
      '便携收纳袋，差旅健身随行',
    ],
    bullet_points: [
      { title: '5 RESISTANCE LEVELS', content: 'Five color-coded bands provide 10-50 lbs of resistance. Mix and match combinations for up to 100+ lbs total resistance.' },
      { title: 'PREMIUM NATURAL LATEX', content: 'Made from 100% natural latex for superior elasticity and durability. Maintains shape after thousands of stretches.' },
      { title: 'COMPLETE HOME GYM KIT', content: 'Includes door anchor, foam handles, ankle straps, carrying bag, and workout guide. Everything you need for full-body training.' },
      { title: 'PORTABLE & TRAVEL-FRIENDLY', content: 'Lightweight kit fits in included carrying bag — perfect for business trips, vacations, or outdoor workouts at the park.' },
      { title: 'VERSATILE WORKOUTS', content: 'Ideal for strength training, physical therapy, yoga, pilates, and rehabilitation exercises. Suitable for all fitness levels.' },
    ],
    description: 'Build your home gym without taking up floor space. The FitFlex Resistance Bands Set provides a complete strength training solution in a portable package. Five color-coded bands offer progressive resistance from 10 to 50 pounds, with combinations enabling over 100 pounds of total resistance. The included door anchor, handles, and ankle straps let you perform hundreds of exercises targeting every major muscle group. Whether you\'re a beginner starting your fitness journey or an experienced athlete looking to add variety to your training, these bands adapt to your level.',
    keywords: ['resistance bands', 'exercise bands', 'workout bands', 'fitness bands', 'resistance band set', 'home gym', 'strength training bands', 'resistance bands with handles', 'resistance bands for physical therapy', 'resistance bands with door anchor'],
    competitor_asins: ['B07FITNESS', 'B09GYM99', 'B08BAND01'],
    rating_breakdown: { 5: 78, 4: 15, 3: 4, 2: 2, 1: 1 },
    has_a_plus: true,
    has_video: true,
    listed_date: '2024-12-01',
    last_updated: '2026-08-29',
    reviews: generateReviews('B0CXXXX006', 234, 4.2, [
      { type: 'quality', keywords: ['弹力带断裂', 'snap', '异味', 'odor', '手柄脱落', 'handle break'] },
      { type: 'function', keywords: ['阻力等级', 'resistance level', '拉伸', 'stretch', '锻炼效果', 'workout effect'] },
      { type: 'logistics', keywords: ['缺配件', 'missing accessories', '说明书', 'instruction manual'] },
    ]),
  },

  // ========== Electronics ==========
  {
    asin: 'B0CXXXX007',
    title: 'Bamboo Cutting Board with Juice Groove, Extra Large Wooden Cutting Boards for Kitchen, Butcher Block Chopping Board for Meat Vegetables Fruits Cheese (17x12")',
    brand: 'BambooCraft',
    price: 22.99,
    currency: 'USD',
    category: 'kitchen_dining',
    category_path: ['Home & Kitchen', 'Kitchen & Dining', 'Cutting Boards'],
    marketplace: 'amazon_us',
    estimated_monthly_sales: 750,
    bsr_rank: 9876,
    bsr_category: 'Cutting Boards',
    review_count: 56,
    rating: 4.5,
    weight_lbs: 3.5,
    dimensions: '17x12x1.5',
    main_image: '/mock/products/B0CXXXX007.png',
    images: [
      '/mock/products/B0CXXXX007.png',
      '/mock/products/B0CXXXX007.png',
      '/mock/products/B0CXXXX007.png',
    ],
    title_score: 83,
    bullet_score: 79,
    image_score: 87,
    overall_listing_score: 83,
    cost_price: 5.50,
    fba_fees: 4.55,
    referral_fee_pct: 15.0,
    roi_estimated: 38.4,
    net_profit: 9.39,
    blue_ocean_score: 62,
    selling_points: [
      '加厚竹材 + 侧面凹槽接汁液，台面整洁',
      '17x12 英寸超大面积，整鸡整鱼都放得下',
      '天然抗菌竹纤维，比塑料砧板更卫生',
      '双面可用 + 提手设计，使用便捷',
    ],
    bullet_points: [
      { title: 'EXTRA LARGE 17x12 INCHES', content: 'Generous cutting surface accommodates whole chickens, large watermelons, or meal prep for a family of four. No more cutting in batches.' },
      { title: 'INTEGRATED JUICE GROOVE', content: 'Deep juice groove on the side catches liquid runoff from meat, fruits, and vegetables — keeps your counter clean and sanitary.' },
      { title: 'PREMIUM BAMBOO CONSTRUCTION', content: 'Made from sustainably-sourced Moso bamboo. Naturally antibacterial, knife-friendly, and more durable than plastic boards.' },
      { title: 'REVERSIBLE DOUBLE-SIDED', content: 'Use one side for meat and fish, the other for vegetables and bread. Prevents cross-contamination and extends board life.' },
      { title: 'BUILT-IN HANDLES', content: 'Recessed handles on both sides for easy lifting, carrying, and hanging storage. Doubles as a serving tray for cheese and charcuterie.' },
    ],
    description: 'The BambooCraft Extra Large Cutting Board transforms meal prep from a chore into a pleasure. At 17x12 inches, it offers ample space for slicing whole chickens, breaking down watermelons, or preparing an entire week\'s meal prep. The integrated juice groove keeps messy liquids contained, while the premium Moso bamboo construction provides natural antibacterial properties that protect your family. Reversible double-sided design lets you designate one side for proteins and the other for produce, preventing cross-contamination.',
    keywords: ['bamboo cutting board', 'wooden cutting board', 'large cutting board', 'butcher block', 'cutting board with juice groove', 'chopping board', 'kitchen cutting board', 'bamboo chopping board', 'cutting board with handle', 'extra large cutting board'],
    competitor_asins: ['B07BAMBOO1', 'B08KITCHB2', 'B09BOARD9'],
    rating_breakdown: { 5: 80, 4: 14, 3: 4, 2: 1, 1: 1 },
    has_a_plus: true,
    has_video: false,
    listed_date: '2025-07-22',
    last_updated: '2026-08-26',
    reviews: generateReviews('B0CXXXX007', 56, 4.5, [
      { type: 'quality', keywords: ['开裂', 'crack', '发霉', 'mold', '变形', 'warp', '刀痕', 'knife mark'] },
      { type: 'function', keywords: ['尺寸', 'size', '厚度', 'thickness', '防滑脚', 'non-slip feet'] },
    ]),
  },
  {
    asin: 'B0CXXXX008',
    title: 'Wireless Charging Pad Fast Charger Stand for iPhone Samsung Galaxy Google Pixel AirPods Pro, Qi-Certified 15W Max Phone Charger Dock Station',
    brand: 'ChargeTech',
    price: 18.99,
    currency: 'USD',
    category: 'electronics_accessories',
    category_path: ['Electronics', 'Accessories', 'Chargers'],
    marketplace: 'amazon_us',
    estimated_monthly_sales: 1450,
    bsr_rank: 5432,
    bsr_category: 'Cell Phone Chargers',
    review_count: 198,
    rating: 4.0,
    weight_lbs: 0.45,
    dimensions: '4x4x1',
    main_image: '/mock/products/B0CXXXX008.png',
    images: [
      '/mock/products/B0CXXXX008.png',
      '/mock/products/B0CXXXX008.png',
    ],
    title_score: 81,
    bullet_score: 73,
    image_score: 83,
    overall_listing_score: 79,
    cost_price: 4.00,
    fba_fees: 1.88,
    referral_fee_pct: 15.0,
    roi_estimated: 19.2,
    net_profit: 5.11,
    blue_ocean_score: 38,
    selling_points: [
      'Qi 认证 15W 快充，兼容 iPhone/Android/AirPods',
      '双线圈设计，横放竖放都能充',
      '智能温控 + 过流保护，充电更安全',
      'LED 指示灯 + 硅胶防滑垫，细节贴心',
    ],
    bullet_points: [
      { title: '15W FAST WIRELESS CHARGING', content: 'Qi-certified fast charging delivers up to 15W for compatible devices — charge iPhone, Samsung Galaxy, Google Pixel, and AirPods Pro.' },
      { title: 'DUAL COIL DESIGN', content: 'Two built-in charging coils let you charge your phone in landscape or portrait orientation. Watch videos while charging.' },
      { title: 'MULTI-PROTECTION SAFETY', content: 'Built-in safeguards protect against overcharging, overheating, overcurrent, and short circuits. Foreign object detection prevents damage.' },
      { title: 'CASE-FRIENDLY CHARGING', content: 'Charges through cases up to 5mm thick — no need to remove your protective case every time you charge.' },
      { title: 'SLEEK MINIMALIST DESIGN', content: 'Compact 4-inch footprint fits any desk or nightstand. Anti-slip silicone pad keeps your device securely in place during charging.' },
    ],
    description: 'Cut the cord with the ChargeTech Wireless Charging Pad. This Qi-certified 15W charger delivers fast wireless charging to all your essential devices — from the latest iPhone and Samsung Galaxy to AirPods Pro and other Qi-enabled accessories. The dual-coil design means you can use your phone in any orientation while it charges, perfect for watching videos or making video calls. Intelligent safety features protect both the charger and your devices, while the compact minimalist design fits seamlessly on any desk or nightstand.',
    keywords: ['wireless charger', 'wireless charging pad', 'qi charger', 'fast wireless charger', 'iphone wireless charger', 'samsung wireless charger', 'wireless charging stand', 'airpods wireless charger', '15w wireless charger', 'wireless phone charger'],
    competitor_asins: ['B07CHARGE', 'B09WIRE01', 'B08QI99'],
    rating_breakdown: { 5: 70, 4: 19, 3: 6, 2: 3, 1: 2 },
    has_a_plus: false,
    has_video: false,
    listed_date: '2025-03-15',
    last_updated: '2026-08-23',
    reviews: generateReviews('B0CXXXX008', 198, 4.0, [
      { type: 'quality', keywords: ['充电慢', 'slow charge', '发热', 'overheat', '指示灯', 'LED indicator'] },
      { type: 'function', keywords: ['兼容性', 'compatibility', '充电距离', 'charging distance', 'case friendly'] },
      { type: 'service', keywords: ['保修', 'warranty', '客服响应', 'support response'] },
    ]),
  },

  // ========== Health & Personal Care ==========
  {
    asin: 'B0CXXXX009',
    title: 'Stainless Steel Water Bottle Insulated Travel Mug with Straw Lid, 32oz Wide Mouth Vacuum Insulated Double Wall Tumbler Keeps Cold 24h Hot 12h, Leak Proof BPA Free',
    brand: 'ThermoKeep',
    price: 26.99,
    currency: 'USD',
    category: 'sports_outdoors',
    category_path: ['Sports & Outdoors', 'Water Bottles'],
    marketplace: 'amazon_us',
    estimated_monthly_sales: 560,
    bsr_rank: 11234,
    bsr_category: 'Water Bottles',
    review_count: 28,
    rating: 4.7,
    weight_lbs: 1.1,
    dimensions: '4x4x11',
    main_image: '/mock/products/B0CXXXX009.png',
    images: [
      '/mock/products/B0CXXXX009.png',
      '/mock/products/B0CXXXX009.png',
      '/mock/products/B0CXXXX009.png',
    ],
    title_score: 86,
    bullet_score: 84,
    image_score: 91,
    overall_listing_score: 87,
    cost_price: 6.20,
    fba_fees: 3.68,
    referral_fee_pct: 15.0,
    roi_estimated: 45.6,
    net_profit: 12.11,
    blue_ocean_score: 69,
    selling_points: [
      '双层真空保温，冷饮 24h / 热饮 12h',
      '32oz 大容量，一瓶满足全天饮水',
      '食品级 304 不锈钢 + BPA Free，安全无味',
      '配吸管盖 + 防漏密封，户外通勤两用',
    ],
    bullet_points: [
      { title: '24H COLD & 12H HOT', content: 'Double-wall vacuum insulation keeps drinks ice-cold for 24 hours or piping hot for 12 hours. Perfect for any climate or season.' },
      { title: '32OZ LARGE CAPACITY', content: 'Generous 32oz capacity eliminates the need for constant refills. Stay hydrated all day at work, gym, or on outdoor adventures.' },
      { title: 'PREMIUM 304 STAINLESS STEEL', content: 'Made from food-grade 18/8 stainless steel. Rust-proof, BPA-free, and won\'t retain or transfer flavors from previous drinks.' },
      { title: 'LEAK-PROOF STRAW LID', content: 'Included flip-up straw lid for easy sipping, plus leak-proof seal prevents spills in your bag. Wide mouth fits ice cubes.' },
      { title: 'ECO-FRIENDLY REUSABLE', content: 'Replaces hundreds of single-use plastic bottles per year. Dishwasher safe and built to last a lifetime.' },
    ],
    description: 'Stay hydrated in style with the ThermoKeep 32oz Insulated Water Bottle. Whether you\'re hitting the gym, heading to the office, or embarking on a weekend adventure, this bottle keeps your drinks at the perfect temperature all day long. Double-wall vacuum insulation locks in cold for 24 hours or heat for 12 hours, while the food-grade stainless steel construction ensures pure taste with zero flavor transfer. The versatile straw lid makes sipping effortless, and the leak-proof seal means you can toss it in your bag worry-free.',
    keywords: ['water bottle', 'insulated water bottle', 'stainless steel water bottle', '32oz water bottle', 'tumbler', 'travel mug', 'reusable water bottle', 'bpa free water bottle', 'vacuum insulated bottle', 'sports water bottle'],
    competitor_asins: ['B08HYDRATE', 'B07BOTTLE1', 'B09WATER9'],
    rating_breakdown: { 5: 76, 4: 16, 3: 5, 2: 2, 1: 1 },
    has_a_plus: true,
    has_video: true,
    listed_date: '2025-10-01',
    last_updated: '2026-08-31',
    reviews: generateReviews('B0CXXXX009', 28, 4.7, [
      { type: 'quality', keywords: ['保温效果', 'insulation', '掉漆', 'paint chip', '吸管漏', 'straw leak'] },
      { type: 'function', keywords: ['容量', 'capacity', '清洗难度', 'cleaning', '杯盖密封', 'lid seal'] },
    ]),
  },
  {
    asin: 'B0CXXXX010',
    title: 'Nebulizer Machine for Kids Adults Portable Compressor Nebulizer System with Full Kit, Jet Nebulizer Personal Steam Inhaler for Home Use Travel',
    brand: 'MediBreathe',
    price: 39.99,
    currency: 'USD',
    category: 'health_personal_care',
    category_path: ['Health & Personal Care', 'Respiratory Aids', 'Nebulizers'],
    marketplace: 'amazon_us',
    estimated_monthly_sales: 420,
    bsr_rank: 14567,
    bsr_category: 'Nebulizers',
    review_count: 67,
    rating: 4.3,
    weight_lbs: 2.8,
    dimensions: '8x6x5',
    main_image: '/mock/products/B0CXXXX010.png',
    images: [
      '/mock/products/B0CXXXX010.png',
      '/mock/products/B0CXXXX010.png',
    ],
    title_score: 84,
    bullet_score: 81,
    image_score: 85,
    overall_listing_score: 83,
    cost_price: 10.50,
    fba_fees: 4.28,
    referral_fee_pct: 15.0,
    roi_estimated: 33.1,
    net_profit: 13.21,
    blue_ocean_score: 52,
    selling_points: [
      '医用级压缩雾化，颗粒细腻直达肺部',
      '成人/儿童双模式，全家适用',
      '配备完整套件（面罩/咬嘴/管路），开箱即用',
      '低噪音设计 + 便携手提，居家旅行两用',
    ],
    bullet_points: [
      { title: 'MEDICAL-GRADE NEBULIZATION', content: 'Compressor system produces fine mist with MMAD ≤ 5μm particles. Effective delivery of medication to lower respiratory tract.' },
      { title: 'DUAL-MODE FOR ADULTS & KIDS', content: 'Includes both adult and child masks. Adjustable flow rate adapts treatment intensity for different family members.' },
      { title: 'COMPLETE TREATMENT KIT', content: 'Comes with mouthpiece, adult mask, child mask, air tube, replacement filters, and carrying case. Everything you need in one box.' },
      { title: 'QUIET OPERATION', content: 'Operates at under 55dB — quieter than a normal conversation. Comfortable for use while children sleep or rest.' },
      { title: 'PORTABLE & TRAVEL-READY', content: 'Compact design with built-in handle. Operates on AC power at home, with optional car adapter (sold separately) for travel.' },
    ],
    description: 'Breathe easier with the MediBreathe Portable Compressor Nebulizer. This medical-grade device delivers medication directly to your lungs as a fine, breathable mist, providing fast and effective relief from respiratory conditions including asthma, bronchitis, and allergies. Suitable for both adults and children, the included dual-mask kit makes family treatment simple. Quiet operation won\'t disturb resting children, and the compact portable design means you can take your treatment anywhere — home, office, or hotel.',
    keywords: ['nebulizer', 'nebulizer machine', 'portable nebulizer', 'compressor nebulizer', 'nebulizer for kids', 'nebulizer for adults', 'breathing machine', 'asthma nebulizer', 'respiratory care', 'medical nebulizer'],
    competitor_asins: ['B07MEDICAL', 'B08BREATH', 'B09NEBUL99'],
    rating_breakdown: { 5: 74, 4: 17, 3: 5, 2: 3, 1: 1 },
    has_a_plus: true,
    has_video: false,
    listed_date: '2025-08-10',
    last_updated: '2026-08-24',
    reviews: generateReviews('B0CXXXX010', 67, 4.3, [
      { type: 'quality', keywords: ['噪音大', 'loud noise', '雾化颗粒', 'particle size', '机器故障', 'malfunction'] },
      { type: 'function', keywords: ['雾化速度', 'nebulization speed', '药液残留', 'residue', '儿童适用', 'kid-friendly'] },
      { type: 'service', keywords: ['配件更换', 'replacement parts', '保修政策', 'warranty policy'] },
    ]),
  },

  // ========== Pet Supplies ==========
  {
    asin: 'B0CXXXX011',
    title: 'Car Backseat Organizer Kick Mats Protector with Touch Screen Tablet Holder + 9 Storage Pockets, Waterproof Seat Back Protectors Cover for Kids Toddlers',
    brand: 'TravelSafe',
    price: 17.99,
    currency: 'USD',
    category: 'automotive',
    category_path: ['Automotive', 'Interior Accessories', 'Seat Back Organizers'],
    marketplace: 'amazon_us',
    estimated_monthly_sales: 980,
    bsr_rank: 7654,
    bsr_category: 'Seat Back Organizers',
    review_count: 112,
    rating: 4.2,
    weight_lbs: 0.95,
    dimensions: '18x14x1',
    main_image: '/mock/products/B0CXXXX011.png',
    images: [
      '/mock/products/B0CXXXX011.png',
      '/mock/products/B0CXXXX011.png',
    ],
    title_score: 77,
    bullet_score: 74,
    image_score: 80,
    overall_listing_score: 77,
    cost_price: 3.80,
    fba_fees: 3.12,
    referral_fee_pct: 15.0,
    roi_estimated: 25.4,
    net_profit: 7.57,
    blue_ocean_score: 48,
    selling_points: [
      '9 个储物袋 + iPad 触屏窗，娱乐收纳两不误',
      '防水面料 + 儿童踩踏防护，保护座椅',
      '通用尺寸适配 99% 车型 SUV/MPV/轿车',
      '可机洗 + 快速安装拆卸',
    ],
    bullet_points: [
      { title: '9 STORAGE POCKETS + TABLET HOLDER', content: 'Organize toys, snacks, water bottles, books, and devices. Clear touchscreen window fits tablets up to 10 inches for backseat entertainment.' },
      { title: 'PREMIUM WATERPROOF FABRIC', content: 'Made from durable 600D Oxford fabric with waterproof coating. Easy to wipe clean and protects seats from spills and stains.' },
      { title: 'KICK MAT PROTECTION', content: 'Reinforced backing prevents scuff marks from children\'s shoes. Keeps your leather or fabric seats looking new for years.' },
      { title: 'UNIVERSAL FIT', content: 'Adjustable straps fit most vehicles including sedans, SUVs, trucks, and minivans. Two-pack covers both front seat backs.' },
      { title: 'EASY INSTALL & MACHINE WASHABLE', content: 'Installs in under 2 minutes with simple buckle straps. When dirty, toss in the washing machine for a fresh, like-new look.' },
    ],
    description: 'Keep your car clean, organized, and your kids entertained with the TravelSafe Car Backseat Organizer. This 2-pack of premium seat back protectors features 9 storage pockets to hold everything from water bottles and snacks to tablets and toys. The transparent touchscreen window lets passengers watch videos or play games on their tablet without removing it from the holder. Waterproof 600D Oxford fabric wipes clean in seconds, while reinforced kick mat backing protects your seats from scuff marks. Universal adjustable straps ensure a perfect fit in virtually any vehicle.',
    keywords: ['car backseat organizer', 'kick mat', 'car seat protector', 'car organizer', 'back seat organizer', 'car seat back protector', 'kick mats for car', 'car organizer for kids', 'toddler car accessories', 'car seat kick guard'],
    competitor_asins: ['B07CARORG1', 'B08KICKMAT', 'B09SEAT99'],
    rating_breakdown: { 5: 72, 4: 18, 3: 6, 2: 3, 1: 1 },
    has_a_plus: false,
    has_video: true,
    listed_date: '2025-06-01',
    last_updated: '2026-08-22',
    reviews: generateReviews('B0CXXXX011', 112, 4.2, [
      { type: 'quality', keywords: ['材质薄', 'thin material', '拉链卡顿', 'zipper stuck', '触屏不灵敏', 'touch screen issue'] },
      { type: 'function', keywords: ['安装难度', 'installation', '收纳空间', 'storage space', '防踢保护', 'kick protection'] },
      { type: 'logistics', keywords: ['尺寸不符', 'size mismatch', '气味', 'smell'] },
    ]),
  },
  {
    asin: 'B0CXXXX012',
    title: 'Digital Food Scale Kitchen Weight Grams and Ounces, 0.1g Precise Graduation 11lb/5kg Capacity Food Scale for Cooking Baking Meal Prep, Tare Function LCD Display',
    brand: 'ScaleRight',
    price: 13.99,
    currency: 'USD',
    category: 'kitchen_dining',
    category_path: ['Home & Kitchen', 'Kitchen & Dining', 'Kitchen Scales'],
    marketplace: 'amazon_us',
    estimated_monthly_sales: 2800,
    bsr_rank: 2567,
    bsr_category: 'Digital Kitchen Scales',
    review_count: 312,
    rating: 4.0,
    weight_lbs: 0.4,
    dimensions: '8x6x1',
    main_image: '/mock/products/B0CXXXX012.png',
    images: [
      '/mock/products/B0CXXXX012.png',
      '/mock/products/B0CXXXX012.png',
      '/mock/products/B0CXXXX012.png',
    ],
    title_score: 75,
    bullet_score: 71,
    image_score: 80,
    overall_listing_score: 75,
    cost_price: 2.80,
    fba_fees: 1.98,
    referral_fee_pct: 15.0,
    roi_estimated: 15.8,
    net_profit: 3.41,
    blue_ocean_score: 28,
    selling_points: [
      '0.1g 高精度 + 5kg 大称量，烘焙烹饪都精准',
      '克/盎司/毫升多单位切换，一键去皮',
      'LCD 大屏 + 触控按键，清洁无缝隙',
      'AAA 电池供电 + 自动关机，省电耐用',
    ],
    bullet_points: [
      { title: '0.1G PRECISION GRADUATION', content: 'High-precision sensors measure in 0.1g increments from 1g to 5000g. Perfect for baking, coffee brewing, meal prep, and jewelry making.' },
      { title: '5 UNIT CONVERSIONS', content: 'Switch seamlessly between grams, ounces, pounds, milliliters, and fluid ounces. Tare function zeros out container weight instantly.' },
      { title: 'SLEEK LCD DISPLAY', content: 'Large backlit LCD screen shows measurements clearly even in low light. Touch-sensitive buttons wipe clean in seconds.' },
      { title: 'COMPACT STORAGE', content: 'Slim profile stores easily in drawers or cabinets. Tempered glass surface is scratch-resistant and easy to wipe clean.' },
      { title: 'AUTO-OFF & BATTERY SAVER', content: '2-minute auto-shutoff extends battery life. Includes 2 AAA batteries — ready to use right out of the box.' },
    ],
    description: 'Achieve perfect results in the kitchen with the ScaleRight Digital Food Scale. Whether you\'re baking artisan bread, brewing pour-over coffee, or portioning meals for weight loss, the 0.1g precision ensures exact measurements every time. Five unit conversions (g/oz/lb/ml/fl.oz) and a one-touch tare function make switching between ingredients effortless. The sleek tempered glass surface and touch-sensitive buttons are not only beautiful but also incredibly easy to clean. Slim enough to store in a drawer yet durable enough for daily use.',
    keywords: ['food scale', 'digital kitchen scale', 'kitchen scale', 'baking scale', 'coffee scale', '0.1g scale', 'gram scale', 'food weighing scale', 'meal prep scale', 'precision kitchen scale'],
    competitor_asins: ['B07SCALE99', 'B08KITCHSC', 'B09BAKE99'],
    rating_breakdown: { 5: 79, 4: 14, 3: 4, 2: 2, 1: 1 },
    has_a_plus: true,
    has_video: false,
    listed_date: '2024-11-15',
    last_updated: '2026-08-19',
    reviews: generateReviews('B0CXXXX012', 312, 4.0, [
      { type: 'quality', keywords: ['精度不准', 'accuracy', '电池盖', 'battery cover', '屏幕模糊', 'screen blur'] },
      { type: 'function', keywords: ['单位切换', 'unit conversion', '去皮功能', 'tare function', '自动关机', 'auto off'] },
      { type: 'quality', keywords: ['按键失灵', 'button malfunction', '做工粗糙', 'build quality'] },
    ]),
  },
]


// ====== 竞品对比 Mock 数据 ======

export function getMockCompetitorComparison(asins: string[]): MockCompetitorCompareResult {
  const competitors = asins.map(asin => {
    const product = MOCK_PRODUCTS.find(p => p.asin === asin)
    if (!product) return null

    // 根据评分生成优劣势
    const isLeader = product.blue_ocean_score >= 65
    const isWeak = product.blue_ocean_score < 40

    return {
      asin: product.asin,
      title: product.title.slice(0, 60) + (product.title.length > 60 ? '...' : ''),
      brand: product.brand,
      price: product.price,
      rating: product.rating,
      review_count: product.review_count,
      bsr_rank: product.bsr_rank,
      listing_quality_score: product.overall_listing_score,
      title_score: product.title_score,
      image_score: product.image_score,
      bullet_score: product.bullet_score,
      a_plus_content: Math.random() > 0.7,
      price_positioning: product.price < 20 ? 'budget' : product.price < 35 ? 'mid-range' : 'premium' as const,
      strengths: isLeader
        ? ['高评分低竞争', 'Listing 质量优秀', '利润空间充足']
        : ['价格有竞争力', '销量稳定'],
      weaknesses: isWeak
        ? ['评论数过多竞争激烈', 'ROI 偏低', '差异化不足']
        : ['品牌知名度有限', 'A+ Content 缺失'],
      sponsored_rank: Math.floor(Math.random() * 50) + 1,
      estimated_ppc: parseFloat((Math.random() * 2 + 0.5).toFixed(2)),
    } as MockCompetitor
  }).filter(Boolean) as MockCompetitor[]

  const best = competitors.reduce((a, b) =>
    (a?.listing_quality_score || 0) > (b?.listing_quality_score || 0) ? a : b
  )

  return {
    compared_asins: asins,
    comparison_summary:
      `共对比 ${competitors.length} 个竞品。` +
      `最佳 Listing：「${best?.title?.slice(0, 25)}...」` +
      `(综合评分 ${best?.listing_quality_score})。` +
      `市场呈现"一超多强"格局，头部产品占据约${Math.floor(35 + Math.random() * 30)}%市场份额。`,
    recommendation:
      best
        ? `建议参考「${best.brand}」的 Listing 结构和图片风格，同时避免「${
            competitors[competitors.length - 1]?.brand
          }」的定价策略。`
        : '建议深入分析各竞品的用户评价，寻找差异化切入点。',
    competitors,
    price_range: {
      min: Math.min(...competitors.map(c => c.price)),
      max: Math.max(...competitors.map(c => c.price)),
    },
    avg_rating: parseFloat(
      (competitors.reduce((sum, c) => sum + c.rating, 0) / competitors.length).toFixed(1)
    ),
    market_leader: best?.asin || '',
    opportunity_areas: [
      '中高端价位段存在空白',
      '环保材料认证是差异化机会',
      '套装组合销售潜力未释放',
      '视频内容营销可提升转化率',
    ],
  }
}


// ====== 痛点分析 Mock 数据 ======

export function getMockPainPointAnalysis(asin: string): MockPainPointAnalysis {
  const product = MOCK_PRODUCTS.find(p => p.asin === asin)
  if (!product) {
    throw new Error(`Product not found: ${asin}`)
  }

  const negativeReviews = product.reviews.filter(r => r.sentiment === 'negative')

  // 统计痛点频率
  const painMap = new Map<string, { count: number; category: string; examples: string[] }>()
  negativeReviews.forEach(review => {
    (review.pain_points || []).forEach(point => {
      if (!painMap.has(point)) {
        painMap.set(point, { count: 0, category: review.category || '未知', examples: [] })
      }
      const entry = painMap.get(point)!
      entry.count++
      if (entry.examples.length < 2) {
        entry.examples.push(review.review_id)
      }
    })
  })

  // 排序并转换为数组
  const totalNegative = negativeReviews.length
  const painPoints: PainPointItem[] = Array.from(painMap.entries())
    .map(([point, data]) => ({
      pain_point: point,
      count: data.count,
      percentage: parseFloat(((data.count / totalNegative) * 100).toFixed(1)),
      severity: data.count > totalNegative * 0.3 ? 'high' as const :
               data.count > totalNegative * 0.15 ? 'medium' as const : 'low' as const,
      category: data.category,
      example_review_id: data.examples[0] || '',
    }))
    .sort((a, b) => b.count - a.count)

  // 生成改进建议
  const improvementSuggestions = [
    ...painPoints.filter(p => p.severity === 'high').map(p =>
      `优先解决高频痛点：「${p.pain_point}」（占比 ${p.percentage}%）`
    ),
    '在 Listing 五点描述中主动回应常见差评问题',
    '考虑增加产品质保期或无忧退货承诺',
    '优化包装减少运输损坏导致的差评',
    '制作 FAQ 视频解答用户常见疑问',
  ]

  return {
    product_asin: asin,
    total_reviews_analyzed: product.review_count,
    negative_review_count: totalNegative,
    positive_review_count: product.reviews.filter(r => r.sentiment === 'positive').length,
    pain_points: painPoints,
    improvement_suggestions: improvementSuggestions.slice(0, 6),
    market_gap_score: Math.min(
      Math.round(100 - (product.review_count / 5) + (product.rating * 10)),
      95
    ),
    competitor_weaknesses: [
      '竞品普遍存在同类质量问题但未回应',
      '市场上缺乏针对该痛点的解决方案型产品',
      '用户对现有产品的满意度有提升空间',
    ],
  }
}


// ====== BSR 趋势 Mock 数据 ======

export function getMockBSRTrend(asin: string, days: number = 90): MockBSRTrend[] {
  const product = MOCK_PRODUCTS.find(p => p.asin === asin)
  if (!product) return []

  const baseRank = product.bsr_rank
  const baseSales = product.estimated_monthly_sales
  const basePrice = product.price
  const trend: MockBSRTrend[] = []

  const now = new Date()
  for (let i = days; i >= 0; i--) {
    const date = new Date(now)
    date.setDate(date.getDate() - i)

    // 模拟波动趋势
    const seasonality = Math.sin(i / 15) * 0.15  // 季节性波动
    const noise = (Math.random() - 0.5) * 0.1    // 随机噪声
    const trend_factor = 1 - (i / days) * 0.1     // 整体趋势（轻微上升）

    const rankVariation = 1 + seasonality + noise + trend_factor
    const salesVariation = 1 / rankVariation + noise * 0.5
    const priceVariation = 1 + (Math.random() - 0.5) * 0.02  // 价格微调 ±1%

    trend.push({
      date: date.toISOString().split('T')[0],
      bsr_rank: Math.round(baseRank * rankVariation),
      category_rank: Math.round(baseRank * rankVariation * (0.8 + Math.random() * 0.4)),
      estimated_sales: Math.round(baseSales * salesVariation),
      price_history: parseFloat((basePrice * priceVariation).toFixed(2)),
    })
  }

  return trend
}


// ====== 工具函数 ======

/**
 * 根据 ASIN 获取商品完整信息
 */
export function getProductByASIN(asin: string): MockProduct | undefined {
  return MOCK_PRODUCTS.find(p => p.asin === asin)
}

/**
 * 按类目获取商品列表
 */
export function getProductsByCategory(category: string): MockProduct[] {
  return MOCK_PRODUCTS.filter(p => p.category === category)
}

/**
 * 按蓝海评分排序（降序）
 */
export function getProductsSortedByBlueOceanScore(limit?: number): MockProduct[] {
  const sorted = [...MOCK_PRODUCTS].sort((a, b) => b.blue_ocean_score - a.blue_ocean_score)
  return limit ? sorted.slice(0, limit) : sorted
}

/** 用 ASIN 尾部数字做确定性种子（避免每次刷新跳动） */
function seededByAsin(asin: string): number {
  const m = asin.match(/(\d+)$/)
  return m ? Number(m[1]) : 0
}

/**
 * 生成蓝海挖掘候选（增强字段版）
 * 在按蓝海评分排序的基础上，为每条附加变体数/卖家数/头程/趋势等
 * 「类目判断、竞争结构」所需字段（mock 为确定性演示值，非真实抓取）。
 */
export function getBlueOceanCandidates(limit?: number): MockProduct[] {
  const base = getProductsSortedByBlueOceanScore(limit)
  return base.map(p => {
    const seed = seededByAsin(p.asin)
    // 变体数：越接近中部说明子款合理；用 seed 确定性映射 1~9
    const variation = (seed % 9) + 1
    // 头程：按重量粗估（$3/磅 空运 + 尾程），至少 1.5
    const freight = Math.max(Math.round((p.weight_lbs * 2.6 + 1.2) * 100) / 100, 1.2)
    // 卖家数：少卖家=更蓝海，倾向给低值；seed 确定性 1~7
    const sellers = (seed % 7) + 1
    // 趋势：价格波动 ±8%，销量波动 ±25%（确定性）
    const priceT = ((seed * 7) % 17) - 8
    const salesT = ((seed * 13) % 51) - 25
    const owned = seed % 5 === 0 // 约 1/5 亚马逊自营
    const [l1, l2] = p.category_path || []
    return {
      ...p,
      category_l1: l1 || p.category,
      category_l2: l2 || '',
      variation_count: variation,
      freight_cost: freight,
      seller_count: sellers,
      is_amazon_owned: owned,
      price_trend_30d: priceT,
      sales_trend_30d: salesT,
    }
  })
}

/**
 * 获取指定商品的评论
 */
export function getReviewsByASIN(asin: string): MockReview[] {
  const product = MOCK_PRODUCTS.find(p => p.asin === asin)
  return product?.reviews || []
}

/**
 * 获取指定商品的负面评论（用于痛点分析）
 */
export function getNegativeReviewsByASIN(asin: string): MockReview[] {
  return getReviewsByASIN(asin).filter(r => r.sentiment === 'negative')
}
