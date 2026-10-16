/**
 * 类目中文化口径单元测试（r365b）
 * ==================================
 * 真源 = `config/categoryTaxonomy.ts` 的 `CATEGORY_ZH` + `displayCategory`。
 *
 * 老板点名的风险原话是「treemap 和短标签展示是联动的，你要统一口径」——
 * 本文件钉住的正是「口径只有一份」：
 *   1. taxonomy 的每个 label 都必须可译（漏译 ⇒ cascader / 组标题条漏出英文）；
 *   2. 后端 seed 与前端已有数据里出现的三级细分品类同样必须可译；
 *   3. 未收录 ⇒ **原样返回英文**（fail-visible：漏收录一眼可见，不造中文不留空）；
 *   4. 两档：narrow 纯中文（窄容器）、wide 中英对照（宽容器）——中文名必然同源；
 *   5. 截断按**显示宽度**而非字符数（中文化后「字符数」口径完全失效）。
 *
 * 末尾一组是**源码形态**判据：钉住已废弃的旧写法不再回流（这类缺陷
 * 「改错一行也不会报错，只是界面又开始漏英文」，行为用例抓不到）。
 */

import { readFileSync } from 'node:fs'
import path from 'node:path'
import { fileURLToPath } from 'node:url'
import { describe, expect, it } from 'vitest'
import {
  CATEGORY_TAXONOMY,
  CATEGORY_ZH,
  displayCategory,
  displayWidth,
  truncateByWidth,
  zhName,
} from '@/config/categoryTaxonomy'

/** 前端仓库根（本文件位于 <frontend>/tests/unit/） */
const FRONTEND_ROOT = path.resolve(fileURLToPath(new URL('../..', import.meta.url)))

function readSrc(rel: string): string {
  return readFileSync(path.join(FRONTEND_ROOT, rel), 'utf8')
}

/** taxonomy 两级 label 全平铺（cascader 子项 / 组标题条 / 色块名同源） */
function taxonomyLabels(): string[] {
  const out: string[] = []
  for (const t of CATEGORY_TAXONOMY) {
    out.push(t.label)
    for (const c of t.children ?? []) out.push(c.label)
  }
  return out
}

/** 后端 seed（modules/product_research/seed.py 的 category_name）实测全集 */
const SEED_LEAF_NAMES = [
  'Coffee Machines',
  'Phone Stands',
  'Smart Lighting',
  'Water Bottles',
  'Kitchen Storage',
  'Face Serums',
  'STEM Kits',
  'Dog Chew Toys',
]

/**
 * 站点数据里已出现的三级细分品类（含不在 taxonomy 内的那条路径）。
 * ★ 正是「不在体系内」的这几个最危险：midLabel 未命中时兜底叶子名，
 *   若术语表也没收 ⇒ 中文块旁边直接漏一块英文（老板说的「口径不统一」）。
 */
const DATA_LEAF_NAMES = [
  'Humidifiers',
  'Cooking Utensils',
  'Grow Lights',
  'Milk Frothers',
  'Storage Organizers',
  'Resistance Bands',
  'Cutting Boards',
  'Chargers',
  'Nebulizers',
  'Seat Back Organizers',
  'Kitchen Scales',
  // 体系外的一级/二级（数据里出现过）——同样必须可译
  'Health & Personal Care',
  'Respiratory Aids',
  'Automotive',
  'Interior Accessories',
  'Fitness Accessories',
]

describe('CATEGORY_ZH —— 唯一真源', () => {
  it('每个键都有非空的中文值（不允许空串占位）', () => {
    const bad = Object.entries(CATEGORY_ZH).filter(
      ([k, v]) => !k.trim() || !v.trim() || !/[\u3400-\u9fff]/.test(v),
    )
    expect(bad).toEqual([])
  })

  it('中文值不重复（防复制粘贴错位：两个类目指向同一中文）', () => {
    const values = Object.values(CATEGORY_ZH)
    const dup = values.filter((v, i) => values.indexOf(v) !== i)
    expect(dup).toEqual([])
  })

  it('★ taxonomy 每个 label 都可译（漏一个 ⇒ cascader 或组标题条漏出英文）', () => {
    const missing = taxonomyLabels().filter((l) => zhName(l) === undefined)
    expect(missing).toEqual([])
  })

  it('★ 后端 seed 的 category_name 全可译', () => {
    const missing = SEED_LEAF_NAMES.filter((n) => zhName(n) === undefined)
    expect(missing).toEqual([])
  })

  it('★ 数据里出现的三级细分品类（含 taxonomy 外路径）全可译', () => {
    const missing = DATA_LEAF_NAMES.filter((n) => zhName(n) === undefined)
    expect(missing).toEqual([])
  })

  it('未收录返回 undefined（调用方自行兜底，不静默编一个中文）', () => {
    expect(zhName('Seafood & Raw Bar')).toBeUndefined()
    expect(zhName('')).toBeUndefined()
  })
})

