# 第 283 轮 · 提示词版本管理 A 档（规格化 + 归位）处置记录

> 范围：让提示词从「住 .py 常量里的裸字符串」变成**有版本、有指纹、有变量契约**的可对账资产。
> 日期：2026-09-27
> 状态：已落地 + 反向注入 6/6 真红 + 全量回归绿

---

## 1. 结论先行

| # | 缺陷 | 性质 | 处置 |
|---|------|------|------|
| 1 | 提示词无版本、无指纹 | 不可观测 | `PromptSpec`：version（人写）+ `sha256(content)[:12]`（内容算） |
| 2 | 变量靠 `str.format` 猜，JSON 示例会炸 / 缺变量静默发占位符 | 静默失效 | `required_vars` 反解 + 校验；渲染只替换已声明变量；缺变量**抛错** |
| 3 | 两张注册表「重名怎么办」答案相反（一处静默覆盖、一处 raise） | 同一判定两份实现 | 统一为**当场 raise** |
| 4 | 8 份提示词散落在 agent / icon 里，3 份注册项零消费（死登记） | 无法对账、无法覆写 | 归位到各模块 `prompts.py` + 走注册表 + AST 门禁 |

---

## 2. 取证（动手前先把全仓提示词数清楚）

上一轮的教训是「报 8 份 → 实到 13 份」，所以本轮先跑 AST 扫描，不靠 grep 猜。

**实到 17 份**提示词常量，其中：

| 形态 | 数量 | 说明 |
|------|------|------|
| 已注册且**真被消费**（走 `get_prompt_template`） | 4 | `aigc_media`(3 处) / `competitor_intel`(3 处) / `customer_service`(4 处) / `product_research`(2 处) |
| 已注册但**零调用点**（死登记） | 2 | `ad_analysis`、`listing_generator` |
| 已注册但消费方**直接用常量**（测试钉住） | 1 | `review_analyst`（`tests/test_review_analyst_agent.py:87` 断言 agent 必须 `from .prompts import REVIEW_ANALYST_PROMPT`） |
| **散落未注册** | 7 | ad(502) / listing(892) / product_research_system(640) / secretary(3395) / aigc 划词翻译(393) / aigc 提示词增强(372) / skills 图标(174) |
| 留在 `prompts.py` 内部使用 | 1 | `memory/prompts.py::EXTRACT_INSTRUCTIONS`（`tasks.py` 直接 import，测试钉住） |

**关键发现：真正在跑的常常不是注册的那份。**
`ad_analysis` 注册的是 141 字的角色描述，而 `agent_ad.py` 里 `SYSTEM_PROMPT`（502 字，含 ACoS/RoAS 行业基准值——业务代码注释里还引用它）才是 `self.system_prompt` 的真身。`listing_generator` 同理（注册 159 字 → 真身 892 字）。
⇒ 注册表里有 2 条**死登记**，真身在外面裸奔。

---

## 3. 落地

### 3.1 新增 `ai_infra/llm/prompt_spec.py`（机制层）

* `PromptSpec`（frozen dataclass）：`name` / `content` / `version` / `required_vars`
  * `fingerprint` = `sha256(content)[:12]` —— **只算正文**：改名或升版本不改变文本，就不该改变指纹
  * `required_vars` 不传 → 按正文自动反解；传了 → 必须与反解结果一致，否则**注册期报错**
* `extract_required_vars()`：`string.Formatter().parse` 反解，**只收标识符形态**
* `render_prompt()`：**只替换已声明变量**，其余花括号原样保留
* `RenderedPrompt` —— **`str` 的子类**

**三个设计决定与理由：**

1. **指纹 vs 版本，两个都要。** version 是**人**写的（表达「这次是语义升级」），会忘改；fingerprint 是**内容**算的，改一个字符就变。只留一个都回答不了「线上跑的是哪一版」。
2. **为什么 `RenderedPrompt` 做成 `str` 子类而不是 dataclass。** 全仓 12 处 `system_prompt=self.get_prompt_template("aigc_media")` 把返回值当字符串用。若返回值不再是 `str`，这 12 处**全部**要改，而它们没有任何一处需要版本信息——为携带元数据去改 12 处调用点，是让「可观测」去打扰「取提示词」。做成 `str` 子类后：既有调用点**零改动**，排障处可顺手读 `.version` / `.fingerprint`。
3. **为什么变量只认标识符。** 提示词正文里普遍含 JSON 示例（`{"section": "运营偏好", ...}`）。`Formatter().parse` 会拆出 field_name=`"section"`（**带引号**），`str.format` 遇到它直接抛 `KeyError`。本仓活样本：`modules/memory/prompts.py::EXTRACT_INSTRUCTIONS`。所以：变量只认标识符，渲染只替换已声明变量，JSON 示例**原样发给模型**。

