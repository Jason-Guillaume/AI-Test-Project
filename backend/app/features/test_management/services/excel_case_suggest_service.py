"""Excel 用例导入的模型建议。

在固定模板预览之后、确认写入之前，读取工作表并给出列含义、测试维度和接口关联建议。
本模块对外提供 suggest，以及确认阶段使用的 resolve_confirmed_rows。

与 excel_case_import_service 协作：文件体积限制复用 open_workbook；枚举复用其常量。
接口清单只读 api_catalog 的 ApiInterface。模型调用走 llm.LLMProvider.generate_structured。

已知限制：
- 每个工作表最多读取 16 列、200 行；超出部分只记警告，不把单元格正文送进模型。
- 未映射列保留在建议响应里，确认入库时不写入用例字段。
- 不创建或覆盖接口，不生成步骤、预期结果，也不执行请求。
- 置信度只供展示，不作为自动通过条件。
"""

from __future__ import annotations

import re
from typing import Any

from zipfile import BadZipFile

from openpyxl.utils.exceptions import InvalidFileException
from pydantic import BaseModel, Field, ValidationError
from sqlalchemy.orm import Session

from app.core.http.errors import bad_request
from app.core.models.identity import User
from app.core.security.sanitizer import sanitize_text
from app.features.api_catalog.models.api_interface import ApiInterface
from app.features.test_management.models.test_case import TestCase
from app.features.test_management.facets import normalize_path
from app.features.test_management.scope_placement import interface_index, unique_interface_id
from app.features.test_management.services.excel_case_import_service import (
    CASE_TYPES,
    HEADERS,
    PRIORITIES,
    ExcelCaseImportService,
    open_workbook,
)
from app.llm.contracts import LLMError
from app.llm.providers.openai_compatible import ProductionLLMProvider

_ENDPOINT_RE = re.compile(r"\b(GET|POST|PUT|PATCH|DELETE)\s+(/[^\s，,；;]+)")
_MAX_SHEETS = 6
_MAX_ROWS = 200
_MAX_COLS = 16
_BATCH_ROWS = 40
_CELL_LIMIT = 180
_FIELDS = {
    "name", "priority", "case_type", "description", "api_code",
    "http_method", "path", "api_name", "test_point", "unmapped",
}


class _ModelColumn(BaseModel):
    """模型给出的单列含义。"""

    column_index: int
    field: str
    reason: str = ""


class _ModelSheet(BaseModel):
    """模型给出的工作表角色。"""

    worksheet: str
    role: str = "cases"
    header_row: int = 1


class _ModelRow(BaseModel):
    """模型给出的单行维度和接口建议。"""

    worksheet: str
    row: int
    case_type: str | None = None
    api_id: int | None = None
    reason: str = ""
    confidence: float = 0


class _ModelDraft(BaseModel):
    """一次模型调用允许返回的结构。多余字段忽略，缺字段用空列表。"""

    sheets: list[_ModelSheet] = Field(default_factory=list)
    columns: list[_ModelColumn] = Field(default_factory=list)
    rows: list[_ModelRow] = Field(default_factory=list)


class _RowChoice(BaseModel):
    """用户对某一行建议的最终选择。未勾选的字段保持表格原值。"""

    worksheet: str
    row: int
    skip: bool = False
    accept_case_type: bool = False
    case_type: str | None = None
    accept_api: bool = False
    api_id: int | None = None


class _Adoption(BaseModel):
    """确认入库时的人工采纳载荷。mode=template 只覆盖标准模板行。"""

    mode: str
    worksheet: str | None = None
    header_row: int = 1
    name_column: int | None = None
    priority_column: int | None = None
    case_type_column: int | None = None
    description_column: int | None = None
    rows: list[_RowChoice] = Field(default_factory=list)


def load_project_interfaces(db: Session, project_id: int) -> list[dict[str, Any]]:
    """读取当前项目未删除接口的编号、名称、方法和路径。

    最多 200 条，避免把整个接口库塞进一次模型请求。确认关联时也用这份归属校验。
    """
    rows = (
        db.query(ApiInterface.id, ApiInterface.name, ApiInterface.method, ApiInterface.path)
        .filter(ApiInterface.project_id == project_id, ApiInterface.deleted_at.is_(None))
        .order_by(ApiInterface.id.asc())
        .limit(200)
        .all()
    )
    return [
        {"id": row.id, "name": row.name or "", "method": row.method or "", "path": row.path or ""}
        for row in rows
    ]


