"""兜底门禁：测试套件不得产生**真实网络出网**（HTTP 与子进程两面）。

## 为什么单独建一个文件

`conftest._no_real_llm` 拦 HTTP，`conftest._no_real_network_subprocess` 拦网络类子进程。
两条兜底都是 autouse 的，**但它们自己也需要被判据钉住** —— 否则哪天被
「顺手删掉 / 改宽」不会有人发现。本文件就是那双眼睛。

## 事故背景（第 243 轮）

全量回归「卡在收尾」十几分钟的真因：某条用例漏挂隔离夹具 ⇒
`mirror.check_connectivity()` 真起 `ssh root@<生产服务器> "echo ok"`
（开发机 `.env` 真配了 host + 私钥）。
而它是**同步**调用却写在 `async def` 端点里 ⇒ 阻塞整个事件循环（本仓 loop scope = session）
⇒ 进度条冻结，看起来像「某个用例卡住」，实际在等 socket 超时。

判据：测试必须自带环境，**不得依赖开发机 .env**。
"""
from __future__ import annotations

import subprocess
import sys

import pytest


# ===========================================================================
# ① 结构性兜底：网络类子进程必须被拦
# ===========================================================================


def test_ssh_and_scp_subprocess_are_blocked():
    """★ 网络类子进程必须被拦 —— 用**真命令名**证明拦的是行为，不是字符串。"""
    for argv in (
        ["ssh", "-o", "BatchMode=yes", "example.com", "echo ok"],
        ["scp", "a.txt", "example.com:/tmp/"],
        ["curl", "-s", "https://example.com"],
    ):
        with pytest.raises(FileNotFoundError):
            subprocess.run(argv, capture_output=True, timeout=10)


def test_popen_direct_call_is_also_blocked():
    """★ 兜底挂在 `Popen` 上 ⇒ `check_output` / `call` 等写法同样被拦。"""
    with pytest.raises(FileNotFoundError):
        subprocess.check_output(["ssh", "example.com", "true"], timeout=10)


def test_python_subprocess_is_not_blocked():
    """★ 反例：**不能**误伤跑子进程的门禁用例。

    本仓有多处 `subprocess.run([sys.executable, ...])` 用来跑门禁 / 迁移 / 子探针
    （`test_ci_gate_coverage` / `test_schema_parity` / `test_skill_injection`）。
    这条就是「只拦网络类」与「拦掉全部 subprocess」的分界线。
    """
    r = subprocess.run(
        [sys.executable, "-c", "print('ok')"],
        capture_output=True, text=True, timeout=60,
    )
    assert r.returncode == 0
    assert "ok" in (r.stdout or "")


# ===========================================================================
# ② 第一层兜底：测试里镜像默认关闭（自带环境，不读开发机 .env）
# ===========================================================================


def test_mirror_is_disabled_by_default_in_tests():
    """★ 测试环境必须默认关闭样本镜像。"""
    from modules.voice_clone import mirror

    assert mirror.is_enabled() is False, (
        "测试里镜像未默认关闭 —— 会真 ssh/scp 到 .env 里配的生产服务器"
    )


def test_voice_config_does_not_shell_out(monkeypatch):
    """★ 体检端点不得真起子进程（用**哨兵**证明「一次都没调过」）。

    这是形态判据：值判据（`public_ready` 算出来是什么）会被另一份实现凑出来，
    「到底有没有起 Popen」才是第 243 轮那次卡死的真判据。
    """
    import asyncio

    from modules.voice_clone import router as vc_router

    calls = []
    real_popen = subprocess.Popen

    def spy(*args, **kwargs):
        calls.append(args[0] if args else kwargs.get("args"))
        return real_popen(*args, **kwargs)

    monkeypatch.setattr(subprocess, "Popen", spy)
    out = asyncio.run(vc_router.voice_config())

    assert calls == [], f"voice_config 不应起子进程，实际调了：{calls}"
    assert "mirror" in out


# ===========================================================================
# ③ 第二层兜底独立生效 + 生产侧 TTL 缓存（P2）
# ===========================================================================


