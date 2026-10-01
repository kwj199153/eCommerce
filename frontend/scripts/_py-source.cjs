/**
 * 读 **Python 模块源码**（单文件 ⇄ 包，双态）—— 前端门禁的共享读取点（第 355 轮）。
 * ============================================================================
 * ★ 为什么需要它：本仓有 **15 个前端门禁直接读 `backend/` 的源码**
 *   （`check-order-track-parity` / `check-tool-reality` / `check-hitl-approval` …）。
 *   后端把一个 `x.py` 拆成 `x/` 包时，这些门禁里的
 *   `path.resolve(..., 'x.py')` 会**读不到文件** ——
 *   而它们的失败形态还不一样：
 *     · 有的直接 `process.exit(1)`（红，好定位）
 *     · 有的用 `indexOf` 定位符号，文件读成空串 ⇒ 符号找不到 ⇒ 报「定位不到 xxx」
 *       （看着像后端改坏了，其实是路径形态变了）
 *     · 最坏的是「读到的窗口跨文件拼接」⇒ 抽出来的清单**静默变错**（不再报错）
 *   ⇒ 读取点只留一份实现，形态问题在这一个地方解决。
 *
 * ★ 为什么不在每个门禁里各写一遍 `fs.statSync().isDirectory()` 分支：
 *   本仓明令禁止同一判定多份实现 —— 15 个调用点各写一遍，
 *   下次改口径必然漏掉几个，而且漏掉的那些**不会有人发现**。
 *
 * ★ 与后端侧 `backend/tests/pkg_source.py` 的分工：
 *   两边是同一套契约、各自语言的一份实现（跨语言无法共用代码）。
 *   契约必须一致：**文件 ⇒ 该文件；同名目录 ⇒ 目录内 `*.py` 按名排序拼接；
 *   都没有 ⇒ 显式报错（绝不返回空串）**。
 *   ⚠️ 改契约时**两边都要改** —— 这条是跨语言重复，只能靠注释互指。
 *
 * ★ 目录名：以 `_` 开头 ⇒ 不匹配 CI 的 `scripts/check-*.*` glob
 *   ⇒ 不会被当门禁执行、也不进「门禁覆盖率自证」的计数（与既有
 *   `_orch-domain.cjs` 等 7 个辅助文件同一约定）。
 */

const fs = require('fs')
const path = require('path')

/** 列出一个目录里的 `*.py`（按文件名排序 ⇒ 拼接顺序稳定） */
function pyFilesIn(dir) {
  return fs
    .readdirSync(dir)
    .filter((n) => n.endsWith('.py'))
    .sort()
    .map((n) => path.join(dir, n))
    .filter((f) => fs.statSync(f).isFile())
}

/**
 * 解析 Python 模块路径 → `{ kind, files }`；两者都不存在时返回 `null`。
 *
 * @param {string} p 指向 `x.py`（文件或同名包）或包目录的路径
 */
function resolvePyModule(p) {
  if (fs.existsSync(p)) {
    const st = fs.statSync(p)
    if (st.isFile()) return { kind: 'file', files: [p] }
    if (st.isDirectory()) return { kind: 'dir', files: pyFilesIn(p) }
  }
  // 调用点写的通常是 `.py` 文件名；拆包后实际是**同名目录** ⇒ 再试一次无后缀形态
  if (p.endsWith('.py')) {
    const pkg = p.slice(0, -3)
    if (fs.existsSync(pkg) && fs.statSync(pkg).isDirectory()) {
      return { kind: 'dir', files: pyFilesIn(pkg) }
    }
  }
  return null
}

/**
 * 读 Python 模块的源码文本（双态）。
 *
 * @param {string} p
 * @returns {string} 行尾统一归一化为 `LF`
 * @throws {Error} 找不到（文件与同名包都不存在），或目录里没有任何 `.py`
 *   —— **绝不返回空串**：空串会让调用方的「符号定位」判据恒真空跑。
 */
function readPyModule(p) {
  const r = resolvePyModule(p)
  if (!r) {
    throw new Error(
      `读不到 Python 模块源码：${p}` +
        (p.endsWith('.py') ? `（同名包 ${p.slice(0, -3)} 也不存在）` : ''),
    )
  }
  if (r.files.length === 0) {
    throw new Error(`${p} 是目录但里面没有任何 .py 文件 —— 判据会恒真，拒绝静默放过`)
  }
  return r.files
    .map((f) => fs.readFileSync(f, 'utf8').replace(/\r\n/g, '\n'))
    .join('\n')
}

module.exports = { readPyModule, resolvePyModule, pyFilesIn }
