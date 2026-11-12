"""整理存量测试资产的双维归属（P1 数据整理）。

用法（在 backend/ 目录下）：
    .venv/bin/python scripts/realign_case_facets.py --dry-run   # 先预览
    .venv/bin/python scripts/realign_case_facets.py             # 确认后写入
    .venv/bin/python scripts/realign_case_facets.py --project-id 3 --dry-run

只改当前 DATABASE_URL 指向的库。做三件事：
1. 测试点拆维：「范围·接口测试 / 边界测试 / 登录接口」→ 名字只留叶子场景「登录接口」，
   target_type 按第一段（接口/界面/业务）对齐；AI 段没有对应枚举，跳过不改。
2. 用例对齐：挂在该测试点下的用例，case_type 按路径第二段（边界/安全/…）对齐，
   target_type 随测试点；路径是人整理的大纲，优先于导入时按文件名猜的值。
3. 回填 api_id：按用例描述「模块路径/画布」里的 方法+路径 匹配接口管理，
   唯一命中才回填；多义或未命中只计数不动数据。

另把测试策略的 category 在其下所有测试点维度一致时对齐；维度混杂的保持原样。
幂等：再次执行没有可改的条目。用例改动会把 revision 加一，避免覆盖编辑中的版本。
"""
from __future__ import annotations

import sys
from collections import defaultdict
from pathlib import Path

BACKEND_DIR = Path(__file__).resolve().parents[1]
if str(BACKEND_DIR) not in sys.path:
    sys.path.insert(0, str(BACKEND_DIR))

from app.core.database.session import SessionLocal
# 外键指向这些表。不导入时，提交更新找不到目标表。
from app.agents.models.session import AgentSession  # noqa: F401
from app.core.models.identity import User  # noqa: F401
from app.core.models.project import Project  # noqa: F401
from app.features.api_catalog.models.api_interface import ApiInterface
from app.features.business.models.business_action import BusinessAction  # noqa: F401
from app.features.business.models.business_flow import BusinessFlow  # noqa: F401
from app.features.test_management.facets import (
    ScopeFacets,
    clip,
    normalize_path,
    parse_endpoint,
    parse_scope_path,
    scope_path_of_point,
)
from app.features.test_management.models.test_case import TestCase
from app.features.test_management.models.test_point import TestPoint
from app.features.test_management.models.test_strategy import TestStrategy


def allocate(base: str, used: set[str]) -> str:
    """在项目已占用的名称之外挑一个不超过 200 字的名字。"""
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


def catalog_index(db, project_ids: list[int]) -> dict[int, dict[tuple[str, str], set[int]]]:
    """按项目建 方法+归一化路径 → 接口ID集 的索引；归一化后撞键的接口按多义处理。"""
    index: dict[int, dict[tuple[str, str], set[int]]] = defaultdict(lambda: defaultdict(set))
    rows = (
        db.query(ApiInterface.project_id, ApiInterface.id, ApiInterface.method, ApiInterface.path)
        .filter(ApiInterface.project_id.in_(project_ids))
        .all()
    )
    for project_id, api_id, method, path in rows:
        index[project_id][(method.upper(), normalize_path(path))].add(api_id)
    return index


