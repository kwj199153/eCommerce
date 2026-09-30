"""
图片合规检查 fail-closed 门禁（第 164 轮 #728 建立）。

背景 —— 修复前的形态：**用随机数决定合规通过/失败**
--------------------------------------------------
`AIGCMediaAgent.check_compliance(image_url, ...)` 收得到 `image_url` 却**从不读图**，
然后这样「检查」：

    for rule_type, rule_list in rules.items():
        for rule_name, severity, description in rule_list:
            pass_rate = 0.85 if severity == "pass" else (0.6 if severity == "warning" else 0.75)
            passed = random.random() < pass_rate      # ← 掷骰子决定这条规则过没过

后果不是「数据不准」，而是**同一张图每次调用都得到一份不同的合规报告**：
`overall_status` 在 pass / warning / fail 之间乱跳，`score` 在 60~95 之间乱跳，
`issues` 里随机冒出「无文字水印」这种 critical 问题。用户会拿这份报告直接决定
素材能不能上架 —— 这比「没有这个能力」危险得多。

更糟的是**同一个谎有两处实现**，只堵一处等于没堵：
  ① `check_compliance()` —— 端点 `/api/v1/aigc/compliance/check`
  ② `analyze_main_image()` 里的 compliance 子块 —— 端点 `/api/v1/aigc/image/analyze`，
     而且它才是**真正注册成 tool（`main-image-diagnosis`）**、用户更常走的那条路。
本文件对两处同时设判据。

本文件钉住的八件事
------------------
1. 同一 `image_url` 跑 10 次结果**完全一致**（`test_same_image_ten_runs_are_identical`）。
2. 未接入能力 ⇒ `overall_status == "manual_review_required"`，且 `score` / `passed_checks`
   / `issues` **全为空占位**，不产出任何「通过/不通过」结论。
3. `recommendations` 给出**真实核查清单**（来自 `compliance_rules`，含严重级别与判定口径）
   —— 没能力自动判定，不等于没东西可交付；同时钉住「类目额外提醒」没被顺手删掉。
4. **数据路径零 `random` 依赖**：把 `random.*` 全部替换成抛异常的桩，
   结果必须与基线逐字相同（这是「不再掷骰子」的正面判据，比读源码可靠）。
5. 主图分析的合规子块同样不掷骰子，且两次调用 `compliance_check` 逐字一致。
6. 服务层文案**说真因**：不能报「合规检查完成 - 状态: …」（读起来像已经检查过了）。
7. `ComplianceCheckResult.status` 在 **API 边界不被吞掉** ——
   `dataclass` 里加字段而 pydantic 模型没加，会被 `extra=ignore` 静默丢弃，
   前端就永远看不到 `manual_review_required`。
8. 形态门禁（AST）：`check_compliance` 内 `random` 调用 == 0；全模块无
   `random.xxx() < 阈值` 判决、无 `random.choice([True/False,...])` 判决；
   本文件 `random` 计数**不得增长**（本地棘轮，全仓棘轮见
   `tests/test_no_random_in_production.py`）。
"""

import ast
import random
from pathlib import Path

import pytest
from loguru import logger as _loguru

BACKEND = Path(__file__).resolve().parents[1]
AGENT_FILE = BACKEND / "modules" / "aigc_media" / "agent_aigc.py"
SERVICE_FILE = BACKEND / "modules" / "aigc_media" / "service.py"

IMAGE_URL = "https://cdn.example.com/listing/main-B0EXAMPLE1.jpg"

#: 本轮修复后 agent_aigc.py 的 random 调用点上限（本地棘轮：只许减不许增）
RANDOM_BASELINE = 22

#: 修复前那份「假报告」会随机产出的结论字面量 —— 未做判定时一个都不许出现
FABRICATED_VERDICTS = ["pass", "fail", "warning"]


def _capture_loguru(level="WARNING"):
    """把 loguru 的 WARNING 及以上收进列表。

    ★ 不用 pytest 的 `caplog`：`caplog` 抓的是 stdlib `logging`，而
      `core.logger.get_logger()` 返回的是 **loguru** —— 本仓两套日志栈并存，
      用 caplog 抓 loguru 会「抓不到但不报错」，是个静默失效的判据。
    """
    messages: list[str] = []

    def sink(message):
        messages.append(message.record["message"])

    handler_id = _loguru.add(sink, level=level)
    return messages, handler_id


