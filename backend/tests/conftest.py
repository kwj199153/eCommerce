"""
pytest 公共夹具

约定：
- 所有测试针对真实本地 PostgreSQL（tests 会创建并清理自己的临时用户）
- 需要鉴权的用例用 `auth_on` 夹具打开生产模式开关
- 不发起真实 LLM 请求：由下方的 `_no_real_llm` 自动夹具**强制兜底**，见其注释
"""

import uuid

import httpx
import pytest
import pytest_asyncio
from httpx import ASGITransport

from core.config import config


# ====== 真实 LLM 出网总闸（autouse） ======
#
# 背景（实测）：本后端存在**两套彼此独立的 LLM 栈**——
#   栈 A：`ai_infra.base_agent.BaseAgent._llm_with_tools()` → LangChain `ChatOpenAI`
#         （走 OpenAI 兼容端点，工具路由/多轮 ReAct 用）
#   栈 B：`ai_infra.base_agent.BaseAgent.llm_stream/llm_chat()`
#         → `ai_infra.llm.dashscope_client.DashScopeLLM`（原生 httpx 流式，正文生成用）
#         （两栈现已同属唯一基类 BaseAgent：原 LLMEnabledAgent 已并入）
#
# 原先的 `fake_llm` 夹具**只补丁了栈 B 的 `DashScopeLLM.chat`**，于是：
#   - 栈 A 从未被拦截 → 真实调用 DashScope
#   - 栈 B 的 `chat_stream` 也没被补丁（只补了 `chat`）→ 真实流式调用
# 后果：大量「看起来已打桩」的用例实际在打真实 API，单个用例耗时 10~36s，
# 全量 488 项要 6 分 33 秒，且**结果依赖网络/额度/限流，不稳定**（同输入耗时 16.8s~36s 波动）。
#
# 修复思路：不去逐个补丁具体实现（新增一条调用路径就会漏），
# 而是在**网络出口**兜底——把 `httpx` 指向未配置的主机，任何真实出网都会
# 立刻 `ConnectError` 并走各 Agent 既有的降级分支（不再静默等待数十秒）。
# 这样新增 LLM 栈/新增端点也不会再悄悄打真 API。
#
# 需要真实 LLM 的用例（如 tests/test_llm_rag_integration.py）请显式声明
# `@pytest.mark.allow_real_llm` 放行。

_DASHSCOPE_HOST_MARKERS = ("dashscope.aliyuncs.com", "aliyuncs.com")


@pytest.fixture(autouse=True)
def _no_real_llm(request, monkeypatch):
    """
    自动夹具：默认阻断一切真实 LLM 出网（除非用例标记 allow_real_llm）。

    不改变业务代码：仅在做网络调用时抛 ConnectError，让 Agent 走既有降级分支。
    """
    if request.node.get_closest_marker("allow_real_llm"):
        yield
        return

    import httpx as _httpx

    real_send = _httpx.AsyncClient.send

    async def guarded_send(self, request, *args, **kwargs):
        url = str(getattr(request, "url", ""))
        if any(m in url for m in _DASHSCOPE_HOST_MARKERS):
            raise _httpx.ConnectError(
                "测试环境禁止真实 LLM 出网（conftest._no_real_llm）。"
                "如需真实调用请加 @pytest.mark.allow_real_llm",
                request=request,
            )
        return await real_send(self, request, *args, **kwargs)

    monkeypatch.setattr(_httpx.AsyncClient, "send", guarded_send)

    # 栈 A 走 LangChain `ChatOpenAI`，它有**自己的** httpx 客户端与传输层，
    # 上面的 `AsyncClient.send` 拦不到（实测：`/listing/chat` 仍耗时 9.5s）。
    # 这里直接把 BaseAgent 取 LLM 的入口换成离线桩，从源头断掉出网。
    #
    # ⚠️ 桩必须**照常上报 `usage_metadata`**。原因：
    # `/listing/chat` 这类端点的正文完全由本栈产出，真实 `ChatOpenAI` 会在
    # `AIMessage.usage_metadata` 里带回 token 数，`BaseAgent._llm_call_node`
    # 读到后经 `record_llm_usage` 落到订阅表。桩只需**如实上报 token 数**，
    # **不要自己记账** —— 那会与节点记账双计。
    from langchain_core.messages import AIMessage

    from ai_infra import base_agent as _ba

    _STUB_TEXT = "[测试桩] LLM 已离线，本响应由桩生成。"

    def _stub_message() -> AIMessage:
        # 只上报 token，**不记账**：记账由 `BaseAgent._llm_call_node` 统一负责。
        # （改造前该节点没有记账逻辑，桩是临时替代品；两者并存会双计。）
        input_tokens, output_tokens = 120, 80
        return AIMessage(
            content=_STUB_TEXT,
            usage_metadata={
                "input_tokens": input_tokens,
                "output_tokens": output_tokens,
                "total_tokens": input_tokens + output_tokens,
            },
        )

    class _OfflineChat:
        """离线桩：不打网络，回固定文本并上报用量。"""

        def bind_tools(self, tools, **kwargs):
            return self

        async def ainvoke(self, messages, **kwargs):
            return _stub_message()

        async def astream(self, messages, **kwargs):
            yield _stub_message()

        def stream(self, messages, **kwargs):
            yield _stub_message()

        def invoke(self, messages, **kwargs):
            return _stub_message()

    # ★ 第 238 轮：两个桩必须容忍**额外参数** —— `_llm_with_tools(model=...)`
    #   是新的调用形态（第一轮走更快的备用模型）。零参 lambda 会让所有秘书
    #   链路用例在 TypeError 上崩，而那不是"判据红了"，是底座坏了。
    monkeypatch.setattr(
        _ba.BaseAgent, "_get_default_llm",
        lambda self, *a, **kw: _OfflineChat(), raising=False,
    )
    monkeypatch.setattr(
        _ba.BaseAgent, "_llm_with_tools",
        lambda self, *a, **kw: _OfflineChat(), raising=False,
    )

    # 栈 B：`BaseAgent.llm_chat/llm_stream` → `DashScopeLLM.chat/chat_stream`。
    # 这里补丁**最底层的客户端方法**（而不是上层 wrapper），好处：
    #   1. `llm_chat` 的返回组装、`_update_stats` 的**计量上报**全都保持真实，
    #      `test_billing_metering` 的「LLM token/成本落库」断言依然有效；
    #   2. 新增调用路径只要最终落到 `DashScopeLLM` 就自动被拦住。
    # 注意必须**同时**补丁 `chat_stream`——原 `fake_llm` 只补了 `chat`，
    # 这是流式用例仍在打真 API 的原因之一。
    from ai_infra.llm import dashscope_client as _dc

    def _stub_response(self, *args, **kwargs):
        return _dc.LLMResponse(
            content="[测试桩] LLM 已离线，本响应由桩生成。",
            model="qwen-max",
            input_tokens=120,
            output_tokens=80,
            total_tokens=200,
            cost=0.0036,
            latency_ms=1,
            finish_reason="stop",
            raw_response={},
        )

    async def _stub_chat(self, messages, system_prompt=None, **kwargs):
        resp = _stub_response(self, messages, system_prompt, **kwargs)
        # 走真实统计/计量钩子，确保「LLM 消耗 → 计费」链路仍被覆盖
        self._update_stats(resp)
        return resp

    async def _stub_chat_stream(self, messages, system_prompt=None, **kwargs):
        for chunk in ("[测试桩] ", "LLM 已离线。"):
            yield chunk
        resp = _stub_response(self, messages, system_prompt, **kwargs)
        self._update_stats(resp)

    monkeypatch.setattr(_dc.DashScopeLLM, "chat", _stub_chat, raising=False)
    monkeypatch.setattr(_dc.DashScopeLLM, "chat_stream", _stub_chat_stream, raising=False)

    yield


