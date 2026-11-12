"""Fixture 可见性解析与依赖展开（§8 第 1、2 步）。

保存时已经做过环检测，但这里在运行时**再检测一次**——防止两个请求并发修改依赖
造成环，保存时检测不到的那种。命中环报 ``FIXTURE_DEPENDENCY_CYCLE``，消息里带
完整路径，便于直接看出谁环了谁。

两个项目身份要分清：
- ``owner_project_id = fixture.project_id``：解析这个 Fixture 自己的步骤资源
  （Provider / API / 被测库连接）用。GLOBAL Fixture 的步骤配置属于拥有者。
- ``consumer_project_id``：执行记录的 project_id 永远是消费方。
Phase B 的手工试跑里两者相同；用例/Run 集成（Phase C）才会真正分叉。
"""

from __future__ import annotations

from sqlalchemy.orm import Session

from app.features.test_data.models.fixture import Fixture, FixtureDependency
from app.core.http.errors import (
    CODE_FIXTURE_DEPENDENCY_CYCLE,
    CODE_FIXTURE_NOT_FOUND,
    AppError,
)


def load_visible_fixture(
    db: Session,
    fixture_id: int,
    *,
    project_id: int,
) -> Fixture:
    """按 ID 加载 Fixture 并校验可见性：本项目，或 GLOBAL 且 ACTIVE。

    跨项目引用私有 Fixture 报 ``FIXTURE_NOT_FOUND``（404），不暴露存在性。
    """
    fixture = db.get(Fixture, fixture_id)
    if fixture is None:
        raise AppError("Fixture 不存在", status_code=404, code=CODE_FIXTURE_NOT_FOUND)
    if fixture.project_id == project_id:
        return fixture
    if fixture.scope == "GLOBAL" and fixture.status == "ACTIVE":
        return fixture
    raise AppError("Fixture 不存在", status_code=404, code=CODE_FIXTURE_NOT_FOUND)


def find_dependency_cycle(
    db: Session,
    fixture_id: int,
    *,
    _path: tuple[int, ...] | None = None,
) -> list[int] | None:
    """迭代 DFS 找环，返回环上的 fixture_id 序列（首尾相同）；无环返回 None。"""
    path = _path or (fixture_id,)
    index = {fid: i for i, fid in enumerate(path)}
    deps = db.query(FixtureDependency.depends_on_fixture_id).filter(
        FixtureDependency.fixture_id == fixture_id
    ).order_by(FixtureDependency.sort.asc(), FixtureDependency.id.asc()).all()

    for dep_id in deps:
        dep_id = int(dep_id[0])
        if dep_id in index:
            return list(path[index[dep_id]:]) + [dep_id]
        found = find_dependency_cycle(db, dep_id, _path=path + (dep_id,))
        if found is not None:
            return found
    return None


def raise_dependency_cycle(db: Session, cycle_ids: list[int]) -> None:
    """把环路径转成报错消息：`A → B → C → A`（用 fixture_key，不用自增 ID）。"""
    keys = []
    for fid in cycle_ids:
        fixture = db.get(Fixture, fid)
        keys.append(fixture.fixture_key if fixture else f"#{fid}")
    raise AppError(
        "检测到 Fixture 依赖环：" + " → ".join(keys),
        status_code=400,
        code=CODE_FIXTURE_DEPENDENCY_CYCLE,
    )


def expand_dependency_order(
    db: Session,
    fixture_id: int,
    *,
    max_depth: int = 10,
    _visited: set[int] | None = None,
) -> list[Fixture]:
    """返回执行顺序：依赖先于自己（深度优先）。

    保存时禁止环，但这里再做运行时环检测，命中直接抛。同一 Fixture 在一次展开里
    只出现一次（visited 去重），避免菱形依赖被生成两遍。
    """
    visited = _visited if _visited is not None else set()
    if fixture_id in visited:
        return []
    if max_depth <= 0:
        raise AppError(
            "Fixture 依赖链过深",
            status_code=400,
            code=CODE_FIXTURE_DEPENDENCY_CYCLE,
        )

    cycle = find_dependency_cycle(db, fixture_id)
    if cycle is not None:
        raise_dependency_cycle(db, cycle)

    fixture = db.get(Fixture, fixture_id)
    if fixture is None:
        return []
    visited.add(fixture_id)

    ordered: list[Fixture] = []
    deps = db.query(FixtureDependency).filter(
        FixtureDependency.fixture_id == fixture_id
    ).order_by(FixtureDependency.sort.asc(), FixtureDependency.id.asc()).all()

    for dep in deps:
        ordered.extend(expand_dependency_order(
            db, int(dep.depends_on_fixture_id),
            max_depth=max_depth - 1,
            _visited=visited,
        ))
    ordered.append(fixture)
    return ordered


__all__ = [
    "expand_dependency_order",
    "find_dependency_cycle",
    "load_visible_fixture",
    "raise_dependency_cycle",
]
