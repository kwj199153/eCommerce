# 项目质量复审报告 · 第 271 轮（新横切面 + 上轮疑似项定论）

> 口径：延续「代码 + 业务」全量审查，但**只报新发现，不重复第 270 轮已报的 45 条老账**。
> 方法：先做实/证伪上轮标「疑似」的项，再换角度扫新横切面（事务边界 / 异常吞没 / 资源泄漏 / 错误码语义 / 并发竞态）。
> 图例：★ 已亲自回读源码验证 · ○ agent 深挖 + 我复核 · △ 仅静态扫描（需运行期实测）

---

## 一、结论摘要

第 270 轮发现的 3 条 P0（读路径越权 / 写失败伪装成功 / 读失败灌 mock）仍是最高优先级，本轮**未发现新的 P0**。

本轮增量价值在**两块**：

1. **把上轮 3 个「疑似」做实/证伪**：
   - 同 `thread_id` 并发竞态 → **已确认（P1）**，确实无任何串行化，且 checkpoint 用 upsert 会静默丢状态。
   - 覆盖率门禁「写了个寂寞」 → **证伪**，CI 里是真红（pytest-cov 自动回退读 `fail_under=62`），只剩一处注释漂移。
   - 假绿残余 → 全量扫 117 文件，**未发现与上轮同级的新假绿**，仅新增 1 处弱假绿（P2）。

2. **新横切面发现一条上轮完全漏掉的问题线**：**24 处 `HTTPException(500, detail=str(e))` 异常透传 + 错误码语义错乱**，它绕过了全局异常处理器，在生产环境照样把内部异常原文泄给前端。

分级：**P1 ×3 · P2 ×4 · 已证伪 ×2**（无新 P0）。

---

## 二、P1（本轮新确认）

### P1-1 ★ 24 处 `500 + str(e)` 异常透传，绕过全局兜底（信息泄露 + 错误码语义错乱）

**现场分布**：

| 模块 | 数量 |
|---|---|
| `modules/listing_generator/router.py` | 9 |
| `modules/ad_analysis/router.py` | 7 |
| `modules/product_research/router.py` | 5 |
| `modules/customer_service/router.py` | 2 |
| `modules/secretary/router.py` | 1 |

**形态**（`listing_generator/router.py:74-78` 等 9 处，`ad_analysis/router.py:51-52` 等 7 处）：

```python
try:
    result = await service.generate_complete_listing(request)
    return ApiResponse(data=result.dict(), message="Listing 生成成功")
except Exception as e:
    raise HTTPException(status_code=500, detail=str(e))   # ← 问题在这
```

**两层问题**：

1. **信息泄露（绕过了全局兜底）**：项目本有正确的全局异常处理器 `main.py:172-191`——生产环境（`config.debug=False`）会把 `Exception` 洗成 `detail="服务器内部错误，请联系管理员"`。**但 `HTTPException` 走的是 FastAPI 自己的 handler，不经过这个全局 `Exception` 处理器**。于是这 24 处手动 `raise HTTPException(500, detail=str(e))` 等于**自己开洞**：生产环境照样把 Python 异常原文（可能含 SQL 片段、内部路径、第三方 SP-API / DashScope 响应体、堆栈线索）原样泄给前端。这是「全局兜底管不到的死角」。

2. **错误码语义错乱**：这些端点多数是 LLM 生成类（`generate/optimize/analyze/诊断`），把「LLM 超时 / 上游限流 / JSON 解析失败 / 内部 bug」**一律打成 500**。本应区分：
   - 上游/LLM 故障 → 502/503（可重试语义）
   - 输入非法 → 422/400
   - 内部 bug → 500（且不泄详情）
   同仓已有正确范式：`stores/router.py:830` 把 `ValueError → 400`、`candidates/router.py:96` 把 `CandidateQueryError → 400`、`ad_analysis/router.py:50` 把 `NoDataError → success=False 业务响应`。这 24 处是漏网的「其余异常」。

**与上轮发现的关系**：上轮报的 `dashscope_client.py:477-479`（LLM JSON 解析失败返回 `{"raw_text": ...}` 与成功同形）意味着**降级信号在 service 层已经丢了**，到 router 层只能一刀切 500——两条发现是同一根因的上下两层。

