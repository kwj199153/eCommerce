# 第 195 轮 · 技能仓库改造 + 店秘书规则核查 + Skill 库整理

> 覆盖老板本轮三条需求。每条都给**可复算的读数**与**反向注入证据**，
> 并如实标出「没做完 / 结论被推翻」的部分。

---

## 摘要

| # | 需求 | 结论 | 关键读数 |
|---|---|---|---|
| 1 | 筛选过滤按钮两行改一行，参考资料库页面，删标签相关内容 | ✅ 完成 | 门禁 18/18；反向注入 11/11 |
| 2 | skill 库整理 | ✅ 完成 | 最大 SKILL.md **178,410 → 12,179 B**；无损验收 0 条问题 |
| 3 | 店秘书转交规则为何被写出来给用户改 + 全库同类筛查 | ✅ 完成 | 唯一命中 1 条（已退役）+ 2 条防复发门禁 |

全链验证：前端 13 道门禁 + `vue-tsc` **14/14 rc=0**；`vite build` rc=0；
后端 pytest 1566 例 / 2 红（**既有缺陷，与本轮无关**，见 §4）；迁移真库往返 5/5 + 空库全链 rc=0。

---

## 1. 技能仓库：筛选区压成一行 + 退役「自定义标签」

### 1.1 做了什么

| 面 | 文件 | 改动 |
|---|---|---|
| 前端 | `components/SkillStore/SkillManager.vue` | 筛选区由 `.sm-filters`(column) > `.sm-filter-row`×2 **压成单层 flex 行**（照 `CandidateLibrary.vue` 的 `.toolbar` 范式）；删「按标签筛选」下拉 + 两处 `sm-chip-tag`；「已筛选 N 项」不再另起 badge 行，改挂「重置筛选」按钮 |
| 前端 | `stores/skills.ts` | 删 `Skill.tags`、`filterTags`、`tagOptions` 及其在 `filteredItems` / 搜索 / `activeFilterCount` / `resetFilters` 里的全部分支与导出 |
| 后端 | `modules/skills/{db_model,service,seed}.py` | 删 `tags` 列 / 校验常量 / 序列化；删 seed #10；新增 `DEMO_SKILL_COUNT=22` 与 `RETIRED_DEMO_SKILLS` + `ensure_demo_skills()` 的 ⓪ 清理步 |
| 迁移 | `alembic/versions/c5f9a3e7b2d8_skills_drop_tags.py` | **新建**（新 head，`_has_column` 守卫，可反向加回列） |

### 1.2 为什么「自定义标签」要整体退役，而不是只删 UI

它**只有筛选口、没有任何录入入口** ⇒ 库里 `tags` 恒空 ⇒ 筛选器**永远筛出 0 条**。
这是半成品，留着要付双份代价：用户以为能筛、下一个人以为它是活的。

⇒ 退役必须**连一起清**：DB 列 + API 出参 + service 常量 + store 状态 + UI 控件 + CSS 类名 + 测试 + 门禁 fixture。
`路` 少清一处，就会留下一个「看起来还在、其实没数据」的洞。

### 1.3 版式需求也做成了可执行判据

「两行改一行」是**版式**要求，而版式退化**三种形态都不报错**：
改回 `flex-direction: column`、把控件重新包一层行容器、计数另起 badge 行。

⇒ 在 `check-skill-view-parity.cjs` 新增 **C 段 5 条形态判据**（单层容器 / 横向单行 /
控件齐备 / `flex-wrap` 兜底 / 旧类名不许复活）+ **B6 反向自检**。

### 1.4 反向注入（11 例，全部符合预期）

每条注入断言的是 **FAIL 集合逐项相等**，不只是 `rc != 0`
（`rc != 0` 也可能是脚本崩了，什么也证明不了）。

