# 第 260 轮（二）· 左侧边栏：三个分组标题的间距统一 + 不出现滚轮

## 0. 需求原话

> **3 个红框的高度要统一，左侧边栏不出现滚轮**
> （附截图：三个红框分别框在「Agent 群 / 资料库 / 能力」三处分组标题上）

## 1. 先量，再改：真因与目测**不一样**

用 CDP 连真实 Chrome 量出来（不是目测，也不是读 CSS 推）：

| 量 | 改动前 | 改动后 |
|---|---|---|
| 三个标题的**盒子高度** | **34.94 / 34.94 / 34.94** —— 本来就相等 | 32 / 32 / 32 |
| 三个标题的**上间距** | **8 / 18 / 2** ← 真凶 | **8 / 8 / 8** |
| 三个标题的**下间距** | 2 / 2 / 2 | 1 / 1 / 1 |
| 侧边栏**自然内容高** | **957**（视口 856 ⇒ 溢出 101） | **805**（余量 51） |
| 滚动条 | 可见（`scrollbar-width: auto`） | 不可见（`none`） |
| 账户入口位置 | top = **895**（在视口**外**，截图里看不到） | 795..856（完整可见） |

老板看到的「三个红框不一样高」，本质是**上下留白不一样**（8 / 18 / 2），
而标题自己的盒子高度从头到尾都是一样的。

**为什么会差 10 倍**：两处容器各加了纵向 padding，与标题自己的 `padding-top` 叠加：

```
AgentList.vue      .agent-list    { padding: var(--space-8) 0 }   → 上间距 8
KnowledgeBase.vue  .knowledge-base{ padding: var(--space-8) 0 }   → 8 + 8 + 2 = 18
（第二个标题「能力」在容器**内部**，吃不到容器 padding）            → 只有 2
```

顺带查出同一根因的第二个症状：`.account-entry` 被挤出视口外 39px
（`top=895` vs 视口 856）—— 所以老板截图底部看不到账户入口。

## 2. 改动清单（5 个文件）

| # | 文件 | 动作 |
|---|---|---|
| 1 | `src/styles/sidebar-nav.css`（**新**） | 分组标题 / 分节菜单规格的**唯一真源**：三个分组共用同一个 `margin-top`（这是「看起来一样高」的关键）；菜单项 40→34px、纵向 margin 2→1px；最后一项清零底边距 |
| 2 | `src/main.ts` | 装载上面那份样式 |
| 3 | `Sidebar/AgentList.vue` | 旧的 `.section-title` 与两条 `:deep(.ant-menu-item)` **删除**（收口到真源）；容器 `padding: 0` |
| 4 | `Sidebar/KnowledgeBase.vue` | 同上（两份标题 + 两个菜单）；**保留** `.knowledge-base` 类名（另一个 CDP 探针依赖它定位侧边栏） |
| 5 | `views/Workspace.vue` | 删掉侧边栏里那条 `<a-divider>`（账户入口自带 `border-top`，白占 17px）；`.sidebar` 加 `scrollbar-width: none` + `::-webkit-scrollbar{width:0}` |
| 6 | `Sidebar/AccountMenu.vue` | `.account-entry` 加 `position: sticky; bottom: 0` + 背景色 —— 窗口再矮也不丢 |

省下 152px（957 → 805）＝ 菜单项 34px×16 + 间距 + 那条分隔线。

## 3. 判据：分两层，因为一件事只有一层判不出来

| 层 | 文件 | 管什么 | 条数 |
|---|---|---|---|
| **结构**（静态） | `frontend/scripts/check-sidebar-layout.cjs`（新，已进 `npm run build`） | 规格唯一真源、类名被引用、容器零纵向 padding、旧写法不得回退、`scrollbar-width: none`、侧边栏块内无 `<a-divider>`、账户入口粘底 | **30** |
| **几何**（真实浏览器） | `frontend/scripts/cdp-sidebar-layout-probe.mjs`（新，`npm run check:sidebar-geometry`） | 三个标题盒子等高、上/下间距各自相等、自然内容高 ≤ 视口、滚轮不可见、账户入口在视口内且**滚到底贴住底边** | **9** |

为什么必须两层：`padding` 叠加后的实际像素**只有浏览器算得出来**，
读源码证明不了「到底多高」；反过来，浏览器探针在 CI 里跑不了（要 Chrome + dev server），
所以「不得再写回第二份样式」这类结构纪律由静态门禁守。

