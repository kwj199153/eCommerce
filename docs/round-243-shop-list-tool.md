# 第 243 轮：店秘书「列店铺」只读工具（方案 A′）—— 实施与实测

> 状态：**已完成并实测通过**。
> 老板指令：`A′`（第 240 轮档位）—— 新增只读 `list_shops` **+ 顺带**把 6 个 `list_*`
> 资料库工具纳入 prompt 点名（同一根因：**prompt 与工具集不对齐**）。
> 诊断依据：`docs/round-240-shop-list-no-tool.md`（三层根因 + 三衍生危害）。
> 实测探针：`.workbuddy/probes/r243_live_check.py`（输出 `out-r243.txt`）。

---

## 一、三层根因 → 三条对应改动

| 第 240 轮根因 | 本轮改动 |
|---|---|
| ①「列店铺」**无专属工具**（只有替换语义的 `switch_shop`，调一次切一次店） | `build_shop_tools()` 1 → 2：新增只读 `list_shops`（`READ_ONLY_METADATA`） |
| ② 规则里**没有一条**覆盖「问有几家店」 | 规则 4 补「**问**店铺 ≠ **换**店铺」，并点名 `switch_shop` 禁用于计数、`get_my_subscription` 是**上限**不是店铺数 |
| ③ 6 个业务工具（`list_*`）在 prompt **零点名** ⇒ 模型在清单里看不到 | 新增【资料库查询工具】分组，逐一登记 6 个工具并说明与 `open_view`（跳页面）的分工 |

---

## 二、改动面（5 个生产/门禁文件 + 1 个新门禁 + 1 个新探针）

| # | 文件 | 改动 |
|---|---|---|
| 1 | `backend/modules/secretary/shop_tools.py` | 新增 `_list_shops_payload()`（+49 行）；`build_shop_tools()` 返回 `[list_shops, switch_shop]`（+24 行） |
| 2 | `backend/modules/secretary/agent.py` | prompt：工具清单点名 `list_shops`、新增【资料库查询工具】分组、规则 2 与规则 4 重写 |
| 3 | `backend/modules/skills/tools_catalog.py` | 登记 `list_shops`（只读）；**分母同步**：店秘书 9→10、去重 59→60、装配点原始 65→66；两处 docstring 分母 |
| 4 | `backend/tests/test_secretary_agent.py` | **收紧墓志铭断言** `{"switch_shop"}` → `{"list_shops","switch_shop"}`；工具数 18 → 19 + 沿革 |
| 5 | `backend/tests/test_tool_catalog.py` · `test_skill_gate.py` | 名单式分母 59 → 60（**4 处**） |
| 6 | `backend/tests/test_secretary_shop_list_tool.py`（新） | 12 条门禁 + 1 条反向注入自检（20 个样本） |
| 7 | `.workbuddy/probes/r243_live_check.py`（新） | 真实 LLM 修前/修后对照 |

**顺序上的一个有意识偏差**：第 240 轮文档写的是 `[switch_shop, list_shops]`，本轮实现为
**只读在前**（`[list_shops, switch_shop]`）—— 工具排列顺序对 LLM 有弱提示作用
（同 `navigation_tools.py` 把 `ask_clarification` 排在 `handoff_to_agent` 之前的做法）。

---

## 三、关键设计：出参为什么**不带 `action` 键**

`list_shops` 的出参**逐键对齐** `modules/library/tools.py` 的四键家族：

```json
{"type": "shop_list", "total": 4, "returned": 4, "items": [
  {"id": "…", "name": "亚马逊1", "platform": "amazon_us",
   "index": 1, "platform_family": "amazon",
   "platform_index": 1, "platform_total": 2}]}
```

