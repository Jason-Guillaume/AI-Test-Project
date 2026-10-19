"""安全 Finding：列表 / 详情 / 状态迁移。

状态迁移受 ``FINDING_STATUS_TRANSITIONS`` 约束，非法迁移 400。关闭态（误报 /
忽略 / 已解决）都只有一条出路——回到 OPEN，重新确认再判定。

Phase 1 不写 ``bug_id``，也没有「转缺陷」按钮。
"""

from __future__ import annotations

from datetime import datetime

from sqlalchemy.orm import Session

from app.features.security_testing.models import SecurityFinding
from app.features.security_testing.schemas import (
    FINDING_STATUS_TRANSITIONS,
    SecurityFindingListResponse,
    SecurityFindingRead,
    SecurityFindingUpdate,
)
from app.features.security_testing.services._access import (
    get_project_or_404,
    require_manage_project,
)
from app.models.identity import User
from app.shared.errors import CODE_SECURITY_FINDING_NOT_FOUND, AppError, bad_request, not_found
from app.shared.pagination import DEFAULT_PAGE_SIZE, MAX_PAGE_SIZE

__all__ = ["FindingService"]

# 记 resolved_by 的目标状态；其余状态只改 status。
_RESOLVED = "RESOLVED"


class FindingService:
    """Finding 服务。读 viewer+，改状态 editor+。"""

    @staticmethod
    def list_findings(
        db: Session,
        project_id: int,
        *,
        user: User,
        severity: str | None = None,
        status: str | None = None,
        statuses: list[str] | None = None,
        api_id: int | None = None,
        test_run_id: int | None = None,
        page: int = 1,
        page_size: int = DEFAULT_PAGE_SIZE,
    ) -> SecurityFindingListResponse:
        """筛选 Finding。过滤条件全部可选。"""
        get_project_or_404(db, project_id, user)
        page = max(1, page)
        page_size = min(max(1, page_size), MAX_PAGE_SIZE)

        query = db.query(SecurityFinding).filter(SecurityFinding.project_id == project_id)
        if severity:
            query = query.filter(SecurityFinding.severity == severity.upper())
        if statuses:
            # 多状态（如「未关闭」= OPEN + CONFIRMED）：单值 status 表达不了集合。
            query = query.filter(SecurityFinding.status.in_({s.upper() for s in statuses}))
        elif status:
            query = query.filter(SecurityFinding.status == status.upper())
        if api_id is not None:
            query = query.filter(SecurityFinding.api_id == api_id)
        if test_run_id is not None:
            # Run 维度的未关闭 Finding（result_analyzer 与报告 summary.security 用）。
            query = query.filter(SecurityFinding.test_run_id == test_run_id)

        total = query.count()
        rows = (
            query.order_by(SecurityFinding.id.desc())
            .offset((page - 1) * page_size)
            .limit(page_size)
            .all()
        )
        return SecurityFindingListResponse(
            items=[SecurityFindingRead.model_validate(row) for row in rows],
            total=total,
            page=page,
            page_size=page_size,
        )

    @staticmethod
    def get_finding(db: Session, finding_id: int, *, user: User) -> SecurityFindingRead:
        """详情；不可见项目与不存在共用 404。"""
        return SecurityFindingRead.model_validate(_get_or_404(db, finding_id, user))

    @staticmethod
    def update_status(
        db: Session, finding_id: int, body: SecurityFindingUpdate, *, actor: User
    ) -> SecurityFindingRead:
        """按状态机迁移 Finding 状态。

        同一状态视为幂等 no-op，方便前端重试；跨非法迁移一律 400。
        """
        row = _get_or_404(db, finding_id, actor)
        require_manage_project(db, row.project_id, actor)

        target = body.status.upper()
        current = str(row.status or "").upper()
        if target == current:
            db.refresh(row)
            return SecurityFindingRead.model_validate(row)

        allowed = FINDING_STATUS_TRANSITIONS.get(current, ())
        if target not in allowed:
            raise bad_request(f"Finding 不能从 {current} 迁移到 {target}")

        row.status = target
        if target == _RESOLVED:
            row.resolved_by = actor.id
        row.updated_at = datetime.now()
        db.add(row)
        db.commit()
        db.refresh(row)
        return SecurityFindingRead.model_validate(row)


# --------------------------------------------------------------------------- 辅助


def _get_or_404(db: Session, finding_id: int, user: User) -> SecurityFinding:
    """按 id 取 Finding；跨项目可见性问题不泄露存在性。"""
    row = db.get(SecurityFinding, finding_id)
    if row is None:
        raise AppError(
            "Finding 不存在", status_code=404, code=CODE_SECURITY_FINDING_NOT_FOUND,
        )
    get_project_or_404(db, row.project_id, user)
    return row
