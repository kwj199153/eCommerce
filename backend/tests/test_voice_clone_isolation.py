"""语音克隆附加模块的隔离性 + 业务规则回归测试。

本文件承载两条**架构级断言**（不是功能测试，坏了就是架构被破了）：

1. **依赖方向单向**：主功能源码里不允许出现 ``voice_clone`` / ``VoiceClone`` 等字面量。
   靠自觉一定会被破 —— 所以用测试钉死。依赖只允许「模块 → 主功能」。
2. **总开关生效**：``voice_clone_enabled=False`` 时路由**根本不注册**（404 语义），
   而不是「注册了但返回 403」—— 前者前端可以据此隐藏入口。

另有若干纯函数级业务规则测试（样本校验 / prefix 归一 / 音色与模型死绑纠正）。
"""

from __future__ import annotations

import re
from pathlib import Path

import pytest

BACKEND = Path(__file__).resolve().parents[1]
MODULE_DIR = BACKEND / "modules" / "voice_clone"

#: 主功能源码里**不允许**出现的标识（模块自身的字面量）
_FORBIDDEN_TOKENS = (
    "voice_clone",
    "voice-clone",
    "VoiceClone",
    "ShopVoice",
    "cosyvoice",
)

#: 主功能范围：除模块自身目录之外的所有 backend 源码
_SCAN_DIRS = ("modules", "core", "ai_infra", "platforms", "services", "main.py")


def _iter_main_source_files():
    """遍历主功能源码（排除模块自身目录 + tests + alembic + __pycache__）。"""
    module_resolved = MODULE_DIR.resolve()
    for entry in _SCAN_DIRS:
        target = BACKEND / entry
        if target.is_file():
            yield target
            continue
        if not target.exists():
            continue
        for path in target.rglob("*.py"):
            if "__pycache__" in path.parts:
                continue
            try:
                if module_resolved in path.resolve().parents or path.resolve() == module_resolved:
                    continue
            except OSError:
                continue
            yield path


# --------------------------------------------------------------------------- #
# 架构断言 1：依赖方向单向
# --------------------------------------------------------------------------- #

def test_main_function_does_not_reference_voice_clone():
    """★ 主功能**业务**源码里不得出现语音克隆模块的任何标识。

    两个**装配点**豁免（这是「挂载外部模块」这件事本身的定义，不是业务耦合）：

    - ``main.py``：条件挂载 router（开关为真才 import，是唯一允许的入口装配）
    - ``core/database.py``：集中导入模型完成后 metadata 注册 + create_all 兜底

    除此之外，任何业务模块（listing / customer_service / secretary / ...）出现
    这些字面量都算违反铁律 —— 依赖方向必须单向「模块 → 主功能」。
    """
    #: 装配层豁免（只允许出现「挂载/注册」语义，不允许出现业务字段名）
    assembly_exempt = {
        (BACKEND / "main.py").resolve(),
        (BACKEND / "core" / "config.py").resolve(),
        (BACKEND / "core" / "database.py").resolve(),
    }

    offenders: list[str] = []
    for path in _iter_main_source_files():
        if path.resolve() in assembly_exempt:
            continue
        text = path.read_text(encoding="utf-8", errors="ignore")
        for token in _FORBIDDEN_TOKENS:
            if token in text:
                offenders.append(f"{path.relative_to(BACKEND)} ← {token!r}")

    assert not offenders, (
        "违反「附加模块可插拔」铁律：主功能业务代码出现了语音克隆模块的引用。\n"
        "依赖方向必须是单向的「模块 → 主功能」，业务模块不得 import 模块。\n"
        "命中位置：\n  " + "\n  ".join(offenders)
    )


def test_business_modules_specifically_clean():
    """逐个点名 6 个业务 Agent + 编排层，明确它们与语音克隆零耦合。"""
    business = (
        "modules/listing_generator",
        "modules/product_research",
        "modules/ad_analysis",
        "modules/customer_service",
        "modules/competitor_intel",
        "modules/aigc_media",
        "modules/secretary",
    )
    hits: list[str] = []
    for rel in business:
        d = BACKEND / rel
        if not d.exists():
            continue
        for path in d.rglob("*.py"):
            if "__pycache__" in path.parts:
                continue
            text = path.read_text(encoding="utf-8", errors="ignore")
            for token in _FORBIDDEN_TOKENS:
                if token in text:
                    hits.append(f"{rel} ← {path.name} ← {token!r}")
    assert not hits, "业务模块被语音克隆污染：\n  " + "\n  ".join(hits)


def test_voice_clone_module_is_self_contained():
    """模块自身只允许依赖 core.*（外加复用 aigc_media 的纯工具 storage）。"""
    allowed_prefixes = (
        "core.",
        "modules.voice_clone",
        "modules.aigc_media.storage",  # 纯工具：远程资源转存，不读业务表
    )
    bad: list[str] = []
    import_re = re.compile(r"^\s*(?:from|import)\s+([A-Za-z_][\w.]*)", re.M)

    for path in MODULE_DIR.rglob("*.py"):
        if "__pycache__" in path.parts:
            continue
        for mod in import_re.findall(path.read_text(encoding="utf-8", errors="ignore")):
            if mod.split(".")[0] in ("core", "modules"):
                if not any(mod == p or mod.startswith(p + ".") or mod.startswith(p) for p in allowed_prefixes):
                    bad.append(f"{path.name} ← {mod}")

    assert not bad, "语音克隆模块引入了不该有的业务依赖：\n  " + "\n  ".join(bad)


