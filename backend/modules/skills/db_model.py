"""技能仓库（Skill）持久化 ORM 模型（第 181 轮 · 批 B）

==============================================================================
★ 归属字段刻意与 `StoreRecord` **同形**
==============================================================================
`owner_id` / `account_id` / `is_demo` 三个字段的名字、类型、可空性、外键、
索引，全部照抄 `core/stores/models.py::StoreRecord`。

这不是巧合，是**为了复用同一个判定内核**（`core/auth/accounts.py::_matches`）：

    filter_accessible_skills(db, user, skills)   ← 与 filter_accessible_stores 同构
        · 演示身份（user is None）⇒ 只放行 is_demo=True 的行
        · 有身份                  ⇒ 按 account_id ∈ 可见账户集合
        · 私有（visibility=private）⇒ 追加 owner_id == user.id

字段名一致 ⇒ 归属访问器（`getattr`）可以直接复用，**判定不会分叉成两份**。
本仓吃过这个亏：同一可见性两份实现 ⇒ 至少有一份永远测不到（第 177 轮 P1-5）。

==============================================================================
★ 为什么 `name` 全局唯一，而不是「账号内唯一」
==============================================================================
`name` 是**引用键** —— 模型调 `load_skill(name)` 时只给一个名字，
判定层必须能无歧义地定位到一行。若按 `(account_id, name)` 唯一，
则「同一个名字在多个账号各有一份」时，按名字查会返回多行，
而**挑哪一行**就成了第二个判定点（另一个「两份实现」的种子）。

全局唯一还有一层好处：`name` 可以直接当「技能标识」对外暴露，
前端、工具、日志三处指的是同一个东西，不需要额外的 id 映射。

代价是不同账号不能起同名技能 —— 对「每个账号自己的技能仓库」这个当前形态
是可接受的；将来真要做「同名技能各自定制」，正确的改法是引入命名空间前缀
（`<scope>/<name>`），而不是放宽唯一约束把歧义放进判定层。

==============================================================================
★ 版本：为什么不只留一个 `version` 字符串
==============================================================================
老板要的「版本」如果只做成一个可编辑的字符串字段，那它**没有真源** ——
用户改了版本号但内容没变、或内容变了但版本号忘改，两者都无从发现。

所以：`skills.version` 是**当前版本号**（展示 / 引用用），
`skill_revisions` 是**每次内容变更的不可变快照**（真源）。
保存时若正文发生变化，自动落一条 revision；版本号由业务层自增（patch +1）。
「回滚」= 把某个 revision 的正文写回 skill 并落一条新的 revision ——
**不是**删掉历史（历史只增不改，否则「回滚」这个动作本身就没有可追溯性）。
"""

from datetime import datetime
from typing import Optional

from sqlalchemy import (
    Boolean,
    DateTime,
    ForeignKey,
    Integer,
    JSON,
    String,
    Text,
    UniqueConstraint,
)
from sqlalchemy.orm import Mapped, mapped_column

from core.database import Base


