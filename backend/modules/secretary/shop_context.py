"""店秘书的「当前店铺」事实段 —— 服务端注入（第 242 轮）。

★ 为什么有这个文件（是老板实测的事故，不是假想）
==============================================================================
在「虾皮1」问「我的资料库每个库有多少数据了」→ 答 `当前店铺（虾皮1）`，数字正确；
切到「亚马逊1」再问 → **数字真的换成了亚马逊1 的**（checkpoint 里那一轮 6 条工具
回执的 id 全为 `…-store_c3529ab1`、`product_list total=16`、`asset_list total=9`），
**但开场白与结论仍写「当前店铺（虾皮1）」**。老板据此判定「切了店铺还是旧店铺的
数据」—— 结论对不上，是因为答案里那句自称**没有任何权威来源**。

⇒ 必须把两件事分开看：
   · 数据链 `X-Shop-ID → core.tenant.scoping.scoped() → shop_id` **是对的**；
   · 错的是**模型自称的当前店铺**。

根因
==============================================================================
店秘书全部工具里**没有一个是「读当前店铺」的**：`build_shop_tools()` 当时只产出
`switch_shop`，而它**有副作用**（调它 = 真的切店），模型无法用它回答「我现在在哪」；
`SECRETARY_SYSTEM_PROMPT` 里也不含店铺名。
★ 第 243 轮补的只读 `list_shops` **也没有解决这件事** —— 它回答的是「我有哪几家店」，
  **不含「当前是哪一家」**：「当前」由请求头 `X-Shop-ID` 决定，是**请求维度**，
  不是库里的属性。所以「注入事实」这一半仍然是必需的，不是可替代的。
⇒ 模型只能从**对话历史**里取（更早那轮的「已切换到虾皮1」+ 上一轮它自己的答案），
把历史里的旧店名当成了当前店铺。

★ 为什么是「注入事实」而不是「再给一个查询工具」
==============================================================================
查询工具是「可查」，注入是「直接告知」。本次事故的形态恰恰是**模型没有去自查**
（它连工具回执里的 `…-store_c3529ab1` 都没读懂）⇒ 补一个只读工具只是把
「给了线索、仍可能不被使用」再赌一次。所以把**已在依赖层校验过**的店铺事实
每轮渲染进 system prompt：

  · 它进 system prompt、**不进 messages** ⇒ 不受 `trim_history()` 裁剪；
  · 每轮现算（真源是库里那一行）⇒ 不会被历史里任何旧值污染；
  · 名称由**服务端按 shop_id 查库**得到 ⇒ 既不是请求体、也不是模型出参
    （同族判据：「归属只能服务端注入」）。

★ 为什么**不**住 `ai_infra/prompt_sections.py` 的注册表
==============================================================================
两个理由，任一都够：
  ① 那里 `PromptContext` 的 docstring **明写**「刻意不带店铺 / 平台 / 商品这类
     维度」，并给出正解「provider 自己去读它的上下文」——本模块就是那个上下文；
  ② 注册表是**全局**的：注册一段「当前店铺」等于给**所有** Agent 都注入，
     而「自称当前店铺」这个暴露面只有店秘书有。
（同族判据：**单 Agent 的短规则写进 prompt 更划算**，不必为此造一套机制。）
"""

from __future__ import annotations

import logging
import re
from typing import NamedTuple, Optional

from langchain_core.messages import AIMessage
from sqlalchemy import select

from core.database import async_session_factory
from core.stores import StoreRecord

logger = logging.getLogger(__name__)

__all__ = [
    "ShopBrief",
    "ShopContext",
    "SELF_REPORT_RE",
    "SELF_REPORT_LINE_RE",
    "load_shop_brief",
    "render_shop_fact",
    "render_shop_banner",
    "build_shop_fact",
    "list_other_shop_names",
    "load_other_shop_names",
    "strip_foreign_shop_names",
    "sanitize_history",
    "build_shop_context",
]


class ShopBrief(NamedTuple):
    """渲染事实段所需的店铺展示信息 —— **只有**这三项，不带任何别的业务维度。"""

    id: str
    name: str
    platform: str