# --------------------------------------------------------------------------- #
# 架构断言 2：总开关
# --------------------------------------------------------------------------- #

def test_router_prefix_is_isolated():
    """路由前缀必须独立（不与既有业务 prefix 混用）。"""
    from modules.voice_clone.router import router

    assert router.prefix == "/voice-clone"
    assert not router.prefix.startswith("/api/v1")


def test_disabled_by_default():
    """★ 装了也不生效：默认必须是 False。"""
    from core.config import Settings

    assert Settings.model_fields["voice_clone_enabled"].default is False


@pytest.mark.asyncio
async def test_routes_absent_when_disabled(monkeypatch):
    """开关关闭 → 路由不存在（404 语义，而非 403）。"""
    from core.config import config

    monkeypatch.setattr(config, "voice_clone_enabled", False)
    import importlib

    import main as main_module

    importlib.reload(main_module)
    try:
        paths = {getattr(r, "path", "") for r in main_module.app.routes}
        assert not [p for p in paths if "voice-clone" in p]
    finally:
        importlib.reload(main_module)


@pytest.mark.asyncio
async def test_routes_present_when_enabled(monkeypatch):
    """开关打开 → 8 个端点全部注册在 /api/v1/voice-clone 下。"""
    from core.config import config

    monkeypatch.setattr(config, "voice_clone_enabled", True)
    import importlib

    import main as main_module

    importlib.reload(main_module)
    try:
        paths = {
            (getattr(r, "path", ""), tuple(sorted(getattr(r, "methods", []) or [])))
            for r in main_module.app.routes
            if "voice-clone" in getattr(r, "path", "")
        }
        assert len(paths) == 8
        assert ("/api/v1/voice-clone/status", ("GET",)) in paths
        assert ("/api/v1/voice-clone/speak", ("POST",)) in paths
        # ★ 分句流水线：纯计算端点（首声延迟从 ~5s 降到 ~1.6s 的关键）
        assert ("/api/v1/voice-clone/speak-plan", ("POST",)) in paths
        assert ("/api/v1/voice-clone", ("DELETE",)) in paths
    finally:
        importlib.reload(main_module)


# --------------------------------------------------------------------------- #
# 业务规则（纯函数级，不联网）
# --------------------------------------------------------------------------- #

def test_validate_sample_rejects_short_audio():
    """少于 5 秒必须拒绝并说清原因（CosyVoice 要求 ≥5 秒连续朗读）。"""
    from modules.voice_clone.client import VoiceCloneError
    from modules.voice_clone.service import validate_sample

    with pytest.raises(VoiceCloneError) as exc:
        validate_sample(filename="a.wav", size=100_000, duration=2.5)
    assert "太短" in str(exc.value)


def test_validate_sample_rejects_oversize():
    from modules.voice_clone.client import VoiceCloneError
    from modules.voice_clone.service import validate_sample

    with pytest.raises(VoiceCloneError) as exc:
        validate_sample(filename="a.mp3", size=11 * 1024 * 1024, duration=15)
    assert "过大" in str(exc.value)


def test_validate_sample_rejects_bad_ext():
    from modules.voice_clone.client import VoiceCloneError
    from modules.voice_clone.service import validate_sample

    with pytest.raises(VoiceCloneError) as exc:
        validate_sample(filename="a.flac", size=1000, duration=15)
    assert "格式不支持" in str(exc.value)


def test_validate_sample_accepts_good_audio():
    from modules.voice_clone.service import validate_sample

    validate_sample(filename="sample.wav", size=2_000_000, duration=15.0)  # 不抛


def test_validate_sample_allows_unknown_duration():
    """时长未知时跳过该项校验（由调用方在响应里标注未验证），但不因此报错。"""
    from modules.voice_clone.service import validate_sample

    validate_sample(filename="sample.m4a", size=2_000_000, duration=None)


def test_normalize_prefix_is_legal():
    """prefix 仅数字/英文字母、≤10 字符，且同一店铺稳定。"""
    from modules.voice_clone.client import normalize_prefix

    p1 = normalize_prefix("store_ab12cd34ef56")
    p2 = normalize_prefix("store_ab12cd34ef56")
    assert p1 == p2
    assert len(p1) <= 10
    assert re.fullmatch(r"[0-9A-Za-z]+", p1)


def test_unsupported_target_model_rejected():
    """白名单外的模型必须报错，**不静默替换成默认模型**。"""
    from modules.voice_clone.client import VoiceCloneError
    from modules.voice_clone.client import SUPPORTED_TARGET_MODELS

    assert "cosyvoice-v3-flash" in SUPPORTED_TARGET_MODELS
    assert "cosyvoice-v3.5-flash" in SUPPORTED_TARGET_MODELS
    # v3.5 仅北京地域可用这一点写在模块注释里；此处只守白名单
    assert "cosyvoice-v4" not in SUPPORTED_TARGET_MODELS


