# 第 240 轮：「我有几家店」答非所问 —— 诊断报告

> 状态：**诊断已完成（有实测证据）；修复方案待老板拍板。**
> 起因：老板报「问『我有几家店』，回答是一段『如果您想…请问您接下来希望做什么？😊』的菜单，答非所问」。
> 探针：`.workbuddy/probes/240a_shop_count_behavior_probe.py`（输出 `out-240a.txt`）
>
> ★★ **已实施（第 243 轮）**：老板拍板 **A′** ⇒ 见 `docs/round-243-shop-list-tool.md`
> （改动面 / 出参契约 / 修前修后实测 / 门禁与反向注入）。
> 本文件自此是**历史诊断**：§五的改动面清单与最终实现有一处有意偏差 ——
> `build_shop_tools()` 实际返回 `[list_shops, switch_shop]`（**只读在前**）。

---

## 一、现象复现（走真 HTTP，每条新建 session，n=2）

| 措辞 | 次 | 日志 `tools=` | `actions=` | 结果 |
|---|---|---|---|---|
| 我有几家店 | 1 | `['switch_shop']` | 1 | 答 4 ✓（但**真切了店**） |
| 我有几家店 | 2 | `['get_my_subscription','switch_shop']` | 1 | 答 4（路径诡异） |
| **我有几家店铺** | 1 | **`-`** | **0** | ❌ **不调工具**，且自述「系统目前不提供直接列出所有店铺的工具」 |
| **我有几家店铺** | 2 | **`-`** | **0** | ❌ **不调工具**（给菜单 = 老板看到的） |
| 列出我的店铺 | 1 | `['switch_shop']` | 1 | 答 4 ✓（真切店） |
| 列出我的店铺 | 2 | `['switch_shop']` | 1 | 答 4 ✓（真切店） |
| 我现在有几家店铺？ | 1 | `['switch_shop']` | 1 | 答 4 ✓ |
| **我现在有几家店铺？** | 2 | **`['get_my_subscription']`** | 0 | ❌ **答「最多可以绑定3家」** |

**结论**：同一意图在极小措辞差异下行为**剧烈摇摆** —— 差一个「铺」字（「我有几家店」→「我有几家店铺」），
从「调工具答对」直接翻转为「完全不调工具」。这不是抽样噪声（n=2 两组各自一致）。

---

## 二、根因（三层，逐层收窄）

### 第 1 层：**这个意图没有承载物** —— 「列店铺」无专属工具

`build_shop_tools()`（`modules/secretary/shop_tools.py:215-234`）**只产出 `switch_shop` 一个工具**，
而它的 desc 通篇只讲「**切**到 XX 店」：

> 「切换当前工作的店铺（数据源）。老板说『切到 XX 店』『换个店铺』『用我的美国店』…时使用。」

**没有任何工具负责「查看/列举店铺」**。`_list_shops()`（`shop_tools.py:80`）是实现好了的、
且**已按归属过滤**（第 239 轮修复），但它只是 `_switch_shop` 的**内部上游**，从未暴露成工具。

### 第 2 层：**prompt 也没把这个意图映射到任何工具**

`SECRETARY_SYSTEM_PROMPT`（`agent.py:33-79`）规则 4 只写：

> 「老板要…『**换**店铺』→ 调 switch_shop」

规则里**没有一条**覆盖「问有几家店 / 列出我的店铺」。「查看店铺」与「切换店铺」是两件事，
prompt 只写了后者。

### 第 3 层：**18 个工具里 9 个在 prompt 里零点名**

实测对账（`SecretaryAgent().tools` × 子串匹配 `SECRETARY_SYSTEM_PROMPT`）：

| 分类 | 工具 | prompt 点名 |
|---|---|---|
| 【路由工具】 | switch_agent / handoff_to_agent / select_product | YES |
| 【系统/店铺/UI】 | open_view / open_account_menu / set_theme / switch_shop / get_my_subscription | YES |
| 规则 6 提到 | ask_clarification | YES |
| **库查询（6 个）** | **list_candidates / list_products / list_assets / list_monitors / list_faqs / list_platform_rules** | **NO** |
| 框架基础能力（3 个） | plan_tasks / update_task / load_skill | NO |

后 3 个（规划器 / 技能加载）由框架自动装配，不点名可理解；但**前 6 个是业务能力**，
prompt 里一个都没提 ⇒ 模型在 system prompt 的「工具清单」里**看不到它们**。

