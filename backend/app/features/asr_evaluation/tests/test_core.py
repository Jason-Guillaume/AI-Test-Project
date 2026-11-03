"""ASR 对齐、通用协议、时区和规则证据的隔离单元测试。"""

from __future__ import annotations

import asyncio
from types import SimpleNamespace

import pytest
import httpx
from fastapi import HTTPException

from app.features.asr_evaluation.alignment import align_triplet, edit_ratio
from app.features.asr_evaluation.providers.generic_json import (
    AsrProviderError, AsrSubmissionUncertain, GenericJsonProvider, read_json_pointer, render_template,
)
from app.features.asr_evaluation.runtime.worker import AsrWorker
from app.features.asr_evaluation.services import media_service
from app.features.asr_evaluation.services.assets_service import _dump_connection, _parse_aware_datetime, _safe_url_display, _validate_parameters
from app.features.asr_evaluation.services.comparison_service import (
    _candidate_value_allowed, _contains_unsupported_claim, _redact_parameters, _rule_suggestions,
    _validated_reference_reuse_sources,
)
from app.execution.http import executor as http_executor


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


def test_alignment_preserves_unanimous_text_and_marks_differences():
    """一致片段保留原文，参考分歧单独形成可复核文本块。"""
    same, degraded = align_triplet("你好。", "你好。", "你好。")
    different, _ = align_triplet("共同片段。待测不同。", "共同片段。待测不同。", "共同片段。参考不同。")

    assert degraded is False
    assert same == [{"test_text": "你好。", "reference_a_text": "你好。", "reference_b_text": "你好。"}]
    assert any(row["reference_b_text"] != row["test_text"] for row in different)
    assert any(row["test_text"] == row["reference_a_text"] == row["reference_b_text"] == "共同片段。" for row in different)


def test_long_alignment_and_edit_ratio_are_explicitly_bounded():
    """超长文本仍完整保留并明确降级，差异比例超过上限时不伪造数字。"""
    text = "长" * 20_001
    rows, degraded = align_triplet(text, text, text)

    assert degraded is True
    assert rows[0]["test_text"] == text
    assert edit_ratio("甲乙", "甲丙") == 0.5
    assert edit_ratio("", "") == 0
    assert edit_ratio("甲" * 2_501, "甲") is None


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


def test_schedule_time_requires_an_explicit_timezone_and_url_display_masks_query():
    """一次性计划拒绝无时区时间，签名查询串在 URL 展示中始终隐藏。"""
    parsed = _parse_aware_datetime("2026-11-03T01:00:00+08:00")

    assert parsed.isoformat() == "2026-11-02T17:00:00+00:00"
    with pytest.raises(HTTPException):
        _parse_aware_datetime("2026-11-03T01:00:00")
    assert _safe_url_display("https://audio.example.org/clip.mp3?X-Amz-Signature=hidden") == "https://audio.example.org/clip.mp3"


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


def test_rule_suggestion_requires_confirmed_omission_and_real_vad_definition():
    """规则排查方向必须同时关联人工确认的疑似漏段和真实定义字段。"""
    block = SimpleNamespace(id=19, test_text="", confirmed_text="确认后的语音文本")
    definitions = [{"path": "/audio/vad_threshold", "display_name": "VAD 阈值", "description": "语音活动检测"}]
    suggestions = _rule_suggestions([block], definitions, {"audio": {"vad_threshold": 0.3}})

    assert len(suggestions) == 1
    assert suggestions[0]["evidence_block_ids"] == [19]
    assert suggestions[0]["parameter_path"] == "/audio/vad_threshold"
    assert suggestions[0]["candidate_value"] is None
    assert _rule_suggestions([SimpleNamespace(id=20, test_text="文本", confirmed_text="人工文本")], definitions, {}) == []
    assert _rule_suggestions([block], [{"path": "/unknown", "display_name": "未知参数"}], {}) == []


