/**
 * 差评工作台 —— **抽屉编辑区的状态与动作**（第 341 轮第二刀，从 `ReviewDeskConfig.vue` 外移）。
 *
 * ★ 这里放什么 / 不放什么
 * ------------------------------------------------------------------------
 * 放：抽屉里「处置通道 + 回复草稿」这一小块编辑区的**全部状态与动作** ——
 *     四个编辑用 ref、抽屉打开时把后端值回填的 watch、「能不能改」的两条判定、
 *     「有没有未保存修改」、通道点选、保存修改、把系统草稿填回编辑框。
 * 不放：
 *   · **写门禁名单里的动作**（approve / reject / issue / recordExecutionReceipt /
 *     setReviewAttribution / 补偿规则 CRUD）—— 它们必须留在面板内，否则门禁
 *     `check-disposition-write-exit.cjs` 的 C1（每个写 API 的 `.vue` 出口恰好 1 处）
 *     与 C2（写 API 在 `.ts` 层 import 数 === 0）当场转红。
 *     本模块只 import `proposeDisposition` / `draftDisposition` 这两个**不在名单**的接口。
 *   · 通道语义表 `CHANNEL_META` 与通道全集 `ALL_CHANNELS` —— 它们是本面板的
 *     **唯一真源**，被门禁 `check-disposition-execution-honesty.cjs` H8 钉在
 *     `ReviewDeskConfig.vue` 内。这里只接受**引用注入**（`deps.channelMeta` /
 *     `deps.allChannels`），**不复制第二份** —— 复制就是本仓反复踩的
 *     「同一判定两份实现」。
 *
 * ★ 为什么这些状态搬走是安全的
 *     编辑区状态只有三个消费方：模板、`adoptEscalate()`、`openDispositionDrawer()`；
 *     三者都是**运行期**才读，而 composable 在 setup 期就返回了 ⇒ 时序不变。
 *     门禁 `check-review-chat-entries.cjs` 钉的 `toDetailView(...)` 调用点、
 *     以及 `check-review-risk-view.cjs` R13/R14 钉的 `reload` / `riskListKey`，
 *     都不在本次搬运范围内。
 */
import { ref, computed, watch, type Ref } from 'vue'
import { message } from 'ant-design-vue'
import { proposeDisposition, draftDisposition, type Disposition } from '@/api/trade'

/** 通道语义的最小形状 —— 面板侧 `CHANNEL_META` 的引用注入面（只读其 `irreversible`） */
interface ChannelMetaLike {
  irreversible?: boolean
}

export interface UseReviewDeskEditsDeps {
  /** 当前抽屉里那条处置 —— 面板侧持有与写入 */
  disposition: Ref<Disposition | null>
  /**
   * 当前抽屉对应的差评。
   * ★ 只用到 `id` —— 它就是 `review_id`（三个入口的**唯一归一形状** `DetailView`）。
   */
  detailView: Ref<{ id: string } | null>
  /** 写入中的开关 —— 与面板其它动作**共用同一个**（不要各持一份） */
  acting: Ref<boolean>
  /** 面板侧的刷新 —— 保存 / 回填后要重取台账 */
  reload: () => void | Promise<void>
  /** 通道全集（顺序即展示顺序）—— 引用注入，不复制 */
  allChannels: string[]
  /** 通道语义表 —— 引用注入，不复制 */
  channelMeta: Record<string, ChannelMetaLike>
}

