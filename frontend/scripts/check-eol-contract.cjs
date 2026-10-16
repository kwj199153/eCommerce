#!/usr/bin/env node
/**
 * 行尾契约门禁（check-eol-contract）
 * ============================================================================
 * 为什么需要它（第 366/367 轮的代价，见 `.gitattributes` 与 #1262）：
 *   「全新检出变 CRLF ⇒ 门禁假红」被修过一次（r347 给 `.gitattributes`
 *   补 `* text=auto eol=lf`），但**修完就没人守**。它复发的形态有两种：
 *     · 有人把 `.gitattributes` 的兜底行删了 / 改了值 ⇒ 检出态又变 CRLF；
 *     · 某个工具（Python `Path.write_text()` 在 Windows 上会把 LF 翻成 CRLF）
 *       写了文件 ⇒ 工作区出现 CRLF，而 **`git status` 看不出来**（声明了 eol=lf
 *       时 git 会按声明归一化后再比，CRLF 与 LF 被当成同一份内容）。
 *   第二种尤其危险：它**静默**。本轮实测工作区 327 个文本文件是 CRLF，
 *   而 `git status` 只报 27 个真改动。
 *
 * ★ 判据有牙的三件事（缺一件就是「看起来在守、其实没守」）：
 *   1. **契约本体自己也被钉**（第 1 组）：`.gitattributes` 的兜底行被删掉之后，
 *      第 2/3 组的「按声明校验」会**静默全跳过** —— 那不叫通过，那叫空跑。
 *   2. **两层都查**：blob 层（git 里存的是不是 CRLF）+ 工作区层（磁盘字节）。
 *      只查一层会漏：blob 全 LF 而工作区全 CRLF，正是本轮的实测状态。
 *   3. **自检**（第 4 组）：用**合成字节**喂同一个判定函数，正反两个方向都要
 *      出正确结论；再断言「判定过的文件数 ≥ 500 且两种 eol 都判定过」。
 *      判据写反（`includes` 写成 `!includes`）时，合成样本会当场红。
 *
 * ★ 三条不许违反的实现纪律（都在本仓踩过）：
 *   · **二进制读**：`fs.readFileSync(p)` 不给编码。用 shell 的 `$'\r'` /
 *     `grep -c` 数行尾在被记过会给出「等于行数」的假计数。
 *   · **禁 shell 拼接**：`spawn('git', [...])` 数组传参，不经过 shell。
 *   · 文件**只读**，绝不写盘（本门禁的职责是判，不是修）。
 *
 * ★ 为什么用**异步** spawn 而不是 `spawnSync`：
 *   本机沙箱（WorkBuddy CLI 的 fs/进程代理）下 `spawnSync` 一律抛 `EBUSY`，
 *   异步 `spawn` 正常。用同步版会让这道门禁在沙箱里**静默退化成 SKIP**
 *   —— 一道永远 SKIP 的门禁等于没有门禁。
 *
 * ★ 为什么是 `.cjs` 而不是 `.py`：本门禁挂在 `npm run build` 上，而前端镜像
 *   的构建阶段是 `node:22-alpine`（没有 python）。CI 里另有 `.py` 门禁的独立
 *   步骤，但那条路进不了 `npm run build`。
 *
 * 退出码：0 = PASS 或 SKIP；1 = FAIL（有违规）；2 = 探针自身失效（不予判定）
 * 环境：不在 git 工作区内（例如前端镜像构建阶段）⇒ 明确 SKIP，不并进 PASS。
 */
'use strict'

const { existsSync, readFileSync, statSync } = require('node:fs')
const { spawn } = require('node:child_process')
const path = require('node:path')

// ---------------------------------------------------------------------------
// 输出与计数
// ---------------------------------------------------------------------------
let failures = 0
let skips = 0

const check = (ok, msg) => {
  if (!ok) failures += 1
  console.log(`  ${ok ? 'PASS' : 'FAIL'}  ${msg}`)
}
const skip = (msg) => {
  skips += 1
  console.log(`  SKIP  ${msg}`)
}
const info = (msg) => console.log(`  · ${msg}`)

