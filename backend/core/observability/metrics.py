"""
轻量指标注册表（observability/metrics.py）

定位：
    给项目补一个「够用的」指标出口，按 Prometheus 文本格式暴露在 /metrics，
    可直接被 Prometheus / 夜莺 / 阿里云 ARMS 采集。

为什么**不**引入 prometheus_client：
    1. 它自带 multiprocess 模式对 FastAPI 多 worker 的支持很别扭（需要
       额外环境变量 + 目录），而本项目部署形态未定；
    2. 我们真正需要的只有「计数器 + 简单直方图」两件事，几百行能写完，
       且**零新依赖** —— 部署时少一个装不上的包就少一类事故；
    3. 自研版本可以把「路径归一化」这类项目特有的防基数爆炸逻辑写死在里面。
    若后续确实需要 Summary/Quantile/多进程聚合，再换 prometheus_client 即可，
    接口（inc / observe / render）是照着它的语义设计的，替换成本低。

★★ 基数（cardinality）是本模块最需要防的东西：
    `http_requests_total{path=...}` 若把原始 URL 当标签，/api/v1/spus/{uuid}
    会长出无数条时间序列，把监控打爆（Prometheus 侧叫 cardinality explosion）。
    因此 **所有路径标签必须过 normalize_path()**：UUID / store_xxx / 纯数字段
    统一替换为 :id。

线程安全：
    用可重入锁保护字典写入 —— 指标更新会出现在 asyncio 事件循环、
    线程池（asyncio.to_thread）与 Celery worker（同进程 solo 模式）三个位置。
"""

import math
import re
import threading
import time
from typing import Dict, Iterable, List, Optional, Tuple

# ====== 路径归一化（防基数爆炸）======

_UUID_RE = re.compile(
    r"[0-9a-fA-F]{8}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{12}"
)
# 业务侧自定义 ID：store_c3529ab1 / spu_1a2b / task_xxx（前缀 + 下划线 + 十六进制/字母数字）
_PREFIX_ID_RE = re.compile(r"\b(store|spu|task|prod|asset|mon|kb|doc|faq|pm)_[0-9a-zA-Z]{4,}\b")
# 纯数字段（/api/v1/plans/12）
_NUMERIC_RE = re.compile(r"(?<=/)\d+(?=/|$)")
# 32 位以上裸 hex（无分隔符的 ID）
_LONG_HEX_RE = re.compile(r"\b[0-9a-f]{20,}\b")


def normalize_path(path: str) -> str:
    """
    把真实路径压成低基数模板：
        /api/v1/spus/3f2a...-...  ->  /api/v1/spus/:id
        /api/v1/stores/store_c3529ab1  ->  /api/v1/stores/:id
        /api/v1/plans/12          ->  /api/v1/plans/:id
    """
    if not path:
        return "/"
    p = _UUID_RE.sub(":id", path)
    p = _PREFIX_ID_RE.sub(":id", p)
    p = _LONG_HEX_RE.sub(":id", p)
    p = _NUMERIC_RE.sub(":id", p)
    return p


# ====== 直方图桶（毫秒）======
# 覆盖「快接口 → 慢 LLM 接口」：5ms 到 30s
DEFAULT_BUCKETS: Tuple[float, ...] = (
    5.0, 10.0, 25.0, 50.0, 100.0, 250.0, 500.0, 1000.0,
    2500.0, 5000.0, 10000.0, 30000.0,
)


class _Counter:
    __slots__ = ("name", "help", "labelnames", "_values", "_lock")

    def __init__(self, name: str, help_: str, labelnames: Tuple[str, ...]):
        self.name = name
        self.help = help_
        self.labelnames = labelnames
        self._values: Dict[Tuple[str, ...], float] = {}
        self._lock = threading.Lock()

    def inc(self, amount: float = 1.0, **labels) -> None:
        key = tuple(str(labels.get(k, "")) for k in self.labelnames)
        with self._lock:
            self._values[key] = self._values.get(key, 0.0) + amount

    def render(self) -> List[str]:
        out = [f"# HELP {self.name} {self.help}", f"# TYPE {self.name} counter"]
        with self._lock:
            items = sorted(self._values.items())
        for key, val in items:
            out.append(f"{self.name}{_fmt_labels(self.labelnames, key)} {_fmt_num(val)}")
        return out


