"""技能图标（emoji）—— 提取、生成、兜底（第 188 轮）

==============================================================================
★ 需求原文
==============================================================================
    「emoji + 保存时自动生成 + 允许手工改（留空则 AI 补）」

拆成三条**可验收**的性质：

    ① **emoji**     —— 存的是一个 emoji 字符（不是 URL、不是图片、不是图标名）。
                       选 emoji 的实据：前端现有 14 张快捷卡片的图标**全是 emoji**
                       （📋 🚨 🧠 …），同一套渲染直接复用，前端零新增分支。
    ② **自动生成**  —— 保存时若没给图标，后端调 LLM 按 title + description 挑一个。
    ③ **允许手工改**—— 给了就用给的，**不覆盖**用户的输入；
                       「留空」才走 AI 补。

==============================================================================
★★★ 本模块为什么单独成文件（而不是塞进 service.py）
==============================================================================
`service.py` 是**纯数据层**（不持有外部依赖，测试直接构造 ORM 行就能跑）。
把一次网络调用塞进去，会让它的每一个用例都变成"要么依赖网络、要么得先 patch"。
本仓已有判据：「**按访问模式选存储形态**」「控制流进唯一实现」——
这里同理：**外部依赖的边界要显式**，让调用方看得见"这一步会出网"。

==============================================================================
★★★ 两条硬的降级要求
==============================================================================
**① 生成失败绝不阻断保存。**
   图标是装饰性元数据。为它丢一次保存（用户刚写完 900 字正文）是不可接受的。
   ⇒ 任何异常都吞掉、记 warning、返回 `None`；调用方把 `None` 存进去，
     前端用 `icon || 通用兜底` 渲染。

**② 失败要**看得见**，不能伪装成成功。**
   ⇒ 返回 `None`（而不是随手塞一个 📦 当"默认分类图标"）。
     塞一个像模像样的图标会让"AI 从没成功过"这件事在界面上**完全不可见** ——
     这正是本仓「降级路径禁用全 0 兜底」那条铁律的同族形态。

==============================================================================
★★ 生成器是**可替换的单一入口**（测试的必需，不是便利）
==============================================================================
`generate_skill_icon` 只做一件事：把请求转给模块级 `_GENERATOR`。
测试通过 `set_icon_generator()` 换成确定性 stub ⇒ 全套测试零网络、零等待。

★ 为什么不用"config 开关关掉生成"：
  开关只能表达"生成 / 不生成"两态，而**解析结果对不对**（LLM 回了一整句话
  时能不能正确摘出 emoji）恰恰是本模块最需要被测的部分 ——
  换生成器能测，开关不能。

★ 为什么不用 `monkeypatch.setattr(service, "generate_skill_icon", ...)`：
  那要求**所有调用点都写成 `service.generate_skill_icon(...)` 属性访问**，
  一旦某处 `from ... import generate_skill_icon` 直取（本仓常规写法），
  patch 就**静默失效** —— 测试还是绿的，但测的是真网络。
  模块级单点 + 显式 setter 没有这个缺口。
"""

from typing import Awaitable, Callable, List, Optional

from core.logger import get_logger

logger = get_logger(__name__)

#: 图标列的长度上限（字符数）。emoji 序列最长也就几个码点，16 足够宽松，
#: 又能挡住"LLM 回了一整行文字"这种越界写入。
ICON_MAX_CHARS = 16

#: 提取结果里允许的**最大码点数**（国旗 2、肤色修饰 3、ZWJ 家庭序列 7）。
#: 超出的部分截断而不是判失败 —— 目标是"别把一句话当图标存进去"。
ICON_MAX_CODEPOINTS = 8


# ============================================================================
# emoji 识别：逐码点扫描
# ============================================================================
#
# ★ 为什么不用正则：
#   `\w` 与字符类范围在 Python / JS / 各引擎里语义不一致，本仓已经吃过
#   "前后端两套判定"的亏（`X-Shop-ID` 曾指两种 ID 空间）。
#   逐码点扫描的口径**只在这里定义一次**，可读、可断言、可被测试穷举。
#
# ★ 区间取"够用且不过宽"：
#   刻意**包含**符号类（✅ ⭐ ⚙），因为技能图标很多是这类；
#   刻意**排除** © ® ™（后两个在 0x21xx/0x21xx 附近但单独用不像图标）。
_EMOJI_BASE_RANGES = (
    (0x1F000, 0x1F02F),   # 麻将牌
    (0x1F0A0, 0x1F0FF),   # 扑克牌
    (0x1F1E6, 0x1F1FF),   # 区域指示符（成对 = 国旗）
    (0x1F300, 0x1F5FF),   # 天气 / 物品 / 符号
    (0x1F600, 0x1F64F),   # 表情
    (0x1F680, 0x1F6FF),   # 交通 / 地图
    (0x1F700, 0x1F77F),   # 炼金符号
    (0x1F780, 0x1F7FF),   # 几何扩展
    (0x1F800, 0x1F8FF),   # 补充箭头 C
    (0x1F900, 0x1F9FF),   # 补充符号（手势 / 身体 / 工具）
    (0x1FA70, 0x1FAFF),   # 符号与象形扩展 A
    (0x2190, 0x21FF),     # 箭头
    (0x2300, 0x23FF),     # 技术符号（⌚ ⏰ ⏳）
    (0x2460, 0x24FF),     # 带圈字母数字
    (0x25A0, 0x25FF),     # 几何图形（▪ ▶ ●）
    (0x2600, 0x26FF),     # 杂项符号（☀ ⚙ ⛔ ⚡）
    (0x2700, 0x27BF),     # 装饰符号（✅ ✂ ✈ ✨）
    (0x2900, 0x297F),     # 补充箭头 B
    (0x2B00, 0x2BFF),     # 杂项符号与箭头（⭐ ⬆）
)