class ShopContext(NamedTuple):
    """本轮「店铺上下文」= **事实** + **去污染名单**，两半装在一个包裹里。

    ★ 为什么打成包裹、不做两个并列参数：`brief`（要告诉模型什么）与
      `foreign_names`（要从历史里抹掉什么）是**同一件事的两半**。分开传就会
      出现「只传了一半」的静默半修状态 —— 只给事实 ⇒ 模型照抄历史旧店名（实测 α）；
      只抹历史 ⇒ 模型干脆不提店名（实测 γ 的 J 组）。两种都是"改完了看起来没事"。
    ★ 为什么 `foreign_names` 只装**其它**店铺名、不含当前店铺：当前店铺名出现在
      历史里是**正确**信息，抹掉它没有收益（还会让历史自相矛盾）。
    """

    brief: Optional[ShopBrief] = None
    foreign_names: tuple = ()


async def load_shop_brief(shop_id: Optional[str]) -> Optional[ShopBrief]:
    """按主键读店铺展示信息（只读，一次 PK 查询）。

    ★ **这里不做归属校验**：`shop_id` 到达本函数之前已由
      `core.tenant.middleware._resolve_current_shop_id` 校验过（不可访问先 403）。
      在这里再判一次就是「同一判定两份实现」—— 本仓铁律：至少一份永远测不到。
    ★ 查不到 ⇒ `None`，**不抛**：合法 id 的行被并发删掉时，这一轮照常对话，
      只是不注入这一段（注入是增益，不是门禁）。
    """
    sid = (shop_id or "").strip()
    if not sid:
        return None
    async with async_session_factory() as session:
        row = (
            await session.execute(select(StoreRecord).where(StoreRecord.id == sid))
        ).scalars().first()
    if row is None:
        return None
    return ShopBrief(
        id=row.id,
        name=(row.name or "").strip(),
        platform=(row.platform or "").strip(),
    )


def render_shop_fact(brief: Optional[ShopBrief]) -> str:
    """渲染「本轮店铺上下文」段（纯函数、零 IO）—— **空串 = 不注入**。

    ★ 规则与事实写在**同一段**里：只给事实不给规则，模型仍可能用历史里的旧名
      （这正是本次事故的直接形态）；而规则若单独写进 `SECRETARY_SYSTEM_PROMPT`，
      两处就会各自漂移 —— 本仓判据：同一判定两份实现 ⇒ 至少一份永远测不到。

    ★★ 规则为什么是「**正文里不要写店名**」而不是「请写对店名」：
      后者被实测证伪到底 —— 写「禁止出现旧店名」时，模型把**禁令里的旧店名**
      回显了出来；写「本轮请以『当前店铺（X）』表述」时，它写成了
      「当前店铺（**虾皮**）」—— 那个"虾皮"来自历史里**老板原话**「切换到虾皮」。
      ⇒ 模型对上下文里任何像店名的 token 都倾向回显，「指名」这件事它做不到稳定。
      于是权威店名改由服务端渲染（`render_shop_banner`），模型这边只要求**不写**。
    ★ 没有名称就返回空串：宁可**什么都不说**，也不说一句可能错的。
      「还没选店铺」这种状态由工具层（`modules/library/tools.py::_NO_SHOP_HINT`）
      去提示，本段只负责「确实有一家店」的情形。
    """
    if brief is None:
        return ""
    # ★ 逐项归一后再判「有没有内容」：只有空白的名称同样算「没有」。
    #   若只判 `not brief.name`，`ShopBrief("store_x", "   ", "amazon")` 会渲染出
    #   一段**自称权威却什么都没说**的块（「当前工作店铺：   」）—— 那正是本次
    #   事故的另一种形态：说了，但说的是空的。生产路径上 `load_shop_brief` 已
    #   strip 过，这里是**纵深防御**（本函数是公开纯函数，别的调用方也能直接构造）。
    name = (brief.name or "").strip()
    if not name:
        return ""
    return "\n".join(
        [
            "【本轮店铺上下文 · 服务端注入，权威事实】",
            f"当前工作店铺：{name}",
            f"店铺 ID：{(brief.id or '').strip()}",
            f"平台站点：{(brief.platform or '').strip() or '（未知）'}",
            "· 回复开头由服务端统一标注当前店铺名，**正文里不要再写店铺名**。",
            "· 指代本店铺时直接省略店名，例如写「各资料库的数据如下」「产品库 16 条记录」。",
            "· 尤其不要从对话历史里挑一个名字来用 —— 历史里出现过的店铺名属于**过去**。",
        ]
    )