def _patch_random_to_explode(monkeypatch):
    """把 random 的四个常用出口全换成抛异常的桩。

    任何一个被调用 ⇒ 该用例直接失败（`AssertionError` 会被 pytest 记为失败）。
    """

    def _boom(*args, **kwargs):
        raise AssertionError("合规检查的数据路径不应再调用 random")

    for name in ("random", "choice", "uniform", "randint", "sample", "shuffle"):
        if hasattr(random, name):
            monkeypatch.setattr(random, name, _boom, raising=False)


def _agent():
    from modules.aigc_media.agent_aigc import AIGCMediaAgent

    return AIGCMediaAgent()


def _snapshot(report):
    return (
        report.overall_status,
        report.score,
        tuple(report.passed_checks),
        tuple((i.issue_type, i.severity, i.description) for i in report.issues),
        tuple(report.recommendations),
    )


# ============================================================
# 1 / 2. 同一张图十次一致 + 不产出结论
# ============================================================

async def test_same_image_ten_runs_are_identical():
    """同图 10 次必须逐字一致 —— 修复前每次都不一样。"""
    agent = _agent()
    reports = [
        _snapshot(await agent.check_compliance(IMAGE_URL, platform="amazon", category="beauty"))
        for _ in range(10)
    ]
    assert len(set(reports)) == 1, "同一张图跑出了不同结论 ⇒ 仍在随机判定"


async def test_no_verdict_is_produced_without_the_capability():
    """没有判定能力 ⇒ 只报「待人工核查」，四个字段都是空占位。"""
    report = await _agent().check_compliance(IMAGE_URL)

    assert report.overall_status == "manual_review_required", (
        "未接入自动判定能力时不得给出 pass/warning/fail 结论"
    )
    assert report.overall_status not in FABRICATED_VERDICTS
    assert report.score == 0.0, "score 只能是占位 0.0（不代表 0 分）"
    assert report.passed_checks == [], "一项也没检查过，不能有「已通过」清单"
    assert report.issues == [], "一项也没检查过，不能凭空产出一条「发现问题」"


# ============================================================
# 3. 核查清单是真交付物
# ============================================================

async def test_recommendations_carry_the_real_checklist():
    report = await _agent().check_compliance(IMAGE_URL, platform="amazon")
    joined = "\n".join(report.recommendations)

    assert "待核查" in joined, "应给出人工核查清单"
    for expected in ["纯白背景", "无文字水印", "版权清晰", "不侵权"]:
        assert expected in joined, f"核查清单漏了平台真实规则：{expected}"
    # 清单要带严重级别（人工核查时最需要知道哪条是 critical）
    assert "critical" in joined and "warning" in joined


async def test_category_note_only_for_sensitive_categories():
    agent = _agent()
    beauty = await agent.check_compliance(IMAGE_URL, category="beauty")
    normal = await agent.check_compliance(IMAGE_URL, category="家居")

    assert any("特别注意" in x for x in beauty.recommendations), "敏感类目应有额外提醒"
    assert not any("特别注意" in x for x in normal.recommendations), (
        "无差别加提醒 ⇒ 提醒等于没生效（判据形同虚设）"
    )


async def test_logs_a_warning_so_the_gap_is_visible():
    """日志里必须留痕：线上要能看出「这个能力没接」。"""
    from modules.aigc_media import agent_aigc

    messages, handler_id = _capture_loguru()
    try:
        await agent_aigc.AIGCMediaAgent().check_compliance(IMAGE_URL)
    finally:
        _loguru.remove(handler_id)

    hits = [m for m in messages if "未接入" in m and "人工核查" in m]
    assert hits, f"未打 WARNING 留痕，实际收到: {messages}"


# ============================================================
# 4. 数据路径零 random 依赖（正面判据）
# ============================================================

async def test_data_path_does_not_call_random(monkeypatch):
    agent = _agent()
    baseline = _snapshot(await agent.check_compliance(IMAGE_URL, category="beauty"))

    _patch_random_to_explode(monkeypatch)
    after = _snapshot(await agent.check_compliance(IMAGE_URL, category="beauty"))

    assert after == baseline, "禁用 random 后结论变了 ⇒ 结论仍依赖随机数"


