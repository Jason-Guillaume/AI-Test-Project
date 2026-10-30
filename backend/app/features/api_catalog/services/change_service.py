"""领域职责提取；保留原权限、事务和执行顺序。"""

from __future__ import annotations

from sqlalchemy.orm import Session
from app.features.api_catalog.models.api_change_log import ApiChangeLog
from app.features.api_catalog.models.api_interface import ApiInterface
from app.features.api_catalog.models.api_import_record import ApiImportRecord
from app.features.api_catalog.schemas import ApiChangeLogResponse
from app.features.api_catalog.services.hash import compute_source_hash
from app.features.api_catalog.services.request_store import (
    load_interface_request_body,
    load_interface_request_params,
)
from app.core.models.identity import User
from app.features.api_catalog.services.access_service import get_interface_or_404
from app.platform.projects.services.access_service import get_project_or_404
from app.features.api_catalog.services.response_mapper import interface_to_internal_schema
from app.features.api_catalog.services.request_store import load_interface_request_body
from app.features.api_catalog.services.request_store import load_interface_request_params
from app.features.api_catalog.services.request_store import load_responses


def write_change_log(db: Session,
    iface: ApiInterface,
    change_type: str,
    *,
    diff_json: dict | None = None,
    source_hash_before: str | None = None,
    source_hash_after: str | None = None,
    summary: str | None = None,
    actor: User,
) -> None:
    """写入`change``log`。"""
    log = ApiChangeLog(
        interface_id=iface.id,
        change_type=change_type,
        diff_json=diff_json,
        source_hash_before=source_hash_before,
        source_hash_after=source_hash_after,
        summary=summary,
        created_by=actor.id,
    )
    db.add(log)
    db.flush()


def recompute_hash_and_log(db: Session,
    iface: ApiInterface,
    *,
    change_type: str,
    summary: str,
    actor: User,
) -> str:
    """重算 source_hash；若变化则写 change_log，返回新 hash。"""
    before = iface.source_hash
    params = load_interface_request_params(db, iface.id)
    body = load_interface_request_body(db, iface.id)
    responses = load_responses(db, iface.id)
    schema = interface_to_internal_schema(iface, params, body, responses)
    after = compute_source_hash(schema)
    if before != after:
        write_change_log(
            db, iface, change_type,
            diff_json={"before": before, "after": after},
            source_hash_before=before,
            source_hash_after=after,
            summary=summary,
            actor=actor,
        )
        iface.source_hash = after
    return after


def list_history(db: Session, api_id: int, user: User, *, page: int = 1, page_size: int = 20
) -> tuple[list[ApiChangeLogResponse], int]:
    """列出`history`。"""
    iface = get_interface_or_404(db, api_id, user)
    query = db.query(ApiChangeLog).filter(ApiChangeLog.interface_id == iface.id)
    total = int(query.count())
    items = (
        query.order_by(ApiChangeLog.id.desc())
        .offset((page - 1) * page_size)
        .limit(page_size)
        .all()
    )
    return [ApiChangeLogResponse.model_validate(i) for i in items], total


def list_import_records(db: Session, project_id: int, user: User, *, page: int = 1, page_size: int = 20
) -> tuple[list, int]:
    """列出`import`记录。"""
    get_project_or_404(db, project_id, user)
    query = db.query(ApiImportRecord).filter(ApiImportRecord.project_id == project_id)
    total = int(query.count())
    items = (
        query.order_by(ApiImportRecord.id.desc())
        .offset((page - 1) * page_size)
        .limit(page_size)
        .all()
    )
    from app.features.api_catalog.schemas import ApiImportRecordResponse

    return [ApiImportRecordResponse.model_validate(i) for i in items], total
