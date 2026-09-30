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
// ★★ 第 169 轮 #664 警告：第二条路径的**代码已经搬走**。
//   原 1,744 行的单文件 `useChatOrchestrator.ts` 已被拆成「装配壳 + `composables/chat/**`」，
//   本脚本要操作的「语音播报」那段现在住在 `composables/chat/useVoiceAnnounce.ts`。
//   ★ 备份是按**文件名**寻址的（`<basename>.before-gate`），所以这里保留旧名不是笔误，
//     而是「已失效的落点」—— 下面的 fail-closed 守卫会拒绝执行。改 FILES 前请先读一遍守卫的报错。
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
    // ★★ fail-closed 守卫（#664 补）：本脚本是**整文件覆盖**式切换，不是文本替换。
    //   若 `.gate-fixed` 已存在且与 live 不一致，说明 live 已经换过一代实现 ——
    //   此时再跑会 ① 用旧实现整体盖掉新代码（不可逆）② 顺手把历史备份冲掉（再也回不去）。
    //   实测现场：`.workbuddy/recovery-backup/useChatOrchestrator.ts.gate-fixed` 是拆分前
    //   那份 80,939 B 的单文件，而 live 现在是 154 行的装配壳（6,395 B）。
    //   没有这个守卫，一次手滑 `prefix` 就等于**静默毁掉整轮 #664**。
    if (fs.existsSync(fixed)) {
      const a = sha(fixed)
      const b = sha(live)
      if (a !== b) {
        throw new Error(
          '拒绝执行 prefix：' + f + '\n' +
          '   live(' + b + ') ≠ .gate-fixed(' + a + ')\n' +
          '   本脚本是整文件覆盖式切换 ⇒ 实现换代之后再跑，会覆盖掉新代码并把历史备份冲掉。\n' +
          '   若确实需要重跑：先更新 FILES 指向新落点，并按新落点另建 before/fixed 备份。')
      }
    }
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