def render_shop_banner(brief: Optional[ShopBrief]) -> str:
    """回复开头的「当前店铺」标注 —— **服务端渲染**（纯函数、零 IO、确定性）。

    ★ 为什么由服务端写、而不是让模型自称：这是第 242 轮一路实测的**唯一可行**形态
      （完整链条见本模块头注释与补丁 F 的说明）。「让 LLM 自称当前店铺」这条通道
      在措辞层面不可稳定 —— 禁它写就把名字带进上下文被回显、要它写它就乱挑一个。
      服务端渲染则完全不过模型：**切店后它必跟随**。
    ★ 空名 / 无 brief ⇒ 空串（宁可不标，也不标一个可能错的）。
    ★ 结尾两个换行：与正文之间留一个空行；不做 Markdown 加粗 —— 这是一个
      **界面标注**，不是回复的一部分，视觉上应克制、且不该被前端当正文样式处理。
    """
    if brief is None:
        return ""
    name = (brief.name or "").strip()
    if not name:
        return ""
    return f"当前店铺：{name}\n\n"


async def build_shop_fact(shop_id: Optional[str]) -> str:
    """单独取「要注入的事实段」—— 仅保留给**只关心事实**的调用方（如探针）。

    ★ 路由层请用 `build_shop_context()`：只拿事实那一半 = 静默半修（见
      `ShopContext` 的判据段）。本函数是它在事实那一半上的投影，行为等价。
    """
    try:
        return render_shop_fact(await load_shop_brief(shop_id))
    except Exception as e:  # noqa: BLE001 —— 增益失败不否决主流程，见 docstring
        logger.warning("[secretary] 店铺上下文段注入失败 shop=%r: %s", shop_id, e)
        return ""


#: 「自称当前店铺」的写法：`当前店铺（虾皮1）` / `当前店铺(虾皮1)`。
#:
#: ★★★ 这是一个**污染槽位**，不是普通句子。第 242 轮 β 探针 E 组：把历史里
#:   这个位置的旧店名换成中性占位符 `⟨历史轮次店铺⟩`，模型随后**照抄了占位符**
#:   本身（写出「当前店铺（⟨历史轮次店铺⟩）」）。⇒ 对这个槽位只能**整段删除**，
#:   不能"替换成别的词"—— 换成什么词，它就会自称什么词。
#: 收口字符只有**全角 `）`** 与换行（半角 `)` 允许出现在槽位内部）：
#: `switch_shop` 的确认文案是「已切换到「虾皮1 (Shopee MY)」店铺。」—— 括号是
#: **嵌套**的，若把半角 `)` 也当收口，就会在半角处提前截断、留下孤零零的 `）`
#: （门禁首跑实测）。排除全角 `）` ⇒ 贪婪匹配必然停在**第一个**全角右括号。
#: `{0,40}` 只是限长（防病态长串跨句），正常槽位远短于它。
SELF_REPORT_RE = re.compile(r"当前店铺[（(][^）\n]{0,40}[）)]")

#: 同一污染槽位的**冒号形态**：`当前店铺：亚马逊1`。
#:
#: ★ 它从哪来：这是**服务端自己**渲染的标注（`render_shop_banner`），会随回复落进
#:   会话历史。切店之后它就成了一条"旧名"—— 若不抹，等于每轮都在给下一轮制造
#:   新的污染源（同一个失败模式换了个形状回来）。整行删（`[^\n]*`）。
SELF_REPORT_LINE_RE = re.compile(r"当前店铺\s*[：:][^\n]*")

