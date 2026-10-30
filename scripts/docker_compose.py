#!/usr/bin/env python3
"""Run Docker Compose with PostgreSQL initialization values derived from backend/.env."""

from __future__ import annotations

import os
import subprocess
import sys
from pathlib import Path
from urllib.parse import unquote, urlsplit


ROOT = Path(__file__).resolve().parents[1]


def read_env_file(path: Path) -> dict[str, str]:
    values: dict[str, str] = {}
    for raw_line in path.read_text(encoding="utf-8").splitlines():
        line = raw_line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, value = line.split("=", 1)
        value = value.strip()
        if len(value) >= 2 and value[0] == value[-1] and value[0] in {"'", '"'}:
            value = value[1:-1]
        values[key.strip()] = value
    return values


def main() -> int:
    env_path = ROOT / "backend" / ".env"
    settings = read_env_file(env_path)
    database_url = settings.get("DATABASE_URL", "")
    if not database_url:
        print("backend/.env must define DATABASE_URL before starting Docker Compose.", file=sys.stderr)
        return 2

    parsed = urlsplit(database_url)
    if not parsed.hostname or not parsed.username or parsed.password is None:
        print("DATABASE_URL must include a PostgreSQL host, user, and password.", file=sys.stderr)
        return 2

    env = os.environ.copy()
    env.update(
        {
            "POSTGRES_USER": unquote(parsed.username),
            "POSTGRES_PASSWORD": unquote(parsed.password),
            "POSTGRES_DB": unquote(parsed.path.lstrip("/")),
        }
    )
    command = ["docker", "compose", "-f", str(ROOT / "compose.yaml"), *sys.argv[1:]]
    return subprocess.run(command, cwd=ROOT, env=env, check=False).returncode


if __name__ == "__main__":
    raise SystemExit(main())
