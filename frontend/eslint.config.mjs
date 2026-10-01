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
 *   ★ 演进：第 348 轮 F-2 欠账 21 → 10（11 条 vue 格式规则清零后移出）；
 *           第 349 轮欠账 10 → 9（`vue/multi-word-component-names` 移出，改用策略档豁免）。
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

  // ---- eslint-plugin-vue（1 条）----
  // ★ 第 348 轮 F-2：11 条「全可自动修」的 vue 规则已清空并移出本表（合计 6285 处）——
  //   html-indent / max-attributes-per-line / singleline&multiline-html-element-content-newline /
  //   attributes-order / html-self-closing / attribute-hyphenation / v-on-event-hyphenation /
  //   html-closing-bracket-spacing & -newline / first-attribute-linebreak。
  //   实测：清理后「清空欠账」口径下这 11 条均为 0，无残留。
  // ★ 第 349 轮：`vue/multi-word-component-names` 已**移出**本表 —— 7 条违规全是合理豁免的
  //   单名组件（index ×2 + 5 个视图页），改用下方 `ratchet/component-name-policy` 策略档
  //   显式豁免那 6 个名字，规则本身回到 preset 的 'error'。
  "vue/no-v-html": 'off',  // 存量 8 条（安全审计项，不可自动修）
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

  // ★ 第 349 轮：`vue/multi-word-component-names` 的**策略档**（不再属于欠账表）。
  //   为什么豁免而不是改名 —— 这 6 个名字都是既定的合理形态：
  //     · `index` —— 目录入口组件的约定名（ChatPanel / TaskConfigPanel 各一个）
  //     · `Login` / `Settings` / `Subscription` / `Team` / `Workspace`
  //       —— 视图级页面组件，名字在 src/views 下唯一
  //   该规则的本意是防止组件名与 HTML/SVG 原生标签（header / main / transition …）撞名，
  //   这 6 个都不撞。改名会断掉全部 import 路径、路由表与既有门禁锚点，代价远大于收益。
  //   ★ 这是**收紧**不是放宽：此前该规则在欠账表里是 'off'（一个名字都不查），
  //     现在除这 6 个名字外，**任何**单名组件都会被 error 拦住。
  //     反向注入自证：`.workbuddy/probes/r349/revinject_mw.py`。
  {
    name: 'ratchet/component-name-policy',
    rules: {
      'vue/multi-word-component-names': ['error', {
        ignores: ['index', 'Login', 'Settings', 'Subscription', 'Team', 'Workspace'],
      }],
    },
  },
)