// ---------------------------------------------------------------------------
// 仓库根：本文件住 <root>/frontend/scripts/ ⇒ 上两级
// ---------------------------------------------------------------------------
const ROOT = path.resolve(__dirname, '..', '..')
const ATTRS = path.join(ROOT, '.gitattributes')

/** git 子进程（异步、数组传参、二进制 stdout） */
const git = (args) =>
  new Promise((resolve) => {
    const p = spawn('git', args, { cwd: ROOT, windowsHide: true })
    const out = []
    const err = []
    p.stdout.on('data', (d) => out.push(d))
    p.stderr.on('data', (d) => err.push(d))
    p.on('error', (e) => resolve({ status: -1, error: e, stdout: Buffer.alloc(0), stderr: Buffer.alloc(0) }))
    p.on('close', (code) => resolve({ status: code, stdout: Buffer.concat(out), stderr: Buffer.concat(err) }))
  })

// ---------------------------------------------------------------------------
// 判据本体：**纯函数**（第 4 组自检要喂合成字节给它）
// ---------------------------------------------------------------------------
const CR = 0x0d
const LF = 0x0a

const countPair = (buf, a, b) => {
  let n = 0
  for (let i = 0; i < buf.length - 1; i += 1) if (buf[i] === a && buf[i + 1] === b) n += 1
  return n
}
const countByte = (buf, b) => {
  let n = 0
  for (let i = 0; i < buf.length; i += 1) if (buf[i] === b) n += 1
  return n
}

/**
 * 磁盘字节 vs 声明 eol。
 * @returns {null | string} null = 合规；字符串 = 违规原因
 */
function eolViolation(bytes, declared) {
  const crlf = countPair(bytes, CR, LF)
  const lf = countByte(bytes, LF)
  const cr = countByte(bytes, CR)

  if (declared === 'lf') {
    if (crlf > 0) return `声明 eol=lf，磁盘上有 ${crlf} 处 CRLF`
    // 裸 CR（旧 Mac 行尾）在文本文件里也是异常：它会把 grep / 锚点对账弄乱
    const lone = cr - crlf
    if (lone > 0) return `声明 eol=lf，磁盘上有 ${lone} 个裸 CR`
    return null
  }
  if (declared === 'crlf') {
    // 每个 LF 都要带 CR；`lf === 0`（无行尾的单行文件）不算违规
    if (crlf !== lf) return `声明 eol=crlf，${lf} 个 LF 里有 ${lf - crlf} 个没带 CR`
    return null
  }
  return null // 未声明 eol 的（二进制等）不该走到这里
}

/** 从 `git ls-files --eol` 的 attr 列取有效声明 */
function declaredEol(attr) {
  const toks = attr.split(/\s+/).filter(Boolean)
  if (toks.includes('-text')) return null // 二进制：跳过
  const hit = toks.find((t) => t.startsWith('eol='))
  return hit ? hit.slice(4) : null // 没声明 eol ⇒ 跳过
}

