"""`ai_infra` 层的**分层门禁**：基础设施层必须与业务无关。

本文件把「基类 / 基础设施层是否与业务无关」这件事变成可执行断言。
背景是一次真实体检发现的 4 处硬泄漏（详见交付报告 R64/R65）：

| # | 位置 | 泄漏内容 | 形态 |
|---|---|---|---|
| L1 | `base_agent.initialize_rag()` else 分支 | `KnowledgeBaseBuilder.build_customer_service_kb` | **死分支**（唯一调用点永远传 faq_items） |
| L2 | `ai_infra/rag/hybrid_engine.py` | `KnowledgeBaseBuilder` + 5 条客服 FAQ 语料 | 活代码 |
| L3 | `ai_infra/llm/dashscope_client.py` | `PROMPT_TEMPLATES` 6 份业务提示词 | **4 份被真实消费（9 个调用点）** |
| L4 | `base_agent.invoke()/stream()` + `AgentState.metadata` | 硬编码 `tenant_id` / `shop_id` | 只写不读（0 消费者） |

★ L4 的后续（R66）：`invoke()` / `stream()` **已被删除** —— 不只是收敛签名。
  全量测试带运行时 spy（全量 620 项）实测其**动态可达性 = 0**：21 处
  `agent.invoke(` 调用点的 receiver 全部在子类重写了同名方法（分派永远落子类），
  而真正继承它的 3 个 Agent（aigc / competitor / secretary）**一处调用点都没有**。
  ★ **「有调用点」≠「方法可达」**：只数调用点会得出「人人都在用」的错觉。
  留下的不是「统一入口」而是「契约地雷」：基类返回 `dict`、业务返回
  `AgentResponse`，真分派过去就 `AttributeError`。
  图驱动方的两种真实用法都直接用 `self.graph`（返回**原始 state**，不预设结构）：
    ① 继承式：secretary 的 `agent.graph.ainvoke(...)`；
    ② 组合式：listing / product_research 各自 new 一个裸 BaseAgent 当 router 子层
       （`metadata={"role": "sub_agent_router"}`）后 `_router.graph.ainvoke`。
  两条用法都需要原始 messages 流自行组装业务响应 —— 而 `invoke()` 恰好把它换成
  `structured_response`，拿走的正是唯一需要的东西。

★ 判据要点（本文件为什么这么写）
  ① **反向 import 是硬红线**，但只查它远远不够（L1~L4 都不违反它）。
  ② 查业务词必须**剥注释与 docstring** 再统计，否则会把讲解性文字判成泄漏；
     但剥完之后**必须区分「标识符」和「字符串字面量」** —— L3 恰恰只存在于字符串里，
     第一版探针只查标识符，于是完全漏掉了它。
  ③ 「只写不读」的结构（L4）是**死重量**不是耦合，判泄漏前先数消费者。
  ④ 本文件自带反向注入自检：`test_layering_gate_is_not_vacuous` 会当场构造
     一个违规样本喂给扫描函数，证明门禁真的会报警（防「门禁写了但恒绿」）。
"""

import ast
import re
import pathlib

import pytest

BACKEND = pathlib.Path(__file__).resolve().parents[1]
AI_INFRA = BACKEND / "ai_infra"

# 业务模块名（反向依赖检测用）
BUSINESS_MODULES = [
    "ad_analysis", "aigc_media", "competitor_intel", "customer_service",
    "listing_generator", "product_research", "review_analyst", "amazon_sp",
    "platform_rules", "secretary", "stores", "products", "candidates",
    "assets", "conversation", "knowledge_base", "monitors", "voice_clone",
    "billing", "auth",
]

# 业务词（字符串字面量扫描用）—— 保守取值，只放本仓真实出现过的业务概念
BUSINESS_WORDS = [
    "shop_id", "shopee", "amazon", "asin", "listing", "Listing",
    "ACoS", "TACoS", "PPC", "客服", "选品", "竞品", "广告",
    "店铺", "跨境", "电商", "退货", "关税", "积分", "发货",
]