def test_serialize_none_is_empty_state():
    """无记录 → 返回空状态（绝不返回虚构默认音色）。"""
    from modules.voice_clone.service import serialize

    out = serialize(None)
    assert out["exists"] is False
    assert out["ready"] is False
    assert "voice_id" not in out


# --------------------------------------------------------------------------- #
# 回归测试：两个实测踩到的坑
# --------------------------------------------------------------------------- #

def test_single_voice_guard_uses_local_vocabulary():
    """★ 回归：单店铺单音色守卫必须比对**本模块落库词表**（ready/pending），
    而不是远端的 ``OK``。

    曾经写成 ``existing.status == client.STATUS_OK``（"OK"），但本模块落库的是
    "ready" —— 两套词表混用让守卫变成**死代码**，第二次 enroll 会直接覆盖掉
    已就绪的音色（实测发现）。
    """
    from modules.voice_clone.service import _SINGLE_VOICE_BLOCKING_STATUSES

    assert _SINGLE_VOICE_BLOCKING_STATUSES == ("ready", "pending")
    # 明确断言：远端词表的值不在本地守卫集合里（防再次混用）
    from modules.voice_clone.client import STATUS_OK

    assert STATUS_OK not in _SINGLE_VOICE_BLOCKING_STATUSES


@pytest.mark.asyncio
async def test_remote_delete_failure_does_not_block_local_cleanup(monkeypatch):
    """★ 回归：远端删除失败时，本地记录**仍须被清掉**，并把原因作为 warning 回报。

    否则远端音色被平台回收 / Key 变更后，用户会永久卡在一个删不掉的记录上。
    """
    shop_id = "store_unittest_delprobe"
    from modules.voice_clone import service

    # 造一条记录
    await service.upsert_record(shop_id, voice_id="cosy-probe-xyz", status="ready")
    try:
        async def boom(voice_id: str) -> None:
            raise service.VoiceCloneError("BadRequest.ResourceNotExist The Required resource not exist")

        monkeypatch.setattr(service.client, "delete_voice", boom)

        result = await service.delete_record(shop_id, also_remote=True)

        assert result["removed"] is True          # 本地清掉了
        assert result["remote_deleted"] is False  # 远端没删掉
        assert "ResourceNotExist" in result["warning"]  # 原因如实回报
        assert await service.get_record(shop_id) is None
    finally:
        # 兜底清理，避免污染后续用例
        await service.delete_record(shop_id, also_remote=False, force=True)


@pytest.mark.asyncio
async def test_force_delete_skips_remote(monkeypatch):
    """``force=True`` 跳过远端调用，纯本地清理。"""
    shop_id = "store_unittest_forceprobe"
    from modules.voice_clone import service

    await service.upsert_record(shop_id, voice_id="cosy-probe-force", status="ready")
    called: list[str] = []

    async def spy(voice_id: str) -> None:
        called.append(voice_id)

    monkeypatch.setattr(service.client, "delete_voice", spy)
    try:
        result = await service.delete_record(shop_id, also_remote=True, force=True)
        assert result["removed"] is True
        assert called == []  # 没有调远端
    finally:
        await service.delete_record(shop_id, also_remote=False, force=True)


@pytest.mark.asyncio
async def test_enroll_rejects_when_voice_already_ready(monkeypatch):
    """★ 端口级回归：已有 ready 音色时，第二次 enroll 必须被拒（不覆盖）。"""
    import httpx
    from httpx import ASGITransport

    from core.config import config

    monkeypatch.setattr(config, "voice_clone_enabled", True)
    monkeypatch.setattr(config, "public_base_url", "https://probe.invalid.example.com")

    shop_id = "store_unittest_enrollguard"
    from modules.voice_clone import service

    # 预置一条 ready 记录（模拟「已经克隆过」）
    await service.upsert_record(shop_id, voice_id="cosy-existing-001", status="ready")
    try:
        import importlib

        import main as main_module

        importlib.reload(main_module)
        try:
            async with httpx.AsyncClient(
                transport=ASGITransport(app=main_module.app), base_url="http://test"
            ) as c:
                r = await c.post(
                    "/api/v1/voice-clone/enroll",
                    headers={"X-Shop-ID": shop_id},
                    json={
                        "sample_url": "/static/voice/whatever.wav",
                        "filename": "a.wav",
                        "duration": 15,
                        "authorized_by": "u1",
                        "agreement_snapshot": "授权原文",
                    },
                )
            assert r.status_code == 400, r.text
            assert "已有音色" in r.json()["detail"]
            # 原记录没被覆盖
            row = await service.get_record(shop_id)
            assert row is not None and row.voice_id == "cosy-existing-001"
        finally:
            importlib.reload(main_module)
    finally:
        await service.delete_record(shop_id, also_remote=False, force=True)


# --------------------------------------------------------------------------- #
# A1：公网回源（PUBLIC_BASE_URL）—— 方案 A 的核心约束
# --------------------------------------------------------------------------- #