class _Gauge:
    __slots__ = ("name", "help", "labelnames", "_values", "_lock")

    def __init__(self, name: str, help_: str, labelnames: Tuple[str, ...]):
        self.name = name
        self.help = help_
        self.labelnames = labelnames
        self._values: Dict[Tuple[str, ...], float] = {}
        self._lock = threading.Lock()

    def set(self, value: float, **labels) -> None:
        key = tuple(str(labels.get(k, "")) for k in self.labelnames)
        with self._lock:
            self._values[key] = float(value)

    def inc(self, amount: float = 1.0, **labels) -> None:
        key = tuple(str(labels.get(k, "")) for k in self.labelnames)
        with self._lock:
            self._values[key] = self._values.get(key, 0.0) + amount

    def dec(self, amount: float = 1.0, **labels) -> None:
        self.inc(-amount, **labels)

    def render(self) -> List[str]:
        out = [f"# HELP {self.name} {self.help}", f"# TYPE {self.name} gauge"]
        with self._lock:
            items = sorted(self._values.items())
        for key, val in items:
            out.append(f"{self.name}{_fmt_labels(self.labelnames, key)} {_fmt_num(val)}")
        return out


class _Histogram:
    """
    累积直方图（Prometheus 语义：每个 bucket 是「<= 上界」的累计计数）

    只保留 bucket + sum + count —— 这是 Prometheus 计算 histogram_quantile
    所需的全部信息，比自研分位数准确且可跨实例聚合。
    """

    __slots__ = ("name", "help", "labelnames", "buckets", "_counts", "_sums", "_lock")

    def __init__(
        self,
        name: str,
        help_: str,
        labelnames: Tuple[str, ...],
        buckets: Iterable[float] = DEFAULT_BUCKETS,
    ):
        self.name = name
        self.help = help_
        self.labelnames = labelnames
        self.buckets = tuple(sorted(float(b) for b in buckets))
        self._counts: Dict[Tuple[str, ...], List[float]] = {}
        self._sums: Dict[Tuple[str, ...], float] = {}
        self._lock = threading.Lock()

    def observe(self, value: float, **labels) -> None:
        key = tuple(str(labels.get(k, "")) for k in self.labelnames)
        val = float(value)
        # NaN / inf 会污染 sum，直接丢弃
        if math.isnan(val) or math.isinf(val):
            return
        with self._lock:
            counts = self._counts.get(key)
            if counts is None:
                counts = [0.0] * (len(self.buckets) + 1)  # 末位是 +Inf
                self._counts[key] = counts
            for i, upper in enumerate(self.buckets):
                if val <= upper:
                    counts[i] += 1.0
            counts[-1] += 1.0
            self._sums[key] = self._sums.get(key, 0.0) + val

    def render(self) -> List[str]:
        out = [f"# HELP {self.name} {self.help}", f"# TYPE {self.name} histogram"]
        with self._lock:
            items = sorted(self._counts.items())
            sums = dict(self._sums)
        for key, counts in items:
            lbl = _fmt_labels(self.labelnames, key)
            # _fmt_labels 返回 "{a=\"b\"}" 或 ""；桶需要把 le 并进同一组标签
            for i, upper in enumerate(self.buckets):
                bucket_lbl = _fmt_labels(self.labelnames, key, extra=[("le", _fmt_num(upper))])
                out.append(f"{self.name}_bucket{bucket_lbl} {_fmt_num(counts[i])}")
            inf_lbl = _fmt_labels(self.labelnames, key, extra=[("le", "+Inf")])
            out.append(f"{self.name}_bucket{inf_lbl} {_fmt_num(counts[-1])}")
            out.append(f"{self.name}_sum{lbl} {_fmt_num(sums.get(key, 0.0))}")
            out.append(f"{self.name}_count{lbl} {_fmt_num(counts[-1])}")
        return out


# ====== 格式化辅助 ======

def _fmt_num(v: float) -> str:
    """整数不显示小数点；浮点保留必要精度"""
    if v == int(v) and abs(v) < 1e15:
        return str(int(v))
    return repr(round(float(v), 6))