class SkillRecord(Base):
    """技能仓库表（`/api/v1/skills` 数据源）。

    一份技能 = 元数据（第一级披露用）+ 正文（第二级披露用），
    字段划分严格对应 `ai_infra.skills` 的两级渲染：

        第一级  name / title / description / enabled_agents / enabled
        第二级  content
    """

    __tablename__ = "skills"

    # 主键：skill_xxxxxxxx（与 stores_store / mon-* 同风格，前缀可读）
    id: Mapped[str] = mapped_column(String(64), primary_key=True)

    # 技能标识（kebab-case）。★ 全局唯一 —— 见模块 docstring 的论证。
    name: Mapped[str] = mapped_column(String(64), nullable=False, unique=True, index=True)

    # 展示名（中文）。与 name 分开：name 是给模型/工具用的稳定引用键，
    # title 是给人看的，改名不影响引用。
    title: Mapped[str] = mapped_column(String(128), default="")

    # 图标（emoji，通常 1 个字符，最长不超过 16）。第 188 轮。
    # ★ 存 emoji 字符本身，不存图片 URL / 图标名：
    #   前端现有 14 张快捷卡片的图标**全是 emoji**（📋 🚨 🧠 …），
    #   存字符则同一套渲染直接复用，前端零新增分支。
    # ★ 空串 = "没生成 / 用户没填"。**刻意不给它一个 default emoji**：
    #   一个像模像样的默认图标会让"AI 从未成功生成过"在界面上完全不可见
    #   （本仓「降级路径禁用全 0 兜底」的同族形态）。兜底渲染归前端。
    #   生成与校验的真源在 `modules/skills/icon.py`。
    icon: Mapped[str] = mapped_column(String(16), default="")

    # ★★ 描述 —— **第一级披露的唯一依据**。
    #    模型只看这一行决定「要不要加载这个技能」，所以它必须写清
    #    「什么场景该用它」。写成"这是一个技能"等于没写。
    description: Mapped[str] = mapped_column(Text, default="")

    # ★★ 正文 —— **第二级披露的内容**，只在 `load_skill` 被调用时才读出。
    content: Mapped[str] = mapped_column(Text, default="")

    # 该技能配套的工具名列表（工具定义）。存名字而不是内联定义：
    # 工具的定义真源在代码里（`modules/*/tools.py`），此处只做**引用**，
    # 避免「工具改了 schema、技能里那份还是旧的」这种双份漂移。
    tools: Mapped[Optional[list]] = mapped_column(JSON, nullable=True)

    # 当前版本号（语义化，如 "1.0.0"）。历史版本见 skill_revisions。
    version: Mapped[str] = mapped_column(String(32), default="1.0.0")

    # 可见范围（权限）：
    #   account —— 账号内共享（同账号成员都能看到，默认）
    #   private —— 仅创建者可见（owner_id == user.id）
    # ★ 它**真的参与判定**（见 core/auth/accounts.py::_matches_skill），
    #   不是装饰性字段 —— 本仓判据：有字段但不参与判定 = 死重量。
    visibility: Mapped[str] = mapped_column(String(16), default="account")

    # 全局启用开关。关闭 ⇒ 不进入任何 Agent 的技能目录（但历史与配置保留）。
    # ★ 与 `enabled_agents` 是**与**关系：两者都满足才进目录。
    enabled: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)

    # ★★ 「Agent 内勾选启用」的落点（范式 1）：这个技能对**哪几个** Agent 生效。
    #    存后端 `agent_name`（**不是**前端 agent id）—— 因为注入发生在后端，
    #    `PromptContext.agent_name` 就是它。两者的桥接表见 `modules/skills/agents.py`。
    #    空列表 = 不启用给任何 Agent（技能建好但还没分配，是合法中间态）。
    enabled_agents: Mapped[Optional[list]] = mapped_column(JSON, nullable=True)

    # ★★★ 「是否在 Agent 对话页显示为快捷卡片」（第 248 轮）—— 与 `enabled_agents`
    #     **刻意分开的第二把闸**。
    #
    #     起因：`enabled_agents` 同时承担了两个**语义不同**的判定，而此前它们共用
    #     同一组值（这是"一个字段两个意思"的经典形态）：
    #        语义 A · 对本 Agent **生效** —— 进技能目录（第一级披露）/
    #                 `load_skill` 可加载（第二级披露）/ 可被「点名」通道命中；
    #        语义 B · 在对话页**显示为可点卡片**。
    #     老板的原话：「【复盘结论写法】是被周报月报**引用**的，那么这个是否不应该
    #     出现在快捷卡片栏？」—— 它必须保留语义 A（周报正文逐字写着「表达结构沿用
    #     「复盘结论写法」」，取消启用会让那三处引用变成**悬空引用**，还会连带
    #     `_load_skill` 的回话把「没有找到名为 … 的技能」交给模型），但它**不该是卡片**：
    #     点下去给的不是一份东西，而是一套"怎么写"的规矩。
    #
    #     ⇒ 语义 B 拆到本列。**没有"零改动的正确解法"**：`enabled` 是三通道共用的
    #       全局开关，动它三条一起断（同族判据：同一判定两份实现 ⇒ 至少一份永远测不到；
    #       这里反过来 —— 一个字段两个判定 ⇒ 想动其中一个必然会误伤另一个）。
    #
    # ★ 默认 `True` = **保持现行为**：22 条演示技能里 21 条原样，只有被判定为
    #   「规矩型」的那条在 seed 里显式标 `False`。
    # ★ 它**不参与**后端任何注入判定（`filter_accessible_skills` /
    #   `read_skill_for_agent` / `build_catalog_for` 一行都不看它）——
    #   它只决定**对话页要不要给它一张卡片**。后端若也用它过滤，就等于
    #   「不让模型加载」，那是语义 A，本列刻意不做那件事。
    as_shortcut: Mapped[bool] = mapped_column(
        Boolean,
        nullable=False,
        default=True,
        comment="在 Agent 对话页显示为快捷卡片（第 248 轮）",
    )

    # ====== 归属（★ 与 stores_store 逐字段同形，见模块 docstring）======
    owner_id: Mapped[Optional[str]] = mapped_column(
        String(36),
        ForeignKey("users.id", ondelete="SET NULL", name="fk_skills_owner_id_users"),
        nullable=True,
        index=True,
    )
    account_id: Mapped[Optional[str]] = mapped_column(
        String(36),
        ForeignKey("accounts.id", ondelete="SET NULL", name="fk_skills_account_id_accounts"),
        nullable=True,
        index=True,
    )
    # 演示标记：仅对「无身份」的演示请求可见（与 stores_store.is_demo 同一套语义，
    # 由 `modules/skills/seed.py::ensure_demo_skills` 双向收敛）。
    is_demo: Mapped[bool] = mapped_column(
        Boolean, nullable=False, default=False,
        comment="演示技能：仅对「无身份」的演示请求可见（第 181 轮）",
    )

    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime, default=datetime.utcnow, onupdate=datetime.utcnow
    )