def test_mirror_probe_is_blocked_even_when_enabled(monkeypatch):
    """★ 第二层兜底**独立**生效：即使把镜像显式打开，体检也出不了网。

    （证明两层各自有效，而不是「第一层关了所以第二层从未被验证」。）
    ★ 自带环境：用 `.invalid` 域名，不读开发机 `.env` 的真实主机。
    ★ 断言的是「拿不到真连通」而非「抛错」—— `_probe_connectivity` 会把
      拦下来的 FileNotFoundError 翻成可展示的 reason，这正是设计意图。
    """
    from core.config import config
    from modules.voice_clone import mirror

    monkeypatch.setattr(config, "voice_sample_mirror_ssh_host", "root@example.invalid", raising=False)
    monkeypatch.setattr(mirror, "is_enabled", lambda: True)
    mirror.reset_connectivity_cache()

    r = mirror.check_connectivity()

    assert r["ok"] is False, "兜底失效：测试里竟然连上了真实 ssh"
    assert r["reason"], "失败必须给可展示的原因，不能是空串"


def test_connectivity_cache_avoids_repeated_probe(monkeypatch):
    """★ 30s TTL 缓存必须真的省掉重复 ssh（同配置只探一次）。

    动机：`GET /voice-clone/config` 每次打开面板都会被调，而体检要真起 ssh。
    没有缓存 ⇒ 面板反复打开 = 反复 ssh（网络抖动时每次最长 15s）。
    """
    from core.config import config
    from modules.voice_clone import mirror

    monkeypatch.setattr(config, "voice_sample_mirror_ssh_host", "root@example.invalid", raising=False)
    monkeypatch.setattr(mirror, "is_enabled", lambda: True)
    monkeypatch.setattr(config, "voice_sample_mirror_remote_dir", "/tmp/vm", raising=False)
    mirror.reset_connectivity_cache()

    seen = []
    real_probe = mirror._probe_connectivity

    def spy(cfg):
        seen.append(cfg.voice_sample_mirror_ssh_host)
        return real_probe(cfg)

    monkeypatch.setattr(mirror, "_probe_connectivity", spy)

    mirror.check_connectivity()
    mirror.check_connectivity()
    mirror.check_connectivity()
    assert len(seen) == 1, f"缓存失效：探了 {len(seen)} 次（应 1 次）"

    # use_cache=False 必须绕过缓存
    mirror.check_connectivity(use_cache=False)
    assert len(seen) == 2, "use_cache=False 应强制重探"

    # 换主机 ⇒ 缓存 key 变 ⇒ 必须重探（否则改了配置还看旧结论）
    monkeypatch.setattr(config, "voice_sample_mirror_ssh_host", "root@other.invalid", raising=False)
    mirror.check_connectivity()
    assert len(seen) == 3, "换了主机必须重新探（缓存 key 应含 host）"


# ===========================================================================
# ④ 生产侧：体检不得阻塞事件循环（P2 的 asyncio.to_thread）
# ===========================================================================


def test_voice_config_does_not_block_event_loop(monkeypatch):
    """★ 体检必须放线程池：换一个**同步阻塞**的桩，断言事件循环仍在推进。

    这是**行为**判据，不是「源码里有没有 to_thread」的字符串判据 ——
    后者会被注释 / 同名变量骗过，也管不住「换个写法又变回同步」。

    判据：`voice_config()` 里若有 `await to_thread(...)`，等待期间心跳任务能跑很多次；
    若改回同步调用（第 243 轮修掉的那一版），心跳一次都轮不上。
    """
    import asyncio
    import time

    from modules.voice_clone import mirror
    from modules.voice_clone import router as vc_router

    def slow_probe(*args, **kwargs):
        # 同步 sleep：只有被丢进线程池，才不会卡住 loop
        time.sleep(0.6)
        return {"ok": False, "enabled": False, "reason": "桩"}

    monkeypatch.setattr(mirror, "check_connectivity", slow_probe)

    async def _main():
        ticks = 0

        async def heartbeat():
            nonlocal ticks
            while True:
                await asyncio.sleep(0.01)
                ticks += 1

        hb = asyncio.create_task(heartbeat())
        try:
            await vc_router.voice_config()
        finally:
            hb.cancel()
        return ticks

    ticks = asyncio.run(_main())
    assert ticks >= 10, (
        f"体检阻塞了事件循环（0.6s 内只跑了 {ticks} 次心跳，应 ≥10）⇒ "
        "voice_config 必须用 asyncio.to_thread 调这个同步的 check_connectivity"
    )
