// 反向注入验证：证明「流式段 == 一次算完的段」这条不变量**真的能抓到**错误实现。
//
// 为什么必须做：一条检查如果写歪了会给出**假绿**，让人以为有防线 —— 比没有检查更糟。
// 做法（项目铁律）：注入一个明确的错误 → 跑探针 → 必须变红 → 字节级还原 → 复跑确认恢复绿。
//
// 用法：node scripts/_inject_tts.mjs
import { spawnSync } from 'node:child_process'
import { readFileSync, writeFileSync, copyFileSync } from 'node:fs'
import { createHash } from 'node:crypto'

const P = 'D:/ai/eCommerce/frontend/src/stores/voiceTts.ts'
const BAK = 'D:/ai/eCommerce/.workbuddy/recovery-backup/voiceTts.ts._inject-bak'
const sha = (b) => createHash('sha256').update(b).digest('hex')

const original = readFileSync(P)
const origSha = sha(original)
copyFileSync(P, BAK)
console.log('原文件 sha256 = ' + origSha.slice(0, 16) + ' bytes=' + original.length)

const INJECTIONS = [
  {
    name: 'A：去掉 stable 闸门（提前念还在长的尾巴）',
    old: '      if (!seg.stable && !ended) break // ② 还在长 → 后面的都先别念（保序）\n',
    neu: '      // INJECT-A: stable 闸门被移除\n',
  },
  {
    name: 'B：去掉原文游标去重（同一段会被反复念）',
    old: '      if (seg.raw_end <= cursor) continue // ① 念过的（或已入队的）不再吃\n',
    neu: '      // INJECT-B: 游标去重被移除\n',
  },
]

function runProbe() {
  const r = spawnSync(process.execPath, ['scripts/cdp-tts-pipeline-measure.mjs'], {
    cwd: 'D:/ai/eCommerce/frontend',
    encoding: 'utf8',
    maxBuffer: 32 * 1024 * 1024,
    env: { ...process.env, TTS_FAST: '1' },
  })
  const out = (r.stdout || '') + (r.stderr || '')
  const m = out.match(/★★ VERDICT overall=(true|false) textOk=(true|false) segOk=(true|false) gapOk=(true|false)/)
  const seg = out.match(/流式 (\d+) 段 \/ 计划 (\d+) 段/)
  const first = out.match(/firstSoundMs=([\d.]+)/)
  return {
    raw: out,
    /** 三项断言的总判定（textOk && segOk && gapOk） */
    overall: m ? m[1] : 'MISSING',
    textOk: m ? m[2] : '?',
    segOk: m ? m[3] : '?',
    gapOk: m ? m[4] : '?',
    segs: seg ? seg[1] + '/' + seg[2] : '?',
    firstSoundMs: first && first[1] !== '?' ? Math.round(Number(first[1])) : null,
  }
}

let allGood = true

// ---- 第 0 步：未注入时必须为绿（否则「变红」说明不了任何事）----
console.log('\n================ 基线（未注入，必须 overall=true）================')
{
  const res = runProbe()
  console.log(
    `  overall=${res.overall} textOk=${res.textOk} segOk=${res.segOk} gapOk=${res.gapOk}` +
      `；段数 流式/计划 = ${res.segs}，首声 = ${res.firstSoundMs}ms`
  )
  if (res.overall !== 'true') {
    console.log('  ✗ 基线不是绿的 → 中止（先查真实现，别急着注入）')
    process.exit(1)
  }
  console.log('  ✔ 基线绿')
}

for (const inj of INJECTIONS) {
  console.log('\n================ ' + inj.name + ' ================')
  let src = original.toString('utf8')
  const n = src.split(inj.old).length - 1
  if (n !== 1) {
    console.log('  ✗ 锚点命中 ' + n + ' 次（要求 1）→ 中止，不动文件')
    allGood = false
    break
  }
  src = src.replace(inj.old, inj.neu)
  writeFileSync(P, src)
  const injSha = sha(readFileSync(P))
  console.log('  注入后 sha256 = ' + injSha.slice(0, 16) + '（与原文件不同 = ' + (injSha !== origSha) + '）')

  const res = runProbe()
  // 注入后 total 判定必须为 false（三项里至少一项红）
  const caught = res.overall === 'false'
  console.log(
    `  探针判定：overall=${res.overall} textOk=${res.textOk} segOk=${res.segOk} gapOk=${res.gapOk}` +
      `；段数 流式/计划 = ${res.segs}，首声 = ${res.firstSoundMs}ms`
  )
  console.log('  ' + (caught ? '✔ 被抓住（总判定变红）' : '✗ 没抓住 —— 说明这套检查是假绿！'))
  if (!caught) {
    allGood = false
    const lines = res.raw.split('\n').filter((l) => /流式|计划|不变量|不变量|VERDICT|排期/.test(l)).slice(0, 10)
    console.log('  探针相关输出：\n' + lines.map((l) => '    ' + l).join('\n'))
  }

  // 字节级还原
  writeFileSync(P, original)
  const backSha = sha(readFileSync(P))
  const restored = backSha === origSha
  console.log('  还原后 sha256 = ' + backSha.slice(0, 16) + ' → byte-identical: ' + restored)
  if (!restored) {
    console.log('  ✗✗ 还原失败，请立刻用 ' + BAK + ' 恢复')
    allGood = false
    break
  }
}

console.log('\n================ 汇总 ================')
console.log(allGood ? '✔ 两个注入都被抓住，且文件已字节级还原' : '✗ 有注入未被抓住或还原失败')
process.exit(allGood ? 0 : 1)
