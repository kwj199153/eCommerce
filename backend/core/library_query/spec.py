"""资料库通用查询 —— 声明式元数据（内核侧，行业无关）。

★ 为什么要抽这一层（第 218 轮）
==============================================================================
第 216 轮把「候选库的读口」修成了通用查询，动因是老板问「换成真数据源还通用吗？
换问法（售价前 5 / 评审通过）还能查吗」。修完那一次之后，实测发现**同样的三处
结构性缺陷在其余 5 个库里原样存在**（详见 `modules/library/tools.py` 的库清单）：

  | 库 | 排序维度 | 过滤维度 | limit 下推 | total 口径 |
  |---|---|---|---|---|
  | 候选库（第 216 轮已修） | 6 维白名单 | 评审状态 | ✅ | ✅ 真实 |
  | 产品库 | 无 | spu_id | ❌ 内存切片 | 恰好对（全量拉） |
  | 素材库 | 无 | 无 | ❌ | len |
  | 竞品监控池 | 硬编码 | 无 | ❌ | len |
  | 业务话术库 | 硬编码 | 无 | ❌ | len |
  | 平台规则库 | 硬编码 | 无 | ❌ | len |

「页面上点一下就能得到正确答案、Agent 却答不了/答错」不是单点 bug，是 6 库规模的
系统性差距。修法是**抽执行内核**，而不是把候选库那套复制 6 份 —— 复制 6 份等于
把上一轮踩过的坑再踩 6 遍。

★ 本模块**只管机制，不管语义**
==============================================================================
可收敛的 7 件事（候选库那轮已逐条实现过一遍，证明可收敛）：
  作用域 / 排序白名单 / limit 归一 / 真实 count / 去重 / 字段投影 / 出参信封+错误分类

**不进本模块**的四类：写入、聚合统计、向量语义检索、跨库领域查询。
（硬塞进来就成了「万能函数」—— 那是另一种技术债。）

★ 为什么 spec 住**各模块自己的包**，而不是集中放一处
==============================================================================
分层门禁（`tests/test_module_layering.py`）规定：`candidates` / `products` 是 SHARED，
而 `assets` / `monitors` / `knowledge_base` / `platform_rules` 是 **PLUGIN**，
且 **SHARED 不得顶层 import PLUGIN**（会成环）。
⇒ 若把 6 份 spec 集中放在 `modules/library/specs.py`（library 是 SHARED），
  就是一条 SHARED → PLUGIN 的顶层边，门禁直接转红。
⇒ 正解：**每库在自己包里声明自己的 spec**（PLUGIN → KERNEL 方向合法），
  消费方（`modules/library/tools.py`）在**函数内**延迟 import。
  先例：`assets` 就是「仅被 secretary 的函数内工具引用（非顶层）」。

★ 本模块**不 import 任何 modules.***
==============================================================================
模型类由调用方以**参数**注入（`LibrarySpec(model=CandidateRecord, ...)`），
所以分层方向天然合法，`test_core_layering.py` 无须豁免。
"""

from typing import Any, Dict, NamedTuple, Optional, Tuple


class LibraryQueryError(ValueError):
    """资料库查询参数非法（排序维度 / 过滤维度 / 过滤取值不在值域内）。

    ★ 为什么要有**专属异常**而不是直接抛 `ValueError`：两个消费者要给出
      **不同形态**的「人话」，但判定必须是**同一份实现**——
        · REST 路由 → `HTTPException(400, detail=...)`
        · Agent 工具 → `{"type": "invalid_argument", ...}`，
          模型据此**改参数重试**（而不是把它转述成「读取失败」）
      本仓判据：同一判定两份实现 ⇒ 至少一份永远测不到。
    """


class FilterSpec(NamedTuple):
    """一个可过滤维度。

    Args:
        attr: 模型上的**属性名**（字符串，不是列对象）——
            ★ 用字符串是有意的：门禁要能「**按属性名相等**」核对它真的存在于模型上
              （本仓铁律：判据禁「源码字符串包含」，会被同族更长标识符顶掉）。
              `LibrarySpec.__init__` 会用 `hasattr` 做**构造期**核对 ⇒ 写错列名即刻炸。
        values: 值域（`None` = 自由文本，不做值域校验）。
            给了值域 ⇒ 传值域外的值**显式报错**，不再静默回空列表。
            ★ 这是第 216 轮 ③ 的教训：合法值只写在 docstring 里时，
              `args_schema` 没有 `enum` ⇒ 传「通过」「APPROVED」静默回**空结果**，
              「真的没有」与「你传错了」被压成同一个结果（归因错方向）。
    """

    attr: str
    values: Optional[Tuple[str, ...]] = None


#: 去重时的默认排序（「每条保留最新评估」的判定口径）。
_DEFAULT_DEDUP_ORDER: Tuple[Tuple[str, str], ...] = (
    ("updated_at", "desc"),
    ("id", "desc"),
)


