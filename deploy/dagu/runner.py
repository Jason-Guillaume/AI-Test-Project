#!/usr/bin/env python3
"""Clone a Codeup repository, run pytest and return an Allure callback from Dagu."""

from __future__ import annotations

import hashlib
import fcntl
import json
import os
import platform
import re
import selectors
import shutil
import signal
import stat
import subprocess
import sys
import time
import zipfile
from pathlib import Path
from typing import BinaryIO
from urllib.parse import urlsplit

MAX_LOG_BYTES = 2_000_000
RUNNER_ROOT = Path(os.environ.get("AUTOMATION_RUNNER_ROOT", "/opt/automation-runner"))
RUN_ROOT = Path(os.environ.get("AUTOMATION_RUN_ROOT", "/opt/automation-runs"))
CACHE_ROOT = Path(os.environ.get("AUTOMATION_CACHE_ROOT", "/opt/automation-cache"))
CALLBACK_ROOT = Path(os.environ.get("AUTOMATION_CALLBACK_SECRET_ROOT", "/etc/dagu/automation-callback-secrets"))
CODEUP_KEY = Path("/etc/dagu/keys/codeup_automation")
GITHUB_KEY = Path("/etc/dagu/keys/github_automation")
CODEUP_KNOWN_HOSTS = Path("/etc/dagu/keys/known_hosts")
STOP_SIGNAL: int | None = None


def _load_helpers() -> tuple[object, Path]:
    """加载仓库内受控的 pytest 参数校验器和回调客户端。"""
    candidates = [RUNNER_ROOT, Path(__file__).resolve().parents[2] / "scripts"]
    helper_dir = next((path for path in candidates if (path / "automation_run_tests.py").is_file()), None)
    if helper_dir is None:
        raise RuntimeError("找不到 automation_run_tests.py；请将两个共享脚本部署到 runner 目录")
    sys.path.insert(0, str(helper_dir))
    import automation_run_tests  # type: ignore[import-not-found]

    callback_script = helper_dir / "automation_callback.py"
    if not callback_script.is_file():
        raise RuntimeError("找不到 automation_callback.py；请将两个共享脚本部署到 runner 目录")
    return automation_run_tests, callback_script


def _required_env(name: str, *, pattern: str | None = None, max_length: int = 500) -> str:
    """读取并验证必须的 Dagu 参数，拒绝空值、超长值和不符合格式的值。"""
    value = os.environ.get(name, "").strip()
    if not value or len(value) > max_length or any(ord(char) < 32 for char in value):
        raise ValueError(f"{name} 缺失或格式无效")
    if pattern and not re.fullmatch(pattern, value):
        raise ValueError(f"{name} 格式无效")
    return value


def _repository_ssh_url(value: str) -> str:
    """只接受 Codeup 或 GitHub，并把 HTTPS 地址映射到对应的只读 Deploy Key。"""
    for prefix, label in (("git@codeup.aliyun.com:", "Codeup"), ("git@github.com:", "GitHub")):
        if value.startswith(prefix):
            path = value.partition(":")[2]
            if not path or path.startswith("/") or ".." in path.split("/"):
                raise ValueError(f"{label} SSH 仓库路径无效")
            return value
    parsed = urlsplit(value)
    hosts = {"codeup.aliyun.com": "git@codeup.aliyun.com:", "github.com": "git@github.com:"}
    if (
        parsed.scheme not in {"https", "ssh"}
        or parsed.hostname not in hosts
        or parsed.username not in {None, "git"}
        or parsed.password or parsed.query or parsed.fragment
        or not parsed.path.strip("/")
        or ".." in parsed.path.split("/")
    ):
        raise ValueError("仓库地址必须是无凭据的 Codeup 或 GitHub HTTPS/SSH URL")
    return hosts[parsed.hostname] + parsed.path.lstrip("/")


def _deploy_key_for(repository_url: str) -> Path:
    """按仓库主机选择 Deploy Key 文件。命令行只放路径，不放私钥内容。"""
    if "github.com" in repository_url:
        return GITHUB_KEY
    return CODEUP_KEY