export function useReviewDeskEdits(deps: UseReviewDeskEditsDeps) {
  const { disposition, detailView, acting, reload, allChannels, channelMeta } = deps

  /** 当前编辑中的通道 */
  const editChannels = ref<string[]>([])
  /** 当前编辑中的回复草稿 */
  const editZh = ref('')
  const editEn = ref('')
  /** 光标停在哪个通道上（用于显示它的作用说明） */
  const channelHint = ref('')

  /** 抽屉打开 / 处置更新时，把后端值同步进编辑区 */
  watch(
    disposition,
    (d) => {
      editChannels.value = [...(d?.channels || [])]
      editZh.value = d?.reply_draft_zh || ''
      editEn.value = d?.reply_draft_en || ''
      channelHint.value = ''
    },
    { immediate: true },
  )

  /**
   * 能不能改 —— 只有 `proposed`（含被驳回后重开）可写。
   *
   * ★ 已批准 / 已核准(`issued`) / 已执行(`executed`) 一律锁定：
   *   批准过的内容被悄悄换掉，HITL 就成了形式。
   */
  const editable = computed(
    () => disposition.value?.status === 'proposed' || disposition.value?.status === 'rejected',
  )

  const lockReason = computed(() =>
    disposition.value?.status === 'issued'
      ? '已核准（券码已生成并写进回复），历史不可改（要调整只能另开一笔）'
      : disposition.value?.status === 'executed'
        ? '平台已执行 —— 终态，不可再改'
        : '已批准 —— 先驳回再改，避免批准过的内容被换掉',
  )

  /** 编辑区有未保存的修改吗 */
  const editDirty = computed(() => {
    const d = disposition.value
    if (!d) return false
    return (
      editChannels.value.join(',') !== (d.channels || []).join(',') ||
      editZh.value !== (d.reply_draft_zh || '') ||
      editEn.value !== (d.reply_draft_en || '')
    )
  })

  /** 说明行聚焦的通道（没点过就看第一个已选通道） */
  const focusChannel = computed(
    () => channelHint.value || editChannels.value[0] || allChannels[0],
  )

  /** 已选的不可逆通道 —— 必须在核准之前就看得见 */
  const irreversiblePicked = computed(() =>
    editChannels.value.filter((c) => channelMeta[c]?.irreversible),
  )

  function toggleChannel(c: string) {
    if (!editable.value) return
    channelHint.value = c
    const i = editChannels.value.indexOf(c)
    if (i >= 0) editChannels.value.splice(i, 1)
    else editChannels.value.push(c)
  }

  /**
   * 保存修改 —— 只提交**通道 + 回复措辞**，**故意不提交 `compensation`**。
   *
   * ★ 为什么不能传金额：后端 `propose_disposition` 在 `compensation` 为 `None` 时
   *   会用 `build_disposition_draft` 按**补偿规则**重算一遍 ⇒ 金额永远由规则唯一
   *   决定。前端若能直接塞金额，就直接绕过了预算上限 —— `CompensationOverBudget`
   *   只在规则那条路上拦得住，而这里正是它拦不住的那个入口。
   */
  async function saveEdits() {
    const reviewId = detailView.value?.id
    if (!reviewId) return
    if (!editChannels.value.length) {
      message.warning('至少要留一个处置通道')
      return
    }
    acting.value = true
    try {
      disposition.value = await proposeDisposition({
        review_id: reviewId,
        channels: [...editChannels.value],
        reply_draft_zh: editZh.value,
        reply_draft_en: editEn.value,
      })
      message.success('已保存（仍是待批准，不影响已批准 / 已核准 / 已执行的历史）')
      void reload()
    } catch (e: any) {
      // ★ 每个失败都要看到原因（例如「已批准的行不许被草稿覆盖」）
      message.error(e?.response?.data?.detail || e?.message || '保存失败')
    } finally {
      acting.value = false
    }
  }

  /** 把回复草稿填回系统现算的那一版（`/draft` 不落库，只用来回填编辑框） */
  async function restoreSystemDraft() {
    const reviewId = detailView.value?.id
    if (!reviewId) return
    acting.value = true
    try {
      const d = await draftDisposition(reviewId)
      if (!d.ready) {
        // ★ 同上：原因一律用后端给的；没有就说「没给」，不补一句像是原因的话
        message.warning(d.reason || '系统给不出草稿，且后端没返回原因 —— 不猜，请先看这条差评有没有归因')
        return
      }
      if (d.channels) editChannels.value = [...d.channels]
      editZh.value = d.reply_draft_zh || ''
      editEn.value = d.reply_draft_en || ''
      message.info('已填入系统草稿，确认后再点「保存修改」')
    } catch (e: any) {
      message.error(e?.response?.data?.detail || e?.message || '读取系统草稿失败')
    } finally {
      acting.value = false
    }
  }

  return {
    // 编辑区状态（模板通过 v-model / @click 双向使用）
    editChannels, editZh, editEn, channelHint,
    // 派生（只读）
    editable, lockReason, editDirty, focusChannel, irreversiblePicked,
    // 动作
    toggleChannel, saveEdits, restoreSystemDraft,
  }
}
