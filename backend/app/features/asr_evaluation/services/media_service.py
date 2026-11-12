"""项目授权下的音频 Range 流媒体代理。

本模块只代理已登记音频的单次播放请求；每次读取都重新检查项目出站目标，不跟随重定向，
不把平台代理地址回传给 ASR 服务，读取字节有明确上限且不将音频完整载入内存。
"""

from __future__ import annotations

import os
import re
import json
import select
import shutil
import struct
import subprocess
import tempfile
import time
import wave
from collections.abc import Iterator
from pathlib import Path
from typing import Any

import httpx
from fastapi.responses import FileResponse, Response, StreamingResponse
from sqlalchemy.orm import Session

from app.core.config import settings
from app.core.http.errors import bad_request, not_found
from app.core.models.identity import User
from app.core.security.crypto import decrypt_secret
from app.execution.http.outbound_policy import resolve_project_outbound_target
from app.platform.projects.services.access_service import get_project_or_404
from app.features.asr_evaluation.models import AsrAudio, AsrAudioVersion, AsrProcessingRun

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


def analyze_audio_version(db: Session, processing_run: AsrProcessingRun) -> dict[str, Any]:
    """在后台有界下载固定版本到临时文件，使用 WAV 或配置工具解析并流式累计信号峰值。"""
    from app.features.asr_evaluation.models import AsrAudio

    version = db.get(AsrAudioVersion, processing_run.audio_version_id)
    audio = db.get(AsrAudio, processing_run.audio_id)
    if version is None or audio is None or version.audio_id != audio.id:
        return _analysis_unavailable("固定音频版本不存在")
    local_path = _managed_audio_path(version)
    if local_path is not None:
        source_info = {
            "name": version.name, "audio_version": version.version, "url_display": version.url_display,
            "playback_url": f"/api/v1/asr/audio/{audio.id}/versions/{version.id}/media",
            "source_size_bytes": local_path.stat().st_size, "source_label": "平台保存的音频文件",
        }
        db.rollback()
        return _analyze_with_ffmpeg(local_path, source_info)
    source_url = decrypt_secret(version.url_ciphertext)
    project_id = processing_run.project_id
    audio_id = audio.id
    source_version_id = version.id
    source_name = version.name
    source_version_number = version.version
    source_url_display = version.url_display
    decision = resolve_project_outbound_target(db, source_url, project_id)
    if decision.rejection_message:
        return _analysis_unavailable("音频源不在项目出站授权范围内")
    # 白名单查询结束后释放 DB 事务，再执行可能持续数分钟的有界文件读取。
    db.rollback()
    try:
        max_bytes = min(max(1024, int(os.getenv("ASR_MEDIA_ANALYSIS_MAX_BYTES", str(2 * 1024**3)))), 2**31 - 1)
    except ValueError:
        max_bytes = 2 * 1024**3
    source_info = {
        "name": source_name, "audio_version": source_version_number, "url_display": source_url_display,
        "playback_url": f"/api/v1/asr/audio/{audio_id}/versions/{source_version_id}/media",
        "source_size_bytes": None, "last_modified": None, "etag": None,
        "source_label": "已登记音频源",
    }
    try:
        with tempfile.TemporaryDirectory(prefix="asr-media-") as directory:
            file_path = Path(directory) / "source.bin"
            with httpx.Client(
                timeout=httpx.Timeout(connect=10, read=60, write=10, pool=10),
                follow_redirects=False, trust_env=False,
            ) as client:
                with client.stream("GET", source_url, headers={"Accept-Encoding": "identity"}) as response:
                    if response.status_code != 200:
                        return _analysis_unavailable("音频源未返回完整文件；后台分析本期不自行重定向或拉取分片")
                    content_length = response.headers.get("content-length")
                    if content_length:
                        try:
                            if int(content_length) > max_bytes:
                                return _analysis_unavailable("音频文件超过后台分析大小上限")
                            source_info["source_size_bytes"] = int(content_length)
                        except ValueError:
                            source_info["source_size_bytes"] = None
                    source_info["last_modified"] = response.headers.get("last-modified")
                    source_info["etag"] = response.headers.get("etag")
                    with file_path.open("wb") as output:
                        total = 0
                        for chunk in response.iter_bytes(65_536):
                            total += len(chunk)
                            if total > max_bytes:
                                return _analysis_unavailable("音频文件超过后台分析大小上限")
                            output.write(chunk)
                    source_info["source_size_bytes"] = total
            try:
                wav_info = _analyze_wav(file_path)
                return {
                    "status": "AVAILABLE", "source": "server-wave", "analyzer_version": "python-wave",
                    "source_info": source_info, "original_format": wav_info["original_format"],
                    "analysis_pcm": wav_info["analysis_pcm"], "signal_statistics": wav_info["signal_statistics"],
                    "peaks": wav_info["peaks"], "processed_range": wav_info["processed_range"], "warnings": [],
                }
            except (wave.Error, EOFError, ValueError):
                return _analyze_with_ffmpeg(file_path, source_info)
    except httpx.HTTPError:
        return _analysis_unavailable("后台读取音频源失败")
    except OSError:
        return _analysis_unavailable("服务器临时空间不可用")


