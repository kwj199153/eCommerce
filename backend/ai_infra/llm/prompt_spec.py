"""Prompt 规格：版本 + 指纹 + 变量契约（第 283 轮 · A 档）。

三问三答
--------
**① 为什么需要 `PromptSpec`，继续把模板当普通字符串不行吗？**

不行 —— 因为「提示词改了」在本仓是**完全不可观测**的：正文住在 `.py` 常量里，
没有版本、没有指纹。线上回答质量突变时，无法回答最基本的一问：
**是提示词改了，还是模型/数据变了？** 只能靠翻 git log 猜。

**② 为什么既要 `version` 又要 `fingerprint`？**

两者管的不是同一件事：

* `version` 是**人**写的 —— 表达「我打算做一次语义升级」，可人不写它就不会变；
* `fingerprint` 是**内容**算的（`sha256(content)[:12]`）—— 改一个字符就变。

只留 version ⇒ 忘记递增时线上跑的是哪一版没人知道；
只留 fingerprint ⇒ 无法表达「这次是语义升级，不只是排版」。
B 档（DB 覆写层）比对的就是 fingerprint：库里存的版本与源码算出来的不一致
⇒ 标记 stale，而不是静默生效。

**③ 为什么 `required_vars` 要"反解 + 校验"，直接 `str.format(**kwargs)` 不行吗？**

不行 —— 提示词正文里普遍含 JSON 示例（`{"section": "运营偏好"}`）。
`string.Formatter().parse` 会把它拆出 field_name=`"section"`（**带引号**），
而 `str.format` 遇到这些花括号会直接抛 `KeyError`。

本仓真实例子：`modules/memory/prompts.py::EXTRACT_INSTRUCTIONS` 里就有一整段
JSON 示例。所以这里的契约是：

* **变量只认标识符形态**（`{market}` 是变量，`{"section"}` / `{}` 不是）；
* 渲染**只替换已声明的变量**，其余花括号原样保留（不去碰 JSON 示例）；
* 声明与反解不一致 ⇒ **注册期就报错**，不让契约漂移进运行期。

★ 与 `ai_infra.prompt_sections` 的分工：那边管「system prompt 的**外部段落**」
（跨会话记忆这类按人注入的增益块），这边管「业务提示词**模板正文**」。
两者重名判据本轮统一为「当场 raise」。
"""

from __future__ import annotations

import hashlib
import string
from dataclasses import dataclass
from typing import Any, Dict, Mapping, Optional, Tuple

__all__ = [
    "PromptSpec",
    "RenderedPrompt",
    "PromptSpecError",
    "PromptVariableMissing",
    "extract_required_vars",
    "render_prompt",
]

_FORMATTER = string.Formatter()

#: 指纹长度（12 hex = 48 bit，碰撞概率对「几百份提示词」量级可忽略）
FINGERPRINT_LEN = 12


class PromptSpecError(ValueError):
    """提示词**契约**错误（注册期就会炸，不让它漂到运行期）。"""


class PromptVariableMissing(KeyError):
    """渲染时缺少模板声明的变量。

    ★ 为什么是 `KeyError` 的子类：既有调用方已经用 `pytest.raises(KeyError)`
      钉住「未注册 → 报错」，让「缺变量」走同一族异常，调用方不需要记两套。
    """


def extract_required_vars(content: str) -> Tuple[str, ...]:
    """反解模板正文里的**真**占位符。

    ★ 只收**标识符**形态（`{market}`）。以下都不是变量：

    * `{"section": "运营偏好"}` —— JSON 示例，field_name 带引号，不是标识符；
    * `{}` —— 空占位符（field_name 为 `''`）；
    * `{0}` —— 位置参数（数字不是标识符）。

    Raises:
        PromptSpecError: 正文里有**无法配对**的花括号（如单个 `{`）。
            提示词作者需写成 `{{` / `}}` 转义 —— 让它在注册期炸，
            好过运行期渲染时才炸（那时它已经在服务线上了）。
    """
    try:
        parsed = list(_FORMATTER.parse(content))
    except ValueError as exc:  # 花括号不配对
        raise PromptSpecError(
            f"提示词正文花括号不配对，无法解析：{exc}。"
            f"若正文里要写花括号（JSON 示例以外），请写成 {{{{ / }}}} 转义。"
        ) from exc

    out: list = []
    seen: set = set()
    for _literal, field_name, _spec, _conv in parsed:
        if not field_name or not field_name.isidentifier():
            continue
        if field_name in seen:
            continue
        seen.add(field_name)
        out.append(field_name)
    return tuple(out)


