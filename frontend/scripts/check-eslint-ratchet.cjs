#!/usr/bin/env node
/**
 * 门禁：ESLint 棘轮「不得回退」（第 346 轮 · F-1；第 348 轮 · F-2 收紧：欠账 21→10、生效 181→192；
 *       第 349 轮：欠账 10→9、生效 192→193）
 * ============================================================================
 * 为什么需要这个文件：`frontend/eslint.config.mjs` 只是**当前**的档位；
 * 没有门禁的话「棘轮只增不减」只是注释里的一句口头约定 ——
 * 下次谁把某条 error 规则改成 off，没有任何东西会吭声。
 * （`docs/review-principles.md` 原则四的反面：门禁必须能被反向注入打红。）
 *
 * ★ 判据怎么来的（两条硬规矩）：
 *   ① 档位**不问字符串、问库本身** —— 用 ESLint 自己的 `calculateConfigForFile`
 *      解析真实档位。用文本正则去抠 config 文件会被注释 / 被注释掉的规则骗过 ⇒ 假绿。
 *   ② 冻结值**从实测产物生成**，不手写。手写 = 期望值靠记忆 ⇒ 下一轮就是假绿来源。
 *
 * ★ 为什么按**文件类**分别取，而不是一份全局快照：
 *   档位是按文件类解析的 —— 实测有 23 条规则只在部分文件类上生效
 *   （例：`constructor-super` 在 .ts 上是 0、在 .vue/.cjs/.mjs 上是 2）。
 *   本轮第一版配置就是拿单份快照当全局口径，把 21 条「在 .ts 上本来就关着」的
 *   规则提成 error ⇒ 等于给仓库新开 21 道闸 ⇒ 冒出一批不是存量的新 error。
 *
 * 四条断言：
 *   R1 生效集合不缩水：FLOOR_ENFORCED 里每条规则，至少在**一个**代表文件类上仍是 > 0
 *   R2 逐类条数不缩水：每个代表文件类上的生效规则数 >= 冻结值
 *   R3 欠账不扩张：config 导出的 LEGACY_DEBT_OFF ⊆ 冻结欠账表，且与生效集合无交集
 *   R4 自检：三张表都非空、条数与冻结时一致（防本文件自己被截断成空表 ⇒ 恒真）
 *
 * ★ 已知边界（如实登记）：R1/R2 能挡住「全局关掉某规则」与「整类缩水」，
 *   挡不住「只把某一类上的一条规则关掉而总量不变」——那属于后续档位的加强与实测。
 *
 * 反向注入（证明它有牙齿）：
 *   ① 在 config 的 LEGACY_DEBT_OFF 里加一条冻结时没有的规则 ⇒ R3 红
 *   ② 把 config 里某条现有规则……（本轮 config 只含欠账表，故用 ① 与 ③）
 *   ③ 把本文件的 FLOOR_ENFORCED 清空 ⇒ R4 红（自检有效）
 */
const path = require('path')
const { createRequire } = require('module')

const FE_ROOT = path.resolve(__dirname, '..')
const requireFE = createRequire(path.join(FE_ROOT, 'package.json'))

/** 冻结：F-1 的 181 条 + 第 348 轮新增 11 条 + 第 349 轮新增 1 条
 *  = 193 条「在任一代表文件类上档位 > 0」的规则 */
