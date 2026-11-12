"""Validated, all-or-nothing Excel import for test cases."""

from __future__ import annotations

import hashlib
import uuid
from io import BytesIO
from typing import Any
from zipfile import BadZipFile

from fastapi import HTTPException
from openpyxl import load_workbook
from openpyxl.utils.exceptions import InvalidFileException
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.core.http.errors import bad_request, conflict
from app.core.models.identity import User
from app.features.test_management.models.case_import import TestCaseImportBatch
from app.features.test_management.models.test_case import TestCase
from app.features.test_management.models.test_scope import TestCaseScope, TestScopeNode
from app.features.test_management.services.scope_service import ScopeService
from app.platform.projects.services.access_service import require_writable_project


HEADERS = ("用例名称（必填）", "优先级", "测试维度", "用例描述")
PRIORITIES = {"P0", "P1", "P2", "P3"}
CASE_TYPES = {"FUNCTIONAL", "BUSINESS", "NEGATIVE", "BOUNDARY", "PERMISSION", "SECURITY", "EXCEPTION"}
CASE_TYPE_LABELS = {
    "功能": "FUNCTIONAL", "业务": "BUSINESS", "负向": "NEGATIVE", "边界": "BOUNDARY",
    "权限": "PERMISSION", "安全": "SECURITY", "异常": "EXCEPTION",
}
TARGET_BY_DIRECTION = {"API": "API", "UI": "WEB", "AI": "AI"}