# ====== 真实网络子进程兜底（autouse） ======
#
# ★ 为什么 `_no_real_llm` 之外还要这一层：它拦的是 **httpx**。
#   而「出网」不止 HTTP —— `subprocess` 起 `ssh`/`scp` 同样会真连出去，
#   且**完全不在 httpx 的覆盖范围**（这是全仓唯一的裸奔出网面）。
#
# 实测事故（第 243 轮）：全量回归「卡在收尾」十几分钟，DB 锁/慢查询/夹具查了一圈
# 都不是；真因是某条用例漏挂隔离夹具 ⇒ `mirror.check_connectivity()` 真起
# `ssh root@<生产服务器> "echo ok"`（开发机 `.env` 真配了 host + 私钥）。
# 更隐蔽的是：`subprocess.run` 是**同步**调用却被写在 `async def` 端点里
# ⇒ 阻塞整个事件循环（本仓 loop scope = session）⇒ 进度条冻结，
# 看起来像「某个用例卡住」，实际在等 socket 超时。
#
# 兜底分两层：
#   ① `mirror.is_enabled()` 置 False —— voice_clone 链路**默认不碰 ssh**
#      （测试必须自带环境，不依赖开发机 .env）。需要真启用的用例可自行
#      `monkeypatch.setattr(mirror, "is_enabled", lambda: True)` 覆盖它。
#   ② 拦 `subprocess.Popen` 里的**网络类命令** —— 结构性堵死 future 新增的出网面。
#      ★ 只拦网络类，**不能**拦掉全部 subprocess：套件里有多处
#      `subprocess.run([sys.executable, ...])` 用来跑门禁 / 迁移 / 子探针
#      （见 `test_ci_gate_coverage` / `test_schema_parity` / `test_skill_injection`）。

#: 视为「网络类」的命令名（按 argv[0] 的 basename 比对）。刻意**不含** python/node/npm。
_NETWORK_SUBPROCESS_BINARIES = frozenset({
    "ssh", "scp", "sftp", "sshpass", "ssh-keygen", "ssh-copy-id",
    "curl", "wget", "rsync", "git", "telnet", "ftp", "ncat", "nc",
})


def _network_binary_of(argv):
    """从 argv 里取出「网络类命令名」；非网络类（或无 argv）返回 None。"""
    if isinstance(argv, (str, bytes)):
        return None  # shell 字符串形态不解析：本仓的出网面都走 list 形态
    try:
        first = str(argv[0])
    except (TypeError, IndexError, KeyError):
        return None
    name = first.replace("\\", "/").rsplit("/", 1)[-1].lower()
    if name.endswith(".exe"):
        name = name[:-4]
    return name if name in _NETWORK_SUBPROCESS_BINARIES else None


@pytest.fixture(autouse=True)
def _no_real_network_subprocess(request, monkeypatch):
    """自动夹具：阻断一切真实**网络类子进程**（ssh/scp/curl/git…）。

    不改业务代码：命中时抛 `FileNotFoundError`（与「本机没装 ssh」同形态），
    业务侧既有的降级分支照常生效（`mirror` 就把它翻成可展示的失败原因）。
    需要真实网络子进程的用例请加 `@pytest.mark.allow_real_network_subprocess`。
    """
    # ① 镜像默认关闭（测试自带环境，不依赖开发机 .env）
    from modules.voice_clone import mirror as _mirror

    monkeypatch.setattr(_mirror, "is_enabled", lambda: False, raising=False)
    _mirror.reset_connectivity_cache()  # 防上一用例把 enabled=True 的结论缓存下来

    if request.node.get_closest_marker("allow_real_network_subprocess"):
        yield
        return

    # ② 结构性兜底：拦 subprocess 的网络类命令
    import subprocess as _sp

    real_popen = _sp.Popen

    def guarded_popen(*args, **kwargs):
        argv = args[0] if args else kwargs.get("args")
        name = _network_binary_of(argv)
        if name is not None:
            raise FileNotFoundError(
                2,
                "测试环境禁止真实网络子进程（conftest._no_real_network_subprocess）。"
                "如需真实调用请加 @pytest.mark.allow_real_network_subprocess",
                name,
            )
        return real_popen(*args, **kwargs)

    monkeypatch.setattr(_sp, "Popen", guarded_popen)
    yield


# ====== 技能图标生成桩（autouse） ======
#
# ★ 为什么 `_no_real_llm` 已经拦了出网，这里还要再换一次生成器：
#   它拦的是**网络出口**，而 `DashScopeLLM` 自带
#   `RetryPolicy(attempts=3, base=1s, ×2)` —— ConnectError 会被重试到
#   **约 3 秒**才放弃。一次 `POST /skills` 就白等 3 秒，
#   `seed` 的 10 条技能要 30 秒。在**生成器**这一层替换，把这笔等待压到 0。
#
# ★ 桩必须**确定性**：同一个标题永远给同一个 emoji。
#   否则「保存后图标是什么」就成了不可断言的量，测试只能写成"非空即可" ——
#   而那恰好抓不住"所有技能拿到同一个图标"这种真实缺陷。
#
# ★ 覆盖面没有丢：图标机制里真正有逻辑的部分是 `extract_emoji`
#   （LLM 回一整句「这个技能的图标是：📉」时怎么摘出 emoji），
#   它由 `tests/test_skill_icon.py` 直接穷举，**不经过这个桩**。

#: 桩用的图标池（顺序即索引，改动会让既有断言移位 —— 有测试钉住池长度）
STUB_ICON_POOL = ("📉", "🎯", "💬", "📣", "🖼", "🎧", "🧭", "✅", "📊", "🔀")


@pytest.fixture(autouse=True)
def _deterministic_skill_icon():
    """把技能图标生成换成确定性桩（零网络、零等待）。"""
    from modules.skills import icon as _icon

    async def _stub(title: str, description: str):
        key = (title or "").strip() or (description or "").strip()
        if not key:
            # 标题与描述都空 ⇒ 无素材可依据，返回 None（与真实实现同语义）
            return None
        return STUB_ICON_POOL[sum(ord(c) for c in key) % len(STUB_ICON_POOL)]

    _icon.set_icon_generator(_stub)
    yield
    _icon.set_icon_generator(None)


# ====== 生产环境 Settings 合规基线（唯一来源） ======
#
# ★ 为什么必须有这一份（这已经是**第三次**被同一件事咬）：
#   `core/config.py::Settings._enforce_production_safety` 每加一条护栏，
#   所有「构造 production Settings 并期望它成功」的用例都会开始报错 ——
#   而且报错信息指向**新护栏**，看起来像是"护栏写错了"，实则只是基线没跟上。
#   历史：P1-d 的 METRICS_TOKEN 加进来时，仓里**两处**独立构造点
#   （test_auth_and_tenant / test_billing_payment）就各自补了一遍合规值，
#   并在注释里登记"应收敛成 conftest 里的唯一 helper"。
#   P1-b 的邮件通道 + 锁定阈值护栏加进来后，同样的问题又发生了。
#   ⇒ 现在收敛成这一个 fixture，新护栏只在**这一处**补合规值。
#
# ★ 为什么用 **fixture** 而不是普通函数：
#   普通函数放 conftest 里需要跨文件 `import conftest` / `import tests.conftest`
#   —— 本仓有 `backend/conftest.py` 与 `backend/tests/conftest.py` 两个同名
#   conftest（且 tests/ 无 `__init__.py`），模块名解析依赖 pytest 的 import 模式，
#   还会把 conftest 执行第二遍。fixture 由 pytest 自动注入到所有测试模块，
#   零 import、零歧义。
#
# 用法：`Settings(**prod_settings_kwargs())` 正向；反向传 overrides 破坏某一项。

