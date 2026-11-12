"""从测试用例反向登记接口目录。

用法（在 backend/ 目录下）：
    .venv/bin/python scripts/build_catalog_from_cases.py --dry-run   # 先预览
    .venv/bin/python scripts/build_catalog_from_cases.py             # 确认后写入
    .venv/bin/python scripts/build_catalog_from_cases.py --project-id 1

背景：方小集/方小址的用例已导入，但接口管理里没有这些项目的接口，
用例库对不上接口名、覆盖矩阵的接口数也是 0。业务系统的 OpenAPI 文档不在手边，
而用例描述「模块路径/画布」里记着每条用例打到的 方法+路径 —— 用它们反向登记。

登记规则：
- 去重键 (项目, 方法, 归一化路径)；{param} 模板和纯数字段都收成 {}，保证和
  realign_case_facets.py 回填 api_id 时的匹配键一致（唯一命中才回填）。
- 接口名称用「方法 + 最常见的原始路径」，好认；path 存归一化形态。
- 描述记下引用用例数，便于追溯；已存在的接口（同去重键）跳过。
- 路径里带中文标点（如「、」）的脏数据跳过并计数。
幂等：再次执行全部跳过。
"""
from __future__ import annotations

import sys
from collections import Counter, defaultdict
from pathlib import Path

BACKEND_DIR = Path(__file__).resolve().parents[1]
if str(BACKEND_DIR) not in sys.path:
    sys.path.insert(0, str(BACKEND_DIR))

from app.core.database.session import SessionLocal
from app.core.models.project import Project  # noqa: F401
from app.features.api_catalog.models.api_interface import ApiInterface
from app.features.test_management.facets import clip, normalize_path, parse_endpoint
from app.features.test_management.models.test_case import TestCase

_DIRTY_MARKS = ("、", "，", "。", "；")


def _option_int(flag: str) -> int | None:
    """从 argv 取 --flag 后面的整数；没传返回 None。"""
    if flag not in sys.argv:
        return None
    index = sys.argv.index(flag)
    if index + 1 >= len(sys.argv):
        raise SystemExit(f"{flag} 后面要跟一个数字")
    return int(sys.argv[index + 1])


def main() -> None:
    """逐项目登记。--dry-run 只打印将要建的条数，--project-id 只处理一个项目。"""
    dry_run = "--dry-run" in sys.argv
    project_id = _option_int("--project-id")
    db = SessionLocal()
    try:
        stats = defaultdict(int)
        case_query = db.query(TestCase.project_id, TestCase.description).filter(
            TestCase.target_type == "API",
        )
        if project_id is not None:
            case_query = case_query.filter(TestCase.project_id == project_id)

        # 按项目聚合：归一化键 → (方法, 原始路径计数)。原始路径取最高频形态做名称。
        grouped: dict[int, dict[tuple[str, str], Counter]] = defaultdict(lambda: defaultdict(Counter))
        for pid, description in case_query.all():
            endpoint = parse_endpoint(description)
            if endpoint is None:
                stats["用例无接口信息"] += 1
                continue
            method, raw_path = endpoint
            raw_path = raw_path.split("?", 1)[0]
            if any(mark in raw_path for mark in _DIRTY_MARKS):
                stats["脏路径跳过"] += 1
                continue
            grouped[pid][(method, normalize_path(raw_path))][raw_path] += 1

        existing = {
            (row.project_id, row.method, row.path)
            for row in db.query(ApiInterface.project_id, ApiInterface.method, ApiInterface.path).all()
        }
        for pid in sorted(grouped):
            for (method, norm_path), raws in sorted(grouped[pid].items()):
                stats[f"项目{pid} 去重接口"] += 1
                if (pid, method, norm_path) in existing:
                    stats["已存在跳过"] += 1
                    continue
                raw_path, references = raws.most_common(1)[0]
                total = sum(raws.values())
                db.add(ApiInterface(
                    project_id=pid,
                    module_id=None,
                    name=clip(f"{method} {raw_path}"),
                    description=f"由测试用例反向登记；{total} 条用例引用此接口",
                    method=method,
                    path=norm_path,
                    source_type="MANUAL",
                ))
                existing.add((pid, method, norm_path))
                stats["新建接口"] += 1
                _ = references

        for key in sorted(stats):
            print(f"{key} {stats[key]}")
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
