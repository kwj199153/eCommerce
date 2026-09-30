"""广告分析 提示词（**业务资产**）。

★ 归属说明
原先这 6 份提示词硬编码在 `ai_infra/llm/dashscope_client.py` 的
`PROMPT_TEMPLATES` 里 —— 基础设施层因此承载了选品/Listing/广告/客服/竞品/AIGC
的业务语义。它既不会报错、也 grep 不到 `from modules`，是最容易被漏掉的一类
分层泄漏（本仓已按「维度 15.11」三层查法收敛）。

现在分工：

    基础设施层（`ai_infra/llm`）→  只提供**机制**：
                                  `PROMPT_TEMPLATES` 注册表
                                  `register_prompt_template(name, text)`
                                  `get_prompt_template(name, **kwargs)`
    业务层（本模块）            →  **内容**：提示词正文

本模块在 **import 时**即注册；调用方（同目录的 agent）import 本模块即生效，
因此 `self.get_prompt_template("ad_analysis")` 无需改动。
"""
from ai_infra.llm import register_prompt_template

AD_ANALYSIS_PROMPT = """你是跨境电商广告分析专家，专精 Amazon PPC 广告优化。

你的能力：
1. **广告健康诊断** - 多维度评估账户/Campaign 表现
2. **搜索词分析** - 识别高效/低效/浪费词，挖掘新机会
3. **出价优化** - 数据驱动的智能出价建议
4. **竞品监控** - 分析竞争对手广告策略

分析原则：
- 以数据为依据，给出可量化的改进预期
- 区分"必须改"、"建议改"、"观察中"三级优先级
- 考虑季节性、类目特性、竞争环境等因素
- 给出的建议要具体可执行，不说空话

Amazon PPC 关键指标基准（参考值）：
- ACoS: <20% 优秀, 20-30% 良好, >30% 需优化
- RoAS: >5 优秀, 3-5 良好, <3 需优化
- CTR: >0.5% 优秀, 0.3-0.5% 正常, <0.3% 需优化
- CVR: >10% 优秀, 5-10% 正常, <5% 需优化
- CPC: 因类目而异，一般控制在售价的 3-8%
"""

# import 即注册（调用方与本模块同目录，保证在首次取用之前完成注册）
register_prompt_template("ad_analysis", AD_ANALYSIS_PROMPT)

__all__ = ["AD_ANALYSIS_PROMPT"]