def test_public_base_url_missing_raises_instead_of_faking():
    """★ 缺 PUBLIC_BASE_URL 必须**显式报错**，不能拼出 localhost 假装能用。

    CosyVoice 的服务端会主动来拉这个 URL —— 填 localhost 等于让它去拉
    它自己的 127.0.0.1，必然失败。与其静默产生一个「看起来对的错 URL」，
    不如当场报错并说明原因（项目铁律：失败要显式给原因，不静默兜底）。
    """
    from modules.voice_clone import service
    from modules.voice_clone.client import VoiceCloneError

    with pytest.raises(VoiceCloneError) as ei:
        service.sample_public_url("/static/voice/a.wav", base_url="")
    msg = str(ei.value)
    assert "PUBLIC_BASE_URL" in msg
    assert "公网" in msg

    # 只有空白字符也算未配置
    with pytest.raises(VoiceCloneError):
        service.sample_public_url("/static/voice/a.wav", base_url="   ")


def test_public_base_url_joins_cleanly():
    """配置了 base_url 时必须拼成合法 URL，且**不产生双斜杠**。

    尾部斜杠处理不当会得到 `https://x.com//static/voice/a.wav` ——
    部分服务端会 404，而且是那种「看起来一模一样」的难查错误。
    """
    from modules.voice_clone import service

    assert (
        service.sample_public_url("/static/voice/a.wav", base_url="https://api.example.com")
        == "https://api.example.com/static/voice/a.wav"
    )
    # 带尾部斜杠 → 不能拼出双斜杠
    assert (
        service.sample_public_url("/static/voice/a.wav", base_url="https://api.example.com/")
        == "https://api.example.com/static/voice/a.wav"
    )


def test_config_exposes_require_public_url_flag():
    """★ 后端必须把「是否已配公网地址」告诉前端。

    前端据此在面板上给出前置提示（而不是让老板点到最后一步才报错）。
    这个信号与 sample_public_url 的抛错行为是**同一判据的两处体现**，
    任何一处单独改动都会造成「前端说能点、后端一点就报错」的错配。
    """
    import asyncio

    from core.config import config
    from modules.voice_clone.router import voice_config

    original = config.public_base_url
    try:
        config.public_base_url = ""
        cfg = asyncio.get_event_loop().run_until_complete(voice_config())
        assert cfg["sample_limits"]["require_public_url"] is True

        config.public_base_url = "https://api.example.com"
        cfg = asyncio.get_event_loop().run_until_complete(voice_config())
        assert cfg["sample_limits"]["require_public_url"] is False
    finally:
        config.public_base_url = original


def test_static_mount_is_not_behind_business_auth():
    """★ `/static` 必须挂在 router 依赖之外（否则公网回源会被 401 挡住）。

    A1 方案的全部前提就是「DashScope 服务端能匿名 GET 到样本」。
    若哪天有人把 /static 改成走 BUSINESS_AUTH 的路由，本断言立刻红。
    """
    import importlib

    import main as main_module

    importlib.reload(main_module)

    # 收集挂载点（StaticFiles）与路由端点，确认 /static 走的是 mount 而非带鉴权的路由
    mounted_paths = {getattr(r, "path", "") for r in main_module.app.routes}
    assert "/static" in mounted_paths, f"/static 未挂载，现有: {sorted(mounted_paths)}"

    # mount 出来的子应用不带 dependencies（router 才是）→ 确认它在 mount 列表里
    static_route = next(
        (r for r in main_module.app.routes if getattr(r, "path", "") == "/static"), None
    )
    assert static_route is not None
    assert hasattr(static_route, "app"), "  /static 应通过 app.mount 挂载（StaticFiles）"


# ===========================================================================
# 公网回源：样本镜像（本地开发能跑通 CosyVoice 的关键）
#
# 背景：CosyVoice 的 url 是**服务端主动来拉**，本地 localhost 取不到 ⇒ 不解决就永远跑不通。
# 方案：样本落盘后额外推一份到云端静态目录，PUBLIC_BASE_URL 指向云端。
# 判据：本机无公网入口但云端有 ⇒ 云端只当"文件柜"，业务逻辑全留本地。
# ===========================================================================

@pytest.fixture
def mirror_unconfigured(monkeypatch):
    """把镜像主机置空，让下面三条用例**不依赖开发机的 .env**。

    ★ 实测踩出来的：原先直接读 ``config``，本地一旦配好镜像（这是跑通语音
    克隆的必要前提），这三条就集体变红；更糟的是 ``push_file`` 那条会**真的
    scp 一个文件到云端** —— 单元测试产生了网络副作用。测试必须自带环境。
    """
    from core.config import config

    monkeypatch.setattr(config, "voice_sample_mirror_ssh_host", "", raising=False)
    monkeypatch.setattr(config, "voice_sample_mirror_remote_dir", "", raising=False)
    return config


def test_mirror_disabled_by_default(mirror_unconfigured):
    """未配置镜像主机时 is_enabled() 必须为 False —— 这是"静默跳过"的开关。"""
    from modules.voice_clone import mirror

    assert mirror.is_enabled() is False, "未配置镜像主机时不应启用镜像"


def test_mirror_push_is_noop_when_disabled(mirror_unconfigured, tmp_path):
    """未启用时 push_file 返回空串（不抛错）—— 调用方据此决定用本地地址。"""
    from modules.voice_clone import mirror

    f = tmp_path / "a.wav"
    f.write_bytes(b"RIFF")
    assert mirror.push_file(f) == ""


