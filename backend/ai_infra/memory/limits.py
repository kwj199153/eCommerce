"""长期记忆的**口径真源**：分节、上限、来源权重。

本模块属于 `ai_infra/` 机制层 —— 纯常量 + 极少量纯函数，**零 IO、零 DB、零网络**。
它与 `modules/memory/`（落库 + HTTP 端点 + Celery 定时任务）的分工，和
`ai_infra/session_state.py` ↔ `modules/conversation/state_store.py`、
`ai_infra/plan.py` ↔ `modules/secretary` 是同一套切法：
**机制住 `ai_infra/`，接线住 `modules/`。**

★★ 为什么上限与分节名必须只有一处
-----------------------------------
上限有**四个消费方**：

  1. `modules/memory/service.py` —— 用户提交超限内容时**拒绝**（HTTP 400），
     而不是静默截断。用户手写的东西被悄悄砍掉一段是不可接受的：他看到
     "保存成功"，回头却发现少了半句；
  2. `ai_infra/memory/distill.py::converge` —— 系统自动整理时按上限**裁剪**
     （这里静默是对的：整理本来就是自动行为，且用户能在界面上看到结果）；
  3. `ai_infra/memory/entry.py::render_prompt_block` —— 注入 system prompt 时
     必须有个硬上限。记忆越长，**每一轮**对话都要多花这笔 token，
     而它是随记忆增长单调变贵的，没有上限等于给自己埋一颗缓慢引爆的账单；
  4. `tests/` 里的门禁 —— 断言"上限改小了，裁剪与拒绝也跟着改口径"。

四处各写一份字面量时，"把 `MAX_ENTRY_CHARS` 从 500 调到 200"这件事只会
**部分生效**：接口仍允许存 500 字、整理时却按 200 裁。
两边都不报错、不告警，只在用户某天发现内容莫名变短时才被注意到 ——
这正是本项目反复踩到的那类「同一判据两份实现」缺陷。
⇒ 所有常量收在本模块，别处一律 `from ai_infra.memory.limits import ...`。

★ 分节名是**用户可见文案**，不是内部标识符：它会被 `entry.render_markdown()`
  渲染成 markdown 的 `# 标题`，并被前端 `MemoryEvolution.vue` 原样展示。
  改这里等于改 UI 文案。
"""

from __future__ import annotations

# ============================================================================
# 分节
# ============================================================================

#: 具名分节。**元组顺序即渲染顺序**，也是全局裁剪时"分节轮转"的取用顺序。
SECTION_WORK = "工作背景"
SECTION_PERSONAL = "个人背景"
SECTION_OPS = "运营偏好"
SECTION_COMMS = "沟通偏好"
SECTION_FOCUS = "关注重点"
#: 兜底分节：落在任何标题之前、或标题无法归类时的条目。
SECTION_OTHER = "其他"

ALL_SECTIONS: tuple[str, ...] = (
    SECTION_WORK,
    SECTION_PERSONAL,
    SECTION_OPS,
    SECTION_COMMS,
    SECTION_FOCUS,
    SECTION_OTHER,
)

#: 标题 → 具名分节 的**别名表**。
#:
#: ★ 为什么要别名：用户导入的 markdown、以及前端历史模板里出现过
#:   「当前关注重点」「用户偏好记忆」这类写法；若不归一，同一件事会分裂成
#:   两个分节，界面上一半条目落在规范节、另一半落在野节里，
#:   而分节配额按节计数 ⇒ 野节会把配额白白吃掉。
SECTION_ALIASES: dict[str, str] = {
    "工作背景": SECTION_WORK,
    "个人背景": SECTION_PERSONAL,
    "运营偏好": SECTION_OPS,
    "沟通偏好": SECTION_COMMS,
    "关注重点": SECTION_FOCUS,
    "当前关注重点": SECTION_FOCUS,
    "当前关注": SECTION_FOCUS,
    "其他": SECTION_OTHER,
}

#: 分节**配额**（每个分节最多保留多少条）。
#:
#: ★ 刻意让配额之和（80）**大于** `MAX_ENTRIES`（60）：这两条上限管的是两件
#:   不同的事 ——
#:     · **配额**防「某一个分节被塞爆」（局部倾斜）；
#:     · **总上限**防「整份记忆无限膨胀」（全局总量）。
#:   若把配额之和设成恰好等于总上限，全局裁剪就永远轮不到执行 ——
#:   那等于写了一段死代码，而且没有任何现象提示它没在跑。
SECTION_QUOTA: dict[str, int] = {
    SECTION_WORK: 15,
    SECTION_PERSONAL: 12,
    SECTION_OPS: 18,
    SECTION_COMMS: 12,
    SECTION_FOCUS: 15,
    SECTION_OTHER: 8,
}
#: 未在 `SECTION_QUOTA` 登记的分节（用户导入的自定义标题）的默认配额。
#: ★ 给一个**非零**的小额度，而不是 0：自定义标题的内容是用户自己写的，
#:   直接清零等于"导入即丢弃"，且不会有任何提示。
DEFAULT_SECTION_QUOTA = 10

