/**
 * 反向注入切换器：「删除音色」位置。
 *
 * prefix  → 换回**修复前**（删除按钮在步骤 4 试听区）⇒ 布局探针必须 FAIL
 * postfix → 换回**修复后**（删除按钮在步骤 3 创建音色）⇒ 布局探针必须 PASS
 *
 * 不做这步，布局探针可能只是「看着对」的假绿 —— 位置类断言的假绿特别隐蔽：
 * 只要断言写歪（比如卡片标题取错元素），修复前后都会通过。
 *
 * 用法：node scripts/_flip_vc_step3.cjs prefix|postfix|status
 */
const fs = require('fs')
const crypto = require('crypto')

const SRC = 'src/components/Settings/VoiceClonePanel.vue'
const B = '../.workbuddy/recovery-backup/'
const PRE = B + 'VoiceClonePanel.vue.before-step3-delete'
const POST = B + 'VoiceClonePanel.vue.after-step3-delete'

const sha = (p) => crypto.createHash('sha256').update(fs.readFileSync(p)).digest('hex')

const mode = process.argv[2]
if (!['prefix', 'postfix', 'status'].includes(mode)) {
  console.error('用法: node _flip_vc_step3.cjs prefix|postfix|status')
  process.exit(2)
}

// 首次运行：把当前（修好的）版本存成 postfix 基准
if (mode === 'postfix' && !fs.existsSync(POST)) {
  fs.copyFileSync(SRC, POST)
  console.log('已建立 postfix 基准 ' + POST + ' ' + fs.statSync(POST).size + ' B')
}

if (mode === 'status') {
  for (const [n, p] of [['工作区', SRC], ['prefix(旧)', PRE], ['postfix(新)', POST]]) {
    if (!fs.existsSync(p)) { console.log(`  ${n.padEnd(12)} (不存在)`); continue }
    const t = fs.readFileSync(p, 'utf8')
    const tplEnd = t.lastIndexOf('</template>')
    const s4 = t.indexOf('步骤 4：试听')
    const step4 = t.slice(s4, tplEnd)
    console.log(`  ${n.padEnd(12)} ${String(fs.statSync(p).size).padStart(6)} B  sha=${sha(p).slice(0, 12)}  步骤4含删除音色=${step4.includes('删除音色')}`)
  }
  process.exit(0)
}

const from = mode === 'prefix' ? PRE : POST
if (!fs.existsSync(from)) {
  console.error('✗ 基准不存在: ' + from)
  process.exit(2)
}

const srcSha = sha(from)
fs.copyFileSync(from, SRC)
const nowSha = sha(SRC)
const ok = srcSha === nowSha
console.log(`切到 ${mode}: ${from} -> ${SRC}`)
console.log(`  sha256 比对 = ${ok ? '一致 ✔' : '不一致 ✗'}  ${nowSha.slice(0, 16)}`)

const t = fs.readFileSync(SRC, 'utf8')
const step4 = t.slice(t.indexOf('步骤 4：试听'), t.lastIndexOf('</template>'))
console.log(`  步骤 4 含「删除音色」= ${step4.includes('删除音色')}（prefix 应为 true，postfix 应为 false）`)
process.exit(ok ? 0 : 1)
