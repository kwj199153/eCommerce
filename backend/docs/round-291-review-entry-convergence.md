# 第 291 轮 · 差评入口收敛（走方案 A）

> 老板拍板：「走 A ，但是删除资料库的【差评处置】可以留到智能客服的功能栏的【差评处理】的右侧边栏，
> 如果宽度不够可以也设置对话模式/大屏模式，你来判断快捷卡片的【差评处理】【退款处理】是否可以删除」

---

## 一句话结论

四个入口收敛到三个：**写动作（批准/驳回/发放）从 2 个 UI 出口收成 1 个**，资料库那页删掉、
能力搬进右栏第三个视图；两张快捷卡片**都不能删**（理由在第四节，有原文出处）。

| 入口 | 第 290 轮 | 现在 |
|---|---|---|
| 资料库【差评处置】 | 存在，带 approve/issue 按钮 | **删除**（能力已搬走，不是丢弃） |
| 客服功能栏【差评处理】右栏 | 2 个视图 | 3 个视图：近期差评 / 未关联产品 / **处置台账** |
| 快捷卡片【差评处理】 | 存在 | **保留**（判断类能力，且需改名，见 4.3） |
| 快捷卡片【退款处理】 | 存在 | **保留**（它是两条技能共用的定性口径） |

---

## 一、写动作出口：从 2 收到 1（本轮核心）

第 290 轮盘出来的真缺陷不是「功能重复」，而是**同一个不可逆的人审动作有两个按钮**：

```
DispositionLibrary.vue:261-266   ← import approve/reject/issue
ReviewDeskConfig.vue:238-240     ← import 同一批
```

后果是 HITL 的**唯一把关点**失效 —— 任一侧漏了校验都没人知道，而券码/退款一旦发出就是既成事实。

判据不选「界面上看有没有重复按钮」（靠人眼，改一轮就失效），选的是：

> **`approveDisposition` / `rejectDisposition` / `issueDisposition` 被多少个 `.vue` import，必须 == 1**

现在 = **1**，且只在 `ReviewDeskConfig.vue`；没有任何 `.ts` 层再包一层。

### 搬过去的东西（一个不落）

`DispositionLibrary` 里独有能力，全部进了 `ReviewDeskConfig` 的第三个视图「处置台账」：

| 能力 | 说明 |
|---|---|
| 台账列表 + 状态筛选 | `listDispositions({status})` |
| **批量「生成待处置」** | `backfillDispositions()` —— `review_dispositions` **唯一的批量写入口**，全仓只此一处 |
| 通道中文名 | 与后端 `service.DISPOSITION_CHANNELS` 的 5 个取值逐字对齐（`reply/coupon/refund/reship/escalate`） |
| 补偿文案的 `refund_percent` 分支 | 退款按百分比给时要显示「退款 100%」，原实现会显示成 0 元 |
| 双语义空态 + 逃生口 | 「筛选后为空」≠「压根没有处置」，前者必须给「清空筛选」 |
| 明细抽屉的批准/驳回/发放 | 本来就已有，抽屉现在三个入口共用一份归一后的字段（`DetailView`） |

---

## 二、删除资料库入口：连带动了 6 处，其中 1 处我之前没料到

`check-review-library-view.cjs` 的 D3/D4/D5/D6/D7 全是**集合相等**（不是包含）⇒ 少改任何一侧立刻红：

| # | 位置 | 改动 |
|---|---|---|
| 1 | `Sidebar/KnowledgeBase.vue` | 删菜单项（留墓碑注释说明搬去了哪） |
| 2 | `Workspace.vue` | 删渲染分支 |
| 3 | `Workspace.vue` | `currentView` 联合类型 |
| 4 | `Workspace.vue` | 导航 cast |
| 5 | `appActions.ts` | `AppView` / `VIEW_LABELS` / `VALID_VIEWS` |
| 6 | `navigation_tools.py` | `VIEW_IDS` |

### ⚠️ 第 6 处里还有第二份清单 —— 这是本轮抓到的隐患

`navigation_tools.py` 里同一份视图清单其实有**两份实现**：

- `VIEW_IDS`（运行时清单）—— 门禁 D5 **只判它**
- `ViewId = Literal[...]`（第 64-67 行）—— **这才是 LLM 的工具签名**