★ **刻意不含 `action`**：前端 `dispatchAppAction` 见到 `action: "switch_shop"` 就**真的切店**
（`modules/secretary/agent.py:437` 按已知 action 值精确匹配）。修前的缺陷形态正是
「拿 `switch_shop` 数店铺 ⇒ 顺手把店切了」；只要出参里没有 `action`，这条路就被**机器堵死**
—— 与提示词里怎么写无关。这条由门禁断言（键集合恰为四键 + 出参文本里不含 `"action"`）。

★ 与 `switch_shop` 的**对照判据**也一并钉住：它的 `action` 必须**继续存在**（否则前端再也切不了店，
而「list_shops 没有 action」那条照样绿）。

---

## 四、提示词对齐：把「模型看不见的能力」变成**可 diff 的规格**

本轮新增一条**通用**判据（不只盯这 7 个工具）：

> `SECRETARY_SYSTEM_PROMPT` 里出现的**每个** snake_case token，都必须能解析成
> **真实存在的工具名**；且被点名集合**冻结**为 `EXPECTED_PROMPT_TOKENS`（16 个）。

三个方向都咬：
- 工具改名而 prompt 不跟 ⇒ prompt 指着不存在的工具（**误导**模型）；
- prompt 里新写一个名字但工具不存在 ⇒ 同上；
- 工具新增而 prompt 不跟 ⇒ token 集合变小 ⇒ `prompt_tokens_changed` 转红（**看不见**）。

★ 另外两条「问 ≠ 换」的判据有个**必须记住的形态教训**：

先写成「含 `list_shops` 与 `switch_shop` 的**段落**里要有否定词」——**这条判据没有区分力**。
原因：规则 1–8 是**一个**大段（中间没有空行），段里规则 1/6/7/8 的「不要」会让它**恒真**。
实测：把规则 4 的两个否定词都换成肯定词，段级判据**照样绿**。
⇒ 改成**行级**（否定词必须与它约束的 `switch_shop` **同一行**）后才有区分力。
（跨行的 `get_my_subscription` 与「上限」则用 **80 字符有界窗口** —— 按行判会假红。）

---

## 五、修前 / 修后对照（真实 LLM，三种措辞）

口径：PRE = 改前形态（提示词由本轮补丁规格**逐字反演** + 改前的 18 个工具）；
POST = 生产 `SecretaryAgent(shop_id=…, shop_context=…)`（19 个工具）。
判据只判三件**客观事实**：① 是否调了 `switch_shop`（= 顺手切店）② 是否调了 `list_shops`
③ 回复里是否出现**真实店铺数**（本机可见 4 家）。

| 措辞 | PRE（改前） | 工具 | POST（改后） | 工具 |
|---|---|---|---|---|
| 我有几家店 | ❌ **完全不调工具** | `(无)` | ✅ OK | `list_shops` |
| 我现在绑定了哪些店铺 | ❌ **真切店** | `switch_shop` | ✅ OK | `list_shops` |
| 我总共几个店铺 | ❌ **真切店** | `switch_shop` | ✅ OK | `list_shops` |

- PRE 的 Q1 正文**自己说出了根因**：「目前系统中**没有直接列出"所有店铺"的通用工具**」
  —— 与第 240 轮记录的旁证逐字同款（这就是老板最初看到的「答非所问」）。
- PRE 的 Q2/Q3 正文：「**我们现在切换到了您的第一个店铺**"亚马逊1"」
  —— **老板只是问一句，工作店铺被改了**（无授权状态变更）。
- POST 三组首行：「您当前共有 4 家店铺。分别是：」/「您当前绑定了 4 家店铺，具体如下：」/
  「您总共有 4 个店铺。」——`切店=False`，数字正确。

```
PRE  出现衍生危害 = 3/3          POST 达标 = 3/3
```

---

## 六、门禁与反向注入

`backend/tests/test_secretary_shop_list_tool.py`（**13 项全绿**）钉六件事：

