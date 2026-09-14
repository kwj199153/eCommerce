"""
测试环境「真实 LLM 出网总闸」自检

`conftest._no_real_llm`（autouse）负责把测试期间的一切 LLM 调用挡在本地。
它一旦失效，用例会**静默打真实 DashScope**：耗时从毫秒涨到数十秒、
依赖网络与额度、而且看起来仍然是绿的（这正是本轮修掉的问题）。

本文件用最小代价钉住两件事：
1. 栈 B（`DashScopeLLM`）拿到的是桩，且毫秒级返回；
2. 桩照常上报用量——否则 test_billing_metering 的计量断言会假失败。

需要真实 LLM 的用例请标 `@pytest.mark.allow_real_llm`（见 pytest.ini）。
"""

import time


async def test_dashscope_stack_is_stubbed():
    """栈 B：`DashScopeLLM.chat` 应被总闸换成桩，且不得真出网。"""
    import ai_infra.llm.dashscope_client as dc

    llm = dc.get_llm(model="qwen-plus")
    t = time.time()
    r = await llm.chat("说一个字")
    elapsed = time.time() - t

    assert elapsed < 1.0, f"疑似真在出网（耗时 {elapsed:.2f}s）"
    assert "测试桩" in r.content, f"不是桩响应：{r.content[:80]}"
    # 桩必须照常上报用量，计量链路才被真实覆盖
    assert r.total_tokens == 200, r.total_tokens


async def test_dashscope_stream_stack_is_stubbed():
    """栈 B 的流式同样要被拦（原 fake_llm 只补了 chat，这里是易漏点）。"""
    import ai_infra.llm.dashscope_client as dc

    llm = dc.get_llm(model="qwen-plus")
    t = time.time()
    chunks = [c async for c in llm.chat_stream("说一个字")]
    elapsed = time.time() - t

    assert elapsed < 1.0, f"疑似真在出网（耗时 {elapsed:.2f}s）"
    assert chunks, "流式桩没有产出任何 chunk"
