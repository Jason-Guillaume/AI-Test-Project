"""整理已经导入的测试用例标题。

用法（在 backend/ 目录下）：
    .venv/bin/python scripts/optimize_case_titles.py
    .venv/bin/python scripts/optimize_case_titles.py --dry-run

只改当前 DATABASE_URL 指向的库。同一项目内名称必须唯一，
冲突时在标题后加「·序号」。改名会把 revision 加一，避免覆盖别人正在编辑的版本。
"""

from __future__ import annotations

import re
import sys
from pathlib import Path

BACKEND_DIR = Path(__file__).resolve().parents[1]
if str(BACKEND_DIR) not in sys.path:
    sys.path.insert(0, str(BACKEND_DIR))

from app.core.database.session import SessionLocal
# 用例外键指向这些表。不导入时，提交更新找不到目标表。
from app.agents.models.session import AgentSession  # noqa: F401
from app.core.models.identity import User  # noqa: F401
from app.core.models.project import Project  # noqa: F401
from app.features.api_catalog.models.api_interface import ApiInterface  # noqa: F401
from app.features.business.models.business_action import BusinessAction  # noqa: F401
from app.features.business.models.business_flow import BusinessFlow  # noqa: F401
from app.features.test_management.models.test_case import TestCase
from app.features.test_management.models.test_point import TestPoint  # noqa: F401
from app.features.test_management.titles import optimize_case_title

_DESCRIPTION_LIMIT = 1000
_ENDPOINT_RE = re.compile(r"(GET|POST|PUT|PATCH|DELETE)\s+\S+")


def endpoint_of(description: str | None) -> str:
    """从画布行取出请求方法和路径，用来区分同名但接口不同的用例。"""
    for line in (description or "").split("\n"):
        if line.startswith("画布"):
            matched = _ENDPOINT_RE.search(line)
            if matched:
                return matched.group(0)
    return ""


def allocate(base: str, used: set[str]) -> str:
    """在项目已占用的名称之外挑一个不超过 200 字的标题。"""
    if base not in used:
        used.add(base)
        return base
    for index in range(2, 100000):
        suffix = f"·{index}"
        candidate = base[: 200 - len(suffix)] + suffix
        if candidate not in used:
            used.add(candidate)
            return candidate
    raise RuntimeError(f"无法为「{base}」分配唯一名称")


def keep_pending_tail(case: TestCase) -> None:
    """待确认标题被截成第一句时，把分号后的说明放进描述。"""
    if not case.name.startswith("待确认"):
        return
    parts = re.split(r"[；;]", case.name, maxsplit=1)
    if len(parts) < 2:
        return
    rest = parts[1].strip()
    if not rest:
        return
    extra = f"补充：{rest}"
    current = case.description or ""
    if extra in current:
        return
    merged = f"{current}\n{extra}".strip()
    if len(merged) <= _DESCRIPTION_LIMIT:
        case.description = merged


def main() -> None:
    """按项目整理标题。--dry-run 只打印将要改的条数。"""
    dry_run = "--dry-run" in sys.argv
    db = SessionLocal()
    try:
        cases = db.query(TestCase).order_by(TestCase.project_id.asc(), TestCase.id.asc()).all()
        reserved: dict[int, set[str]] = {}
        pending: list[tuple[TestCase, str]] = []
        for case in cases:
            new_name = optimize_case_title(case.name)
            bucket = reserved.setdefault(case.project_id, set())
            if new_name == case.name:
                bucket.add(case.name)
            else:
                pending.append((case, new_name))
        changed = 0
        samples: list[tuple[str, str]] = []
        for case, new_name in pending:
            keep_pending_tail(case)
            chosen = new_name
            bucket = reserved[case.project_id]
            if chosen in bucket:
                hint = endpoint_of(case.description)
                hinted = f"{new_name}（{hint}）" if hint else ""
                if hinted and hinted not in bucket and len(hinted) <= 200:
                    chosen = hinted
            stored = allocate(chosen, bucket)
            if len(samples) < 8:
                samples.append((case.name, stored))
            case.name = stored
            case.revision = int(case.revision or 1) + 1
            changed += 1
        print(f"用例 {len(cases)}，标题改写 {changed}")
        for before, after in samples:
            print(f"- {before}")
            print(f"  → {after}")
        if dry_run:
            db.rollback()
            print("未写入")
            return
        db.commit()
        print("已写入")
    except Exception:
        db.rollback()
        raise
    finally:
        db.close()


if __name__ == "__main__":
    main()