> ★ 决定性旁证：模型在「我有几家店铺」那轮的正文里**自己说出了根因** ——
> 「**系统目前不提供直接列出所有店铺的工具**」。它准确知道这个能力不存在。

**综合**：模型被点名了 8 个工具，其中**没有一个能回答「有几家店」**；
剩余 9 个虽在 `tools` 参数里但 prompt 未提 ⇒ 它只落到规则 7（「与工具无关的闲聊，礼貌回应即可」）
去打了那段太极菜单。

---

## 三、三个衍生危害（**都比原现象严重**）

1. **★ 会拿 `get_my_subscription` 凑数、给出错数字**
   实测「我现在有几家店铺？」第 2 次：调 `get_my_subscription` → 答「**最多可以绑定3家店铺**」。
   那是**套餐上限**，不是店铺数（实际 4 家）。**用户会当真** —— 这比"不回答"更坏。

2. **★ `switch_shop` 被当查询用，且带副作用**
   模型为了让 step 里有东西，真的执行了切换（正文：「我已帮您切换到了您的第一个店铺『亚马逊1』」）。
   **老板只是问一句，当前店铺被改了** —— 这是无授权状态变更。

3. **措辞敏感度极高**（见 §一）：同一意图，差一个字行为反转 ⇒ 用户无法预期。

**为什么长期没被抓到**：`tests/test_secretary_agent.py:151` 有一条断言把缺陷钉成了规格 ——

```python
assert names == {"switch_shop"}      # build_shop_tools() 的返回值
```

⇒ 「店铺工具只有 switch_shop」被写成**规格**，任何「补一个列店铺工具」的改动都会**先撞这条测试**；
而它没有任何一条门禁覆盖「问几家店能否答对」。**这条断言是负资产**（第 239 轮同款教训的第二次实例）。

---

## 四、修复方案（待拍板）

| 方案 | 做法 | 评价 |
|---|---|---|
| **A（推荐）** | **新增只读工具 `list_shops`** —— 把已有的 `_list_shops()` 包成 `StructuredTool`（`READ_ONLY_METADATA`），并在 prompt 里点名 + 加一条规则「问『有几家店 / 列出我的店铺』→ 调 `list_shops`，按 `total` 如实回答」 | 语义正、**零副作用**、复用已修好的归属过滤 |
| B | 只改 prompt，让模型用 `switch_shop` 拿 `total` | **否决** —— `switch_shop` 有副作用，等于每次问「有几家」都改当前店铺 |
| C | 给 `switch_shop` 加 `dry_run` 参数 | 否决 —— 一工具两职责，且模型未必会传该参数 |
| A′ | A **+ 顺带**把 6 个 `list_*` 也纳入 prompt 点名（同一根因：prompt 与工具集不对齐） | 建议与 A 一并做（静态文本，不进缓存动态段） |

---

## 五、改动面（方案 A，约 6 处 / +60 行）

| # | 文件 | 改动 |
|---|---|---|
| 1 | `modules/secretary/shop_tools.py` | `build_shop_tools()` 返回 `[switch_shop, list_shops]`（+1 工具，约 25 行） |
| 2 | `modules/secretary/agent.py` | prompt 补 `list_shops` 点名 + 规则（约 6 行） |
| 3 | `modules/skills/tools_catalog.py:328-394` | 登记新工具（人工目录，注释「店秘书（9）」需同步） |
| 4 | `tests/test_secretary_agent.py:151` | **收紧墓志铭断言**：`{"switch_shop"}` → `{"switch_shop","list_shops"}` |
| 5 | 新增门禁文件 | `list_shops` 装配 + prompt 点名 + **只读且不改当前店铺**（含反向注入） |
| 6 | `modules/skills/tools_catalog.py` 等名单式门禁 | 按 `test_tool_registry_guard.py` 校验重名 / 交叉引用 |

**前置校验**（实施时做）：`list_shops` 工具名全仓唯一；`test_tool_registry_guard.py` 的能力承诺一致性判据。

---

## 六、待办

- [ ] 老板拍板：走 A（推荐）还是 A′（A + 6 个 list_* 一并点名）
- [ ] 实施 + **修前/修后对照**（复用 240a 的措辞矩阵：修前基线已在本轮量出）
- [ ] 门禁 + 反向注入验证