@pytest.fixture
def prod_settings_kwargs():
    """返回「生产环境合规 Settings 入参」工厂；overrides 用于定向破坏某一项。"""

    def _make(**overrides) -> dict:
        base = dict(
            _env_file=None,             # 隔离 backend/.env，避免外部取值干扰
            environment="production",
            auth_required=True,
            jwt_secret_key="a-very-strong-random-secret-9f2c8e1b7d4a6035",
            debug=False,
            # 支付：既非 mock 也非「未接入清单」，用于证明护栏不过宽
            payment_gateway="internal",
            # P1-d（2026-09-16）：/metrics 开启 ⇒ 必须给令牌
            metrics_enabled=True,
            metrics_token="metrics-token-for-pytest",
            # 口令哈希：生产要求 >= 12
            password_hash_rounds=12,
            # ★ P1-b（2026-09-16）：邮件通道。
            #   基线取**真发信那一档且必填项齐全** —— 这样「console 在
            #   生产非法」这条反向用例是靠 overrides 打出的差异，
            #   而不是靠默认值碰巧命中。
            email_provider="aliyun_dm",
            aliyun_dm_access_key_id="pytest-ak",
            aliyun_dm_access_key_secret="pytest-secret",
            aliyun_dm_account_name="noreply@example.com",
            public_site_url="https://app.example.com",
            # ★ P1-b：锁定阈值（生产须 >=3 / >=5）
            login_max_failures=5,
            login_lockout_minutes=15,
            # ★ P0-4（2026-09-30）：生产合规基线现在**必须**含强口令 database_url。
            #   原先这里没有这一项，靠 Settings 字段默认值兜底 —— 而那个默认值
            #   恰好是「生产环境用默认弱口令」这个真实事故形态（弱口令检查上线后，
            #   本文件两条**正向**用例立刻被打红，已实测确认）。显式写出，
            #   让「合规」在 fixture 里一眼可见，而不是靠字段默认值碰巧成立。
            database_url="postgresql+asyncpg://kevin:zzz-placeholder-pw@db.internal:5432/storekeeper",
        )
        base.update(overrides)
        return base

    return _make


# ====== 鉴权开关 ======

@pytest.fixture
def auth_on():
    """打开生产模式鉴权（要求 Bearer Token）"""
    prev = config.auth_required
    config.auth_required = True
    yield
    config.auth_required = prev


@pytest.fixture
def auth_off():
    """演示模式（匿名放行）"""
    prev = config.auth_required
    config.auth_required = False
    yield
    config.auth_required = prev


# ====== 演示哨兵开关（★ 第 182 轮由 test_auth_optional_semantics.py 提升到此处） ======

# ★ 为什么提到 conftest：第 182 轮起至少三个模块需要它
#   （`test_auth_optional_semantics` / `test_skill_gate` / `test_demo_identity`）。
#   留在某个测试文件里会让其余两个各抄一份 —— 本仓判据：
#   同一判定两份实现 ⇒ 至少一份永远测不到（而"抄错一个"的症状是
#   **演示模式相关用例静默变成真匿名用例**，照样绿）。


@pytest.fixture
def demo_on():
    """显式打开演示哨兵（不依赖 .env，避免测试结论随外部配置漂移）

    ★ 必须显式打开而不是"读 .env 默认值"：`.env` 里 `DEMO_MODE=true` 是
      **本机**的形态。若用例依赖它，那么在 CI（未配该变量 ⇒ 默认 false）上
      这些用例会全部退化成"真匿名"场景并**依然通过** —— 测的东西变了而灯是绿的。
    """
    from core.config import config

    prev = config.demo_mode
    config.demo_mode = True
    yield
    config.demo_mode = prev


@pytest.fixture
def demo_off():
    from core.config import config

    prev = config.demo_mode
    config.demo_mode = False
    yield
    config.demo_mode = prev


# ====== 技能实验场（★ 第 188 轮由 test_skill_gate.py 提升到此处） ======

# ★ 为什么提到 conftest：第 188 轮起 `test_skill_icon.py` 也需要它。
#   而它的清理逻辑**不是随手写的**（见下面 docstring 里的 SET NULL 坑），
#   复制一份出去等于埋一个"改一处漏一处"的隐患。
#   与 `demo_on`/`demo_off` 第 182 轮的提升同判据。


@pytest_asyncio.fixture
async def skill_owner(make_user):
    """一个真实用户的技能实验场；结束时把它建的技能连同版本历史删干净。

    ★ 为什么必须显式清 `skills`：`skills.owner_id` 的外键是 **SET NULL**
      （不是 CASCADE），所以 `_purge_users` 删掉用户之后，技能行会**留下来**
      并继续占着那个全局唯一的 `name` —— 同名技能从此再也建不出来，
      而报错指向「名字重复」（错误方向）。这正是 `service.create_skill`
      docstring 里"宁可当场拒绝无主技能"的同一条理由。

    ★ 前缀 `sk-` 是**清理锚点**（`DELETE ... WHERE name LIKE 'sk-%'`），
      不是给人看的标识 —— 用例一律用 `skill_owner["prefix"] + "-xxx"` 拼名字。
    """
    from sqlalchemy import text

    from core.database import async_session_factory

    info = await make_user("skillowner")
    prefix = "sk-" + uuid.uuid4().hex[:8]
    yield {"user_id": info["user_id"], "headers": info["headers"], "prefix": prefix}

    async with async_session_factory() as db:
        await db.execute(
            text("DELETE FROM skills WHERE name LIKE :p"), {"p": prefix + "%"}
        )
        await db.commit()


# ====== HTTP 客户端 ======

@pytest_asyncio.fixture
async def client(request, tenant_headers):
    """
    基于 ASGI 的内存 HTTP 客户端（不经过网络）。

    ★★★ 第 177 轮：带 `tenant_identity` 标记的模块，请求**默认带夹具租户身份**。

      为什么需要它：`user is None`（演示 / 匿名身份）的归属判定已收紧为
      「只放行 `is_demo` 店铺」，于是「匿名 + 合成 shop_id」这条老通道不再成立
      —— 而合成店铺的归属者现在就是夹具租户（见 `_ensure_tenant_fixture`）。
      这些模块测的是**业务逻辑**，本就不该顺带依赖「演示档放行」那条旁路；
      带上身份后它们与生产档（`AUTH_REQUIRED=true`）走同一条代码路径。

      ★ 不标记的模块**完全不受影响**：`test_demo_store.py` /
      `test_auth_optional_semantics.py` / `test_shop_id_guard.py` 里那些
      「匿名 ⇒ 看不到真实店铺」的判据仍然按**真匿名**发请求。
    """
    from main import app

    headers = {}
    if request.node.get_closest_marker("tenant_identity"):
        headers = dict(tenant_headers)

    async with httpx.AsyncClient(
        transport=ASGITransport(app=app), base_url="http://test", headers=headers
    ) as c:
        yield c


# ====== 测试进程内的口令哈希降轮（提速，不影响生产） ======

@pytest.fixture(scope="session", autouse=True)
def _fast_password_hash_rounds():
    """
    把本测试进程的 bcrypt 轮数降到 4（会话级、自动生效）。

    ★ 为什么必须做这件事（实测，别再当成「优化」删掉）：
      bcrypt rounds=12 单次 hash ≈209ms、verify ≈207ms。而 `user` / `job_user`
      夹具是 **function 级**的，每条用例都要真跑一次 register(1 hash) +
      login(1 verify) ⇒ 每例固定白花 **≈416ms**。
      全量 627 项里 25 项依赖该夹具 ⇒ 合计 17.73s，其中 bcrypt 占 ≈10.4s。

    ★ 为什么这是安全的：
      套件里**没有任何用例**在验证「哈希够不够慢」—— 那属于部署参数，
      由 `Settings.password_hash_rounds`（默认 12）+ 生产启动护栏负责。
      测试要验证的是「注册/登录逻辑是否正确」，而不是 bcrypt 的迭代次数。
      实测 rounds=4 时单次 verify ≈0.8ms，语义完全不变（同为 $2b$ 格式、
      互验通过，见 test_auth_and_tenant 的轮数守护用例）。

    ★ 为什么写成「改运行时属性」而不是写进 .env：
      `backend/.env` 同时被 uvicorn 开发服务读取，写进去会连带把**开发环境**
      的注册哈希也降弱。只改本进程，爆炸半径最小。

    ★ 反向保护：`test_password_hash_rounds_default_stays_production_grade`
      直接检查字段默认值仍 >= 12 —— 防止有人把**默认值**也改小
      （那样测试会照常全绿，生产却静默变弱）。
    """
    from core.config import config

    prev = config.password_hash_rounds
    config.password_hash_rounds = 4
    yield
    config.password_hash_rounds = prev