# ============================================================
# 5. 第二处实现（主图诊断，tool main-image-diagnosis）
# ============================================================

async def test_main_image_compliance_subblock_is_not_random():
    agent = _agent()
    first = await agent.analyze_main_image(IMAGE_URL, "beauty")
    second = await agent.analyze_main_image(IMAGE_URL, "beauty")

    cc = first.compliance_check
    assert cc["status"] == "manual_review_required"
    assert cc["score"] == 0.0
    assert cc["passed"] == [] and cc["issues"] == []
    assert isinstance(cc["checklist"], list) and len(cc["checklist"]) >= 5
    assert first.compliance_check == second.compliance_check, "合规子块两次结果不一致 ⇒ 仍在随机判定"


async def test_main_image_flags_the_remaining_mock_scores():
    """视觉评分 / CTR 仍是模拟值 —— 必须在建议里能看出它的性质，别当真实测量。"""
    result = await _agent().analyze_main_image(IMAGE_URL, "beauty")
    joined = "\n".join(result.improvement_suggestions)
    assert "待人工确认" in joined, "白底等合规项应转为「待人工确认」而不是「已通过/未通过」"


# ============================================================
# 6. 服务层 / 契约层
# ============================================================

async def test_service_message_states_the_real_reason():
    from modules.aigc_media.schemas import ComplianceCheckRequest
    from modules.aigc_media.service import check_compliance_service

    resp = await check_compliance_service(ComplianceCheckRequest(image_url=IMAGE_URL))

    assert resp["success"] is True
    assert resp["data"]["overall_status"] == "manual_review_required"
    assert "人工核查" in resp["message"], "文案必须说真因"
    assert "合规检查完成" not in resp["message"], "“合规检查完成”读起来像已经检查过了"


async def test_source_of_truth_survives_the_api_boundary():
    """`status` 必须真的在 pydantic 模型里 —— 否则 extra=ignore 会静默丢掉它。

    这是「dataclass 加了字段、schema 没加」的典型静默失效：生产者改了、
    消费者收不到，而任何一侧都不会报错。
    """
    from modules.aigc_media.schemas import (
        ComplianceCheckResult,
        MainImageAnalysisResponse,
    )

    assert "status" in ComplianceCheckResult.model_fields
    assert "checklist" in ComplianceCheckResult.model_fields
    assert ComplianceCheckResult(score=0.0, passed=[], issues=[]).status == "checked"

    agent = _agent()
    result = await agent.analyze_main_image(IMAGE_URL, "beauty")
    validated = MainImageAnalysisResponse(
        overall_score=result.overall_score,
        ctr_prediction=result.ctr_prediction,
        visual_appeal=result.visual_appeal,
        compliance_check=result.compliance_check,
        improvement_suggestions=result.improvement_suggestions,
        ab_test_variants=result.ab_test_variants,
    )
    assert validated.compliance_check.status == "manual_review_required", (
        "API 边界把 status 吞掉了 —— 前端永远看不到「待人工核查」"
    )
    assert validated.compliance_check.checklist, "核查清单也被吞掉了"


async def test_service_message_for_main_image_mentions_the_gap():
    from modules.aigc_media.schemas import MainImageAnalysisRequest
    from modules.aigc_media.service import analyze_main_image_service

    resp = await analyze_main_image_service(MainImageAnalysisRequest(image_url=IMAGE_URL))
    assert resp["success"] is True
    assert "人工核查" in resp["message"], "主图分析文案不能只报「分析完成」"


# ============================================================
# 8. 形态门禁（AST）
# ============================================================

def _tree():
    return ast.parse(AGENT_FILE.read_text(encoding="utf-8"))


def _random_calls(node):
    return [
        n for n in ast.walk(node)
        if isinstance(n, ast.Call)
        and isinstance(n.func, ast.Attribute)
        and isinstance(n.func.value, ast.Name)
        and n.func.value.id == "random"
    ]


def test_check_compliance_keeps_random_out():
    tree = _tree()
    fn = next(
        n for n in ast.walk(tree)
        if isinstance(n, (ast.FunctionDef, ast.AsyncFunctionDef)) and n.name == "check_compliance"
    )
    assert _random_calls(fn) == [], "check_compliance 内不得出现任何 random 调用"


