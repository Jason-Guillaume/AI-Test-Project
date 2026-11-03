"""把已授权的 HTTP 音频有界下载到临时文件，再通过共享执行器上传转写。"""

from __future__ import annotations

import json
import tempfile
import time
from pathlib import PurePosixPath
from urllib.parse import urlsplit

import httpx

from app.execution.http.outbound_policy import resolve_project_outbound_target
from .generic_json import AsrProviderError

MAX_AUDIO_BYTES = 50 * 1024 * 1024
_AUDIO_TYPES = {
    ".wav": "audio/wav", ".mp3": "audio/mpeg", ".m4a": "audio/mp4",
    ".mp4": "audio/mp4", ".ogg": "audio/ogg", ".webm": "audio/webm",
    ".flac": "audio/flac", ".aac": "audio/aac", ".pcm": "application/octet-stream",
}


def send_audio_transcription(executor, db, *, project_id, method, url, headers, body, execution):
    """源站不接收模型凭据；两个目标分别授权，临时音频在所有退出路径关闭。"""
    if method != "POST" or not isinstance(body, dict):
        raise AsrProviderError("文件转写适配器仅支持同步 POST 请求")
    source_url = execution["audio_url"]
    for target in (url, source_url):
        if resolve_project_outbound_target(db, target, project_id).rejection_message:
            raise AsrProviderError("音频源或模型接口不在项目出站授权范围内")
    parameters = body.get("parameters", {})
    if not isinstance(parameters, dict) or any(key in parameters for key in ("file", "model")):
        raise AsrProviderError("音频转写参数无效，不能覆盖 file 或 model")
    form = {"model": execution["model_id"]}
    for key, value in parameters.items():
        if value is not None:
            form[str(key)] = value if isinstance(value, str) else json.dumps(value, ensure_ascii=False, allow_nan=False)
    limit = min(MAX_AUDIO_BYTES, max(1, int(execution.get("max_audio_bytes", MAX_AUDIO_BYTES))))
    timeout = min(180, max(1, int(execution.get("audio_download_timeout_seconds", 60))))
    suffix = PurePosixPath(urlsplit(source_url).path).suffix.lower()
    mime = _AUDIO_TYPES.get(suffix, "application/octet-stream")
    upload_headers = {key: value for key, value in headers.items() if key.lower() not in {"content-type", "content-length"}}
    with tempfile.TemporaryFile(mode="w+b") as audio:
        started = time.monotonic()
        try:
            with httpx.Client(timeout=httpx.Timeout(timeout, connect=min(10, timeout)),
                              follow_redirects=False, trust_env=False) as client:
                with client.stream("GET", source_url, headers={"Accept-Encoding": "identity"}) as response:
                    if response.status_code != 200:
                        raise AsrProviderError("音频源读取失败或返回了重定向")
                    content_type = response.headers.get("content-type", "").split(";", 1)[0].strip().lower()
                    if content_type and not (content_type.startswith("audio/") or content_type in {
                        "application/octet-stream", "binary/octet-stream", "video/mp4", "video/webm",
                    }):
                        raise AsrProviderError("音频源返回了非音频内容")
                    length = response.headers.get("content-length")
                    if length is not None:
                        try:
                            declared_size = int(length)
                        except ValueError:
                            raise AsrProviderError("音频源文件长度无效") from None
                        if declared_size < 1 or declared_size > limit:
                            raise AsrProviderError("音频文件为空或超过上传大小上限")
                    size = 0
                    for chunk in response.iter_bytes(chunk_size=65_536):
                        size += len(chunk)
                        if size > limit:
                            raise AsrProviderError("音频文件超过上传大小上限")
                        if time.monotonic() - started > timeout:
                            raise AsrProviderError("音频文件下载超时")
                        audio.write(chunk)
                    if size == 0 or (length is not None and size != declared_size):
                        raise AsrProviderError("音频文件为空或下载不完整")
        except httpx.HTTPError:
            raise AsrProviderError("音频文件下载失败，尚未向模型提交") from None
        audio.seek(0)
        return executor.execute(
            db, project_id=project_id, method="POST", url=url, headers=upload_headers,
            form_body=form, files=[("file", ("audio" + (suffix if suffix in _AUDIO_TYPES else ".bin"), audio, mime))],
            timeout=int(execution["timeout_seconds"]), max_response_bytes=int(execution["max_response_bytes"]),
        )
