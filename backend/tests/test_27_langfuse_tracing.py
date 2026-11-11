"""Langfuse LLM 可观测埋点（Agent tracing）。

覆盖红线语义：
- 默认关闭 / key 不齐时全链路 no-op，不产生任何网络行为；
- 主流程异常（LLMError）标记 ERROR 后**原样抛出**，绝不被埋点吞掉；
- 埋点自身失败（span 创建/回写/flush 抛错）只记日志，不阻塞主流程；
- usage 字段按 OpenAI → Langfuse 映射（prompt_tokens→input 等）。

测试策略：不连真实 Langfuse，用假客户端替换 ``langfuse.Langfuse`` 验证交互。
"""

from __future__ import annotations

import pytest

from app.llm import tracing as langfuse_tracer
from app.llm.tracing import (
    flush_langfuse,
    get_langfuse_client,
    llm_generation,
    runtime_call_observation,
    runtime_attempt_observation,
    update_generation,
)
from app.core.config import settings


@pytest.fixture(autouse=True)
def _reset_tracer(monkeypatch):
    """每个用例前后重置客户端单例与配置，保证用例间互不影响。"""
    monkeypatch.setattr(settings, "LANGFUSE_ENABLED", False, raising=False)
    monkeypatch.setattr(settings, "LANGFUSE_PUBLIC_KEY", None, raising=False)
    monkeypatch.setattr(settings, "LANGFUSE_SECRET_KEY", None, raising=False)
    langfuse_tracer._build_client.cache_clear()
    yield
    langfuse_tracer._build_client.cache_clear()


def _enable(monkeypatch, *, public_key="pk-lf-test", secret_key="sk-lf-test"):
    """把配置切到「已启用」并清缓存，供后续重建客户端。"""
    monkeypatch.setattr(settings, "LANGFUSE_ENABLED", True, raising=False)
    monkeypatch.setattr(settings, "LANGFUSE_PUBLIC_KEY", public_key, raising=False)
    monkeypatch.setattr(settings, "LANGFUSE_SECRET_KEY", secret_key, raising=False)
    monkeypatch.setattr(settings, "LANGFUSE_ENVIRONMENT", "test", raising=False)
    langfuse_tracer._build_client.cache_clear()


# --------------------------------------------------------------------------- 假客户端


class _FakeGeneration:
    """记录 update 调用的假 generation。"""

    def __init__(self):
        """初始化对象状态。"""
        self.updates: list[dict] = []
        self.id = "span-test-id"

    def update(self, **kwargs):
        """更新对应数据。"""
        self.updates.append(kwargs)


class _FakeSpanCM:
    """假 span 上下文管理器，enter 可配置抛错。"""

    def __init__(self, generation, *, enter_error: Exception | None = None):
        """初始化对象状态。"""
        self._generation = generation
        self._enter_error = enter_error
        self.exited = False

    def __enter__(self):
        """进入上下文并返回所需资源。"""
        if self._enter_error is not None:
            raise self._enter_error
        return self._generation

    def __exit__(self, *exc_info):
        """退出上下文并释放资源。"""
        self.exited = True
        return False


class _FakeLangfuse:
    """记录交互的假 Langfuse 客户端。"""

    instances: list["_FakeLangfuse"] = []

    def __init__(self, **kwargs):
        """初始化对象状态。"""
        self.kwargs = kwargs
        self.observations: list[dict] = []
        self.generation = _FakeGeneration()
        self.flushed = False
        self.enter_error: Exception | None = None
        _FakeLangfuse.instances.append(self)

    def start_as_current_observation(self, **kwargs):
        """启动`as``current``observation`。"""
        self.observations.append(kwargs)
        return _FakeSpanCM(self.generation, enter_error=self.enter_error)

    def flush(self):
        """标记模拟追踪器已完成数据刷新。"""
        self.flushed = True


def _install_fake_langfuse(monkeypatch) -> type[_FakeLangfuse]:
    """把假客户端类注入 langfuse 模块命名空间。"""
    _FakeLangfuse.instances = []
    import langfuse

    monkeypatch.setattr(langfuse, "Langfuse", _FakeLangfuse)
    return _FakeLangfuse


# --------------------------------------------------------------------------- 用例


def test_disabled_by_default_is_noop():
    """默认关闭：客户端为 None，埋点 yield None，主流程照常执行。"""
    assert get_langfuse_client() is None
    with llm_generation(name="agent.chat", model="m", input_messages=[]) as gen:
        assert gen is None
    # update / flush 对 None 均为 no-op，不抛异常。
    update_generation(None, output="x", usage={"prompt_tokens": 1})
    flush_langfuse()


def test_enabled_without_keys_stays_disabled(monkeypatch):
    """enabled 但 key 不齐：保持关闭并告警，绝不抛出。"""
    _enable(monkeypatch, public_key="", secret_key="")
    assert get_langfuse_client() is None


def test_enabled_builds_client_with_environment(monkeypatch):
    """key 齐全：按配置构建客户端，environment 标签透传。"""
    fake_cls = _install_fake_langfuse(monkeypatch)
    _enable(monkeypatch)
    client = get_langfuse_client()
    assert isinstance(client, fake_cls)
    assert client.kwargs["environment"] == "test"
    assert client.kwargs["base_url"] == settings.LANGFUSE_BASE_URL


