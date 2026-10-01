/**
 * Vitest 配置（第 355 轮 · #1282 前端单测起步）
 * ============================================================================
 * ★ 为什么用 `mergeConfig` 复用 `vite.config.ts`，而不是另写一份配置：
 *   `@` 别名是全前端所有 import 的前缀（`@/utils/...`、`@/stores/...`）。
 *   若在这里**手抄**一遍 `resolve.alias`，两份配置就会各自漂移 ——
 *   改了一处、另一处静默不同步，症状是「测试里 import 不到、应用里照跑」
 *   （与项目记忆里「同一判定两份实现 ⇒ 至少一份永远测不到」同族）。
 *   ⇒ 直接 import 同一份 `vite.config.ts` 再 merge，别名只有**一个**真源。
 *
 * ★ 为什么 `environment: 'node'` 而不是 `jsdom`：
 *   首批靶点是纯函数（`utils/colorSemantics.ts` / `utils/competitorSimilarity.ts`），
 *   完全不碰 DOM。jsdom 既慢又要多一个依赖 ⇒ 等真有组件用例时再加，别预先装。
 *
 * ★ 为什么**不开** `globals: true`：
 *   让用例显式 `import { describe, it, expect } from 'vitest'`。
 *   开了 globals 就得往 tsconfig 塞 `types: ["vitest/globals"]`，
 *   而且 `describe/it/expect` 会变成「未声明的全局标识符」⇒ 与 `strict` 冲突。
 *   显式导入零配置、也不依赖任何全局桩。
 *
 * ★ 为什么显式写 `include` + `passWithNoTests: false`：
 *   `include` 写歪（或目录改名）时，vitest 的默认行为是「0 个用例 = 通过」——
 *   这正是本仓反复记录的「常绿假门禁 / 覆盖率不足却全绿」形态。
 *   显式 pattern + 禁用 no-tests 通过 ⇒ 空集合必须红。
 *
 * ★★ 为什么 `fileParallelism: false`（串行跑测试文件）—— 这是**实测**得出的，
 *   不是保守起见，也不是猜的：
 *
 *   现象：默认并行下**必现**（连跑 4 次，4/4）——
 *         ```
 *         ✓ tests/unit/competitorSimilarity.test.ts (25 tests)
 *         ⎯ Unhandled Error: EPERM: operation not permitted, open
 *           '<tmp>/ssr/40b9f1f37d5bd759c353e90078138580f67eb091'
 *         Test Files  1 passed (1)      ← 另一个测试文件被整份丢弃！
 *         Errors      1 error
 *         ```
 *   定位：写入点 = vitest `ModuleRunner.fetchModule`——
 *         把转换后的模块码写到 `tmpDir/<transformMode>/<sha1(id)>`（无扩展名）。
 *         该函数在「查缓存」与「写文件」之间夹了一个 `await mkdir(dir)`，
 *         于是**并发取同一个模块**时会两次写同一路径 ⇒ 本机的 fs 代理
 *         （WorkBuddy CLI 注入的 `node-brokered-fs-shim.cjs`）返回 EPERM。
 *         实测：把 `os.tmpdir()` 指到工作区内、换 `--pool`、换 `TMP/TEMP/TMPDIR`
 *         都**不能**消除；只有串行才消除（`--no-file-parallelism` ⇒ 0 error / 退出码 0）。
 *   影响面：**不静默** —— 这种跑法 vitest 退出码是 **1**（实测），CI 会红。
 *         但输出极具误导性（「Test Files 1 passed」+ 一个看不懂的临时路径），
 *         且被丢掉的测试文件**不固定**（两次运行分别丢了不同的那个）。
 *   取舍：本仓当前只有纯逻辑用例，串行与并行差 ~0.1s（实测 1.12s vs 0.99s）；
 *         换来的是「跑出来的绿 = 真的都跑过」。**用例变重之后可以把这一行删掉**，
 *         删掉前请先确认上面的 EPERM 不再复现。
 */
import { defineConfig, mergeConfig } from 'vitest/config'
import viteConfig from './vite.config'

export default mergeConfig(
  viteConfig,
  defineConfig({
    test: {
      environment: 'node',
      include: ['tests/**/*.test.ts'],
      // 一个用例都没收集到 ⇒ 直接失败，而不是"没有失败所以通过"
      passWithNoTests: false,
      // 见文件头：默认并行会因 fs 代理的 EPERM **丢掉一个测试文件**（实测必现）
      fileParallelism: false,
    },
  }),
)
