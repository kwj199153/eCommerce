/**
 * 用留存的样本文件重建被误删的音色。
 *
 * ★★★ 为什么需要这个脚本 ★★★
 * 2026-09-15 01:42:53，做「删除音色」搬迁的反向注入时，编排脚本把代码切回了**修复前**版本，
 * 而修复前的按钮是 `@click="handleDelete"`（点击即执行删除、无二次确认）——
 * 布局探针点了一下它，**真的删掉了老板「亚马逊2」的音色**：
 *     [voice-clone] 已删除音色记录 shop=store_a498a7d5 remote_deleted=True
 *     DELETE /api/v1/voice-clone -> 200
 * 远端 DashScope 音色与本地记录都已删除，样本文件仍在（未被 delete_record 清理）：
 *     uploads/voice/ae5ccd1b47f622d1.wav  966700 B
 * ⇒ 用同一个样本重新 enroll，即可重建一个音色（voice_id 会变，音色一致）。
 *
 * ⚠️ 执行前必须得到老板确认：enroll 会**消耗一次远端声音复刻配额**。
 *
 * 用法：node scripts/_restore_voice.cjs            # 干跑，只打印将要发送的请求
 *       node scripts/_restore_voice.cjs --go       # 真执行
 */
const SHOP = process.env.VC_SHOP || 'store_a498a7d5'
const SAMPLE = process.env.VC_SAMPLE || '/static/voice/ae5ccd1b47f622d1.wav'
const MODEL = process.env.VC_MODEL || 'cosyvoice-v3-flash'
const BY = process.env.VC_BY || 'demo-user-001'
const GO = process.argv.includes('--go')
const API = 'http://127.0.0.1:8000'

async function main() {
  const statusUrl = `${API}/api/v1/voice-clone/status`
  const before = await (await fetch(statusUrl, { headers: { 'X-Shop-ID': SHOP } })).json()
  console.log('当前状态:', JSON.stringify(before))
  if (before.ready) {
    console.log('✓ 该店铺已有 ready 音色，无需恢复。中止。')
    process.exit(0)
  }

  // 确认样本文件仍然可达（后端按 /static/ 前缀读本地文件）
  const sampleUrl = `${API}${SAMPLE}`
  try {
    const r = await fetch(sampleUrl)
    const buf = Buffer.from(await r.arrayBuffer())
    console.log(`样本可达性: HTTP ${r.status}  ${buf.length} B  ${r.headers.get('content-type')}`)
    if (!r.ok || buf.length < 1024) throw new Error('样本不可用')
  } catch (e) {
    console.log('✗ 样本不可达，无法重建：' + e.message)
    process.exit(1)
  }

  const body = { sample_url: SAMPLE, authorized_by: BY, target_model: MODEL }
  console.log('\n将发送 POST /api/v1/voice-clone/enroll')
  console.log('  X-Shop-ID: ' + SHOP)
  console.log('  body: ' + JSON.stringify(body))
  console.log('  ⚠️ 这会消耗一次远端声音复刻配额')

  if (!GO) {
    console.log('\n（干跑结束。加 --go 才真正执行）')
    process.exit(0)
  }

  console.log('\n执行中…')
  const t0 = Date.now()
  const r = await fetch(`${API}/api/v1/voice-clone/enroll`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json', 'X-Shop-ID': SHOP },
    body: JSON.stringify(body),
  })
  const txt = await r.text()
  console.log(`HTTP ${r.status}  耗时 ${Date.now() - t0}ms`)
  console.log(txt.slice(0, 1200))

  const after = await (await fetch(statusUrl, { headers: { 'X-Shop-ID': SHOP } })).json()
  console.log('\n恢复后状态:', JSON.stringify(after))
  process.exit(after.ready || after.exists ? 0 : 1)
}

main().catch((e) => { console.error(e); process.exit(2) })
