/**
 * 「删除音色」搬迁的双向验证编排（postfix PASS / prefix FAIL / 还原 PASS）。
 *
 * 位置类断言最容易假绿：断言写歪（卡片标题取错元素、区间取空）时，修复前后都会通过。
 * 所以必须真的把文件换回修复前，看探针**是否敢判 FAIL 并给出非零退出码**。
 *
 * ★★★ 2026-09-15 事故与防护 ★★★
 * 上一版没有给 prefix 轮加 --readonly，而修复前的按钮是 `@click="handleDelete"`
 * （点击立即删除、无二次确认）⇒ 探针点了一下，**真的把老板「亚马逊2」的音色删了**
 * （日志：`已删除音色记录 shop=store_a498a7d5 remote_deleted=True`，远端配额一并释放）。
 * 教训：**对破坏性操作做反向注入时，「切回旧版本」会把破坏性语义一起带回来** ——
 * 旧代码的点击后果与新代码不同，探针必须在该版本下降级为只读。
 * 现在 prefix 轮强制 --readonly，且脚本开头拒绝在「无 ready 音色」时运行。
 *
 * 用法：node scripts/_run_vc_step3_ab.cjs
 */
const { execFileSync } = require('node:child_process')
const crypto = require('node:crypto')
const fs = require('node:fs')

const PROBE = 'scripts/cdp-vc-step-layout-probe.mjs'
const FLIP = 'scripts/_flip_vc_step3.cjs'
const SRC = 'src/components/Settings/VoiceClonePanel.vue'
const sha = (p) => crypto.createHash('sha256').update(fs.readFileSync(p)).digest('hex')
const sleepMs = (ms) => new Promise((r) => setTimeout(r, ms))

/** 让 Vite 先把新代码编译出来，否则浏览器可能拿到上一次的模块（HMR 有延迟） */
async function warmModule(tag) {
  for (let i = 0; i < 12; i++) {
    try {
      const r = await fetch('http://127.0.0.1:5173/src/components/Settings/VoiceClonePanel.vue?t=' + Date.now())
      const t = await r.text()
      const hasDanger = t.includes('vc-danger-row')
      // postfix 期望含 vc-danger-row；prefix 期望不含
      const want = tag === 'postfix'
      if (hasDanger === want) return { ok: true, hasDanger, len: t.length }
    } catch { /* dev server 忙 */ }
    await sleepMs(800)
  }
  return { ok: false }
}

function runProbe(outFile) {
  let code = 0
  try {
    execFileSync(process.execPath, [PROBE], { stdio: ['ignore', fs.openSync(outFile, 'w'), fs.openSync(outFile, 'a')] })
  } catch (e) {
    code = typeof e.status === 'number' ? e.status : -1
  }
  return code
}

function verdict(outFile) {
  const t = fs.readFileSync(outFile, 'utf8')
  const line = (t.split('\n').find((l) => l.includes('★★ VERDICT')) || '').trim()
  const passLine = (t.split('\n').find((l) => l.includes('★★ PASS=')) || '').trim()
  const popGone = (t.split('\n').find((l) => l.includes('浮层已关闭')) || '').trim()
  const delCard = (t.split('\n').find((l) => l.includes('删除音色   → 所属卡片')) || '').trim()
  const closeLine = (t.split('\n').find((l) => l.includes('stateKept')) || '').trim()
  return { verdict: line, pass: passLine, popGone, delCard, stateKept: closeLine }
}

async function main() {
  // ★★★ 前置闸：目标店铺必须有 ready 音色 —— 否则「删除音色」按钮根本不渲染，
  // 三轮都会以「前置不满足」失败，产出误导性的红。宁可拒绝运行，也别给假失败。
  const shop = process.env.VC_PROBE_SHOP || 'store_a498a7d5'
  try {
    const st = await (await fetch(`http://127.0.0.1:8000/api/v1/voice-clone/status`, { headers: { 'X-Shop-ID': shop } })).json()
    console.log(`前置检查：${shop} ready=${st.ready} exists=${st.exists}`)
    if (!st.ready) {
      console.log('✗ 该店铺没有 ready 音色 —— 删除按钮不会渲染，本编排无法验收。中止。')
      console.log('  （如需重建：用 admin 在设置页重新选样本并点「开始克隆」）')
      process.exit(2)
    }
  } catch (e) {
    console.log('✗ 后端不可达，无法前置检查：' + e.message)
    process.exit(2)
  }

  const results = []
  const variants = [
    { tag: 'postfix', expectExit: 0, out: 'D:/ai/_ab_postfix.txt', args: [] },
    // ★★★ prefix 必须 --readonly：修复前版本的按钮是 `@click="handleDelete"`，
    //   交互式跑会**真的删掉老板的音色**（2026-09-15 已发生过一次：远端配额一并释放）。
    //   prefix 的判据（位置错/无 vc-danger-row）在只读模式下同样能判出来，不需要点击。
    { tag: 'prefix', expectExit: 1, out: 'D:/ai/_ab_prefix.txt', args: ['--readonly'] },
    { tag: 'postfix', expectExit: 0, out: 'D:/ai/_ab_restore.txt', args: [] },
  ]

  for (const v of variants) {
    console.log(`\n${'='.repeat(72)}\n### 切到 ${v.tag}\n${'='.repeat(72)}`)
    let flipCode = 0
    try {
      execFileSync(process.execPath, [FLIP, v.tag], { stdio: 'inherit' })
    } catch (e) { flipCode = e.status ?? -1 }
    const warm = await warmModule(v.tag)
    console.log(`  Vite 预热: ${JSON.stringify(warm)}  flipExit=${flipCode}`)
    await sleepMs(1500)

    const exit = runProbe(v.out)
    const vd = verdict(v.out)
    console.log('  ' + vd.verdict)
    console.log('  ' + vd.pass + '   ' + vd.popGone)
    console.log('  ' + vd.delCard)
    console.log(`  探针退出码 = ${exit}（期望 ${v.expectExit}）`)
    results.push({ tag: v.tag, exit, expect: v.expectExit, ok: exit === v.expectExit, vd })
  }

  // 最终确认：工作区必须回到 postfix（= 修复后）
  const afterSha = sha(SRC)
  console.log('\n' + '='.repeat(72))
  console.log('### 汇总')
  console.log('='.repeat(72))
  let allOk = true
  for (const r of results) {
    if (!r.ok) allOk = false
    console.log(`  ${r.ok ? '✔' : '✗'} ${r.tag.padEnd(8)} 退出码 ${r.exit}（期望 ${r.expect}）`)
  }
  const postfixSha = sha('../.workbuddy/recovery-backup/VoiceClonePanel.vue.after-step3-delete')
  const restored = afterSha === postfixSha
  if (!restored) allOk = false
  console.log(`  ${restored ? '✔' : '✗'} 工作区已还原为修复后版本  sha=${afterSha.slice(0, 12)}`)

  console.log('\n★★ 双向验证 ' + (allOk ? 'PASS（prefix 被抓住、postfix 通过、还原一致）' : 'FAIL'))
  process.exit(allOk ? 0 : 1)
}

main().catch((e) => { console.error(e); process.exit(2) })