// ---------------------------------------------------------------------------
// 主流程
// ---------------------------------------------------------------------------
async function main() {
  console.log('=== 行尾契约门禁（.gitattributes 声明 vs 磁盘字节）===')

  // ---- [0] 环境 -----------------------------------------------------------
  console.log('\n[0] 环境')
  if (!existsSync(ATTRS)) {
    skip(`未找到 ${ATTRS}（当前不在仓库工作区内，例如前端镜像构建阶段）`)
    console.log('\nRESULT: SKIP（本门禁只在仓库工作区内生效；0 失败）')
    return
  }
  info(`仓库根：${ROOT}`)

  const top = await git(['rev-parse', '--show-toplevel'])
  if (top.error || top.status !== 0) {
    skip(
      `\`git rev-parse --show-toplevel\` 不可用（${top.error ? top.error.code : 'rc=' + top.status}）` +
        ' —— 无 git 或不在工作区内',
    )
    console.log('\nRESULT: SKIP（无法取得 git 上下文；0 失败）')
    return
  }
  info(`git 顶层：${top.stdout.toString('utf8').trim()}`)

  // ---- [1] 契约本体（防「契约被删 ⇒ 判据静默全跳过」）---------------------
  console.log('\n[1] 契约本体：`.gitattributes` 的关键声明必须还在')
  const attrText = readFileSync(ATTRS, 'utf8')
  const hasLine = (re) => re.test(attrText)
  check(hasLine(/^\*\s+text=auto\s+eol=lf\s*$/m), '兜底行 `* text=auto eol=lf` 仍在（否则检出会变 CRLF）')
  check(hasLine(/^\*\.bat\s+text\s+eol=crlf\s*$/m), '`*.bat text eol=crlf` 仍在')
  check(hasLine(/^\*\.cmd\s+text\s+eol=crlf\s*$/m), '`*.cmd text eol=crlf` 仍在')
  check(hasLine(/^\*\.[A-Za-z0-9]+\s+binary\s*$/m), '二进制声明（`*.<ext> binary`）仍在（否则 PNG 里的随机 CR 会误判）')

  // ---- 取清单（含未跟踪、排除被忽略的）-----------------------------------
  // `-z`：路径按 NUL 分隔，中文路径不被转义；
  // `--eol` 第 3 列是 git 自己算出的**有效属性**（与 .gitattributes 同源），
  // 不另写一份 glob 匹配器 —— 那是「同一判定两份实现」。
  const listed = await git(['ls-files', '--eol', '-z', '--cached', '--others', '--exclude-standard'])
  if (listed.error || listed.status !== 0) {
    console.error('探针失效：`git ls-files --eol -z` rc=' + listed.status)
    process.exitCode = 2
    return
  }

  const records = []
  for (const rec of listed.stdout.toString('utf8').split('\0')) {
    if (!rec) continue
    const tab = rec.indexOf('\t')
    if (tab < 0) continue
    const cols = rec.slice(0, tab).split(/\s+/).filter(Boolean)
    records.push({ indexEol: cols[0] || '', attr: cols.slice(2).join(' '), rel: rec.slice(tab + 1) })
  }

  // ---- [2] blob 层 --------------------------------------------------------
  console.log('\n[2] blob 层：git 里存的（index）不该是 CRLF')
  const iCrlf = records.filter((r) => r.indexEol === 'i/crlf')
  const iMixed = records.filter((r) => r.indexEol === 'i/mixed')
  info(`清单 ${records.length} 条（被跟踪 + 未跟踪且未被忽略）`)
  check(iCrlf.length === 0, `i/crlf = ${iCrlf.length}（期望 0）`)
  for (const r of iCrlf.slice(0, 20)) console.log(`         ${r.rel}`)
  check(iMixed.length === 0, `i/mixed = ${iMixed.length}（期望 0）`)
  for (const r of iMixed.slice(0, 20)) console.log(`         ${r.rel}`)

  // ---- [3] worktree 层 ----------------------------------------------------
  console.log('\n[3] worktree 层：磁盘字节必须符合声明')
  const violations = []
  const counter = { lf: 0, crlf: 0, skippedBinary: 0, skippedEmpty: 0, missing: 0 }

  for (const r of records) {
    const declared = declaredEol(r.attr)
    if (declared !== 'lf' && declared !== 'crlf') {
      counter.skippedBinary += 1
      continue
    }
    const abs = path.join(ROOT, r.rel)
    let st
    try {
      st = statSync(abs)
    } catch {
      counter.missing += 1
      continue
    }
    if (!st.isFile()) {
      counter.missing += 1
      continue
    }
    if (st.size === 0) {
      counter.skippedEmpty += 1
      continue
    }
    // ★ 二进制读：不传 encoding
    const bytes = readFileSync(abs)
    const why = eolViolation(bytes, declared)
    counter[declared] += 1
    if (why) violations.push({ rel: r.rel, why })
  }

  info(
    `已判定 ${counter.lf + counter.crlf} 个（eol=lf ${counter.lf} / eol=crlf ${counter.crlf}）` +
      `；跳过：二进制 ${counter.skippedBinary}、空文件 ${counter.skippedEmpty}、磁盘缺失 ${counter.missing}`,
  )
  check(violations.length === 0, `行尾不合声明的文件 = ${violations.length}（期望 0）`)
  for (const v of violations.slice(0, 30)) console.log(`         ${v.rel}  —— ${v.why}`)
  if (violations.length > 30) console.log(`         …其余 ${violations.length - 30} 个`)

  // ---- [4] 自检：防空跑 / 防判据写反 --------------------------------------
  console.log('\n[4] 自检（判据本体与判定规模）')
  const B = (...xs) => Buffer.from(xs) // 逐字节给，避免字节串被任何工具归一化
  const LF_BYTES = B(0x61, 0x0a, 0x62, 0x0a)
  const CRLF_BYTES = B(0x61, 0x0d, 0x0a, 0x62, 0x0d, 0x0a)
  const LONE_CR = B(0x61, 0x0d, 0x62, 0x0a)

  check(eolViolation(LF_BYTES, 'lf') === null, '合成样本① LF 字节 @ eol=lf ⇒ 通过')
  check(eolViolation(CRLF_BYTES, 'lf') !== null, '合成样本② CRLF 字节 @ eol=lf ⇒ 判违规（判据写反会在这里红）')
  check(eolViolation(LONE_CR, 'lf') !== null, '合成样本③ 裸 CR @ eol=lf ⇒ 判违规')
  check(eolViolation(CRLF_BYTES, 'crlf') === null, '合成样本④ CRLF 字节 @ eol=crlf ⇒ 通过')
  check(eolViolation(LF_BYTES, 'crlf') !== null, '合成样本⑤ LF 字节 @ eol=crlf ⇒ 判违规')
  check(eolViolation(B(0x61), 'crlf') === null, '合成样本⑥ 无行尾单行 @ eol=crlf ⇒ 通过（没有行尾可错）')

  const judged = counter.lf + counter.crlf
  const enough = judged >= 500
  // 为什么是 500：正常仓里有 ~1270 个文本文件。低于这个数量说明扫描面塌了
  // （清单取不到 / 声明全解析不出来 / 文件全被判成二进制）—— 那时「0 违规」
  // 毫无意义。这一条只防「空跑」，具体数字不对账。
  check(enough, `判定规模 ≥ 500（实测 ${judged}）—— 低于这个数说明扫描面塌了`)
  check(counter.lf >= 1 && counter.crlf >= 1, `两种 eol 都被真的判定过（lf ${counter.lf} / crlf ${counter.crlf}）`)

  // ---- 汇总 ---------------------------------------------------------------
  console.log()
  if (failures > 0) {
    console.log(`RESULT: FAIL（${failures} 项不通过，跳过 ${skips} 项${enough ? '' : '；另：判定规模也不足'}）`)
    console.log('修法：')
    console.log('  · 工作区行尾漂移 —— 按 `.gitattributes` 声明把行尾归位（只删 CR，不动其它字节），')
    console.log('    再用 `git add --renormalize` 刷新索引 stat（CRLF 的漂移 `git status` 看不出来）。')
    console.log('  · 别再让 Python 在 Windows 上写源码：`Path.write_text()` 默认把 LF 翻成 CRLF，')
    console.log('    写盘一律 `write_bytes()`。')
    process.exitCode = 1
    return
  }
  if (!enough) {
    console.log('RESULT: 探针失效（判定规模塌了、且没有别的判据可依）—— 退出码 2，**不当作通过**')
    process.exitCode = 2
    return
  }
  console.log(
    `RESULT: PASS（契约 4 条在位；blob i/crlf=0；工作区 ${judged} 个文件行尾合声明；自检 8 条通过）`,
  )
}

main().catch((e) => {
  console.error('探针自身异常：', e && e.stack ? e.stack : e)
  process.exitCode = 2
})
