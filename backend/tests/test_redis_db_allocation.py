# -*- coding: utf-8 -*-
"""Redis 库号分配的门禁（对应网站管理员 P2-1）。

背景：线上只有 127.0.0.1:6379 一个 redis-server，两站共用；eCommerce 原本在 db0。
运维建议迁到 db3 并把分配写进 .env.example，但真源**不止一处**（运维只看到一处）：

    backend/.env.example                 REDIS_URL
    backend/core/config.py               Settings.redis_url 的**声明默认值**
                                         （env 没配时就用它 —— 只改 example 的
                                           典型症状是「线上对了、新环境又落回 0」）
    docker-compose.yml                   backend / worker / beat 三个服务各一行
    .github/workflows/ci.yml             它自己写着「与 .env.example 对齐」

为什么必须门禁：库号是「配错不报错」的典型 —— redis 照样连得上、限流照样生效，
只是数据写进了别人的库。要到「Celery 上线后队列与缓存抢同一库」或
「切库时丢了 jti 黑名单 ⇒ 已撤销的 token 复活」才会暴露，而那时已经很难归因。

分配表（本项目占用 3）：
    0  eEducation 现状（0 是「谁都没配」的默认落点，本项目不占）
    1  Celery broker
    2  Celery result
    3  本项目运行时（jti 黑名单 + 限流计数）
"""
from __future__ import annotations

import re
from pathlib import Path

import pytest

BACKEND = Path(__file__).resolve().parent.parent
ROOT = BACKEND.parent
EXPECTED_CELERY_BROKER = 1
EXPECTED_CELERY_RESULT = 2


def _lib_of(url: str) -> int:
    """redis://host:port/N -> N。不带 /N 时 redis 默认落到 0（不能当「没配」）。"""
    url = url.strip()
    m = re.search(r"://[^/]+/(\d+)\s*$", url)
    if m:
        return int(m.group(1))
    assert re.match(r"redis://[^/]+$", url), "无法解析的 redis url：%r" % url
    return 0


def _from_env_example(key: str) -> int:
    text = (BACKEND / ".env.example").read_text(encoding="utf-8")
    pairs = dict(
        re.findall(r"^([A-Z_]+)=(.*)$", text, re.M)
    )
    assert key in pairs, ".env.example 缺 %s —— 判据无从比较" % key
    return _lib_of(pairs[key])


def _from_config_default(field: str) -> int:
    from core.config import Settings

    f = Settings.model_fields[field]
    assert isinstance(f.default, str) and f.default, (
        "%s 没有字符串默认值（改成必填了？）—— 判据失效，请更新本文件" % field)
    return _lib_of(f.default)


def _from_compose() -> list[int]:
    text = (ROOT / "docker-compose.yml").read_text(encoding="utf-8")
    hits = re.findall(r"^\s*REDIS_URL:\s*(\S+)\s*$", text, re.M)
    assert hits, "docker-compose.yml 里一个 REDIS_URL 都没扫到 —— 判据空跑"
    return [_lib_of(h) for h in hits]


def _from_ci() -> int:
    text = (ROOT / ".github/workflows/ci.yml").read_text(encoding="utf-8")
    hits = re.findall(r"^\s*REDIS_URL:\s*(\S+)\s*$", text, re.M)
    assert hits, "ci.yml 里没扫到 REDIS_URL —— 判据空跑"
    assert len(hits) == 1, "ci.yml 出现 %d 处 REDIS_URL，需人工确认哪个生效" % len(hits)
    return _lib_of(hits[0])


# ---------- D1：四处真源必须同号 ----------

def test_d1_all_four_sources_agree() -> None:
    eco = _from_env_example("REDIS_URL")
    sources = {
        ".env.example": eco,
        "config.py 默认值": _from_config_default("redis_url"),
        "ci.yml": _from_ci(),
    }
    for i, n in enumerate(_from_compose(), 1):
        sources["docker-compose.yml#%d" % i] = n

    distinct = set(sources.values())
    assert len(distinct) == 1, (
        "Redis 库号在真源之间分叉（实际 %s）：\n  %s\n"
        "只改一处等于没改 —— 没配 env 的环境会自动落回声明默认值。"
        % (sorted(distinct),
           "\n  ".join("%-24s /%d" % kv for kv in sources.items())))


# ---------- D2：与 Celery 的库不能重叠 ----------

def test_d2_not_colliding_with_celery() -> None:
    eco = _from_env_example("REDIS_URL")
    broker = _from_env_example("CELERY_BROKER_URL")
    result = _from_env_example("CELERY_RESULT_BACKEND")
    # config.py 的默认值也必须一致，否则「env 缺两行」时会漂到别处
    assert _from_config_default("celery_broker_url") == broker, (
        "CELERY_BROKER_URL 在 .env.example(%d) 与 config.py 默认值(%d) 分叉"
        % (broker, _from_config_default("celery_broker_url")))
    assert _from_config_default("celery_result_backend") == result, (
        "CELERY_RESULT_BACKEND 在 .env.example(%d) 与 config.py 默认值(%d) 分叉"
        % (result, _from_config_default("celery_result_backend")))

    used = {broker: "CELERY_BROKER_URL", result: "CELERY_RESULT_BACKEND"}
    assert eco not in used, (
        "本项目 REDIS_URL=/{} 与 {} 撞库 —— Celery 一旦启用，缓存/限流会与队列"
        "抢同一个键空间（flushdb、--scan、dbsize 全部互相污染）"
        .format(eco, used[eco]))


# ---------- D3：不得占用 0 ----------

def test_d3_not_using_default_db0() -> None:
    eco = _from_env_example("REDIS_URL")
    assert eco != 0, (
        "本项目仍在 db0。db0 是「谁都没配」的默认落点：任何一个忘记配置的服务"
        "都会静默落进来，与我们的 jti 黑名单和限流计数共用键空间。"
        "本项目应显式占用 3（0 留给 eEducation 现状）")


# ---------- D4：库号必须合法 ----------

def test_d4_library_index_in_range() -> None:
    for key in ("REDIS_URL", "CELERY_BROKER_URL", "CELERY_RESULT_BACKEND"):
        n = _from_env_example(key)
        assert 0 <= n <= 15, (
            "%s=/%d 超出 redis 默认 16 库范围（databases 16）；"
            "SELECT 会直接报 ERR DB index is out of range" % (key, n))


# ---------- D5：broker 与 result 不能同库 ----------

def test_d5_broker_and_result_differ() -> None:
    broker = _from_env_example("CELERY_BROKER_URL")
    result = _from_env_example("CELERY_RESULT_BACKEND")
    assert broker != result, (
        "CELERY_BROKER_URL 与 CELERY_RESULT_BACKEND 同为 /%d —— result 的键会被"
        "broker 的队列键空间混在一起，排查时无法区分，清缓存会连带清掉队列" % broker)
