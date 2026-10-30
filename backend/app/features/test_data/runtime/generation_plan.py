"""领域职责提取；保留原权限、事务和执行顺序。"""

from __future__ import annotations

from sqlalchemy.orm import Session
from app.features.test_data.runtime.fixture_resolver import expand_dependency_order, load_visible_fixture


def iter_generation_plan(db: Session, fixture_id: int, project_id: int):
    """按依赖顺序逐项复核可见性；无跨项目或跨运行缓存。"""
    for fixture in expand_dependency_order(db, fixture_id):
        load_visible_fixture(db, fixture.id, project_id=project_id)
        yield fixture
