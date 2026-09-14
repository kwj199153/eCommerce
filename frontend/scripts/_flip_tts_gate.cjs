/* 在「修复前 / 修复后」之间切换两个源文件，用于验证闸门探针**确实抓得住**这个 bug。
 *
 *   node scripts/_flip_tts_gate.cjs prefix    # 切到修复前（先自动留存修复后副本 .gate-fixed）
 *   node scripts/_flip_tts_gate.cjs postfix   # 切回修复后，并做 sha256 字节级比对
 *
 * 备份统一放 .workbuddy/recovery-backup/（源文件旁不留垃圾）。
 * 为什么必须做这一步：一个「全绿」的探针说明不了什么 —— 必须证明它在**错误实现**下会变红，
 * 否则它可能只是没钉住任何东西（本项目有过「看着很对、实则没钉住」的假绿教训）。
 */
const fs = require('fs')
const crypto = require('crypto')
const path = require('path')

const ROOT = path.resolve(__dirname, '..')
const BAK = path.resolve(ROOT, '..', '.workbuddy', 'recovery-backup')
const FILES = ['src/stores/chat.ts', 'src/composables/useChatOrchestrator.ts']
const mode = process.argv[2]

const sha = (p) => crypto.createHash('sha256').update(fs.readFileSync(p)).digest('hex').slice(0, 16)
const base = (f) => path.basename(f)

if (mode === 'prefix') {
  for (const f of FILES) {
    const live = path.join(ROOT, f)
    const buggy = path.join(BAK, base(f) + '.before-gate')
    const fixed = path.join(BAK, base(f) + '.gate-fixed')
    if (!fs.existsSync(buggy)) throw new Error('缺少修复前备份: ' + buggy)
    if (!fs.existsSync(fixed)) fs.copyFileSync(live, fixed)
    fs.copyFileSync(buggy, live)
    console.log(`prefix  ${f}  修复后(${sha(fixed)}) -> 修复前(${sha(live)})`)
  }
  console.log('现在跑：node scripts/cdp-tts-gate-probe.mjs   （预期 overall=false, histOk=false）')
} else if (mode === 'postfix') {
  for (const f of FILES) {
    const live = path.join(ROOT, f)
    const fixed = path.join(BAK, base(f) + '.gate-fixed')
    if (!fs.existsSync(fixed)) throw new Error('缺少修复后副本: ' + fixed)
    fs.copyFileSync(fixed, live)
    const a = sha(fixed)
    const b = sha(live)
    console.log(`postfix ${f}  ${a} === ${b} ? ${a === b ? 'byte-identical: true' : 'byte-identical: FALSE'}`)
    if (a !== b) throw new Error('还原失败: ' + f)
  }
  console.log('现在跑：node scripts/cdp-tts-gate-probe.mjs   （预期 overall=true）')
} else {
  console.log('用法: node scripts/_flip_tts_gate.cjs <prefix|postfix>')
  process.exit(1)
}
