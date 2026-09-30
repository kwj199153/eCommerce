/**
 * 对话编排层 · 工具结果后处理（第 169 轮 #664）
 *
 * 工具执行完之后、把结果塞进对话流之前的三件「顺手事」：
 *   ① `resolveProfitResult` —— 利润测算与右栏面板**同源**（面板算过就直接沿用，绝不前端复算）
 *   ② `saveScriptToStore`  —— 带货脚本落共享 store，供「AI 短视频生成」复用
 *   ③ `syncListingDraft`   —— Listing 各工具结果写进「Listing 工作区」草稿
 *
 * ★ 这三个是普通函数而不是 composable：它们只依赖 Pinia store（进程内单例），
 *   在函数体里现取即可。原来的写法是从编排器的闭包里抓 `shopStore` / `productLibraryStore`，
 *   拆出来后改成函数内取 store —— **同一份单例，语义不变**，但不再需要把 store 一路透传。
 *
 * ★ 全部包在 try/catch 里且失败只 `console.warn`：这些是**增强**而非主链路，
 *   后处理失败不能让用户拿不到已经生成好的结果。
 */
import { useShopStore } from '@/stores/shop'
import { useProductLibraryStore } from '@/stores/productLibrary'
import { useListingDraftStore } from '@/stores/listingDraft'

  /**
   * 利润测算结果：以后端 /stores/profit/calculate 为唯一计算源。
   * 面板带过来的 _preview 就是后端响应，直接沿用；没有（从对话侧触发）才自己调一次。
   */
export const resolveProfitResult = async (params: any) => {
    const { calculateProfit, toProfitRequest } = await import('@/api/stores')
    if (params?._preview) return params._preview
    const shopId = useShopStore().currentShopId
    if (!shopId) throw new Error('未选择店铺，无法获取费率模板')
    return await calculateProfit(toProfitRequest(params), shopId)
  }

  // 将最近生成的脚本写入共享 store，供 AI 短视频生成「分镜脚本专业模式」导入
export const saveScriptToStore = async (result: any) => {
    try {
      const { useVideoScriptsStore } = await import('@/stores/videoScripts')
      useVideoScriptsStore().saveLastScript(result)
    } catch (e) {
      console.warn('写入 lastVideoScript 失败：', e)
    }
  }

  /**
   * 把 Listing 工具的执行结果同步到「Listing 工作区」草稿，
   * 让右侧面板与对话结果保持一致（对话里生成 → 面板里继续编辑/保存）
   */
export const syncListingDraft = (toolId: string, params: any, result: any) => {
    try {
      const draft = useListingDraftStore()
      // 有产品来源时，先用产品预填一次，保证面板上下文正确
      if (params?.product_id && !draft.productId) {
        const p = useProductLibraryStore().items.find((i: any) => i.id === params.product_id)
        if (p) draft.loadFromProduct(p)
      }
      if (!draft.productName && params?.product_name) draft.productName = params.product_name
      if (!draft.brand && params?.brand) draft.brand = params.brand

      switch (toolId) {
        case 'keyword-miner':
          if (Array.isArray(result?.keywords)) draft.setKeywords(result.keywords)
          break
        case 'title-gen':
          if (result?.recommended_title) {
            draft.setTitle(result.recommended_title, (result.variants || []).map((v: any) => v.title || v))
          }
          break
        case 'bullet-gen':
          if (Array.isArray(result?.bullets)) {
            draft.setBullets(result.bullets.map((b: any) => ({ title: b.title || '', content: b.content || b.point || '' })))
          }
          break
        case 'desc-gen':
          if (result?.description) draft.setAPlus(draft.aplusModules.length ? draft.aplusModules : normalizeDescToModules(result.description))
          break
        case 'seo-audit':
          if (Array.isArray(result?.dimensions) || Array.isArray(result?.checks)) {
            draft.setSeo(result.checks || result.dimensions, result.overall_score)
          }
          break
      }
    } catch (e) {
      console.warn('同步 Listing 草稿失败：', e)
    }
  }

  /** desc-gen 的 description（含 sections）→ A+ 模块结构 */
  const normalizeDescToModules = (desc: any): any[] => {
    if (Array.isArray(desc?.modules)) return desc.modules
    if (Array.isArray(desc?.sections)) {
      return desc.sections.map((s: any) => ({ type: 'text', heading: s.heading || '', content: s.content || '' }))
    }
    return []
  }