# ============================================================================
# 条目上限
# ============================================================================

#: 整份长期记忆的**条数**硬上限（全局）。
MAX_ENTRIES = 60
#: 单条条目的**字符数**上限。
#:
#: ★ 取 500 而不是 100：条目形态是"一小段话"而不是"一个词"
#:   （例：「标题重关键词覆盖（前端词+核心词+长尾词），五点描述卖点和场景并重」）。
#:   太小会把完整的一条事实切碎，切碎后的半句在注入 prompt 时**语义就变了** ——
#:   那不是"少给一点信息"，是"给了错误信息"。
MAX_ENTRY_CHARS = 500
#: 注入 system prompt 的记忆块**字符数**上限（见本模块 docstring 第 3 条）。
MAX_PROMPT_CHARS = 2000
#: 截断标记。用单个字符而不是 `[已截断]` 这类短语：后者本身也要占长度，
#: 且在紧密的列表里显得喧宾夺主。
TRUNCATION_MARK = "…"

# ============================================================================
# 学习时间线 / 每晚蒸馏
# ============================================================================

#: 学习时间线保留的最大条数（前端 `a-timeline` 展示的就是它）。
MAX_LOGS = 30
#: 单条时间线记录的正文上限。
MAX_LOG_CHARS = 500
#: 每晚抽取时最多读入多少条**对话消息**。
MAX_DISTILL_MESSAGES = 200
#: 每晚抽取时读入对话正文的**总字符**上限（控 prompt 成本）。
MAX_DISTILL_TRANSCRIPT_CHARS = 8000
#: 转录里单条消息**至少**要拿到多少字符，才值得收进来。
#:
#: ★ 为什么需要一个下限，而不是"放不下就丢"：把一条消息截到只剩几个字，
#:   模型会照着残句**补出一个它自己编的完整偏好**，而那条偏好会永久
#:   留在记忆里影响之后每一轮回答。半句话比没有更糟。
#:   低于这个数就整条不收（此时转录宁可少一条）。
MIN_DISTILL_LINE_CHARS = 200
#: 单次抽取最多接受多少条候选（防模型一口气吐一屏）。
MAX_CANDIDATES_PER_RUN = 20
#: 时间线记录里最多附带几条"新增/移除"样本。
MAX_LOG_SAMPLE_ITEMS = 5
#: 时间线记录里单条样本的字符上限。
MAX_LOG_SAMPLE_CHARS = 120

# ============================================================================
# 蒸馏节奏（每晚自动整理 / 「立即整理」）
# ============================================================================
#
# ★★ 这一组与上面的 `MAX_*` 是**两件事**，别混：
#   上面的 `MAX_*` 管「一次整理能装多少」（成本上界），
#   这里的 `DISTILL_*` 管「多久去整理一次」（节奏）。
#   写在一起会让人以为"调大批次就等于跑得更勤"。
#
# ★ 为什么节奏也要收进真源：它有**两个消费方** ——
#   ① `core/redis.py` 的 `beat_schedule`（几点触发，部署侧）；
#   ② `modules/memory/service.py` 的 `claim_distill_run`（该不该跑，运行侧）。
#   两处各写一份字面量时，"把周期从 24h 改成 12h"只会**部分生效**：
#   调度按 12h 触发、冷却仍按 24h 判 ⇒ 每天有一次被静默跳过，
#   而界面上看不出任何异常（时间线里只是"那天没有记录"）。
#
# ★★ 冷却必须**严格小于**周期（本文件里是 20 < 24）
#    两者相等时，边界判定（`<` 还是 `<=`）就决定了"每天跑"还是"两天跑一次"；
#    而 beat 的触发时刻有抖动（worker 排队、进程重启、时钟漂移），
#    它会在这个边界上**随机**二选一 —— 表现为"有时两天才整理一次"，
#    且没有任何一处代码看起来是错的。留 4 小时余量后，
#    抖动必须大到 4 小时才会撞上边界。
#
# ★ 回溯窗口必须**大于**周期（这里是 26 > 24）：上次跑完到这次跑之间的对话
#   不能有缺口。宁可与上一轮重叠（重复读到的内容会被 `dedup_key` 去重，
#   代价只是一点 token），也不能漏读 —— 漏掉的消息**永远不会**再被看到。