def suggest(
    content: bytes, *, project_id: int, direction: str, scope_node_id: int | None,
    db: Session, actor: User, use_model: bool = True, provider: Any | None = None,
) -> dict[str, Any]:
    """生成列映射、测试维度和接口关联建议，不写用例。

    use_model 为假或模型失败时仍返回规则匹配结果，调用方可以手动映射。
    provider 仅供测试注入；生产路径使用当前库里的默认文本模型。
    """
    service = ExcelCaseImportService()
    from app.platform.projects.services.access_service import require_writable_project

    require_writable_project(db, project_id, actor)
    service._validate_target(db, project_id, direction, scope_node_id)
    grid = read_grid(content)
    interfaces = load_project_interfaces(db, project_id) if not grid["errors"] else []
    rows = _apply_rules(grid, interfaces)
    model_status = "skipped"
    model_error = ""
    model_calls = 0
    draft_columns: list[dict[str, Any]] = []
    draft_sheets: list[dict[str, Any]] = []
    if use_model and not grid["errors"]:
        # 模型不可用时保留规则结果，避免用户失去手动导入能力。
        try:
            draft, model_calls = _ask_model(grid, interfaces, db, provider)
            draft_columns, draft_sheets = _accept_model_structure(grid, draft)
            _merge_model_rows(rows, draft, {item["id"] for item in interfaces})
            model_status = "ok"
        except (LLMError, ValidationError, ValueError):
            model_status = "unavailable"
            model_error = "模型建议不可用，可按列手动映射后导入"
    return {
        "source_hash": grid["source_hash"],
        "template_compatible": _template_compatible(grid),
        "sheets": grid["sheets"],
        "warnings": grid["warnings"],
        "errors": grid["errors"],
        "interfaces": [{"id": item["id"], "name": item["name"], "method": item["method"], "path": item["path"]} for item in interfaces],
        "columns": draft_columns,
        "sheet_roles": draft_sheets,
        "suggested_mapping": _suggested_mapping(grid, draft_sheets, draft_columns),
        "rows": rows,
        "model_status": model_status,
        "model_error": model_error,
        "model_calls": model_calls,
    }


def resolve_confirmed_rows(
    service: ExcelCaseImportService, content: bytes, *, project_id: int, direction: str,
    scope_node_id: int | None, db: Session, actor: User, adoption_json: str | None,
) -> tuple[dict[str, Any], list[dict[str, Any]]]:
    """把确认请求解析成可写入的行，并返回实际采纳的字段。

    未提供 adoption 时直接走固定模板解析。提供后只在用户勾选的字段上覆盖原值，
    并再次核对接口属于当前项目。本函数不提交事务。
    """
    if not adoption_json:
        parsed = service.parse(
            content, project_id=project_id, direction=direction, scope_node_id=scope_node_id, db=db, actor=actor,
        )
        return parsed, []
    try:
        adoption = _Adoption.model_validate_json(adoption_json)
    except ValidationError as exc:
        raise bad_request("采纳内容无法解析") from exc
    if adoption.mode not in {"template", "mapping"}:
        raise bad_request("采纳模式只能是 template 或 mapping")
    if adoption.mode == "template":
        parsed = service.parse(
            content, project_id=project_id, direction=direction, scope_node_id=scope_node_id, db=db, actor=actor,
        )
    else:
        parsed = _mapped_preview(service, content, adoption, project_id, direction, scope_node_id, db, actor)
    interfaces = load_project_interfaces(db, project_id)
    return _apply_choices(parsed, adoption.rows, interfaces)