class ExcelCaseImportService:
    """Excel 模板、预览校验、单事务确认。"""

    def parse(self, content: bytes, *, project_id: int, direction: str, scope_node_id: int | None, db: Session, actor: User) -> dict[str, Any]:
        require_writable_project(db, project_id, actor)
        self._validate_target(db, project_id, direction, scope_node_id)
        source_hash = hashlib.sha256(content).hexdigest()
        errors: list[dict[str, Any]] = []
        items: list[dict[str, Any]] = []
        if direction not in TARGET_BY_DIRECTION:
            errors.append(self._error(0, "测试方向", "测试方向必须是 API、UI 或 AI"))
            return {"source_hash": source_hash, "items": items, "errors": errors, "total_rows": 0}
        try:
            workbook = load_workbook(BytesIO(content), read_only=True, data_only=True)
            if not workbook.worksheets:
                raise ValueError("工作簿没有工作表")
            sheet = workbook.worksheets[0]
            worksheet_name = sheet.title
            if sheet.max_row > 1001:
                errors.append(self._error(1002, "用例名称", "最多支持 1000 条用例", worksheet_name))
                return {"source_hash": source_hash, "items": items, "errors": errors, "total_rows": 0}
            header = tuple(cell.value for cell in next(sheet.iter_rows(min_row=1, max_row=1, values_only=False), ()))
            normalized_header = tuple(str(value).strip() if value is not None else "" for value in header[:4])
            if normalized_header != HEADERS or any(value not in (None, "") for value in header[4:]):
                for idx, expected in enumerate(HEADERS):
                    actual = normalized_header[idx] if idx < len(normalized_header) else ""
                    if actual != expected:
                        errors.append(self._error(1, f"{chr(65 + idx)}列", f"表头应为「{expected}」", worksheet_name))
                if len(header) > 4 and any(value not in (None, "") for value in header[4:]):
                    errors.append(self._error(1, "E列", "模板只支持四列", worksheet_name))
                return {"source_hash": source_hash, "items": items, "errors": errors, "total_rows": 0}

            seen: dict[str, int] = {}
            existing_names: set[str] = set()
            raw_rows = list(sheet.iter_rows(min_row=2, max_row=1001, values_only=True))
            candidate_names = {str(row[0]).strip() for row in raw_rows if row and row[0] is not None and str(row[0]).strip()}
            if candidate_names:
                existing_names = {name for (name,) in db.query(TestCase.name).filter(
                    TestCase.project_id == project_id, TestCase.name.in_(candidate_names), TestCase.deleted_at.is_(None),
                ).all()}

            for row_number, raw in enumerate(raw_rows, start=2):
                cells = list(raw[:4]) + [None] * max(0, 4 - len(raw[:4]))
                if all(value is None or str(value).strip() == "" for value in cells):
                    continue
                name = "" if cells[0] is None else str(cells[0]).strip()
                priority = "P1" if cells[1] is None or str(cells[1]).strip() == "" else str(cells[1]).strip().upper()
                case_type_raw = "FUNCTIONAL" if cells[2] is None or str(cells[2]).strip() == "" else str(cells[2]).strip()
                case_type = CASE_TYPE_LABELS.get(case_type_raw, case_type_raw.upper())
                description = "" if cells[3] is None else str(cells[3])
                row_has_error = False
                if not name:
                    errors.append(self._error(row_number, "用例名称", "用例名称必填", worksheet_name)); row_has_error = True
                elif len(name) > 200:
                    errors.append(self._error(row_number, "用例名称", "用例名称最多 200 字", worksheet_name)); row_has_error = True
                elif name in seen:
                    errors.append(self._error(row_number, "用例名称", f"文件内重名，首次出现在第 {seen[name]} 行", worksheet_name)); row_has_error = True
                else:
                    seen[name] = row_number
                    if name in existing_names:
                        errors.append(self._error(row_number, "用例名称", "当前项目已存在同名用例", worksheet_name)); row_has_error = True
                if priority not in PRIORITIES:
                    errors.append(self._error(row_number, "优先级", "优先级只能是 P0、P1、P2 或 P3", worksheet_name)); row_has_error = True
                if case_type not in CASE_TYPES:
                    errors.append(self._error(row_number, "测试维度", "测试维度不在模板选项中", worksheet_name)); row_has_error = True
                if len(description) > 1000:
                    errors.append(self._error(row_number, "用例描述", "用例描述最多 1000 字", worksheet_name)); row_has_error = True
                items.append({
                    "worksheet": worksheet_name, "row": row_number, "name": name,
                    "priority": priority, "case_type": case_type, "description": description,
                    "valid": not row_has_error,
                })
            return {"source_hash": source_hash, "items": items, "errors": errors, "total_rows": len(items)}
        except (OSError, ValueError, KeyError, TypeError, BadZipFile, InvalidFileException) as exc:
            return {"source_hash": source_hash, "items": [], "errors": [self._error(0, "工作簿", f"无法读取 Excel：{exc}")], "total_rows": 0}

    def confirm(
        self, content: bytes, *, project_id: int, direction: str, scope_node_id: int | None,
        request_key: str, expected_source_hash: str, db: Session, actor: User,
    ) -> dict[str, Any]:
        require_writable_project(db, project_id, actor)
        try:
            key = str(uuid.UUID(request_key))
        except (ValueError, TypeError, AttributeError) as exc:
            raise bad_request("request_key 必须是 UUID") from exc
        source_hash = hashlib.sha256(content).hexdigest()
        if source_hash != expected_source_hash:
            raise conflict("确认文件与预览文件不一致，请重新预览")
        previous = db.query(TestCaseImportBatch).filter(TestCaseImportBatch.request_key == key).first()
        if previous is not None:
            return self._existing_result(previous, project_id, direction, scope_node_id, source_hash, actor.id)

        parsed = self.parse(content, project_id=project_id, direction=direction, scope_node_id=scope_node_id, db=db, actor=actor)
        if parsed["errors"] or not parsed["items"]:
            raise HTTPException(status_code=422, detail={
                "message": "Excel 校验失败，未写入任何用例",
                "meta": {"errors": parsed["errors"] or [self._error(0, "用例名称", "工作簿中没有用例行")]},
            })
        if any(not row["valid"] for row in parsed["items"]):
            raise HTTPException(status_code=422, detail={
                "message": "Excel 校验失败，未写入任何用例", "meta": {"errors": parsed["errors"]},
            })

        target_type = TARGET_BY_DIRECTION[direction]
        case_ids: list[int] = []
        try:
            for row in parsed["items"]:
                case = TestCase(
                    project_id=project_id, name=row["name"], description=row["description"] or None,
                    priority=row["priority"], case_type=row["case_type"], target_type=target_type,
                    status="DRAFT", enabled=True, source_type="MANUAL", created_by=actor.id,
                )
                db.add(case)
                db.flush()
                ScopeService().attach_new_case(db, case)
                if scope_node_id is not None:
                    db.query(TestCaseScope).filter(TestCaseScope.test_case_id == case.id).delete(synchronize_session=False)
                    db.add(TestCaseScope(test_case_id=case.id, scope_node_id=scope_node_id))
                case_ids.append(case.id)

            result = {
                "batch_id": None, "request_key": key, "project_id": project_id,
                "direction": direction, "scope_node_id": scope_node_id,
                "source_hash": source_hash, "imported_count": len(case_ids), "case_ids": case_ids,
            }
            batch = TestCaseImportBatch(
                request_key=key, project_id=project_id, created_by=actor.id,
                direction=direction, scope_node_id=scope_node_id, source_hash=source_hash,
                result_json=result,
            )
            db.add(batch)
            db.flush()
            result["batch_id"] = batch.id
            batch.result_json = result
            db.commit()
            return result
        except IntegrityError:
            db.rollback()
            duplicate = db.query(TestCaseImportBatch).filter(TestCaseImportBatch.request_key == key).first()
            if duplicate is not None:
                return self._existing_result(duplicate, project_id, direction, scope_node_id, source_hash, actor.id)
            raise
        except Exception:
            db.rollback()
            raise

    @staticmethod
    def _existing_result(batch: TestCaseImportBatch, project_id: int, direction: str, scope_node_id: int | None, source_hash: str, actor_id: int) -> dict[str, Any]:
        if batch.created_by != actor_id:
            raise conflict("request_key 已用于其他导入人")
        if (batch.project_id, batch.direction, batch.scope_node_id, batch.source_hash) != (project_id, direction, scope_node_id, source_hash):
            raise conflict("request_key 已用于不同项目、方向、目录或文件")
        return dict(batch.result_json)

    @staticmethod
    def _validate_target(db: Session, project_id: int, direction: str, scope_node_id: int | None) -> None:
        if direction not in TARGET_BY_DIRECTION:
            return
        if scope_node_id is None:
            return
        node = db.get(TestScopeNode, scope_node_id)
        if node is None or node.project_id != project_id or node.direction != direction or node.deleted_at is not None:
            raise bad_request("所选目录不属于当前项目或测试方向")

    @staticmethod
    def _error(row: int, column: str, message: str, worksheet: str = "测试用例") -> dict[str, Any]:
        return {"worksheet": worksheet, "row": row, "column": column, "message": message}


SERVICE = ExcelCaseImportService()