def _infra_files():
    return sorted(AI_INFRA.rglob("*.py"))


def _docstring_node_ids(tree: ast.AST) -> set:
    """收集所有 docstring 对应的 Constant 节点 id（这些不算「业务字符串」）。"""
    ids = set()
    for n in ast.walk(tree):
        if isinstance(n, (ast.Module, ast.ClassDef, ast.FunctionDef, ast.AsyncFunctionDef)):
            body = getattr(n, "body", None)
            if body and isinstance(body[0], ast.Expr) and isinstance(body[0].value, ast.Constant) \
               and isinstance(body[0].value.value, str):
                ids.add(id(body[0].value))
    return ids


def scan_reverse_imports(source: str):
    """返回 `from modules...` / `import modules...` 的模块名列表。"""
    pat = re.compile(r"^\s*(?:from|import)\s+(modules[\w\.]*|\.\.modules[\w\.]*)", re.M)
    return [m.group(1) for m in pat.finditer(source)]


def scan_business_identifiers(source: str, words=BUSINESS_MODULES):
    """扫描**代码级**标识符（Name / Attribute / Import）里的业务名。

    注意 `words` 用模块名，与字符串扫描分开调用 —— 两类泄漏的判据不同。
    """
    hits = []
    tree = ast.parse(source)
    wanted = set(words)
    for n in ast.walk(tree):
        if isinstance(n, ast.Name) and n.id in wanted:
            hits.append((n.id, n.lineno))
        elif isinstance(n, ast.Attribute) and n.attr in wanted:
            hits.append((n.attr, n.lineno))
        elif isinstance(n, (ast.Import, ast.ImportFrom)):
            for a in n.names:
                if (a.name or "").split(".")[0] in wanted:
                    hits.append((a.name, n.lineno))
    return hits


def scan_business_strings(source: str, words=BUSINESS_WORDS):
    """扫描**非 docstring 的字符串字面量**里的业务词。

    ★ 这一层是第一版探针的盲区：`PROMPT_TEMPLATES` 的业务内容全在字符串里，
      既不会报错、也不出现在任何标识符中。
    """
    hits = []
    tree = ast.parse(source)
    skip = _docstring_node_ids(tree)
    for n in ast.walk(tree):
        if isinstance(n, ast.Constant) and isinstance(n.value, str) and id(n) not in skip:
            for w in words:
                if w in n.value:
                    hits.append((w, n.lineno, n.value[:60].replace("\n", " ")))
    return hits


# ---------------------------------------------------------------- 1. 反向依赖

def test_ai_infra_does_not_import_business_modules():
    """基础设施层不得反向 import 业务模块（分层的硬红线）。"""
    bad = []
    for f in _infra_files():
        for mod in scan_reverse_imports(f.read_text(encoding="utf-8")):
            bad.append(f"{f.relative_to(BACKEND)} -> {mod}")
    assert not bad, f"ai_infra 出现反向依赖: {bad}"


# ------------------------------------------------- 2. 标识符层面零业务名

def test_ai_infra_identifiers_have_no_business_names():
    """代码级标识符里不得出现业务模块名。"""
    bad = []
    for f in _infra_files():
        hits = scan_business_identifiers(f.read_text(encoding="utf-8"))
        if hits:
            bad.append(f"{f.relative_to(BACKEND)}: {hits[:6]}")
    assert not bad, f"ai_infra 标识符层业务泄漏: {bad}"


# --------------------------------------- 3. 字符串字面量层面零业务内容（L3）

def test_ai_infra_string_literals_have_no_business_content():
    """★ 非 docstring 的字符串里不得出现业务内容。

    这条钉住的正是 `PROMPT_TEMPLATES` 那类泄漏：**只存在于字符串里**的
    业务语义（选品/Listing/广告/客服/竞品/AIGC 提示词，以及客服 FAQ 语料）。
    """
    bad = []
    for f in _infra_files():
        hits = scan_business_strings(f.read_text(encoding="utf-8"))
        if hits:
            bad.append(f"{f.relative_to(BACKEND)}: {hits[:6]}")
    assert not bad, (
        f"ai_infra 字符串层仍有业务内容（业务语料/提示词应归 modules/*）：{bad}"
    )