def read_grid(content: bytes) -> dict[str, Any]:
    """读取工作表网格。公式单元格不取值，超限列和行记入警告。

    返回的 source_hash 与固定模板预览一致，确认时用来核对文件没有被换掉。
    """
    import hashlib

    source_hash = hashlib.sha256(content).hexdigest()
    warnings: list[str] = []
    errors: list[dict[str, Any]] = []
    sheets: list[dict[str, Any]] = []
    workbook = None
    try:
        workbook = open_workbook(content)
        if not workbook.worksheets:
            raise ValueError("工作簿没有工作表")
        selected = workbook.worksheets[:_MAX_SHEETS]
        if len(workbook.worksheets) > _MAX_SHEETS:
            warnings.append(f"只读取前 {_MAX_SHEETS} 个工作表")
        for sheet in selected:
            sheets.append(_read_sheet(sheet, warnings, errors))
    except (OSError, ValueError, KeyError, TypeError, BadZipFile, InvalidFileException) as exc:
        errors.append({"worksheet": "", "row": 0, "column": "工作簿", "message": f"无法读取 Excel：{exc}"})
    finally:
        if workbook is not None:
            workbook.close()
    return {"source_hash": source_hash, "sheets": sheets, "warnings": warnings, "errors": errors}


def _read_sheet(sheet: Any, warnings: list[str], errors: list[dict[str, Any]]) -> dict[str, Any]:
    """读取一张表的表头和数据行。只迭代一次，兼容 openpyxl 只读模式。"""
    name = sheet.title
    columns: list[dict[str, Any]] = []
    rows: list[dict[str, Any]] = []
    header_row = 1
    # 只读模式下 max_column 可能还没算出来，固定读取上限列，避免把后面的单元格漏掉。
    width = _MAX_COLS
    if (sheet.max_column or 0) > _MAX_COLS:
        warnings.append(f"工作表「{name}」只保留前 {_MAX_COLS} 列")
    seen_header = False
    for row_number, cells in enumerate(sheet.iter_rows(min_row=1, max_row=_MAX_ROWS + 1, max_col=width, values_only=False), start=1):
        if row_number > _MAX_ROWS:
            warnings.append(f"工作表「{name}」只保留前 {_MAX_ROWS} 行")
            break
        values: list[str] = []
        for column_index, cell in enumerate(cells, start=1):
            if getattr(cell, "data_type", None) == "f":
                errors.append({"worksheet": name, "row": row_number, "column": f"第{column_index}列", "message": "不支持公式，请先转换为值"})
                values.append("")
                continue
            text = "" if cell.value is None else str(cell.value).strip()
            values.append(text[:1000])
        if not seen_header and any(values):
            header_row = row_number
            columns = [{"index": index, "header": value} for index, value in enumerate(values, start=1)]
            seen_header = True
            continue
        if seen_header and any(values):
            rows.append({"row": row_number, "cells": values})
    return {"name": name, "header_row": header_row, "columns": columns, "rows": rows}


