#!/usr/bin/env python3
"""Validate the Jenkinsfile with Jenkins' Declarative Pipeline linter."""

from __future__ import annotations

import base64
import argparse
import os
import sys
import urllib.error
import urllib.parse
import urllib.request
from pathlib import Path


class NoRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, request, fp, code, message, headers, new_url):
        return None


def validate_static(source: str) -> list[str]:
    """Check required failure-closure steps before an optional live Jenkins lint."""
    required = {
        "Declarative Pipeline": "pipeline {",
        "post always closure": "always {",
        "pytest exit-code capture": "returnStatus: true, script: '.venv/bin/python scripts/automation_run_tests.py'",
        "Allure report generation": "allure generate allure-results --clean -o allure-report",
        "complete Allure entry point check": "fileExists('allure-report/index.html')",
        "callback upload": "python3 scripts/automation_callback.py upload",
        "Jenkins result metadata": "env.JENKINS_RESULT = currentBuild.currentResult",
        "platform timeout status": "timedOut ? 'TIMEOUT' : 'CANCELLED'",
    }
    errors = [f"Missing required {label}." for label, value in required.items() if value not in source]
    if 'error("pytest failed")' in source or "error('pytest failed')" in source:
        errors.append("pytest failure must not skip the Allure/callback post actions.")
    return errors


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--jenkins", action="store_true", help="also call the configured Jenkins Declarative linter")
    args = parser.parse_args()
    source = (Path(__file__).resolve().parents[1] / "Jenkinsfile").read_text(encoding="utf-8")
    errors = validate_static(source)
    if errors:
        print("Jenkins pipeline static contract failed:", file=sys.stderr)
        for error in errors:
            print(f"- {error}", file=sys.stderr)
        return 1
    print("Jenkins pipeline static failure-closure checks: valid.")
    if not args.jenkins:
        print("Jenkins syntax lint was not run; use --jenkins with configured Jenkins credentials.")
        return 0

    base_url = os.environ.get("JENKINS_BASE_URL", "").strip().rstrip("/")
    username = os.environ.get("JENKINS_USERNAME", "")
    token = os.environ.get("JENKINS_API_TOKEN", "")
    if not base_url or not username or not token:
        print("Set JENKINS_BASE_URL, JENKINS_USERNAME, and JENKINS_API_TOKEN in the environment.", file=sys.stderr)
        return 2
    parsed = urllib.parse.urlsplit(base_url)
    if parsed.scheme != "https" or not parsed.hostname or parsed.username or parsed.password or parsed.query or parsed.fragment:
        print("JENKINS_BASE_URL must be a clean HTTPS Jenkins origin and optional context path.", file=sys.stderr)
        return 2
    source = Path(__file__).resolve().parents[1] / "Jenkinsfile"
    endpoint = base_url + "/pipeline-model-converter/validate"
    credentials = base64.b64encode(f"{username}:{token}".encode()).decode("ascii")
    request = urllib.request.Request(
        endpoint,
        data=source.read_bytes(),
        headers={"Authorization": f"Basic {credentials}", "Content-Type": "text/plain; charset=utf-8"},
        method="POST",
    )
    opener = urllib.request.build_opener(NoRedirect)
    try:
        with opener.open(request, timeout=30) as response:
            result = response.read(20_000).decode("utf-8", errors="replace").strip()
    except urllib.error.HTTPError as exc:
        detail = exc.read(4000).decode("utf-8", errors="replace").strip()
        print(f"Jenkins Pipeline linter returned HTTP {exc.code}: {detail or 'no details'}", file=sys.stderr)
        return 1
    except (urllib.error.URLError, TimeoutError, OSError) as exc:
        print(f"Jenkins Pipeline linter request failed: {type(exc).__name__}", file=sys.stderr)
        return 1
    if "successfully validated" not in result.lower():
        print(result or "Jenkins Pipeline linter returned an empty response.", file=sys.stderr)
        return 1
    print("Jenkins Declarative Pipeline linter: valid.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