def test_mirror_check_reports_disabled_reason(mirror_unconfigured):
    """体检端点必须明确说明"为什么不可用"，不能只返回 False。"""
    from modules.voice_clone import mirror

    r = mirror.check_connectivity()
    assert r["ok"] is False
    assert r["enabled"] is False
    assert "VOICE_SAMPLE_MIRROR_SSH_HOST" in r["reason"]


def test_persist_sample_does_not_fail_when_mirror_errors(monkeypatch, tmp_path):
    """★ 镜像失败不得阻塞本地落盘 —— 本地已可用，公网问题由 public_base_url 统一报。"""
    import asyncio
    from modules.voice_clone import service, mirror

    monkeypatch.setattr(mirror, "is_enabled", lambda: True)

    def _boom(*a, **k):
        raise mirror.MirrorError("模拟 scp 失败")

    monkeypatch.setattr(mirror, "push_file", _boom)

    url = asyncio.run(service.persist_sample(b"RIFF0000", "t.wav"))
    assert url.startswith("/static/voice/"), "本地落盘必须成功（镜像失败不阻塞）"


def test_persist_sample_pushes_to_mirror_when_enabled(monkeypatch, tmp_path):
    """启用镜像时，落盘后必须真的调用 push_file。"""
    import asyncio
    from modules.voice_clone import service, mirror

    pushed = []
    monkeypatch.setattr(mirror, "is_enabled", lambda: True)
    monkeypatch.setattr(mirror, "push_file", lambda p, **k: pushed.append(p) or "/remote/x.wav")

    asyncio.run(service.persist_sample(b"RIFF1111", "m.wav"))
    assert len(pushed) == 1, "应调用一次 push_file"


def test_config_reports_public_not_ready_without_base_url(monkeypatch):
    """★ 未配 PUBLIC_BASE_URL 时，体检必须报 not ready 并给原因（提前暴露，不等点克隆）。"""
    import asyncio
    from modules.voice_clone import router as vc_router

    out = asyncio.run(vc_router.voice_config())
    assert "public_ready" in out, "config 必须暴露 public_ready"
    assert "public_reason" in out, "config 必须暴露 public_reason"
    assert "mirror" in out, "config 必须暴露镜像体检结果"


# ===========================================================================
# 对话播报（speak）：把 Agent 回复念出来
#
# 背景：对话框右上角加喇叭开关，打开后店秘书的回复**自动朗读**（复用已克隆音色）。
# 两条核心约束，也正是「不能直接复用 /preview」的理由：
#   1. /preview 会回写 preview_text（试听样例）→ 播报会把用户的样例冲掉
#   2. 对话正文是 markdown → 原样丢给 TTS 会把 ** | 反引号逐个念出来
# ===========================================================================


def test_speech_text_strips_markdown_markers():
    """★ 回归：``**粗体**`` 的星号必须消失，否则 TTS 念成「星号星号店秘书星号星号」。"""
    from modules.voice_clone.service import to_speech_text

    out = to_speech_text("我是 **店秘书**，正在为您分析...")
    assert "**" not in out
    assert "店秘书" in out


def test_speech_text_drops_code_and_urls_but_keeps_anchor_text():
    """代码块整体丢弃（念代码无意义且必念错）；链接只留锚文本、URL 丢掉。"""
    from modules.voice_clone.service import to_speech_text

    out = to_speech_text("```python\nprint('hi')\n```\n结论：看 [这份文档](https://x.com/a) 即可。")
    assert "print" not in out
    assert "https://" not in out
    assert "这份文档" in out
    assert "结论" in out


def test_speech_text_drops_emoji_and_table_separator():
    """★ emoji 与 markdown 表格分隔行都不能被念出来（实测会念成「大括号笑脸」）。"""
    from modules.voice_clone.service import to_speech_text

    out = to_speech_text("> 💡 提示：\n\n| 项目 | 值 |\n| --- | --- |\n| ACoS | 32% |")
    assert "💡" not in out
    assert "---" not in out
    assert "ACoS" in out


def test_speech_text_empty_stays_empty():
    """★ 空正文必须返回空串（由调用方显式报错），**不得**编造一句兜底文案。"""
    from modules.voice_clone.service import to_speech_text

    assert to_speech_text("") == ""
    assert to_speech_text("   \n  ") == ""
    assert to_speech_text("💡 ✅ ★") == ""


def test_speech_text_clips_at_sentence_boundary():
    """超长时截到句末（不硬断在词中间），且不超过上限。"""
    from modules.voice_clone.service import MAX_SPEECH_CHARS, to_speech_text

    out = to_speech_text("这是一句用来测试截断的话。" * 100)
    assert len(out) <= MAX_SPEECH_CHARS
    assert out.endswith("。"), "应截在句末标点处"