### 3.1 反向注入验证

| 探针 | 结果 |
|---|---|
| `.workbuddy/probes/r260_review_library/inject_reverse_sidebar.cjs` | 注入 **16** / 符合预期 **16** / 异常 **0**（含 1 条反向对照：改与判据无关的圆角 ⇒ 门禁**保持全绿**） |
| `.workbuddy/probes/r260_review_library/inject_reverse_geometry.py` | 注入 **5** / 符合预期 **5** / 异常 **0**（含 1 条反向对照） |

几何注入额外要求**「注入确实生效」**：判据取自探针**自己打印出来的实测值**
（如「上间距 20」「scrollbar-width=auto」），而不是「我写了文件」这种代理判据 ——
否则 HMR 没跟上会把「注入没生效」误报成「门禁没抓到」，结论正好相反。

## 4. 一条被实测**否掉**的断言（本轮最该记下来的部分）

我一开始按推断做了两件事，**都被实测打掉**：

1. **推断**：`.ant-layout-sider-children` 写死 `height: 100%` 会让 `position: sticky`
   的包含块只有视口高，粘底失效 ⇒ 改成只留 `min-height: 100%`，并加了断言 S9d
   「不得写死 height: 100%」。
   **实测**：856 / 768 两档下，改与不改 `computed height` **都是 768px**，
   账户入口位置**逐像素相同**（`.ant-layout-sider` 自己是 flex 容器，这个盒子被拉伸定高）。
   ⇒ 改动**零收益**、断言**永远测不出差别**。**已回退改动、删除 S9d**，并在源码里留证。
2. **推断**：几何探针的 L8 只要判「滚到底时账户入口可见」就能证明粘底生效。
   **实测**：内容末尾在滚到底时**本来**就在视口底 —— 该位点上断言**恒真**，
   连「删掉 sticky」都抓不到。改成判「**贴住**视口底边（|bottom − 视口高| ≤ 1）」才有牙；
   真正能 falsify 的注入也从「加回 height:100%」换成「删掉 `position: sticky`」。

⇒ 两条教训：**「探针恒真」比「探针缺失」更危险**（它给缺陷盖章）；
凡断言，先问「什么样的改动能把它打红」，答不上来就先别写。

## 5. 验证结果（全量）

| 项 | 结果 |
|---|---|
| `check-sidebar-layout.cjs` | **30/30 PASS** |
| `cdp-sidebar-layout-probe.mjs` @1600×856 | **9/9 PASS** |
| `cdp-sidebar-layout-probe.mjs` @1600×768（小窗档） | **8/8 PASS**（L4 按设计允许溢出，仅作 INFO） |
| 静态反向注入 | 16/16 |
| 几何反向注入 | 5/5 |
| 完整 `npm run build`（**23** 条门禁 + `vue-tsc` + `vite build`） | 门禁全绿、`vue-tsc` 通过；`vite build` 在本沙箱里被**删除守卫**拦在 `emptyDir`（要删旧 `dist/assets` 62 个文件 > 阈值 50），改用 `--emptyOutDir false` 后 **EXIT=0** |

对照图：`.workbuddy/probes/r260_review_library/out_sidebar_compare.png`

## 6. 已知的诚实边界

- **只测了 1600 宽**。侧边栏是定宽 260px，宽度不影响这三个分组标题的纵向几何；
  但没测过 2 倍缩放 / 操作系统字体放大 —— 那种情况下内容可能重新超出视口。
- **菜单项从 40px 压到 34px 是肉眼可见的密度变化**（老板只要求「标题统一 + 不出滚轮」，
  压缩是为了把 957px 压到 805px 达到后者）。若觉得太挤，可回到 36px
  —— 代价是 856px 视口下的余量从 51px 降到约 19px，**需要重新量**再说。
- **宽口径无法完全覆盖 768px 及以下**：那个高度装不下 16 个菜单项，
  该档靠「不显示滚轮 + 账户入口粘底」兜住，而不是靠「装得下」。
- 全局 6px 滚动条样式（`App.vue`）**没动**，只针对 `.sidebar` 隐藏；
  主内容区、`.toolbar-tools` 等同族实现保持原样（其中 `.toolbar-tools` 与本轮新增的
  `scrollbar-width: none` 逐字相同 —— 所以本轮的注入探针锚点必须带上下文才唯一）。