# ====== 临时用户（含订阅） ======
#
# ★★ 「删除测试用户」的**唯一实现** —— 测试文件不要再自己写一份
#
#   指向 `users` 的外键共 **10 个**（`pg_constraint` 实测，2026-09-17），
#   按「删 users 时会不会被阻塞」分两类：
#     · CASCADE（数据库自己收尾）：accounts / account_members.user_id /
#       email_tokens / user_api_keys
#     · **NO CASCADE ⇒ 必须先手工处理**，否则 `DELETE FROM users` 直接报
#       `ForeignKeyViolationError: ... is still referenced from table ...`
#
#   血泪（第 100 轮）：`tests/test_users_self_service.py` 曾在文件内自建
#   `_cleanup()`，只 `DELETE FROM users` ⇒ 撞 `subscriptions_user_id_fkey`
#   （/register 会自动建一条默认订阅），4 条用例直接红。
#   根因**不是端点有 bug**，而是清理漏了依赖行 ⇒ 收敛到本函数。
#
#   清单可复算：
#     SELECT conrelid::regclass, conname, pg_get_constraintdef(oid)
#     FROM pg_constraint
#     WHERE confrelid='public.users'::regclass AND contype='f';
#   ★ 将来新增指向 users 的 NO-CASCADE 外键时，必须同步下面两张表。
#
#   `stores_store` 不放进这两张表：它的列名是 `owner_id`（不是 user_id），
#   而且它下面还挂着一堆带 shop_id 的业务表，需单独走拓扑序清理。
_USER_NO_CASCADE_DEPS = (
    ("invoices", "user_id"),         # 账单
    ("login_attempts", "user_id"),   # 登录尝试（可空：匿名尝试 user_id 为 NULL）
    ("payment_methods", "user_id"),  # 支付方式
    ("subscriptions", "user_id"),    # 订阅（注册时自动创建的那条 —— 本轮踩的就是它）
)

#: `invited_by` 用**置空**而不是删行 —— 它表示「谁邀请了这位成员」，
#: 删整行等于把**别人**的成员关系也一并抹掉。该列可空，置空即可。
_USER_NULL_OUT_DEPS = (("account_members", "invited_by"),)


async def _purge_users(*user_ids) -> None:
    """彻底删除这些测试用户（连同其名下店铺与全部依赖行）。

    参数混着传都可以：`_purge_users(uid)` / `_purge_users([a, b])` /
    `_purge_users(a, b)`。
    """
    from sqlalchemy import text
    from core.database import get_async_session

    flat: list[str] = []
    for u in user_ids:
        if isinstance(u, (list, tuple, set)):
            flat.extend(x for x in u if x)
        elif u:
            flat.append(u)
    if not flat:
        return

    async with get_async_session() as db:
        for uid in flat:
            # ① 该用户名下的店铺：先按外键拓扑序清 shop-scoped 数据，再删店铺。
            #    普通用例不建店（此处多为 0 行），但绝不能因此把这段写成错的 ——
            #    否则第一个"建了店"的用例就会在这里失败。
            shop_ids = (
                (
                    await db.execute(
                        text("SELECT id FROM stores_store WHERE owner_id = :u"),
                        {"u": uid},
                    )
                )
                .scalars()
                .all()
            )
            if shop_ids:
                for tbl in await _shop_scoped_delete_order(db):
                    await db.execute(
                        text(f'DELETE FROM "{tbl}" WHERE shop_id = ANY(:ids)'),
                        {"ids": shop_ids},
                    )
                await db.execute(
                    text("DELETE FROM stores_store WHERE id = ANY(:ids)"),
                    {"ids": shop_ids},
                )

            # ② 指向 users 的 NO-CASCADE 依赖
            for tbl, col in _USER_NO_CASCADE_DEPS:
                await db.execute(
                    text(f"DELETE FROM {tbl} WHERE {col} = :u"), {"u": uid}
                )
            for tbl, col in _USER_NULL_OUT_DEPS:
                await db.execute(
                    text(f"UPDATE {tbl} SET {col} = NULL WHERE {col} = :u"), {"u": uid}
                )

            # ③ 用户本体（accounts / account_members.user_id / email_tokens /
            #    user_api_keys 由数据库 CASCADE 收尾）
            await db.execute(text("DELETE FROM users WHERE id = :u"), {"u": uid})
        await db.commit()


@pytest_asyncio.fixture
async def user(client):
    """
    注册一个临时用户并返回其凭据。

    /register 会自动创建默认订阅，因此返回对象里带 subscription 信息。
    测试结束后连同其全部依赖行一起删除（见 `_purge_users`）。

    ★ 需要**多个互相隔离**的用户（越权 / 数据隔离类用例）请用 `make_user`，
      不要在本夹具之外再造第二个用户，也不要在测试文件里自己写删除逻辑。
    """
    email = f"pytest-{uuid.uuid4().hex[:10]}@example.com"
    password = "pytest123456"

    r = await client.post(
        "/api/v1/auth/register",
        json={"email": email, "password": password, "name": "pytest user"},
    )
    assert r.status_code in (200, 201), f"注册失败: {r.status_code} {r.text}"

    lr = await client.post(
        "/api/v1/auth/login",
        data={"username": email, "password": password},
        headers={"Content-Type": "application/x-www-form-urlencoded"},
    )
    assert lr.status_code == 200, f"登录失败: {lr.status_code} {lr.text}"
    token = lr.json()["access_token"]

    # 查 user_id / subscription_id 供 DB 断言与清理
    from sqlalchemy import select
    from core.database import get_async_session
    from core.identity.models import User
    from modules.billing.models import Subscription

    async with get_async_session() as db:
        u = (await db.execute(select(User).where(User.email == email))).scalar_one()
        sub = (
            await db.execute(select(Subscription).where(Subscription.user_id == u.id))
        ).scalar_one_or_none()
        payload = {
            "email": email,
            "password": password,
            "token": token,
            "user_id": u.id,
            "subscription_id": sub.id if sub else None,
        }

    yield payload

    # ★ 复用唯一实现：按外键依赖顺序删干净（旧版只删 3 张表，
    #   漏了 login_attempts —— 该表已因此累积到 850 行）。
    await _purge_users(payload["user_id"])