**修法**：删掉 24 处的 `except Exception → 500+str(e)`，让异常上抛给全局处理器；确需区分的业务失败用对应 4xx + 具体 `detail`；LLM 降级信号用上一轮 5.1 的 `data_status` 契约表达，而不是 500。

---

### P1-2 ○ 同 `thread_id` 并发无任何串行化，静默丢状态（上轮「疑似」→ 已确认）

**现场**：`ai_infra/base_agent.py:1659-1698`（`run_session` / `stream_session` / `aget_state`）

```python
async with asyncio.timeout(self.budget.max_seconds):
    return await graph.ainvoke(state, config=cfg)
```

- 全仓锁扫描：`asyncio.Lock` 只在 `rate_limit.py`（按 IP 计数）、`usage_tracker.py`/`billing`（计费行锁）等**无关处**，`thread_id` 路径**零锁、零串行化**（置信度 95%）。
- checkpoint 写入是 **upsert**（`ON CONFLICT (thread_id, checkpoint_ns, checkpoint_id) DO UPDATE`），不是先查后写。
- 结论：用户双开标签页 / 快速连点同一会话 → 两个 `ainvoke` 基于同一份 base state 各自算、各自 `put`，**后写覆盖先写，一轮消息被静默丢弃**。**不抛 IntegrityError、不报错、极难归因**。
- 定级 P1：多租户 SaaS 下这是真实可触发的静默数据丢失。

**修法**：按 `thread_id` 做进程内 `asyncio.Lock`（或用 Redis 分布式锁），把同一会话的 `ainvoke` 串行化；或至少用 checkpoint 的 `checkpoint_id` 乐观并发控制检测冲突并返回明确错误。

---

### P1-3 ○ 覆盖率门禁「写了个寂寞」→ **证伪**（门禁真实有效，仅注释漂移）

**结论翻转**：上一轮怀疑「CI 覆盖率命令无 `--cov-fail-under`，阈值只写在 `pyproject.toml`，等于没生效」。

**核实结果**：pytest-cov v5 的 `CovPlugin.start()` 会**回退**读 coverage 配置的 `[report] fail_under`（=`pyproject.toml:171` 的 `62`），且 `--cov-report=term-missing` 产出 `cov_total`，一旦 < 62 就 `testsfailed += 1` → CI 真红。CI 的 `working-directory: backend` 保证能读到 pyproject.toml，链路是通的。

**唯一问题（P2 级，文档漂移）**：`ci.yml:192` 注释写「`fail_under = 65` 是棘轮」，实际值是 **62**。`pyproject.toml:168-170` 自己解释了「先按 line-only 65.95% 定了 65，启用 branch 后重算成 62」，但 ci.yml 注释没同步。会误导下次抬阈值的人。

---

## 三、P2（本轮新确认）

### P2-1 ○ `create_candidate` 判重是「先查后写」TOCTOU，asin 无唯一约束

**现场**：`modules/candidates/service.py:240-247`

```python
if on_duplicate == "skip":
    existing = await find_candidate_by_asin(record.asin, shop_id)   # 先查
    if existing is not None:
        return {**existing, "deduped": True}
async with async_session_factory() as session:
    session.add(record)                                            # 后写，无唯一约束
    await session.commit()
```

`modules/candidates/db_model.py:35` 的 `asin` 只有 `index=True`（**非 unique**）。两个并发 `skip` 请求可双双通过 `find_candidate_by_asin` 检查、双双插入 → 重复行。

**与本仓已有范式矛盾**：`modules/aigc_media/job_service.py:8-17` 已经用 `INSERT ... ON CONFLICT DO NOTHING` 解决了同型问题。判重应下沉到数据库唯一约束 + `ON CONFLICT`。

### P2-2 ○ `approve_candidate` commit 后仍有序列化窗口，重试可重复建 SPU

**现场**：`modules/candidates/service.py:608-614`

```python
await session.commit()              # 608：已提交
...
return {"...", "product": spu_to_dict(product)}   # 611-614：在 async with 之外
```

若 `spu_to_dict` 抛异常（目前只访问标量字段、概率极低，但结构性存在），SPU + 候选标记已提交、客户端却见 500；重试时 `spu_id` 由时间戳重新生成（`:571` `f"spu-{int(...*1000)}"`）→ **重复建 SPU**。

### P2-3 ○ 事务边界：15 处 commit 无显式 rollback（范式不一致，非数据丢失）

