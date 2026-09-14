/**
 * 独立核验：VoiceClonePanel.vue 的「删除音色」搬迁是否正确。
 *
 * ⚠️ 两条踩过的坑都写进断言里：
 *  ① 区间终点必须用 lastIndexOf('</template>') —— 首个 '</template>' 是第 10 行
 *     `<template #title>` 的闭合，用它当终点会让区间为空 ⇒ 永远通过（假绿）。
 *  ② 计数前必须剥注释 —— 我在步骤 3 写了含「删除音色」字样的说明注释，
 *     不剥注释就会数出 2 ⇒ 把正确结果误判成失败。
 */
const fs = require('fs')

const P = 'src/components/Settings/VoiceClonePanel.vue'
const raw = fs.readFileSync(P, 'utf8')
const cnt = (hay, n) => hay.split(n).length - 1

/** 剥掉 HTML 注释与 JS 行注释（`//`，但保留 `://` 里的斜杠） */
function stripComments(text) {
  return text
    .replace(/<!--[\s\S]*?-->/g, '')
    .replace(/(^|\s)\/\/[^\n]*/g, '$1')
    .replace(/\/\*[\s\S]*?\*\//g, '')
}

const tplEnd = raw.lastIndexOf('</template>')
const step3Start = raw.indexOf('步骤 3：创建音色')
const step4Start = raw.indexOf('步骤 4：试听')
if (tplEnd < 0 || step3Start < 0 || step4Start < 0 || !(step3Start < step4Start && step4Start < tplEnd)) {
  throw new Error('区间定位失败')
}

const tplRaw = raw.slice(0, raw.indexOf('<script'))
const tpl = stripComments(tplRaw)
const step3 = stripComments(raw.slice(step3Start, step4Start))
const step4 = stripComments(raw.slice(step4Start, tplEnd))
const code = raw.slice(raw.indexOf('<script'))

const checks = [
  // ── 位置：删除按钮在步骤 3、不在步骤 4 ──
  ['步骤 3 有「删除音色」按钮文字', cnt(step3, '>删除音色<'), 1],
  ['步骤 3 有 popconfirm 包裹', cnt(step3, '<a-popconfirm'), 1],
  ['步骤 4 无「删除音色」', cnt(step4, '删除音色'), 0],
  ['模板内 @confirm="handleDelete"', cnt(tpl, '@confirm="handleDelete"'), 1],
  ['步骤 4 无 handleDelete 调用', cnt(step4, 'handleDelete'), 0],
  ['步骤 3 在步骤 4 之前', step3Start < step4Start ? 1 : 0, 1],

  // ── 二次确认：删除必须经 popconfirm ──
  ['模板内 handleDelete 引用总数（应仅 popconfirm 一处）', cnt(tpl, 'handleDelete'), 1],

  // ── 错误归属：4 个 scope 各渲染一处 ──
  ["模板 errorScope === 'status'", cnt(tpl, "errorScope === 'status'"), 1],
  ["模板 errorScope === 'sample'", cnt(tpl, "errorScope === 'sample'"), 1],
  ["模板 errorScope === 'enroll'", cnt(tpl, "errorScope === 'enroll'"), 1],
  ["模板 errorScope === 'preview'", cnt(tpl, "errorScope === 'preview'"), 1],
  ['script setError 调用', cnt(code, "setError('"), 5],
  ['script setError 定义', cnt(code, 'function setError'), 1],
  // 5 个动作的归属必须一一对应，别只是「都调了 setError」
  ["上传 → sample", cnt(code, "setError('sample'"), 1],
  ["创建 → enroll", cnt(code, "setError('enroll', e?.response?.data?.detail || e?.message || '创建音色失败'"), 1],
  ["查询状态 → status", cnt(code, "setError('status'"), 1],
  ["试听 → preview", cnt(code, "setError('preview'"), 1],
  ["删除 → enroll", cnt(code, "setError('enroll', e?.response?.data?.detail || e?.message || '删除音色失败'"), 1],

  // ── CSS ──
  ['CSS 定义 .vc-danger-row', cnt(raw, '.vc-danger-row {'), 1],
  ['模板使用 vc-danger-row', cnt(tpl, 'class="vc-danger-row"'), 1],

  // ── 结构配对（tsc 不校验 HTML 结构平衡）──
  // a-alert：原 5 个（顶部状态条 4 + 步骤 4 的 lastError）+ 本次新增 3 个（status/sample/enroll）= 8
  // 其中只有顶部前两个带 slot，需要闭合标签，故 </a-alert> = 2，其余 6 个是自闭合 `/>`
  ['<a-card 开', cnt(tplRaw, '<a-card'), 4],
  ['</a-card> 闭', cnt(tplRaw, '</a-card>'), 4],
  ['<a-popconfirm 开', cnt(tplRaw, '<a-popconfirm'), 1],
  ['</a-popconfirm> 闭', cnt(tplRaw, '</a-popconfirm>'), 1],
  ['<a-alert 开', cnt(tplRaw, '<a-alert'), 8],
  ['</a-alert> 闭（带 slot 的两个）', cnt(tplRaw, '</a-alert>'), 2],
  ['自闭合 a-alert 收尾行 `/>` 数', tplRaw.split('\n').filter((l) => l.trim() === '/>').length >= 6 ? 1 : 0, 1],
]

let ok = true
for (const [name, got, want] of checks) {
  const pass = got === want
  if (!pass) ok = false
  console.log(`${pass ? '  ✔' : '  ✗'} ${name} = ${got}${pass ? '' : ` (期望 ${want})`}`)
}

const crlf = cnt(raw, '\r\n')
const bareLF = (raw.match(/(?<!\r)\n/g) || []).length
console.log(`\n行尾: CRLF=${crlf}  bareLF=${bareLF}`)
if (crlf !== 0) {
  ok = false
  console.log('  ✗ 行尾被改成 CRLF')
}

console.log(ok ? '\n★★ VERIFY OK' : '\n★★ VERIFY FAILED')
process.exit(ok ? 0 : 1)