@pytest_asyncio.fixture
async def make_user(client):
    """
    工厂夹具：一次用例内建 **N 个互相隔离**的用户，teardown 统一回收。

    为什么需要它：`user` 夹具只能提供一个用户，而「越权访问」「数据按
    user_id 隔离」这类用例**天生需要两个主体**（A 的资源不能被 B 动）。
    第 100 轮曾在测试文件里自建 `_register()/_cleanup()`，清理漏了依赖行
    直接撞外键 ⇒ 本夹具把「建」和「删」都钉在唯一实现上。

    用法::

        async def test_x(client, make_user):
            a = await make_user("owner")
            b = await make_user("other")
            await client.get("/...", headers=a["headers"])   # 已备好 Bearer 头
            assert a["user_id"] != b["user_id"]

    ★ 关键收益不只是省事：**计数类断言从此是确定性的**。
      若用共享的 `auth_headers`，同一用户会被其它用例反复写入
      （例如"再建一把 key"），于是 `total == 1` 这类断言会随执行顺序变红 ——
      这是"单跑绿、加个 -k 就红"的典型来源。
    """
    created: list[dict] = []

    async def _make(label: str = "u") -> dict:
        email = f"pytest-{label}-{uuid.uuid4().hex[:8]}@example.com"
        password = "pytest123456"

        r = await client.post(
            "/api/v1/auth/register",
            json={"email": email, "password": password, "name": label},
        )
        assert r.status_code in (200, 201), f"注册失败: {r.status_code} {r.text}"

        lr = await client.post(
            "/api/v1/auth/login",
            data={"username": email, "password": password},
            headers={"Content-Type": "application/x-www-form-urlencoded"},
        )
        assert lr.status_code == 200, f"登录失败: {lr.status_code} {lr.text}"
        body = lr.json()

        info = {
            "email": email,
            "password": password,
            "token": body["access_token"],
            "user_id": body["user"]["id"],
            "headers": {"Authorization": f"Bearer {body['access_token']}"},
        }
        created.append(info)
        return info

    yield _make

    await _purge_users([c["user_id"] for c in created])


@pytest.fixture
def auth_headers(user):
    """带 Bearer Token 的请求头"""
    return {"Authorization": f"Bearer {user['token']}"}


# ====== 夹具租户身份（第 177 轮）======
#
# 背景：`SYNTHETIC_TEST_SHOP_IDS` 上方那条预告**在第 177 轮兑现了** ——
# 演示身份（`user is None`）的归属判定收紧为「只放行 `is_demo` 店铺」之后，
# 「匿名 + 合成 shop_id」这条通道不再成立，137 个用例**大声失败**
# （正是那条预告想要的：失败，而不是静默变成「看不见的店铺」）。
#
# 预告给的做法是「给它们补 account_id，**而不是**把断言调松」。本段就是那件事：
#   ① 一个**固定的**夹具用户 + 它的默认容器，作为全部合成店铺的归属者；
#   ② `ensure_shop` / `SYNTHETIC_TEST_SHOP_IDS` 建行时写入该归属；
#   ③ 需要身份的用例把 `tenant_headers` 合并进请求头 —— 请求因此**真的有身份**，
#      与生产档（`AUTH_REQUIRED=true`）走同一条代码路径，而不是靠演示档旁路。
#
# ★ 为什么**不能**改用「把合成店铺标成 `is_demo=True`」：
#   `is_demo` 不是「测试可见位」，它由 `ensure_demo_stores()` **双向收敛**为
#   「演示账号名下的店铺」。借用它会同时打破两条产品级不变量
#   （`test_demo_marker_is_derived_from_demo_account` 的集合相等、
#    `test_ensure_demo_stores_is_idempotent` 的「恰好 4 家」），
#   并让演示界面的店铺列表多出 12 家 `[test]` 店。
#
# ★ 为什么**不能**改用「匿名也放行无主店铺」：
#   实测本机库里有 4 家历史残留的无主店（`BOLA店铺-A` / `隔离店铺-A` /
#   `pytest-*`）。放行无主 ⇒ 它们会出现在演示模式的店铺列表里（`GET /stores`
#   读的是内存全量镜像）⇒ 老板看到一堆无名店铺。这是产品可见的缺陷。

#: 夹具租户的 email
TENANT_FIXTURE_EMAIL = "tenant-fixture@test.local"

#: 夹具租户的固定 id（UUID 形状；由 email 推导 ⇒ 任何机器都一样）
TENANT_FIXTURE_USER_ID = str(uuid.uuid5(uuid.NAMESPACE_DNS, TENANT_FIXTURE_EMAIL))

_tenant_identity: dict = {}


async def _ensure_tenant_fixture() -> dict:
    """
    建/取「夹具租户」—— 全部合成店铺的归属者（**幂等**，进程内缓存）。

    Returns:
        `{"user_id": ..., "account_id": ..., "token": ...}`

    ★ 为什么直接写 ORM 而不走 `/auth/register`：本夹具要在**会话级**使用
      （`_synthetic_test_shops` 建行时就要它），而 `client` 是函数级夹具 ——
      会话级夹具不能依赖它。直接写库也顺带说明了一件事：本身份**不靠登录流程**，
      它就是「一个已存在的用户 + 他名下最早的那个容器」。

    ★ 为什么不给它 `admin` 角色：`is_platform_admin` 会让 `can_access_store`
      整体短路（全部放行），那样「按归属过滤」这一层在本套件里就再也测不到了。
    """
    if _tenant_identity:
        return _tenant_identity

    from datetime import datetime

    from sqlalchemy import select

    from core.auth.accounts import ensure_default_account
    from core.auth.jwt_handler import create_access_token
    from core.database import async_session_factory
    from core.identity.models import User, UserRole
    from core.identity.router import hash_password
    # ★ 延迟导入 `modules`：`core/` 顶层禁 import modules（见 tests/test_core_layering.py），
    #   测试夹具同理 —— 只在真正需要时于函数内导入。
    from modules.billing.models import Subscription, SubscriptionPlan

    async with async_session_factory() as db:
        user = (
            await db.execute(select(User).where(User.id == TENANT_FIXTURE_USER_ID))
        ).scalar_one_or_none()
        if user is None:
            user = User(
                id=TENANT_FIXTURE_USER_ID,
                email=TENANT_FIXTURE_EMAIL,
                # 口令哈希只为满足 NOT NULL —— 本身份从不走口令登录，令牌在下面自签。
                hashed_password=hash_password("tenant-fixture-not-a-login"),
                name="夹具租户",
                role=UserRole.USER,
                is_active=True,
                is_verified=True,
            )
            db.add(user)
            await db.flush()
        account = await ensure_default_account(db, user)

        # ★★★ 第 177 轮（续）：夹具租户必须有**有效的订阅行**。
        #   没有它，带身份的请求会撞 `core/metering/usage_tracker.py::check_quota`
        #   的 `if not subscription or not subscription.is_active` ⇒ **429
        #   「订阅无效或已过期」**。实测：夹具租户一生效，定向回归里 94 条用例
        #   整齐地变成这个 429（`probes/o177_r3x.txt`），其中相当一部分的
        #   `KeyError: 'success' / 'data'` 只是 429 响应没有那两个键的次生现象。
        #
        #   ★ 为什么挂**最高档套餐**，而不是照抄 `/register` 的免费版（plan_id=1）：
        #     ① 本身份名下挂着**全部合成店铺**（`SYNTHETIC_TEST_SHOP_IDS` 13 家
        #        + `ensure_shop` 动态造的那些），而 `max_shops` 只有
        #        3（free）/ 10（pro）/ 50（enterprise）—— 低档套餐对一个
        #        "拥有 13+ 家店"的租户**本身就不自洽**；
        #     ② 更要紧的是**测试身份不该受生产月度预算约束**：免费版
        #        `api_calls_limit=100`，而单次全量回归就要打掉约 94 次 ⇒
        #        **第二轮跑批必然变红**，正是本仓反复踩过的「单跑绿 / 全量红」
        #        那一类顺序依赖缺陷。用最高档把这类假红彻底移出噪声区。
        #   ★ 计数器每次会话**归零**：夹具租户的用量是纯测试残留，
        #     归零才能让「跑第 N 次」与「跑第 1 次」结果一致。
        #   ★ 这不削弱任何门禁：配额门禁有自己的用户与用例
        #     （`test_billing_metering.py` / `test_aigc_jobs.py`，用的是
        #      `user` / `job_user` 夹具），与本夹具**无交集**。
        #
        # ★ 取套餐不硬编码 id / name：按 `api_calls_limit` 降序取第一条
        #   （= 最高档），这样套餐表被调整顺序或换名都不会让本夹具失配。
        top_plan = (
            await db.execute(
                select(SubscriptionPlan)
                .order_by(SubscriptionPlan.api_calls_limit.desc())
                .limit(1)
            )
        ).scalar_one()
        sub = (
            await db.execute(
                select(Subscription).where(Subscription.user_id == user.id)
            )
        ).scalar_one_or_none()
        if sub is None:
            db.add(
                Subscription(
                    id=str(uuid.uuid4()),
                    user_id=user.id,
                    plan_id=top_plan.id,
                    status="active",
                    current_period_start=datetime.utcnow(),
                )
            )
        else:
            # 上一轮跑批留下的行：校准到最高档 + 归零用量（幂等）。
            sub.plan_id = top_plan.id
            sub.status = "active"
            sub.current_period_end = None
            sub.api_calls_used = 0
            sub.agent_chats_used = 0

        await db.commit()
        token = create_access_token(
            {"sub": user.id, "email": user.email, "role": "user"},
            token_version=user.token_version,
        )

    _tenant_identity.update(user_id=user.id, account_id=account.id, token=token)
    return _tenant_identity


