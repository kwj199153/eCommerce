# 第 283 轮 · 输出校验止血（P0-8）处置记录

> 范围：LLM 结构化输出「不可用」不再伪装成成功。
> 日期：2026-09-27
> 状态：已落地 + 已反向注入验证（5/5 真红）+ 指标已曝光

---

## 1. 结论先行

| # | 缺陷 | 性质 | 处置 |
|---|------|------|------|
| 1 | `structured_chat()` 解析失败**同形退化**为 `{"raw_text": ...}` | 假成功 + 假阴 | 换成**相异结构** `__llm_parse_failed__` + 唯一判定入口 |
| 2 | `llm_structured()` **无条件** `success=True` | 假成功放大器 | 解析失败时 `success=False` 并带 `error` |
| 3 | `finish_reason` 是**只写不读**的死字段（全仓 0 消费点） | 归因错位 | `truncated` property + 流式路径显式标记 + 指标分原因 |

三条叠加的真实后果：**LLM 输出被截断 / 吐成非 JSON 时，前端拿到的是一份"看起来正常的增强结果"**，既不报错也不降级。

---

## 2. 证据链

### 2.1 同形退化（假阴 + 假成功）

`ai_infra/llm/dashscope_client.py` 修复前：

```python
except json.JSONDecodeError:
    return {"raw_text": response.content}     # ← 旧形态
```

问题不是"返回了什么"，而是**这个形态和合法结果同形**：

- LLM 合法返回一个含 `raw_text` 字段的 JSON → 与失败载荷**完全同形** → 调用方只能靠 `"raw_text" in data` 猜 → **假阴**（真结果被判失败）。
- 更危险的反方向：失败照样返回 `dict` → 下游 `isinstance(result, dict)` **恒真**。

实际受害点（`modules/product_research/agent_product_research.py:1447-1450`）：

```python
if llm_result.success and isinstance(llm_result.content, dict):
    result["llm_insights"] = llm_result.content
    result["enhanced"] = True                 # ← 解析失败也照样 True
```

配合 `ai_infra/base_agent.py` 修复前的**无条件** `success=True`（旧 `:686-695`），两个条件同时恒真 ⇒ `enhanced=True` **假成功**。

### 2.2 死字段导致归因跑偏

- `LLMResponse.finish_reason`（定义 `:182`、赋值 `:578`）修复前**全仓 0 个消费点**。
- 流式路径 `:396` 只取 delta content，全程不读 `finish_reason`。
- 后果：输出被 `max_tokens` 截断时，上层看到的症状是"偶发解析失败"，会去查提示词、查模型抽风，而不是查 `max_tokens` 配小了。

### 2.3 两个 `raw_text` 语义冲突

| 来源 | 语义 |
|------|------|
| `base_agent.LLMCallResult.raw_text` | **正常字段**（模型原文） |
| `dashscope_client` 失败载荷的 `raw_text` | **失败标记** |

同一个键两个语义，正是"只能靠猜"的根源。

---

## 3. 改动清单