def _escape_label_value(s: str) -> str:
    return s.replace("\\", "\\\\").replace('"', '\\"').replace("\n", "\\n")


def _fmt_labels(
    labelnames: Tuple[str, ...],
    values: Tuple[str, ...],
    extra: Optional[List[Tuple[str, str]]] = None,
) -> str:
    parts = [f'{k}="{_escape_label_value(v)}"' for k, v in zip(labelnames, values)]
    if extra:
        parts.extend(f'{k}="{_escape_label_value(v)}"' for k, v in extra)
    return "{" + ",".join(parts) + "}" if parts else ""


# ====== 全局指标实例 ======

START_TIME = time.time()

# --- HTTP ---
HTTP_REQUESTS = _Counter(
    "http_requests_total",
    "HTTP 请求总数（按方法/归一化路径/状态码）",
    ("method", "path", "status"),
)
HTTP_DURATION = _Histogram(
    "http_request_duration_ms",
    "HTTP 请求耗时（毫秒，TTFB）",
    ("method", "path"),
)
HTTP_IN_FLIGHT = _Gauge(
    "http_requests_in_flight",
    "当前正在处理的 HTTP 请求数",
    (),
)

# --- 业务：LLM / AIGC / 配额 ---
LLM_CALLS = _Counter(
    "llm_calls_total",
    "LLM 调用次数（按模型与结果）",
    ("model", "status"),
)
LLM_TOKENS = _Counter(
    "llm_tokens_total",
    "LLM token 消耗（按模型与方向）",
    ("model", "direction"),
)
# ★ P0-8（2026-09-27）：LLM 结构化输出**不可用**的次数。
#   与 `llm_calls_total{status}` 的分工：后者记「这次 HTTP 调用成没成」，
#   前者记「调用成了，但吐出来的东西能不能用」—— 这两件事在告警上完全不同：
#   前者是可用性故障，后者是**静默的正确性故障**（不报错、不降级，只给错数据）。
#   reason ∈ {"json_decode_error", "truncated"}。
LLM_OUTPUT_INVALID = _Counter(
    "llm_output_invalid_total",
    "LLM 结构化输出不可用次数（按模型与原因）",
    ("model", "reason"),
)
AIGC_TASKS = _Counter(
    "aigc_tasks_total",
    "AIGC 生成任务数（按类型与结果）",
    ("kind", "status"),
)
AIGC_TASK_DURATION = _Histogram(
    "aigc_task_duration_ms",
    "AIGC 任务耗时（毫秒）",
    ("kind",),
    buckets=(500.0, 1000.0, 3000.0, 5000.0, 10000.0, 30000.0, 60000.0, 300000.0),
)
QUOTA_REJECTIONS = _Counter(
    "quota_rejections_total",
    "被配额拦截的请求数（按配额类型）",
    ("kind",),
)

# --- 依赖可用性 ---
DEPENDENCY_UP = _Gauge(
    "dependency_up",
    "依赖可用性（1=可用，0=不可用）",
    ("name",),
)

# --- 异步任务（Celery）---
CELERY_TASK_RESULTS = _Counter(
    "celery_task_results_total",
    "Celery 任务终态计数（按任务名与结果）",
    ("task", "status"),
)

# --- 长期记忆的夜间自动整理 ---
# ★ 为什么要单独一个指标，而不是复用上面的 `CELERY_TASK_RESULTS`：
#   后者记的是「Celery 层面把任务判成功还是失败」，而本指标记的是
#   **业务结局**。两者刻意不重合，因为最需要看见的那一档恰恰是
#   「Celery 判成功、业务上什么都没做」—— 例如「因为冷却被跳过」
#   与「没有对话可整理」。把它们混成一个数字，调度坏掉时
#   （每天都 skip）看起来会和「每晚正常整理、只是没新内容」一模一样。
MEMORY_DISTILL_RUNS = _Counter(
    "memory_distill_runs_total",
    "长期记忆整理次数（按业务结局：ok / no_messages / skipped / failed）",
    ("status",),
)