@pytest_asyncio.fixture(scope="session")
async def tenant_identity() -> dict:
    """夹具租户（会话级；同一次跑批里所有用例共用同一个用户与容器）。"""
    return await _ensure_tenant_fixture()


@pytest_asyncio.fixture
async def tenant_headers(tenant_identity) -> dict:
    """
    夹具租户的请求头 —— 「需要有身份」的用例把它合并进 headers。

    用法::

        async def test_x(client, tenant_headers, ensure_shop):
            sid = await ensure_shop(f"store_pytest_{uuid.uuid4().hex[:8]}")
            headers = {"X-Shop-ID": sid, **tenant_headers}
            ...

    ★ 合成店铺的归属者就是这个身份 ⇒ `X-Shop-ID` 指向自己的店 ⇒ 200。
      指向**别人的**店或演示店仍会 403（归属判定没有被削弱）。
    """
    return {"Authorization": f"Bearer {tenant_identity['token']}"}


# ====== LLM 打桩 ======

@pytest.fixture
def fake_llm(monkeypatch):
    """
    把 DashScopeLLM 的 chat / chat_stream 换成固定桩，避免真实调用与花费。

    仍会走 `_update_stats` / 计量钩子，因此能覆盖「LLM 消耗 → 计费」链路。
    """
    from ai_infra.llm import dashscope_client as dc

    def _make_response(input_tokens=120, output_tokens=80, cost=0.0036):
        return dc.LLMResponse(
            content="这是一段模拟的 LLM 回答。",
            model="qwen-max",
            input_tokens=input_tokens,
            output_tokens=output_tokens,
            total_tokens=input_tokens + output_tokens,
            cost=cost,
            latency_ms=5,
            finish_reason="stop",
            raw_response={},
        )

    async def fake_chat(self, messages, system_prompt=None, **kwargs):
        resp = _make_response()
        self._update_stats(resp)
        return resp

    async def fake_chat_stream(self, messages, system_prompt=None, **kwargs):
        for chunk in ["这是", "一段", "模拟的", "流式回答。"]:
            yield chunk
        dc.record_llm_usage(input_tokens=120, output_tokens=80, cost=0.0036, model="qwen-max")

    monkeypatch.setattr(dc.DashScopeLLM, "chat", fake_chat)
    monkeypatch.setattr(dc.DashScopeLLM, "chat_stream", fake_chat_stream)
    return {"response": _make_response}


# ====== 平台凭证加密密钥（第 318 轮上移到 conftest：两个文件都要用） ======

@pytest.fixture
def with_key(monkeypatch):
    """装一个合法 Fernet 密钥（function 级，不污染其他用例）。

    ★ 为什么收在 conftest：`test_credential_encryption.py` 与
      `test_store_connect.py` 都需要它。留两份就是「同一能力两份实现」——
      改一处漏一处时，其中一个文件会**静默地**不再覆盖「配了密钥」的情形，
      而且两边都不会报错。
    """
    from core.config import config
    from core.security.credentials import generate_key

    key = generate_key()
    monkeypatch.setattr(config, "credentials_encryption_key", key, raising=False)
    return key


# ====== 连接器桩（离线断言「连接成功」路径的唯一手段） ======

class _StubConnector:
    """真连接器的**字段声明** + **受控**的 `verify()` —— 不联网。

    属性访问走 `__getattr__` 代理，因此 `fields()` / `normalize()` / `require()`
    / `masked_echo()` / `schema()` 一律是真实现（真 schema），只有 `verify`
    被替换掉。

    ★ 为什么用 `self.__dict__[...]` 而不是 `self._real = ...`：
      `__getattr__` 在属性缺失时触发，而 `__init__` 里若先有属性访问，
      就会在 `_real` 尚未存在的瞬间**递归调用 `__getattr__`** ⇒ 无限递归。
      直接写 `__dict__` 绕开这条路径。
    """

    def __init__(self, real, result):
        self.__dict__["_real"] = real
        self.__dict__["_result"] = result
        self.__dict__["seen"] = None

    def __getattr__(self, name):
        # 只代理**未显式定义**的属性：本类已定义 `verify`，
        # 因此 `__getattr__` 不会被用来覆盖它。
        return getattr(self.__dict__["_real"], name)

    async def verify(self, values):
        self.__dict__["seen"] = dict(values)
        return self.__dict__["_result"]


@pytest.fixture
def stub_connector(monkeypatch):
    """把 `router._resolve_connector` 换成受控桩，返回一个**安装函数**。

    用法::

        async def test_ok(client, with_key, stub_connector, ...):
            stub_connector("amazon_us", VerifyStatus.OK)
            r = await client.post(f"/api/v1/stores/{sid}/connect", json=payload)

    ★ 为什么必须留这条接缝：端点唯一的真实外部依赖就是「连到平台」。
      不注入的话，断言「连接成功」就只能真拿凭据去打 Amazon —— 这种用例慢、
      不可复现（网络一抖就红，且红的原因与被测逻辑无关），最后的结局一定是
      被注释掉，于是**成功路径永久失去覆盖**。
      （判据：每条成功路径都必须能在**离线**条件下被断言。）

    ★ 桩为什么要代理**真**连接器的 `fields()`：若桩自己发明一套字段，
      真 schema 改了而桩没跟上，用例照旧全绿 —— 那测的就不是真实的表单形状了。

    ★ 返回的桩上有 `seen`：记录 `verify()` 实际收到的值（已过白名单收敛），
      供「**落库的到底是什么**」这类断言使用。
    """
    from modules.stores import router as stores_router
    from modules.stores.connect import VerifyResult
    from modules.stores.connect.registry import get_connector

    def _install(platform, status, message="已通过校验", refreshed=None, detail=None):
        stub = _StubConnector(
            get_connector(platform),
            VerifyResult(
                status=status,
                message=message,
                refreshed=dict(refreshed or {}),
                detail=dict(detail or {}),
            ),
        )
        monkeypatch.setattr(stores_router, "_resolve_connector", lambda _p: stub)
        return stub

    return _install


