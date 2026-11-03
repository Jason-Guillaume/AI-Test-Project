"""受限 JSON HTTP ASR 提供方。

本适配器只渲染白名单变量、读取 JSON Pointer，并调用平台共享 HTTP 执行器；不支持任意代码、
厂商签名算法或自动跟随重定向。响应超出配置上限时拒绝解析，不能把截断文本当成成功结果。
"""

from __future__ import annotations

import json
import math
import re
from typing import Any

from sqlalchemy.orm import Session

from app.execution.http.executor import ApiRequestExecutor

_TOKEN = re.compile(r"\{\{([a-zA-Z0-9_.-]+)\}\}")
_EXACT_TOKEN = re.compile(r"^\{\{([a-zA-Z0-9_.-]+)\}\}$")


class AsrProviderError(ValueError):
    """ASR 通用协议中的可定位错误；不包含请求密钥或签名 URL。"""


class AsrSubmissionUncertain(AsrProviderError):
    """提交可能已被远端接收；必须核实状态，不能安全重提。"""


class AsrRemoteFailure(AsrProviderError):
    """远端明确返回终态失败；与网络暂时不可用分开处理。"""


class AsrRateLimited(AsrProviderError):
    """远端返回限流，可安全延迟轮询或在明确拒绝后延迟提交。"""

    def __init__(self, retry_after_seconds: int | None = None) -> None:
        """保存脱离原始响应头的有限重试延迟。"""
        super().__init__("接口请求过于频繁")
        self.retry_after_seconds = retry_after_seconds


def render_template(value: Any, context: dict[str, Any]) -> Any:
    """递归渲染已命名变量，整值占位符保留 bool、number、object 与 null 类型。"""
    if isinstance(value, dict):
        return {key: render_template(item, context) for key, item in value.items()}
    if isinstance(value, list):
        return [render_template(item, context) for item in value]
    if not isinstance(value, str):
        return value
    exact = _EXACT_TOKEN.fullmatch(value)
    if exact:
        return _lookup_context(context, exact.group(1))

    def replace(match: re.Match[str]) -> str:
        replacement = _lookup_context(context, match.group(1))
        if isinstance(replacement, (dict, list)) or replacement is None:
            raise AsrProviderError("对象、数组和空值只能作为完整字段值")
        return str(replacement)

    return _TOKEN.sub(replace, value)


def _lookup_context(context: dict[str, Any], name: str) -> Any:
    """只讀取注入上下文中的明確路徑，拒絕未知變數。"""
    current: Any = context
    for part in name.split("."):
        if not isinstance(current, dict) or part not in current:
            raise AsrProviderError(f"模板变量未定义：{name}")
        current = current[part]
    return current


def read_json_pointer(value: Any, pointer: str) -> Any:
    """按 RFC 6901 JSON Pointer 读取字段；不存在路径时返回 None。"""
    if pointer == "":
        return value
    if not pointer.startswith("/"):
        raise AsrProviderError("字段映射必须使用 JSON Pointer")
    current = value
    for raw_part in pointer[1:].split("/"):
        part = raw_part.replace("~1", "/").replace("~0", "~")
        if isinstance(current, list):
            if not part.isdigit() or int(part) >= len(current):
                return None
            current = current[int(part)]
        elif isinstance(current, dict):
            if part not in current:
                return None
            current = current[part]
        else:
            return None
    return current