def _read_callback_credentials(config_id: str, origin: str) -> dict[str, str]:
    """从只允许 Dagu 用户读取的本机 JSON 文件取回调密钥并构造可信 HTTPS 地址。"""
    path = CALLBACK_ROOT / f"{config_id}.json"
    metadata = path.stat()
    if not stat.S_ISREG(metadata.st_mode) or stat.S_IMODE(metadata.st_mode) & 0o077:
        raise PermissionError("回调凭证文件必须是普通文件且权限不宽于 0400/0600")
    credentials = json.loads(path.read_text(encoding="utf-8"))
    callback_key = str(credentials.get("callback_key") or "").strip()
    callback_secret = str(credentials.get("callback_secret") or "")
    parsed = urlsplit(origin.rstrip("/"))
    if (
        parsed.scheme != "https" or not parsed.hostname or parsed.username or parsed.password
        or parsed.path or parsed.query or parsed.fragment
        or not re.fullmatch(r"[A-Za-z0-9_-]{8,64}", callback_key)
        or len(callback_secret) < 8
    ):
        raise ValueError("回调凭证文件或可信 HTTPS Origin 配置无效")
    callback_url = f"{origin.rstrip('/')}/api/v1/automation-callbacks/{callback_key}"
    return {
        "AUTOMATION_CALLBACK_KEY": callback_key,
        "AUTOMATION_CALLBACK_SECRET": callback_secret,
        "AUTOMATION_CALLBACK_URL": callback_url,
        "AUTOMATION_CALLBACK_ORIGIN": origin.rstrip("/"),
    }