# --- 通用审计（P0-5）---
# ★ 为什么审计已有日志还要独立指标：`record_audit()` 的失败是**旁路失败** ——
#   业务照常返回 200，只有审计悄悄没了。这种东西只出现在日志里时没人会看；
#   做成指标才能被 Prometheus 抓成告警（见 observability/alert_rules.yml::
#   AuditWriteFailing）。这是「安全能力静默失效」的典型形态，必须有独立出口。
AUDIT_RECORDS = _Counter(
    "audit_records_total",
    "审计写入成功数（按动作与结果）",
    ("action", "status"),
)
AUDIT_WRITE_ERRORS = _Counter(
    "audit_write_errors_total",
    "审计写入失败数（按动作）—— 业务不受影响，但该条痕迹已丢失",
    ("action",),
)

# --- 审计保留期清理（第 328 轮）---
# ★ 为什么后台清理也必须有指标：定时任务的失效**默认是静默的** ——
#   beat 没跑 / 任务名写错 / 任务体是空壳，现象全都表现为「审计表只增不减」，
#   而这件事在接口、访问日志、错误日志里**一个影子都没有**。
#   日志会被滚动覆盖，指标不会 ⇒ 两个出口都要有（跑没跑成 + 回收了多少）。
AUDIT_PURGE_RUNS = _Counter(
    "audit_purge_runs_total",
    "审计保留期清理执行次数（按结局：ok / failed）",
    ("status",),
)
# ★ 为什么删除行数要单独一个指标，而不是塞进上面的 status 标签：
#   `runs{status}` 只答「跑没跑成」，答不了「回收了多少」——
#   而"保留期到底有没有在生效"只能靠删除行数判断
#   （长期恒为 0 ⇒ 保留期设得过大，或这张表压根没在增长）。
#   ★ 用 Counter 而不是 Gauge：单次删除量本身无意义（逐日波动大），
#     要看的是它的**累计斜率**（≈ 表的真实增长速率上界）。
AUDIT_PURGE_DELETED = _Counter(
    "audit_purge_deleted_rows_total",
    "审计保留期清理累计删除的行数",
    (),
)

# --- 身份域保留期清理（第 331 轮）---
# ★ 为什么该有指标，而不只是「日志里有一行」：这两张表的失效**没有任何别的影子** ——
#   `login_attempts` 每次登录写一行、`email_tokens` 每点一次「重发验证邮件」写一行，
#   而清理这件事在接口、访问日志、错误日志里都不出现。日志会被滚动覆盖，指标不会。
#   ★ 与审计那组**逐字同款**，因为失效形态相同：beat 没起 / 任务名两处写法不一致
#     / 任务体是空壳 —— 三种都表现为「表只增不减，且一条日志都没有」。
IDENTITY_PURGE_RUNS = _Counter(
    "identity_purge_runs_total",
    "身份域保留期清理执行次数（按结局：ok / failed）",
    ("status",),
)
# ★ 为什么这一条**带 `table` 标签**（而审计那条不带）：本任务一次跑**两张表**的清理，
#   两边的写入速率差三个数量级（`login_attempts` 每登录一行 / `email_tokens` 只在
#   验证与重置时一行）。合成一个数字之后，"到底是谁在涨"就问不出来了 ——
#   而那个答案才是保留期有没有配错的唯一线索。
#   ★ 标签值取自 `Model.__tablename__`（不是手写字面量）：表名只有一个真源，
#     改名时这里不会静默失配（同 `retention.py` 用 ORM `delete()` 的理由）。
IDENTITY_PURGE_DELETED = _Counter(
    "identity_purge_deleted_rows_total",
    "身份域保留期清理累计删除的行数（按表：login_attempts / email_tokens）",
    ("table",),
)