def _apply_rules(grid: dict[str, Any], interfaces: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """用方法和路径、接口编号、接口名称做精确关联。模糊匹配留给模型。"""
    index = interface_index([(item["id"], item["method"], item["path"]) for item in interfaces])
    by_id = {item["id"]: item for item in interfaces}
    name_hits: dict[str, list[int]] = {}
    for item in interfaces:
        label = item["name"].strip()
        if label:
            name_hits.setdefault(label, []).append(item["id"])
    prepared: list[dict[str, Any]] = []
    for sheet in grid["sheets"]:
        code_columns = [
            column["index"] for column in sheet["columns"]
            if any(token in column["header"] for token in ("接口编号", "接口ID", "接口id"))
        ]
        for row in sheet["rows"]:
            prepared.append(_match_row(sheet["name"], row, index, by_id, name_hits, code_columns))
    return prepared


def _match_row(
    worksheet: str, row: dict[str, Any], index: dict[tuple[str, str], list[int]],
    by_id: dict[int, dict[str, Any]], name_hits: dict[str, list[int]], code_columns: list[int],
) -> dict[str, Any]:
    """为一行生成规则关联。多条命中时保持歧义，不挑第一条。"""
    cells = row["cells"]
    found: list[int] = []
    for method, path in _ENDPOINT_RE.findall(" ".join(cells)):
        found.extend(index.get((method.upper(), normalize_path(path)), []))
    for column_index in code_columns:
        if column_index - 1 >= len(cells):
            continue
        text = cells[column_index - 1]
        if text.isdigit() and int(text) in by_id:
            found.append(int(text))
    for cell in cells:
        found.extend(name_hits.get(cell, []))
    distinct = list(dict.fromkeys(found))
    status = "unmatched"
    api_id = unique_interface_id(distinct)
    reason = "未匹配到项目接口"
    if api_id is not None:
        status = "recommended"
        reason = "方法与路径、接口编号或接口名称精确匹配"
    elif distinct:
        status = "ambiguous"
        reason = "命中多个接口，需要选择"
        api_id = None
    return {
        "worksheet": worksheet,
        "row": row["row"],
        "cells": cells,
        "rule_status": status,
        "rule_api_id": api_id,
        "candidates": [_brief(by_id[item_id]) for item_id in distinct[:5] if item_id in by_id],
        "rule_reason": reason,
        "model_case_type": None,
        "model_api_id": None,
        "model_reason": "",
        "model_confidence": None,
    }


def _brief(item: dict[str, Any]) -> dict[str, Any]:
    """压缩候选接口，只留预览需要的字段。"""
    return {"id": item["id"], "name": item["name"], "method": item["method"], "path": item["path"]}


def _ask_model(grid: dict[str, Any], interfaces: list[dict[str, Any]], db: Session, provider: Any | None) -> tuple[_ModelDraft, int]:
    """分批调用文本模型。每批都校验 JSON，失败由调用方降级。"""
    active = provider if provider is not None else ProductionLLMProvider(db)
    catalog = interfaces[:80]
    merged = _ModelDraft()
    calls = 0
    pending = [
        (sheet["name"], row["row"], [_clip(value) for value in row["cells"]])
        for sheet in grid["sheets"] for row in sheet["rows"]
    ]
    sheets_payload = [
        {"name": sheet["name"], "header_row": sheet["header_row"], "columns": sheet["columns"]}
        for sheet in grid["sheets"]
    ]
    for offset in range(0, max(len(pending), 1), _BATCH_ROWS):
        batch = pending[offset:offset + _BATCH_ROWS]
        payload = {
            "sheets": sheets_payload,
            "interfaces": catalog,
            "rows": [{"worksheet": item[0], "row": item[1], "cells": item[2]} for item in batch],
        }
        import json

        system = (
            "你只根据给定表格和接口清单提出导入建议，不判断数据可以执行。"
            "返回 JSON。列 field 只能是 name、priority、case_type、description、api_code、http_method、path、api_name、test_point、unmapped。"
            "case_type 只能是 FUNCTIONAL、BUSINESS、NEGATIVE、BOUNDARY、PERMISSION、SECURITY、EXCEPTION。"
            "api_id 必须来自接口清单；无法判断时留空。不要编造接口。"
        )
        raw = active.generate_structured(
            system, json.dumps(_redact(payload), ensure_ascii=False),
            schema=_ModelDraft.model_json_schema(), kind="excel_case_import_suggest",
            validator=lambda value: _ModelDraft.model_validate(value),
        )
        draft = raw if isinstance(raw, _ModelDraft) else _ModelDraft.model_validate(raw)
        if calls == 0:
            merged.sheets = draft.sheets
            merged.columns = draft.columns
        merged.rows.extend(draft.rows)
        calls += 1
        if not pending:
            break
    return merged, calls


def _redact(value: Any) -> Any:
    """送出模型前按自由文本脱敏。结构化字段名保持不变，方便模型对齐列。"""
    if isinstance(value, str):
        return sanitize_text(value) or ""
    if isinstance(value, list):
        return [_redact(item) for item in value]
    if isinstance(value, dict):
        return {key: _redact(item) for key, item in value.items()}
    return value


def _clip(value: str) -> str:
    """限制进入模型的单元格长度，完整原文仍留在预览 cells。"""
    text = value.strip()
    if len(text) <= _CELL_LIMIT:
        return text
    return text[:_CELL_LIMIT]


def _accept_model_structure(grid: dict[str, Any], draft: _ModelDraft) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    """丢掉对不存在工作表、列或未知字段的建议。"""
    sheet_names = {sheet["name"] for sheet in grid["sheets"]}
    column_indexes = {
        sheet["name"]: {column["index"] for column in sheet["columns"]} for sheet in grid["sheets"]
    }
    sheets = []
    for item in draft.sheets:
        if item.worksheet not in sheet_names or item.role not in {"cases", "summary", "notes"}:
            continue
        sheets.append({"worksheet": item.worksheet, "role": item.role, "header_row": item.header_row})
    columns = []
    known = set().union(*column_indexes.values()) if column_indexes else set()
    for item in draft.columns:
        if item.column_index not in known or item.field not in _FIELDS:
            continue
        columns.append({"column_index": item.column_index, "field": item.field, "reason": item.reason[:200]})
    return columns, sheets


def _merge_model_rows(rows: list[dict[str, Any]], draft: _ModelDraft, allowed_ids: set[int]) -> None:
    """合并模型行建议。精确规则和歧义结果都不被模型接口编号覆盖。"""
    located = {(row["worksheet"], row["row"]): row for row in rows}
    for item in draft.rows:
        target = located.get((item.worksheet, item.row))
        if target is None:
            continue
        if item.case_type in CASE_TYPES:
            target["model_case_type"] = item.case_type
        target["model_reason"] = item.reason[:200]
        target["model_confidence"] = max(0.0, min(float(item.confidence or 0), 1.0))
        # 歧义行不允许模型替用户选定接口；未匹配才保留建议编号供勾选。
        if target["rule_status"] == "unmatched" and item.api_id in allowed_ids:
            target["model_api_id"] = item.api_id


def _template_compatible(grid: dict[str, Any]) -> bool:
    """判断第一张表是不是现有四列模板。是则确认可以不改列映射。"""
    if not grid["sheets"]:
        return False
    headers = tuple(column["header"] for column in grid["sheets"][0]["columns"][:4])
    return headers == HEADERS and len(grid["sheets"][0]["columns"]) <= 4


def _suggested_mapping(
    grid: dict[str, Any], sheet_roles: list[dict[str, Any]], columns: list[dict[str, Any]],
) -> dict[str, Any] | None:
    """把模型列建议整理成确认载荷可直接改的映射。没有表时返回空。"""
    if not grid["sheets"]:
        return None
    preferred = next((item["worksheet"] for item in sheet_roles if item["role"] == "cases"), grid["sheets"][0]["name"])
    sheet = next((item for item in grid["sheets"] if item["name"] == preferred), grid["sheets"][0])
    mapping: dict[str, Any] = {
        "worksheet": sheet["name"], "header_row": sheet["header_row"],
        "name_column": None, "priority_column": None, "case_type_column": None, "description_column": None,
    }
    field_to_key = {
        "name": "name_column", "priority": "priority_column",
        "case_type": "case_type_column", "description": "description_column",
    }
    for column in columns:
        key = field_to_key.get(column["field"])
        if key and mapping[key] is None:
            mapping[key] = column["column_index"]
    return mapping


def _mapped_preview(
    service: ExcelCaseImportService, content: bytes, adoption: _Adoption, project_id: int,
    direction: str, scope_node_id: int | None, db: Session, actor: User,
) -> dict[str, Any]:
    """按用户选定的列生成与固定模板相同形状的预览行。"""
    from app.platform.projects.services.access_service import require_writable_project

    require_writable_project(db, project_id, actor)
    service._validate_target(db, project_id, direction, scope_node_id)
    grid = read_grid(content)
    errors = list(grid["errors"])
    if adoption.worksheet is None or adoption.name_column is None:
        errors.append(service._error(0, "用例名称", "手动映射必须选择工作表和用例名称列"))
        return {"source_hash": grid["source_hash"], "items": [], "errors": errors, "total_rows": 0}
    sheet = next((item for item in grid["sheets"] if item["name"] == adoption.worksheet), None)
    if sheet is None:
        errors.append(service._error(0, "工作表", "所选工作表不存在"))
        return {"source_hash": grid["source_hash"], "items": [], "errors": errors, "total_rows": 0}
    items = []
    seen: dict[str, int] = {}
    candidate_names = {_cell(row["cells"], adoption.name_column) for row in sheet["rows"] if row["row"] > adoption.header_row}
    candidate_names.discard("")
    existing_names: set[str] = set()
    if candidate_names:
        # 与固定模板一样拒绝项目内同名，避免映射导入绕过重名校验。
        existing_names = {name for (name,) in db.query(TestCase.name).filter(
            TestCase.project_id == project_id, TestCase.name.in_(candidate_names), TestCase.deleted_at.is_(None),
        ).all()}
    for row in sheet["rows"]:
        if row["row"] <= adoption.header_row:
            continue
        cells = row["cells"]
        name = _cell(cells, adoption.name_column)
        priority = _cell(cells, adoption.priority_column) or "P1"
        case_type_raw = _cell(cells, adoption.case_type_column) or "FUNCTIONAL"
        case_type = {"功能": "FUNCTIONAL", "业务": "BUSINESS", "负向": "NEGATIVE", "边界": "BOUNDARY", "权限": "PERMISSION", "安全": "SECURITY", "异常": "EXCEPTION"}.get(case_type_raw, case_type_raw.upper())
        description = _cell(cells, adoption.description_column)
        row_errors = _row_errors(service, sheet["name"], row["row"], name, priority, case_type, description, seen)
        if name in existing_names:
            row_errors.append(service._error(row["row"], "用例名称", "当前项目已存在同名用例", sheet["name"]))
        items.append({
            "worksheet": sheet["name"], "row": row["row"], "name": name, "priority": priority.upper(),
            "case_type": case_type, "description": description, "valid": not row_errors,
        })
        errors.extend(row_errors)
    return {"source_hash": grid["source_hash"], "items": items, "errors": errors, "total_rows": len(items)}


def _cell(cells: list[str], column: int | None) -> str:
    """按 1 起始列号取单元格。未选择该列时返回空字符串。"""
    if column is None or column < 1 or column > len(cells):
        return ""
    return cells[column - 1].strip()


def _row_errors(
    service: ExcelCaseImportService, worksheet: str, row_number: int, name: str, priority: str,
    case_type: str, description: str, seen: dict[str, int],
) -> list[dict[str, Any]]:
    """复用固定模板的名称、优先级、维度和描述限制。"""
    errors = []
    if not name:
        errors.append(service._error(row_number, "用例名称", "用例名称必填", worksheet))
    elif len(name) > 200:
        errors.append(service._error(row_number, "用例名称", "用例名称最多 200 字", worksheet))
    elif name in seen:
        errors.append(service._error(row_number, "用例名称", f"文件内重名，首次出现在第 {seen[name]} 行", worksheet))
    else:
        seen[name] = row_number
    if priority.upper() not in PRIORITIES:
        errors.append(service._error(row_number, "优先级", "优先级只能是 P0、P1、P2 或 P3", worksheet))
    if case_type not in CASE_TYPES:
        errors.append(service._error(row_number, "测试维度", "测试维度不在模板选项中", worksheet))
    if len(description) > 1000:
        errors.append(service._error(row_number, "用例描述", "用例描述最多 1000 字", worksheet))
    return errors


def _apply_choices(
    parsed: dict[str, Any], choices: list[_RowChoice], interfaces: list[dict[str, Any]],
) -> tuple[dict[str, Any], list[dict[str, Any]]]:
    """按勾选覆盖维度和接口。跳过的行从错误和待写入列表中去掉。"""
    allowed = {item["id"] for item in interfaces}
    chosen = {(item.worksheet, item.row): item for item in choices}
    known = {(row["worksheet"], row["row"]) for row in parsed["items"]}
    errors = []
    for key in chosen:
        if key not in known:
            errors.append({"worksheet": key[0], "row": key[1], "column": "采纳", "message": "采纳行不在当前预览中"})
    skipped = {key for key, item in chosen.items() if item.skip}
    items = []
    applied = []
    for row in parsed["items"]:
        key = (row["worksheet"], row["row"])
        if key in skipped:
            continue
        choice = chosen.get(key)
        current = dict(row)
        record: dict[str, Any] = {"worksheet": row["worksheet"], "row": row["row"]}
        if choice and choice.accept_case_type:
            if choice.case_type not in CASE_TYPES:
                errors.append({"worksheet": row["worksheet"], "row": row["row"], "column": "测试维度", "message": "采纳的测试维度不在可选范围内"})
                current["valid"] = False
            else:
                current["case_type"] = choice.case_type
                record["case_type"] = choice.case_type
        if choice and choice.accept_api:
            # 接口必须属于当前项目；不存在的编号不能借模型输出写入。
            if choice.api_id not in allowed:
                errors.append({"worksheet": row["worksheet"], "row": row["row"], "column": "接口", "message": "关联接口不属于当前项目"})
                current["valid"] = False
            else:
                current["api_id"] = choice.api_id
                record["api_id"] = choice.api_id
        items.append(current)
        if len(record) > 2:
            applied.append(record)
    remaining_errors = [
        error for error in parsed["errors"]
        if (error.get("worksheet"), error.get("row")) not in skipped
    ]
    return {**parsed, "items": items, "errors": remaining_errors + errors, "total_rows": len(items)}, applied
