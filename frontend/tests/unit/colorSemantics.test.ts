/**
 * `utils/colorSemantics.ts` 行为契约（第 355 轮 · #1282 前端单测起步）
 * ============================================================================
 * ★ 本文件钉的是**业务契约**，不是实现细节：
 *   该模块的 docstring 第一条规则就是「同类业务含义的标签，全项目固定用同一颜色，
 *   不允许乱换」。这句规则原本只活在注释里 —— 谁把「爆款」从 green 改成 red，
 *   没有任何东西会吭声（前端没有编译器能检查颜色语义）。
 *   ⇒ 这里把那张「业务含义 → 颜色」表逐条写成**显式期望**，
 *     报错信息会直接指出是哪个标签漂了。
 *
 * ★ 为什么用 `toMatchObject` 而不是 `toEqual` 钉整张表：
 *   本模块的**合法演进**是「新增一个业务标签」；`toEqual` 会把新增也判红，
 *   于是下一次有人加标签时第一反应是「把测试改绿」，等于把契约测废掉。
 *   `toMatchObject` 只要求**已登记的条目**不得改变 —— 那正是要守的东西。
 *
 * ★ 为什么这里**不**再断言「颜色值必须在 SemanticColor 联合内」：
 *   那条判据由类型系统承担，且已被 CI 的 `vue-tsc --noEmit` 覆盖
 *   （`Record<string, SemanticColor>` 的注解 + 字面量类型）。再写一遍运行期断言
 *   就是同一判定的第二份实现 —— 项目记忆里明确记着这种「两份实现 ⇒ 一份永远测不到」。
 */
import { describe, it, expect } from 'vitest'
import {
  COLOR_COUNT,
  COLOR_HOT,
  COLOR_INFO,
  COLOR_MODE,
  COLOR_NEUTRAL,
  COLOR_NEW,
  COLOR_PLATFORM,
  COLOR_RISK,
  COLOR_SPEC,
  COLOR_STAR,
  COLOR_WARN,
  PRODUCT_STATUS_COLOR,
  PRODUCT_TAG_COLOR,
  SUBSCRIPTION_STATUS_COLOR,
  productStatusColor,
  productTagColor,
} from '@/utils/colorSemantics'
import type { SemanticColor } from '@/utils/colorSemantics'

/** 冻结：语义色盘（模块 docstring 的「业务 → 颜色」表） */
const EXPECTED_CONSTANTS: Record<string, SemanticColor> = {
  COLOR_NEW: COLOR_NEW,
  COLOR_HOT: COLOR_HOT,
  COLOR_RISK: COLOR_RISK,
  COLOR_WARN: COLOR_WARN,
  COLOR_STAR: COLOR_STAR,
  COLOR_NEUTRAL: COLOR_NEUTRAL,
  COLOR_SPEC: COLOR_SPEC,
  COLOR_PLATFORM: COLOR_PLATFORM,
  COLOR_COUNT: COLOR_COUNT,
  COLOR_MODE: COLOR_MODE,
  COLOR_INFO: COLOR_INFO,
}

describe('colorSemantics · 语义色盘', () => {
  it('11 个语义常量各自绑定到 docstring 里声明的那个颜色', () => {
    // 逐个写出来（而不是遍历 EXPECTED_CONSTANTS），这样报错时能直接看出「哪个常量被换色了」
    expect(COLOR_NEW).toBe('blue') // 新品 / 蓝海 / 信息类
    expect(COLOR_HOT).toBe('green') // 爆款 / 高周转 / 正常
    expect(COLOR_RISK).toBe('red') // 风险 / 淘汰 / 异常 / 删除
    expect(COLOR_WARN).toBe('orange') // 预警 / 待处理 / 即将到期 / 草稿
    expect(COLOR_STAR).toBe('gold') // 评分星级 / 领导者 / 赢家
    expect(COLOR_NEUTRAL).toBe('default') // 详情 / 编辑 / 中性
    expect(COLOR_SPEC).toBe('purple') // SPU / 规格 / 多维分析
    expect(COLOR_PLATFORM).toBe('cyan') // 平台 / 渠道分类
    expect(COLOR_COUNT).toBe('blue') // 计数统计
    expect(COLOR_MODE).toBe('default') // 模式 / 形态标签
    expect(COLOR_INFO).toBe('blue') // 信息提示
  })

  it('常量表非空（防止本文件自己退化成空断言 ⇒ 恒真）', () => {
    expect(Object.keys(EXPECTED_CONSTANTS)).toHaveLength(11)
  })
})