我只删了前者，后者原地不动 ⇒ **LLM 的签名里依然写着「可以跳到差评处置」，而那个视图已经不存在：跳过去是空白，且零报错。**

根因是这两份之间**原本没有任何门禁在守**。已修：

- 同步删除；
- 门禁补 `D8 后端 VIEW_IDS == ViewId Literal（集合相等）` + `B0k` 自检（防止抽取落空后「空集==空集」恒真）；
- 反向注入自证（`backend/scripts/probe_d8_reverse_inject.py`）：只塞回一侧 ⇒ **exit=1，49 条里只有 D8 红**；还原后 49/49 绿。

---

## 三、双模式（对话模式 / 大屏模式）

处置台账是 8 列表格（SKU / 评分 / 标题 / 通道 / 补偿 / 状态 / 更新 / 操作），340 与 528 都放不下。

接的是**工具级**宽看板（新增 `isReviewDeskTool` + `hasWideBoard`），不是 Agent 级：

> 客服的主形态是聊天。像 AIGC 那样做成「点进 Agent 就挂个大屏开关」是干扰；
> 只有真的选中了「差评处理」才需要。这与利润测算（`isWideProfitTool`）是同一粒度。

样式复用既有的 `review-data-mode`（对话收窄 400 + 右栏撑开），没有复制第二套布局规则。
「对话模式」下右栏 528；「大屏模式」下右栏吃剩余宽度，台账横向滚动即可看全。

---

## 四、裁决：两张快捷卡片能不能删 → **都不能删**

### 4.1 【退款处理】不是退款按钮，是两条技能共用的定性标准

出处 `modules/skills/seed.py:456-504`，正文第 0 步定义**责任定性四类口径**：

| 类别 | 判据 | 主导方 |
|---|---|---|
| 我方责任 | 发错货 / 少发 / 明显质量缺陷 | 直接给方案，不扯皮 |
| 买家误解 | 与 listing 描述一致，买家预期错位 | 说明 + 有限补偿 |
| 物流责任 | 破损 / 丢失 / 超时 | 走物流索赔，同时先安抚 |
| 责任不明 | 证据不足 | **转人工**，不要自行判断 |

而【差评处理】技能正文第 1 步明写（原文）：

> 分工：**责任归属怎么定性不在本技能定义** —— 沿用「退款处理」（`cs-refund-playbook`）的四类口径。
> ★ 为什么不分头定义：两条技能各判一次，结论不一致时没人知道以哪个为准

删掉它 ⇒ 差评处理第 1 步没有口径可依，LLM 只有两条路，都是坑：
自己编一类（踩「同一判定两份实现」），或跳过定性直接给方案（踩它自己的红线「证据不足时不要先认责」）。

另外：`toolDefinitions.ts` 里客服只有 `order-track` 与 `review-desk` 两个表单工具，
**不存在退款侧的表单工具** ⇒ 这张卡同时是买家提退款时的唯一定性入口。

### 4.2 【差评处理】属于「不确定」，正该住在卡片里

它的工具链：`get_customer_review_context` / `fetch_order_tracking` / `get_sku_health_score` / `plan_compensation` / `list_customer_reviews`，
做的是四件**需要判断**的事：取证 → 定性 → 建议方案 → 判个案还是重复问题（决定是否升级到根因）→ 回复草稿。

它与本轮收敛的写动作**不冲突**：正文第 2 步写着「`plan_compensation` 返回的是建议不是发放动作；真发放不可逆，必须过人工审批」。

分工上正好对上老板自己那条：**确定性 → 功能栏；不确定 → 快捷卡片 skill**。
右栏覆盖了确定性那一半（列表/台账/生成草稿/批准/发放），这张卡独占的是要判断的那一半。

### 4.3 但有一处真问题：同名撞车（建议改技能卡名，等你点头）

同一屏同时出现两个【差评处理】：

- 功能栏 form 工具 `review-desk`（标题是「差评处理」）
- 快捷卡片 `cs-negative-review-triage` 的 `title` 也是「差评处理」

**第 290 轮「为什么这么多入口」的重复感，主要来自同名**，不完全来自功能重叠。

