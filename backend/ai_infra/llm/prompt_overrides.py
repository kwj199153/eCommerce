"""Prompt 覆写层 —— **应用侧**（第 351 轮 · P0-7 B 档）

==============================================================================
★ A 档给了什么，B 档补什么
==============================================================================
A 档（第 283 轮）给每份提示词配了 `version` + `fingerprint`，让「提示词改了」
第一次变得**可观测**。但它只解决了「看得见」——提示词正文仍然只住在 `.py` 常量里，
改一个词就要改代码 + 重新发布。

B 档是**覆写层**：把「当前生效的正文」从源码里解耦出来，放进一张表
（`prompt_versions`），运维可以不改代码就换上另一版正文。
本模块是这条链路的**下游一半**（把一份覆写应用到内存注册表）；
上游（建表 / 读写 / 管理端点）在 `modules/prompt_versions/`。

★ 为什么应用侧住 `ai_infra`，而读写侧住 `modules/`
    `PROMPT_TEMPLATES` 注册表是 `ai_infra/llm` 的进程级单例，而本仓有一条**硬红线**：
    `ai_infra` 不得 import `modules.*`（见 `tests/test_infra_layering.py`，
    它拦的是历史上 4 处真实泄漏）。若把「读表 + 应用」写在一起放进业务模块，
    业务模块就得伸手改 `ai_infra` 的内部状态 —— 那等于把红线的方向反过来。
    ⇒ 分工：**业务侧读表、infra 侧应用**，中间只过一个受控入口（本模块的
      `apply_override()`）。方向仍是 `modules → ai_infra`（合法）。

==============================================================================
★ 为什么必须有 `base_fingerprint` 这道闸门（本模块存在的核心理由）
==============================================================================
    一条覆写是**基于源码某一版正文**写的。若源码后来被人改过，那条覆写就
    建立在一份**已不存在的文本**上 —— 此时直接把它盖上：

      · 覆盖掉的是别人刚改好的正文，而且**没有任何一处会报错**；
      · 症状是「某人改了提示词却没生效」，去翻 git 也看不出问题
        （改动确实在源码里），典型的**静默回滚**。

    ⇒ 覆写必须带上它写的时候那一版的指纹（`base_fingerprint`）。
      应用时拿它与**当前源码**的指纹比对：
        · 相等 ⇒ 源码没动过，覆写可以盖上去；
        · 不等 ⇒ 拒绝应用（`PromptOverrideRejected`），状态标 `stale`，
          由人决定「是重写覆写，还是放弃」。

    ★ 这条判据与 A 档 docstring 里那句「库里存的版本与源码算出来的不一致 ⇒
      标记 stale，而不是静默生效」是同一句话的落地。

==============================================================================
★ 第二道闸门：变量集必须一致
==============================================================================
    提示词正文里的 `{var}` 决定了调用点要传什么。若覆写把变量换掉
    （删掉 `{market}`、或新加 `{tone}`），调用点仍按老一套传参：

      · 少传 ⇒ 渲染期 `PromptVariableMissing`（还好，会炸）；
      · 多传 ⇒ **完全静默**，那个变量永远不会被填进去。

    ⇒ 覆写的变量集必须与源码那版的 `required_vars` **完全相同**（集合相等），
      否则拒绝应用。想让覆写换变量，就必须先改源码 —— 那是刻意的摩擦：
      变量集是**调用点契约**，不该由一份运维配置单方面改掉。
"""

from __future__ import annotations

import hashlib
from typing import Dict, List, Optional, Tuple

from .dashscope_client import PROMPT_TEMPLATES
from .prompt_spec import FINGERPRINT_LEN, PromptSpec, PromptSpecError, extract_required_vars

__all__ = [
    "PromptOverrideError",
    "PromptOverrideRejected",
    "applied_overrides",
    "apply_override",
    "describe_override",
    "preview_override",
    "registered_names",
    "reset_override",
    "source_fingerprint",
    "validate_override",
    "variables_of",
]


class PromptOverrideError(ValueError):
    """覆写层自身的用法错误（调用方参数不对）。"""


class PromptOverrideRejected(PromptOverrideError):
    """这条覆写**不能**被应用（stale / 变量集不符 / 名字未注册）。

    ★ 与「应用成功」严格分开：调用方必须能区分「他没写覆写」与
      「他写了但被拒绝」—— 后者要显示给人看，前者是常态。
    """

    def __init__(self, message: str, *, reason: str) -> None:
        self.reason = reason
        super().__init__(message)