@dataclass(frozen=True)
class PromptSpec:
    """一份提示词的**规格**：正文 + 版本 + 变量契约。

    frozen ⇒ 注册后不可被就地改写（改写等于让线上提示词在无人知情的情况下换掉）。

    Args:
        name: 模板键（注册表里的唯一名字）
        content: 模板正文
        version: 语义版本（人写；默认 `"1"`）
        required_vars: 声明的变量名。**不传则按正文反解**；
            传了就必须与反解结果**完全一致**（顺序无关），否则注册期报错 ——
            这一条守的是「声明与正文漂移」：正文删掉了 `{market}` 而声明里还留着，
            或正文新加了 `{lang}` 而声明没跟上。
    """

    name: str
    content: str
    version: str = "1"
    required_vars: Optional[Tuple[str, ...]] = None

    def __post_init__(self) -> None:
        if not str(self.name or "").strip():
            raise PromptSpecError("提示词名不能为空 —— 空名会让出错时无法指出是哪一份")
        if not self.content or not self.content.strip():
            raise PromptSpecError(f"提示词 {self.name!r} 正文为空")
        if not str(self.version or "").strip():
            raise PromptSpecError(f"提示词 {self.name!r} 版本不能为空")

        derived = extract_required_vars(self.content)
        if self.required_vars is None:
            # frozen dataclass 里用 object.__setattr__ 落默认值：
            # 让「反解结果」成为规格的一部分，渲染时不必每次重算。
            object.__setattr__(self, "required_vars", derived)
            return

        declared = tuple(self.required_vars)
        for v in declared:
            if not v.isidentifier():
                raise PromptSpecError(
                    f"提示词 {self.name!r} 声明的变量 {v!r} 不是合法标识符"
                )
        if set(declared) != set(derived):
            raise PromptSpecError(
                f"提示词 {self.name!r} 变量声明与正文不符："
                f"声明={sorted(declared)} 正文反解={sorted(derived)}。"
                f"改正文就要改声明（或干脆不传 required_vars，让它自动反解）。"
            )
        object.__setattr__(self, "required_vars", derived)

    @property
    def fingerprint(self) -> str:
        """正文指纹（`sha256(content)[:12]`）。

        ★ 只算**正文**，不含 name / version：指纹要回答的是「这份文本是不是变了」，
          改名或升版本不改变文本本身，就不该改变指纹。
        """
        return hashlib.sha256(self.content.encode("utf-8")).hexdigest()[:FINGERPRINT_LEN]

    def render(self, **kwargs: Any) -> "RenderedPrompt":
        """填充变量并产出 `RenderedPrompt`。"""
        return render_prompt(self, **kwargs)


class RenderedPrompt(str):
    """渲染结果：**就是** `str`，额外携带 `name` / `version` / `fingerprint`。

    ★ 为什么做成 `str` 的子类，而不是一个普通 dataclass：
      全仓 12 处调用形如 `system_prompt=self.get_prompt_template("aigc_media")`，
      直接把返回值当字符串用。若返回值不再是 `str`，这 12 处**全部**要改，
      而它们没有任何一处需要版本信息 —— 为携带元数据去改 12 处调用点，
      等于让「可观测性」这个需求去打扰「取提示词」这个需求。

      做成 `str` 子类后：既有调用点**零改动**（`==`、`len()`、拼接、序列化照旧），
      需要排障的地方可以顺手打 `.fingerprint` / `.version`。

    ★ 反过来说，这也意味着**不能**用 `type(x) is str` 去判它 —— 本仓没有这么判的。
    """

    def __new__(
        cls,
        text: str,
        *,
        spec: PromptSpec,
        values: Optional[Mapping[str, Any]] = None,
    ) -> "RenderedPrompt":
        obj = super().__new__(cls, text)
        obj._spec = spec
        obj._values = dict(values or {})
        return obj

    @property
    def spec(self) -> PromptSpec:
        return self._spec

    @property
    def name(self) -> str:
        return self._spec.name

    @property
    def version(self) -> str:
        return self._spec.version

    @property
    def fingerprint(self) -> str:
        return self._spec.fingerprint

    @property
    def values(self) -> Dict[str, Any]:
        """本次渲染实际用到的变量值（排障用）。"""
        return dict(self._values)

    def __repr__(self) -> str:  # pragma: no cover - 只影响日志可读性
        return (
            f"RenderedPrompt(name={self.name!r}, version={self.version!r}, "
            f"fingerprint={self.fingerprint!r}, chars={len(self)})"
        )


def render_prompt(spec: PromptSpec, **kwargs: Any) -> RenderedPrompt:
    """按规格渲染：**只替换已声明的变量**，其余花括号原样保留。

    ★ 为什么不用 `str.format`：
      正文里的 JSON 示例（`{"section": ...}`）会让 `str.format` 抛 `KeyError`，
      而那些花括号是**要原样发给模型**的示例文本，不是变量。

    Raises:
        PromptVariableMissing: 模板声明了某个变量但本次没传。
            ★ 这里是**显式失败**，不再退回「保留 `{market}` 原样发出去」——
            把未填充的占位符发给模型是静默失效：不报错、不降级，
            只是模型偶尔看到一句「你是一位专注于 {market} 市场的分析师」。
    """
    required = tuple(spec.required_vars or ())
    missing = [v for v in required if v not in kwargs]
    if missing:
        raise PromptVariableMissing(
            f"提示词 {spec.name!r}（v{spec.version} / {spec.fingerprint}）缺少变量 "
            f"{sorted(missing)}；已声明变量={sorted(required)}。"
            f"缺变量时**不会**把未填充的 {{占位符}} 发给模型。"
        )

    text = spec.content
    used: Dict[str, Any] = {}
    for var in required:
        value = kwargs[var]
        used[var] = value
        text = text.replace("{" + var + "}", str(value))

    return RenderedPrompt(text, spec=spec, values=used)
