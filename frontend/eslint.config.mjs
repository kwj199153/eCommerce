/**
 * ESLint flat config —— 「棘轮第一档」（第 346 轮 · F-1）
 * ============================================================================
 * 依据：`docs/baseline-r345-lint.md`（第 345 轮实测基线）
 *       `docs/plan-l3-batches.md` §1.3「棘轮怎么设」
 *
 * ★ 为什么不能把 `flat/recommended` 预设直接当门禁 —— 方向是反的：
 *     ruff 的 `--select` 是**白名单**（只跑我列的）⇒ 天然棘轮，往名单里加项就行；
 *     ESLint 默认**全开**（除关掉的都跑）⇒ 三个官方推荐预设一次开 204 条，
 *     本仓存量 8116 条问题 ⇒ 常红 ⇒ 必然被 `--no-verify` 绕过（原则四：常红的门禁 = 没有门禁）。
 *   ⇒ 必须**反向**做：先跑基线拿真实数字，只把「已生效且有违规」的显式登记并关掉。
 *
 * ★ 本档的口径（全部实测，非估计）：
 *     print-config 规则数                       204
 *       ├─ 有违规（8116 条问题全部出自这 21 条）   21  → 下方 LEGACY_DEBT_OFF 显式关闭
 *       ├─ 已生效且零违规                        162  → 由 `--max-warnings=0` 进入强制
 *       │     （档位 error 141 + 档位 warn 21；**warn 也按失败处理**，否则那 21 条没牙齿）
 *       └─ 基线即为关闭                           21  → 保持关闭，本文件**不动它们**
 *     ⇒ 落地后 `eslint .` 的结果应当是 **0 problem**（可验收的硬判据）。
 *
 * ★★ 为什么**不**把 162 条显式钉成 'error'（第一版就是这么做的，错了）：
 *     档位是**按文件类解析**的 —— 同一条规则在 `.ts` / `.vue` / `.mjs` 上可以不同。
 *     把「基线里在 A 文件类是关闭的」规则全局钉成 'error'，就会在 A 文件类里**新开一道闸**。
 *     实测后果：第一版配置让 `scripts/*.mjs` 冒出 core `no-unused-vars` / `prefer-const`
 *     等一批新 error —— 那些不是存量问题，是新开的检查在报。
 *     要收紧档位，必须逐文件类实测后按 `files` 作用域分别钉，属于后续档位的事。
 *
 * ★★ 那 21 条「基线即关闭」的是什么：
 *   - constructor-super
 *   - getter-return
 *   - no-array-constructor
 *   - no-class-assign
 *   - no-const-assign
 *   - no-dupe-args
 *   - no-dupe-class-members
 *   - no-dupe-keys
 *   - no-func-assign
 *   - no-import-assign
 *   - no-new-native-nonconstructor
 *   - no-new-symbol
 *   - no-obj-calls
 *   - no-redeclare
 *   - no-setter-return
 *   - no-this-before-super
 *   - no-unreachable
 *   - no-unsafe-negation
 *   - no-unused-expressions
 *   - no-unused-vars
 *   - no-with
 *   它们是 typescript-eslint 的 `eslint-recommended` 刻意关掉的核心规则
 *   （TS 编译器已经覆盖同类检查）⇒ 关闭是**正确**的，不是欠账。
 *
 * ★ 怎么收紧（只增不减）：
 *     ① 清干净某条欠账（例：F-2 用 `--fix` 自动修掉三条 vue 格式规则，约 6286 处）
 *     ② 把该条从下面这个「欠账表」删掉
 *     ③ 重跑 `npx eslint .` 确认仍是 0 problem
 *     `scripts/check-eslint-ratchet.cjs` 会守住：已生效的规则集合不得缩水、
 *     欠账集合不得新增条目（挡住「想消红就把规则丢进欠账」这条路）。
 *
 * ★ 读集：除 node_modules / dist / coverage / 压缩产物外**不排除任何目录**，
 *   与基线扫到的 320 个文件口径一致（新增配置与门禁文件后会变成 322）。
 */
import js from '@eslint/js'
import tseslint from 'typescript-eslint'
import pluginVue from 'eslint-plugin-vue'
import globals from 'globals'