# ------------------------------------------ 4. 基类签名无业务形参（L4）

def test_base_agent_public_signature_has_no_business_params():
    """`BaseAgent` 公开方法签名不得夹带业务维度（原 `tenant_id` / `shop_id`）。"""
    src = (AI_INFRA / "base_agent.py").read_text(encoding="utf-8")
    tree = ast.parse(src)
    forbidden = {"shop_id", "tenant_id", "platform", "asin", "listing_id"}
    offenders = []
    for n in ast.walk(tree):
        if isinstance(n, (ast.FunctionDef, ast.AsyncFunctionDef)):
            args = list(n.args.args) + list(n.args.kwonlyargs) + list(n.args.posonlyargs)
            for a in args:
                if a.arg in forbidden:
                    offenders.append((n.name, a.arg, a.lineno))
    assert not offenders, (
        f"BaseAgent 签名夹带业务参数: {offenders} —— 应改为 `metadata={{\"...\": ...}}` 自由字典"
    )


def test_agent_state_metadata_is_free_form_dict():
    """`AgentState.metadata` 应是自由字典，不预置业务键。"""
    src = (AI_INFRA / "base_agent.py").read_text(encoding="utf-8")
    tree = ast.parse(src)
    node = None
    for n in ast.walk(tree):
        if isinstance(n, ast.ClassDef) and n.name == "AgentState":
            node = n
    assert node is not None, "未找到 AgentState"
    md = None
    for n in node.body:
        if isinstance(n, ast.AnnAssign) and getattr(n.target, "id", "") == "metadata":
            md = n
    assert md is not None, "AgentState 没有 metadata 字段"
    assert isinstance(md.value, ast.Dict) and not md.value.keys, (
        "AgentState.metadata 应默认空字典（原先硬编码了 tenant_id/shop_id/"
        "token_usage/cost_estimate 四个业务/死键）"
    )


# ---------------------- 4b. 基类不得暴露与业务契约冲突的调用入口

def scan_public_methods(source: str, cls_name: str):
    """返回类体内**直接定义**的方法名集合（含 property / staticmethod）。

    只扫类体第一层，不递归内部类 —— 与 `type(BaseAgent).__dict__` 语义一致。
    """
    tree = ast.parse(source)
    for n in ast.walk(tree):
        if isinstance(n, ast.ClassDef) and n.name == cls_name:
            return {m.name for m in n.body
                    if isinstance(m, (ast.FunctionDef, ast.AsyncFunctionDef))}
    return set()


def test_base_agent_exposes_no_conflicting_entry():
    """★ 基类不得再长出 `invoke` / `stream`（防回流）。

    背景：「基类提供统一调用入口」这个想法在本仓**从未成立**。业务 Agent 的入口是
    `invoke(query, context=None) -> AgentResponse`（Pydantic），而基类曾提供的
    `invoke(query, context_id, metadata) -> dict` 是**另一套契约**：
      · 同名 ⇒ 子类遮蔽，基类实现永远不执行（动态可达性 = 0）；
      · 契约不同 ⇒ 一旦真分派过去，调用方把 `dict` 当 `AgentResponse` 用，
        `response.content` 直接 `AttributeError`。
    「没人调」比「调了炸」安全，但那份安全是巧合 ⇒ 删掉并防回流。
    需要图驱动的一方请直接用 `self.graph`（不预设返回结构）。
    """
    src = (AI_INFRA / "base_agent.py").read_text(encoding="utf-8")
    methods = scan_public_methods(src, "BaseAgent")
    offenders = sorted(methods & {"invoke", "stream", "stream_chat"})
    assert not offenders, (
        f"BaseAgent 又出现了统一入口 {offenders}：它与业务契约（AgentResponse）冲突，"
        f"会产生同名遮蔽 + 静默 AttributeError。图驱动请直接用 `self.graph`。"
    )


