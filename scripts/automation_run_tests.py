"""Run pytest with a deliberately small, shell-free option allowlist for CI jobs."""

from __future__ import annotations

import os
import re
import shlex
import subprocess
import sys
from pathlib import Path

_ALLOWED_FLAGS = {
    "-q", "-v", "-x", "--disable-warnings", "--capture=no", "--tb=short", "--strict-markers",
}
_VALUE_FLAGS = {"--maxfail": re.compile(r"^[1-9][0-9]?$"), "-k": re.compile(r"^[A-Za-z0-9_ .:'\"()!&|=-]{1,200}$")}
_TAG_EXPR = re.compile(r"^[A-Za-z0-9_ .()!&|]{1,200}$")


def _scope_paths(raw: str, root: Path) -> list[str]:
    paths: list[str] = []
    for part in raw.split(","):
        target = part.strip()
        if not target:
            continue
        path_text = target.split("::", 1)[0]
        candidate = (root / path_text).resolve()
        if candidate != root and root not in candidate.parents:
            raise ValueError("TEST_SCOPE 必须位于仓库目录内")
        if not path_text or path_text.startswith("-"):
            raise ValueError("TEST_SCOPE 路径不合法")
        paths.append(target)
    return paths


def _pytest_args(raw: str) -> list[str]:
    tokens = shlex.split(raw, posix=True)
    result: list[str] = []
    index = 0
    while index < len(tokens):
        token = tokens[index]
        if token in _ALLOWED_FLAGS:
            result.append(token)
        elif token.startswith("--maxfail="):
            value = token.partition("=")[2]
            if not _VALUE_FLAGS["--maxfail"].fullmatch(value):
                raise ValueError("--maxfail 参数无效")
            result.append(token)
        elif token in _VALUE_FLAGS:
            if index + 1 >= len(tokens) or not _VALUE_FLAGS[token].fullmatch(tokens[index + 1]):
                raise ValueError(f"{token} 参数无效")
            result.extend((token, tokens[index + 1]))
            index += 1
        else:
            raise ValueError(f"pytest 参数不在允许列表中：{token}")
        index += 1
    return result


def build_command(root: Path, env: dict[str, str]) -> list[str]:
    command = [sys.executable, "-m", "pytest", "-q"]
    command.extend(_pytest_args(env.get("PYTEST_ARGS", "")))
    tags = env.get("TEST_TAGS", "").strip()
    if tags:
        if not _TAG_EXPR.fullmatch(tags):
            raise ValueError("TEST_TAGS 只允许 pytest marker 表达式字符")
        command.extend(("-m", tags))
    command.extend(_scope_paths(env.get("TEST_SCOPE", ""), root))
    command.append("--alluredir=allure-results")
    return command


def main() -> int:
    root = Path.cwd().resolve()
    try:
        command = build_command(root, dict(os.environ))
    except ValueError as exc:
        print(f"自动化测试参数无效：{exc}", file=sys.stderr)
        return 2
    print("运行 pytest（参数由平台白名单校验）")
    process = subprocess.Popen(
        command, cwd=root, stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
        env=os.environ.copy(),
    )
    tail = bytearray()
    assert process.stdout is not None
    while chunk := process.stdout.read(8192):
        sys.stdout.buffer.write(chunk)
        sys.stdout.buffer.flush()
        tail.extend(chunk)
        if len(tail) > 1_900_000:
            del tail[: len(tail) - 1_900_000]
    code = process.wait()
    Path("run.log").write_bytes(bytes(tail))
    return code


if __name__ == "__main__":
    raise SystemExit(main())