#: 短于该长度的店名一律不参与去污染 —— 单字店名（如「1」）会把历史里所有 `1`
#: 抹掉，那是**大范围误伤**，比留下一处旧店名更糟。宁可不抹。
_MIN_STRIPPABLE_NAME_LEN = 2


def strip_foreign_shop_names(text: str, foreign_names) -> str:
    """抹掉一段文本里的**其它店铺名**（纯函数、零 IO）。

    三条规则，**顺序不可换**：
      ① 先删掉「自称当前店铺」**整个片段** —— 它是污染槽位，**两种写法都要删**：
         `当前店铺（X）`（`SELF_REPORT_RE`）与服务端标注的 `当前店铺：X`
         （`SELF_REPORT_LINE_RE`；它会随回复落进历史，切店后就是旧名）。
         替换词会被照抄（β 探针 E 组），所以是**删**不是"换个词"；
         而且先删它，才不会把括号里的店名替换成一个半截空壳。
      ② 再删掉**含其它店名的整段引号**（`「…虾皮1 (Shopee MY)…」`）。
         ★ 这一条是被实测逼出来的：只删店名本体时，同段残留的平台后缀
         `(Shopee MY)` 会孤零零留下，而模型**能从它反推出平台、再反推回「虾皮」**
         （收口实测里它写出了「您当前店铺「虾皮 (Shopee MY)」下…」——
         既不是当前店名、也不是历史原文）。所以必须连平台后缀一起删。
         ★ 用「整段**删除**」而不是"替换成一句话"：β 探针的 E 组已证
         —— 放进去什么词，模型就可能把那个词回显出来。
      ③ 最后删残余的店名本体，**长名优先** —— `虾皮1` 是 `虾皮10` 的**前缀**，
         先替换短名会把 `虾皮10` 剁成 `0`（同族坑见 `shop_tools._switch_shop` 的
         「全字匹配优先」注释：那是"匹配"，这里是"替换"，坑是同一个）。

    ★ 为什么可以粗暴地字符串处理：抹的对象是**权威名单里的店名**，不是自然语言
      理解。不需要分词、不需要猜"哪句在说店铺"—— 名单里有、文本里出现，就抹。
    """
    valid = [n for n in (foreign_names or ()) if len(n) >= _MIN_STRIPPABLE_NAME_LEN]
    ordered = sorted(valid, key=len, reverse=True)
    t = SELF_REPORT_LINE_RE.sub("", SELF_REPORT_RE.sub("", text))
    if ordered:
        # ★ 交替式里**长名在前**：正则交替是"最左优先"，短名在前会先吃掉前缀。
        alt = "|".join(re.escape(n) for n in ordered)
        t = re.sub(r"「[^」]*(?:" + alt + r")[^」]*」", "", t)
    for name in ordered:
        t = t.replace(name, "")
    return t


def sanitize_history(messages: list, foreign_names) -> list:
    """把**发给模型的那份历史副本**里的其它店铺名抹掉（返回新列表）。

    ★ 为什么必须做这件事（第 242 轮实测，不是推断）：只注入事实（system 里
      摆着「当前工作店铺：亚马逊1」）时模型**仍然**写「当前店铺（虾皮1）」——
      α 探针三组措辞全 BAD，β 的阳性对照证明事实段确实被读了。
      真因是：历史里那条**句式完整的错误自称**是一份现成的"示范"，而 γ 的 H 组
      更狠 —— 就算删掉自称片段，模型还会从**别处**（切店确认那条）把旧店名捞回来；
      只有 I 组（历史里完全不存在旧店名）才改口。⇒ 污染源是**历史里任何位置的
      旧店名**，不是某一句话。

    ★ 为什么只动 `AIMessage`：老板原话（`HumanMessage`）里的店名是**正当引用**
      （「虾皮1 有多少产品」是历史事实），抹掉会破坏多轮语境；模型的"自称"才是
      把旧店名当成**当前**店铺的那个污染源。
    ★ 为什么返回新列表、不改原消息：`state` / checkpoint 里的历史保持原样、可审计；
      本函数只作用在"这一轮发给模型的那一份"（同 `_sanitize_tool_call_pairing` 的立场）。
    ★ 为什么不干脆删掉整条历史消息：那条消息里还有老板要看的数字，删了就丢信息。
    ★ 名单为空 ⇒ **原样返回**（同一个对象）：没绑店铺 / 账号只有一家店时零开销，
      也保证"没店铺时提示词与历史都不许有任何变化"这条既有判据继续成立。
    """
    if not foreign_names:
        return messages
    out: list = []
    for m in messages:
        if isinstance(m, AIMessage) and isinstance(m.content, str) and m.content:
            cleaned = strip_foreign_shop_names(m.content, foreign_names)
            if cleaned != m.content:
                m = m.model_copy(update={"content": cleaned})
        out.append(m)
    return out


