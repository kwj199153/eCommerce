#!/usr/bin/env node
/**
 * 「扫码支付前端」门禁 —— 守的是「**没付钱，不许说买到了**」
 *
 * ============================================================================
 * ## 为什么需要它（这条形态的破坏力）
 * ============================================================================
 * 支付宝接入后 `/billing/subscribe` 有了**两种**返回形态：
 *
 *   · 同步（演示身份 / mock）：扣款成功即开通 ⇒ `charged: true`
 *   · 异步（真实用户）：只下单拿到二维码，**权益还没生效** ⇒
 *     `charged: false, requires_confirmation: true, payment: {...}`
 *
 * 前端最容易犯、且**看起来完全正常**的错，是把这两种当成一种：
 *
 *     if (res.charged) { message.success('已切换为年付套餐') }
 *     else { message.success('已切换为年付套餐') }      // ← 灾难
 *
 * 后果不是"提示文案不准"：用户被告知"已切换"，于是关掉页面去干活，
 * 而套餐从未生效（他没付钱）—— 等他发现功能不可用时，已经把这次操作
 * 忘干净了。而**接口全是 200**，日志里没有任何异常。
 *
 * ★ 这个门禁只钉**一个形态**，但钉的是最贵的那个：
 *   `requires_confirmation` 分支里**不得**出现成功提示，且**必须**把
 *   二维码交给用户（`openPayModal`）。
 *
 * ============================================================================
 * ## 判据（锚点找不到 = FAIL，不是"跳过"）
 * ============================================================================
 * A. `src/api/billing.ts` 的契约层
 *   A1 `changePlan` 返回类型含 `requires_confirmation` 与 `payment`
 *   A2 存在 `PendingPayment` 契约且含 `expires_at`（倒计时的**唯一**来源）
 *   A3~A5 `changePlan` / `fetchPaymentQr` / `fetchPaymentStatus` 声明 `silentError`
 *        —— 不声明就会"拦截器弹一条 + 调用点再弹一条"（见 `request.ts` 提示归属）
 *   A6 三个读接口都真的存在（`pending` / `qr` / `status`）
 *
 * B. `src/views/Subscription.vue` 的分支与渲染
 *   B1 `charged` 分支在 `requires_confirmation` **之前**（演示身份先命中同步分支）
 *   B2 `requires_confirmation` 分支窗口内出现 `openPayModal(`
 *   B3 ★★ 该窗口内**不得**出现 `message.success`
 *   B4 ★★ 该窗口内不得出现「已切换」这类"买到了"的措辞
 *   B5 模板里二维码真的被渲染：`:src="payQr"` 与 `.pay-qr-img`
 *   B6 取码撞 409 被当成**成功**（`onPaySucceeded`），不是"加载失败"
 *   B7 定时器在卸载时被清理（`onUnmounted(stopPayPolling)`）
 *
 * C. 自检（防门禁恒绿）
 *   C1 `stripComments` 会剥掉注释里的锚点（否则注释能骗过 B2/B3）
 *   C2 `stripComments` **不破坏** `https://`（行内注释保护的回归哨兵）
 *   C3 把"在 requires_confirmation 分支里写 message.success"的**构造样本**
 *      喂给 B3 的同一段判定函数，必须报错
 *
 * ★ 反向注入（改真文件后复跑，必须转红）：
 *   1. 在 `requires_confirmation` 分支里加 `message.success('已切换')` ⇒ B3/B4 红
 *   2. 把 `await openPayModal(res.payment)` 删掉 ⇒ B2 红
 *   3. 去掉 `changePlan` 的 `silentError` ⇒ A3 红
 *   4. 把 `=== 409` 分支改成抛错（提示"二维码加载失败"）⇒ B6 红
 *   5. 去掉 `onUnmounted(stopPayPolling)` ⇒ B7 红
 *   6. 锚点改名（`res.requires_confirmation` → `res.needPay`）⇒ B1~B4 红
 *      （**不许静默放行**）
 */

const fs = require('fs')
const path = require('path')

