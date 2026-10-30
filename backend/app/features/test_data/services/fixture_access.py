"""领域职责提取；保留原权限、事务和执行顺序。"""

from __future__ import annotations

from sqlalchemy.orm import Session
from app.features.test_data.models.fixture import Fixture
from app.features.test_data.services.access_service import resolve_fixture_project_id
from app.platform.projects.services.access_service import get_project_or_404, require_writable_project
from app.core.models.identity import User
from app.features.test_data.services.fixture_validation import raise_not_found


def get_or_404(db: Session, fixture_id: int, user: User) -> Fixture:
    """获取或。"""
    row = db.get(Fixture, fixture_id)
    if row is None:
        raise_not_found()
    get_project_or_404(db, row.project_id, user)
    return row


def get_writable_or_404(db: Session, fixture_id: int, actor: User) -> Fixture:
    """获取可写或。"""
    row = db.get(Fixture, fixture_id)
    if row is None:
        raise_not_found()
    require_writable_project(db, resolve_fixture_project_id(db, fixture_id), actor)
    return row