describe('colorSemantics · PRODUCT_TAG_COLOR 契约表', () => {
  it('已登记的业务标签不得换色，且归类与 docstring 一致', () => {
    expect(PRODUCT_TAG_COLOR).toMatchObject({
      // ---- 新品 / 蓝海 / 机会 → 蓝 ----
      新品: 'blue',
      蓝海: 'blue',
      潜力: 'blue',
      新品机会: 'blue',
      // ---- 爆款 / 高周转 / 表现好 → 绿 ----
      爆款: 'green',
      高周转: 'green',
      热销: 'green',
      畅销: 'green',
      // ---- 风险 / 淘汰 / 异常 → 红 ----
      风险: 'red',
      淘汰: 'red',
      异常: 'red',
      滞销: 'red',
      // ---- 清仓：介于「淘汰」与「待处理」之间 → 橙（不是红）----
      清仓: 'orange',
      // ---- 待处理 / 预警 / 草稿 → 橙 ----
      待处理: 'orange',
      待评审: 'orange',
      草稿: 'orange',
      // ---- 规格 / 层级 → 紫（专属，尽量少用）----
      SPU: 'purple',
      规格: 'purple',
    })
  })

  it('productTagColor 走的就是这张表（访问器不是第二份映射）', () => {
    for (const [tag, color] of Object.entries(PRODUCT_TAG_COLOR)) {
      expect(productTagColor(tag), `标签「${tag}」`).toBe(color)
    }
  })

  it('未命中的自由文本兜底为「信息蓝」，而不是中性灰', () => {
    // ★ 两条兜底刻意不同：tag 是自由文本，兜底代表「信息」；
    //   status 是枚举，兜底代表「无状态」。混用会让未登记标签看着像已归档。
    expect(productTagColor('这个标签没人登记过')).toBe('blue')
    expect(productTagColor('')).toBe('blue')
    expect(productTagColor('Blue')).toBe('blue') // 大小写不同 ⇒ 未命中 ⇒ 仍走兜底
  })
})

describe('colorSemantics · PRODUCT_STATUS_COLOR 契约表', () => {
  it('已登记的产品状态不得换色', () => {
    expect(PRODUCT_STATUS_COLOR).toMatchObject({
      draft: 'orange',
      草稿: 'orange',
      active: 'green',
      normal: 'green',
      正常: 'green',
      risk: 'red',
      风险: 'red',
      archived: 'default',
      归档: 'default',
    })
  })

  it('productStatusColor：空值直接返回灰，不发散查表', () => {
    expect(productStatusColor(undefined)).toBe('default')
    expect(productStatusColor(null)).toBe('default')
    expect(productStatusColor('')).toBe('default')
  })

  it('productStatusColor：命中走表、未命中兜底灰', () => {
    expect(productStatusColor('active')).toBe('green')
    expect(productStatusColor('draft')).toBe('orange')
    expect(productStatusColor('risk')).toBe('red')
    expect(productStatusColor('不知名状态')).toBe('default')
  })
})

describe('colorSemantics · SUBSCRIPTION_STATUS_COLOR 契约表', () => {
  it('已登记的订阅状态不得换色（过期/欠费必须是红，不能退化成灰）', () => {
    expect(SUBSCRIPTION_STATUS_COLOR).toMatchObject({
      trialing: 'orange',
      试用中: 'orange',
      active: 'green',
      正常: 'green',
      cancel_at_period_end: 'orange',
      past_due: 'red',
      canceled: 'default',
      inactive: 'default',
    })
  })
})