class GenericJsonProvider:
    """提交同步或可轮询 JSON ASR 请求并提取文本与可选分段时间。"""

    def __init__(self, executor: ApiRequestExecutor | None = None) -> None:
        """注入平台共享 HTTP 执行器；测试可替换为隔离的假执行器。"""
        self._executor = executor or ApiRequestExecutor()

    def submit(self, db: Session, *, project_id: int, execution: dict[str, Any], idempotency_key: str) -> dict[str, Any]:
        """提交一次待测或参考识别；结果未知的传输错误由 Worker 标记待核实。"""
        context = {
            "audio": {"url": execution["audio_url"]},
            "connection": {"model_id": execution["model_id"]},
            "experiment": {"parameters": execution.get("parameters", {})},
        }
        payload = render_template(execution["request_template"], context)
        if not isinstance(payload, dict):
            raise AsrProviderError("请求模板根节点必须是 JSON 对象")
        headers = self._headers(execution, idempotency_key)
        result = self._send(
            db, project_id=project_id, method=execution["method"], url=execution["endpoint"],
            headers=headers, body=payload, execution=execution,
        )
        return self._parse_response(result, execution, submitting=True)

    def poll(self, db: Session, *, project_id: int, execution: dict[str, Any], remote_task_id: str) -> dict[str, Any]:
        """查询已保存的远端任务 ID；GET 查询可在临时传输错误后安全重试。"""
        async_config = execution.get("async_config") or {}
        template = async_config.get("poll_url_template")
        if not isinstance(template, str) or not template:
            raise AsrProviderError("异步连接缺少轮询地址模板")
        poll_url = render_template(template, {"task_id": remote_task_id})
        result = self._send(
            db, project_id=project_id, method=str(async_config.get("poll_method", "GET")).upper(),
            url=str(poll_url), headers=self._headers(execution, None), body=None, execution=execution,
        )
        return self._parse_response(result, execution, submitting=False)

    def _headers(self, execution: dict[str, Any], idempotency_key: str | None) -> dict[str, str]:
        """复制连接自定义头，单独添加加密保存的凭据与幂等标识。"""
        headers = {str(key): str(value) for key, value in (execution.get("headers") or {}).items()}
        secret = execution.get("secret")
        secret_header = execution.get("secret_header")
        if secret and secret_header:
            if (execution.get("request_encoding") == "multipart" and secret_header.lower() == "authorization"
                    and not secret.lower().startswith("bearer ")):
                secret = f"Bearer {secret}"
            headers[secret_header] = secret
        if idempotency_key:
            headers.setdefault("Idempotency-Key", idempotency_key)
        return headers

    def _send(
        self, db: Session, *, project_id: int, method: str, url: str,
        headers: dict[str, str], body: dict[str, Any] | None, execution: dict[str, Any],
    ) -> Any:
        """通过项目出站白名单与共享有界执行器发送请求。"""
        if execution.get("request_encoding") == "multipart":
            from .audio_transcriptions import send_audio_transcription

            return send_audio_transcription(
                self._executor, db, project_id=project_id, method=method, url=url,
                headers=headers, body=body, execution=execution,
            )
        return self._executor.execute(
            db, method=method, url=url, project_id=project_id, headers=headers,
            json_body=body, timeout=int(execution["timeout_seconds"]),
            max_response_bytes=int(execution["max_response_bytes"]),
        )

    def _parse_response(self, response: Any, execution: dict[str, Any], *, submitting: bool) -> dict[str, Any]:
        """识别 HTTP、传输、截断和远端任务状态，统一为领域响应合同。"""
        if response.response_truncated:
            error = "接口响应超出已配置上限，未保存截断结果"
            if submitting:
                raise AsrSubmissionUncertain(error)
            raise AsrProviderError(error)
        if response.transport_error_kind:
            # 不把共享执行器的 URL 或传输异常原文写进错误栏，避免泄漏查询串和凭据。
            error = "提交响应状态未知，需核实远端状态" if submitting else "远端任务暂时无法查询"
            if submitting:
                raise AsrSubmissionUncertain(error)
            raise AsrProviderError(error)
        if response.error_message:
            raise AsrProviderError("请求被项目出站策略拒绝或接口暂时不可用")
        if response.status_code == 429:
            retry_after = response.response_headers.get("retry-after") or response.response_headers.get("Retry-After")
            try:
                delay = min(3600, max(1, int(retry_after))) if retry_after is not None else None
            except ValueError:
                delay = None
            raise AsrRateLimited(delay)
        if not 200 <= int(response.status_code) < 300:
            if submitting and int(response.status_code) >= 500:
                raise AsrSubmissionUncertain("接口提交响应状态未知，需核实远端状态")
            raise AsrProviderError(f"接口返回 HTTP {response.status_code}")
        try:
            body = json.loads(response.response_body or "null")
        except (ValueError, TypeError):
            if submitting:
                raise AsrSubmissionUncertain("接口已响应但结果无法解析，需核实远端状态") from None
            raise AsrProviderError("接口响应不是有效 JSON") from None
        async_config = execution.get("async_config") or {}
        response_mapping = execution.get("response_mapping") or {}
        if submitting and async_config:
            task_id = read_json_pointer(body, str(async_config.get("task_id_pointer", "")))
            if task_id is not None:
                return {"state": "RUNNING", "remote_task_id": str(task_id), "response_time_ms": response.response_time_ms}
            if async_config:
                raise AsrSubmissionUncertain("接口已响应但没有返回远端任务 ID，需核实提交状态")
        if not submitting and async_config:
            state = str(read_json_pointer(body, str(async_config.get("status_pointer", ""))) or "").lower()
            successes = {str(item).lower() for item in async_config.get("success_values", ["succeeded", "success", "done"])}
            failures = {str(item).lower() for item in async_config.get("failure_values", ["failed", "error"])}
            if state in failures:
                raise AsrRemoteFailure("远端识别任务明确失败")
            if state not in successes:
                return {"state": "RUNNING", "response_time_ms": response.response_time_ms}
            result_pointer = str(async_config.get("result_pointer", ""))
            if result_pointer:
                body = read_json_pointer(body, result_pointer)
        text_value = read_json_pointer(body, str(response_mapping.get("text_pointer", "")))
        if not isinstance(text_value, str):
            if submitting:
                raise AsrSubmissionUncertain("接口已响应但未提供可映射文本，需核实远端状态")
            raise AsrProviderError("响应文本映射未指向字符串")
        segments = self._segments(body, response_mapping, text_value)
        return {
            "state": "SUCCEEDED", "transcript": text_value,
            "segments": segments, "response_time_ms": response.response_time_ms,
        }

    def _segments(self, body: Any, mapping: dict[str, Any], transcript: str = "") -> list[dict[str, Any]]:
        """按字段映射保留原生 ID、说话人、置信度、声道和精确文本偏移。"""
        segment_path = mapping.get("segments_pointer")
        if not segment_path:
            return []
        rows = read_json_pointer(body, str(segment_path))
        if not isinstance(rows, list):
            return []
        normalized: list[dict[str, Any]] = []
        unit = str(mapping.get("time_unit", "seconds")).lower()
        cursor = 0
        for index, row in enumerate(rows[:100_000]):
            if not isinstance(row, dict):
                continue
            text_value = read_json_pointer(row, str(mapping.get("segment_text_pointer", "/text")))
            start = read_json_pointer(row, str(mapping.get("start_pointer", "/start")))
            end = read_json_pointer(row, str(mapping.get("end_pointer", "/end")))
            try:
                if unit in {"sample", "samples", "frame", "frames"}:
                    sample_rate = _read_optional(row, mapping, "sample_rate_pointer")
                    sample_rate = sample_rate or mapping.get("sample_rate")
                    if not isinstance(sample_rate, (int, float)) or sample_rate <= 0:
                        start_value = end_value = None
                    else:
                        start_value = float(start) / float(sample_rate) if start is not None else None
                        end_value = float(end) / float(sample_rate) if end is not None else None
                elif unit in {"s", "sec", "second", "seconds", "ms", "millisecond", "milliseconds"}:
                    factor = 0.001 if unit in {"ms", "millisecond", "milliseconds"} else 1.0
                    start_value = float(start) * factor if start is not None else None
                    end_value = float(end) * factor if end is not None else None
                else:
                    start_value = end_value = None
            except (TypeError, ValueError):
                start_value, end_value = None, None
            if start_value is not None and (not math.isfinite(start_value) or start_value < 0):
                start_value = None
            if end_value is not None and (not math.isfinite(end_value) or end_value < 0):
                end_value = None
            if start_value is not None and end_value is not None and end_value < start_value:
                start_value, end_value = None, None
            if isinstance(text_value, str):
                segment_start = transcript.find(text_value, cursor) if text_value else -1
                segment_end = segment_start + len(text_value) if segment_start >= 0 else None
                if segment_end is not None:
                    cursor = segment_end
                source_id = _read_optional(row, mapping, "segment_id_pointer")
                speaker_id = _read_optional(row, mapping, "speaker_pointer")
                confidence = _read_optional(row, mapping, "confidence_pointer")
                channel = _read_optional(row, mapping, "channel_pointer")
                word_times = _read_optional(row, mapping, "word_times_pointer")
                normalized.append({
                    "segment_index": index, "source_segment_id": str(source_id) if source_id is not None else None,
                    "text": text_value, "start_ms": round(start_value * 1000) if start_value is not None else None,
                    "end_ms": round(end_value * 1000) if end_value is not None else None,
                    "start_seconds": start_value, "end_seconds": end_value,
                    "start_offset": segment_start if segment_start >= 0 else None,
                    "end_offset": segment_end, "native_speaker_id": str(speaker_id) if speaker_id is not None else None,
                    "confidence": _finite_number(confidence), "channel": str(channel) if channel is not None else None,
                    "word_times": word_times if isinstance(word_times, list) else [],
                })
        return normalized