### 3.2 注册表改造 `ai_infra/llm/dashscope_client.py`

* `PROMPT_TEMPLATES: Dict[str, PromptSpec]`（值从 `str` 升级为规格）
* `register_prompt_template(name, template, *, version="1", required_vars=None)` —— **重名 raise**
* 新增 `get_prompt_spec()` / `registered_prompts()`（返回元组，不给调用方绕过 `register_*` 的后门）
* `get_prompt_template()` 委托 `get_prompt_spec(name).render(**kwargs)`

### 3.3 8 份提示词归位

| 注册表键 | 原位置 | 新位置 | 消费方改动 |
|---------|--------|--------|-----------|
| `ad_analysis` | `agent_ad.py` 类属性（502，**真身**） | `ad_analysis/prompts.py` | `self.get_prompt_template("ad_analysis")` |
| `listing_generator` | `agent_listing.py`（892，**真身**） | `listing_generator/prompts.py` | `self.get_prompt_template("listing_generator")` |
| `product_research_system` | `agent_product_research.py`（640） | `product_research/prompts.py`（新增） | `self.get_prompt_template("product_research_system")` |
| `secretary` | `secretary/agent.py`（3395） | `secretary/prompts.py`（**新建**） | `_with_shop_fact(get_prompt_template("secretary"), ...)` |
| `aigc_selection_translate` | `agent_aigc.py` 类属性（393） | `aigc_media/prompts.py` | `self.get_prompt_template(...)` |
| `aigc_enhance_prompt` | `agent_aigc.py` 类属性（372） | `aigc_media/prompts.py` | `self.get_prompt_template(...)` |
| `skills_icon` | `skills/icon.py`（174） | `skills/prompts.py`（**新建**） | `get_prompt_template("skills_icon")` |

* **删除了 2 条死登记的正文**（141 字 `AD_ANALYSIS_PROMPT`、159 字 `LISTING_GENERATOR_PROMPT`），由真身顶替；git 可回溯。
* `secretary/agent.py` 仍 re-export `SECRETARY_SYSTEM_PROMPT`（既有用例从 `modules.secretary.agent` 取这个名字）。
  为此新增 `test_secretary_prompt_is_served_from_registry`：运行时那份**必须等于**注册表那份——否则「常量」和「注册表」两份会静默漂移。

### 3.4 AST 形态门禁

`tests/test_prompt_spec.py::test_no_prompt_body_outside_prompts_module`：
扫描 `modules/**` 下 `prompts.py` **之外**的「赋值名字含 PROMPT/INSTRUCTIONS/TEMPLATE 且长度 ≥ 200 的字符串常量」。
配套 `test_stray_prompt_gate_is_not_vacuous`（人造违规必须被抓到、干净样本不得误报）——没有它，扫描器写错就是恒绿假门禁。

---

## 4. 验证

### 4.1 正文保真（最关键的一条）

迁移不能改变一个字符。用 **git HEAD 现算基线**逐字比对：

| 键 | 字数 | 指纹 | 与 HEAD 逐字相同 |
|----|------|------|-----------------|
| `ad_analysis` | 502 | `1dc7f4a9636b` | ✅ |
| `listing_generator` | 892 | `de7a7a353d0a` | ✅ |
| `product_research_system` | 640 | `cbec611f9622` | ✅ |
| `aigc_selection_translate` | 393 | `8aa356df0ece` | ✅ |
| `aigc_enhance_prompt` | 372 | `3401272b69f6` | ✅ |
| `secretary` | 3395 | `80d1249d4c6b` | ✅（HEAD 版比工作区少一段 `list_shops`，属既有未提交改动，非本轮引入） |
| `skills_icon` | 174 | `560edc62363b` | ✅（该文件未入库，按迁移前 AST 扫描的 174 字对齐） |