| 注入 | 期望红 | 实测 |
|---|---|---|
| 基线（副本不改）× 2 门禁 | 全绿 | ✅ 39/39、18/18 |
| 对照：只改注释 × 2 | 全绿 | ✅ |
| 把 `tags` 搜索加回 store | F7 | ✅ **只有 F7** |
| 把 `filterTags/tagOptions` 导出回来 | F29 | ✅ **只有 F29** |
| 重新包一层行容器 | C1 | ✅ **只有 C1** |
| 筛选区改 `column` | C3 | ✅ **只有 C3** |
| 去掉 `flex-wrap` 兜底 | C4 | ✅ **只有 C4** |
| 计数另起 badge 行 | C5 | ✅ **只有 C5** |
| 标签 chip 类名复活 | C5 | ✅ **只有 C5** |

### 1.5 ★ 两处「门禁自己有问题」（都不是代码问题）

1. **F7 原本是空跑**：断言「搜 `合规` 得 0 条」，但 fixture 里已无 `tags`
   ⇒ 即便有人把 tags 搜索加回来，**也没有行能被命中** ⇒ 永远绿。
   **修法：钉子自带诱饵行**（`{...sk(...), tags:['合规','选品']}`）。
2. **F15 其实崩了**：概念退役时漏扫了**门禁脚本自身**（仍引用 `s.filterTags.value`）
   ⇒ store 导出删掉后 TypeError，输出停在 F14 —— **看不出是崩，只看到少了几条**。

---

## 2. 店秘书转交规则：为什么不该让用户改 + 全库同类筛查

### 2.1 结论

`secretary-handoff-rules`（店秘书转交与澄清规则）是**平台编排层内部规则**：

- 真源在 `modules/secretary/agent.py` 的 `SECRETARY_SYSTEM_PROMPT`（规则 1 / 6 / 8）
- 「问」的工具化实现在 `ai_infra/tools/clarification.py`（`ask_clarification`）

把它作为「技能」放进技能仓库 ⇒ **既无意义**（改了不生效，prompt 才是真源）
**又误导**（终端用户以为自己能改平台路由）。⇒ 已退役（删 seed #10）。

### 2.2 全库同类筛查：用**形态判据**，不用名字

| 判据 | 内容 |
|---|---|
| A | `agents` 是否命中**编排层** Agent 名（`secretary`） |
| B | 正文是否含 **≥4 个系统级特征词**（转交 / 交接 / 澄清 / 槽位 / 路由 / 分发 / 三选一 / 直接办 / 调用什么 / handoff） |

**结果：23 条里唯一命中 #10**，其余 22 条全是业务方法学。**没有第二例。**

### 2.3 ★ 「登记退役清单 + 主动清理」缺一不可

`ensure_demo_skills()` 是「缺了才建」的幂等写入，**从不删任何行**。
⇒ 光从规格表删掉只影响**新库**；**已有库里那条永久留着**，且照样能被 Agent 加载
（`read_skill_for_agent` 按 name 取，不看规格表）。

所以落地成两步：

1. `RETIRED_DEMO_SKILLS: Dict[str, str]`（name → 退役原因）—— 让「为什么退役」可追溯
2. `ensure_demo_skills()` 内加 **⓪ 清理步**，幂等（先腾掉不该在的，再补该在的）

### 2.4 两条防复发门禁

- `test_demo_skills_do_not_target_orchestrator_agent` —— 演示技能不得归属编排层 Agent
- `test_retired_demo_skills_are_not_resurrected` —— 退役 name 不得重回规格表

★ 原门禁 `test_demo_specs_are_self_consistent` 有**盲区**：它只校验「agent 名字**存在**」，
而 `secretary` 是**合法存在**的 Agent ⇒ 查不出编排层误挂。新门禁补的正是这个盲区。

---

## 3. Skill 库整理

### 3.1 体量（★ 只算 SKILL.md —— `references/` 不进上下文）

| 指标 | 整理前 | 整理后 |
|---|---|---|
| skill 数 | 47 | 48 |
| **SKILL.md 总字节** | 1,525,381（含 38 KB 游离备份） | **832,181** |
| 最大 SKILL.md | `project-health-audit` **178,410** | **12,179** |
| 次大 | `reverse-injection-verification` 105,962 | 25,008 |