# ====== 内存店铺镜像自清理（autouse） ======
#
# ★★ 为什么必须有这一道（第 106 轮实测踩到，全量跑红 / 单跑绿）：
#   `GET /api/v1/stores` 读的是**进程内内存字典** `_store_db`
#   （PG 才是权威存储，lifespan 启动时回灌；见 modules/stores/router.py）。
#   用 API 建的店铺会**同时**写 PG 与 `_store_db`；而 `make_user` / `user`
#   夹具收尾只走 `_purge_users` 删 PG 行，**内存镜像没有对应的清理**。
#   ⇒ 排在后面的用例读 `GET /api/v1/stores`（内存）会拿到"PG 里已不存在"的店铺。
#   实测打破 `test_stores.py::test_stores_order_matches_shop_tools_order`
#   —— 它比对的正是「内存版 /api/v1/stores」与「PG 版 _list_shops」。
#
#   ★ 现象特征：**单跑绿、全量红**（是否踩中取决于文件收集顺序里谁排在前面），
#     且报错信息是"api 返回了 tool 不认识的店铺"，看起来像归属过滤出了问题，
#     其实是测试进程内的残留 —— 别去改断言，先怀疑内存镜像没清。
#
# ★ 为什么是「快照差集」而不是逐用例写 `_store_db.pop`：
#   逐处 pop 依赖每个新用例作者都记得（本仓已有 test_stores /
#   test_store_delete_guard / test_credential_encryption /
#   test_account_store_hierarchy 四个文件各写了一遍），漏一个就重现。
#   这里在**内存镜像这个出口**统一兜底 —— 与上面 `_no_real_llm` 在"网络出口"
#   兜底是同一个思路：新增用例零负担，不必知道 `_store_db` 的存在。
#
# ★ 只删「本用例新增」的 key，因此绝不会误伤：
#   · lifespan 回灌的基线店铺；
#   · 模块级 / 会话级夹具在用例**开始之前**就放进去的店铺（它们都在快照里）。

@pytest.fixture(autouse=True)
def _isolate_store_memory_mirror():
    """用例结束后移除本用例往 `_store_db` 新增的条目（详见上方说明）。"""
    from modules.stores.router import _store_db

    before = set(_store_db.keys())
    yield
    for sid in set(_store_db.keys()) - before:
        _store_db.pop(sid, None)


# ====== 业务店铺上下文（需要 X-Shop-ID 的端点测试共用） ======
#
# 背景：spus / skus / assets / candidates / monitors / knowledge_* / *_groups …
# 全部按 shop_id 过滤（`get_current_shop_id` 从 `X-Shop-ID` 头取）。
# 所以凡是要写业务数据的端点测试，都得先有一个"当前店铺"，
# 且用例结束后必须把它连同其下数据一起清掉，否则开发库里会堆测试垃圾。

_TABLES_WITH_SHOP_ID_SQL = """
    SELECT c.table_name
    FROM information_schema.columns c
    JOIN pg_class t ON t.relname = c.table_name
    JOIN pg_namespace n ON n.oid = t.relnamespace AND n.nspname = 'public'
    WHERE c.column_name = 'shop_id' AND c.table_schema = 'public'
"""

_FK_EDGES_SQL = """
    SELECT src.relname AS child, ref.relname AS parent
    FROM pg_constraint con
    JOIN pg_class src ON src.oid = con.conrelid
    JOIN pg_class ref ON ref.oid = con.confrelid
    WHERE con.contype = 'f'
"""


async def _shop_scoped_delete_order(session):
    """
    返回「带 shop_id 的表」的删除顺序：**先子表、后父表**。

    不硬编码表名：从 information_schema 取表，从 pg_constraint 取外键边，
    再拓扑排序。将来新增带 shop_id 的表（以及新的外键）会自动纳入。

    为什么不能随便顺序删：`skus.spu_id -> spus.id` 这类外键真实存在，
    先删 spus 会被数据库拒绝（子行还在），清理就失败了。
    """
    from sqlalchemy import text

    tables = set((await session.execute(text(_TABLES_WITH_SHOP_ID_SQL))).scalars().all())
    edges = (await session.execute(text(_FK_EDGES_SQL))).all()

    parents_of = {t: set() for t in tables}
    for child, parent in edges:
        if child in tables and parent in tables:
            parents_of[child].add(parent)

    order, remaining = [], set(tables)
    while remaining:
        # 「被其它剩余表引用」的表要往后放；先删没有被引用的
        referenced = {p for t in remaining for p in parents_of[t] if p in remaining}
        ready = sorted(remaining - referenced)
        if not ready:  # 出现环（正常 schema 不该有）→ 兜底，交给事务整体回滚
            ready = sorted(remaining)
        order.extend(ready)
        remaining -= set(ready)
    return order


# ====== 合成测试店铺（外键前提） ======
#
# 测试套件长期用「合成 shop_id」做分区隔离，例如 test_platform_rules.py 里
# `build_rule_record({"title": "T"}, shop_id="s1")`。这些 id 只是分区键，
# 过去不需要真实存在。
#
# 但迁移 d5e6f7a8b9c0（2026-09-15）给 16 张业务表加了 shop_id -> stores_store
# 外键后，合成 id 不再是"合法"值：写入会被数据库拒绝。
# 实测一次性打破 49 个用例 / 709 处外键违例。
#
# 这里在会话开始时为这些 id 建出真实店铺行，结束时清掉。
# 保留原有隔离语义（每个文件仍用自己的 id 分区），只是补上"必须真实存在"这一前提。
#
# ★★ P1-c（2026-09-16）这些合成店铺**故意不带 account_id**（owner_id 也空）：
#   它们扮演的是「租户上下文标记」，不是用户看得见的店铺。
#   归属判定因此走 `core/auth/accounts.py::_matches` 的**过渡期兜底分支**
#   （account_id 为空 ⇒ 回退到 owner_id 判定；两者都为空 ⇒ 非超管一律拒绝），
#   而业务侧解析时它们只在演示模式（AUTH_REQUIRED=false）下被放行 ——
#   这正是测试套件的运行模式。
#   ⇒ 一旦过渡期分支被删除，相关用例会**大声失败**（而不是静默变成
#     「看不见的店铺」）；那时请给它们补 account_id，而不是把断言调松。
#   过渡期分支的分支穷尽断言见
#   `tests/test_account_store_hierarchy.py::test_ownership_kernel_branches`。
#
# ★★★ 第 177 轮：**预告兑现了，并且就是按预告做的。**
#   演示身份（`user is None`）收紧为「只放行 `is_demo` 店铺」之后，
#   匿名 + 合成 shop_id 不再被放行 ⇒ 137 个用例同时变红（见
#   `probes/o177_fullx.txt`），红的原因是 `ensure_shop` 造出的是**无主**店铺。
#   处理方式 = 「补归属」，而不是把判定调松：
#     · 全部合成店铺（本表 + `ensure_shop` 动态造的那些）现在归属
#       「夹具租户」（`_ensure_tenant_fixture()`），
#     · 相关用例用 `tenant_headers` 带上该身份。
#   ⇒ 它们由此从「靠演示档旁路」变成「与生产档同一条路径」。
#
# ★ 新增合成 shop_id 时必须登记到下面这张表，否则那条用例会以外键违例失败。
#   （p9b_enum_shop_ids.py 可以机械枚举出全部字面量）
SYNTHETIC_TEST_SHOP_IDS = (
    "s1",                          # test_knowledge_base / test_platform_rules / test_auth_and_tenant
    "s2",                          # test_auth_and_tenant
    "store_1",                     # test_secretary_intent_shortcut
    "store_test",                  # test_aigc_jobs / test_competitor_intel / test_review_analyst_api
    "store_review_other",          # test_review_analyst_api（第二家店，验证回显的是服务端注入的那个）
    "store_x",                     # test_monitors
    "store_unittest_delprobe",     # test_voice_clone_isolation
    "store_unittest_enrollguard",
    "store_unittest_forceprobe",
    "store_unittest_novoice",
    "store_unittest_speak",
    "store_unittest_speakclip",
    "store_unittest_speakempty",
    "store_r216_q",                # test_candidate_generic_query（候选通用查询）
)