const ROOT = path.resolve(__dirname, '..')
// ★ 读 `SRC_ROOT`（而不是硬编码真仓路径）：这样同一个脚本能被指向一份**副本树**
//   去做反向注入 —— 否则"改真文件再复跑"就变成手工操作，迟早没人做。
//   （本仓铁律：没被反向注入验证过的门禁 = 没有门禁。）
const SRC_ROOT = process.env.BILLING_PAY_SRC_ROOT
  ? path.resolve(process.env.BILLING_PAY_SRC_ROOT)
  : ROOT

const API = 'src/api/billing.ts'
const VIEW = 'src/views/Subscription.vue'

const failures = []
let pass = 0
function check(name, ok, detail) {
  if (ok) {
    pass++
    console.log('PASS  ' + name)
  } else {
    failures.push(name + (detail ? '  |  ' + detail : ''))
    console.log('FAIL  ' + name + (detail ? '  |  ' + detail : ''))
  }
}

// ---------------------------------------------------------------------------
// 剥注释（判据一律跑在**剥掉注释**的源码上，本仓铁律：注释里的旧文案会骗过检查）
// ---------------------------------------------------------------------------

/**
 * @param {string} src
 * @returns {string}
 */
function stripComments(src) {
  let out = ''
  let i = 0
  const n = src.length
  while (i < n) {
    const c = src[i]
    const c2 = src[i + 1]
    // `//` 行注释。★ `src[i-1] !== ':'` 保护 `https://...` ——
    //   否则 URL 会把该行剩余部分整段吃掉（本仓踩过：反而漏掉真代码）。
    if (c === '/' && c2 === '/' && src[i - 1] !== ':') {
      while (i < n && src[i] !== '\n') i++
      continue
    }
    // `/* */` 块注释
    if (c === '/' && c2 === '*') {
      i += 2
      while (i < n && !(src[i] === '*' && src[i + 1] === '/')) i++
      i += 2
      continue
    }
    // `<!-- -->` 模板注释（.vue 里的大段说明都住在这里，必须剥掉）
    if (c === '<' && src.slice(i, i + 4) === '<!--') {
      i += 4
      const end = src.indexOf('-->', i)
      i = end < 0 ? n : end + 3
      continue
    }
    // 字符串字面量整体照搬（避免把串里的 `//` 当注释）
    if (c === '`' || c === '"' || c === "'") {
      const q = c
      out += c
      i++
      while (i < n && src[i] !== q) {
        if (src[i] === '\\') {
          out += src[i]
          i++
        }
        if (i < n) {
          out += src[i]
          i++
        }
      }
      out += q
      i++
      continue
    }
    out += c
    i++
  }
  return out
}

/**
 * 取 `requires_confirmation` 那个分支的源码窗口（锚点缺失返回 `null`）。
 *
 * ★ 为什么用"窗口"而不是全文件搜索：
 *   全文件里当然能找到 `message.success`（`charged` 分支里就有一条），
 *   于是"分支里有没有写成功提示"这个判定会被**别处的同形调用**满足 ⇒ 恒绿。
 *   判据的作用域必须和它所断言的作用域一致。
 */
function pendingBranchWindow(code) {
  const start = code.indexOf('res.requires_confirmation')
  if (start < 0) return null
  const end = code.indexOf('} else if (res.already_subscribed)', start)
  if (end < 0) return null
  return code.slice(start, end)
}