| 组 | 判据 |
|---|---|
| A 形态 | 工厂恰两个工具、只读在前、`list_shops` 的 `coroutine` 指向**真会查库**的实现（AST；防"空壳工具"） |
| B 出参 | 四键契约、`total`/`returned` 与 `items` 一致、**无 `action`**、每项恰 7 个定位字段、**空店铺不抛错** |
| C 对照 | `switch_shop` 的 `action` **仍在**（防"统一出参"把切店改坏） |
| D 对齐 | 7 个工具被点名 + snake token 全部可解析 + 集合冻结 |
| E 明文 | 「不许拿 `switch_shop` 数店」与 `switch_shop` **同行**；`get_my_subscription` 的**上限**语义（80 字符窗口）；只读必须写在**给模型看的 desc** 里 |
| F 目录 | `tools_catalog` 登记且副作用档为**只读**（独立于通用门禁的"两侧一致"） |

**★ 反向注入自检**：`test_judgments_are_not_vacuous_and_can_be_injected` 给出 **20 个样本**
（7 出参 + 8 源码 + 5 提示词），逐码精确比对 `expect`，并断言
**`STATIC_JUDGMENT_CODES` 被样本全覆盖**（19 个静态判据码一个都不能没有反例）。

反向注入必须**成对**声明的一个实例：`factory_drops_list_shops`（删掉整个条目）会**顺带**
命中 `list_shops_desc_not_readonly`（条目都没了自然没有它的只读 desc）——
期望值必须写全，否则判据会以「多命中」的形式转红。

---

## 七、回归

| 范围 | 结果 |
|---|---|
| 受影响面定向（16 文件） | **221 项全绿** |
| 新门禁 | **13 项全绿** |
| 全量（1791 项） | 跑完 **1728** 项后**卡死**（见 §八） |

**全量回归顺带抓出两处漏网消费者**（都已修）：

1. **我的漏项**：`tests/test_skill_gate.py:1191` 的 `assert … == 59` —— 与
   `test_tool_catalog.py` 那三处**同类**。教训：改目录表条数时**必须全仓 grep `59`**，
   不能只改"我知道的那三处"；漏的那一处会变成**静默漂移的断言**。
2. **第 242 轮遗留**（不是本轮引入）：`tests/test_structured_response_consumer.py` 的
   三个 stub 写的是 `lambda shop_id=None:`，而 242 轮起 `route()` 会下传
   `shop_context=` ⇒ **三个用例全部 `TypeError`**。属于本仓铁律
   「改字段名 / 加字段 → 生产者 + 消费者**双向**对账」漏掉的那一半。已补形参并写明来由。

---

## 八、遗留（不在本轮范围，已记入待办）

| # | 事项 | 证据 |
|---|---|---|
| 1 | 全量回归在 `tests/test_users_self_service.py` **第 4 项卡死**（15 min 无任何进展） ⇒ 该项文件需单独立项排查 | `pytest tests/` 停在 1728/1791 |
| 2 | `tests/test_competitor_intel.py` 有 **1 项顺序依赖红**（单独跑该文件**全绿**） | 全量 idx=502 红 / 单跑绿 |
| 3 | 记忆结算：`MEMORY.md` 13171 B（95%），`_pending/` 10 份 65.7 KB（阈值 8 / 40 KB） | `check_budget.py` 3 项 WARN |

---

## 九、一句话结论

「问有几家店」原本**没有承载物**（唯一相关工具是替换语义的 `switch_shop`），
prompt 也没把该意图映射到任何工具、还把 6 个业务工具藏在清单之外 ⇒ 模型只能
要么**不调工具**、要么**拿会切店的工具或套餐上限凑数**。
本轮补上只读 `list_shops`（出参**无 `action`**，从机制上不可能切店）+ 把 7 个工具
**点名进 prompt**，并用一条通用判据把「prompt 与工具集对齐」钉成**可 diff 的规格**。
实测：改前 3/3 出衍生危害，改后 3/3 走 `list_shops` 且答出真实店铺数。