@pytest_asyncio.fixture(scope="session", autouse=True)
async def _synthetic_test_shops():
    """
    为 `SYNTHETIC_TEST_SHOP_IDS` 建出真实店铺行（会话级，自动生效）。

    只写 PG、不写内存 `_store_db`：
    这些是"租户上下文"，不是用户看得见的店铺；写进内存会让
    `GET /api/v1/stores`（读内存）凭空多出 12 家店。
    需要它们的用例都走 `X-Shop-ID` 头，命中点只在 PG 侧。

    ★ P1-c（2026-09-16）：这些行**不写 `account_id`**，理由见上面
      `SYNTHETIC_TEST_SHOP_IDS` 上方的说明 —— 它们靠归属判定的过渡期
      兜底分支存活，那是刻意保留的一条**临时**通道。
    """
    from sqlalchemy import text
    from core.database import async_session_factory
    from core.stores import StoreRecord

    async with async_session_factory() as session:
        existing = set((await session.execute(
            text("SELECT id FROM stores_store WHERE id = ANY(:ids)"),
            {"ids": list(SYNTHETIC_TEST_SHOP_IDS)},
        )).scalars().all())
        # ★★★ 第 177 轮：这些行**必须带归属**（见上方 P1-c 的预告）。
        owner = await _ensure_tenant_fixture()
        for sid in SYNTHETIC_TEST_SHOP_IDS:
            if sid in existing:
                continue
            session.add(StoreRecord(
                id=sid,
                name=f"[test] {sid}",
                platform="amazon_us",
                tenant_id="default_tenant",
                owner_id=owner["user_id"],
                account_id=owner["account_id"],
            ))
        await session.commit()

        # ★ 已存在的合成行（本机上一轮跑过、或上一次跑批中断留下的）也要补归属：
        #   只补"新建的"会让本机「首次绿、之后红」—— 顺序依赖的典型来源。
        #   `account_id IS NULL` 是守卫：绝不改写任何真实归属。
        await session.execute(
            text(
                "UPDATE stores_store SET owner_id = :u, account_id = :a "
                "WHERE id = ANY(:ids) AND account_id IS NULL"
            ),
            {
                "u": owner["user_id"],
                "a": owner["account_id"],
                "ids": list(SYNTHETIC_TEST_SHOP_IDS),
            },
        )
        await session.commit()

    yield

    # 结束清理：先清这些 id 名下的业务数据（外键 RESTRICT 会拦住直接删店铺），
    # 复用 _shop_scoped_delete_order 的拓扑排序，保证「先子表后父表」。
    async with async_session_factory() as session:
        for table in await _shop_scoped_delete_order(session):
            await session.execute(
                text('DELETE FROM "%s" WHERE shop_id = ANY(:ids)' % table),
                {"ids": list(SYNTHETIC_TEST_SHOP_IDS)},
            )
        await session.execute(
            text("DELETE FROM stores_store WHERE id = ANY(:ids)"),
            {"ids": list(SYNTHETIC_TEST_SHOP_IDS)},
        )
        await session.commit()


@pytest_asyncio.fixture(autouse=True)
async def _fresh_db_pool_per_test():
    """每个用例开始前**清空连接池** —— 见下方「为什么」。

    ★ 为什么需要（第 210 轮定位到的既有隐患，**不是本轮引入**）：
      `pytest.ini` 已刻意把 loop scope 钉成 session（注释里写的就是这条），
      但**同步用例里的 `asyncio.run(...)` 会另起一个 loop**（全仓 20+ 处：
      `test_voice_clone_isolation` / `test_secretary_plan_read` /
      `test_llm_rag_integration` / `test_agent_budget` …）。那个 loop 用完即销毁，
      而它从共享 `engine` 池里取走的连接**留在池里**；后面的用例在自己的 loop 里
      拿到它 ⇒ `RuntimeError: got Future <...> attached to a different loop`。

    ★ 症状是「可复现但与内容无关」，所以特别费解：
        · 单跑 `tests/test_agent_session_state.py` → 46/46 绿；
        · 全量跑 → 同一文件里两条**真 PG 端到端**用例必红（其余全绿）。
      受伤的永远是**直接对池取连接**的用例 —— 只有它们会撞上池里的脏连接。

    ★ `close=False` 是必须的：池里那些连接绑在**已经销毁**的 loop 上，
      真去 `close()` 又要 await 那个 loop ⇒ 当场再炸一次。
      SQLAlchemy 为本场景提供了 `dispose(close=False)`：只丢弃句柄、不关连接。

    ★ 只改 tests/，不动 `core/database.py`：生产跑在 uvicorn 的单 loop 下不存在本问题，
      把 `NullPool` 之类推进产品代码属于「为了测试改产品」。
    """
    from core.database import engine

    await engine.dispose(close=False)
    yield


@pytest_asyncio.fixture
async def ensure_shop():
    """
    合成 shop_id 的「真实化」工厂：`sid = await ensure_shop(sid)`。

    为什么需要
    ----------
    迁移 d5e6f7a8b9c0 给 16 张业务表加了 `shop_id -> stores_store` 外键。
    而测试里常见写法是先造一个分区键、再塞进 X-Shop-ID 头：

        sid = f"store_pytest_kb_{uuid.uuid4().hex[:8]}"
        yield {"X-Shop-ID": sid}

    这个 id 只是分区键，`stores_store` 里并没有对应行 ⇒ 写入被外键拒绝
    （实测一次性打破 49 个用例）。

    把生成表达式包一层 `await ensure_shop(...)` 即可：它在 PG 里为该 id
    建出真实店铺行（幂等），用例结束后按外键依赖倒序清掉。

    注意
    ----
    只写 PG、不写内存 `_store_db`：这些是"租户上下文"，不是用户可见的店铺，
    进内存会让 `GET /api/v1/stores`（读内存）凭空多出店铺。

    需要"店铺属于某个用户"的场景（生产模式下 `get_current_shop_id` 会校验
    `stores_store.owner_id`）不适用本夹具 —— 那种情况请直接插入带 owner_id
    的 StoreRecord，例如 test_aigc_jobs.py 的 `job_user`。
    """
    from sqlalchemy import text
    from core.database import async_session_factory
    from core.stores import StoreRecord

    created: list = []

    async def _ensure(sid: str) -> str:
        if not sid or sid in created:
            return sid
        async with async_session_factory() as session:
            exists = (await session.execute(
                text("SELECT 1 FROM stores_store WHERE id = :sid"), {"sid": sid}
            )).scalar()
            # ★★★ 第 177 轮：合成店铺**必须属于夹具租户**（见上方 P1-c 的预告）。
            #   无主店铺对任何身份都不可见（生产档同样），匿名也不再放行 ——
            #   所以"匿名 + 合成 shop_id"这条老通道已经不存在了。
            owner = await _ensure_tenant_fixture()
            if not exists:
                session.add(StoreRecord(
                    id=sid, name=f"[test] {sid}",
                    platform="amazon_us", tenant_id="default_tenant",
                    owner_id=owner["user_id"], account_id=owner["account_id"],
                ))
            else:
                # 上一轮跑批留下的无主行：补归属。`account_id IS NULL` 守卫
                # 保证不会改写任何已有归属（含真实店铺）。
                await session.execute(
                    text(
                        "UPDATE stores_store SET owner_id = :u, account_id = :a "
                        "WHERE id = :sid AND account_id IS NULL"
                    ),
                    {"u": owner["user_id"], "a": owner["account_id"], "sid": sid},
                )
            await session.commit()
        created.append(sid)
        return sid

    yield _ensure

    if not created:
        return
    async with async_session_factory() as session:
        for table in await _shop_scoped_delete_order(session):
            await session.execute(
                text('DELETE FROM "%s" WHERE shop_id = ANY(:ids)' % table),
                {"ids": created},
            )
        await session.execute(
            text("DELETE FROM stores_store WHERE id = ANY(:ids)"), {"ids": created}
        )
        await session.commit()