const FLOOR_ENFORCED = [
  "@typescript-eslint/ban-ts-comment",
  "@typescript-eslint/no-array-constructor",
  "@typescript-eslint/no-duplicate-enum-values",
  "@typescript-eslint/no-empty-object-type",
  "@typescript-eslint/no-extra-non-null-assertion",
  "@typescript-eslint/no-misused-new",
  "@typescript-eslint/no-namespace",
  "@typescript-eslint/no-non-null-asserted-optional-chain",
  "@typescript-eslint/no-this-alias",
  "@typescript-eslint/no-unnecessary-type-constraint",
  "@typescript-eslint/no-unsafe-declaration-merging",
  "@typescript-eslint/no-unsafe-function-type",
  "@typescript-eslint/no-wrapper-object-types",
  "@typescript-eslint/prefer-as-const",
  "@typescript-eslint/prefer-namespace-keyword",
  "@typescript-eslint/triple-slash-reference",
  "constructor-super",
  "for-direction",
  "getter-return",
  "no-async-promise-executor",
  "no-class-assign",
  "no-compare-neg-zero",
  "no-cond-assign",
  "no-const-assign",
  "no-constant-binary-expression",
  "no-constant-condition",
  "no-control-regex",
  "no-debugger",
  "no-delete-var",
  "no-dupe-args",
  "no-dupe-class-members",
  "no-dupe-else-if",
  "no-dupe-keys",
  "no-duplicate-case",
  "no-empty-character-class",
  "no-empty-pattern",
  "no-empty-static-block",
  "no-ex-assign",
  "no-extra-boolean-cast",
  "no-fallthrough",
  "no-func-assign",
  "no-global-assign",
  "no-import-assign",
  "no-invalid-regexp",
  "no-irregular-whitespace",
  "no-loss-of-precision",
  "no-misleading-character-class",
  "no-new-native-nonconstructor",
  "no-nonoctal-decimal-escape",
  "no-obj-calls",
  "no-octal",
  "no-prototype-builtins",
  "no-redeclare",
  "no-regex-spaces",
  "no-self-assign",
  "no-setter-return",
  "no-shadow-restricted-names",
  "no-sparse-arrays",
  "no-this-before-super",
  "no-unexpected-multiline",
  "no-unreachable",
  "no-unsafe-finally",
  "no-unsafe-negation",
  "no-unsafe-optional-chaining",
  "no-unused-labels",
  "no-unused-private-class-members",
  "no-useless-backreference",
  "no-useless-catch",
  "no-var",
  "no-with",
  "prefer-const",
  "prefer-rest-params",
  "prefer-spread",
  "require-yield",
  "use-isnan",
  "valid-typeof",
  "vue/block-order",
  "vue/comment-directive",
  "vue/component-definition-name-casing",
  "vue/html-end-tags",
  "vue/html-quotes",
  "vue/jsx-uses-vars",
  "vue/mustache-interpolation-spacing",
  "vue/no-arrow-functions-in-watch",
  "vue/no-async-in-computed-properties",
  "vue/no-child-content",
  "vue/no-computed-properties-in-data",
  "vue/no-deprecated-data-object-declaration",
  "vue/no-deprecated-delete-set",
  "vue/no-deprecated-destroyed-lifecycle",
  "vue/no-deprecated-dollar-listeners-api",
  "vue/no-deprecated-dollar-scopedslots-api",
  "vue/no-deprecated-events-api",
  "vue/no-deprecated-filter",
  "vue/no-deprecated-functional-template",
  "vue/no-deprecated-html-element-is",
  "vue/no-deprecated-inline-template",
  "vue/no-deprecated-model-definition",
  "vue/no-deprecated-props-default-this",
  "vue/no-deprecated-router-link-tag-prop",
  "vue/no-deprecated-scope-attribute",
  "vue/no-deprecated-slot-attribute",
  "vue/no-deprecated-slot-scope-attribute",
  "vue/no-deprecated-v-bind-sync",
  "vue/no-deprecated-v-is",
  "vue/no-deprecated-v-on-native-modifier",
  "vue/no-deprecated-v-on-number-modifiers",
  "vue/no-deprecated-vue-config-keycodes",
  "vue/no-dupe-keys",
  "vue/no-dupe-v-else-if",
  "vue/no-duplicate-attributes",
  "vue/no-export-in-script-setup",
  "vue/no-expose-after-await",
  "vue/no-lifecycle-after-await",
  "vue/no-lone-template",
  "vue/no-multi-spaces",
  "vue/no-multiple-slot-args",
  "vue/no-mutating-props",
  "vue/no-parsing-error",
  "vue/no-ref-as-operand",
  "vue/no-required-prop-with-default",
  "vue/no-reserved-component-names",
  "vue/no-reserved-keys",
  "vue/no-reserved-props",
  "vue/no-shared-component-data",
  "vue/no-side-effects-in-computed-properties",
  "vue/no-spaces-around-equal-signs-in-attribute",
  "vue/no-template-key",
  "vue/no-template-shadow",
  "vue/no-textarea-mustache",
  "vue/no-unused-components",
  "vue/no-unused-vars",
  "vue/no-use-computed-property-like-method",
  "vue/no-use-v-if-with-v-for",
  "vue/no-useless-template-attributes",
  "vue/no-v-for-template-key-on-child",
  "vue/no-v-text-v-html-on-component",
  "vue/no-watch-after-await",
  "vue/one-component-per-file",
  "vue/order-in-components",
  "vue/prefer-import-from-vue",
  "vue/prop-name-casing",
  "vue/require-component-is",
  "vue/require-default-prop",
  "vue/require-explicit-emits",
  "vue/require-prop-type-constructor",
  "vue/require-prop-types",
  "vue/require-render-return",
  "vue/require-slots-as-functions",
  "vue/require-toggle-inside-transition",
  "vue/require-v-for-key",
  "vue/require-valid-default-prop",
  "vue/return-in-computed-property",
  "vue/return-in-emits-validator",
  "vue/this-in-template",
  "vue/use-v-on-exact",
  "vue/v-bind-style",
  "vue/v-on-style",
  "vue/v-slot-style",
  "vue/valid-attribute-name",
  "vue/valid-define-emits",
  "vue/valid-define-options",
  "vue/valid-define-props",
  "vue/valid-next-tick",
  "vue/valid-template-root",
  "vue/valid-v-bind",
  "vue/valid-v-cloak",
  "vue/valid-v-else",
  "vue/valid-v-else-if",
  "vue/valid-v-for",
  "vue/valid-v-html",
  "vue/valid-v-if",
  "vue/valid-v-is",
  "vue/valid-v-memo",
  "vue/valid-v-model",
  "vue/valid-v-on",
  "vue/valid-v-once",
  "vue/valid-v-pre",
  "vue/valid-v-show",
  "vue/valid-v-slot",
  "vue/valid-v-text",
  // ---- 第 348 轮 F-2：11 条可自动修规则清零后**入列**（棘轮收紧方向）----
  "vue/attribute-hyphenation",
  "vue/attributes-order",
  "vue/first-attribute-linebreak",
  "vue/html-closing-bracket-newline",
  "vue/html-closing-bracket-spacing",
  "vue/html-indent",
  "vue/html-self-closing",
  "vue/max-attributes-per-line",
  "vue/multiline-html-element-content-newline",
  "vue/singleline-html-element-content-newline",
  "vue/v-on-event-hyphenation",
  // ---- 第 349 轮：`vue/multi-word-component-names` 移出欠账表后**入列**（棘轮收紧方向）----
  //   此前它是 'off'（一个名字都不查）；现在回到 preset 的 'error'，
  //   仅由 `ratchet/component-name-policy` 豁免 6 个既定名字。
  "vue/multi-word-component-names",
]

