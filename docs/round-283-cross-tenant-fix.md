# 第 283 轮 · 跨租户读越权普查与收敛（P0-1 处置记录）

> 起因：第 283 轮技术尽调报告列「3 处读端点跨租户越权」。动手前复核时发现**报告低估了**，
> 且两个**根因**比漏洞本身更值得记录 —— 一个是写错的论证，一个是会漂移的门禁。

---

## 一、结论先行：实际是 5 处，不是 3 处

| # | 位置 | 形态 | HTTP | 是否可利用 |
|---|---|---|---|---|
| 1 | `modules/platform_rules/service.py` `get_rule_by_id` | `if shop_id:` | **GET** | ✅ 可读任意租户规则 |
| 2 | `modules/platform_rules/service.py` `get_doc_by_id` | `if shop_id:` | **GET** | ✅ 可读任意租户规则源文档正文 |
| 3 | `modules/knowledge_base/service.py` **4 个 GET**（`get_kb_by_id` / `get_kb_dict` / `get_faq_by_id` / `get_doc_by_id`） | `scoped_if(...)` | **GET** | ✅ 可读任意租户话术与知识库文档 |
| 4 | `modules/knowledge_base/service.py` **5 个写类** | `scoped_if(...)` | PUT/DELETE | ⚠️ 当前被 400 拦住（同形态，一并收敛） |
| 5 | `modules/candidates/service.py` `_load_scoped` | `if shop_id:` | **GET** | ✅ 可读任意租户候选选品详情 |
| 6 | `modules/monitors/service.py` `get_monitor_by_id` | `if shop_id:` | — | ⚠️ **零调用死代码**，但与 router 里那份无条件版是同一判定的第二份实现 |

攻击链：**带任意有效 token，不带 `X-Shop-ID`，凭 id 直读**。这类漏洞的特点是「看起来完全正常」
—— 缺一个可选的请求头，不该因此看到别人的数据。

---

## 二、根因 1：一段写错的论证，让这段漏洞活了三个版本

`core/tenant/scoping.py` 的模块 docstring 原本写着：

> ⚠️ 上表第二行「为空时返回全部店铺」在**当前不可达**：接入这些端点的模块都在
> `EXPECTED_STRICT_MODULES` 的严格档里，缺 `X-Shop-ID` 时 `get_current_shop_id` 会先 400。
> 那些 `if shop_id:` 是**防御性冗余**，本轮**刻意不删**。

**这个论证是错的。** 事实是（`core/tenant/middleware.py::_resolve_current_shop_id`）：

```python
if shop_id is None:
    if require_for_write and request.method.upper() in WRITE_METHODS:   # POST/PUT/PATCH/DELETE
        raise HTTPException(400, MISSING_SHOP_DETAIL)
    return None          # ← GET 缺头走的是这一条
```

400 空值守卫**只对写方法生效**，GET 不在 `WRITE_METHODS` 里 ⇒ GET 缺头返回 `None`
⇒ `if shop_id:` 判假 ⇒ 店铺条件整个不发 ⇒ **全库可读**。

⇒ 危害排序里，这段注释可能比漏洞本身更大：**它给了后来人一个「这里可以不改」的权威理由。**
本轮已重写该论证，并补上实测证据链。

## 三、根因 2：门禁是张手写名单，名单外的洞一个都没守住

`tests/test_shop_id_guard.py` 里其实**一直有**一条针对这个形态的 AST 护栏：

```python
targets = {
    "modules/assets/router.py":    ("get_asset",    "AssetRecord"),
    "modules/products/router.py":  ("get_spu",      "SpuRecord"),
    "modules/products/router.py":  ("get_sku",      "SpuRecord"),
    "modules/monitors/router.py":  ("get_monitor",  "MonitorRecord"),
}
```

它守住了 4 个 **router**，而本轮发现的 5 处漏洞全住在 **service**
（`platform_rules` / `knowledge_base` / `candidates` 三个模块从未进过名单）。

这正是本仓判据「**「恰好 N 处」是钉住旧形态的负资产**」的教科书案例：
手写名单必然漂移，因为它需要有人在新增文件时想起它。

### 还有一个「沉默的同犯」

`test_candidate_lifecycle_tools.py` 里早就写着：

> 漏传 shop_id 在 service 层表现为「`_load_scoped` 跳过归属过滤」⇒ **跨租户**能读到别人的候选

它当时把这归因于「工具层漏传」，于是只给**工具层**加了断言 —— REST 那条 GET 路径就此漏网。
**知道了裂缝的位置，却把补丁打在了另一堵墙上。**

---

## 四、本轮做了什么

### 修复（合计 40 处énom收敛）