@pytest.mark.asyncio
async def test_speak_does_not_overwrite_preview_text(monkeypatch):
    """★★ 核心回归：对话播报**不得**回写 ``preview_text``。

    试听文案是用户在面板里选定的样例；播报的语义是「这一轮回复的原话」。
    若两者共用写回，老板每跟店秘书说一句话，自己的试听样例就被冲掉一次 ——
    这正是 speak 必须单独开一条路径（而不是复用 /preview）的原因。
    """
    shop_id = "store_unittest_speak"
    from modules.voice_clone import service
    from modules.voice_clone.router import speak_voice

    await service.upsert_record(
        shop_id,
        voice_id="cosy-speak-001",
        target_model="cosyvoice-v3-flash",
        status="ready",
        preview_text="您好，很高兴为您服务",
    )

    async def fake_synthesize(text, *, voice_id, model="", **kwargs):
        return "https://dashscope.example.com/tmp/out.mp3"

    async def fake_persist(url):
        return "/static/voice/spoken_probe.mp3"

    monkeypatch.setattr(service.client, "synthesize", fake_synthesize)
    monkeypatch.setattr(service, "persist_remote_audio", fake_persist)

    raw = "我是 **店秘书**，为您服务。"
    try:
        out = await speak_voice(text=raw, target_model="", shop_id=shop_id)

        assert out["audio_url"] == "/static/voice/spoken_probe.mp3"
        assert "**" not in out["spoken_text"], "播报正文必须已净化"
        assert out["truncated"] is False
        assert out["source_chars"] == len(raw)

        row = await service.get_record(shop_id)
        assert row.preview_text == "您好，很高兴为您服务", "试听文案被播报正文覆盖了"
    finally:
        await service.delete_record(shop_id, also_remote=False, force=True)


@pytest.mark.asyncio
async def test_speak_reports_truncation_instead_of_silently_cutting(monkeypatch):
    """★ 超过朗读上限时如实回报 ``truncated`` —— 不静默只念一半。"""
    shop_id = "store_unittest_speakclip"
    from modules.voice_clone import service
    from modules.voice_clone.router import speak_voice

    await service.upsert_record(
        shop_id, voice_id="cosy-speak-clip", target_model="cosyvoice-v3-flash", status="ready"
    )

    async def fake_synthesize(text, *, voice_id, model="", **kwargs):
        return "https://dashscope.example.com/tmp/long.mp3"

    async def fake_persist(url):
        return "/static/voice/long_probe.mp3"

    monkeypatch.setattr(service.client, "synthesize", fake_synthesize)
    monkeypatch.setattr(service, "persist_remote_audio", fake_persist)

    try:
        out = await speak_voice(
            text="这是一句会被反复重复以超过朗读上限的话。" * 40,
            target_model="",
            shop_id=shop_id,
        )
        assert out["truncated"] is True
        assert out["source_chars"] > len(out["spoken_text"])
    finally:
        await service.delete_record(shop_id, also_remote=False, force=True)


@pytest.mark.asyncio
async def test_speak_errors_when_no_voice_instead_of_falling_back():
    """★ 没有可用音色时必须**明确报错并给原因**，不得静默换系统默认音色顶上。"""
    from fastapi import HTTPException

    from modules.voice_clone.router import speak_voice

    with pytest.raises(HTTPException) as ei:
        await speak_voice(text="你好", target_model="", shop_id="store_unittest_novoice")
    assert ei.value.status_code == 400
    assert "尚未创建音色" in str(ei.value.detail)


@pytest.mark.asyncio
async def test_speak_rejects_reply_with_nothing_to_read(monkeypatch):
    """★ 纯卡片/纯符号的回复：显式报错，而不是发起一次注定读不出内容的合成。"""
    shop_id = "store_unittest_speakempty"
    from fastapi import HTTPException

    from modules.voice_clone import service
    from modules.voice_clone.router import speak_voice

    await service.upsert_record(
        shop_id, voice_id="cosy-speak-empty", target_model="cosyvoice-v3-flash", status="ready"
    )
    called: list[str] = []

    async def spy(text, *, voice_id, model="", **kwargs):
        called.append(text)
        return "https://dashscope.example.com/tmp/x.mp3"

    monkeypatch.setattr(service.client, "synthesize", spy)
    try:
        with pytest.raises(HTTPException) as ei:
            await speak_voice(text="💡 ✅ ★", target_model="", shop_id=shop_id)
        assert ei.value.status_code == 400
        assert "没有可朗读的正文" in str(ei.value.detail)
        assert called == [], "不应发起合成调用"
    finally:
        await service.delete_record(shop_id, also_remote=False, force=True)


# ===========================================================================
# 分句流水线（P0）：/speak-plan
#
# 背景：整段合成 160 字实测要等 5.2s 才出声（240 字约 8s），加 700ms 防抖后
# 「等太久了」非常明显。改成「切句 → 逐段合成 → 逐段无缝播放」后，首声只等第一段
# （实测 1.65s）。代价是前端必须能在「文本还在长」的时候反复重算计划，
# 并用 raw_end 游标保证「已念过的段不重念、没念过的段不跳过」。
# 下面几条就是把这个**游标协议**钉死的 —— 它们全部是「不变量」测试，
# 不依赖具体切法（改了段长阈值也不会误红），只锁住正确性。
# ===========================================================================