class DiarizationJsonProvider:
    """提交仅返回时间区间或带文本片段的通用 JSON 说话人模型请求。"""

    def __init__(self, executor: ApiRequestExecutor | None = None) -> None:
        """复用项目共享 HTTP 出站执行器，不引入厂商 SDK 或绕开项目白名单。"""
        self._provider = GenericJsonProvider(executor)

    def submit(
        self, db: Session, *, project_id: int, execution: dict[str, Any], idempotency_key: str,
    ) -> dict[str, Any]:
        """提交独立说话人处理请求，模型响应含全文与否都不影响其成功判断。"""
        context = {
            "audio": {"url": execution["audio_url"]},
            "connection": {"model_id": execution["model_id"]},
            "experiment": {"parameters": execution.get("parameters", {})},
        }
        payload = render_template(execution["request_template"], context)
        if not isinstance(payload, dict):
            raise AsrProviderError("请求模板根节点必须是 JSON 对象")
        response = self._provider._send(
            db, project_id=project_id, method=execution["method"], url=execution["endpoint"],
            headers=self._provider._headers(execution, idempotency_key), body=payload, execution=execution,
        )
        return self._parse_response(response, execution, submitting=True)

    def poll(
        self, db: Session, *, project_id: int, execution: dict[str, Any], remote_task_id: str,
    ) -> dict[str, Any]:
        """轮询已持久化远端任务 ID，并在可恢复阶段继续使用原始连接快照。"""
        async_config = execution.get("async_config") or {}
        template = async_config.get("poll_url_template")
        if not isinstance(template, str) or not template:
            raise AsrProviderError("说话人异步连接缺少轮询地址模板")
        poll_url = render_template(template, {"task_id": remote_task_id})
        response = self._provider._send(
            db, project_id=project_id, method=str(async_config.get("poll_method", "GET")).upper(),
            url=str(poll_url), headers=self._provider._headers(execution, None), body=None, execution=execution,
        )
        return self._parse_response(response, execution, submitting=False)

    def _parse_response(self, response: Any, execution: dict[str, Any], *, submitting: bool) -> dict[str, Any]:
        """提取任务状态、标准化说话人区间，并允许没有转写文本的成功响应。"""
        if response.response_truncated:
            if submitting:
                raise AsrSubmissionUncertain("说话人接口响应超出已配置上限，提交状态待核实")
            raise AsrProviderError("说话人接口响应超出已配置上限")
        if response.transport_error_kind:
            if submitting:
                raise AsrSubmissionUncertain("说话人提交状态未知，需核实远端状态")
            raise AsrProviderError("说话人任务暂时无法查询")
        if response.error_message:
            raise AsrProviderError("说话人请求被项目出站策略拒绝或接口暂时不可用")
        if response.status_code == 429:
            retry_after = response.response_headers.get("retry-after") or response.response_headers.get("Retry-After")
            try:
                delay = min(3600, max(1, int(retry_after))) if retry_after is not None else None
            except (TypeError, ValueError):
                delay = None
            raise AsrRateLimited(delay)
        if not 200 <= int(response.status_code) < 300:
            if submitting and int(response.status_code) >= 500:
                raise AsrSubmissionUncertain("说话人提交响应状态未知，需核实远端状态")
            raise AsrProviderError(f"说话人接口返回 HTTP {response.status_code}")
        try:
            body = json.loads(response.response_body or "null")
        except (ValueError, TypeError):
            if submitting:
                raise AsrSubmissionUncertain("说话人接口响应不是有效 JSON，需核实提交状态") from None
            raise AsrProviderError("说话人接口响应不是有效 JSON") from None
        async_config = execution.get("async_config") or {}
        mapping = execution.get("response_mapping") or {}
        if submitting and async_config:
            task_id = read_json_pointer(body, str(async_config.get("task_id_pointer", "")))
            if task_id is not None:
                return {"state": "RUNNING", "remote_task_id": str(task_id), "response_time_ms": response.response_time_ms}
            raise AsrSubmissionUncertain("说话人接口没有返回远端任务 ID，需核实提交状态")
        if not submitting and async_config:
            state = str(read_json_pointer(body, str(async_config.get("status_pointer", ""))) or "").lower()
            success = {str(item).lower() for item in async_config.get("success_values", ["succeeded", "success", "done"])}
            failures = {str(item).lower() for item in async_config.get("failure_values", ["failed", "error"])}
            if state in failures:
                raise AsrRemoteFailure("远端说话人任务明确失败")
            if state not in success:
                return {"state": "RUNNING", "response_time_ms": response.response_time_ms}
            if async_config.get("result_pointer"):
                body = read_json_pointer(body, str(async_config["result_pointer"]))
        source_turns = read_json_pointer(body, str(mapping.get("segments_pointer", "")))
        if not isinstance(source_turns, list):
            raise AsrProviderError("响应未提供可用的说话人时间区间")
        turns = _normalize_turns(body, mapping)
        if source_turns and not turns:
            raise AsrProviderError("响应中的说话人区间全部无效")
        return {
            "state": "SUCCEEDED", "turns": turns, "timeline": mapping.get("timeline", "original_audio"),
            "model_version": mapping.get("model_version"), "raw_response": _sanitize_payload(body),
            "response_time_ms": response.response_time_ms,
        }


