/**
 * 共享读取器：把**对话编排域**的全部源码当成一份文本。
 *
 * ★ 为什么需要它（第 169 轮 #664「按域拆编排器」）：
 *   编排层原本是单文件 `src/composables/useChatOrchestrator.ts`（1,744 行 / 91 KB），
 *   有三个门禁直接按路径读它。拆成「壳 + `composables/chat/**`」之后，
 *   如果门禁还盯着单文件，就会**假红**（能力明明还在、门禁说没了）。
 *   假红比不检查更糟 —— 下一个人会把断言删掉，而不是把路径改对。
 *
 * ★ 判据口径显式改写为「**编排域**里有没有这个能力」。这与门禁原意一致：
 *   它们判的从来不是「这段代码住在哪个文件」。
 *
 * ★ 为什么文件名以 `_` 开头：**它不是门禁**。
 *   CI 用 `for f in scripts/check-*.*` 的 glob 枚举 + 「覆盖率自证」
 *   （实跑数必须等于磁盘 `check-*` 数），所以 helper 不能被 glob 捞到。
 *   同族先例：`scripts/_flip_tts_gate.cjs`。
 *
 * ★ 因此**反向注入也必须跟着改口径**：注入要改到「域里真正持有该能力的那个文件」
 *   （例如计划链路的 `setPlan` 在 `chat/replies/secretary.ts` 而不在壳里）。
 *   只改壳的副本 ⇒ 门禁不红 ⇒ 你会误以为门禁失效，其实是注入打偏了。
 *
 * 用法：
 *   const { readOrchestratorDomain, resolvePair } = require('./_orch-domain.cjs')
 *   const { shell, dir } = resolvePair(ROOT)                  // 真源
 *   const { text, files } = readOrchestratorDomain(shell, dir)
 */
const fs = require('fs')
const path = require('path')

const SHELL_REL = path.join('src', 'composables', 'useChatOrchestrator.ts')
const DOMAIN_REL = path.join('src', 'composables', 'chat')

/** 给一个前端根目录，返回 (壳, 域目录) 的绝对路径。 */
function resolvePair(root) {
  return { shell: path.join(root, SHELL_REL), dir: path.join(root, DOMAIN_REL) }
}

function collect(dir, out) {
  for (const e of fs.readdirSync(dir, { withFileTypes: true })) {
    if (e.name === 'node_modules' || e.name === 'dist') continue
    const p = path.join(dir, e.name)
    if (e.isDirectory()) collect(p, out)
    else if (/\.(ts|mts|js)$/.test(e.name)) out.push(p)
  }
  return out
}

/**
 * @param {string} shell 壳文件绝对路径（`useChatOrchestrator.ts`）
 * @param {string} [dir] 域目录绝对路径（`composables/chat`）；不存在则只读壳
 * @returns {{ text: string, files: string[] }} text = 全部源码按「壳 → 域内文件（排序）」拼接
 */
function readOrchestratorDomain(shell, dir) {
  if (!shell || !fs.existsSync(shell)) throw new Error('未找到编排壳：' + shell)
  const files = [shell]
  if (dir && fs.existsSync(dir)) collect(dir, files)
  const text = files.map((p) => fs.readFileSync(p, 'utf8')).join('\n')
  return { text, files }
}

module.exports = { readOrchestratorDomain, resolvePair, SHELL_REL, DOMAIN_REL }
