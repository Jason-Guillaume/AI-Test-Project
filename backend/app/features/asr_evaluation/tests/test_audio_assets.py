"""音频资产、通用 JSON 提供方与媒体代理的隔离单元测试。"""

from __future__ import annotations

import asyncio
from types import SimpleNamespace

import httpx
import pytest
from fastapi import HTTPException

from app.execution.http import executor as http_executor
from app.features.asr_evaluation.providers.generic_json import (
    AsrProviderError, AsrSubmissionUncertain, GenericJsonProvider, read_json_pointer, render_template,
)
from app.features.asr_evaluation.services import media_service
from app.features.asr_evaluation.services.assets_service import _safe_url_display, _validate_parameters


def test_template_keeps_json_parameter_types_and_rejects_unknown_variable():
    """完整变量保留对象类型，未授权变量不能悄悄留在请求体。"""
    context = {"experiment": {"parameters": {"vad": {"enabled": True}}}}
    rendered = render_template({"parameters": "{{experiment.parameters}}"}, context)

    assert rendered == {"parameters": {"vad": {"enabled": True}}}
    with pytest.raises(AsrProviderError, match="未定义"):
        render_template({"audio": "{{audio.secret_url}}"}, context)


def test_json_pointer_reads_nested_objects_and_arrays():
    """JSON Pointer 能定位嵌套对象和数组索引，路径不存在时返回空值。"""
    value = {"data": {"segments": [{"text": "你好"}]}}

    assert read_json_pointer(value, "/data/segments/0/text") == "你好"
    assert read_json_pointer(value, "/data/segments/2/text") is None


def test_truncated_or_ambiguous_provider_submit_is_not_success():
    """截断 JSON 和缺少异步任务 ID 都进入待核实路径，不能存半条结果。"""
    provider = GenericJsonProvider(executor=object())
    truncated = SimpleNamespace(response_truncated=True)
    with pytest.raises(AsrSubmissionUncertain):
        provider._parse_response(truncated, {}, submitting=True)

    response = SimpleNamespace(
        response_truncated=False, transport_error_kind=None, error_message=None, status_code=200,
        response_body='{"accepted":true}', response_headers={}, response_time_ms=4,
    )
    with pytest.raises(AsrSubmissionUncertain, match="远端任务 ID"):
        provider._parse_response(
            response,
            {"async_config": {"task_id_pointer": "/task_id"}, "response_mapping": {"text_pointer": "/text"}},
            submitting=True,
        )


def test_segment_timestamps_reject_nonfinite_and_reversed_ranges():
    """供应方时间戳仅在有限、非负且起止有序时用于真实播放定位。"""
    provider = GenericJsonProvider(executor=object())
    segments = provider._segments(
        {"segments": [
            {"text": "甲", "start": float("nan"), "end": 1},
            {"text": "乙", "start": 2, "end": 1},
            {"text": "丙", "start": 1250, "end": 2500},
        ]},
        {"segments_pointer": "/segments", "time_unit": "milliseconds"},
    )

    assert [(item["text"], item["start_seconds"], item["end_seconds"]) for item in segments] == [
        ("甲", None, 0.001), ("乙", None, None), ("丙", 1.25, 2.5),
    ]
    assert segments[2]["start_ms"] == 1250
    assert segments[2]["end_ms"] == 2500


def test_shared_http_default_keeps_200k_character_contract_while_asr_can_raise_it(monkeypatch):
    """共享执行器默认仍按 200,000 字符截断，ASR 显式上限可保留更长中文响应。"""
    text = "中" * 200_001
    body = text.encode("utf-8")
    original_client = httpx.AsyncClient
    monkeypatch.setattr(
        http_executor.httpx, "AsyncClient",
        lambda **options: original_client(
            transport=httpx.MockTransport(lambda _request: httpx.Response(200, content=body)), **options,
        ),
    )

    legacy = http_executor.send_http_request(method="GET", url="https://api.example.test/legacy")
    asr = http_executor.send_http_request(
        method="GET", url="https://api.example.test/asr", max_response_bytes=1_000_000,
    )

    assert legacy.response_body == text[:200_000] + "\n...[已截断]"
    assert legacy.response_truncated is True
    assert asr.response_body == text
    assert asr.response_truncated is False


def test_url_display_masks_query_and_parameter_validation_rejects_credentials():
    """签名查询串在 URL 展示中始终隐藏，参数 JSON 不允许夹带凭据。"""
    assert _safe_url_display("https://audio.example.org/clip.mp3?X-Amz-Signature=hidden") == "https://audio.example.org/clip.mp3"
    with pytest.raises(HTTPException):
        _validate_parameters({"api_key": "hidden"}, [])


def test_media_proxy_streams_range_with_limit_and_rejects_multi_range(monkeypatch):
    """音频代理按项目权限流式传递 Range、限制读取字节并拒绝多段请求。"""
    captured: dict[str, object] = {}
    audio = SimpleNamespace(id=7, project_id=2, content_version=1, url_ciphertext="encrypted")

    class FakeResponse:
        status_code = 206
        headers = {
            "content-type": "audio/mpeg", "content-range": "bytes 0-4/100",
            "content-length": "5", "accept-ranges": "bytes",
        }

        def iter_raw(self, chunk_size):
            yield b"01234"
            yield b"56789"

        def close(self):
            captured["response_closed"] = True

    class FakeClient:
        def build_request(self, method, url, headers):
            captured["request_headers"] = headers
            return SimpleNamespace(method=method, url=url)

        def send(self, request, stream):
            captured["stream"] = stream
            return FakeResponse()

        def close(self):
            captured["client_closed"] = True

    monkeypatch.setattr(media_service, "resolve_project_outbound_target", lambda *_: SimpleNamespace(rejection_message=None))
    monkeypatch.setattr(media_service, "get_project_or_404", lambda *_: None)
    monkeypatch.setattr(media_service, "decrypt_secret", lambda _: "https://audio.example.org/file.mp3?signature=hidden")
    monkeypatch.setattr(media_service.httpx, "Client", lambda **_: FakeClient())
    monkeypatch.setenv("ASR_MEDIA_MAX_BYTES", "5")

    class EmptyAudioVersionQuery:
        """旧版音频无版本记录时返回 None 的最小查询替身。"""

        def filter(self, *_):
            """保留 SQLAlchemy 链式查询形状。"""
            return self

        def one_or_none(self):
            """该合成音频使用兼容的旧版本 URL。"""
            return None

    db = SimpleNamespace(get=lambda *_: audio, query=lambda *_: EmptyAudioVersionQuery())

    response = media_service.stream_audio(db, 7, SimpleNamespace(), "bytes=0-4")
    body = asyncio.run(_collect_body(response.body_iterator))

    assert response.status_code == 206
    assert response.headers["Content-Range"] == "bytes 0-4/100"
    assert response.headers["X-ASR-Range-Supported"] == "true"
    assert captured["request_headers"]["Range"] == "bytes=0-4"
    assert body == b"01234"
    assert captured["response_closed"] is True
    assert captured["client_closed"] is True
    monkeypatch.setenv("ASR_MEDIA_MAX_BYTES", "4")
    with pytest.raises(HTTPException):
        media_service.stream_audio(db, 7, SimpleNamespace(), "bytes=0-4")
    with pytest.raises(HTTPException):
        media_service.stream_audio(db, 7, SimpleNamespace(), "bytes=0-1,3-4")


async def _collect_body(iterator) -> bytes:
    """收集只在单测中使用的小型异步响应体。"""
    return b"".join([chunk async for chunk in iterator])