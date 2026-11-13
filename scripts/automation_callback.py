"""Sign and send Allure callback/history requests using the platform HMAC contract."""

from __future__ import annotations

import argparse
import hashlib
import hmac
import json
import os
import random
import sys
import time
import urllib.error
import urllib.parse
import urllib.request
import uuid
import zipfile
from pathlib import Path, PurePosixPath

MAX_UPLOAD_BYTES = 180_000_000
MAX_LOG_BYTES = 1_900_000
RETRIES = 4


class NoRedirect(urllib.request.HTTPRedirectHandler):
    """Refuse callback redirects so HMAC headers never cross origins."""

    def redirect_request(self, req, fp, code, msg, headers, newurl):
        return None


def sha(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def signed_headers(
    secret: str, callback_key: str, idempotency_key: str, report: bytes, metadata: str,
    *, report_sha256: str | None = None,
) -> dict[str, str]:
    timestamp = str(int(time.time()))
    report_digest = report_sha256 or sha(report)
    canonical = "\n".join((timestamp, callback_key, idempotency_key, report_digest, sha(metadata.encode("utf-8"))))
    signature = hmac.new(secret.encode("utf-8"), canonical.encode("utf-8"), hashlib.sha256).hexdigest()
    return {
        "X-Automation-Timestamp": timestamp,
        "X-Automation-Signature": signature,
        "X-Idempotency-Key": idempotency_key,
    }


def callback_settings() -> tuple[str, str, str, str]:
    url = os.environ.get("AUTOMATION_CALLBACK_URL", "").strip()
    key = os.environ.get("AUTOMATION_CALLBACK_KEY", "").strip()
    secret = os.environ.get("AUTOMATION_CALLBACK_SECRET", "")
    project_id = os.environ.get("AUTOMATION_PROJECT_ID", "").strip()
    parsed = urllib.parse.urlsplit(url)
    allowed_origin = os.environ.get("AUTOMATION_CALLBACK_ORIGIN", "").strip().rstrip("/")
    if (
        parsed.scheme != "https" or not parsed.netloc or parsed.username or parsed.password
        or not allowed_origin or f"{parsed.scheme}://{parsed.netloc}" != allowed_origin
        or not parsed.path.rstrip("/").endswith("/automation-callbacks/" + key)
    ):
        raise ValueError("AUTOMATION_CALLBACK_URL 必须是可信 HTTPS 地址")
    if not key or not secret or not project_id.isdigit():
        raise ValueError("Jenkins Credentials 或自动化项目参数未配置")
    return url, key, secret, project_id


def open_request(request: urllib.request.Request, *, timeout: int = 20) -> bytes:
    opener = urllib.request.build_opener(NoRedirect)
    with opener.open(request, timeout=timeout) as response:
        return response.read(MAX_UPLOAD_BYTES + 1)


def retry_request(request_factory, *, allow_history_404: bool = False) -> bytes:
    last_error: Exception | None = None
    for attempt in range(RETRIES):
        request = request_factory()
        try:
            return open_request(request)
        except urllib.error.HTTPError as exc:
            if allow_history_404 and exc.code == 404:
                print("平台没有上一份 Allure history；将生成首轮报告。")
                return b""
            if exc.code not in {408, 425, 429, 500, 502, 503, 504}:
                raise RuntimeError(f"平台回调失败（HTTP {exc.code}）") from exc
            last_error = exc
        except (urllib.error.URLError, TimeoutError) as exc:
            last_error = exc
        if attempt + 1 < RETRIES:
            time.sleep(min(2**attempt + random.random(), 8))
    raise RuntimeError(f"平台回调在 {RETRIES} 次尝试后仍失败：{type(last_error).__name__}")


def fetch_history() -> int:
    callback_url, callback_key, secret, project_id = callback_settings()
    parsed = urllib.parse.urlsplit(callback_url)
    query = urllib.parse.parse_qsl(parsed.query, keep_blank_values=True)
    query = [(key, value) for key, value in query if key != "automation_project_id"]
    query.append(("automation_project_id", project_id))
    url = urllib.parse.urlunsplit((parsed.scheme, parsed.netloc, parsed.path.rstrip("/") + "/history", urllib.parse.urlencode(query), ""))
    build_scope = hashlib.sha256(os.environ.get("BUILD_TAG", "manual").encode()).hexdigest()[:20]
    idempotency = f"jenkins-history:{project_id}:{build_scope}"

    def make_request():
        headers = signed_headers(secret, callback_key, idempotency, b"", project_id)
        return urllib.request.Request(url, headers=headers, method="GET")

    archive = retry_request(make_request, allow_history_404=True)
    if not archive:
        return 0
    if len(archive) > MAX_UPLOAD_BYTES:
        raise RuntimeError("平台返回的 Allure history 压缩包超过大小限制")
    target_root = Path("allure-results/history").resolve()
    target_root.mkdir(parents=True, exist_ok=True)
    total = 0
    try:
        with zipfile.ZipFile(__import__("io").BytesIO(archive)) as source:
            for member in source.infolist():
                path = PurePosixPath(member.filename)
                parts = path.parts[1:] if path.parts and path.parts[0] == "history" else path.parts
                if member.is_dir() or not parts or path.is_absolute() or ".." in parts:
                    continue
                total += member.file_size
                if total > 50_000_000:
                    raise RuntimeError("Allure history 解压后超过 50 MB")
                destination = target_root.joinpath(*parts).resolve()
                try:
                    destination.relative_to(target_root)
                except ValueError as exc:
                    raise RuntimeError("Allure history 中包含非法路径") from exc
                destination.parent.mkdir(parents=True, exist_ok=True)
                with source.open(member) as reader, destination.open("wb") as writer:
                    writer.write(reader.read(50_000_001))
    except zipfile.BadZipFile as exc:
        raise RuntimeError("平台返回的 Allure history 不是有效 ZIP") from exc
    print("已继承上一份 Allure history。")
    return 0


def _multipart(fields: dict[str, str], files: list[tuple[str, Path]]) -> tuple[bytes, str]:
    boundary = "----AutomationCallback" + uuid.uuid4().hex
    chunks: list[bytes] = []
    marker = boundary.encode("ascii")
    for name, value in fields.items():
        chunks.extend((b"--" + marker + b"\r\n", f'Content-Disposition: form-data; name="{name}"\r\n\r\n'.encode(), value.encode("utf-8"), b"\r\n"))
    total = 0
    for field, path in files:
        if not path.is_file():
            continue
        if field == "log" and path.stat().st_size > MAX_LOG_BYTES:
            data = _read_tail(path, MAX_LOG_BYTES)
        else:
            data = path.read_bytes()
        total += len(data)
        limit = MAX_LOG_BYTES if field == "log" else MAX_UPLOAD_BYTES
        if len(data) > limit or total > MAX_UPLOAD_BYTES:
            raise RuntimeError(f"回调附件超过大小限制：{path.name}")
        filename = path.name.replace('"', "_").replace("\\", "_")
        content_type = "application/zip" if path.suffix.lower() == ".zip" else "application/octet-stream"
        chunks.extend((
            b"--" + marker + b"\r\n",
            f'Content-Disposition: form-data; name="{field}"; filename="{filename}"\r\n'.encode(),
            f"Content-Type: {content_type}\r\n\r\n".encode(), data, b"\r\n",
        ))
    chunks.append(b"--" + marker + b"--\r\n")
    return b"".join(chunks), f"multipart/form-data; boundary={boundary}"


def _allure_stats(report_dir: Path) -> dict[str, int]:
    summary = report_dir / "widgets" / "summary.json"
    if not summary.is_file():
        return {}
    try:
        raw = json.loads(summary.read_text(encoding="utf-8"))
        statistic = raw.get("statistic", {})
        keys = ("total", "passed", "failed", "broken", "skipped", "unknown")
        return {key: int(statistic.get(key, 0) or 0) for key in keys}
    except (OSError, ValueError, TypeError):
        return {}


def _read_tail(path: Path, limit: int) -> bytes:
    """Read a bounded log tail, including when Jenkins produced a very large file."""
    with path.open("rb") as stream:
        stream.seek(0, os.SEEK_END)
        stream.seek(max(0, stream.tell() - limit))
        return stream.read(limit)


def _file_sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        while chunk := stream.read(1024 * 1024):
            digest.update(chunk)
    return digest.hexdigest()


def _valid_report_archive(path: Path) -> bool:
    """Only attach a generated Allure site when the archive has its root entry point."""
    try:
        if not path.is_file() or path.stat().st_size > MAX_UPLOAD_BYTES:
            return False
        with zipfile.ZipFile(path) as archive:
            members = archive.infolist()
            return len(members) <= 20_000 and any(member.filename == "index.html" for member in members)
    except (OSError, zipfile.BadZipFile):
        return False


def normalize_status(automation_status: str, jenkins_result: str) -> str:
    """Keep timeout/cancel intent explicit; an unknown Jenkins ABORTED is a failure."""
    requested = automation_status.strip().upper()
    result = jenkins_result.strip().upper()
    if requested in {"CANCELLED", "TIMEOUT", "FAILED", "FAILURE", "UNSTABLE", "ABORTED"}:
        return "FAILED" if requested in {"FAILURE", "UNSTABLE", "ABORTED"} else requested
    if result in {"FAILURE", "UNSTABLE", "ABORTED"}:
        return "FAILED"
    if result == "SUCCESS":
        return "SUCCESS"
    if requested == "SUCCESS":
        return "SUCCESS"
    return "FAILED"


def upload() -> int:
    callback_url, callback_key, secret, project_id = callback_settings()
    execution_id = os.environ.get("AUTOMATION_EXECUTION_ID", "").strip()
    if not execution_id.isdigit():
        raise ValueError("AUTOMATION_EXECUTION_ID 无效")
    report_path = Path(os.environ.get("AUTOMATION_REPORT_ARCHIVE", "allure-report.zip"))
    results_path = Path(os.environ.get("AUTOMATION_RESULTS_ARCHIVE", "allure-results.zip"))
    log_path = Path(os.environ.get("AUTOMATION_LOG_FILE", "run.log"))
    report_dir = Path(os.environ.get("AUTOMATION_REPORT_DIR", "allure-report"))
    started_ms = int(os.environ.get("AUTOMATION_START_MS", "0") or 0)
    duration = max(0, int(time.time() * 1000) - started_ms) if started_ms else 0
    jenkins_result = os.environ.get("JENKINS_RESULT", "").strip().upper()
    metadata_obj = {
        "execution_id": int(execution_id),
        "automation_project_id": int(project_id),
        "pipeline_id": os.environ.get("JOB_NAME", ""),
        "trigger_source": "MANUAL",
        "provider_type": "JENKINS",
        "build_number": int(os.environ["BUILD_NUMBER"]) if os.environ.get("BUILD_NUMBER", "").isdigit() else None,
        "build_url": os.environ.get("BUILD_URL", ""),
        "status": normalize_status(os.environ.get("AUTOMATION_STATUS", ""), jenkins_result),
        "jenkins_result": jenkins_result,
        "branch": os.environ.get("BRANCH_NAME", os.environ.get("GIT_BRANCH", "")),
        "environment": os.environ.get("TEST_ENV", ""),
        "git_commit": os.environ.get("GIT_COMMIT", ""),
        "duration_ms": duration,
        "started_at_ms": started_ms or None,
        "stats": _allure_stats(report_dir),
        "log_excerpt": _read_tail(log_path, 20_000).decode("utf-8", errors="replace") if log_path.is_file() else "",
    }
    metadata = json.dumps(metadata_obj, ensure_ascii=False, separators=(",", ":"))
    job_scope = hashlib.sha256(os.environ.get("JOB_NAME", "job").encode()).hexdigest()[:20]
    idempotency = f"jenkins:{job_scope}:{os.environ.get('BUILD_NUMBER', execution_id)}"
    fields = {"metadata": metadata}
    report_available = _valid_report_archive(report_path)
    if report_path.is_file() and not report_available:
        print("Allure HTML archive is incomplete or too large; uploading Results, logs, and execution metadata only.")
    files = ([ ("report", report_path) ] if report_available else []) + [
        ("results", results_path), ("log", log_path),
    ]

    def make_request():
        body, content_type = _multipart(fields, files)
        report_digest = _file_sha256(report_path) if report_available else sha(b"")
        headers = signed_headers(
            secret, callback_key, idempotency, b"", metadata, report_sha256=report_digest,
        )
        headers["Content-Type"] = content_type
        headers["Content-Length"] = str(len(body))
        return urllib.request.Request(callback_url, data=body, headers=headers, method="POST")

    response = retry_request(make_request)
    print("测开平台已确认 Jenkins 执行回调。")
    return 0


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("action", choices=("history", "upload"))
    args = parser.parse_args()
    try:
        return fetch_history() if args.action == "history" else upload()
    except (OSError, ValueError, RuntimeError, urllib.error.URLError) as exc:
        print(f"自动化平台回调失败：{exc}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