| 文件 | 改动 |
|------|------|
| `ai_infra/llm/dashscope_client.py` | 新增 `LLMResponse.truncated` property（`:186`）；常量 `LLM_PARSE_FAILED_KEY`（`:214`）/ `FINISH_REASON_TRUNCATED`（`:216`）；`is_llm_parse_failed()` 唯一判定入口（`:219`）；`_llm_parse_failed_result()` 相异载荷构造 + 指标 + warning（`:228`）；`structured_chat()` 先判截断、`rpartition` 安全剥 ` ``` ` 包裹（不再抛 `IndexError`）、失败走相异载荷（`:563`）；`chat_stream` 收集 `stream_finish_reason`，截断则计指标 + warning（`:461`/`:485`） |
| `ai_infra/base_agent.py` | `llm_structured()` 在 `success=True` 之前插入判定（`:688-705`）：失败则 `success=False` + `error` 说明原因，`content` 仍回传供排障 |
| `core/observability/metrics.py` | 新增 `LLM_OUTPUT_INVALID`（`llm_output_invalid_total{model,reason}`，`:248`）并登记进 `_REGISTRY`（`:314`）；`reason ∈ {json_decode_error, truncated}` |
| `core/observability/__init__.py` | 导入 + `__all__` 导出 |
| `ai_infra/llm/__init__.py` | 门面导出 `is_llm_parse_failed` / `LLM_PARSE_FAILED_KEY` |
| `modules/platform_rules/ai_split.py` | 唯一正确消费方改为走 `is_llm_parse_failed()`（`:27`/`:87`），docstring 同步（`:79`） |
| `tests/test_llm_output_validation.py` | **新增** 12 条用例 |
| `tests/test_platform_rules.py` | `test_normalize_returns_empty_on_raw_text` → `test_normalize_returns_empty_on_parse_failed`（载荷**故意**带一份合法 `rules`，见 §5）+ 新增 `test_normalize_does_not_treat_legal_raw_text_as_failure` |

### 新失败载荷形态

```python
{
    "__llm_parse_failed__": True,   # 业务不可能产出此键 → 判定唯一入口
    "raw_text": "...",              # 仅排障用，不再是判据
    "reason": "truncated",          # 或 "json_decode_error"
    "truncated": True,
}
```

---

## 4. 设计要点（为什么这么改）

1. **相异结构胜于约定**：失败标记必须是业务不可能产出的键名 + **显式布尔**（`is True`，不是 truthy），否则"合法含该键"与"失败"无法区分。
2. **判定入口只有一处**：`is_llm_parse_failed()`。调用方禁写 `if "raw_text" in data`（那是同一判定的第二份实现）。
3. **截断与格式错分开归因**：两者运维动作完全不同（调 `max_tokens` vs 改提示词/加输出约束）。
4. **可用性与正确性分开计量**：`llm_calls_total{status}` 记"HTTP 成没成"，`llm_output_invalid_total` 记"成了但吐出来的能不能用"——后者是**静默的正确性故障**，不报错不降级，只能靠指标发现。
5. **AST 形态门禁**：测试扫描 `ai_infra/` 与 `modules/` 下所有 `"raw_text" in ...` 的 `ast.Compare`（`ast.In`），禁止旧判据复活。

---

## 5. 验证

### 5.1 回归

| 测试 | 结果 |
|------|------|
| `tests/test_llm_output_validation.py` | **12 passed** |
| `tests/test_platform_rules.py` | **47 passed** |
| LLM 相关 6 文件 | 41 passed |
| `product_research` + `base_agent` 4 文件 | 98 passed |

### 5.2 反向注入（把修复退回旧形态，看测试是否真红）

| # | 注入 | 结果 |
|---|------|------|
| R1 | `is_llm_parse_failed` 恒 False | **RED(good)** |
| R2 | `llm_structured` 恢复无条件 `success=True` | **RED(good)** |
| R3 | `structured_chat` 恢复 `{"raw_text": ...}` 同形退化 | **RED(good)** |
| R4 | 判据退回 `"raw_text" in data`（假阴判据） | **RED(good)** |
| R5 | 删掉 AST 形态门禁 | **RED(good)** |

**R1 的第一轮曾出现 `GREEN(BAD)`**：注入生效但测试仍绿——因为失败载荷里没有 `rules` 键，清洗层本就返回空，**判据被另一条守卫顶住**。
修法：让失败载荷**故意**带一份合法 `rules`，未识别标记就会吐出 1 条规则 ⇒ 判据立刻转红。
（教训：反向注入绿 ≠ 注入生效，先问"是不是被别的守卫顶住了"。）

### 5.3 指标曝光实测

```
llm_output_invalid_total{model="qwen-max",reason="truncated"} 1
```

---

## 6. 已知局限 / 遗留

1. 本次**不改** `product_research` 等下游的业务语义（只让它们不再被假成功骗），是否需要在 `success=False` 时走显式降级（如回退纯规则结果）属于产品决策，未在本轮拍板。
2. `output_format` 为 `json` 时目前只做"能否 `json.loads`"，**未做 schema 级校验**（字段齐不齐、类型对不对）。要补的话建议走 Pydantic，可作为下一项。
3. `finish_reason` 只在**非流式**与**流式收尾**两个点判定；若上游未来引入 tool_calls 中断等新终止原因，需同步扩 `FINISH_REASON_*` 常量。

---

## 7. 本次踩到的坑（供后续参考）

| 坑 | 处理 |
|----|------|
| 脚本 `load()` 未做行尾归一化 → CRLF/LF 混存 ⇒ 多行锚点恒 0 命中 | 统一 `b.decode().replace("\r\n","\n")`，回写按原样恢复 |
| 插入型幂等判据写成 `new in src`（`new` 以 `old` 为前缀 ⇒ `old` 恒命中）⇒ 块重复插入 2 次 | 按"定义体逐字节相同"去重；本轮在 `metrics.py` 抓到 1 处并已清理 |
| `monkeypatch.setattr(LLM_OUTPUT_INVALID,"inc",...)` 撞 `AttributeError: read-only`（`_Counter` 用 `__slots__`） | 改为从 `render()` 解析真实曝光值、断言 **delta**（基线现算，不手写期望值） |
| 并发跑两个 pytest 撞共享生产库（`tests/` 直连生产库） | 串行重跑 |
