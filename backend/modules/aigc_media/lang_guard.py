"""同语言短路 + 混合语言放行 —— 一个判据、两条入口共用（第 364 轮建，365 轮修正）。

━━━ 它解决什么 ━━━
唯一的翻译入口是划词：**一律译成中文**（r364 老板拍板）。
但目标语言固定成中文后，**中文选区**就掉进一个坑：模型被要求
「译成中文」，它要么原样回显，要么把中文**改写**一遍 —— 后者是静默的语义漂移。
实测：纯中文「这个商品」→「此商品」（同一个意思，但不再是他选中的那段）。
⇒ 方向 == 原文语言时**根本不调模型**，如实回 `same_lang=true`，
   由前端给一个「译为英文」的显式入口。

━━━ 第 365 轮为什么改了短路条件 ━━━
老板实测（2026-10-02 20:00）：「我选择的是『这个 listing』，翻译结果应该是
『该商品链接』，目前是否识别为了全中文。」—— 是的：二值判据把它整段判成 zh，
于是一次都不译。
根因：`detect_lang` 是**二值**判据（含任一 CJK ⇒ zh），它分不出
「纯中文」与「中文夹外文词」，而后者在跨境电商场景里是**常态**
（「这个 listing」「这个 Noise Cancelling 耳机」）。
⇒ 夹了拉丁字母就**不短路**，交给模型。实测效果正是想要的那种：
    「这个 Noise Cancelling 耳机」→「这款主动降噪耳机」（外文术语被落成中文）；
    而纯中文仍然短路（「这个商品」→ 一次 LLM 都不调）。

━━━ 为什么还要 reconcile_noop ━━━
放行混合文本之后，「纯中文 + 英文缩写」这类（实测「店管家 AI」）模型常常**原样退回**。
照常显示译文的话，界面会给出「中文 → 中文」这种自相矛盾的方向徽标。
故拿到结果后比对一次「输出 vs 输入」，实质相同就归回 `same_lang` 那一态。
★ 不额外花钱：只比对已有输出，不加一次调用。
★ 与 `guard_same_lang` 不是同一个判断：guard 比的是「输入 vs 目标语言」，
  这个比的是「输出 vs 输入」。两者都不含语言表。

━━━ 为什么住在模块里，而不是 `AIGCMediaAgent` 的方法 ━━━
`agent_aigc.py` 在体量棘轮冻结表里（`tests/test_source_size_ratchet.py`，
冻结值 1849），**加一行就红** —— 这条判据塞回 agent 就会把它推过上限。
（第 367 轮截屏链路退场后，消费方只剩 `service.translate_selection_service` 一处；
但它住在这里而不是 agent 里，理由与消费方个数无关：agent 那一格已经被封顶。）
本仓对这类「逻辑需要一个家」的既有范式是**外移模块 + 顶层函数 + 显式传参**
（同目录的 `asset_gen.py` / `image_client.py` 是同一手法）。
本模块**不 import 任何项目模块**（只接 `agent` 参数）⇒ 不可能有循环导入。

━━━ 判据只住一处 ━━━
语言判定的唯一真源 = `AIGCMediaAgent.detect_lang`（含 CJK ⇒ zh，否则 en；
r364 由 `_detect_lang` 改为公开名，供本模块消费）。
本模块**不重算方向**：`target_lang` 为 `auto` / 空时直接返回 None（交给 agent 自己解析），
只处理「**显式指定**的目标语言 != 原文主导语言」之外的两种收口。
"""

from __future__ import annotations

import re
from typing import TYPE_CHECKING, Any, Dict, Optional

if TYPE_CHECKING:   # 仅为类型标注；运行期不 import，避免与 agent 互相牵住
    from .agent_aigc import AIGCMediaAgent


#: 拉丁字母（≈ 外文词）。中文里夹英文词是跨境电商的常态，而 `detect_lang` 看不见它。
_LATIN = re.compile(r"[A-Za-z]")

#: 比对「实质相同」时抹掉的噪声：空白 / 标点 / 下划线
_NOISE = re.compile(r"[\s\W_]+")


def same_lang_result(text: str, lang: str) -> Dict[str, Any]:
    """诚实回一句「无需翻译」：success=True、translation 为空、degraded=False。

    ★ 三态不许压成两态：`degraded=False` 明确说「这不是故障」，
      `same_lang=True` 才是「没翻」的原因 —— 前端据此显示「已是中文」，
      而不是显示一个空译文框（那看起来像坏了）。
    """
    return {
        "success": True,
        "message": f"原文已是 {lang}，无需翻译",
        "data": {
            "original_text": text,
            "translation": "",
            "source_lang": lang,
            "target_lang": lang,
            "degraded": False,
            "same_lang": True,
        },
    }


def has_foreign_word(text: str) -> bool:
    """文本里夹了拉丁字母（有外文词）⇒ 它并不是「纯目标语言」。"""
    return bool(_LATIN.search(text or ""))


def _substantive_equal(a: str, b: str) -> bool:
    """两段文字「实质相同」：抹掉空白与标点、忽略大小写后逐字相等。

    ★ 空串一律不算相同 —— 否则「两个空值」会让判据**恒真**，
      下游所有同语言短路都成了空跑。
    """
    left = _NOISE.sub("", a or "").lower()
    right = _NOISE.sub("", b or "").lower()
    return bool(left) and left == right


def reconcile_noop(result: Dict[str, Any]) -> Dict[str, Any]:
    """模型把混合文本**原样退回** ⇒ 归回 `same_lang` 那一态（不额外调模型）。

    只看已经拿到的输出，所以**不增加任何 LLM 调用**。
    degraded / 失败的响应一律原样放行（那是另一态，不归这里管）。
    """
    data = result.get("data") or {}
    if not result.get("success") or data.get("degraded"):
        return result
    target = (data.get("target_lang") or "").strip()
    original = data.get("original_text") or ""
    if not target or not original:
        return result
    if not _substantive_equal(original, data.get("translation") or ""):
        return result
    return same_lang_result(original, target)


def guard_same_lang(
    agent: "AIGCMediaAgent",
    text: str,
    target_lang: str,
) -> Optional[Dict[str, Any]]:
    """原文已是目标语言 ⇒ 返回短路结果；否则 `None`（调用方继续走翻译）。

    Args:
        agent: 提供 `detect_lang` 的 Agent 实例（显式传参，本模块不持有全局）。
        text: 待翻译文本（划词选区）。
        target_lang: 目标语言；`auto` / 空 ⇒ 返回 None（方向解析是 agent 的职责）。

    Returns:
        与 `agent.translate_selection` 同形的 `{"success", "message", "data"}`；
        不需要短路时返回 `None`。
    """
    target = (target_lang or "").strip()
    if not target or target == "auto":
        # ★ 在别处再解析一次 auto 就是长出第二份方向实现 —— 直接让路给 agent
        return None
    body = (text or "").strip()
    if not body:
        # 空白由 agent 自己的「没有取到文字」分支负责，别抢它的判定
        return None
    if agent.detect_lang(body) != target:
        return None
    if has_foreign_word(body):
        # ★ 第 365 轮：夹了外文词 ⇒ 不短路，交给模型（见模块 docstring）。
        #   纯中文没有拉丁字母 ⇒ 照旧短路。
        return None
    return same_lang_result(body, target)