| 类别 | 数量 | 说明 |
|---|---|---|
| 可利用读越权的修复 | 7 | platform_rules ×2、knowledge_base GET ×4、candidates ×1 |
| 同形态写路径收敛 | 23 | 当前被 400 拦住，但留着就是「下次换个依赖就复活」 |
| 批量删除端点收敛 | 4 | `delete_faqs_batch` 等项目错 attachments 形式 |
| 零调用重复实现 | 1 | `monitors.get_monitor_by_id` 删除（不在 `__all__`、零调用点） |
| **危险变体** | 1 | **删除 `scoped_if()`** —— 它的语义就是「为空即不过滤」 |

★ 为什么删 `scoped_if` 而不是留着加注释：**危险语义不该有名字。** 有名字，下一次就会被顺手用上。
配套加了反向断言：`scoped_if` 若重新出现在 `scoping.py` ⇒ 测试红。

### 修正了两处「把漏洞写成契约」的注释

原 docstring：`"""按主键取知识库（带租户校验：**给了** shop_id 就必须匹配）"""`
—— 一半语义藏在默认值里，读起来像设计，跑起来是漏洞。已改为明确写出「缺店铺 ⇒ 0 行 ⇒ None」。

### 门禁：手写名单 → 全仓形态扫描

`tests/test_tenant_scoping.py` 新增 S6：

- `test_no_conditional_scope_mounting` —— 遍历 `modules/**`，任何 `scoped()` /
  `scope_condition()` 调用被 `if shop_id:` 包住即红；
- `test_scanner_catches_conditional_mounting` —— **扫描器自检**（造一段违规源码必须被抓到），
  防的是「扫描器坏了 ⇒ 恒绿 ⇒ 门禁形同虚设」；
- 原 `test_shop_id_guard.py` 的手写字典型已删除，注释里指向 S6 —— **不留第二份实现**。

### 行为层：新增 `test_library_detail_reads_never_leak_across_shop`

形态门禁只证明「代码长对了」，不证明「请求真的被挡住」。所以补了端到端用例：
A 在其店铺建规则源文档 / 话术文档 / 候选选品，然后

| 情形 | 期望 |
|---|---|
| B **不带** `X-Shop-ID` 读 | 404（安全失败方向） |
| B 带**自己店**的头读 | 404 |
| A 带自己店的头读 | 200（不误伤） |

### 反向注入验证（双层都过）

```
[FIXED]     exit=0   ..                                    ← 修复后绿
[INJECTED]  exit=1   FAILED ...test_no_conditional_scope_mounting   ← 形态层转红
[INJECTED]  exit=1   FAILED ...test_library_detail_reads_never_leak_across_shop  ← 行为层转红
[RESTORED]  exit=0   ..                                    ← 恢复后绿
```

> 过程记录：第一次一起跑两个用例时，输出里只看到形态层转红，行为层看着是绿的。
> 怀疑是「被另一条守卫顶住 ⇒ 假绿」，隔离单跑后确认行为层**也真的会红**（两个用例都 Fail，
> 只是一起跑时 summary 行被截断，看起来只有一个红）。**没验证过的「看起来红/绿」都不算数。**

---

## 五、回归结果

定向 + 相关批次，合计 **~300 条用例通过**，覆盖：
`test_shop_id_guard` / `test_tenant_scoping` / `test_knowledge_base` / `test_platform_rules` /
`test_candidate_*` / `test_monitors` / `test_crud_endpoints` / `test_stores` /
`test_module_layering` / `test_core_internal_layering` / `test_product_research_candidate_flow` /
`test_frontend_api_field_contract` / `test_route_dependency_form` / `test_tool_registry_guard` /
`test_auth_and_tenant`。

### 一条与本轮无关的既有失败（待拍板）

`test_core_internal_layering.py::test_standalone_units_registry_is_exact`
⇒ `core/timefmt.py` 未登记进 `STANDALONE_UNITS`。

它是第 277 轮新增、至今未提交的模块；判据是 core 内部 import 图，与本轮改动的
`modules/**` 及 `scoping.py` 无交集 ⇒ **pre-existing**。修复只需一行（登记 + 写理由），
但属「分层收敛」另一个主题，未擅自处置。

---

## 六、沉淀（可复用判据）

1. **「只在写路径上验证过的守卫，不等于读路径安全」。** 本项目 400 空值守卫按 method 分流，
   任何「缺 ctx ⇒ 放宽过滤」的写法在读路径上都是越权。查守卫时先问：**它对 GET 生效吗？**
2. **注释里的安全论证必须可验证。** `scoping.py` 那段「不可达」是推理而非实测，
   而推理的前提（"会先 400"）本身是错的。写了承诺又不检查 ⇒ 比不写更危险。
3. **手写名单型门禁必然漂移，形态扫描不会。** 名单要有人想起它才有效；扫描只要文件在就有效。
4. **同一判定两份实现时，通常那份测不到的就是旧的、有害的。** `get_monitor_by_id` 正是因为
   零调用才没人发现它带着旧形态 —— 死代码不是惰性资产。
5. **补 contractor 前先问「这条路和水星有关吗」**：早先的测试已经点出 `_load_scoped` 会跳过过滤，
   但断言只加在工具层 ⇒ REST 那条路继续裸奔十年。