### 4.2 回归

| 测试 | 结果 |
|------|------|
| `tests/test_prompt_spec.py`（新增 21 条） | 21 passed |
| `tests/test_infra_layering.py` | 11 passed |
| `tests/test_secretary_shop_fact.py` / `test_secretary_agent.py` / stream / plan / intent / shop_list | 29 + 全绿 |
| `tests/test_clarification_tool.py` | 11 passed |
| `tests/test_skill_*`（8 个文件） | 147 passed |
| `tests/test_memory_distill.py` / `test_platform_rules.py` / `test_module_facades.py` | 78 passed |
| `tests/test_llm_output_validation.py`（上一轮） | 12 passed |

### 4.3 反向注入（6/6 真红）

| # | 退回的形态 | 结果 |
|---|-----------|------|
| R1 | 重名退回**静默覆盖** | **RED(good)** |
| R2 | 变量反解不过滤非标识符（JSON 示例当变量） | **RED(good)** |
| R3 | 缺变量退回「原样发 `{market}`」 | **RED(good)** |
| R4 | 把正文散落回 agent 文件 | **RED(good)** |
| R5 | `RenderedPrompt` 不再是 `str` | **RED(good)** |
| R6 | 指纹掺进 version | **RED(good)** |

---

## 5. 本轮顺带修的两处既有问题

1. **`tests/test_secretary_shop_fact.py::test_wiring_gates_are_not_vacuous` 的 3 个锚点早已失修**（本轮之前就红）：`router.py` 缩进重排后，锚点里的 8/12 空格不再命中，实际是 4/8 ⇒ 3 条判据**空跑**。已按实测缩进修正锚点（228/235 行）。
2. **`tests/test_clarification_tool.py` 读 `agent.py` 找提示词规则 6** —— 正文归位后改读 `prompts.py`（判的是提示词文本，必须跟到新家）。

## 6. 已知遗留 / 下一档（B 档）衔接

1. **`review_analyst` 仍是「半死登记」**：注册了，但 `agent.py` 直接用常量（`tests/test_review_analyst_agent.py:87` 把这种用法钉住了）。要改成走注册表需同步改那条测试——**待拍板**。
2. **`product_research` 与 `product_research_system` 是两份**（159 字带 `{market}` 的子任务提示词 + 640 字的 Agent 人设）。都活着、都在用，但命名相近易误取，建议在 B 档改名消歧。
3. **B 档（DB 覆写层）需要的接口已就位**：`get_prompt_spec(name).fingerprint` 就是「库里那版 vs 源码这版」的比对键。前提是消费方全部走 `get_prompt_template`——`review_analyst` 与 `memory` 那两条尚未满足（见 1）。
4. **未做 schema 级校验**（只保证能渲染、变量不缺）。
5. **既有失败（与本轮无关）**：`tests/test_listing_seo_contract.py` 2 条——`service.analyze_seo` 抛 `ValueError` 未被路由层转成 HTTP 响应，用 HEAD 版本复跑同样红，确认 pre-existing。

## 7. 本轮踩到的坑

| 坑 | 处理 |
|----|------|
| 探针把 `Formatter().parse` 的四元组解包错位（`format_spec` 当成 `field_name`）⇒ 报「没有模板含变量」，与事实相反 | 判据必须**先实测**再下结论；改完立刻拿已知含 `{language}` 的模板复核 |
| `secretary/agent.py` 那段提示词在 HEAD 就与工作区不同（既有未提交改动）⇒ 拿 HEAD 当基线会误判「迁移改坏了」 | 基线要选**同一个口径**；这里改用「迁移前工作区 AST 扫描长度 + diff 定位差异来源」 |
| `loguru` 不认 `%s` 占位（本仓一律 f-string）⇒ 注册日志打出原始 `%s` | 改 f-string |
| 门禁自检样本名写成 `NOT_A_PROMPT_NAME` —— 含 "PROMPT"，被大小写不敏感正则命中⇒ 自检自己红了 | 样本名改 `SOME_LONG_TEXT`（注释留着防再踩） |
| `git checkout HEAD -- <file>` 会同时改索引 ⇒ 临时把改动变成「已暂存」 | 用完 `git reset HEAD -- <file>` 复位，保持工作区状态与之前一致 |