def test_generation_records_model_input_and_usage(monkeypatch):
    """正常路径：span 记录 model/input，usage 完成 OpenAI→Langfuse 映射。"""
    fake_cls = _install_fake_langfuse(monkeypatch)
    _enable(monkeypatch)
    client = get_langfuse_client()
    messages = [{"role": "user", "content": "你好"}]
    with llm_generation(
        name="agent.generate_structured.intent",
        model="qwen-plus",
        input_messages=messages,
        model_parameters={"temperature": 0.2},
        metadata={"model_config_id": 17, "model_revision": "r2"},
    ) as gen:
        assert gen is client.generation
        assert langfuse_tracer.current_generation_span_id.get() == gen.id
        update_generation(
            gen,
            output='{"intent":"GENERATE_TEST_POINTS"}',
            usage={"prompt_tokens": 10, "completion_tokens": 5, "total_tokens": 15},
        )
    obs = client.observations[0]
    assert obs["as_type"] == "generation"
    assert obs["model"] == "qwen-plus"
    assert obs["input"] == messages
    assert obs["metadata"]["model_config_id"] == 17
    assert gen.updates[-1]["usage_details"] == {"input": 10, "output": 5, "total": 15}
    assert langfuse_tracer.current_generation_span_id.get() is None


def test_main_flow_exception_marked_error_and_reraised(monkeypatch):
    """主流程异常：generation 标记 ERROR，异常原样抛出（不吞）。"""
    _install_fake_langfuse(monkeypatch)
    _enable(monkeypatch)
    client = get_langfuse_client()

    class _Boom(Exception):
        pass

    with pytest.raises(_Boom, match="模型服务请求失败"):
        with llm_generation(name="agent.chat", model="m", input_messages=[]) as gen:
            raise _Boom("模型服务请求失败")
    assert client.generation.updates[-1]["level"] == "ERROR"
    assert client.generation.updates[-1]["status_message"] == '_Boom'


def test_task_metadata_hides_output_and_error_body(monkeypatch):
    """任务元数据模式禁止响应和异常正文通过 generation 回写外泄。"""
    _install_fake_langfuse(monkeypatch)
    _enable(monkeypatch)
    client = get_langfuse_client()
    token = langfuse_tracer.task_trace_metadata.set({'task_id': 42})
    try:
        with pytest.raises(RuntimeError):
            with llm_generation(name='task', model='stub', input_messages=[{'content': 'private-input'}]) as gen:
                update_generation(gen, output='private-output', usage={'total_tokens': 3})
                raise RuntimeError('private-error-body')
        assert client.observations[0]['input'] == {'redacted': True}
        assert client.generation.updates[0]['output'] == {'redacted': True}
        assert client.generation.updates[0]['usage_details'] == {'total': 3}
        assert 'private-' not in str(client.observations) + str(client.generation.updates)
    finally:
        langfuse_tracer.task_trace_metadata.reset(token)


def test_runtime_attempt_observation_propagates_and_restores_parent(monkeypatch):
    """Attempt Span 使用可信 Trace 身份，退出后清理线程上下文。"""
    _install_fake_langfuse(monkeypatch)
    _enable(monkeypatch)
    client = get_langfuse_client()
    metadata = {"task_id": 7, "task_run_id": 8, "trace_id": "a" * 32, "attempt_id": 9}
    with runtime_attempt_observation(metadata) as span_id:
        assert span_id == "span-test-id"
        assert langfuse_tracer.task_trace_metadata.get() == metadata
        assert langfuse_tracer.task_trace_parent_span_id.get() == span_id
    assert client.observations[0]["name"] == "task.attempt"
    assert client.observations[0]["trace_context"] == {"trace_id": "a" * 32}
    assert langfuse_tracer.task_trace_metadata.get() is None
    assert langfuse_tracer.task_trace_parent_span_id.get() is None


def test_runtime_call_observation_inherits_agent_correlation(monkeypatch):
    """工具调用 span 自动继承任务/Agent 身份且不需要复制完整 Trace。"""
    _install_fake_langfuse(monkeypatch)
    _enable(monkeypatch)
    client = get_langfuse_client()
    metadata = {"task_id": 7, "task_run_id": 8, "trace_id": "b" * 32, "attempt_id": 9}
    with runtime_attempt_observation(metadata):
        with runtime_call_observation(name="tool.call", metadata={"tool_key": "safe.read"}) as span:
            span.update(output={"status": "SUCCEEDED"})
    assert client.observations[1]["metadata"]["task_id"] == 7
    assert client.observations[1]["metadata"]["tool_key"] == "safe.read"


def test_tracer_failure_never_blocks_main_flow(monkeypatch):
    """埋点自身失败（span 创建抛错）：主流程无感通过，yield None。"""
    _install_fake_langfuse(monkeypatch)
    _enable(monkeypatch)
    client = get_langfuse_client()
    client.enter_error = RuntimeError("Langfuse 服务端不可达")
    with llm_generation(name="agent.chat", model="m", input_messages=[]) as gen:
        assert gen is None  # 降级为 no-op，主流程继续
    flush_langfuse()
    assert client.flushed is True


def test_client_build_failure_falls_back_to_none(monkeypatch):
    """SDK 构造抛错（如版本不兼容）：返回 None 而不是让应用起不来。"""
    import langfuse

    def _broken(**kwargs):
        """模拟追踪器因参数不兼容而抛出异常。"""
        raise TypeError("unexpected keyword argument")

    monkeypatch.setattr(langfuse, "Langfuse", _broken)
    _enable(monkeypatch)
    assert get_langfuse_client() is None