/** B3/B4 的判定函数（抽出来是为了让 C3 能拿构造样本喂它） */
function pendingBranchIsHonest(code) {
  const w = pendingBranchWindow(code)
  if (w === null) return { ok: false, why: '找不到 requires_confirmation 分支窗口（锚点改名了？）' }
  if (/message\.success/.test(w)) {
    return { ok: false, why: '分支里出现 message.success —— 未付款却提示"成功"' }
  }
  if (/已切换/.test(w)) {
    return { ok: false, why: '分支里出现「已切换」—— 用户会以为买到了，而权益尚未生效' }
  }
  if (!/openPayModal\(/.test(w)) {
    return { ok: false, why: '分支里没有 openPayModal( —— 下单了却没把二维码交给用户' }
  }
  return { ok: true }
}

// ---------------------------------------------------------------------------
// 载入源码
// ---------------------------------------------------------------------------

function read(rel) {
  const p = path.join(SRC_ROOT, rel)
  if (!fs.existsSync(p)) {
    console.error(`\n✗ 源文件不存在：${p}\n  （本门禁**不跳过** —— 拿不到清单 ≠ 清单为空）`)
    process.exit(1)
  }
  return fs.readFileSync(p, 'utf8')
}

console.log('扫码支付前端门禁 —— 盘面读数')
console.log('  源码根 ' + SRC_ROOT)

const apiRaw = read(API)
const viewRaw = read(VIEW)
const api = stripComments(apiRaw)
const view = stripComments(viewRaw)
console.log(`  ${API}  ${apiRaw.length} B（剥注释后 ${api.length} B）`)
console.log(`  ${VIEW}  ${viewRaw.length} B（剥注释后 ${view.length} B）`)

// ---------------------------------------------------------------------------
// A. 契约层
// ---------------------------------------------------------------------------

const changePlanSig = (() => {
  const i = api.indexOf('export async function changePlan')
  if (i < 0) return null
  const j = api.indexOf('{', api.indexOf('>', i))
  return api.slice(i, j < 0 ? i + 1200 : j)
})()

check(
  'A1 changePlan 返回类型声明了 requires_confirmation（否则前端根本看不到"未付款"这个状态）',
  !!changePlanSig && /requires_confirmation\??:\s*boolean/.test(changePlanSig),
  'changePlan 的返回类型里找不到 `requires_confirmation`'
)
check(
  'A2 changePlan 返回类型声明了 payment（二维码从这条通道下来）',
  !!changePlanSig && /payment\??:\s*PendingPayment\s*\|\s*null/.test(changePlanSig),
  'changePlan 的返回类型里找不到 `payment?: PendingPayment | null`'
)
check(
  'A3 PendingPayment 契约存在且含 expires_at（倒计时的唯一来源）',
  /export interface PendingPayment/.test(api) && /expires_at:/.test(api),
  'PendingPayment 契约缺失或没有 expires_at —— 前端会自己造 TTL，与支付宝侧漂移'
)

/**
 * 取一个顶层函数体的源码（从声明行到**行首顶格的 `}`**）。
 *
 * ★ 为什么不用 `/export async function f[\s\S]*?\n\}/`：
 *   本仓的函数签名常把对象类型写在返回值里（`Promise<{ ... }>`），
 *   那个 `}` 也在行首 —— 非贪婪匹配会**停在签名末尾**，
 *   于是"函数体里有没有 X"变成恒假（实测：changePlan 的 silentError 就是这么漏掉的）。
 *   按"行首顶格 `}`"找闭合，才能稳定拿到整个函数体。
 */
function functionBody(code, header) {
  const lines = code.split('\n')
  const start = lines.findIndex((l) => l.includes(header))
  if (start < 0) return null
  for (let i = start + 1; i < lines.length; i++) {
    if (lines[i] === '}') return lines.slice(start, i + 1).join('\n')
  }
  return null
}

const silentSites = [
  ['changePlan', 'export async function changePlan'],
  ['fetchPaymentQr', 'export async function fetchPaymentQr'],
  ['fetchPaymentStatus', 'export async function fetchPaymentStatus'],
]
for (const [name, header] of silentSites) {
  const body = functionBody(api, header)
  check(
    `A4 ${name} 声明了 silentError（否则同一个失败"拦截器弹一条 + 调用点再弹一条"）`,
    !!body && /silentError:\s*true/.test(body),
    body ? `${name} 里没有 { silentError: true }` : `找不到 ${name} 的定义`
  )
}

check(
  'A5 三个支付读接口都在（pending / qr / status）',
  /fetchPendingPayment/.test(api) && /fetchPaymentQr/.test(api) && /fetchPaymentStatus/.test(api) &&
    /'\/billing\/payment\/pending'/.test(api) &&
    /\/billing\/payment\/qr\/\$\{invoiceId\}/.test(api) &&
    /\/billing\/payment\/\$\{invoiceId\}/.test(api),
  '三个读接口的函数或路径有缺失'
)

// ---------------------------------------------------------------------------
// B. 分支与渲染
// ---------------------------------------------------------------------------

const iCharged = view.indexOf('if (res.charged)')
const iPending = view.indexOf('res.requires_confirmation')
check(
  'B1 charged 分支排在 requires_confirmation 之前（演示身份要走同步分支）',
  iCharged >= 0 && iPending > iCharged,
  `charged 锚点=${iCharged}，requires_confirmation 锚点=${iPending}（应后者更大）`
)

const honesty = pendingBranchIsHonest(view)
check(
  'B2/B3/B4 未付款分支：把二维码交给用户，且不许说"成功 / 已切换"',
  honesty.ok,
  honesty.why
)

check(
  'B5 模板里二维码真的被渲染（拿到数据 ≠ 画出来）',
  /:src="payQr"/.test(view) && /pay-qr-img/.test(view),
  '模板里找不到 `:src="payQr"` 或 `.pay-qr-img`'
)

const i409 = view.indexOf('=== 409')
check(
  'B6 取码撞 409 被当作"已支付成功"处理（不是"二维码加载失败"）',
  i409 >= 0 && /onPaySucceeded\(\)/.test(view.slice(i409, i409 + 400)),
  i409 < 0
    ? '找不到 `=== 409` 分支 —— 用户会对着"已付款却提示加载失败"的窗口重新下单'
    : '409 分支里没有调用 onPaySucceeded（会被当成失败路径）'
)

check(
  'B7 定时器在组件卸载时被清理（否则离开页面后还在每 3 秒打后端）',
  /onUnmounted\(\s*stopPayPolling\s*\)/.test(view),
  '找不到 `onUnmounted(stopPayPolling)`'
)

// ---------------------------------------------------------------------------
// C. 自检（防门禁恒绿）
// ---------------------------------------------------------------------------

{
  const fake = stripComments(
    `const a = 1 // openPayModal(pay)\n/* message.success('已切换') */\nconst b = 'https://qr.alipay.com/x'`
  )
  check(
    'C1 剥注释真的剥掉了注释里的锚点（否则注释能骗过 B2~B4）',
    !/openPayModal/.test(fake) && !/message\.success/.test(fake),
    `剥注释后仍能看到注释内容：${JSON.stringify(fake)}`
  )
  check(
    'C2 剥注释不破坏 `https://`（行内注释保护的回归哨兵）',
    fake.includes('https://qr.alipay.com/x'),
    `URL 被当成注释吃掉了：${JSON.stringify(fake)}`
  )

  const bad = `
    if (res.charged) { message.success('已切换') }
    else if (res.requires_confirmation && res.payment) {
      message.success('已切换为年付套餐')
    } else if (res.already_subscribed) { }
  `
  const verdict = pendingBranchIsHonest(bad)
  check(
    'C3 判定函数对「未付款分支里写成功提示」的构造样本必须报警（否则 B3/B4 是装饰）',
    verdict.ok === false && /message\.success/.test(verdict.why || ''),
    `构造样本被判成 ok=${verdict.ok}，理由=${verdict.why}`
  )

  const good = `
    if (res.charged) { message.success('已切换') }
    else if (res.requires_confirmation && res.payment) {
      await openPayModal(res.payment)
    } else if (res.already_subscribed) { }
  `
  check(
    'C3b 正向对照：合规样本必须被判成 ok（否则门禁恒红）',
    pendingBranchIsHonest(good).ok === true,
    `合规样本被判成了：${pendingBranchIsHonest(good).why}`
  )
}

// ---------------------------------------------------------------------------
// 汇总
// ---------------------------------------------------------------------------

console.log('')
if (failures.length) {
  console.log(`---- ${pass}/${pass + failures.length} 通过 ----`)
  console.log('失败项：')
  for (const f of failures) console.log('  · ' + f)
  process.exit(1)
}
console.log(
  `---- ${pass}/${pass} 通过 ----\n` +
    '扫码支付前端契约成立（未付款分支不说成功 · 二维码真的渲染 · 409 当成功 · 定时器收口）'
)