def _analyze_wav(file_path: Path) -> dict[str, Any]:
    """以固定帧块读取 PCM WAV，不把整条音频或其峰值样本载入内存。"""
    with wave.open(str(file_path), "rb") as source:
        channels = source.getnchannels()
        sample_rate = source.getframerate()
        sample_width = source.getsampwidth()
        frame_count = source.getnframes()
        if source.getcomptype() != "NONE" or channels < 1 or channels > 8 or sample_width not in {1, 2, 3, 4}:
            raise ValueError("不支持的 WAV PCM 格式")
        channels = int(channels)
        resolutions = (2048, 8192)
        minimums = {resolution: [[1.0] * resolution for _ in range(channels)] for resolution in resolutions}
        maximums = {resolution: [[-1.0] * resolution for _ in range(channels)] for resolution in resolutions}
        bin_counts = {resolution: [[0] * resolution for _ in range(channels)] for resolution in resolutions}
        sums = [0.0] * channels
        squares = [0.0] * channels
        peaks = [0.0] * channels
        full_scale = [0] * channels
        sample_counts = [0] * channels
        frame_index = 0
        while True:
            data = source.readframes(8192)
            if not data:
                break
            samples = _decode_pcm(data, sample_width)
            frame_size = channels
            frames = len(samples) // frame_size
            for frame_offset in range(frames):
                for channel in range(channels):
                    normalized = samples[frame_offset * frame_size + channel]
                    for resolution in resolutions:
                        peak_bin = min(
                            resolution - 1,
                            ((frame_index + frame_offset) * resolution) // max(frame_count, 1),
                        )
                        minimums[resolution][channel][peak_bin] = min(
                            minimums[resolution][channel][peak_bin], normalized,
                        )
                        maximums[resolution][channel][peak_bin] = max(
                            maximums[resolution][channel][peak_bin], normalized,
                        )
                        bin_counts[resolution][channel][peak_bin] += 1
                    absolute = abs(normalized)
                    peaks[channel] = max(peaks[channel], absolute)
                    sums[channel] += normalized
                    squares[channel] += normalized * normalized
                    full_scale[channel] += int(absolute >= 0.999)
                    sample_counts[channel] += 1
            frame_index += frames
    duration = frame_count / sample_rate if sample_rate else None
    return {
        "original_format": {
            "container": "WAV", "codec": "PCM", "codec_configuration": "uncompressed",
            "sample_rate_hz": sample_rate, "channels": channels, "channel_layout": None,
            "bit_rate": None, "bits_per_sample": sample_width * 8, "encoder": None,
            "duration_seconds": duration,
        },
        "analysis_pcm": {
            "analysis_side": "server", "sample_rate_hz": sample_rate, "channels": channels,
            "format": "normalized_float32", "frames": frame_count, "duration_seconds": duration,
        },
        "signal_statistics": {
            "scope": "full_file", "channels": [{
                "channel_index": index, "peak": peaks[index],
                "rms": (squares[index] / sample_counts[index]) ** 0.5 if sample_counts[index] else None,
                "dc_offset": sums[index] / sample_counts[index] if sample_counts[index] else None,
                "full_scale_sample_count": full_scale[index], "sample_count": sample_counts[index],
            } for index in range(channels)],
        },
        "peaks": {
            str(resolution): [[
                [minimums[resolution][channel][index], maximums[resolution][channel][index]]
                if bin_counts[resolution][channel][index] else [0.0, 0.0]
                for index in range(resolution)
            ] for channel in range(channels)]
            for resolution in resolutions
        },
        "processed_range": {"start_ms": 0, "end_ms": round(duration * 1000) if duration is not None else None},
    }


