#!/usr/bin/env node
/**
 * 前端「空态不得撒谎」门禁（★ 第 280 轮）
 *
 * 为什么值得单独一个门禁
 * ====================
 * 异步取数失败时，界面有两种写法，用户看到的却是**完全相反的操作指引**：
 *
 *   · 说「暂无数据」 ⇒ 用户去**添加**（以为库里本来就没有）
 *   · 说「加载失败，请重试」⇒ 用户去**重试**（本来就有数据，只是没取到）
 *
 * 这个仓为此吃过两次亏，而且**每次都是「修了一半」**：
 *   第 271 轮：`productLibrary` / `assetLibrary` 的 catch 从「灌 mock 假数据」
 *              改成「置空 + 记 `loadError`」—— 假数据没了 ✓，
 *              但 `loadError` **没有任何界面消费点**（全仓 grep 只找得到定义），
 *              于是界面从「一屏假数据」变成「一屏空白」，仍然在撒谎（说"没有"）。
 *   第 279 轮：`candidateLibrary` 是同族第 3 处，连「置空」都还没做。
 *   第 280 轮：`Subscription.vue` 的套餐/账单补上了完整半边（失败态 + 重试），
 *              回头把上面 3 个库一起接上，并把口径**收成一个组件**。
 *
 * ⇒ 判据不能只守「catch 里别灌 mock」（那是 `check-mock-retirement.cjs` 的 A7），
 *   还要守「**失败态有没有真的被呈现出来**」。两种缺陷是一体两面。
 *
 * 与相邻门禁的分工
 * ================
 *   · `check-mock-retirement.cjs` A7 —— 读失败**不许伪造数据**（赋值面：catch 里别灌 mock）
 *   · 本门禁 D1/D2/D3       —— 读失败**必须说真话**（呈现面：失败态有没有上屏、口径是否唯一）
 *   · `check-theme-var-refs.py` —— 呈现用的 CSS 变量存不存在（视觉面）
 * 三者互补：A7 管「别编数据」，本门禁管「要说明白」，主题门禁管「说明白的那句话能不能看清」。
 *
 * 判据组
 * ======
 *   D1 统一组件 `src/components/common/AsyncEmpty.vue` 存在
 *   D2 组件契约正确：
 *       · 失败态与空态**互斥**（`:description="error ? … : …"`）——
 *         不允许两条文案并存（「暂无数据」+「加载失败」摆在一起自相矛盾）
 *       · 失败文案里含「加载失败」（固定人话，不把 axios 的原文铺到界面上）
 *       · `error` 非空时有「重试」出口（按钮 + `emit('retry')`）
 *   D3 消费点数据流（**逐调用点判**，不数总数）：
 *       · 清单里每个 `<AsyncEmpty>` 都必须带 `:error` 绑定（漏了 ⇒ 失败态永远不显示）
 *       · label 语义清单齐全（订阅页 套餐/账单；三库 产品库/素材库/选品库）
 *   D4 反向：全仓不得再有**裸三元空态**（`:description="…加载失败…"`）绕过统一组件
 *   D5 自检：D4 匹配器的正/反对照（裸三元必命中；合法的 `:empty-description=` 三元
 *      与 `<AsyncEmpty>` 用法必不命中）
 *   D6 扫描面规模达标（否则 D4 会「因为什么都没扫到」而永远通过）
 *
 * 怎么跑
 * ======
 *   node scripts/check-empty-state-honesty.cjs
 *
 * 反向注入（证明本门禁不是空跑）
 * ============================
 *   python scripts/probe_empty_state_inject.py     # 副本树上的 4 组精确失败集
 */
const fs = require('fs')
const path = require('path')

const ROOT = path.resolve(__dirname, '..')

/**
 * 扫描根：默认 `frontend/src`。
 * `EMPTY_STATE_SRC_ROOT` 供**反向注入台架**（probe_empty_state_inject.py）把扫描面
 * 指向一份副本树 —— 这样注入只改副本、绝不动工作区。
 */
const SRC = process.env.EMPTY_STATE_SRC_ROOT
  ? path.resolve(process.env.EMPTY_STATE_SRC_ROOT)
  : path.join(ROOT, 'src')

const COMPONENT_REL = 'components/common/AsyncEmpty.vue'
const COMPONENT_ABS = path.join(SRC, COMPONENT_REL)

/** 允许的扫描根（`.vue` 是唯一会写 `:description=` 的地方；.ts 也顺带扫） */
const MIN_SCANNED = 80

