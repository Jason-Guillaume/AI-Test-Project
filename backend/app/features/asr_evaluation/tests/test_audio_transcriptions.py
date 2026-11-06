"""文件转写的音频边界、凭据隔离及共享 multipart 传输回归。"""

import json
from types import SimpleNamespace

import httpx
import pytest

from app.execution.http import executor as http_executor
from app.execution.http.contracts import ApiRequestResult
from app.features.asr_evaluation.providers import audio_transcriptions
from app.features.asr_evaluation.providers.generic_json import AsrProviderError, GenericJsonProvider
from app.features.asr_evaluation.providers.response_redaction import execution_secrets, redact_response


def execution(**updates):
    return {
        "audio_url": "http://audio.example.test/clip.m4a?signature=private",
        "endpoint": "https://model.example.test/v1/audio/transcriptions", "method": "POST",
        "model_id": "XingChenAGI/XingChenASR-Diarize-V3.0", "request_encoding": "multipart",
        "secret": "test-key", "secret_header": "Authorization", "parameters": {},
        "request_template": {"parameters": "{{experiment.parameters}}"},
        "response_mapping": {"text_pointer": "/text", "segments_pointer": "/segments",
                             "start_pointer": "/start", "end_pointer": "/end", "speaker_pointer": "/speaker"},
        "timeout_seconds": 3, "max_response_bytes": 2048, **updates,
    }


def test_response_redaction_preserves_long_nested_transcript():
    """脱敏不截断长文本或数组，同时清除敏感字段和签名地址。"""
    transcript = "语音" * 1600
    result, changed = redact_response({"nested": [{"text": transcript}, {"token": "secret"}],
        "link": "https://example.invalid/audio?signature=private", "other": "key test-key"}, "test-key")
    assert changed is True
    assert result["nested"][0]["text"] == transcript
    assert result["nested"][1]["token"] == "[已脱敏]"
    assert "private" not in result["link"]
    assert "test-key" not in result["other"]
    secrets = execution_secrets({"parameters": {"access_token": "nested-secret"}, "secret_header": "Authorization"})
    assert secrets == ["nested-secret"]


def test_async_submission_and_final_preserve_distinct_complete_responses():
    """异步回执与最终轮询响应分别捕获；指针提取不丢失外层字段。"""
    provider = GenericJsonProvider()
    config = execution(async_config={"task_id_pointer": "/id", "status_pointer": "/status",
        "result_pointer": "/result", "success_values": ["done"]})
    receipt = ApiRequestResult()
    receipt.status_code = 200
    receipt.response_body = json.dumps({"id": "remote", "metadata": "receipt"})
    assert provider._parse_response(receipt, config, submitting=True)["response_kind"] == "RESPONSE_SUBMISSION"
    final = ApiRequestResult()
    final.status_code = 200
    final.response_body = json.dumps({"status": "done", "result": {"text": "甲" * 3000}, "extra": "完整外层"})
    response = provider._parse_response(final, config, submitting=False)
    assert response["response_kind"] == "RESPONSE_POLL_FINAL"
    assert response["response_capture"]["body"]["extra"] == "完整外层"
    assert len(response["transcript"]) == 3000


def install_audio_source(monkeypatch, response, captured):
    original_client = httpx.Client

    def handle(request):
        captured["source_headers"] = request.headers
        return response

    monkeypatch.setattr(audio_transcriptions, "resolve_project_outbound_target",
                        lambda *_: SimpleNamespace(rejection_message=None))
    monkeypatch.setattr(audio_transcriptions.httpx, "Client", lambda **kwargs: original_client(
        transport=httpx.MockTransport(handle), **kwargs))


def test_url_is_downloaded_then_uploaded_without_forwarding_model_secret(monkeypatch):
    captured = {}
    install_audio_source(monkeypatch, httpx.Response(200, content=b"audio-bytes",
                         headers={"content-type": "audio/mp4"}), captured)

    class Executor:
        def execute(self, db, **kwargs):
            captured.update(kwargs)
            handle = kwargs["files"][0][1][1]
            captured["audio"] = handle.read()
            captured["handle"] = handle
            result = ApiRequestResult()
            result.status_code = 200
            result.response_body = json.dumps({"text": "1: 测试", "segments": [
                {"id": "0", "text": "测试", "speaker": "1", "start": 0.0, "end": 1.25},
            ]})
            return result

    result = GenericJsonProvider(Executor()).submit(object(), project_id=1, execution=execution(), idempotency_key="probe")
    assert result["transcript"] == "1: 测试"
    assert result["segments"][0]["native_speaker_id"] == "1"
    assert result["segments"][0]["end_ms"] == 1250
    assert captured["audio"] == b"audio-bytes"
    assert captured["handle"].closed
    assert captured["headers"]["Authorization"] == "Bearer test-key"
    assert "authorization" not in captured["source_headers"]
    assert captured["form_body"] == {"model": execution()["model_id"]}
    assert captured["files"][0][1][0] == "audio.m4a"


@pytest.mark.parametrize("response,limit", [
    (httpx.Response(302, headers={"location": "http://other.test"}), 100),
    (httpx.Response(200, content=b"", headers={"content-type": "audio/wav"}), 100),
    (httpx.Response(200, content=b"1234", headers={"content-type": "text/html"}), 100),
    (httpx.Response(200, content=b"1234", headers={"content-type": "audio/wav"}), 3),
    (httpx.Response(200, stream=httpx.ByteStream(b"1234"), headers={"content-type": "audio/wav"}), 3),
    (httpx.Response(200, content=b"1234", headers={"content-length": "5"}), 100),
])
def test_invalid_or_oversized_download_is_never_submitted(monkeypatch, response, limit):
    install_audio_source(monkeypatch, response, {})

    class Executor:
        def execute(self, *_args, **_kwargs):
            pytest.fail("invalid audio must not be submitted")

    with pytest.raises(AsrProviderError):
        GenericJsonProvider(Executor()).submit(object(), project_id=1,
            execution=execution(max_audio_bytes=limit), idempotency_key="probe")


def test_denied_target_is_checked_before_any_download(monkeypatch):
    monkeypatch.setattr(audio_transcriptions, "resolve_project_outbound_target",
                        lambda *_: SimpleNamespace(rejection_message="denied"))
    monkeypatch.setattr(audio_transcriptions.httpx, "Client", lambda **_: pytest.fail("must not download"))
    with pytest.raises(AsrProviderError, match="授权"):
        GenericJsonProvider(object()).submit(object(), project_id=1, execution=execution(), idempotency_key="probe")


def test_shared_executor_sends_file_and_model_in_multipart(monkeypatch):
    captured = {}

    def handle(request):
        captured["type"] = request.headers["content-type"]
        captured["body"] = request.content
        return httpx.Response(200, json={"text": "测试"})

    original_client = httpx.AsyncClient
    monkeypatch.setattr(http_executor, "resolve_project_outbound_target",
                        lambda *_: SimpleNamespace(rejection_message=None))
    monkeypatch.setattr(http_executor.httpx, "AsyncClient", lambda **kwargs: original_client(
        transport=httpx.MockTransport(handle), **kwargs))
    result = http_executor.ApiRequestExecutor().execute(object(), method="POST", project_id=1,
        url="https://model.example.test", form_body={"model": "test-model"},
        files=[("file", ("audio.wav", b"audio-bytes", "audio/wav"))])
    assert result.status_code == 200
    assert captured["type"].startswith("multipart/form-data; boundary=")
    assert b'name="model"' in captured["body"] and b"test-model" in captured["body"]
    assert b'filename="audio.wav"' in captured["body"] and b"audio-bytes" in captured["body"]
