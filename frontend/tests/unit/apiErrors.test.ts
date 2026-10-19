/**
 * `api/errors.ts` 行为契约（第 386 轮 · 按店取数 P0-3）
 * ============================================================================
 * 为什么这一批需要一个前端单测
 * ----------------------------------------------------------------------------
 * 第 386 轮后端把两类**业务状态**改成了结构化 detail：
 *
 *   409 `{code: "STORE_NOT_CONNECTED",    store_id, reason, message}`
 *   422 `{code: "UNSUPPORTED_MARKETPLACE", store_id, message}`
 *
 * 前端原先有 **19 处** `e?.response?.data?.detail || '兜底文案'`。字符串 detail
 * 时代这是对的；对象 detail 之下它会出两个**都不会报错**的故障：
 *
 *   ① 把对象塞进 `ref<string>` / toast ⇒ 界面渲染 `[object Object]`
 *      （看起来像前端崩了，比"没提示"更糟）；
 *   ② 把「未授权」显示成「加载失败，请重试」⇒ 用户被按在一个永远点不好的
 *      按钮上，而正确操作是去授权。
 *
 * 这两条都不抛异常、不报错、不改状态码 —— 只有断言能钉住。所以这里钉两件事：
 *
 *   · **归一化**：任何 detail 形态进去，出来的必须是**非空人话**，绝不 `[object Object]`；
 *   · **识别**：409 里只有 `STORE_NOT_CONNECTED` 才算「未授权」——
 *     同一个 409 还承载 `INVOICE_NOT_REFUNDABLE`（账单退款），认错了会把
 *     运营点退款的失败说成「请去授权店铺」（归因指向完全错的地方）。
 *
 * ★ 本文件只测**前端自己的行为**，不重抄后端契约（那是 check-* 门禁的活）。
 */
import { describe, it, expect } from 'vitest'
import {
  detailText,
  errorText,
  storeNotConnectedInfo,
  unsupportedMarketplaceInfo,
} from '@/api/errors'

/** 造一个 axios 风格的 rejection（只保留本模块读到的两个字段） */
function httpError(status: number, detail: unknown) {
  return { response: { status, data: { detail } }, message: `Request failed with status code ${status}` }
}

const NC_DETAIL = {
  code: 'STORE_NOT_CONNECTED',
  store_id: 'store_abc',
  reason: 'no_credentials',
  message: '该店铺尚未完成 Amazon 授权',
}

describe('detailText —— 结构化 detail 归一（禁 [object Object]）', () => {
  it('字符串 detail 原样返回', () => {
    expect(detailText('店铺未选中', '兜底')).toBe('店铺未选中')
  })

  it('对象 detail 取 message', () => {
    expect(detailText(NC_DETAIL, '兜底')).toBe('该店铺尚未完成 Amazon 授权')
  })

  it('对象里没有 message ⇒ 用兜底，**不**退化成 String(detail)', () => {
    // ★ 这条是病根本身：改造前的写法 `detail || '兜底'` 传对象会渲染成
    //   `[object Object]`。这里要求"宁可说兜底，也不说一句看不懂的话"。
    const out = detailText({ code: 'WHATEVER' }, '操作失败，请稍后重试')
    expect(out).toBe('操作失败，请稍后重试')
    expect(out).not.toContain('[object')
  })

  it('空白字符串 / null / undefined / 数组 一律走兜底', () => {
    for (const v of ['', '   ', null, undefined, [], 0, false]) {
      expect(detailText(v, '兜底')).toBe('兜底')
    }
  })

  it('任何形态都不得产出 [object Object]（穷举本模块接受的输入面）', () => {
    const samples: unknown[] = [
      null, undefined, '', '文字', 0, false, [], {}, { code: 'X' },
      NC_DETAIL, { message: '' }, { message: '   ' }, { message: 123 },
    ]
    for (const s of samples) {
      expect(detailText(s, '兜底')).not.toContain('[object Object]')
    }
  })
})

describe('errorText —— 从错误对象取该给用户看的那句话', () => {
  it('优先用 detail（对象取 message）', () => {
    expect(errorText(httpError(409, NC_DETAIL), '兜底')).toBe('该店铺尚未完成 Amazon 授权')
  })

  it('没有 detail ⇒ 用兜底，**不**把 axios 的开发者语言铺到界面', () => {
    const err = { response: { status: 500, data: {} }, message: 'Request failed with status code 500' }
    expect(errorText(err, '复盘数据加载失败，请稍后重试')).toBe('复盘数据加载失败，请稍后重试')
  })

  it('不是 axios 错误（比如代码里 throw 的 Error）也不炸', () => {
    expect(errorText(new Error('boom'), '兜底')).toBe('兜底')
    expect(errorText(null, '兜底')).toBe('兜底')
  })
})

describe('storeNotConnectedInfo —— 只认 409 且 code=STORE_NOT_CONNECTED', () => {
  it('命中：返回可上屏的说明与原因', () => {
    const info = storeNotConnectedInfo(httpError(409, NC_DETAIL))
    expect(info).not.toBeNull()
    expect(info!.storeId).toBe('store_abc')
    expect(info!.reason).toBe('no_credentials')
    expect(info!.message).toBe('该店铺尚未完成 Amazon 授权')
  })

  it('★ 同一个 409 的另一种 code（账单退款）**不得**被认成未授权', () => {
    // 认错的后果：运营点退款失败时看到「请去授权店铺」—— 归因指向完全错的地方。
    const info = storeNotConnectedInfo(
      httpError(409, { code: 'INVOICE_NOT_REFUNDABLE', message: '该发票已退款，不可重复操作' }),
    )
    expect(info).toBeNull()
  })

  it('状态码不是 409 ⇒ null（哪怕 body 里恰好带着这个 code）', () => {
    expect(storeNotConnectedInfo(httpError(500, NC_DETAIL))).toBeNull()
    expect(storeNotConnectedInfo(httpError(200, NC_DETAIL))).toBeNull()
  })

  it('老形态（detail 是字符串）⇒ null，不误判', () => {
    expect(storeNotConnectedInfo(httpError(409, '该店铺尚未完成平台授权'))).toBeNull()
  })

  it('缺字段时给安全默认，不产出 undefined', () => {
    const info = storeNotConnectedInfo(httpError(409, { code: 'STORE_NOT_CONNECTED' }))
    expect(info).not.toBeNull()
    expect(info!.storeId).toBe('')
    expect(info!.reason).toBe('not_connected')
    expect(info!.message).toBe('该店铺尚未完成平台授权')
  })
})

describe('unsupportedMarketplaceInfo —— 422 与 409 必须分开', () => {
  it('命中 422 + UNSUPPORTED_MARKETPLACE', () => {
    const info = unsupportedMarketplaceInfo(
      httpError(422, { code: 'UNSUPPORTED_MARKETPLACE', store_id: 'store_sg', message: '站点 SG 不在支持列表内' }),
    )
    expect(info).not.toBeNull()
    expect(info!.storeId).toBe('store_sg')
    expect(info!.message).toContain('SG')
  })

  it('★ 未授权（409）不得被认成站点不支持 —— 两者的出口不同', () => {
    // 未授权 ⇒ 去授权；站点不支持 ⇒ 联系我们。指错了用户会白折腾一轮。
    expect(unsupportedMarketplaceInfo(httpError(409, NC_DETAIL))).toBeNull()
    expect(storeNotConnectedInfo(
      httpError(422, { code: 'UNSUPPORTED_MARKETPLACE', store_id: 'x', message: 'y' }),
    )).toBeNull()
  })
})