/** 消费点语义清单：文件 -> 必须齐备的 label（不钉「总数」，钉「哪些语义在场」） */
const CONSUMERS = [
  ['views/Subscription.vue', ['套餐', '账单']],
  ['components/KnowledgeBase/ProductLibrary.vue', ['产品库']],
  ['components/KnowledgeBase/AssetLibrary.vue', ['素材库']],
  ['components/KnowledgeBase/CandidateLibrary.vue', ['选品库']],
]

// ---------------------------------------------------------------- 工具

/** 剥 // 与 块注释，但**保留字符串里的 `//`**（否则 https:// 会被吃掉） */
function stripComments(text) {
  let out = ''
  let i = 0
  const n = text.length
  while (i < n) {
    const c = text[i]
    if (c === '/' && text[i + 1] === '/') {
      const j = text.indexOf('\n', i)
      i = j < 0 ? n : j
      continue
    }
    if (c === '/' && text[i + 1] === '*') {
      const j = text.indexOf('*/', i + 2)
      i = j < 0 ? n : j + 2
      continue
    }
    if (c === '"' || c === "'" || c === '`') {
      out += c
      i++
      while (i < n) {
        if (text[i] === '\\') {
          out += text[i] + text[i + 1]
          i += 2
          continue
        }
        out += text[i]
        if (text[i] === c) {
          i++
          break
        }
        i++
      }
      continue
    }
    out += c
    i++
  }
  return out
}

/** 切出每个 `<AsyncEmpty … />` 标签块（支持多行属性） */
function collectAsyncEmptyBlocks(text) {
  const blocks = []
  const re = /<AsyncEmpty\b/g
  let m
  while ((m = re.exec(text))) {
    const start = m.index
    const end = text.indexOf('/>', start)
    if (end < 0) continue
    blocks.push(text.slice(start, end + 2))
  }
  return blocks
}

/**
 * D4 的匹配器：`:description=" … 加载失败 … "` 就是「绕过统一组件、自己写失败文案」。
 * ★ 判「含『加载失败』字面量」而不是判「含 `Error` 变量名」——
 *   变量叫什么不可控，但**那句谎话的措辞**是可控的：真要说失败，必然出现「加载失败」。
 */
function findBareFailureDescription(text) {
  const hits = []
  const re = /:description="([^"]*)"/g
  let m
  while ((m = re.exec(text))) {
    if (m[1].includes('加载失败')) hits.push(m[0])
  }
  return hits
}

// ---------------------------------------------------------------- 扫描

const files = []
;(function walk(dir) {
  for (const e of fs.readdirSync(dir, { withFileTypes: true })) {
    if (e.name === 'node_modules' || e.name.startsWith('.')) continue
    const p = path.join(dir, e.name)
    if (e.isDirectory()) walk(p)
    else if (/\.(vue|ts)$/.test(e.name)) files.push(p)
  }
})(SRC)

const read = (abs) => stripComments(fs.readFileSync(abs, 'utf8'))

// ---------------------------------------------------------------- 判定

const results = []
function assert(cond, msg) {
  if (!cond) throw new Error(msg)
}
function check(name, fn) {
  try {
    fn()
    results.push({ ok: true, name })
  } catch (e) {
    results.push({ ok: false, name, msg: e.message })
  }
}

// ---- D1
check('D1 统一组件 src/components/common/AsyncEmpty.vue 存在', () => {
  assert(fs.existsSync(COMPONENT_ABS), `未找到 ${COMPONENT_REL}`)
})

// ---- D2
const compSrc = fs.existsSync(COMPONENT_ABS) ? read(COMPONENT_ABS) : ''

check('D2a 失败态与空态互斥（`:description="error ? … : …"`，不允许两条文案并存）', () => {
  assert(compSrc.length > 0, '组件不存在或为空')
  assert(
    /:description\s*=\s*"error\s*\?[^"]*:[^"]*"/.test(compSrc),
    '组件模板里没有以 `error` 为条件的三元 —— 失败文案与空态文案可能并存',
  )
  assert(
    compSrc.includes('加载失败'),
    '失败分支里没有「加载失败」字样 —— 失败态无法被识别',
  )
})

check('D2b `error` 非空时有「重试」出口（按钮 + emit retry）', () => {
  assert(/v-if\s*=\s*"error"/.test(compSrc), '重试按钮没有以 `v-if="error"` 挂在失败态上')
  assert(/emit\(\s*'retry'\s*\)/.test(compSrc), "按钮没有 emit('retry') —— 重试出口是断的")
  assert(/重试/.test(compSrc), '按钮文案里没有「重试」')
})

