"""项目授权下的音频 Range 流媒体代理。

本模块只代理已登记音频的单次播放请求；每次读取都重新检查项目出站目标，不跟随重定向，
不把平台代理地址回传给 ASR 服务，读取字节有明确上限且不将音频完整载入内存。
"""

from __future__ import annotations

import os
import re
from collections.abc import Iterator
from pathlib import Path

import httpx
from fastapi.responses import FileResponse, Response, StreamingResponse
from sqlalchemy.orm import Session

from app.core.config import settings
from app.core.http.errors import bad_request, not_found
from app.core.models.identity import User
from app.core.security.crypto import decrypt_secret
from app.execution.http.outbound_policy import resolve_project_outbound_target
from app.platform.projects.services.access_service import get_project_or_404
from app.features.asr_evaluation.models import AsrAudio, AsrAudioVersion

_RANGE = re.compile(r"^bytes=(\d*)-(\d*)$")
_CONTENT_RANGE = re.compile(r"^bytes (\d+)-(\d+)/(\d+|\*)$")


def _managed_audio_path(version: AsrAudioVersion | None) -> Path | None:
    """只读取已登记版本在持久卷内的媒体文件，不接受任意文件路径。"""
    key = (version.source_info or {}).get("local_media_key") if version is not None else None
    if key is None:
        return None
    if not isinstance(key, str) or re.fullmatch(r"[0-9a-f]{64}\.m4a", key) is None:
        raise not_found("平台音频文件登记无效")
    directory = (Path(settings.ASR_ARTIFACT_DIR) / "media").resolve()
    path = (directory / key).resolve()
    if path.parent != directory or not path.is_file():
        raise not_found("平台音频文件不存在")
    return path


def _iter_media(response: httpx.Response, client: httpx.Client, max_bytes: int) -> Iterator[bytes]:
    """逐块转发上游二进制；超出单次读取上限时停止并关闭两个流。"""
    sent = 0
    try:
        for chunk in response.iter_raw(chunk_size=65_536):
            remaining = max_bytes - sent
            if remaining <= 0:
                break
            if len(chunk) > remaining:
                yield chunk[:remaining]
                break
            sent += len(chunk)
            yield chunk
    finally:
        response.close()
        client.close()


def stream_audio(
    db: Session, audio_id: int, actor: User, range_header: str | None, *, audio_version_id: int | None = None,
) -> Response:
    """授权后代理指定不可变音频版本；未指定时兼容旧客户端读取当前版本。"""
    row = db.get(AsrAudio, audio_id)
    if row is None:
        raise not_found("音频资源不存在")
    get_project_or_404(db, row.project_id, actor)
    if audio_version_id is not None:
        version = db.get(AsrAudioVersion, audio_version_id)
        if version is None or version.audio_id != row.id:
            raise not_found("音频版本不存在")
    else:
        version = db.query(AsrAudioVersion).filter(
            AsrAudioVersion.audio_id == row.id, AsrAudioVersion.version == row.content_version,
        ).one_or_none()
    if range_header and _RANGE.fullmatch(range_header.strip()) is None:
        raise bad_request("仅支持单段 HTTP Range 请求")
    local_path = _managed_audio_path(version)
    if local_path is not None:
        return FileResponse(local_path, media_type="audio/mp4", headers={
            "Cache-Control": "private, no-store", "X-ASR-Range-Supported": "true",
        })
    source_url = decrypt_secret(version.url_ciphertext if version is not None else row.url_ciphertext)
    decision = resolve_project_outbound_target(db, source_url, row.project_id)
    if decision.rejection_message:
        raise not_found("音频源不在项目出站授权范围内")
    headers = {"Accept-Encoding": "identity"}
    if range_header:
        if _RANGE.fullmatch(range_header.strip()) is None:
            raise bad_request("仅支持单段 HTTP Range 请求")
        headers["Range"] = range_header.strip()
    client = httpx.Client(
        timeout=httpx.Timeout(connect=10, read=60, write=10, pool=10),
        follow_redirects=False, trust_env=False,
    )
    try:
        request = client.build_request("GET", source_url, headers=headers)
        response = client.send(request, stream=True)
    except httpx.HTTPError:
        client.close()
        raise bad_request("音频源暂时无法提供播放") from None
    if response.status_code == 416:
        content_range = response.headers.get("content-range")
        response.close()
        client.close()
        response_headers = {"Cache-Control": "private, no-store"}
        if content_range and "\r" not in content_range and "\n" not in content_range:
            response_headers["Content-Range"] = content_range
        return Response(status_code=416, headers=response_headers)
    if response.status_code not in {200, 206}:
        response.close()
        client.close()
        raise bad_request("音频源拒绝播放或返回了未授权的重定向")
    if response.status_code == 206 and not response.headers.get("content-range"):
        response.close()
        client.close()
        raise bad_request("音频源的 Range 响应缺少 Content-Range")
    try:
        max_bytes = min(max(1, int(os.getenv("ASR_MEDIA_MAX_BYTES", str(2 * 1024**3)))), 2**31 - 1)
    except ValueError:
        max_bytes = 2 * 1024**3
    if response.status_code == 206:
        match = _CONTENT_RANGE.fullmatch(response.headers.get("content-range", ""))
        if match is None:
            response.close()
            client.close()
            raise bad_request("音频源返回了无效的 Content-Range")
        start, end = int(match.group(1)), int(match.group(2))
        total = match.group(3)
        expected_length = end - start + 1
        content_length = response.headers.get("content-length")
        try:
            declared_length = int(content_length) if content_length is not None else expected_length
        except ValueError:
            declared_length = -1
        if (
            end < start
            or (total != "*" and end >= int(total))
            or expected_length > max_bytes
            or declared_length != expected_length
        ):
            response.close()
            client.close()
            raise bad_request("音频源 Range 响应超出读取上限或长度不一致")
    content_type = response.headers.get("content-type", "application/octet-stream").split(";", 1)[0].strip()
    if not (content_type.startswith("audio/") or content_type == "application/octet-stream"):
        response.close()
        client.close()
        raise bad_request("登记的音频源返回了非音频内容")
    output_headers = {
        "Content-Type": content_type,
        "Cache-Control": "private, no-store",
        "Accept-Ranges": response.headers.get("accept-ranges", "none"),
        "X-ASR-Range-Supported": "true" if response.status_code == 206 else "false",
    }
    for name in ("content-range", "content-length"):
        value = response.headers.get(name)
        if value and "\r" not in value and "\n" not in value:
            try:
                within_limit = name != "content-length" or int(value) <= max_bytes
            except ValueError:
                within_limit = False
            if within_limit:
                output_headers["Content-Range" if name == "content-range" else "Content-Length"] = value
    output_headers["X-ASR-Max-Read-Bytes"] = str(max_bytes)
    return StreamingResponse(
        _iter_media(response, client, max_bytes), status_code=response.status_code, headers=output_headers,
    )


__all__ = ["stream_audio"]
