/**
 * 新手引导 API（第 387 轮 · 网站管理员 P0-2）
 *
 * ★ 为什么单独一个文件而不是塞进 `productResearch.ts`：
 *   这个端点服务的**不止**市场洞察 —— 它按店铺灌的是 9 个库的示例数据
 *   （产品 / 素材 / 候选 / 监控 / 平台规则 / 话术 / 履约 / 市场洞察）。
 *   放进某一个业务模块的 api 文件，会让下一个人以为它只跟那个模块有关。
 */

import request from './request'

/** `POST /onboarding/sample-data` 的返回体。 */
export interface SampleDataResult {
  shop_id: string
  /**
   * ★ 恒为 true，且**必须**被界面用上。
   *   它是「这批数是示例、不是真实平台数据」的机器可读凭据。
   */
  is_sample: boolean
  /** 给用户看的一句话（已含「非真实平台数据」） */
  label: string
  /** 每个库实际新增的条数 */
  counts: Record<string, number>
  total: number
  /**
   * 全部返回 0。
   *
   * ★ 这**不是失败**：各 seed 是 `*_if_empty`，该店已有数据时不重复写。
   *   界面应显示「示例数据已存在」，而不是「加载成功」或「加载失败」。
   */
  nothing_new: boolean
}

/**
 * 给**当前选中的店铺**灌一份示例数据（幂等）。
 *
 * 店铺由请求头 `X-Shop-ID` 决定（`api/request.ts` 统一注入），
 * 归属校验在后端 `get_current_shop_id` —— 前端不做第二份判定。
 */
export function loadSampleData() {
  return request.post<{ success: boolean; data: SampleDataResult }>(
    '/onboarding/sample-data',
  )
}