#: 覆盖各种会把切句搞乱的 markdown 形态（表格 / 代码块 / emoji / 无标点 / 超长）
_PLAN_CASES = {
    "multiline_bold": "**重点**：标题太长。\n第二行内容。第三行收尾",
    "table": (
        "下面是对比：\n\n"
        "| 项目 | 值 |\n| --- | --- |\n| ACoS | 32% |\n| CTR | 1.1% |\n\n"
        "结论：ACoS 偏高。建议降价。"
    ),
    "code_fence": "先看代码：\n\n```python\nprint('hi')\n```\n\n然后执行。结果正常",
    "emoji_mix": "建议如下 💡：\n- 第一点 ✅\n- 第二点 ⚠️\n最后总结。完成",
    "links": "参考 [亚马逊规则](https://example.com/x) 和 https://foo.bar/baz 两条。注意合规",
    "no_punct": "这是一个没有任何句末标点的超长句子用来测试尾部碎片与长度上限的行为边界情况",
    "single_short": "好的",
    "comma_only": "甲，乙，丙，丁，戊，己，庚，辛，壬，癸，子，丑，寅，卯，辰",
    "long_single": "第一段" * 3 + "，" + "第二段" * 30 + "。后面还有一句。",
    "very_long": "".join(f"这是第{i}句，用来把总长推过上限。" for i in range(1, 61)),
    "real_secretary": (
        "收到，我把这条 listing 完整过了一遍，下面按优先级说。"
        "第一，标题的问题最大。现在前五十个字符里只有品牌和品类，"
        "最核心的搜索词被压到了第六十个字符之后，手机端根本看不到。"
        "第二，五点描述的顺序和买家搜索意图不一致，"
        "买家最关心的降噪深度被放在了第三条，应该提到第一条。"
        "第三，主图全是白底图，缺少一张使用场景图。"
        "我先改标题和前五点，改完给您过目。"
    ),
}


def _incremental_run(markdown: str) -> str:
    """照前端的方式跑一遍：文本一个字一个字变长，流式期间只念 ``stable`` 的段，
    流结束后再把剩下的（含结尾碎片）补上。返回**实际会被念出来的全文**。

    这段代码就是前端 ``voiceTts`` store 里游标逻辑的等价物 ——
    它一旦和 batch 版本不一致，就意味着用户会听到重复或缺失的内容。
    """
    from modules.voice_clone.service import split_speech_segments

    spoken: list[str] = []
    cursor = 0
    for cut in range(1, len(markdown) + 1):
        for seg in split_speech_segments(markdown[:cut]):
            if seg["stable"] and seg["raw_end"] > cursor:
                spoken.append(seg["text"])
                cursor = seg["raw_end"]
    for seg in split_speech_segments(markdown):
        if seg["raw_end"] > cursor:
            spoken.append(seg["text"])
            cursor = seg["raw_end"]
    return "".join(spoken)


def test_speech_plan_segments_join_to_the_same_text_as_whole_cleaning():
    """★ 段净化拼接 == 整段净化。

    分句**不得**演变成「另写一套净化逻辑」：每段仍走同一个 ``to_speech_text``。
    超上限时两者允许差在截断点上（一个按段截、一个按全文截），
    但必须互为前缀 —— 否则就是有的内容被念成了别的样子。
    """
    from modules.voice_clone.service import speech_plan, to_speech_text

    for name, md in _PLAN_CASES.items():
        plan = speech_plan(md)
        joined = "".join(s["text"] for s in plan["segments"])
        whole = to_speech_text(md, max_chars=10**9)
        if plan["truncated"]:
            assert joined.startswith(whole) or whole.startswith(joined), f"{name}: 截断处对不上"
        else:
            assert joined == whole, f"{name}: 段拼接与整段净化不一致"


def test_speech_plan_segments_stay_frozen_as_the_text_grows():
    """★★ 游标协议的前提：**``stable`` 的段，在原文变长后必须逐字重现**。

    前端靠 ``raw_end`` 游标去重。只要有一个「当初标了 stable、后来内容却变了」的段，
    前端就会算出错误的游标 —— 要么跳过它不念（丢内容），要么下一轮再念一遍（重复）。
    这里对每一段前缀都比对一次。
    """
    from modules.voice_clone.service import split_speech_segments

    for name, md in _PLAN_CASES.items():
        for cut in range(1, len(md) + 1):
            partial = split_speech_segments(md[:cut])
            full = split_speech_segments(md)
            for seg in partial:
                if not seg["stable"]:
                    continue
                same = [f for f in full if f["raw_end"] == seg["raw_end"]]
                assert same, f"{name}@cut{cut}: stable 段在原文变长后消失了（游标会丢内容）"
                assert same[0]["text"] == seg["text"], (
                    f"{name}@cut{cut}: stable 段内容变了（游标会重复朗读）"
                )


def test_speech_plan_incremental_run_equals_single_full_plan():
    """★★★ 最强的一条：模拟前端流式跑一遍，念出来的必须与「一次算完」完全一致。

    这条同时覆盖「丢内容」和「重复念」两种事故，且与切法无关 ——
    它断言的是**用户最终听到的东西**，不是某一段的长度或边界。
    """
    from modules.voice_clone.service import speech_plan

    for name, md in _PLAN_CASES.items():
        spoken = _incremental_run(md)
        batch = "".join(s["text"] for s in speech_plan(md)["segments"])
        assert spoken == batch, f"{name}: 流式跑出来与一次算完不一致（丢内容或重复念）"


