"""Allure 报告的安全解压与文件定位。

压缩包只允许落在本次执行目录内。数据库不保存 HTML 正文。
"""

from __future__ import annotations

import hashlib
import io
import json
import os
import zipfile
from pathlib import Path

from app.core.config import settings
from app.core.http.errors import bad_request, not_found

_MAX_FILES = 8000
_MAX_UNCOMPRESSED = 800 * 1024 * 1024
_MAX_RATIO = 200


def report_root() -> Path:
    """返回报告持久目录，并确保目录存在。"""
    root = Path(settings.AUTOMATION_REPORT_DIR).resolve()
    root.mkdir(parents=True, exist_ok=True)
    return root


def execution_dir(project_id: int, execution_id: int) -> Path:
    """按业务项目和执行隔离目录。"""
    return report_root() / str(project_id) / str(execution_id)


def sha256_bytes(data: bytes) -> str:
    """计算文件摘要，用于完整性校验和幂等对比。"""
    return hashlib.sha256(data).hexdigest()


def safe_extract(data: bytes, dest: Path) -> None:
    """解压 Allure HTML。拒绝路径穿越、符号链接、超大文件和异常压缩比。"""
    limit = settings.AUTOMATION_REPORT_MAX_BYTES
    if len(data) > limit:
        raise bad_request("报告压缩包超过大小限制")
    if len(data) < 4 or data[:2] != b"PK":
        raise bad_request("报告文件不是 ZIP 压缩包")
    dest.mkdir(parents=True, exist_ok=True)
    root = dest.resolve()
    try:
        archive = zipfile.ZipFile(io.BytesIO(data))
    except zipfile.BadZipFile as exc:
        raise bad_request("报告压缩包已损坏") from exc
    with archive:
        infos = archive.infolist()
        if len(infos) > _MAX_FILES:
            raise bad_request("报告文件数量超过限制")
        total = 0
        for info in infos:
            _reject_entry(info)
            total += info.file_size
            if total > _MAX_UNCOMPRESSED:
                raise bad_request("报告解压后超过大小限制")
            if info.compress_size and info.file_size > 1_000_000:
                if info.file_size / info.compress_size > _MAX_RATIO:
                    raise bad_request("报告压缩比异常")
            target = (root / info.filename).resolve()
            if not target.is_relative_to(root):
                raise bad_request("报告包含非法路径")
            if info.is_dir():
                target.mkdir(parents=True, exist_ok=True)
                continue
            target.parent.mkdir(parents=True, exist_ok=True)
            written = 0
            with archive.open(info) as source, target.open("wb") as output:
                while True:
                    chunk = source.read(1024 * 1024)
                    if not chunk:
                        break
                    written += len(chunk)
                    if written > info.file_size + 1024 or written > _MAX_UNCOMPRESSED:
                        raise bad_request("报告文件实际大小异常")
                    output.write(chunk)
    if not (root / "index.html").is_file():
        raise bad_request("报告压缩包缺少 index.html，无法打开完整 Allure 报告")


def _reject_entry(info: zipfile.ZipInfo) -> None:
    """拒绝绝对路径、父目录和符号链接。"""
    name = info.filename.replace("\\", "/")
    if not name or name.startswith("/") or "\x00" in name:
        raise bad_request("报告包含非法路径")
    parts = Path(name).parts
    if ".." in parts:
        raise bad_request("报告包含非法路径")
    mode = (info.external_attr >> 16) & 0o170000
    if mode == 0o120000:
        raise bad_request("报告包含符号链接")


def read_allure_summary(html_dir: Path) -> tuple[dict[str, int], list[dict], bool]:
    """从 Allure widgets 读取统计、套件分布，以及是否带有 history。"""
    stats = {"total": 0, "passed": 0, "failed": 0, "broken": 0, "skipped": 0, "unknown": 0}
    summary_path = html_dir / "widgets" / "summary.json"
    if summary_path.is_file():
        payload = _load_json(summary_path)
        statistic = payload.get("statistic") if isinstance(payload, dict) else None
        if isinstance(statistic, dict):
            for key in stats:
                stats[key] = int(statistic.get(key) or 0)
    suites = _suites(html_dir / "widgets" / "suites.json")
    history = (html_dir / "history").is_dir() and any((html_dir / "history").iterdir())
    return stats, suites, history


def resolve_report_file(storage_dir: str, file_path: str) -> Path:
    """把报告相对路径解析为真实文件。越界路径按不存在处理。"""
    root = (report_root() / storage_dir).resolve()
    relative = file_path.strip("/")
    if not relative:
        relative = "index.html"
    path = Path(relative)
    if path.is_absolute() or ".." in path.parts:
        raise not_found("报告文件不存在")
    target = (root / path).resolve()
    if not target.is_relative_to(root) or not target.is_file():
        raise not_found("报告文件不存在")
    return target


def write_bytes(path: Path, data: bytes) -> None:
    """原子写入附件，避免读到半份压缩包。"""
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(path.suffix + ".tmp")
    temporary.write_bytes(data)
    os.replace(temporary, path)


def _load_json(path: Path) -> dict:
    """读取 JSON 对象。损坏时返回空对象，不让统计解析阻断报告保存。"""
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {}
    return payload if isinstance(payload, dict) else {}


def _suites(path: Path) -> list[dict]:
    """提取套件名称和统计。兼容 Allure widgets 的对象或数组。"""
    if not path.is_file():
        return []
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return []
    items = payload.get("items") if isinstance(payload, dict) else payload
    if not isinstance(items, list):
        return []
    suites = []
    for item in items[:100]:
        if not isinstance(item, dict):
            continue
        statistic = item.get("statistic") if isinstance(item.get("statistic"), dict) else {}
        suites.append({
            "name": str(item.get("name") or "未命名套件")[:120],
            "total": int(statistic.get("total") or 0),
            "passed": int(statistic.get("passed") or 0),
            "failed": int(statistic.get("failed") or 0),
            "broken": int(statistic.get("broken") or 0),
            "skipped": int(statistic.get("skipped") or 0),
        })
    return suites