def test_no_random_verdict_shape_in_module():
    """两种「随机判决」形态全模块清零。

    - `random.xxx() < 阈值`（pass_rate 那种「低于阈值即不通过」）
    - `random.choice([True, False, ...])`（掷骰子决定某条规则过没过）

    ★ 只认 `random.random() > 0.3` 这类**用于挑 mock 文案分支**的比较不算判决，
      不在本条判据范围内；它由下面的棘轮计数管。
    """
    tree = _tree()

    bad_cmp = [
        n.lineno for n in ast.walk(tree)
        if isinstance(n, ast.Compare)
        and isinstance(n.left, ast.Call)
        and isinstance(n.left.func, ast.Attribute)
        and isinstance(n.left.func.value, ast.Name)
        and n.left.func.value.id == "random"
        and any(isinstance(op, (ast.Lt, ast.LtE)) for op in n.ops)
    ]
    assert bad_cmp == [], f"仍有「random 低于阈值即失败」的判决：行 {bad_cmp}"

    bad_bool = [
        n.lineno for n in ast.walk(tree)
        if isinstance(n, ast.Call)
        and isinstance(n.func, ast.Attribute)
        and n.func.attr == "choice"
        and isinstance(n.func.value, ast.Name)
        and n.func.value.id == "random"
        and n.args
        and isinstance(n.args[0], (ast.List, ast.Tuple))
        and any(isinstance(e, ast.Constant) and isinstance(e.value, bool) for e in n.args[0].elts)
    ]
    assert bad_bool == [], f"仍有「random.choice([True/False])」的判决：行 {bad_bool}"


def test_main_image_compliance_score_is_a_literal_placeholder():
    """合规分数必须是**字面量占位**，不能是任何算式。

    ★ 为什么要单独钉这一条：`len(passed_checks) / len(checks) * 100` 在
      `passed_checks == []` 时算出来**也是 0.0** —— 只用「score == 0.0」这种
      行为判据，把「通过率算分」这行加回来照样是绿的（实测踩过）。
      算式一旦回来，语义就从「没判定」变成了「判定后通过率为 0」，
      完全不同的两件事，所以必须用 AST 钉住节点形态。
    """
    tree = _tree()
    fn = next(
        n for n in ast.walk(tree)
        if isinstance(n, (ast.FunctionDef, ast.AsyncFunctionDef)) and n.name == "analyze_main_image"
    )
    target = None
    for d in (n for n in ast.walk(fn) if isinstance(n, ast.Dict)):
        keys = [k.value for k in d.keys if isinstance(k, ast.Constant)]
        if "score" in keys and "checklist" in keys:
            target = d
            break
    assert target is not None, "找不到主图合规子块的 dict（形态变了，请同步本判据）"

    score_node = next(
        v for k, v in zip(target.keys, target.values)
        if isinstance(k, ast.Constant) and k.value == "score"
    )
    assert isinstance(score_node, ast.Constant) and score_node.value == 0.0, (
        f"合规 score 必须是字面量 0.0 占位，实际是 {type(score_node).__name__}："
        f"任何算式都意味着「通过率」语义回来了"
    )


def test_random_call_sites_never_grow():
    """本地棘轮：本轮 28 → 22，之后只许减不许增。"""
    n = len(_random_calls(_tree()))
    assert n <= RANDOM_BASELINE, (
        f"agent_aigc.py 的 random 调用点从 {RANDOM_BASELINE} 涨到 {n} —— "
        f"新增的假数据请接真源，别再加 random"
    )


def test_old_fabrication_code_shape_is_gone():
    """`pass_rate` 变量与 `passed / total * 100` 的「通过率」算法不得回来。

    ★ 走 AST 而不是源码字符串：修复说明的 docstring 里**故意**写着
      `random.random() < pass_rate`（解释历史实现），字符串口径会被自己写的注释骗。
    """
    tree = _tree()
    names = {n.id for n in ast.walk(tree) if isinstance(n, ast.Name)}
    assert "pass_rate" not in names, "pass_rate 又回来了"

    src = AGENT_FILE.read_text(encoding="utf-8")
    assert "len(passed_checks) / len(checks)" not in src, "「通过率 = passed/total」又回来了"