#: beat 每天在几点触发（本地时区：`celery_app.conf.timezone` = Asia/Shanghai）。
#: 取凌晨：这是唯一一个用户不太可能正在对话的时刻，整理导致的
#: "记忆条数突然变化"不会与他正在进行的操作撞在一起。
DISTILL_HOUR = 3
#: beat 触发的分钟。★ 与 `DISTILL_HOUR` 一起构成 crontab；单独抽出来是为了
#: 让测试里把触发点设到"下一分钟"时不必改小时数（那会连带改掉语义）。
DISTILL_MINUTE = 0
#: beat 的**周期**（小时）。目前等于每日一次（crontab 的粒度是「天」）。
#: ★ 它是一个**恒定值**而不是可调参数：唯一用途是让下面两条不变量
#:   可以被断言（`DISTILL_COOLDOWN_HOURS < 周期 < DISTILL_LOOKBACK_HOURS`）。
#:   把周期做成配置项而 crontab 仍是「每天一次」，等于造出一个
#:   永远不会被读的第二份真源。
DISTILL_PERIOD_HOURS = 24
#: 冷却窗口（小时）：距上次**发起**整理不足这么久就跳过。
#: ★ 这是「幂等闸门」而不是"调度周期" —— `task_acks_late=True` 下 worker 崩溃
#:   会重投递，也可能被手动点两次"立即整理"；没有它就会重复调 LLM（重复花钱）。
DISTILL_COOLDOWN_HOURS = 20
#: 「立即整理」的最小间隔（秒）。★ 与冷却窗口是**两道不同的闸门**：
#:   冷却管"夜间调度跑过没有"，这一道管"用户连点按钮"。
#:   `force=True`（手动触发）绕过冷却，但**不绕过**这一道 ——
#:   force 的语义是"别管今晚跑过没有"，不是"钱也要烧"。
DISTILL_MANUAL_GAP_SECONDS = 60
#: 一次整理读入的对话回溯窗口（小时，> `DISTILL_COOLDOWN_HOURS`，理由见上）。
DISTILL_LOOKBACK_HOURS = 26
#: 一次 beat 触发最多为多少人投递整理任务。
#: ★ 设上限而不是"有多少处理多少"：这是**成本闸门**。某天用户量涨十倍时，
#:   不设限的调度会在那一晚把十倍的钱花出去 —— 而它不会报错，
#:   只会在账单上体现。超出的人次日会被轮到（回溯窗口内的对话不会丢）。
DISTILL_BATCH_LIMIT = 100

# ============================================================================
# 来源与重要性权重
# ============================================================================

#: 用户手工新增/编辑保存。
SOURCE_MANUAL = "manual"
#: 用户导入 markdown 文件。
SOURCE_IMPORT = "import"
#: 每晚任务从对话里**归纳**出来的。
SOURCE_DISTILL = "distill"

MEMORY_SOURCES: tuple[str, ...] = (SOURCE_MANUAL, SOURCE_IMPORT, SOURCE_DISTILL)

#: 来源 → 重要性权重。
#:
#: ★★ 「满了先挤掉谁」的判据是**权重**，不是时间。
#:
#:   用户手写/亲手导入的条目代表他**明确的意图**；AI 归纳的条目只是猜测。
#:   若按时间淘汰，一条昨晚刚被归纳出来的废话会把用户半年前认真写下的
#:   一条偏好挤掉 —— 而用户只会在某天发现"我明明记过这条"时才发现，
#:   中间没有任何报错。方向错了的代价是不对称的：少一条 AI 猜测无感，
#:   少一条用户手写的偏好是**他对我失去信任**。
SOURCE_WEIGHTS: dict[str, int] = {
    SOURCE_MANUAL: 10,
    SOURCE_IMPORT: 10,
    SOURCE_DISTILL: 1,
}
#: 未登记来源的权重。
#: ★ 给**最低**权重而不是最高：不认识的来源不该获得"优先保留"的特权。
DEFAULT_SOURCE_WEIGHT = 1


# ============================================================================
# 时间线记录类型（memory_logs.kind 的取值真源）
# ============================================================================