#: name -> 覆写前的**源码**规格。第一次覆写时记下，供撤回与后续比对。
#: ★ 存源码规格而不是「上一版覆写」：`base_fingerprint` 的语义是
#:   「这条覆写基于哪一版**源码**」，不是「基于哪一版覆写」。
_ORIGINALS: Dict[str, PromptSpec] = {}

#: name -> 当前生效的覆写指纹（便于 `describe_override` 与幂等判断）
_APPLIED: Dict[str, str] = {}


def _fingerprint(content: str) -> str:
    """与 `PromptSpec.fingerprint` **同一算法**（`sha256(content)[:12]`）。

    ★ 刻意复用同一个长度常量，不另写 `12`：两处口径分叉时，
      比对会永远不相等 ⇒ 所有覆写一律被判 stale，而症状看着像「没人写覆写」。
    """
    return hashlib.sha256(content.encode("utf-8")).hexdigest()[:FINGERPRINT_LEN]


def applied_overrides() -> Tuple[str, ...]:
    """当前真正被覆写的模板名（有序 = 首次应用顺序）。"""
    return tuple(_APPLIED)


def describe_override(name: str) -> Optional[dict]:
    """描述某个模板的覆写状态；未被覆写返回 `None`。"""
    if name not in _APPLIED:
        return None
    original = _ORIGINALS.get(name)
    return {
        "name": name,
        "source_fingerprint": original.fingerprint if original else None,
        "applied_fingerprint": _APPLIED[name],
        "source_version": original.version if original else None,
    }


def apply_override(
    name: str,
    *,
    content: str,
    version: str,
    base_fingerprint: str,
) -> str:
    """把一条覆写应用到内存注册表。

    Args:
        name: 模板键（必须已在 `PROMPT_TEMPLATES` 里注册）
        content: 覆写正文
        version: 覆写后的语义版本（人写）
        base_fingerprint: **写这条覆写时**源码那一版的指纹

    Returns:
        应用的覆写指纹。

    Raises:
        PromptOverrideRejected:
            · `unknown-name` —— 该名字没被注册（`prompts.py` 没被 import）；
            · `stale`         —— 源码已变，覆写基于旧文本；
            · `vars-mismatch` —— 变量集与源码不一致（调用点契约会被破坏）；
            · `invalid`       —— 正文为空 / 花括号不配对等规格错误。
        PromptOverrideError: 调用方参数缺失（name / content 为空）。
    """
    # ★ 全部闸门在 `_prepare()` 里 —— 与写口的 `validate_override()` 同一实现。
    #   本函数只多做一件 `_prepare` 不做的事：**落写**。
    source, candidate = _prepare(
        name, content=content, version=version, base_fingerprint=base_fingerprint
    )
    key = (name or "").strip()

    # 首次覆写才记下源码规格（后续换覆写内容时基线不变）
    _ORIGINALS.setdefault(key, source)
    PROMPT_TEMPLATES[key] = candidate
    _APPLIED[key] = candidate.fingerprint
    return candidate.fingerprint