建议改**技能卡**的 title → 「差评归因与回复」，保留功能栏按钮名「差评处理」（那是你定的名字）。

⚠️ 落法有个坑，先说清楚：`title` 属于**内容列**，`resync_demo_skills()` **不同步**它
（`seed.py:1689-1692` 明写「不动 content / title / description」—— 那是能被演示身份编辑的列，
覆盖等于抹掉编辑且绕过版本快照）。所以**只改 `seed.py` 对已落库的行无效**，
必须走 `service.update_skill`（会落 revision），两边一起改才不漂移。

---

## 五、新门禁与自证

### `frontend/scripts/check-disposition-write-exit.cjs`（13 条，新增）

核心判据：三个写动作的 `.vue` import 数 == 1 且只在 `ReviewDeskConfig.vue`；`.ts` 层 0 处；旧页面已删；
Workspace 无残留分支；`appActions` 无残留 key。带 B0/B1 自检（证明解析没落空 ⇒ 不是「0==0」恒真）。

**双向注入自证**（`backend/scripts/probe_write_exit_reverse_inject.py`）：

| 注入 | 期望 | 实测 |
|---|---|---|
| A：新建 `.vue` 真的 import | 变红 | **exit=1，FAIL C1 approveDisposition** ✓ |
| B：新建 `.vue` **只在注释里**提这三个函数 | 仍绿 | **13/13 绿** ✓ |
| C：清理后 | 恢复 | 13/13 绿，临时文件已删 ✓ |

方向 B 是必须的：只做 A 会得出「门禁有效」的结论，却放过一个「写句注释就能骗过」的判据
——那正是本仓在 `check-review-library-view.cjs::F5` 上踩过的形态（注释喂饱判据 ⇒ 真代码删了照样绿）。

---

## 六、回归

| 项目 | 结果 |
|---|---|
| `vue-tsc --noEmit` | exit=0 / 0 行输出（台账合并后、删除后、双模式后各跑一次） |
| pytest（7 个受影响文件） | **173 tests / 0 failures / 0 errors / 0 skipped** |
| `check-review-library-view.cjs` | 49/49（含新增 B0k + D8） |
| `check-disposition-write-exit.cjs` | 13/13（新增，双向注入已证） |
| `check-tool-reality.cjs` | 39/39 |

## 七、改动清单

**改**
- `frontend/src/components/TaskConfigPanel/configs/ReviewDeskConfig.vue` —— 加第三个视图「处置台账」
- `frontend/src/views/Workspace.vue` —— 删 `dispositions` 视图 + 工具级双模式
- `frontend/src/utils/appActions.ts` —— 删三项 `dispositions`
- `frontend/src/components/Sidebar/KnowledgeBase.vue` —— 删侧边栏第 8 项（留墓碑）
- `frontend/src/components/TaskConfigPanel/index.vue` —— 注释改指新落点
- `backend/modules/secretary/navigation_tools.py` —— `VIEW_IDS` + `ViewId Literal`
- `frontend/scripts/check-review-library-view.cjs` —— 加 B0k / D8

**删**
- `frontend/src/components/KnowledgeBase/DispositionLibrary.vue`

**加**
- `frontend/scripts/check-disposition-write-exit.cjs`
- `backend/scripts/patch_review_desk_ledger.py`（台账合并）
- `backend/scripts/patch_remove_disposition_library.py`（删除 + 6 处消费方）
- `backend/scripts/patch_nav_viewid_literal.py`（修第二份清单 + 门禁加固）
- `backend/scripts/probe_d8_reverse_inject.py` / `probe_write_exit_reverse_inject.py`（双向注入自证）

## 八、留一件事给你拍

1. **技能卡改名**（4.3）：改「差评处理」→「差评归因与回复」？改的话我按 `service.update_skill` 落 revision 并同步 seed。
2. **记忆该结算了**：`MEMORY.md` 已用 98%（余量 249 B），`_pending` 积压 11 份 / 63.9 KB（阈值 8 份 / 40 KB）。
   本轮的新判据我先落在 `_pending/第291轮.md`（未动你已有的判据）。要清理冷数据的话建议单开一轮做。