#: 允许**跟在基字符之后**的修饰码点。
_VS16 = 0xFE0F   # 变体选择符-16（把文字形态的 ☀ 变成 emoji 形态）
_VS15 = 0xFE0E   # 变体选择符-15（反向：强制文字形态 —— 出现即视为序列结束）
_ZWJ = 0x200D    # 零宽连接符（拼合序列，如 👨‍👩‍👧）
_KEYCAP = 0x20E3  # 组合用键帽（1️⃣）
_TAG_BASE = 0xE0020
_TAG_MAX = 0xE007F
_SKIN_BASE = 0x1F3FB
_SKIN_MAX = 0x1F3FF

#: 键帽序列的**候选基字符**（ASCII）。⚠️ 它们是"有条件的基字符"：
#: 只有后面紧跟 VS16 或键帽修饰符时才算 emoji。
#:
#: ★★★ 这个区分是必需的，不是洁癖：若把 `0`-`9` 无差别当基字符，
#:   `extract_emoji("每月1号复盘")` 会摘出 `"1"` 并当成图标存进库 ——
#:   界面上就会显示一个光秃秃的数字。而这行描述**完全正常**，
#:   所以在真实数据里迟早会出现，且症状（图标变成数字）极难归因到本函数。
_KEYCAP_BASES = frozenset("0123456789#*")


def _is_base(ch: str) -> bool:
    """**无条件**基字符（U+1F300 这一类独立成 emoji 的）。"""
    cp = ord(ch)
    return any(lo <= cp <= hi for lo, hi in _EMOJI_BASE_RANGES)


def _is_conditional_base(ch: str) -> bool:
    """**有条件**基字符（键帽候选）。见 `_KEYCAP_BASES` 的论证。"""
    return ch in _KEYCAP_BASES


def _is_zwj(ch: str) -> bool:
    return ord(ch) == _ZWJ


def _is_skin(ch: str) -> bool:
    return _SKIN_BASE <= ord(ch) <= _SKIN_MAX


def _is_vs16(ch: str) -> bool:
    return ord(ch) == _VS16


def _is_keycap(ch: str) -> bool:
    return ord(ch) == _KEYCAP


def _is_tag(ch: str) -> bool:
    return _TAG_BASE <= ord(ch) <= _TAG_MAX


def extract_emoji(text: str) -> Optional[str]:
    """从任意文本里摘出**第一个 emoji 序列**；找不到返回 `None`。

    ★ 为什么需要它而不是直接用 `response.content.strip()`：
      提示词写着"只回一个 emoji"，但模型**经常**回
      「这个技能的图标是：📉」或「📉」（带引号）或「图标：📉\\n说明：…」。
      直接 strip 会把这些整句存进 `skills.icon`，
      前端 `<span>` 里就会出现一句中文解释 —— 而列只有 16 字符，还会被截断。

    ★ 序列规则（覆盖实际会遇到的几类）：
      · 单个基字符                `📉`
      · 基字符 + VS16             `☀️`（两个码点，缺 VS16 会渲染成文字色）
      · 基字符 + 肤色              `👍🏽`
      · 区域指示符 + 区域指示符     `🇨🇳`（两面相同区域码才算国旗，这里放宽为任意一对）
      · 基字符 (ZWJ 基字符)*       `👨‍💻`
      · 基字符 + 键帽              `1️⃣`
      · 基字符 + 标签序列          旗帜的后缀变体
    """
    raw = str(text or "")
    if not raw:
        return None

    for i, ch in enumerate(raw):
        if _is_base(ch):
            conditional = False
        elif _is_conditional_base(ch):
            # ★ 只是**候选**：下面扫完若没找到键帽修饰符，会跳过它继续往后找。
            conditional = True
        else:
            continue

        out: List[str] = [ch]
        saw_keycap_mark = False
        j = i + 1
        while j < len(raw) and len(out) < ICON_MAX_CODEPOINTS:
            nxt = raw[j]

            # --- ZWJ：只有后面真跟着一个基字符才算拼合，否则视为噪声 ---
            if _is_zwj(nxt):
                if j + 1 < len(raw) and _is_base(raw[j + 1]):
                    out.append(nxt)
                    out.append(raw[j + 1])
                    j += 2
                    continue
                break

            # --- VS15 是"要文字形态"，与"当图标用"的意图相悖 ⇒ 到此为止 ---
            if ord(nxt) == _VS15:
                break

            if _is_vs16(nxt) or _is_skin(nxt) or _is_keycap(nxt):
                if _is_keycap(nxt):
                    saw_keycap_mark = True
                out.append(nxt)
                j += 1
                continue

            if _is_tag(nxt):
                out.append(nxt)
                j += 1
                continue

            # --- 国旗：区域指示符成对。仅当双方都是区域指示符时才相连 ---
            if _is_base(nxt) and len(out) == 1 and 0x1F1E6 <= ord(ch) <= 0x1F1FF:
                if 0x1F1E6 <= ord(nxt) <= 0x1F1FF:
                    out.append(nxt)
                    j += 1
                    continue

            break

        if conditional and not saw_keycap_mark:
            # 有条件的基字符没组成键帽序列 ⇒ 这不是 emoji，继续往后找。
            # （`"每月1号复盘"` 就是走这条：`1` 后面跟着 `号` ⇒ 跳过 ⇒ 最终 None。）
            continue

        candidate = "".join(out)[:ICON_MAX_CHARS].strip()
        if candidate:
            return candidate
        # 理论上不可达（out 至少含 ch）；保留以防将来改区间时静默返回空
        continue

    return None