class LibrarySpec:
    """一个资料库的**完整声明**（查询侧的元数据真源）。

    ★ 唯一构造入口是关键字参数 —— 参数多且相邻类型相似（model / scope_model
      都是类，sort_fields / filters 都是 dict），位置传参极易错配且看不出来。

    Args:
        key: 库的唯一 key（**与前端侧边栏一致**，供跨端对齐门禁核对）。
        label: 中文名（用于生成工具 description，避免各库手写中文名漂移）。
        model: 主模型类（查询主体）。
        sort_fields: `{对外排序名: (模型属性名, 方向)}`。
            对外名 = REST 查询参数 / 工具参数 / 前端 `sortBy` **三名一体**。
        default_sort: 不指定排序时用哪个 key（必须在 `sort_fields` 里）。
        scope_model: 承载 `shop_id` 的模型（默认 = `model`）。
            ★ 产品库的 SKU 通过 `spu_id` 归属 SPU ⇒ 这里传 `SpuRecord`，
              与 REST 端点 `products/router.py::list_skus` 的作用域口径逐字一致。
        filters: `{对外过滤名: FilterSpec}`。
        dedup_key: 去重键工厂 `(model) -> SQL 表达式`；`None` = 不做去重。
            ★ 给的是**纯函数**（无副作用），不是「每库自己写查询」——
              查询主体仍由内核构建，这里只回答「同一个商品的判定键怎么算」。
        dedup_order: 去重时保留哪一条的排序（默认 `updated_at desc, id desc`）。
        joins: `((目标模型, 连接条件), ...)`。
        select_extra: 除 `model` 外还要一起 select 的实体（产品库要取 SPU 标题）。
        tie_breaker: 排序值相同时的兜底列（默认 `id`，保证结果确定性）。
    """

    __slots__ = (
        "key", "label", "model", "sort_fields", "default_sort", "scope_model",
        "filters", "dedup_key", "dedup_order", "joins", "select_extra", "tie_breaker",
    )

    def __init__(
        self,
        *,
        key: str,
        model: Any,
        sort_fields: Dict[str, Tuple[str, str]],
        default_sort: str,
        label: str = "",
        scope_model: Any = None,
        filters: Optional[Dict[str, FilterSpec]] = None,
        dedup_key: Any = None,
        dedup_order: Optional[Tuple[Tuple[str, str], ...]] = None,
        joins: Tuple[Any, ...] = (),
        select_extra: Tuple[Any, ...] = (),
        tie_breaker: str = "id",
    ) -> None:
        if not key:
            raise ValueError("LibrarySpec.key 不能为空（跨端对齐门禁按它对账）")
        if not sort_fields:
            raise ValueError(f"LibrarySpec[{key}] 必须至少有一个排序维度")
        if default_sort not in sort_fields:
            raise ValueError(
                f"LibrarySpec[{key}] 的 default_sort={default_sort!r} 不在 sort_fields 里"
            )
        # ★ 构造期核对列名真的存在 —— 比门禁更早一步炸，且不依赖门禁被跑。
        #   SQLAlchemy 声明式类上 `hasattr(Model, "price")` 对 instrumented
        #   attribute 返回 True；写错列名（如 estimated_sales）返回 False。
        for sort_key, (attr, direction) in sort_fields.items():
            if not hasattr(model, attr):
                raise ValueError(
                    f"LibrarySpec[{key}] 排序维度 {sort_key!r} 指向 {model.__name__}.{attr}"
                    f"，该属性不存在"
                )
            if direction not in ("asc", "desc"):
                raise ValueError(
                    f"LibrarySpec[{key}] 排序维度 {sort_key!r} 的方向 {direction!r} 非法"
                )
        for filter_key, fs in (filters or {}).items():
            if not hasattr(model, fs.attr):
                raise ValueError(
                    f"LibrarySpec[{key}] 过滤维度 {filter_key!r} 指向 {model.__name__}.{fs.attr}"
                    f"，该属性不存在"
                )
        if not hasattr(model, tie_breaker):
            raise ValueError(
                f"LibrarySpec[{key}] 的 tie_breaker={tie_breaker!r} 在 {model.__name__} 上不存在"
            )

        self.key = key
        self.label = label or key
        self.model = model
        self.sort_fields = dict(sort_fields)
        self.default_sort = default_sort
        self.scope_model = scope_model if scope_model is not None else model
        self.filters = dict(filters or {})
        self.dedup_key = dedup_key
        self.dedup_order = dedup_order or _DEFAULT_DEDUP_ORDER
        self.joins = tuple(joins)
        self.select_extra = tuple(select_extra)
        self.tie_breaker = tie_breaker

    @property
    def sort_keys(self) -> Tuple[str, ...]:
        """白名单键序（= 报错文案与工具 description 里的可选值顺序）。"""
        return tuple(self.sort_fields)

    @property
    def filter_keys(self) -> Tuple[str, ...]:
        return tuple(self.filters)