| skill | 整理前 | 整理后 | 外迁内容 |
|---|---|---|---|
| `project-health-audit` | 178,410 | 12,179 | 17 个维度拆 19 份 + 历史基线 3 份 |
| `reverse-injection-verification` | 105,962 | 25,008 | 22 条轮次补正 |
| `agent-memory-tiering` | 54,699 | 31,752 | 2 条 + 挪走 38 KB 游离备份 |
| `demo-identity-narrow-aperture` | 40,797 | 23,020 | 3 条轮次补正 |
| `credential-vault-server-side` | 40,440 | 19,947 | 4 条轮次补正 |
| `frontend-backend-contract-reconciliation` | 33,218 | 10,562 | 3 组变体场景 |
| `theme-preset-table` | 39,640 | 22,651 | 三项加固 |
| `hardcoded-color-tokenization` | 38,905 | 20,886 | 变体 C |
| `crosscut-convergence-form-gate` | 30,858 | 16,969 | 2 个「附」 |

### 3.2 ★ 修掉一个真缺陷：UTF-8 BOM 让技能「没有描述」

`project-health-audit/SKILL.md` 以 `\ufeff---` 开头 ⇒ **frontmatter 解析失败**
⇒ 技能目录里那条显示成「project-health-audit (user)」而**没有描述**。

它同时是**唯一**带 BOM 的 skill，也是**最大**的 —— 不是巧合：大文件更可能是
被某个脚本整份重写时带进了 BOM。已剥掉，全库复查 **BOM = 0**。

### 3.3 外迁规则（可机械判定）+ 保住可发现性

只外迁三类**不是主流程**的段：

1. **冻结快照**：`## 第 N 轮基线`、`## …修复记录` —— 某一轮的数字，加载时只会带来过期信息
2. **分支场景 / 附录**：`## 变体 A/B/C`、`## 附：…`、`## 三项加固`
3. **按轮次追加的补正**：`## …第 NNN 轮…`（天然是 append-only 增补）

**不外迁**：何时用、铁律、主流程、**坑清单**（那是这些 skill 最贵的部分）。

★ 每处外迁都在 SKILL.md 原位留一份 **标题索引**（不是一句「见 references」）——
否则以后不知道有哪些补正存在，等于把它们埋了。

### 3.4 无损验收（0 条问题）

对账基线 = 整理前的**整树副本** `~/.workbuddy/archive/skills-backup-r195`（109 文件 / 1.5 MB）。

> 断言：基线 SKILL.md 的**每条非空行**，都出现在 (现 SKILL.md ∪ 现 references ∪ 现其它子文件) 里。

唯一容差：基线里带头 BOM 的那行 `---`（有意剥掉的）。**结果：0 条问题。**
（只跟「自己刚写的产物」比是自证，不算数。）

### 3.5 ★ 一条被推翻的自述：skill 之间**没有**章节层重叠

我此前在给老板的汇报里说过「多对职责重叠」。**这个自述不成立。**

机械判据（两个 skill 的 `## ` **标题集合** Jaccard ≥ 0.25）实测：**0 对**。
名字最像的那对（`frontend-backend-contract-reconciliation` × `-single-source-calc`）
章节层是**分开**的 —— 它们管的是两件事。

真正有害的是**触发面**撞车（同一句话命中两个 skill），实测：

| 类型 | 结果 |
|---|---|
| 逐字撞车的触发语 | **1 对**：`project-health-audit` × `refuted-concept-removal` 都列了「只写不读」 |
| 触发面重合度最高 | 1 对（0.398）：`agent-tool-routing-and-slot-filling` × `crosscut-convergence-form-gate` —— 但后者 description 里**已写明「分工边界」** ⇒ **非缺陷** |

⇒ 结论：**没有需要合并的 skill**。合并会丢判据，本轮不做，也不建议做。

### 3.6 其他清理

- 游离备份 `agent-memory-tiering/SKILL.md.bak-r135`（38,389 B）**挪**（不是删）
  到 `~/.workbuddy/archive/skills-stray/` —— 它是 r135 的旧正文，删掉丢历史。