/** 冻结：显式关掉并登记的 9 条欠账（不得新增，只许清零后移出）
 *  ★ 第 348 轮 F-2 已把 11 条「全可自动修」的 vue 规则清零并移出本表（6285 处）。
 *  ★ 第 349 轮 `vue/multi-word-component-names` 移出（改用 config 的策略档豁免 6 个既定名字）。 */
const CEILING_DEBT = [
  "@typescript-eslint/no-explicit-any",
  "@typescript-eslint/no-require-imports",
  "@typescript-eslint/no-unused-expressions",
  "@typescript-eslint/no-unused-vars",
  "no-case-declarations",
  "no-empty",
  "no-undef",
  "no-useless-escape",
  "vue/no-v-html",
]

/** 冻结：每个代表文件类上的生效规则条数 */
const FLOOR_PER_CLASS = {
  "src/main.ts": 174,
  "src/App.vue": 189,
  "scripts/check-session-registry.cjs": 187,
  "scripts/cdp-dark-contrast.mjs": 187,
}

const errors = []
function fail(msg) { errors.push(msg) }
function report() {
  errors.forEach((e) => console.error('FAIL  [eslint-ratchet] ' + e))
  process.exitCode = 1
}

async function main() {
  // ---- R4 自检：先证明三张表都不是空的、条数对得上（防自己坏掉后恒真）
  // ★★ 这里必须 `fail(...); return report()` —— **不能写 `return fail(...)`**：
  //    那样只会往 errors 里塞一条就返回，永远走不到「打印 + 置退出码」那段
  //    ⇒ 自检静默空转、门禁恒绿。本轮反向注入 R4 就是靠这个把它抓出来的。
  if (FLOOR_ENFORCED.length !== 193) { fail(`冻结生效集合条数异常：${FLOOR_ENFORCED.length} != 193（本门禁自身被改坏了）`); return report() }
  if (CEILING_DEBT.length !== 9) { fail(`冻结欠账条数异常：${CEILING_DEBT.length} != 9（本门禁自身被改坏了）`); return report() }
  if (Object.keys(FLOOR_PER_CLASS).length !== 4) { fail(`逐类冻结表条数异常：${Object.keys(FLOOR_PER_CLASS).length} != 4（本门禁自身被改坏了）`); return report() }
  if (FLOOR_PER_CLASS[Object.keys(FLOOR_PER_CLASS)[0]] === undefined) { fail('逐类冻结表内容异常（本门禁自身被改坏了）'); return report() }

  const { ESLint } = requireFE('eslint')
  const eslint = new ESLint({ cwd: FE_ROOT })

  const sevByClass = {}
  for (const f of Object.keys(FLOOR_PER_CLASS)) {
    const cfg = await eslint.calculateConfigForFile(f)
    const m = {}
    for (const [r, v] of Object.entries(cfg.rules || {})) m[r] = Array.isArray(v) ? v[0] : v
    sevByClass[f] = m
  }
  const anyOn = (r) => Object.values(sevByClass).some((m) => (m[r] || 0) > 0)

  // ---- R1 生效集合不缩水
  const shrunk = FLOOR_ENFORCED.filter((r) => !anyOn(r))
  if (shrunk.length) {
    fail(`棘轮回退：这 ${shrunk.length} 条规则原本能拦住人，现在在所有代表文件类上都关掉了：\n` +
      shrunk.map((r) => {
        const det = Object.keys(sevByClass).map((f) => `${path.basename(f)}=${sevByClass[f][r] ?? '-'}`).join(' ')
        return `        ${r}  ->  ${det}`
      }).join('\n') +
      '\n      （棘轮只增不减：要放宽必须先说明理由，并同步更新本文件的冻结表）')
  }

  // ---- R2 逐类条数不缩水
  for (const [f, floor] of Object.entries(FLOOR_PER_CLASS)) {
    const live = Object.values(sevByClass[f]).filter((v) => v > 0).length
    if (live < floor) fail(`文件类 ${f} 的生效规则数缩水：${live} < 冻结值 ${floor}`)
  }

  // ---- R3 欠账不扩张（读 config 自己导出的那张表 = 问真源）
  const cfgMod = await import(require('url').pathToFileURL(path.join(FE_ROOT, 'eslint.config.mjs')).href)
  const liveDebt = cfgMod.LEGACY_DEBT_OFF
  if (!liveDebt) { fail('eslint.config.mjs 没有导出 LEGACY_DEBT_OFF —— 判据读不到真源，不能静默放过'); return report() }
  const added = Object.keys(liveDebt).filter((r) => !CEILING_DEBT.includes(r))
  if (added.length) {
    fail(`欠账表新增了 ${added.length} 条：${added.join(', ')}\n` +
      '      （把有违规的规则塞进欠账表就等于静默关掉它 —— 要关必须先登记理由）')
  }
  const conflict = FLOOR_ENFORCED.filter((r) => r in liveDebt)
  if (conflict.length) fail(`生效集合与欠账表出现交集：${conflict.join(', ')}（判据自相矛盾）`)

  if (errors.length) return report()
  const liveTotal = Object.values(sevByClass[Object.keys(FLOOR_PER_CLASS)[0]]).filter((v) => v > 0).length
  console.log(`OK    [eslint-ratchet] 生效集合 ${FLOOR_ENFORCED.length}/${FLOOR_ENFORCED.length} 全在位；` +
    `欠账 ${Object.keys(liveDebt).length}/${CEILING_DEBT.length} 条未扩张；逐类条数均达标（首类 ${liveTotal}）`)
  if (Object.keys(liveDebt).length === 0) {
    console.log('      ★ 欠账已清零 —— 可以把本文件的 CEILING_DEBT 改成空表，并删掉 config 里的欠账档')
  }
}

main().catch((e) => {
  console.error('FAIL  [eslint-ratchet] 执行异常：' + (e && e.stack ? e.stack : e))
  process.exitCode = 1
})