def list_other_shop_names(shops: list, current_shop_id: Optional[str]) -> tuple:
    """从「可见店铺」字典列表里挑出**其它**店铺名（纯函数，便于门禁）。

    · 排除当前店铺（按 id）—— 它出现在历史里是对的，不该抹；
    · 去空白、跳过空名与短名（见 `_MIN_STRIPPABLE_NAME_LEN`）；
    · **去重但保序**（同一家店名重复出现只会多花时间，不影响结果；
      保序是为了让日志与用例可比）。
    """
    sid = (current_shop_id or "").strip()
    out: list = []
    for s in shops or ():
        s = s or {}
        if (s.get("id") or "").strip() == sid:
            continue
        name = (s.get("name") or "").strip()
        if len(name) < _MIN_STRIPPABLE_NAME_LEN:
            continue
        if name not in out:
            out.append(name)
    return tuple(out)


async def load_other_shop_names(shop_id: Optional[str]) -> tuple:
    """读「本账号可见的其它店铺名」—— 去污染名单的真源。

    ★ 名单必须来自 `shop_tools.list_visible_shops()`：那是「可见店铺」的**唯一**
      口径（全表 → `filter_accessible_stores` → `SHOP_ORDER_BY`）。在这里另写
      一次查询就是第二份实现，而第 239 轮刚修过"读全表把别家店铺喂给 LLM"。
    ★ 局部 import：`shop_context` ← `shop_tools` 是单向依赖，但 `shop_tools`
      引了 langchain 的 `StructuredTool`，放在模块顶部会把这条链提前到
      import 期（店秘书的两个模块本来就互相可见，这里只是避免 import 顺序变脆）。
    """
    from modules.secretary.shop_tools import list_visible_shops

    if not (shop_id or "").strip():
        return ()
    return list_other_shop_names(await list_visible_shops(), shop_id)


async def build_shop_context(shop_id: Optional[str]) -> ShopContext:
    """本轮的**唯一入口**：事实段 + 去污染名单，一次取齐（路由层只调这个）。

    ★ 两半**各自** try：任一半读库失败 ⇒ 该半退化为空，另一半照常生效，
      整体**不抛** —— 这一段是增益不是门禁（同族判据：
      `ai_infra/prompt_sections.py` 的判据 ③、`build_shop_fact` 的原注释）。
      若合并成一个 try，一次失败会把两半一起清空，且日志分不清是哪一半。
    ★ 两半分别留痕：「事实没注入」与「名单没取到」是两种不同的退化，
      排查时必须可分。
    """
    brief: Optional[ShopBrief] = None
    names: tuple = ()
    if (shop_id or "").strip():
        try:
            brief = await load_shop_brief(shop_id)
        except Exception as e:  # noqa: BLE001 —— 增益失败不否决主流程，见 docstring
            logger.warning("[secretary] 店铺事实读取失败 shop=%r: %s", shop_id, e)
        try:
            names = await load_other_shop_names(shop_id)
        except Exception as e:  # noqa: BLE001 —— 同上
            logger.warning("[secretary] 历史去污染名单读取失败 shop=%r: %s", shop_id, e)
    return ShopContext(brief=brief, foreign_names=names)