def main() -> None:
    """按项目整理。--dry-run 只打印将要改的条数，--project-id 只整理一个项目。"""
    dry_run = "--dry-run" in sys.argv
    project_id = _option_int("--project-id")
    db = SessionLocal()
    try:
        stats = defaultdict(int)
        samples: list[str] = []

        point_query = db.query(TestPoint).order_by(TestPoint.project_id.asc(), TestPoint.id.asc())
        if project_id is not None:
            point_query = point_query.filter(TestPoint.project_id == project_id)
        points = point_query.all()

        # 第一遍：解析每个测试点的范围路径；不改的名字先占位，保证改名唯一。
        facets_by_point: dict[int, tuple[ScopeFacets, str]] = {}
        reserved: dict[int, set[str]] = defaultdict(set)
        renames: list[tuple[TestPoint, str]] = []
        for point in points:
            path = scope_path_of_point(point.name, point.description)
            facets = parse_scope_path(path) if path else None
            if facets is None:
                stats["范围路径未识别"] += 1
                reserved[point.project_id].add(point.name)
                continue
            facets_by_point[point.id] = (facets, path)
            if facets.target_type and point.target_type != facets.target_type:
                point.target_type = facets.target_type
                stats["测试点对象对齐"] += 1
            leaf = clip(facets.leaf)
            if leaf and leaf != point.name:
                renames.append((point, leaf))
            else:
                reserved[point.project_id].add(point.name)

        for point, leaf in renames:
            stored = allocate(leaf, reserved[point.project_id])
            if stored == point.name:
                # 叶子名被别人占用时 allocate 会给出当前名字（如 ·2），等于不改。
                continue
            if len(samples) < 8:
                samples.append(f"测试点 {point.name} → {stored}")
            point.name = stored
            stats["测试点改名"] += 1

        case_query = db.query(TestCase).order_by(TestCase.project_id.asc(), TestCase.id.asc())
        if project_id is not None:
            case_query = case_query.filter(TestCase.project_id == project_id)
        cases = case_query.all()
        catalog = catalog_index(db, sorted({case.project_id for case in cases})) if cases else {}

        for case in cases:
            changed = False
            mounted = facets_by_point.get(case.test_point_id) if case.test_point_id else None
            if mounted is not None:
                facets, _path = mounted
                if facets.case_type and case.case_type != facets.case_type:
                    case.case_type = facets.case_type
                    stats["用例维度对齐"] += 1
                    changed = True
                if facets.target_type and case.target_type != facets.target_type:
                    case.target_type = facets.target_type
                    stats["用例对象对齐"] += 1
                    changed = True
            if case.api_id is None and case.target_type == "API":
                endpoint = parse_endpoint(case.description)
                if endpoint is None:
                    stats["接口未解析"] += 1
                else:
                    method, path = endpoint
                    hits = catalog.get(case.project_id, {}).get((method, normalize_path(path)), set())
                    if len(hits) == 1:
                        case.api_id = next(iter(hits))
                        stats["api_id回填"] += 1
                        changed = True
                    elif hits:
                        stats["接口多义跳过"] += 1
                    else:
                        stats["接口未命中"] += 1
            if changed:
                case.revision = int(case.revision or 1) + 1
                stats["用例变更"] += 1

        # 策略类别：其下测试点维度一致时对齐；混杂的保持原样。
        strategy_query = db.query(TestStrategy)
        if project_id is not None:
            strategy_query = strategy_query.filter(TestStrategy.id.in_(
                db.query(TestPoint.strategy_id).filter(
                    TestPoint.project_id == project_id,
                ).scalar_subquery(),
            ))
        point_strategy = {point.id: point.strategy_id for point in points if point.strategy_id}
        dims_by_strategy: dict[int, set[str]] = defaultdict(set)
        for point_id, (facets, _path) in facets_by_point.items():
            strategy_id = point_strategy.get(point_id)
            if strategy_id and facets.case_type:
                dims_by_strategy[strategy_id].add(facets.case_type)
        for strategy in strategy_query.all():
            dims = dims_by_strategy.get(strategy.id, set())
            if len(dims) == 1:
                dim = next(iter(dims))
                if strategy.category != dim:
                    strategy.category = dim
                    stats["策略类别对齐"] += 1
            elif len(dims) > 1:
                stats["策略维度混杂保持"] += 1

        for key in sorted(stats):
            print(f"{key} {stats[key]}")
        for line in samples:
            print(f"- {line}")
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


def _option_int(flag: str) -> int | None:
    """从 argv 取 --flag 后面的整数；没传返回 None。"""
    if flag not in sys.argv:
        return None
    index = sys.argv.index(flag)
    if index + 1 >= len(sys.argv):
        raise SystemExit(f"{flag} 后面要跟一个数字")
    return int(sys.argv[index + 1])


if __name__ == "__main__":
    main()