- ★ `skills/` 根目录的 3 个 `.xxx_migration.json` 是**加载器的迁移状态**，不是垃圾，未动。
- 新建 skill **`skill-library-curation`**，含两个可跑脚本：
  - `scripts/check_skill_budget.py` —— 五查（体量 / BOM / frontmatter / 悬空引用 / 游离文件）+ 可选重叠报告
  - `scripts/relocate_sections.py` —— **围栏感知**的无损段外迁（默认干跑，`--apply` 才写）

---

## 4. ★ 如实报告：一条与本轮无关的既有红

全量 pytest：**1566 例 / 2 红 / 0 error / 3 skipped**。

两条都在 `tests/test_agent_session_state.py` 的「端到端（真 PG）」组：

- `test_real_pg_roundtrip_upsert_delete_and_ownership`
- `test_table_shape_matches_the_contract`

**决定性证据（排除与本轮的相关性）**：

| 跑法 | 结果 |
|---|---|
| 单跑这两条 | ✅ **全绿** |
| 全量（含本轮改的测试文件） | 1566 例 / 2 红 |
| 全量（`--ignore` 本轮改的 2 个测试文件） | 1521 例 / **同样这 2 条红** |

⇒ **与本轮改动无关**，是既有的「全量红 / 单跑绿」顺序依赖缺陷
（`pytest-fixture-hygiene` 家族）。已登记为独立任务。

根因（完整堆栈）：`core.database` 的 async engine 连接池里的连接被**上一个事件循环**
创建，本用例所在的 session-scoped loop 复用时 `asyncpg do_ping → await_only` 报
`got Future attached to a different loop`。

---

## 5. 迁移实测（真库往返 + 空库全链）

**真库**（当前停在 `b4e8f2c6a1d7`，即新迁移的前一版）：判据一律查 `information_schema`，

| 步骤 | `skills.tags` | 列数 |
|---|---|---|
| 0 前置 | 在（`json`, nullable） | 17 |
| 1 `upgrade head` | **不在** ✓ | 16 |
| 2 `downgrade -1` | **回来**（`json`, nullable）✓ | 17 |
| 3 `upgrade head` | **再次不在** ✓ | 16 |
| 4 重复 `upgrade head`（幂等） | 仍不在，rc=0 ✓ | 16 |

**临时空库**（`r195_migtest_<hex>`，跑完已 drop）：
17 个迁移全部应用 · `alembic_version = c5f9a3e7b2d8` · 建出 **46 张表** ·
`skills` **不含** `tags` ⇒ 基线已同步。

---

## 6. 遗留

| # | 事项 | 说明 |
|---|---|---|
| 1 | 仍超 30 KB 的 4 个 skill | `dialog-tts-playback` 51 KB / `screenshot-driven-ui-change` 43.9 KB / `alembic-chain-integrity` 34.5 KB / `agent-memory-tiering` 31.8 KB。它们的超长段是**主流程 / 坑清单**（不该外迁），要瘦身得先想清怎么切 |
| 2 | 触发语 `只写不读` 撞车 | 是否让其中一方在 description 里让位 ⇒ 待拍板 |
| 3 | `docker-container-forensics` 无 `agent_created` | 只影响「能否自我修改」，非缺陷 |
| 4 | 既有顺序依赖红 | 见 §4，已登记独立任务 |

---

## 7. 本轮踩到的坑（已写进 skill）

1. **切标题必须识别代码围栏**：```text 报表模板里的 `## 一句话结论` 被当成真标题
   ⇒ 切片夹带 5 个假标题。靠「区间内同级标题必须恰好等于目标」这条护栏抓出来的。
2. **门禁的悬空引用检查不许全文搜路径**：文档里的示例路径（`references/xxx.md`、`references/*.md`）
   会全被报成悬空 ⇒ 门禁对示例假红。正解：只校验**工具生成的那句指针**，且跳过围栏。
3. **「门禁一建就常红 = 没有门禁」**：体量类判据一开始就把现存超限项判红 ⇒ 没人看。
   改成「结构缺陷硬红、体量先警告、`--strict` 才收紧」。