def _decode_pcm(data: bytes, sample_width: int) -> list[float]:
    """将一个有限 PCM 帧块转成归一化浮点值供流式信号累计。"""
    if sample_width == 1:
        return [(value - 128) / 128 for value in data]
    if sample_width == 2:
        return [value / 32768 for (value,) in struct.iter_unpack("<h", data[:len(data) // 2 * 2])]
    if sample_width == 3:
        output = []
        for index in range(0, len(data) - 2, 3):
            value = data[index] | (data[index + 1] << 8) | (data[index + 2] << 16)
            if value & 0x800000:
                value -= 1 << 24
            output.append(value / 8_388_608)
        return output
    return [value / 2_147_483_648 for (value,) in struct.iter_unpack("<i", data[:len(data) // 4 * 4])]


def _analyze_with_ffmpeg(file_path: Path, source_info: dict[str, Any]) -> dict[str, Any]:
    """只对受控本地临时文件调用显式配置的 ffprobe/ffmpeg，工具缺失时不伪造分析结果。"""
    ffprobe = os.getenv("ASR_FFPROBE_PATH") or shutil.which("ffprobe")
    if not ffprobe:
        return _analysis_unavailable("当前不是可解析的 WAV 文件，且未配置 ffprobe")
    try:
        result = subprocess.run(
            [ffprobe, "-v", "error", "-protocol_whitelist", "file,pipe",
             "-show_format", "-show_streams", "-of", "json", str(file_path)],
            capture_output=True, text=True, timeout=30, check=False,
        )
        if result.returncode != 0 or len(result.stdout) > 2_000_000:
            return _analysis_unavailable("ffprobe 无法读取该音频的结构化文件信息")
        decoded = json.loads(result.stdout)
    except (OSError, subprocess.TimeoutExpired, ValueError):
        return _analysis_unavailable("ffprobe 执行失败或超时")
    streams = [item for item in decoded.get("streams", []) if item.get("codec_type") == "audio"]
    if not streams:
        return _analysis_unavailable("文件没有可识别的音频轨")
    stream = streams[0]
    duration_value = (decoded.get("format") or {}).get("duration") or stream.get("duration")
    try:
        duration = float(duration_value) if duration_value is not None else None
    except (TypeError, ValueError):
        duration = None
    original = {
        "container": (decoded.get("format") or {}).get("format_name"),
        "codec": stream.get("codec_name"), "codec_configuration": stream.get("profile"),
        "sample_rate_hz": _to_int(stream.get("sample_rate")), "channels": _to_int(stream.get("channels")),
        "channel_layout": stream.get("channel_layout"), "bit_rate": _to_int(stream.get("bit_rate")),
        "bits_per_sample": _to_int(stream.get("bits_per_raw_sample") or stream.get("bits_per_sample")),
        "encoder": (decoded.get("format") or {}).get("tags", {}).get("encoder"),
        "duration_seconds": duration,
    }
    ffmpeg = os.getenv("ASR_FFMPEG_PATH") or shutil.which("ffmpeg")
    if ffmpeg and duration and original["channels"] and 1 <= original["channels"] <= 8:
        try:
            decoded = _decode_with_ffmpeg(
                ffmpeg, file_path, int(original["channels"]), int(original["sample_rate_hz"] or 0), duration,
            )
            return {
                "status": "AVAILABLE", "source": "server-ffmpeg", "analyzer_version": "ffprobe+ffmpeg",
                "source_info": source_info, "original_format": original,
                "analysis_pcm": decoded["analysis_pcm"], "signal_statistics": decoded["signal_statistics"],
                "peaks": decoded["peaks"], "processed_range": decoded["processed_range"], "warnings": [],
            }
        except (OSError, subprocess.SubprocessError, ValueError):
            return _analysis_unavailable("ffmpeg 解码失败或超过后台处理时限")
    warning = "已读取原文件参数；当前未配置可用 ffmpeg，信号统计和波形尚未生成。"
    return {
        "status": "PARTIAL", "source": "server-ffprobe", "analyzer_version": "ffprobe",
        "source_info": source_info, "original_format": original, "analysis_pcm": {},
        "signal_statistics": {}, "peaks": {}, "processed_range": {}, "warnings": [warning],
    }


def _decode_with_ffmpeg(
    ffmpeg: str, file_path: Path, channels: int, source_rate: int, duration: float,
) -> dict[str, Any]:
    """流式读取受控文件的 float32 PCM 输出，按声道累计多级峰值与信号统计。"""
    sample_rate = 8000
    expected_frames = max(1, round(duration * sample_rate))
    resolutions = (2048, 8192)
    minimums = {resolution: [[1.0] * resolution for _ in range(channels)] for resolution in resolutions}
    maximums = {resolution: [[-1.0] * resolution for _ in range(channels)] for resolution in resolutions}
    bin_counts = {resolution: [[0] * resolution for _ in range(channels)] for resolution in resolutions}
    sums = [0.0] * channels
    squares = [0.0] * channels
    peaks = [0.0] * channels
    full_scale = [0] * channels
    sample_counts = [0] * channels
    frame_count = 0
    command = [
        ffmpeg, "-v", "error", "-nostdin", "-protocol_whitelist", "file,pipe", "-i", str(file_path),
        "-map", "0:a:0", "-vn", "-ac", str(channels), "-ar", str(sample_rate),
        "-f", "f32le", "-acodec", "pcm_f32le", "pipe:1",
    ]
    process = subprocess.Popen(command, stdout=subprocess.PIPE, stderr=subprocess.DEVNULL)
    if process.stdout is None:
        process.kill()
        raise OSError("ffmpeg 输出管道不可用")
    carry = b""
    frame_bytes = channels * 4
    deadline = time.monotonic() + min(
        max(60, int(os.getenv("ASR_MEDIA_ANALYSIS_TIMEOUT_SECONDS", "7200"))), 21_600,
    )
    try:
        while True:
            remaining = deadline - time.monotonic()
            if remaining <= 0 or not select.select([process.stdout], [], [], min(10, remaining))[0]:
                if time.monotonic() >= deadline:
                    raise subprocess.TimeoutExpired(command, 21_600)
                continue
            chunk = process.stdout.read(65_536)
            if not chunk:
                break
            data = carry + chunk
            usable = len(data) - len(data) % frame_bytes
            carry = data[usable:]
            for frame in struct.iter_unpack("<" + "f" * channels, data[:usable]):
                for channel, value in enumerate(frame):
                    if not (-1.0001 <= value <= 1.0001):
                        continue
                    normalized = max(-1.0, min(1.0, value))
                    absolute = abs(normalized)
                    peaks[channel] = max(peaks[channel], absolute)
                    sums[channel] += normalized
                    squares[channel] += normalized * normalized
                    full_scale[channel] += int(absolute >= 0.999)
                    sample_counts[channel] += 1
                    for resolution in resolutions:
                        peak_bin = min(resolution - 1, frame_count * resolution // expected_frames)
                        minimums[resolution][channel][peak_bin] = min(
                            minimums[resolution][channel][peak_bin], normalized,
                        )
                        maximums[resolution][channel][peak_bin] = max(
                            maximums[resolution][channel][peak_bin], normalized,
                        )
                        bin_counts[resolution][channel][peak_bin] += 1
                frame_count += 1
        if carry:
            raise ValueError("ffmpeg 返回了不完整 PCM 帧")
        if process.wait(timeout=max(1, deadline - time.monotonic())) != 0:
            raise subprocess.CalledProcessError(process.returncode, command)
    except Exception:
        process.kill()
        process.wait(timeout=5)
        raise
    return {
        "analysis_pcm": {
            "analysis_side": "server", "sample_rate_hz": sample_rate, "channels": channels,
            "format": "float32", "frames": frame_count,
            "duration_seconds": frame_count / sample_rate, "source_sample_rate_hz": source_rate,
        },
        "signal_statistics": {
            "scope": "full_file", "channels": [{
                "channel_index": index, "peak": peaks[index],
                "rms": (squares[index] / sample_counts[index]) ** 0.5 if sample_counts[index] else None,
                "dc_offset": sums[index] / sample_counts[index] if sample_counts[index] else None,
                "full_scale_sample_count": full_scale[index], "sample_count": sample_counts[index],
            } for index in range(channels)],
        },
        "peaks": {
            str(resolution): [[
                [minimums[resolution][channel][index], maximums[resolution][channel][index]]
                if bin_counts[resolution][channel][index] else [0.0, 0.0]
                for index in range(resolution)
            ] for channel in range(channels)]
            for resolution in resolutions
        },
        "processed_range": {"start_ms": 0, "end_ms": round(frame_count / sample_rate * 1000)},
    }


def _to_int(value: Any) -> int | None:
    """转换 ffprobe 的可选数值字段；无法报告时保持 None。"""
    try:
        return int(value)
    except (TypeError, ValueError):
        return None


def _analysis_unavailable(message: str) -> dict[str, Any]:
    """生成明确失败结果，音频播放和原始文本仍可独立使用。"""
    return {
        "status": "UNAVAILABLE", "source": None, "analyzer_version": None,
        "source_info": {}, "original_format": {}, "analysis_pcm": {},
        "signal_statistics": {}, "peaks": {}, "processed_range": {}, "warnings": [message],
    }


__all__ = ["analyze_audio_version", "stream_audio"]
