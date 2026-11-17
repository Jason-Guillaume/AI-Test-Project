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