4. **概念退役要连所有消费方一起列**：包括门禁 / 测试 / 脚本，不只是 `src`。
5. **`npm` 被沙箱判到 `wsl.exe` 黑名单**（不可批准 / 绕过）⇒ 前端构建改直调
   `node node_modules/vue-tsc/bin/vue-tsc.js` 与 `node node_modules/vite/bin/vite.js`。
6. **宿主注入的 `<current_time>` 是陈旧的**（报 09-18，实测 09-21）⇒ 落日志前先取真实日期。

---

## 8. 第 196 轮补正：筛选为空时「直接空」

老板原文：

> 当筛选为空时候，直接空就好了，你好像做了另外一个页面跳转（删除这个跳转，
> 直接空，然后已经提供了重置筛选的功能了）。

### 8.1 根因不是插画，是**层级**

旧结构把**整条筛选栏（含顶部「重置筛选」）**关在 `v-else` 分支里：

```html
<a-empty v-if="!store.items.length" />                              <!-- 库里真没技能 -->
<a-empty v-else-if="!store.filteredItems.length">清空筛选</a-empty>  <!-- 筛选为空 -->
<template v-else>                                                   <!-- 筛选栏 + 列表都在这里 -->
```

⇒ 一筛空，筛选栏整条消失、页面只剩一个居中空状态块 —— 那才是「像跳转到另一个页面」
的来源；而空状态里那个「清空筛选」按钮就成了**唯一**的逃生口 ⇒ 同一个 `resetFilters`
被迫有两套入口。

### 8.2 修法（两条必须一起做，缺一条都不成立）

| 面 | 改动 |
|---|---|
| 模板 · 删 | 「筛选后为空」的 `a-empty` 整块（插画 + 文案 + 清空筛选按钮）—— 筛选栏因此天然活在判空之外 |
| 模板 · 加守卫 | 列表容器 `.sm-groups` 改 `v-if="store.filteredItems.length"` ⇒ 筛空时列表区**什么都不渲染** |
| 保留 | `!store.items.length`（库里真没技能）的空状态**不动** —— 那是另一种语义 |
| 门禁 | `check-skill-view-parity.cjs` 新增 **D 段 6 条**（D1~D5 + 1 条反向自检） |

### 8.3 验证读数

| 项 | 读数 |
|---|---|
| 版式门禁 | **24/24**（原 18/18 + D 段 6 条） |
| 反向注入 | **7/7 逐项相等**（基线绿 / 只改注释仍绿 / 5 条注入「只红该红的那条」） |
| 全链 | 13 道 node 门禁 + 2 道 py 门禁 + `vue-tsc` + `vite build` = **17/17 rc=0** |
| 真浏览器 DOM（1280 宽，筛空后） | `.sm-filters` 仍在且可见 · `重置筛选(1)` 可点 · 工具栏「显示 0 / 22 个技能」· `.sm-groups` **不存在** · `.ant-empty` 计数 **0** · 旧文案与旧按钮**都不存在** |
| 真浏览器 DOM（1920 宽） | 筛选栏高度 54px = **单行**（8 个控件合计 1065px，容器 1606px） |

> 1280 宽下筛选栏会换行成两行（8 个控件约需 1100px，内容区可用约 956px）——
> 这是 `flex-wrap` **按设计**的兜底（C4 明确要求窄屏宁可换行也不横向溢出），
> 不是「两行改一行」没落地：1920 宽下确实是单行。

### 8.4 顺带修掉的工具链假红

`vite build` 从 Python 驱动时稳定报
`[vite:html-inline-proxy] ... No matching HTML proxy module found`，
从 bash 驱动则 rc=0。**变量是 cwd 的盘符大小写**：

| cwd | 结果 |
|---|---|
| `d:\ai\eCommerce\frontend` | rc=1（假红） |
| `D:/ai/eCommerce/frontend` | rc=0 |

vite 的 HTML proxy 表按 id 字符串索引，`process.cwd()` 保留传入的大小写，
而另一侧走 `fs.realpathSync` 会归一成大写盘符 ⇒ 查不到条目。
判据：**非 shell 驱动 node 工具链，cwd 一律写大写盘符**。