def test_connection_and_parameter_snapshots_do_not_echo_credentials_or_urls():
    """连接摘要隐藏自定义请求头和值模板，参数方案拒绝疑似凭据并清理 LLM 输入。"""
    row = SimpleNamespace(
        id=1, project_id=2, name="test", role="TEST", task_type="TRANSCRIPTION",
        provider_id="generic-json", model_id="model",
        version=1, endpoint_display="https://asr.example.org/v1", secret_ciphertext="encrypted",
        secret_header="Authorization", enabled=True, created_at=None,
        config_json={"headers": {"X-Client": "raw-secret"}, "request_template": {"audio": "https://audio.example.org/a?token=hidden"},
                     "response_mapping": {"text_pointer": "/text", "leak": "should-not-return"}},
    )
    summary = _dump_connection(row)

    assert summary["headers"] == {"X-Client": "[已配置]"}
    assert summary["request_template"] == {"configured": True}
    assert summary["response_mapping"] == {"text_pointer": "/text"}
    assert _redact_parameters({"evidence": "听到 https://audio.example.org/a?token=hidden Bearer abc"}) == {
        "evidence": "听到 [URL 已脱敏] Bearer [已脱敏]",
    }
    with pytest.raises(HTTPException):
        _validate_parameters({"api_key": "hidden"}, [])


def test_suggestion_filter_rejects_accuracy_causality_and_optimality_claims():
    """建议输出不能把参考一致写成正确、不能宣称因果或最优。"""
    assert _contains_unsupported_claim({"rationale": "两家参考模型一致，因此这是正确答案"})
    assert _contains_unsupported_claim({"observation": "该参数导致识别错误"})
    assert _contains_unsupported_claim({"rationale": "候选值已改善识别效果"})
    assert _contains_unsupported_claim({"rationale": "字段可能需要在接口说明中核实"}) is False


def test_llm_candidate_values_are_checked_against_real_parameter_definitions():
    """越界或类型不符的模型候选会被丢弃，合法候选通过既有定义。"""
    parameters = {"vad": {"threshold": 4}}
    definition = {"path": "/vad/threshold", "value_type": "integer", "minimum": 0, "maximum": 10}

    assert _candidate_value_allowed(parameters, "/vad/threshold", 7, definition)
    assert not _candidate_value_allowed(parameters, "/vad/threshold", 11, definition)
    assert not _candidate_value_allowed(parameters, "/vad/threshold", True, definition)


def test_worker_poll_backoff_has_a_fixed_upper_bound():
    """异步模型轮询逐渐退避但有界，不占用线程持续等待。"""
    assert AsrWorker._poll_delay(1) == 5
    assert AsrWorker._poll_delay(20) == 900


def test_reference_result_reuse_requires_two_successes_and_unchanged_audio_version():
    """显式复用仅能引用同一批次、同一音频版本下两条成功的参考输出。"""
    source_job = SimpleNamespace(id=5, config_snapshot={"audio_versions": {"9": 2}})
    comparison = SimpleNamespace(id=12, job_id=5, audio_id=9)
    audio = SimpleNamespace(id=9, content_version=2)
    references = [
        SimpleNamespace(id=20, role="REFERENCE", connection_id=3, status="SUCCEEDED", transcript="甲", audio_id=9, job_id=5),
        SimpleNamespace(id=21, role="REFERENCE", connection_id=4, status="SUCCEEDED", transcript="乙", audio_id=9, job_id=5),
    ]

    assert _validated_reference_reuse_sources(source_job, comparison, audio, references) == references
    with pytest.raises(HTTPException, match="音频版本已变化"):
        _validated_reference_reuse_sources(source_job, comparison, SimpleNamespace(id=9, content_version=3), references)
    references[1].status = "FAILED"
    with pytest.raises(HTTPException, match="两条完整成功"):
        _validated_reference_reuse_sources(source_job, comparison, audio, references)
