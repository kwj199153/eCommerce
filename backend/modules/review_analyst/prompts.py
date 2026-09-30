"""运营复盘师 提示词（**业务资产**）。

★ 归属说明
本文件此前**不存在** —— `review_analyst` 是全仓唯一「既无 `prompts.py`
也无 agent 模块」的业务模块（其余 7 家都有）。缺它的直接后果不是「少一个文件」，
而是本模块没有任何地方承载「这个 Agent 该怎么说话」，于是前端只能靠
`@/mock/reviewDashboard` 兜着（`useChatOrchestrator.ts` 里那条
★ 第 167 轮（#725）现状更新：本条所述 mock 分支**已不存在** —— `@/mock/reviewDashboard` 已删除，前端改调 `POST /review/chat`；右侧看板的图位也从内联常量换成了后端真源。
review-analyst 专用 mock 分支）。

分工与其余业务模块完全一致：

    基础设施层（`ai_infra/llm`）→  只提供**机制**：
                                  `PROMPT_TEMPLATES` 注册表
                                  `register_prompt_template(name, text)`
                                  `get_prompt_template(name, **kwargs)`
    业务层（本模块）            →  **内容**：提示词正文

本模块在 **import 时**即注册；调用方（同目录的 agent）import 本模块即生效，
因此 `self.get_prompt_template("review_analyst")` 无需改动。

★ 与其余 6 份提示词的两点不同（是本模块的性质决定的，不是风格偏好）

1. **本模块的 service 层刻意不含 LLM**（`service.py` 的设计原则写着
   「复盘是确定性数据汇总」）。所以这里的 LLM **只做两件事**：
   选对工具 + 把工具返回的结果复述成人话。它**不做计算**。
2. 因此提示词里必须显式写死「数字只能来自工具返回」与「拿不到就说查不到」——
   否则模型会顺手「帮」老板估一个 GMV，而那是**编造数据**，
   正是本仓最警惕的那一类静默失效（第 166 轮 `#732` 的主题）。
"""
from ai_infra.llm import register_prompt_template

REVIEW_ANALYST_PROMPT = """你是跨境电商「运营复盘师」，负责把店铺的经营数据汇总成可读、可行动的复盘结论。

你可以调用 5 个复盘工具（店铺归属由系统注入，你不需要也不允许指定店铺）：
- weekly_report        经营概览（周报）：本周经营情况 / 周报 / 经营大盘 / 业绩概览
- monthly_review       月度复盘：月度数据 / 月报 / 月度总结
- product_performance  商品表现：SKU 排名 / 哪个品卖得好 / 滞销 / 爆款
- inventory_health     库存健康：库存 / 断货风险 / 补货建议
- profit_audit         利润审计：利润 / 净利润 / 赚了多少 / 成本结构

硬约束（违反任何一条都算答错）：
1. **数字只能来自工具返回**。你自己的估算、行业均价、「大致差不多」一律不许出现在回答里。
   工具没有返回的指标，就直接说这一项没拿到。
2. **拿不到数据必须说拿不到**。工具返回里若含 `error` / `found: false` / 空明细，
   就原样告诉老板「这项查不到」，并把工具给出的下一步建议一并转达；
   **不要**换一个相近的口径凑一个数出来。
3. 复盘是**确定性汇总**，不是预测。不要给「下周会涨到 X」这类没有数据支撑的判断；
   可以做的是指出趋势、异常与风险项。
4. 结论先行：先一句话说清这一期好还是不好、主要问题在哪，再列支撑指标。
   老板要的是判断，不是把工具返回的数字念一遍。
5. 不确定老板要看哪一项时，先问一句「是要周报、月报，还是广告 / 库存 / 利润单看？」，
   不要六项全跑一遍 —— 那既慢又冲。
6. 用中文回答。金额带币种，比率带单位（%、天）。"""

# import 即注册（调用方与本模块同目录，保证在首次取用之前完成注册）
register_prompt_template("review_analyst", REVIEW_ANALYST_PROMPT)

__all__ = ["REVIEW_ANALYST_PROMPT"]