# --- 数据库备份（第 340 轮 / P0-2）---
# ★ 为什么备份也必须有指标：备份的失效**默认是静默的** —— beat 没起 /
#   任务名两处写法不一致 / 脚本路径漂移，现象全都表现为「`backups/` 目录
#   不再长新文件」，而这件事在接口、访问日志、业务错误日志里**一个影子都没有**。
#   等到真要用备份那天才发现"最近一份是三个月前的"，是不可逆的事故。
#   日志会被滚动覆盖，指标不会 ⇒ 必须有两个出口（跑没跑成 + 备了多少）。
#   ★ 与审计 / 身份域那两组**逐字同款**，因为失效形态相同。
BACKUP_RUNS = _Counter(
    "backup_runs_total",
    "数据库备份执行次数（按结局：ok / failed）",
    ("status",),
)
# ★ 为什么大小要单独一个 gauge：`runs{status}` 只答"跑没跑成"，答不了
#   "备了多少"。而"备份是不是真的在长"只能靠字节数看 ——
#   持续偏小 ⇒ dump 被截断或库被清空；长期一个数 ⇒ 备份没真的重跑。
#   ★ 用 Gauge 而不是 Counter：这里要的是**最近一次**的绝对值，不是累计。
BACKUP_LAST_BYTES = _Gauge(
    "backup_last_bytes",
    "最近一次成功备份的字节数（0 = 尚无成功备份）",
    (),
)

# --- PITR / WAL 归档（第 351 轮 / P0-2）---
# ★ 为什么这两条**不能**复用 `backup_runs_total`：它们答的是不同的问题。
#   `backup_runs_total` 只答「逻辑 dump 跑没跑成」；而 PITR 的两半
#   （WAL 外送、物理基线）**各自都能独立地坏**，且坏法不同：
#     · 外送停 ⇒ 归档段只活在容器可写层，`docker rm` 即丢（无异地副本）；
#     · 基线停 ⇒ 只剩增量、没有可恢复的起点（有归档也回不去）。
#   合并成一个计数器后，「备份 OK」会把「PITR 已残废」一起说成好的。
PITR_RUNS = _Counter(
    "pitr_runs_total",
    "PITR 任务执行次数（kind=wal_fetch / basebackup，status=ok / failed）",
    ("kind", "status"),
)
# ★ 为什么归档体积要单独一个 gauge：`pitr_runs_total{kind=wal_fetch}` 只说明
#   "外送这个动作跑过"，答不了"归档是不是真的在长"。长期一个数 ⇒ 归档停了
#   （archive_mode 被改回 off / 归档目录满了），而任务每天照样"成功"。
PITR_WAL_ARCHIVE_BYTES = _Gauge(
    "pitr_wal_archive_bytes",
    "宿主 WAL 归档目录累计字节数（0 = 尚无归档）",
    (),
)

# 对外暴露的顺序（/metrics 输出顺序稳定，便于 diff）
_REGISTRY = (
    HTTP_REQUESTS,
    HTTP_DURATION,
    HTTP_IN_FLIGHT,
    LLM_CALLS,
    LLM_TOKENS,
    LLM_OUTPUT_INVALID,
    AIGC_TASKS,
    AIGC_TASK_DURATION,
    QUOTA_REJECTIONS,
    CELERY_TASK_RESULTS,
    MEMORY_DISTILL_RUNS,
    AUDIT_RECORDS,
    AUDIT_WRITE_ERRORS,
    AUDIT_PURGE_RUNS,
    AUDIT_PURGE_DELETED,
    IDENTITY_PURGE_RUNS,
    IDENTITY_PURGE_DELETED,
    BACKUP_RUNS,
    BACKUP_LAST_BYTES,
    PITR_RUNS,
    PITR_WAL_ARCHIVE_BYTES,
    DEPENDENCY_UP,
)


def render_prometheus() -> str:
    """渲染为 Prometheus 文本格式（text/plain; version=0.0.4）"""
    lines: List[str] = [
        "# HELP process_uptime_seconds 进程启动至今秒数",
        "# TYPE process_uptime_seconds gauge",
        f"process_uptime_seconds {_fmt_num(time.time() - START_TIME)}",
    ]
    for metric in _REGISTRY:
        lines.extend(metric.render())
    return "\n".join(lines) + "\n"


def reset_all() -> None:
    """清空所有指标（测试用；生产不要调用）"""
    for metric in _REGISTRY:
        with metric._lock:  # noqa: SLF001 —— 同模块内的测试辅助
            if hasattr(metric, "_values"):
                metric._values.clear()
            if hasattr(metric, "_counts"):
                metric._counts.clear()
            if hasattr(metric, "_sums"):
                metric._sums.clear()