def _append_log(log_path: Path, chunk: bytes) -> None:
    """追加一段日志并将文件限制在最近两兆字节，同时原样输出到 Dagu 日志。"""
    if not chunk:
        return
    sys.stdout.buffer.write(chunk)
    sys.stdout.buffer.flush()
    with log_path.open("r+b") as stream:
        stream.seek(0, os.SEEK_END)
        size = stream.tell()
        if size + len(chunk) > MAX_LOG_BYTES:
            stream.seek(max(0, size - MAX_LOG_BYTES // 2))
            tail = stream.read()
            retained = (tail + chunk)[-MAX_LOG_BYTES:]
            stream.seek(0)
            stream.write(retained)
            stream.truncate()
        else:
            stream.write(chunk)
        stream.flush()


def _run_command(
    args: list[str], *, cwd: Path, env: dict[str, str], log_path: Path,
    timeout_seconds: int, label: str, honor_stop: bool = True,
) -> int:
    """以参数数组运行子进程、实时保存有界日志，并在超时或终止信号时结束整个进程组。"""
    global STOP_SIGNAL
    _append_log(log_path, f"\n--- {label} ---\n$ {args[0]} [参数已省略]\n".encode())
    try:
        process = subprocess.Popen(
            args, cwd=cwd, env=env, stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
            start_new_session=True,
        )
    except OSError as exc:
        _append_log(log_path, f"启动 {label} 失败：{type(exc).__name__}\n".encode())
        return 127
    assert process.stdout is not None
    selector = selectors.DefaultSelector()
    selector.register(process.stdout, selectors.EVENT_READ)
    deadline = time.monotonic() + timeout_seconds
    while True:
        if honor_stop and STOP_SIGNAL is not None:
            stop_code = 128 + STOP_SIGNAL
            _append_log(log_path, f"收到停止信号 {STOP_SIGNAL}，正在结束 {label}\n".encode())
            break
        if time.monotonic() >= deadline:
            stop_code = 124
            _append_log(log_path, f"{label} 超过 {timeout_seconds} 秒限时\n".encode())
            break
        events = selector.select(timeout=0.25)
        if events:
            chunk = process.stdout.read1(8192)
            if chunk:
                _append_log(log_path, chunk)
                continue
        if process.poll() is not None:
            selector.close()
            return int(process.returncode or 0)
    selector.close()
    try:
        os.killpg(process.pid, signal.SIGTERM)
        process.wait(timeout=10)
    except (ProcessLookupError, subprocess.TimeoutExpired):
        try:
            os.killpg(process.pid, signal.SIGKILL)
        except ProcessLookupError:
            pass
        process.wait()
    return stop_code


def _make_archive(source: Path, target: Path, *, flatten: bool = False) -> bool:
    """创建 ZIP 并校验 CRC；报告压缩包必须含根目录 index.html。"""
    if not source.is_dir():
        return False
    files = [path for path in source.rglob("*") if path.is_file() and not path.is_symlink()]
    if not files:
        return False
    with zipfile.ZipFile(target, "w", compression=zipfile.ZIP_DEFLATED, compresslevel=6) as archive:
        for path in files:
            archive.write(path, path.relative_to(source) if flatten else Path(source.name) / path.relative_to(source))
    try:
        with zipfile.ZipFile(target) as archive:
            if archive.testzip() is not None:
                return False
            if flatten and "index.html" not in archive.namelist():
                return False
    except zipfile.BadZipFile:
        return False
    return target.stat().st_size <= 180_000_000


def _cleanup_expired_runs(root: Path, *, retention_days: int = 7) -> None:
    """仅删除带成功回调标记且超过保留期的工作区，保留失败现场供恢复。"""
    expiry = time.time() - retention_days * 86_400
    for marker in root.glob("*/.callback-ok"):
        work_dir = marker.parent
        if work_dir.is_symlink() or not marker.is_file() or marker.stat().st_mtime >= expiry:
            continue
        try:
            work_dir.resolve().relative_to(root.resolve())
        except ValueError:
            continue
        shutil.rmtree(work_dir)


def _dependency_manifest(repo_dir: Path) -> Path | None:
    """选择仓库依赖清单，以确定可复用的隔离 Python 环境。"""
    return next((path for path in (
        repo_dir / "requirements.txt", repo_dir / "backend" / "requirements.txt",
    ) if path.is_file()), None)


def _environment_cache_key(manifest: Path | None) -> str:
    """依赖缓存只跟解释器、系统和依赖清单有关，代码提交变化不重新安装。"""
    digest = hashlib.sha256()
    digest.update(platform.python_version().encode("utf-8"))
    digest.update(sys.version.encode("utf-8"))
    digest.update(platform.system().encode("utf-8"))
    digest.update(platform.machine().encode("utf-8"))
    digest.update(manifest.read_bytes() if manifest is not None else b"<no-requirements>")
    digest.update(b"\0pytest\0allure-pytest")
    return digest.hexdigest()[:24]


def _cleanup_expired_venvs(active_key: str | None = None) -> None:
    """删除过期虚拟环境。拿不到独占锁的目录视为正在使用，不能删。"""
    root = CACHE_ROOT / "venvs"
    if not root.is_dir():
        return
    expiry = time.time() - 14 * 86_400
    for ready in root.glob("*/.ready"):
        venv_dir = ready.parent
        if venv_dir.name.startswith(".") or ready.stat().st_mtime >= expiry:
            continue
        try:
            cache_key = ready.read_text(encoding="ascii").strip()[:24]
        except OSError:
            continue
        if not cache_key or cache_key == active_key:
            continue
        lock_path = CACHE_ROOT / "locks" / f"{cache_key}.lock"
        lock_path.parent.mkdir(parents=True, exist_ok=True)
        lock_file = lock_path.open("a+b")
        try:
            fcntl.flock(lock_file.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError:
            lock_file.close()
            continue
        try:
            if venv_dir.exists() and not venv_dir.is_symlink():
                shutil.rmtree(venv_dir)
        finally:
            fcntl.flock(lock_file.fileno(), fcntl.LOCK_UN)
            lock_file.close()


def _ensure_disk_budget(root: Path) -> None:
    """剩余空间过低时拒绝新的执行，避免多个任务把磁盘写满。"""
    root.mkdir(parents=True, exist_ok=True)
    minimum_free = int(os.environ.get("AUTOMATION_MIN_FREE_BYTES", str(1024 ** 3)))
    if shutil.disk_usage(root).free < minimum_free:
        raise RuntimeError("执行机剩余磁盘不足，已拒绝本次运行")


def _acquire_run_slot() -> BinaryIO:
    """用文件锁限制同时运行的任务数，锁在进程退出时释放。"""
    slots = int(os.environ.get("AUTOMATION_MAX_CONCURRENT", "2") or "2")
    slot_root = RUN_ROOT / "slots"
    slot_root.mkdir(parents=True, exist_ok=True, mode=0o700)
    last_error: BlockingIOError | None = None
    for index in range(max(1, min(slots, 8))):
        handle = (slot_root / f"slot-{index}").open("a+b")
        try:
            fcntl.flock(handle.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
            return handle
        except BlockingIOError as exc:
            last_error = exc
            handle.close()
    raise RuntimeError("执行机并发已满，请稍后重试") from last_error


def _cached_python(repo_dir: Path, log_path: Path, env: dict[str, str]) -> tuple[Path, BinaryIO]:
    """缓存 venv 并持有共享运行锁，避免定时清理删除正在使用的环境。"""
    manifest = _dependency_manifest(repo_dir)
    cache_key = _environment_cache_key(manifest)
    _cleanup_expired_venvs(cache_key)
    venv_dir = CACHE_ROOT / "venvs" / cache_key
    cache_python = venv_dir / "bin" / "python"
    lock_root = CACHE_ROOT / "locks"
    pip_cache = CACHE_ROOT / "pip"
    for directory in (CACHE_ROOT, CACHE_ROOT / "venvs", lock_root, pip_cache):
        directory.mkdir(parents=True, exist_ok=True, mode=0o700)
        os.chmod(directory, 0o700)
    cache_env = {**env, "PIP_CACHE_DIR": str(pip_cache)}
    lock_path = lock_root / f"{cache_key}.lock"
    lock_file = lock_path.open("a+b")
    try:
        os.chmod(lock_path, 0o600)
        ready = venv_dir / ".ready"
        while True:
            if STOP_SIGNAL is not None:
                raise RuntimeError("等待依赖环境时收到停止信号")
            try:
                fcntl.flock(lock_file.fileno(), fcntl.LOCK_SH | fcntl.LOCK_NB)
            except BlockingIOError:
                time.sleep(0.1)
                continue
            if cache_python.is_file() and ready.is_file():
                os.utime(ready, None)
                return cache_python, lock_file
            # Competing cold starts must recheck readiness as readers after construction.
            fcntl.flock(lock_file.fileno(), fcntl.LOCK_UN)
            try:
                fcntl.flock(lock_file.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
            except BlockingIOError:
                time.sleep(0.1)
                continue
            if not (cache_python.is_file() and ready.is_file()):
                break
            fcntl.flock(lock_file.fileno(), fcntl.LOCK_SH)
            return cache_python, lock_file
        staging = CACHE_ROOT / "venvs" / f".{cache_key}.{os.getpid()}.tmp"
        if staging.exists():
            shutil.rmtree(staging)
        create_code = _run_command(
            [sys.executable, "-m", "venv", str(staging)], cwd=repo_dir, env=cache_env,
            log_path=log_path, timeout_seconds=300, label="创建共享依赖环境",
        )
        if create_code != 0:
            shutil.rmtree(staging, ignore_errors=True)
            raise RuntimeError("Python 虚拟环境创建失败")
        staging_python = staging / "bin" / "python"
        pip_args = [str(staging_python), "-m", "pip", "install", "--disable-pip-version-check", "--no-input"]
        if manifest:
            pip_args.extend(["-r", str(manifest)])
        pip_args.extend(["pytest", "allure-pytest"])
        install_code = _run_command(
            pip_args, cwd=repo_dir, env=cache_env, log_path=log_path,
            timeout_seconds=2700, label="安装仓库依赖和 Allure pytest 插件",
        )
        if install_code != 0:
            shutil.rmtree(staging, ignore_errors=True)
            raise RuntimeError("依赖安装失败")
        (staging / ".ready").write_text(cache_key, encoding="ascii")
        os.chmod(staging / ".ready", 0o600)
        if venv_dir.exists():
            shutil.rmtree(venv_dir)
        os.replace(staging, venv_dir)
        fcntl.flock(lock_file.fileno(), fcntl.LOCK_SH)
        return cache_python, lock_file
    except BaseException:
        lock_file.close()
        raise


def _deliver_result(work_dir: Path, callback_script: Path, env: dict[str, str]) -> int:
    """Deliver a completed run once and return its original execution result on replay."""
    with (work_dir / ".callback.lock").open("a+b") as lock:
        fcntl.flock(lock.fileno(), fcntl.LOCK_EX)
        result = json.loads((work_dir / ".result.json").read_text(encoding="utf-8"))
        exit_code = int(result["exit_code"])
        marker = work_dir / ".callback-ok"
        if marker.is_file():
            return exit_code
        upload_env = {
            **env,
            "AUTOMATION_STATUS": result["status"],
            "AUTOMATION_START_MS": str(result["started_ms"]),
            "AUTOMATION_FINISH_MS": str(result["finished_ms"]),
            "GIT_COMMIT": result["git_commit"],
        }
        upload_code = _run_command(
            [sys.executable, str(callback_script), "upload"], cwd=work_dir, env=upload_env,
            log_path=work_dir / "run.log", timeout_seconds=120,
            label="签名上传 Allure 与运行状态", honor_stop=False,
        )
        if upload_code:
            _append_log(work_dir / "run.log", "回调未确认；重试本次运行可补传。\n".encode())
            return exit_code or 1
        marker.touch(mode=0o600)
        return exit_code


def main() -> int:
    """执行单次 Dagu 运行：检出、装依赖、取 history、pytest、Allure 和签名回调。"""
    global STOP_SIGNAL
    automation_runner, callback_script = _load_helpers()
    execution_id = _required_env("AUTOMATION_EXECUTION_ID", pattern=r"[1-9][0-9]{0,18}", max_length=19)
    project_id = _required_env("AUTOMATION_PROJECT_ID", pattern=r"[1-9][0-9]{0,18}", max_length=19)
    config_id = _required_env("INTEGRATION_CONFIG_ID", pattern=r"[1-9][0-9]{0,18}", max_length=19)
    dag_run_id = _required_env("DAG_RUN_ID", pattern=r"[A-Za-z0-9_.-]{1,64}", max_length=64)
    repository_url = _repository_ssh_url(_required_env("REPOSITORY_URL", max_length=500))
    branch = _required_env("BRANCH_NAME", pattern=r"[A-Za-z0-9._/-]{1,200}", max_length=200)
    if branch.startswith("-") or ".." in branch or "//" in branch or "@{" in branch:
        raise ValueError("BRANCH_NAME 不合法")
    timeout_seconds = int(_required_env("TIMEOUT_SECONDS", pattern=r"[0-9]{1,5}", max_length=5))
    if not 60 <= timeout_seconds <= 10_800:
        raise ValueError("TIMEOUT_SECONDS 必须在 60 到 10800 秒之间")
    callback_origin = _required_env("AUTOMATION_CALLBACK_ORIGIN", max_length=300)
    callback_env = _read_callback_credentials(config_id, callback_origin)
    callback_env.update({
        "AUTOMATION_EXECUTION_ID": execution_id,
        "AUTOMATION_PROJECT_ID": project_id,
        "AUTOMATION_PROVIDER_TYPE": "DAGU",
        "AUTOMATION_PIPELINE_ID": os.environ.get("AUTOMATION_PIPELINE_ID", "automation-pytest-allure")[:200],
        "DAG_RUN_ID": dag_run_id,
        "BRANCH_NAME": branch,
        "TEST_ENV": os.environ.get("TEST_ENV", "")[:100],
        "AUTOMATION_START_MS": str(int(time.time() * 1000)),
        "AUTOMATION_CALLBACK_SECRET_ROOT": str(CALLBACK_ROOT),
    })

    RUN_ROOT.mkdir(parents=True, exist_ok=True, mode=0o700)
    os.chmod(RUN_ROOT, 0o700)
    _cleanup_expired_runs(RUN_ROOT)
    run_key = hashlib.sha256(dag_run_id.encode("utf-8")).hexdigest()[:12]
    work_dir = RUN_ROOT / f"{execution_id}-{run_key}"
    repo_dir = work_dir / "repository"
    log_path = work_dir / "run.log"
    callback_env.update({
        "AUTOMATION_LOG_FILE": str(log_path),
        "AUTOMATION_REPORT_ARCHIVE": str(work_dir / "allure-report.zip"),
        "AUTOMATION_RESULTS_ARCHIVE": str(work_dir / "allure-results.zip"),
        "AUTOMATION_REPORT_DIR": str(repo_dir / "allure-report"),
    })
    temp_root = work_dir / "tmp"
    env = {
        "PATH": os.environ.get("PATH", "/usr/local/bin:/usr/bin:/bin"),
        "HOME": str(work_dir),
        "TMPDIR": str(temp_root),
        "LANG": "C.UTF-8",
        "LC_ALL": "C.UTF-8",
    }
    env.update({
        "GIT_SSH_COMMAND": (
            f"ssh -i {_deploy_key_for(repository_url)} -o IdentitiesOnly=yes -o StrictHostKeyChecking=yes "
            f"-o UserKnownHostsFile={CODEUP_KNOWN_HOSTS}"
        ),
        "GIT_TERMINAL_PROMPT": "0",
        "AUTOMATION_EXECUTION_ID": execution_id,
        "AUTOMATION_PROJECT_ID": project_id,
        "AUTOMATION_PROVIDER_TYPE": "DAGU",
        "DAG_RUN_ID": dag_run_id,
        "BRANCH_NAME": branch,
        "TEST_ENV": callback_env["TEST_ENV"],
        "PYTEST_ARGS": os.environ.get("PYTEST_ARGS", "")[:500],
        "TEST_TAGS": os.environ.get("TEST_TAGS", "")[:300],
        "TEST_SCOPE": os.environ.get("TEST_SCOPE", "")[:500],
    })
    signal.signal(signal.SIGTERM, lambda signum, _frame: _record_signal(signum))
    signal.signal(signal.SIGINT, lambda signum, _frame: _record_signal(signum))
    if work_dir.exists():
        if (work_dir / ".result.json").is_file():
            return _deliver_result(work_dir, callback_script, {**env, **callback_env, "AUTOMATION_CALLBACK_REPLAY": "1"})
        raise RuntimeError(f"运行目录缺少可恢复的执行结果，请核对原运行：{work_dir}")
    work_dir.mkdir(mode=0o700)
    log_path.touch(mode=0o600)
    temp_root.mkdir(mode=0o700)
    result_code = 0
    status = "FAILED"
    cache_lock: BinaryIO | None = None
    _ensure_disk_budget(RUN_ROOT)
    run_slot = _acquire_run_slot()
    try:
        clone_env = {**env, "GIT_CONFIG_NOSYSTEM": "1"}
        clone_code = _run_command(
            ["git", "clone", "--depth=1", "--single-branch", "--branch", branch, "--", repository_url, str(repo_dir)],
            cwd=work_dir, env=clone_env, log_path=log_path, timeout_seconds=900, label="检出 Codeup 仓库",
        )
        if clone_code != 0:
            result_code = clone_code
            raise _RunFailed("Codeup 仓库检出失败")
        git_commit = subprocess.run(
            ["git", "rev-parse", "HEAD"], cwd=repo_dir, env=clone_env,
            check=True, capture_output=True, text=True, timeout=15,
        ).stdout.strip()
        callback_env["GIT_COMMIT"] = git_commit[:64]
        venv_python, cache_lock = _cached_python(repo_dir, log_path, env)
        venv_dir = venv_python.parent.parent

        child_env = env.copy()
        for key in (
            "AUTOMATION_CALLBACK_KEY", "AUTOMATION_CALLBACK_SECRET", "AUTOMATION_CALLBACK_URL",
            "AUTOMATION_CALLBACK_ORIGIN", "AUTOMATION_CALLBACK_SECRET_ROOT",
        ):
            child_env.pop(key, None)
        history_env = {**child_env, **callback_env}
        history_code = _run_command(
            [sys.executable, str(callback_script), "history"], cwd=repo_dir, env=history_env,
            log_path=log_path, timeout_seconds=180, label="读取上次 Allure history",
        )
        if history_code != 0:
            _append_log(log_path, "读取 Allure history 失败；继续执行并生成本次报告。\n".encode("utf-8"))

        test_env = child_env.copy()
        test_env["PATH"] = f"{venv_dir / 'bin'}:{test_env.get('PATH', '')}"
        command = automation_runner.build_command(repo_dir, test_env)
        command[0] = str(venv_python)
        pytest_code = _run_command(
            command, cwd=repo_dir, env=test_env, log_path=log_path,
            timeout_seconds=timeout_seconds, label="运行 pytest",
        )
        if STOP_SIGNAL is not None:
            status = "CANCELLED"
            result_code = pytest_code
        elif pytest_code == 124:
            status = "TIMEOUT"
            result_code = pytest_code
        elif pytest_code != 0:
            status = "FAILED"
            result_code = pytest_code
        else:
            status = "SUCCESS"
            result_code = 0
    except _RunFailed:
        status = "FAILED"
    except (OSError, ValueError, RuntimeError, subprocess.SubprocessError) as exc:
        _append_log(log_path, f"Runner 阶段失败：{type(exc).__name__}: {exc}\n".encode("utf-8", errors="replace"))
        status = "FAILED"
        result_code = result_code or 1
    finally:
        if cache_lock is not None:
            cache_lock.close()
            cache_lock = None
        try:
            if STOP_SIGNAL is not None and status not in {"TIMEOUT", "CANCELLED"}:
                status = "CANCELLED"
            allure_results = repo_dir / "allure-results"
            allure_report = repo_dir / "allure-report"
            if allure_results.is_dir() and any(allure_results.iterdir()):
                allure_bin = shutil.which("allure")
                if allure_bin:
                    allure_code = _run_command(
                        [allure_bin, "generate", str(allure_results), "--clean", "-o", str(allure_report)],
                        cwd=repo_dir, env=child_env if "child_env" in locals() else env,
                        log_path=log_path, timeout_seconds=900, label="生成 Allure HTML 报告",
                    )
                    if allure_code != 0 and status not in {"CANCELLED", "TIMEOUT"}:
                        status = "FAILED"
                        result_code = result_code or allure_code
                else:
                    _append_log(log_path, "未安装 Allure CLI，不能伪造 HTML 报告。\n".encode("utf-8"))
                    if status not in {"CANCELLED", "TIMEOUT"}:
                        status = "FAILED"
                        result_code = result_code or 1
            else:
                _append_log(log_path, "pytest 未生成 Allure 结果，不能创建报告。\n".encode("utf-8"))
                if status not in {"CANCELLED", "TIMEOUT"}:
                    status = "FAILED"
                    result_code = result_code or 1

            if allure_results.is_dir() and any(allure_results.iterdir()):
                if not _make_archive(allure_results, work_dir / "allure-results.zip"):
                    _append_log(log_path, "Allure results 压缩包校验失败。\n".encode("utf-8"))
                    if status not in {"CANCELLED", "TIMEOUT"}:
                        status = "FAILED"
                    result_code = result_code or 1
            report_available = allure_report.is_dir() and (allure_report / "index.html").is_file()
            if report_available:
                if not _make_archive(allure_report, work_dir / "allure-report.zip", flatten=True):
                    _append_log(log_path, "Allure HTML 压缩包校验失败。\n".encode("utf-8"))
                    if status not in {"CANCELLED", "TIMEOUT"}:
                        status = "FAILED"
                    result_code = result_code or 1
            elif status not in {"CANCELLED", "TIMEOUT"}:
                _append_log(log_path, "Allure HTML 报告缺少有效的 index.html。\n".encode("utf-8"))
                status = "FAILED"
                result_code = result_code or 1

            if STOP_SIGNAL is not None and status != "TIMEOUT":
                status = "CANCELLED"
                result_code = 128 + STOP_SIGNAL
            result = {
                "status": status, "exit_code": result_code,
                "started_ms": int(callback_env["AUTOMATION_START_MS"]),
                "finished_ms": int(time.time() * 1000),
                "git_commit": callback_env.get("GIT_COMMIT", ""),
            }
            staging = work_dir / ".result.tmp"
            staging.write_text(json.dumps(result), encoding="utf-8")
            staging.replace(work_dir / ".result.json")
            result_code = _deliver_result(work_dir, callback_script, {**env, **callback_env})
        finally:
            run_slot.close()
    return result_code


class _RunFailed(RuntimeError):
    """用于结束流水线阶段并继续生成失败回调。"""


def _record_signal(signum: int) -> None:
    """记录 Dagu 的停止信号，交由当前子进程收尾并上报取消状态。"""
    global STOP_SIGNAL
    STOP_SIGNAL = signum


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except (OSError, PermissionError, ValueError, RuntimeError, KeyError) as exc:
        print(f"Dagu runner 初始化失败：{type(exc).__name__}: {exc}", file=sys.stderr)
        raise SystemExit(2)