class SkillRevisionRecord(Base):
    """技能版本历史（**不可变**快照）。

    ★ 为什么单独一张表而不是把历史塞进 `skills.content_history` 的 JSON 列：
      版本历史要按「逐条查看 / 逐条回滚」访问，是**行级**的读写模式；
      塞进 JSON 只会换来「整段读出再改再写回」的读放大与并发覆盖。
      这与 `modules/monitors/db_model.py` 里「7 维时序用 JSON」的判据同源 ——
      **按访问模式选存储形态**，两个方向都有过实际决策。

    ★ `changed_by` 指向用户：谁改的。这不是审计装饰 —— 团队共享技能时
      「这条改动是谁做的」是回滚决策的必要信息。
    """

    __tablename__ = "skill_revisions"

    id: Mapped[str] = mapped_column(String(64), primary_key=True)  # rev_xxxxxxxx
    skill_id: Mapped[str] = mapped_column(
        String(64),
        ForeignKey("skills.id", ondelete="CASCADE", name="fk_skill_revisions_skill_id_skills"),
        nullable=False,
        index=True,
    )
    # 本次变更后的版本号（与 skills.version 同一口径）
    version: Mapped[str] = mapped_column(String(32), default="1.0.0")
    # 变更后的正文快照
    content: Mapped[str] = mapped_column(Text, default="")
    # 变更说明（可选，用户填）
    note: Mapped[str] = mapped_column(String(255), default="")
    # create / update / rollback —— 便于前端区分「这次是怎么来的」
    action: Mapped[str] = mapped_column(String(16), default="update")
    changed_by: Mapped[Optional[str]] = mapped_column(
        String(36),
        ForeignKey("users.id", ondelete="SET NULL", name="fk_skill_revisions_changed_by_users"),
        nullable=True,
        index=True,
    )
    changed_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)


class SkillFavoriteRecord(Base):
    """技能收藏（⭐）—— 「用户 × 技能」的关系（第 194 轮）。

    ★ 为什么是独立表，而不是 `skills` 上再加一个 JSON 列：
      判据是**访问模式**（与 `enabled_agents` 那类 JSON 列同源、结论相反）：
        1. 收藏是**按人**的 —— 张三收藏了不代表李四收藏了，
           塞进 `skills` 行会把"谁的收藏"这个问题变成无解；
        2. 独立读写 —— 一个人点星标不该改 `skills` 行、更不该让
           `skills.updated_at` 抖动（那会让"最近修改"排序失真，
           而这一轮刚好要做按更新时间排序）；
        3. 要支持**反查**「我收藏了哪些技能」—— JSON 列做不到，
           只能整表读出再遍历（读放大）。

    ★ `(user_id, skill_id)` 唯一不是"顺手加的约束"，它是**幂等切换**的依据：
      重复点星标不该产生第二行。业务层的 `toggle` 也依赖它兜底 ——
      两个并发请求同时插，唯一约束会让其中一个失败而不是留下脏数据。

    ★ 两个外键都用 CASCADE（与 `skills.owner_id` 的 SET NULL 刻意不同）：
      收藏行**没有独立价值** —— 用户注销或技能删除后，这条收藏不指向
      任何还能被解释的东西，留着就是孤儿行。而技能本体即使创建者注销
      也仍然是团队资产 ⇒ 那边必须 SET NULL 保命。
    """

    __tablename__ = "skill_favorites"

    id: Mapped[str] = mapped_column(String(64), primary_key=True)  # fav_xxxxxxxx

    user_id: Mapped[str] = mapped_column(
        String(36),
        ForeignKey("users.id", ondelete="CASCADE", name="fk_skill_favorites_user_id_users"),
        nullable=False,
        index=True,
    )
    skill_id: Mapped[str] = mapped_column(
        String(64),
        ForeignKey("skills.id", ondelete="CASCADE", name="fk_skill_favorites_skill_id_skills"),
        nullable=False,
        index=True,
    )
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)

    __table_args__ = (
        UniqueConstraint("user_id", "skill_id", name="uq_skill_favorites_user_skill"),
    )


# ====== 外键目标表的 metadata 注册（★ 必须留在文件末尾）======
#
# 本模块声明了两个**字符串**外键目标（`users` / `accounts`），
# 且 `skill_revisions.skill_id` 指向本文件自己的 `skills`。
# 缺注册时不会在 import 期报错，而是在**某一次 flush 的拓扑排序**里抛：
#
#     NoReferencedTableError: Foreign key associated with column
#     'skills.account_id' could not find table 'accounts'
#
# 报错指向外键本身（看起来像"外键写错了"），且**整个 pytest 套件在 setup 阶段
# 全 ERROR** —— 因为测试进程不走 `main.py` 的 lifespan。
# 详见 `core/stores/models.py` 末尾那段完整的事故记录（同一模式）。
#
# ⇒ 由**声明方自己**把目标表带进来（自洽），不依赖「某个入口恰好先 import」。
#   配套回归：`tests/test_schema_parity.py` 三条用例。
import core.identity.account_models  # noqa: E402,F401  注册 accounts / account_members
import core.identity.models  # noqa: E402,F401  注册 users