#: 每晚自动整理**成功**（含"跑通了但本次无新内容"）。
#: ★ 与 `KIND_DISTILL_FAILED` 严格分开：前者是正常结果，后者需要人介入。
KIND_DISTILL = "distill"
#: 每晚自动整理**失败**（抽取抛错 / 模型打了 / 返回不合规）。
#:
#: ★★ 为什么失败必须**单独留一条**，而不是"不写日志"：
#:   界面上的"暂无学习记录"会同时表示三件事 —— "没跑"、"跑了没事"、
#:   "跑失败了"。用户没有任何办法区分，于是也没法判断该不该去找人问。
#:   这正是 r141 认定「假页面承诺『每晚自动整理』」的同类判据：
#:   系统静默地什么都没做，而所有可见状态看起来都正常。
KIND_DISTILL_FAILED = "distill_failed"
#: 用户手动点"立即整理"。
KIND_MANUAL = "manual"
#: 用户导入 markdown。
KIND_IMPORT = "import"
#: 用户重置（清空全部条目，**保留开关本身**）。
KIND_RESET = "reset"

LOG_KINDS: tuple[str, ...] = (
    KIND_DISTILL,
    KIND_DISTILL_FAILED,
    KIND_MANUAL,
    KIND_IMPORT,
    KIND_RESET,
)

#: 属于"坏消息"的记录类型 —— 界面必须与成功记录**区分渲染**
#: （警示色 / 可展开看到错误原因）。放在这里而不是前端硬编码，
#: 是为了避免"新增一种失败类型时忘了改前端"。
FAILURE_LOG_KINDS: tuple[str, ...] = (KIND_DISTILL_FAILED,)


def is_known_log_kind(kind: str) -> bool:
    """`kind` 是否为已登记类型。

    ★ 用途是**写入前的守卫**：落一条未知 `kind` 进库，等于在时间线上
      加了一条永远渲染不出图标、也永远筛不出来的孤儿记录。宁可让调用方
      当场拿到错误，也不要让它在表里沉默地积存。
    """
    return (kind or "").strip().lower() in LOG_KINDS


def source_weight(source: str) -> int:
    """来源 → 重要性权重（未知来源按最低权重）。"""
    return SOURCE_WEIGHTS.get((source or "").strip().lower(), DEFAULT_SOURCE_WEIGHT)


def section_quota(section: str) -> int:
    """分节 → 配额（未登记的自定义分节走 `DEFAULT_SECTION_QUOTA`）。"""
    return SECTION_QUOTA.get(section, DEFAULT_SECTION_QUOTA)


def ordered_sections(sections) -> list[str]:
    """把一组分节名排成**确定的展示顺序**：具名分节按 `ALL_SECTIONS`，
    其余（用户自定义标题）按**首次出现顺序**排在后面。

    ★ 为什么不能只 `sorted()`：自定义标题一旦被字典序重排，
      用户导入的 markdown 结构在**每次保存后都会换个样子** ——
      看起来像"系统在乱动我的内容"。保持首次出现顺序则保存是稳定的。
    """
    seen = []
    for s in sections:
        if s not in seen:
            seen.append(s)
    known = [s for s in ALL_SECTIONS if s in seen]
    unknown = [s for s in seen if s not in ALL_SECTIONS]
    return known + unknown


__all__ = [
    "ALL_SECTIONS",
    "DEFAULT_SECTION_QUOTA",
    "DEFAULT_SOURCE_WEIGHT",
    "DISTILL_BATCH_LIMIT",
    "DISTILL_COOLDOWN_HOURS",
    "DISTILL_HOUR",
    "DISTILL_LOOKBACK_HOURS",
    "DISTILL_MANUAL_GAP_SECONDS",
    "DISTILL_MINUTE",
    "DISTILL_PERIOD_HOURS",
    "FAILURE_LOG_KINDS",
    "KIND_DISTILL",
    "KIND_DISTILL_FAILED",
    "KIND_IMPORT",
    "KIND_MANUAL",
    "KIND_RESET",
    "LOG_KINDS",
    "MAX_CANDIDATES_PER_RUN",
    "MAX_DISTILL_MESSAGES",
    "MAX_DISTILL_TRANSCRIPT_CHARS",
    "MIN_DISTILL_LINE_CHARS",
    "MAX_ENTRIES",
    "MAX_ENTRY_CHARS",
    "MAX_LOGS",
    "MAX_LOG_CHARS",
    "MAX_LOG_SAMPLE_CHARS",
    "MAX_LOG_SAMPLE_ITEMS",
    "MAX_PROMPT_CHARS",
    "MEMORY_SOURCES",
    "SECTION_ALIASES",
    "SECTION_COMMS",
    "SECTION_FOCUS",
    "SECTION_OPS",
    "SECTION_OTHER",
    "SECTION_PERSONAL",
    "SECTION_QUOTA",
    "SECTION_WORK",
    "SOURCE_DISTILL",
    "SOURCE_IMPORT",
    "SOURCE_MANUAL",
    "SOURCE_WEIGHTS",
    "TRUNCATION_MARK",
    "is_known_log_kind",
    "ordered_sections",
    "section_quota",
    "source_weight",
]
