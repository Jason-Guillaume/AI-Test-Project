"""确定性转换 ASR 规范化快照。

供评测产物与后续内容评审使用；转写正文始终作为引用数据，转换不执行文本中的指令。
本模块不读取数据库或推测缺失时间，证据标识由快照提供。
"""

from __future__ import annotations

import json
import re
from typing import Any


CONVERTER_VERSION = "asr-markdown-1"


def _quoted(value: str) -> str:
    """逐行引用原文；保留换行和 Markdown 字符，避免原文伪造章节。"""
    return "> " + re.sub(r"(\r\n|\r|\n)", r"\1> ", value)


def render_markdown(snapshot: dict[str, Any]) -> bytes:
    """将冻结快照转换成稳定 UTF-8 字节；缺失字段显示未知，不引入生成时间。"""
    lines = [
        "# ASR 评测资料",
        f"转换版本：{CONVERTER_VERSION}",
        f"运行：{snapshot['run_id']}",
        f"音频版本：{snapshot.get('audio_version_id') if snapshot.get('audio_version_id') is not None else '未知'}",
        "模型与参数快照：" + json.dumps(snapshot.get("configuration", {}), ensure_ascii=False, sort_keys=True, separators=(",", ":")),
        "时间单位：毫秒", "", "## 原始全文", "",
        _quoted(snapshot.get("transcript") or ""), "",
    ]
    for segment in snapshot.get("segments", []):
        start, end = segment.get("start_ms"), segment.get("end_ms")
        time_range = f"{start}–{end} ms" if start is not None and end is not None else "未定位"
        speaker = segment.get("native_speaker_id")
        lines.extend([
            f"## 片段 {segment['evidence_id']}", f"- 时间：{time_range}",
            "- 原生说话人：" + (json.dumps(str(speaker), ensure_ascii=False) if speaker is not None else "未知"),
            f"- 原文偏移：{segment.get('start_offset')}–{segment.get('end_offset')}", "",
            _quoted(segment.get("text") or ""), "",
        ])
    if snapshot.get("warnings"):
        lines.extend(["## 限制", *[f"- {item}" for item in snapshot["warnings"]], ""])
    return "\n".join(lines).encode("utf-8")