def _finite_number(value: Any) -> float | None:
    """保留可用有限数值置信度，未知或非数值字段保持为空。"""
    if isinstance(value, bool):
        return None
    try:
        number = float(value)
    except (TypeError, ValueError):
        return None
    return number if math.isfinite(number) else None


def _normalize_turns(body: Any, mapping: dict[str, Any]) -> list[dict[str, Any]]:
    """接收时间区间-only 与带文本区间两种形态，不给缺失时间推测位置。"""
    values = read_json_pointer(body, str(mapping.get("segments_pointer", "")))
    if not isinstance(values, list):
        return []
    unit = str(mapping.get("time_unit", "seconds")).lower()
    if unit not in {"s", "sec", "second", "seconds", "ms", "millisecond", "milliseconds", "sample", "samples", "frame", "frames"}:
        return []
    result = []
    for index, row in enumerate(values[:100_000]):
        if not isinstance(row, dict):
            continue
        start = read_json_pointer(row, str(mapping.get("start_pointer", "/start")))
        end = read_json_pointer(row, str(mapping.get("end_pointer", "/end")))
        try:
            if isinstance(start, bool) or isinstance(end, bool):
                continue
            start_number, end_number = float(start), float(end)
            if not math.isfinite(start_number) or not math.isfinite(end_number) or start_number < 0 or end_number <= start_number:
                continue
            if unit in {"ms", "millisecond", "milliseconds"}:
                start_ms, end_ms = round(start_number), round(end_number)
            elif unit in {"sample", "samples", "frame", "frames"}:
                sample_rate = _read_optional(row, mapping, "sample_rate_pointer")
                sample_rate = sample_rate or mapping.get("sample_rate")
                if isinstance(sample_rate, bool) or not isinstance(sample_rate, (int, float)) or sample_rate <= 0:
                    continue
                start_ms = round(start_number / float(sample_rate) * 1000)
                end_ms = round(end_number / float(sample_rate) * 1000)
            else:
                start_ms, end_ms = round(start_number * 1000), round(end_number * 1000)
        except (OverflowError, TypeError, ValueError):
            continue
        if start_ms < 0 or end_ms <= start_ms:
            continue
        source_id = _read_optional(row, mapping, "segment_id_pointer")
        speaker = _read_optional(row, mapping, "speaker_pointer")
        text_value = read_json_pointer(row, str(mapping.get("segment_text_pointer", "/text")))
        channel = _read_optional(row, mapping, "channel_pointer")
        confidence = _read_optional(row, mapping, "confidence_pointer")
        source_label = str(speaker) if isinstance(speaker, (str, int, float)) and not isinstance(speaker, bool) else None
        channel_label = str(channel) if isinstance(channel, (str, int, float)) and not isinstance(channel, bool) else None
        result.append({
            "turn_index": index,
            "source_segment_id": str(source_id) if isinstance(source_id, (str, int, float)) and not isinstance(source_id, bool) else None,
            "source_speaker_id": source_label,
            "start_ms": start_ms, "end_ms": end_ms,
            "text": text_value if isinstance(text_value, str) else None,
            "channel": channel_label,
            "confidence": _finite_number(confidence), "raw_payload": _sanitize_payload(row),
        })
    return result