def test_speech_plan_only_the_last_segment_may_be_unstable():
    """★ 只有最后一段允许 ``stable=False``（它含仍在增长的尾巴）。

    若中间段也不稳定，前端「取前 k 段」的游标假设就不成立了。
    """
    from modules.voice_clone.service import split_speech_segments

    for name, md in _PLAN_CASES.items():
        segs = split_speech_segments(md)
        bad = [i for i, s in enumerate(segs) if not s["stable"] and i != len(segs) - 1]
        assert not bad, f"{name}: 非末段被标为未定型，位置 {bad}"


def test_speech_plan_merges_segments_too_short_to_keep_up():
    """★ 短段不许单独成段 —— 这是实测出来的硬约束，不是审美。

    实测：合成耗时 ≈ 0.9s + 0.025s/字、播放 ≈ 0.2s/字。解 ``0.9 + 0.025N < 0.2N``
    得 **N > 5.1 字**：段短于这个数时「合成比播放还慢」，双缓冲会被抽干、段间接不上
    （实测「请稍等。」4 字：合成 821ms vs 播放 800ms，余量 **-0.02s**）。
    """
    from modules.voice_clone.service import MIN_SEGMENT_CHARS, split_speech_segments

    # 「请稍等。」单独成句、只有 4 字 —— 必须被并进相邻段
    md = (
        "好的，我马上处理这个店铺的广告数据。请稍等。"
        "以下是详细的分析结果，请注意查看每一项指标的变化情况。"
    )
    segs = split_speech_segments(md)
    assert segs, "不该切出空计划"
    for i, seg in enumerate(segs[:-1]):
        assert seg["chars"] >= MIN_SEGMENT_CHARS, (
            f"第 {i} 段只有 {seg['chars']} 字（< {MIN_SEGMENT_CHARS}），"
            f"合成会慢于播放、段间会露出空隙：{seg['text']!r}"
        )
    assert not any(s["text"] == "请稍等。" for s in segs), "4 字段不该单独成段"


def test_speech_plan_first_segment_is_the_smallest():
    """★ 首段要抢首包：首声延迟**只由第一段决定**，所以首段上限比后续段小。"""
    from modules.voice_clone.service import (
        FIRST_SEGMENT_CHARS,
        MAX_SEGMENT_CHARS,
        split_speech_segments,
    )

    assert FIRST_SEGMENT_CHARS < MAX_SEGMENT_CHARS
    segs = split_speech_segments(_PLAN_CASES["real_secretary"])
    assert len(segs) > 1, "用例本身应能切出多段"
    assert segs[0]["chars"] < sum(s["chars"] for s in segs[1:]) / len(segs[1:])


def test_speech_plan_reports_truncation_over_the_global_cap():
    """★ 超上限时如实回报 ``truncated``，且计划本身不超上限（前端据此告知用户）。"""
    from modules.voice_clone.service import MAX_SPEECH_CHARS, speech_plan

    plan = speech_plan(_PLAN_CASES["very_long"])
    assert plan["truncated"] is True
    assert plan["plan_chars"] <= MAX_SPEECH_CHARS
    assert plan["clean_chars"] > plan["plan_chars"]
    assert plan["source_chars"] == len(_PLAN_CASES["very_long"])


def test_speech_plan_empty_stays_empty():
    """★ 空/纯符号正文 → 空计划（由调用方显式报错），**不编造兜底文案**。"""
    from modules.voice_clone.service import speech_plan

    assert speech_plan("")["segments"] == []
    assert speech_plan("   \n  ")["segments"] == []
    assert speech_plan("💡 ✅ ★")["segments"] == []


def test_to_speech_text_is_idempotent_on_cleaned_segments():
    """★ 管道的前提：每一段交给 ``/speak`` 合成时会被**再净化一次**（同一个函数）。

    所以「对已净化的文本再净化」必须是恒等变换，否则分段合成与整段合成就不是一回事。
    （若哪天不成立，正确做法是给 ``/speak`` 加「已净化」入参，而不是把这段测试删掉。）
    """
    from modules.voice_clone.service import split_speech_segments, to_speech_text

    for name, md in _PLAN_CASES.items():
        for i, seg in enumerate(split_speech_segments(md)):
            assert to_speech_text(seg["text"]) == seg["text"], f"{name} 第 {i} 段双重净化后变了"


@pytest.mark.asyncio
async def test_speak_plan_endpoint_is_pure_calculation(monkeypatch):
    """★ ``/speak-plan`` 只算不合成：不查库、不调 DashScope、不落库。

    这条同时防止一种退路：有人图省事把分句又并回「整段合成」，
    那样首声延迟会从 ~1.6s 退回 ~5s，而接口形状看起来还是对的。
    """
    from modules.voice_clone import service
    from modules.voice_clone.router import speak_plan

    synth_calls: list[str] = []

    async def spy(text, *, voice_id, model="", **kwargs):
        synth_calls.append(text)
        return "https://dashscope.example.com/tmp/x.mp3"

    monkeypatch.setattr(service.client, "synthesize", spy)

    out = await speak_plan(text="我是 **店秘书**，正在为您分析。请稍等。")
    assert synth_calls == [], "/speak-plan 不该发起任何合成调用"
    assert out["segments"], "应切出至少一段"
    assert all("**" not in s["text"] for s in out["segments"]), "段文本必须已净化"
    assert out["truncated"] is False
    assert out["source_chars"] == len("我是 **店秘书**，正在为您分析。请稍等。")