describe('displayCategory —— 两档口径（中文名同源，只差带不带英文）', () => {
  it('narrow = 纯中文（treemap 色块 / 组标题条等窄容器）', () => {
    expect(displayCategory('Kitchen & Dining', 'narrow')).toBe('厨房与餐饮')
    expect(displayCategory('Home & Kitchen', 'narrow')).toBe('家居与厨房')
  })

  it('wide = 中文（English）（cascader / tooltip / 详情抽屉等宽容器）', () => {
    expect(displayCategory('Kitchen & Dining', 'wide')).toBe('厨房与餐饮（Kitchen & Dining）')
  })

  it('默认档 = narrow（窄容器是多数调用点，漏传时不至于把英文塞满色块）', () => {
    expect(displayCategory('Kitchen & Dining')).toBe('厨房与餐饮')
  })

  it('★ 未收录 ⇒ 原样返回英文（fail-visible），两档行为一致', () => {
    expect(displayCategory('Seafood & Raw Bar', 'narrow')).toBe('Seafood & Raw Bar')
    expect(displayCategory('Seafood & Raw Bar', 'wide')).toBe('Seafood & Raw Bar')
  })

  it('空串 ⇒ 空串（不抛错，调用方用 `|| "-"` 兜底）', () => {
    expect(displayCategory('')).toBe('')
  })

  it('★ 两档共享同一份中文名（防「treemap 一种译法、短标签另一种」）', () => {
    for (const k of Object.keys(CATEGORY_ZH)) {
      const narrow = displayCategory(k, 'narrow')
      const wide = displayCategory(k, 'wide')
      expect(wide.startsWith(narrow), `${k}: wide 未以 narrow 开头`).toBe(true)
    }
  })
})

describe('displayWidth / truncateByWidth —— 中文化后的截断口径', () => {
  it('半角记 1、CJK 记 2', () => {
    expect(displayWidth('abc')).toBe(3)
    expect(displayWidth('厨房')).toBe(4)
    expect(displayWidth('Home & Kitchen')).toBe(14)
    expect(displayWidth('家居与厨房 · US')).toBe(15)
  })

  it('未超宽原样返回', () => {
    expect(truncateByWidth('Home & Kitchen', 22)).toBe('Home & Kitchen')
    expect(truncateByWidth('家居与厨房 · US', 22)).toBe('家居与厨房 · US')
  })

  it('★ 22 个汉字必须被截断 —— 旧的 `length > 22` 口径会整串放行（≈44 半角宽）', () => {
    const s = '一'.repeat(22)
    expect(s.length).toBe(22) // 旧口径：不截断（这就是缺陷）
    const cut = truncateByWidth(s, 22)
    expect(cut).not.toBe(s)
    expect(cut.endsWith('…')).toBe(true)
    expect(displayWidth(cut)).toBeLessThanOrEqual(22)
  })

  it('截断结果宽度永不超过 maxWidth', () => {
    const samples = ['Home & Kitchen', '家居与厨房 · US', '一'.repeat(30), 'Kitchen & Dining', 'a'.repeat(50)]
    for (const s of samples) {
      for (const w of [4, 8, 14, 22]) {
        expect(displayWidth(truncateByWidth(s, w)), `${s} @ ${w}`).toBeLessThanOrEqual(w)
      }
    }
  })

  it('★ 全部中文类目（含站点后缀）都在 treemap 截断阈值内 —— 中文名不该被砍', () => {
    const overlong = Object.keys(CATEGORY_ZH)
      .map((k) => `${displayCategory(k, 'narrow')} · US`)
      .filter((s) => displayWidth(s) > 22)
    expect(overlong).toEqual([])
  })
})

describe('源码形态门禁 —— 已废弃的旧写法不得回流', () => {
  it('★ MarketInsightConfig 色块名必须经过 displayCategory（不得裸用 midLabel 结果）', () => {
    const src = readSrc('src/components/TaskConfigPanel/configs/MarketInsightConfig.vue')
    expect(src).toContain('displayCategory(')
    // 旧形态：`name: \`${midName} · ...\``（midName 直取 midLabel 结果，不过术语表）
    expect(src).not.toContain('name: `${midName} · ')
    expect(src).not.toContain('group: topLabel(top) ?? top')
  })

  it('★ treemap 截断必须走显示宽度（不得回到 name.length 口径）', () => {
    const src = readSrc('src/components/charts/EChartsTreemap.vue')
    expect(src).toContain('truncateByWidth(')
    expect(src).not.toContain('name.length > 22')
  })

  it('四个类目消费点都已接入 displayCategory', () => {
    const files = [
      'src/components/TaskConfigPanel/configs/MarketInsightConfig.vue',
      'src/components/TaskConfigPanel/configs/BlueOceanConfig.vue',
      'src/components/ChatPanel/results/BlueOceanDetailDrawer.vue',
      'src/components/ChatPanel/results/BlueOceanResult.vue',
    ]
    for (const f of files) {
      expect(readSrc(f), f).toContain('displayCategory')
    }
  })

  it('★ cascader 选项 label 走 displayCategory（value 仍是 slug，不得被中文化）', () => {
    const src = readSrc('src/components/TaskConfigPanel/configs/BlueOceanConfig.vue')
    expect(src).toContain("displayCategory(t.label, 'wide')")
    expect(src).toContain('value: t.value')
  })
})
