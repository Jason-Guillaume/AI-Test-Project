"""Dagu runner cache, workspace retention and credential file checks."""

from __future__ import annotations

import importlib.util
import json
import os
import time
from pathlib import Path


def _runner_module():
    """Load the deployment runner so its filesystem safeguards can be exercised locally."""
    path = Path(__file__).resolve().parents[2] / "deploy" / "dagu" / "runner.py"
    spec = importlib.util.spec_from_file_location("automation_dagu_runner_test", path)
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_dependency_environment_is_cached_across_runs(tmp_path, monkeypatch):
    """Create the venv and install packages once for a matching repository manifest."""
    runner = _runner_module()
    repo = tmp_path / "repo"
    repo.mkdir()
    (repo / "requirements.txt").write_text("httpx==0.28.0\n", encoding="utf-8")
    cache_root = tmp_path / "cache"
    monkeypatch.setattr(runner, "CACHE_ROOT", cache_root)
    log_path = tmp_path / "run.log"
    log_path.touch()
    calls = []
    environments = []

    def fake_run(args, **kwargs):
        calls.append(args)
        environments.append(kwargs["env"])
        if args[1:3] == ["-m", "venv"]:
            environment = Path(args[-1])
            (environment / "bin").mkdir(parents=True)
            (environment / "bin" / "python").touch()
        return 0

    monkeypatch.setattr(runner, "_run_command", fake_run)
    first, first_lock = runner._cached_python(repo, log_path, {})
    first_lock.close()
    second, second_lock = runner._cached_python(repo, log_path, {})
    second_lock.close()
    assert first == second
    assert len(calls) == 2
    (repo / "requirements.txt").write_text("httpx==0.27.0\n", encoding="utf-8")
    third, third_lock = runner._cached_python(repo, log_path, {})
    third_lock.close()
    assert third != first
    assert len(calls) == 4
    assert all("PIP_CACHE_DIR" in environment for environment in environments)
    assert runner._repository_ssh_url("https://github.com/org/repo.git") == "git@github.com:org/repo.git"


def test_cleanup_removes_only_expired_successful_workspaces(tmp_path):
    """Preserve failed/manual recovery directories while expiring acknowledged successes."""
    runner = _runner_module()
    root = tmp_path / "runs"
    successful = root / "12-abcdef123456"
    failed = root / "13-fedcba654321"
    successful.mkdir(parents=True)
    failed.mkdir()
    marker = successful / ".callback-ok"
    marker.write_text("ok", encoding="utf-8")
    old_time = time.time() - 8 * 86_400
    os.utime(marker, (old_time, old_time))
    runner._cleanup_expired_runs(root)
    assert not successful.exists()
    assert failed.is_dir()


def test_repository_and_callback_credentials_are_host_scoped(tmp_path, monkeypatch):
    """Accept only the Codeup host and read callback secrets from a private HTTPS setup."""
    runner = _runner_module()
    assert runner._repository_ssh_url("https://codeup.aliyun.com/team/repo.git") == "git@codeup.aliyun.com:team/repo.git"
    credentials_root = tmp_path / "credentials"
    credentials_root.mkdir()
    monkeypatch.setattr(runner, "CALLBACK_ROOT", credentials_root)
    credentials = credentials_root / "7.json"
    credentials.write_text(json.dumps({"callback_key": "callback_1234", "callback_secret": "callback-secret-value"}), encoding="utf-8")
    credentials.chmod(0o400)
    result = runner._read_callback_credentials("7", "https://platform.example.com")
    assert result["AUTOMATION_CALLBACK_URL"].endswith("/api/v1/automation-callbacks/callback_1234")
    assert result["AUTOMATION_CALLBACK_SECRET"] == "callback-secret-value"
    try:
        runner._repository_ssh_url("https://example.com/team/repo.git")
    except ValueError:
        pass
    else:
        raise AssertionError("non-Codeup repository URL was accepted")


def test_cached_environment_can_be_used_while_first_run_still_holds_lock(tmp_path, monkeypatch):
    from concurrent.futures import ThreadPoolExecutor

    runner = _runner_module()
    monkeypatch.setattr(runner, "CACHE_ROOT", tmp_path / "cache")
    target = runner.CACHE_ROOT / "venvs" / runner._environment_cache_key(None)
    (target / "bin").mkdir(parents=True)
    (target / "bin" / "python").touch()
    (target / ".ready").touch()
    _, first = runner._cached_python(tmp_path, tmp_path / "run.log", {})
    with ThreadPoolExecutor(max_workers=1) as pool:
        second = pool.submit(runner._cached_python, tmp_path, tmp_path / "run.log", {})
        try:
            path, lock = second.result(timeout=2)
            lock.close()
            assert path == target / "bin" / "python"
        finally:
            first.close()


def test_cancelled_run_uploads_and_replays_original_exit_code(tmp_path, monkeypatch):
    import signal

    runner = _runner_module()
    script = tmp_path / "callback.py"
    script.write_text(
        "import os\nfrom pathlib import Path\n"
        "with Path('attempts').open('a') as f: f.write(os.environ['AUTOMATION_STATUS'] + '\\n')\n"
        "raise SystemExit(0 if Path('online').exists() else 1)\n"
    )
    work = tmp_path / "work"
    work.mkdir()
    (work / "run.log").touch()
    (work / ".result.json").write_text(json.dumps({
        "status": "CANCELLED", "exit_code": 143, "started_ms": 10, "finished_ms": 20, "git_commit": "abc",
    }))
    monkeypatch.setattr(runner, "STOP_SIGNAL", signal.SIGTERM)
    assert runner._deliver_result(work, script, {}) == 143
    assert not (work / ".callback-ok").exists()
    (work / "online").touch()
    assert runner._deliver_result(work, script, {}) == 143
    assert (work / ".callback-ok").is_file()
    assert runner._deliver_result(work, script, {}) == 143
    assert (work / "attempts").read_text().splitlines() == ["CANCELLED", "CANCELLED"]


def test_main_retries_upload_without_repeating_failed_checkout(tmp_path, monkeypatch):
    runner = _runner_module()
    monkeypatch.setattr(runner, "RUN_ROOT", tmp_path / "runs")
    monkeypatch.setattr(runner, "_load_helpers", lambda: (None, tmp_path / "callback.py"))
    monkeypatch.setattr(runner, "_read_callback_credentials", lambda *_: {})
    monkeypatch.setattr(runner.signal, "signal", lambda *_: None)
    for key, value in {
        "AUTOMATION_EXECUTION_ID": "1", "AUTOMATION_PROJECT_ID": "2", "INTEGRATION_CONFIG_ID": "3",
        "DAG_RUN_ID": "automation-1", "BRANCH_NAME": "main", "TIMEOUT_SECONDS": "60",
        "AUTOMATION_CALLBACK_ORIGIN": "https://platform.example.com",
        "REPOSITORY_URL": "https://github.com/team/repo.git", "AUTOMATION_MIN_FREE_BYTES": "0",
    }.items():
        monkeypatch.setenv(key, value)
    commands = []
    def run(args, **kwargs):
        commands.append(args)
        if args[0] == "git":
            return 42
        assert args[-1] == "upload"
        assert kwargs["env"]["AUTOMATION_STATUS"] == "FAILED"
        assert not kwargs["honor_stop"]
        return 1 if len(commands) == 2 else 0

    monkeypatch.setattr(runner, "_run_command", run)
    assert runner.main() == 42
    assert runner.main() == 42
    assert runner.main() == 42
    assert len(commands) == 3
