# favicon 显示成旧图标（蓝底「学」字）—— 第 383 轮补

> 现象：网页 tab 标题已经是「店管管」，图标却是蓝底白「学」字。

## 一、根因：SVG 是非法 XML，浏览器静默沿用旧图标

`frontend/public/favicon.svg` 第 4 行的注释里写了 CSS 变量名 `--brand-ink`。
**XML 规范禁止注释体内出现连续两个短横** ⇒ 整份文件不是合法 XML：

```
ET.parse('frontend/public/favicon.svg')
  → ParseError: not well-formed (invalid token): line 4, column 22
```

浏览器对 favicon 的失败是**完全静默**的：不报错、不警告、`vite build` 也不红，
直接**沿用同一个 origin 上缓存的旧图标** —— 于是 tab 上一直显示前一个项目
（eEducation，同样跑 5173）那个蓝底「学」字。

全仓扫描（`.workbuddy/probes/scan-svg-xml.py`）：**47 个 svg，2 个非法**——
产品站与官网的 favicon 是同一模板，都中招。

> eEducation 的 `favicon.svg` 注释里记着同一个坑（第 457~499 轮也是这个「学」字），
> 说明这类缺陷跨项目复发，不是一次性手误。

## 二、改了什么

| 文件 | 改动 |
|---|---|
| `frontend/public/favicon.svg` | 注释里的变量名改成「brand-ink 变量（前面是两个连字符）」，并加一段「不得出现连续短横」的警示 |
| `site/assets/favicon.svg` | 同上（该文件有一处，顺带补警示） |
| `frontend/index.html` | `href="/favicon.svg?v=383"` |
| `site/index.html` / `terms.html` / `privacy.html` | `href="./assets/favicon.svg?v=383"` |
| `frontend/scripts/check-brand-mark.cjs` | B8e 允许 `?v=` 后缀；**新增 B12** |

**为什么非要加 `?v=`**：favicon 有独立缓存，且**加载失败时浏览器沿用旧图标**。
只修文件不加版本号，强刷也未必重新请求 —— 用户会认为"你根本没改"。

## 三、门禁（让这类静默失败变成可控的红）

新增 **B12**：扫描 `frontend/public` 与 `site/assets` 下的全部 svg，
**注释体内不得出现 `--`**（直接钉根因，不依赖 XML 解析器，零依赖）。

反向注入验证：

| 步骤 | 结果 |
|---|---|
| 往 favicon 注释里塞 `X--Y` | `FAIL B12`，汇总 `30 PASS / 1 FAIL` |
| 还原 | sha256 回到基线 `2d1fc046…`，`31 PASS / 0 FAIL` |

同时修了 **B8e** 的过度约束：它原先钉死 `href="/favicon.svg"` 精确匹配，
于是"加版本号破缓存"这个正确做法反而被判红 —— 判据该管"指向哪个文件"，不是"带不带查询串"。

## 四、验证

| 项 | 结果 |
|---|---|
| dev server | `GET /favicon.svg?v=383` → `200` `image/svg+xml`，`ET.parse` 通过 |
| 页面引用 | `curl 5173` 的 HTML 里 `favicon.svg?v=383` |
| 图形本身 | 渲染为**白色店铺象形**（雨棚 + 店面轮廓），64/32 像素下可辨；不是「学」字 |
| 全仓扫描 | 47/47 合法，非法 0 |
| 构建 | `EXIT=0`，1082 行 PASS；`dist/favicon.svg` 可解析、`dist/index.html` 带 `?v=383` |

## 五、线上还要一次部署

8090 上那份 `favicon.svg` **仍是坏版本**（`curl` 实测注释含 `--`），
所以线上 tab 现在依旧显示旧图标。

按契约本仓不执行部署（`docs/产品侧上线契约.md` 第 3 行：不带凭据、不连服务器、不碰 nginx），
需要执行方把新的 `frontend/dist/` 传上去 —— 最小改动是这两个文件：

```
frontend/dist/favicon.svg
frontend/dist/index.html
```

传完用带 `Content-Type` 的探针确认，再强刷一次页面（`Ctrl+Shift+R`）。