def _prepare(
    name: str,
    *,
    content: str,
    version: str,
    base_fingerprint: str,
) -> Tuple[PromptSpec, PromptSpec]:
    """跑完**全部**闸门，返回 `(源码规格, 候选覆写规格)`。

    ★ 刻意**不做任何 mutation**（不写 `_ORIGINALS` / `PROMPT_TEMPLATES` /
      `_APPLIED`）：写口要在**落库之前**复用同一套闸门，那时不该有副作用。

    ★ 与 `apply_override()` 共用**同一实现**（后者只是调它 + 落写）：
      闸门一旦有两份，下次改动只会修好其中一条路，而症状是
      「写的时候拦住了、应用的时候没拦」（或反过来）—— 两条路各说各话。

    Raises:
        PromptOverrideRejected: unknown-name / stale / vars-mismatch / invalid
        PromptOverrideError: 调用方参数缺失（name / content 为空）
    """
    key = (name or "").strip()
    if not key:
        raise PromptOverrideError("覆写校验: name 不能为空")
    if not content or not content.strip():
        raise PromptOverrideError(f"覆写校验: 模板 {key!r} 覆写正文为空")

    source = PROMPT_TEMPLATES.get(key)
    if source is None:
        raise PromptOverrideRejected(
            f"模板 {key!r} 未注册 —— 覆写只能作用在已注册的提示词上。"
            f"当前已注册: {sorted(PROMPT_TEMPLATES)}",
            reason="unknown-name",
        )

    baseline = _ORIGINALS.get(key, source)
    expected_base = (base_fingerprint or "").strip()
    if expected_base != baseline.fingerprint:
        raise PromptOverrideRejected(
            f"模板 {key!r} 的覆写已过期（stale）：它基于 {expected_base or '<空>'}，"
            f"而当前源码是 {baseline.fingerprint}（v{baseline.version}）。"
            f"源码正文改过之后，这条覆写会**静默回滚**那次改动，所以拒绝应用。"
            f"请基于新正文重写覆写，或放弃它。",
            reason="stale",
        )

    try:
        candidate = PromptSpec(name=key, content=content, version=version or "1")
    except PromptSpecError as exc:
        raise PromptOverrideRejected(
            f"模板 {key!r} 的覆写正文不是合法规格：{exc}", reason="invalid"
        ) from exc

    source_vars = set(baseline.required_vars or ())
    candidate_vars = set(candidate.required_vars or ())
    if candidate_vars != source_vars:
        raise PromptOverrideRejected(
            f"模板 {key!r} 的覆写改变了变量集：源码={sorted(source_vars)} "
            f"覆写={sorted(candidate_vars)}。变量集是**调用点契约** —— "
            f"改了它，调用点可能少传（渲染期报错）或多传（**完全静默**地丢掉一个变量）。"
            f"要换变量请先改源码。",
            reason="vars-mismatch",
        )

    return source, candidate


def validate_override(
    name: str,
    *,
    content: str,
    version: str,
    base_fingerprint: str,
) -> Tuple[str, ...]:
    """只校验、**不应用**：返回候选覆写的变量集（便于调用方回显）。

    ★ 为什么写口必须自己跑一遍：本模块的闸门原本只在 `apply_override()`
      （= **应用**时）跑，而写口是**先落库、后应用**。于是库里会留下一条
      `enabled=True` + 基线对得上的覆写，却永远装不上；而
      `modules/prompt_versions/service.py::_status_of()` 恰恰按这两条判
      `active` ⇒ 界面显示「覆写生效中」，线上跑的却是源码版 —— **虚假陈述**，
      正是本模块存在要消灭的那种状态。

    Raises:
        同 `_prepare()`；本函数不产生任何副作用。
    """
    _, candidate = _prepare(
        name, content=content, version=version, base_fingerprint=base_fingerprint
    )
    return tuple(candidate.required_vars or ())


def reset_override(name: str) -> bool:
    """撤回覆写，恢复源码版。返回是否真的撤回了一条（幂等）。"""
    key = (name or "").strip()
    original = _ORIGINALS.pop(key, None)
    _APPLIED.pop(key, None)
    if original is None:
        return False
    PROMPT_TEMPLATES[key] = original
    return True


def preview_override(content: str) -> Tuple[str, ...]:
    """预览一份正文会声明哪些变量（给管理端点做前端校验用）。"""
    return extract_required_vars(content)


def variables_of(name: str) -> Tuple[str, ...]:
    """某个已注册模板**当前生效**的变量集。"""
    spec: Optional[PromptSpec] = PROMPT_TEMPLATES.get((name or "").strip())
    return tuple(spec.required_vars or ()) if spec is not None else ()


def source_fingerprint(name: str) -> Optional[str]:
    """某模板**源码**那一版的指纹（有覆写时返回基线，没有时返回当前）。

    ★ 管理端点用它填 `base_fingerprint`，让前端不需要自己算 sha256 ——
      自算复刻就是「同一判定两份实现」，迟早会分叉。
    """
    key = (name or "").strip()
    baseline = _ORIGINALS.get(key)
    if baseline is not None:
        return baseline.fingerprint
    spec = PROMPT_TEMPLATES.get(key)
    return spec.fingerprint if spec is not None else None


def registered_names() -> List[str]:
    """已注册的模板名（给管理端点列候选）。"""
    return sorted(PROMPT_TEMPLATES)
