/**
 * 翻译结果判定（**唯一真源**）
 * =============================
 * 后端划词翻译的响应是一条**四态**契约，不是布尔：
 *
 *   | 后端字段组合                              | 含义                        | 界面该怎么说话            |
 *   |------------------------------------------|-----------------------------|---------------------------|
 *   | `success && !degraded && translation`    | 正常译文                    | 直接显示译文              |
 *   | `success && !degraded && same_lang`      | 原文已是目标语言（**没调模型**） | 「已是中文」+「译为英文」   |
 *   | `success && degraded`                    | LLM 不可用，译文为空        | 如实告知「暂不可用」       |
 *   | `!success` / 无 `response`               | 请求层失败                  | 如实告知「暂不可用」       |
 *
 * ★ 为什么必须抽成一处（这是本文件存在的唯一理由）：
 *   后端这条四态契约**只能有一份判定**。判定若跟着界面走，每加一个**文本**翻译入口
 *   （划词浮层，以及任何未来的内联 / 悬浮译文块）就要多写一份，必然结局是
 *   「同一份响应在不同入口显示成不同话术」—— 典型症状：一处说「已是中文」，
 *   另一处却渲染成一个空框。空框既可能是「不需要翻」也可能是「翻了但结果是空」，
 *   用户无从分辨 —— 这就是本仓反复记录的**三态压两态**。
 *
 * ★ 边界：本条只管**文本**翻译入口（划词浮层）。历史注记：第 365–366 轮曾另有一路
 *   「图片 / 截屏」翻译，它的状态机更宽（多出「这块区域没认到字」一态、降级时仍要
 *   回显原文），因此**没有**并入本模块 —— 第 367 轮该链路整套退场。
 *   ⇒ 结论不变：任何**文本**翻译新入口必须复用本模块，不许另写一份判定。
 *
 * ★ 三条不许随手改的判据（每条都有代价，改前先想清楚要付出什么）：
 *   1. **`degraded` 优先判**：后端降级时理论上译文为空；即便它回了半截译文，也不该当成正常
 *      结果展示 —— 降级就是降级，半截译文比空更危险（用户会当成完整结果用）。
 *   2. **`same_lang` 不是失败**：它是「本来就不需要翻」。压成 `error` 会让用户以为坏了；
 *      压成「空译文 + 成功」会让用户以为模型抽风。必须自成一态。
 *   3. **译文为空白（含纯空白串）⇒ 不当作 `ok`**：否则界面渲染出一个空白块，
 *      与 `degraded` 不可区分。宁可归到「暂不可用」，也不要展示一个看起来像坏了的空框。
 *      （口径对齐 `useSelectionTranslate` 改造前的既有行为：只有非空译文才算成功。）
 *
 * ★ 本模块是**纯叶子**：不 import 任何 api / vue / axios。
 *   这样消费方（划词浮层）能零成本单测它，也不会被 api 层的 mock 牵着走。
 *   输入类型是**结构式**的，与 `api/aigcMedia.ts` 的 `SelectionTranslation` 由
 *   `tests/unit/translateOutcome.test.ts` 里的编译期断言对齐（漂移即 `vue-tsc` 报红）。
 */

/** 四态。`degraded` 与 `error` 分成两个 kind：目前话术相同，但成因不同，别合并。 */
export type TranslateOutcomeKind = 'ok' | 'same_lang' | 'degraded' | 'error'

export interface TranslateOutcome {
  kind: TranslateOutcomeKind
  /** 仅 `kind === 'ok'` 时非空 */
  translation: string
  /** 仅 `ok` / `same_lang` 时非空（失败时不展示语言方向） */
  sourceLang: string
  targetLang: string
  /** 仅 `degraded` / `error` 时非空，且是**直接给用户看的话术** */
  message: string
}

/**
 * 降级 / 请求失败时的统一话术。
 *
 * ★ 所有消费方共用这一处 —— 禁各写一份（写两份就会出现「同一个后端故障，一处说
 *   『暂不可用』、一处说『翻译失败』」的口径分叉）。
 */
export const TRANSLATE_UNAVAILABLE = '翻译服务暂不可用，请稍后重试'

/**
 * 后端响应体的**结构**约束（刻意不 import `SelectionTranslation`，见文件头）。
 * 字段与 `api/aigcMedia.ts` 的 `SelectionTranslation` 一一对应。
 */
export interface TranslateResponseLike {
  original_text?: string
  translation?: string
  source_lang?: string
  target_lang?: string
  degraded?: boolean
  same_lang?: boolean
}

/** 外层信封：`success` 是 axios 响应体里的业务标志，与 `response.degraded` 是两层。 */
export interface TranslateEnvelope {
  success?: boolean
  response?: TranslateResponseLike | null
  message?: string
}

const BLANK: Omit<TranslateOutcome, 'kind'> = {
  translation: '',
  sourceLang: '',
  targetLang: '',
  message: '',
}

/**
 * 后端响应 → UI 四态。**纯函数**，不抛异常、不触碰任何全局。
 *
 * 传 `null` / `undefined` / 畸形响应一律得到 `error`（不静默当成空译文）。
 */
export function resolveTranslateOutcome(
  res: TranslateEnvelope | null | undefined,
): TranslateOutcome {
  const d = res?.response

  // ① 请求层失败 —— 连响应体都没有，无从判断
  if (!res?.success || !d) {
    return { ...BLANK, kind: 'error', message: TRANSLATE_UNAVAILABLE }
  }

  // ② 降级优先：即便回了半截译文也不能当正常结果（见文件头判据 1）
  if (d.degraded) {
    return { ...BLANK, kind: 'degraded', message: TRANSLATE_UNAVAILABLE }
  }

  const lang = { sourceLang: d.source_lang || '', targetLang: d.target_lang || '' }

  // ③ 原文已是目标语言 —— 既不是失败，也不是「空译文成功」（见文件头判据 2）
  if (d.same_lang) {
    return { ...BLANK, ...lang, kind: 'same_lang' }
  }

  // ④ 正常译文。空白串不算成功（见文件头判据 3）
  const translation = d.translation || ''
  if (!translation.trim()) {
    return { ...BLANK, kind: 'degraded', message: TRANSLATE_UNAVAILABLE }
  }

  // ★ 回带的是**未 trim 的原文**：后端可能刻意保留首尾格式，交给渲染层决定
  return { ...BLANK, ...lang, kind: 'ok', translation }
}
