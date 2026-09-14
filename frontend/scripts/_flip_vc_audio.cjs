// 反向注入：把 VoiceClonePanel.vue 切成「修复前 / 修复后」两版，用来证明
// cdp-preview-audio-probe.mjs 的 visible 断言**确实钉住了 flex-basis 这个真修复点**
// （否则一个恒真的判定会给出假绿，比没有探针更糟）。
//
// 用法：
//   node scripts/_flip_vc_audio.cjs prefix    # 切到修复前（应让探针 FAIL）
//   node scripts/_flip_vc_audio.cjs postfix   # 切回修复后
const { copyFileSync, existsSync, readFileSync, statSync } = require('fs')
const { createHash } = require('crypto')

const SRC = 'D:/ai/eCommerce/frontend/src/components/Settings/VoiceClonePanel.vue'
const B = 'D:/ai/eCommerce/.workbuddy/recovery-backup/'
const MAP = {
  prefix: B + 'VoiceClonePanel.vue.before-audio-css',
  postfix: B + 'VoiceClonePanel.vue.after-audio-css',
}

const mode = process.argv[2]
if (!MAP[mode]) {
  console.error('用法: node scripts/_flip_vc_audio.cjs prefix|postfix')
  process.exit(2)
}
const from = MAP[mode]
if (!existsSync(from)) {
  console.error('缺少备份文件 ' + from)
  process.exit(1)
}
copyFileSync(from, SRC)

const sha = (p) => createHash('sha256').update(readFileSync(p)).digest('hex')
console.log('已切到 ' + mode)
console.log('  src  sha=' + sha(SRC).slice(0, 16) + ' (' + statSync(SRC).size + ' B)')
console.log('  期望 sha=' + sha(from).slice(0, 16) + ' (' + statSync(from).size + ' B)')
console.log('  与备份一致: ' + (sha(SRC) === sha(from)))
const t = readFileSync(SRC, 'utf8')
console.log("  含 'flex: 1 1 auto' = " + (t.split('flex: 1 1 auto').length - 1))
console.log("  含 '.vc-preview .vc-audio' = " + (t.split('.vc-preview .vc-audio').length - 1))
