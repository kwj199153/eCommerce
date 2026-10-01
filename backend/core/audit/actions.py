"""审计**动作目录**与结果/目标枚举的唯一真源（P0-5）。

==============================================================================
★ 为什么动作名必须有唯一真源，而不是各端点点就地写一个字符串
==============================================================================
审计真正值钱的能力是「按动作聚合与筛选」：

    「过去 7 天谁执行过 `store.delete`？」
    「`account.member.*` 这类变更本月发生了多少次？」

如果 `"store.delete"` 这个字面量被分别抄在 router、service、前端筛选下拉三处，
任何一次改名（哪怕只是 `delete` → `remove`）都会**静默撕裂历史**：

    · 老记录的动作名是旧串 ⇒ 用新串筛不到；
    · 新记录是新串 ⇒ 用旧串也筛不到；
    · 而**没有任何地方会报错** —— 审计表是 append-only 的，
      写进去的字符串永远不会被回读校验，两个名字会永久并存。

⇒ 所以这里定唯一的常量集合，读口 `/audit/actions` 与前端筛选框共用同一张表
  （`ACTIONS`），由 `tests/test_audit_gate.py` 守着「消费点引用的动作名必须来自本模块」。

==============================================================================
★ 为什么 action 用「对象.动词」，而不是 `STORE_DELETE` 这样的裸大写名
==============================================================================
`store.delete` / `account.member.update` 这类点分命名有两个好处：
  · 前缀即**可聚合的域** —— `action=~"store\\..*"` 一条 PromQL / SQL `LIKE`
    就能捞出一个域的全部动作，不需要维护「哪些动作属于 store 域」的映射表；
  · 与 `target_type` 天然对齐（`store.*` 动作的目标就是 `store`），
    将来新增动作时域归属一目了然，不会出现「动作在 store 端点、
    却记成 user 域」这种口径漂移。
"""

from __future__ import annotations

# ==============================================================================
# 结果（status）
# ==============================================================================
#: 业务动作**执行成功**。
STATUS_SUCCESS = "success"
#: 业务动作**失败 / 被拒绝**。
#:
#: ★ 为什么必须把「尝试但失败」也记下来，而不是只记成功：
#:   安全排查问的是「谁试过」，不是「谁成功了」。一次被 403 挡下的
#:   `store.transfer` 恰恰是最该被看见的痕迹 —— 只记成功等于把
#:   攻击者的全部失败尝试丢进黑洞。这正是 `status` 存在的理由。
STATUS_FAILURE = "failure"

#: 全部合法结果（读口白名单校验用）。
STATUSES: tuple[str, ...] = (STATUS_SUCCESS, STATUS_FAILURE)


# ==============================================================================
# 目标类型（target_type）
# ==============================================================================
TARGET_USER = "user"
TARGET_STORE = "store"
TARGET_ACCOUNT = "account"
TARGET_MEMBER = "member"
TARGET_SESSION = "session"
#: 提示词覆写（`prompt_versions` 表的一行）。
#: ★ 它不是租户资源，是**平台级配置** —— 见
#:   `modules/prompt_versions/db_model.py` 文件头「没有 store_id / account_id」那一节。
TARGET_PROMPT = "prompt"

TARGET_TYPES: tuple[str, ...] = (
    TARGET_USER,
    TARGET_STORE,
    TARGET_ACCOUNT,
    TARGET_MEMBER,
    TARGET_SESSION,
    TARGET_PROMPT,
)


# ==============================================================================
# 动作（action）
# ==============================================================================
#: 登录成功。★ 与 `login_attempts` 的分工见 `models.py` 文件头：
#: 本动作只记**成功**登录（失败尝试由 `login_attempts` 逐条记录，理由见那里）。
ACTION_LOGIN_SUCCESS = "login.success"

#: 连接店铺 —— 会**写入平台凭据**（`_save_store_credentials()`）。
#: 这是资产性变更：一条泄露的凭据等于对方能用你的卖家账号下单/改价。
ACTION_STORE_CONNECT = "store.connect"
#: 断开店铺 —— 清除平台凭据。同样记，因为「谁把某个店的接入断掉了」是排障起点。
ACTION_STORE_DISCONNECT = "store.disconnect"
#: 转移店铺归属 —— 改变的是**可见性边界**（谁能看到这家店）。
ACTION_STORE_TRANSFER = "store.transfer"
#: 删除店铺 —— 不可逆（本仓语义），必须留痕。
ACTION_STORE_DELETE = "store.delete"

#: 修改账户成员的角色 / 状态 —— 权限变更，最典型的高危写操作。
ACTION_MEMBER_UPDATE = "account.member.update"
#: 移除账户成员（软删 `status=REMOVED`）—— 权限回收。
ACTION_MEMBER_REMOVE = "account.member.remove"

#: 写入 / 替换一条提示词覆写 —— 改的是**线上所有会话**吃到的指令文本。
#: ★ 为什么它必须审计：这条改动**不会**触发任何代码评审（它不在 git 里），
#:   却能改掉每一个 Agent 的行为与口吻。本仓所有「平台级配置」里，
#:   它的影响面最大、留痕最少 ⇒ 不记审计就完全不可追溯。
ACTION_PROMPT_OVERRIDE_WRITE = "prompt.override.write"
#: 删除一条提示词覆写 —— 让源码版重新生效（等价于一次**静默的行为回退**）。
ACTION_PROMPT_OVERRIDE_DELETE = "prompt.override.delete"


#: 动作目录：`(动作, 中文说明, 目标类型)`。
#:
#: ★ 读口 `GET /api/v1/audit/actions` 直接返回本表；前端筛选下拉也读它。
#:   刻意**不做成第二份清单** —— 两份清单必然在某次加动作后不同步，
#:   而表现是「新动作记进了库，但筛选框里选不到」，排查时极难想到。
#:   ★ 新增动作 = 在这里加一行 + 在调用点用常量，没有第三种地方要改。
ACTIONS: tuple[tuple[str, str, str], ...] = (
    (ACTION_LOGIN_SUCCESS, "登录成功", TARGET_USER),
    (ACTION_STORE_CONNECT, "连接店铺（写入平台凭据）", TARGET_STORE),
    (ACTION_STORE_DISCONNECT, "断开店铺（清除平台凭据）", TARGET_STORE),
    (ACTION_STORE_TRANSFER, "转移店铺归属", TARGET_STORE),
    (ACTION_STORE_DELETE, "删除店铺", TARGET_STORE),
    (ACTION_MEMBER_UPDATE, "修改账户成员角色/状态", TARGET_MEMBER),
    (ACTION_MEMBER_REMOVE, "移除账户成员", TARGET_MEMBER),
    (ACTION_PROMPT_OVERRIDE_WRITE, "写入/替换提示词覆写", TARGET_PROMPT),
    (ACTION_PROMPT_OVERRIDE_DELETE, "删除提示词覆写", TARGET_PROMPT),
)

#: 已知动作集合。
#:
#: ★ 用途只是**软校验**：`record_audit()` 见到不在集合里的动作名会打一条
#:   WARNING，但仍然照常落库。为什么是「告警 + 仍落库」而不是「拒绝写入」：
#:   审计的立场是「宁可记下一个拼错的，也不要因为一个校验把真实行为丢掉」——
#:   反过来（拒绝写入）会让一次端点的名字写错变成**证据丢失**，
#:   而丢失是静默的、不可恢复的；多一条 WARNING 则下一轮就能被发现。
KNOWN_ACTIONS: frozenset[str] = frozenset(a for a, _, _ in ACTIONS)