def _read_optional(value: Any, mapping: dict[str, Any], field: str) -> Any:
    """读取可选 JSON Pointer；空映射表示字段未配置，不能误把整行当成字段值。"""
    pointer = mapping.get(field)
    return read_json_pointer(value, str(pointer)) if isinstance(pointer, str) and pointer else None


def _sanitize_payload(value: Any) -> Any:
    """保留受限原始 JSON 证据并屏蔽常见凭据字段，避免响应回显秘密。"""
    if isinstance(value, dict):
        return {
            key: "[已脱敏]" if re.search(r"(authorization|token|secret|password|api[-_]?key|cookie)", str(key), re.I)
            else _sanitize_payload(item)
            for key, item in value.items()
        }
    if isinstance(value, list):
        return [_sanitize_payload(item) for item in value[:100_000]]
    if isinstance(value, str):
        value = re.sub(
            r"https?://[^\s\"'<>]+",
            lambda match: match.group(0).split("?", 1)[0] + ("?[已脱敏]" if "?" in match.group(0) else ""),
            value,
        )
        return re.sub(r"(?i)\bBearer\s+[^\s,;]+", "Bearer [已脱敏]", value)[:2000]
    if isinstance(value, (int, float, bool)) or value is None:
        return value
    return str(value)[:2000]


__all__ = [
    "AsrProviderError", "AsrRateLimited", "AsrRemoteFailure", "AsrSubmissionUncertain",
    "DiarizationJsonProvider", "GenericJsonProvider",
    "read_json_pointer", "render_template",
]