# ------------------------------- 5. 提示词机制在 infra、内容在业务模块（L3）

def test_prompt_registry_lives_in_infra_but_is_empty_by_default():
    """注册表是基础设施能力，但**默认必须为空**（内容在业务模块）。"""
    from ai_infra.llm import PROMPT_TEMPLATES, register_prompt_template  # noqa: F401
    from ai_infra.llm import dashscope_client as ds

    # 模块级定义处必须是空字典（不受其它测试 import 业务模块后的运行时状态影响）
    tree = ast.parse(pathlib.Path(ds.__file__).read_text(encoding="utf-8"))
    for n in tree.body:
        if isinstance(n, ast.AnnAssign) and getattr(n.target, "id", "") == "PROMPT_TEMPLATES":
            assert isinstance(n.value, ast.Dict) and not n.value.keys, (
                "PROMPT_TEMPLATES 在 ai_infra 里不得预置内容"
            )
            break
    else:
        pytest.fail("dashscope_client 里没有 PROMPT_TEMPLATES 定义")


def test_business_prompts_are_owned_by_business_modules():
    """6 份业务提示词必须由各业务模块各自持有并注册。"""
    import importlib

    from ai_infra.llm import get_prompt_template

    keys = ["product_research", "listing_generator", "ad_analysis",
            "customer_service", "competitor_intel", "aigc_media"]
    for k in keys:
        importlib.import_module(f"modules.{k}.prompts")
        got = get_prompt_template(k)
        assert got and len(got) > 50, f"{k}: 提示词为空或过短"
        assert (BACKEND / "modules" / k / "prompts.py").exists()


def test_get_prompt_template_raises_on_unregistered():
    """★ 缺键必须显式报错，不得静默返回空串。

    返回空串 ⇒ 拿着空 system prompt 请求 LLM ⇒ 不报错不降级，属静默失效。
    """
    from ai_infra.base_agent import BaseAgent
    from ai_infra.llm import get_prompt_template

    with pytest.raises(KeyError):
        get_prompt_template("__definitely_not_registered__")

    agent = BaseAgent(agent_name="tpl-gate-probe")
    with pytest.raises(KeyError):
        agent.get_prompt_template("__definitely_not_registered__")


# ------------------------------------------ 6. 门禁自身有效性自检（防恒绿）

def test_layering_gate_is_not_vacuous():
    """★ 反向注入自检：故意造违规样本，扫描函数必须报出来。

    没有这一条，「门禁」可能因为正则写错而恒绿 —— 那就是又一个假门禁。
    """
    # ① 反向 import
    assert scan_reverse_imports("from modules.secretary import agent\n") == ["modules.secretary"]

    # ② 标识符（Attribute 形态：KnowledgeBaseBuilder 就是被这样引用的）
    assert scan_business_identifiers("x = modules.secretary.agent\n")

    # ③ 字符串字面量（PROMPT_TEMPLATES 的真实形态）
    fake = 'PROMPT_TEMPLATES = {"k": "你是 Amazon Listing 优化专家"}\n'
    assert scan_business_strings(fake), "字符串扫描漏报"

    # ④ docstring 里的业务词**不应**被算作泄漏（否则会误伤说明性文字）
    doc_only = '"""说明：曾是 KnowledgeBaseBuilder，含 shop_id。"""\nx = 1\n'
    assert not scan_business_strings(doc_only), "docstring 被误判为泄漏"

    # ⑤ 干净样本不应误报
    clean = 'from typing import Dict\nPROMPT_TEMPLATES: Dict[str, str] = {}\n'
    assert not scan_business_strings(clean)
    assert not scan_reverse_imports(clean)

    # ⑥ 类方法扫描（防「基类又长出 invoke」那条门禁恒绿）
    fake_cls = 'class BaseAgent:\n    async def invoke(self):\n        pass\n'
    assert 'invoke' in scan_public_methods(fake_cls, 'BaseAgent'), "类方法扫描漏报"
    assert scan_public_methods('class Other:\n    pass\n', 'BaseAgent') == set()