**结论**：抽查 `candidates/service.py`、`knowledge_base/service.py`、`assets/router.py` 共 15 处 `await session.commit()`，均无 try/except、无显式 rollback。**但这不构成数据丢失**——它们都在 `async with async_session_factory()` 内，SQLAlchemy 2.0 的 `__aexit__` 调 `close()` 会隐式回滚未提交改动。

**真问题**：① 这些路由**不走 `get_db` 依赖**（`get_db` 有「成功 commit / 异常 rollback / 总是 close」的规范范式，见 `core/database.py:74-91`），而是 service 内部直接 `async_session_factory()`，导致**两套 session 管理范式并存**，异常路径少了 `get_db` 里的统一日志/回滚语义；② 异常发生时「隐式回滚」无任何日志，排查时难以定位「哪次写丢了」。

### P2-4 ○ 假绿残余：`test_billing_payment.py:489` 的 `pytest.raises(Exception)` 过宽

**现场**：`backend/tests/test_billing_payment.py:489-491`

```python
with pytest.raises(Exception) as ei:
    Settings(**prod_settings_kwargs(**over))
assert keyword in str(ei.value), ...
```

被测代码 `core/config.py:190-193` 实际抛的是 `raise ValueError(...)`（`:191`）。`pytest.raises(Exception)` 捕获一切 `Exception` 子类——若未来这条护栏被重构为 pydantic `ValidationError` 或某无关 bug 抛 `KeyError`，只要文案含关键字测试照绿。**建议**：改成 `pytest.raises(ValueError)`。

（注：比上轮已知的 `test_agent_budget.py:163`、`test_agent_plan.py:232` 强一档——那两处是裸 `pytest.raises(Exception)` 无后续断言；本处有 `assert keyword in`，故定 P2 非 P1。）

---

## 四、已排查并明确排除（避免重复挖）

- **同步阻塞调用**：`requests`/`urllib` 零命中，全用 `httpx` 异步，`async with` 管理连接，无泄漏。
- **资源泄漏**：`async with async_session_factory()` 兜底 + `AsyncClient` 绑定 loop（`memory/tasks.py:122` 注释明确），未发现未关闭连接/文件句柄。
- **假绿全量扫**：117 个测试文件，5 类假绿形态（恒真断言 / 过宽 pytest.raises / try-except-pass 吞逻辑 / 只断调用不断结果 / mock 整替换被测函数）**除 P2-4 外零新增**。门禁测试普遍自带「反向注入验证 + 防空转正向对照」，纪律极高。
- **`detail=str(e)` 里 stores/candidates 的 400/422**：正确，不是问题（业务错误转 4xx）。
- **`ad_analysis` 已有 `data_status` 契约雏形**：`agent_ad.py:1082-1102` 的 `_no_data()` 已实现 `data_status="no_data"` + `data_reason`，说明上轮 5.1「数据真实性分级」契约在该模块已开始落地，是好信号。

---

## 五、行动顺序

| 批次 | 内容 |
|---|---|
| **一批（立即）** | 承接上轮 P0-1/P0-2/P0-3/P1-6；**本轮 P1-1**（24 处 `500+str(e)` 删掉，让异常上抛全局兜底）可与之一并做 |
| **二批（本周）** | **P1-2**（thread_id 串行化，防静默丢消息）；**P2-1**（asin 唯一约束 + ON CONFLICT）；**P2-3**（统一 session 范式到 `get_db`） |
| **三批** | **P2-2**（approve_candidate 序列化收口）；**P2-4**（pytest.raises 收窄）；**P1-3 注释**（ci.yml:192 的 65→62） |

**本轮验证缺口**：
- P1-2 的 checkpoint upsert SQL 细节基于 langgraph-checkpoint-postgres 3.x 标准实现 + requirements 版本（本机未装 langgraph），置信度 85%；「无锁」结论是本仓代码直接确认，置信度 95%。
- P1-1 的信息泄露需**运行期实测**（生产 config.debug=False 下发一个会抛异常的真实请求，看 detail 是否泄出原文）——静态证据链已闭合（HTTPException 不走全局 Exception 处理器是 FastAPI 既定行为），建议修完补一条反向注入门禁：断言「生产模式无端点向 `HTTPException` 传 `detail=str(e)`」。