/**
 * 欠账表：第 345 轮基线里**有违规**的 21 条规则 ⇒ 显式关闭。
 * 每条后面的注释是该规则当时的存量条数（合计 8116）。
 * ★ 不得新增条目 —— `scripts/check-eslint-ratchet.cjs` 会红。
 * ★ 收口方向：先清存量，再把条目从这里删掉（删掉即回到预设档位 = 收紧）。
 */
export const LEGACY_DEBT_OFF = {
  // ---- ESLint 核心（4 条）----
  "no-case-declarations": 'off',  // 存量 9 条
  "no-empty": 'off',  // 存量 12 条
  "no-undef": 'off',  // 存量 13 条
  "no-useless-escape": 'off',  // 存量 4 条

  // ---- typescript-eslint（4 条）----
  "@typescript-eslint/no-explicit-any": 'off',  // 存量 689 条
  "@typescript-eslint/no-require-imports": 'off',  // 存量 112 条
  "@typescript-eslint/no-unused-expressions": 'off',  // 存量 1 条
  "@typescript-eslint/no-unused-vars": 'off',  // 存量 103 条

  // ---- eslint-plugin-vue（13 条）----
  "vue/attribute-hyphenation": 'off',  // 存量 77 条
  "vue/attributes-order": 'off',  // 存量 154 条
  "vue/first-attribute-linebreak": 'off',  // 存量 9 条
  "vue/html-closing-bracket-newline": 'off',  // 存量 3 条
  "vue/html-closing-bracket-spacing": 'off',  // 存量 10 条
  "vue/html-indent": 'off',  // 存量 1529 条
  "vue/html-self-closing": 'off',  // 存量 132 条
  "vue/max-attributes-per-line": 'off',  // 存量 2607 条
  "vue/multi-word-component-names": 'off',  // 存量 7 条
  "vue/multiline-html-element-content-newline": 'off',  // 存量 83 条
  "vue/no-v-html": 'off',  // 存量 8 条
  "vue/singleline-html-element-content-newline": 'off',  // 存量 2522 条
  "vue/v-on-event-hyphenation": 'off',  // 存量 31 条
}

export default tseslint.config(
  // ★ 只放 ignores 的对象 = 「全局忽略」。别再往里加别的键：
  //   同对象一旦出现其他配置键，ignores 会退化成「只对该对象生效」的过滤器，
  //   全局忽略静默失效（本仓踩过的同形坑：条件挂载的假门禁）。
  {
    ignores: [
      'node_modules/**',
      'dist/**',
      'coverage/**',
      '**/*.min.js',
    ],
  },
  {
    // 多余的 `eslint-disable` 指令本身就是欠账（会让下一个人以为那里真有问题）。
    // ESLint 9 默认为 'warn'，这里提为 error，让存量也无法在 CI 里蒙混。
    linterOptions: {
      reportUnusedDisableDirectives: 'error',
    },
  },

  // ---- 规则集：与基线**逐条相同**的三个官方推荐全集 ----
  js.configs.recommended,
  ...tseslint.configs.recommended,
  ...pluginVue.configs['flat/recommended'],

  {
    languageOptions: {
      // ★ 这不是「裁剪规则」，是让规则有意义：本仓 tsconfig 未声明 globals，
      //   而 ESLint 不做类型解析、看不到 tsconfig ⇒ 不配的话 window/document/process
      //   全被 `no-undef` 报成未定义（那类报错无法区分「真未定义」与「本该是全局」）。
      globals: { ...globals.browser, ...globals.node },
      ecmaVersion: 2022,
      sourceType: 'module',
    },
  },
  {
    // .vue 的 <script lang="ts">：需要「vue parser 包 ts parser」两层结构
    files: ['**/*.vue'],
    languageOptions: {
      parserOptions: {
        parser: tseslint.parser,
        ecmaVersion: 2022,
        sourceType: 'module',
      },
    },
  },

  // ---- 棘轮档：放在最后 ⇒ 覆盖上面预设给的档位 ----
  { name: 'ratchet/legacy-debt-off', rules: LEGACY_DEBT_OFF },
)