# ============================================================================
# 默认生成器：调 LLM
# ============================================================================
#
# ★ 提示词写在**业务模块**而不是 `ai_infra`：
#   `ai_infra` 有一条 AST 门禁（`tests/test_infra_layering.py`）禁止业务词，
#   而这里必须提到"电商""技能"这类词才能让模型挑对图标。
# ★ 第 283 轮：正文归位到 `modules/skills/prompts.py`（注册表键 `"skills_icon"`）。


async def _llm_generate(title: str, description: str) -> Optional[str]:
    """真实生成器：调 LLM 挑一个 emoji，解析失败返回 `None`。

    ★ 这里**只负责"拿到一个候选字符串"**，摘取与校验交给 `extract_emoji` ——
      两条职责分开，才使得"解析逻辑"可以在**不发网络请求**的前提下被单测
      （直接喂 `extract_emoji("图标：📉")` 即可）。
    """
    from ai_infra.llm.dashscope_client import get_llm
    from ai_infra.llm import get_prompt_template
    from modules.skills import prompts  # noqa: F401  —— import 即注册

    user = f"技能名称：{title or '(未命名)'}\n技能用途：{description or '(未填写描述)'}"
    llm = get_llm()
    resp = await llm.chat(
        user,
        system_prompt=get_prompt_template("skills_icon"),
        # ★ 挑图标要的是**稳定**而不是多样：temperature 高会同一个技能
        #   每次保存换一个图标，看起来像"坏了"。
        temperature=0.1,
        # 一个 emoji 最多几个 token；给 16 留出"模型先输出一小段"的余地，
        # 同时把它想长篇大论的路堵死（省时省钱）。
        max_tokens=16,
    )
    return extract_emoji(getattr(resp, "content", "") or "")


# ============================================================================
# 可替换入口（唯一）
# ============================================================================
IconGenerator = Callable[[str, str], Awaitable[Optional[str]]]

_GENERATOR: IconGenerator = _llm_generate


async def generate_skill_icon(title: str, description: str) -> Optional[str]:
    """生成一个 emoji 图标；任何失败都返回 `None`（**绝不抛错**）。

    ★ 调用方约定：
      · `None` ⇒ 图标为空，前端用通用兜底渲染；
      · **不要**把 `None` 换成一个"看起来像图标"的默认值 ——
        那会让"生成从未成功"这件事在界面上完全不可见（见模块 docstring）。
    """
    try:
        found = await _GENERATOR(title or "", description or "")
    except Exception as exc:  # noqa: BLE001 —— 故意的：装饰性元数据不配阻断保存
        logger.warning("技能图标生成失败（不影响保存）：%s", exc)
        return None
    if not found:
        logger.warning("技能图标生成返回了无法解析的内容（不影响保存）")
        return None
    return found


def set_icon_generator(fn: Optional[IconGenerator]) -> None:
    """替换生成器（`None` 表示恢复成真实 LLM 实现）。

    ★ 测试用；生产代码不应调用。它存在的理由见模块 docstring
      「生成器是可替换的单一入口」。
    """
    global _GENERATOR
    _GENERATOR = fn or _llm_generate


def current_generator_name() -> str:
    """当前生成器的名字（测试断言"挂的是不是 stub"用）。"""
    return getattr(_GENERATOR, "__name__", type(_GENERATOR).__name__)


__all__ = [
    "ICON_MAX_CHARS",
    "ICON_MAX_CODEPOINTS",
    "extract_emoji",
    "generate_skill_icon",
    "set_icon_generator",
    "current_generator_name",
]