// ---- D3
const consumerDetails = []
check('D3a 清单里每个 <AsyncEmpty> 都绑定了 :error（漏了就永远显示不出失败态）', () => {
  for (const [rel, labels] of CONSUMERS) {
    const abs = path.join(SRC, rel)
    assert(fs.existsSync(abs), `消费点文件不存在：${rel}`)
    const text = read(abs)
    const blocks = collectAsyncEmptyBlocks(text)
    assert(blocks.length > 0, `${rel} 里没有任何 <AsyncEmpty> —— 空态口径没有收敛到统一组件`)
    blocks.forEach((b, i) => {
      assert(
        /:error\s*=/.test(b),
        `${rel} 的第 ${i + 1} 个 <AsyncEmpty> 没有绑定 :error ⇒ 失败态永远不会显示`,
      )
    })
    consumerDetails.push(`${rel.split('/').pop()} x${blocks.length}`)
  }
})

check('D3b label 语义清单齐全（订阅页 套餐/账单；三库 产品库/素材库/选品库）', () => {
  for (const [rel, labels] of CONSUMERS) {
    const text = read(path.join(SRC, rel))
    for (const lb of labels) {
      assert(
        text.includes(`label="${lb}"`),
        `${rel} 缺少 label="${lb}" —— 失败文案会说不清是**哪个**资源没加载出来`,
      )
    }
  }
})

// ---- D4
const bare = []
check('D4 全仓无「裸三元空态」（`:description="…加载失败…"` 绕过统一组件）', () => {
  for (const abs of files) {
    const rel = path.relative(SRC, abs).split(path.sep).join('/')
    if (rel === COMPONENT_REL) continue // 组件自身就是那个「真源」，豁免
    const hits = findBareFailureDescription(read(abs))
    for (const h of hits) bare.push(`${rel} :: ${h.slice(0, 80)}`)
  }
  assert(bare.length === 0, `仍有 ${bare.length} 处裸三元：\n      ${bare.join('\n      ')}`)
})

// ---- D5
check('D5 自检：D4 匹配器正反对照（裸三元必命中；合法写法必不命中）', () => {
  // 正向：这就是被收掉的那个形态
  const bad = `<a-empty :description="invoicesError ? '账单加载失败，请重试' : '暂无账单记录'" />`
  assert(
    findBareFailureDescription(bad).length === 1,
    '自检正向样本（裸三元失败文案）未被命中 —— 匹配器坏了，D4 是空跑',
  )
  // 反 1：组件内部的**正确**写法（以 error 为条件，但用变量不是字面量）
  const good1 = `<a-empty :description="error ? \`\${label}加载失败，请重试\` : emptyDescription">`
  assert(
    findBareFailureDescription(good1).length === 1, // 组件内部本就该写「加载失败」
    '反例 1 不应被当作违规（它在区分：组件内部是允许的，只有**非组件文件**里出现才算违规）',
  )
  // 反 2：合法的空态三元（含 `?` 但不含「加载失败」）—— 这是 AssetLibrary/CandidateLibrary 的实测用法
  const good2 = `<AsyncEmpty :empty-description="store.hasActiveFilters ? '没有匹配的候选' : '选品库为空'" />`
  assert(
    findBareFailureDescription(good2).length === 0,
    '反例 2（合法空态三元）被误命中 —— D4 会假红，而假红灯会让人把门禁关掉',
  )
  // 反 3：统一组件的正常调用（错误文案不落在这个属性上）
  const good3 = `<AsyncEmpty :error="store.loadError" label="产品库" empty-description="产品库为空" />`
  assert(
    findBareFailureDescription(good3).length === 0,
    '反例 3（<AsyncEmpty> 正常用法）被误命中',
  )
})

// ---- D6
check(`D6 扫描面规模达标（>= ${MIN_SCANNED} 个 .vue/.ts；否则 D4 可能因「什么都没扫到」而永绿）`, () => {
  assert(files.length >= MIN_SCANNED, `只扫到 ${files.length} 个文件（下限 ${MIN_SCANNED}）—— 扫描根可能指错了`)
})

// ---------------------------------------------------------------- 输出

const failed = results.filter((r) => !r.ok)
for (const r of results) {
  console.log(`  ${r.ok ? 'PASS' : 'FAIL'}  ${r.name}${r.ok ? '' : '  ← ' + r.msg}`)
}
console.log(`\n${results.length - failed.length}/${results.length} 通过`)
if (failed.length) {
  console.error(`\n前端空态口径门禁失败：${failed.length} 条`)
  process.exit(1)
}
console.log(
  `前端空态口径门禁通过（统一组件 1 个 ✓ / 消费点 ${consumerDetails.join('、')} 均带 :error ✓ / ` +
    `扫描 ${files.length} 文件无裸三元 ✓ / 自检 1 正 3 反 ✓）`,
)
