"""资源路由；认证、响应模型与原 method/path 保持不变。"""

from __future__ import annotations

from io import BytesIO
from urllib.parse import quote

from fastapi import APIRouter, Depends, File, Form, HTTPException, Query, UploadFile, status
from openpyxl import Workbook
from openpyxl.worksheet.datavalidation import DataValidation
from starlette.responses import Response
from sqlalchemy.orm import Session
from app.features.test_management.schemas import (
    TestAssertionCreate,
    TestCaseCoverageResponse,
    TestCaseCreate,
    TestCaseDataCreate,
    TestCaseFixtureReplace,
    TestCasePreconditionCreate,
    TestCaseUpdate,
    TestStepCreate,
)
from app.core.models.identity import User
from app.core.security.auth import get_current_user
from app.core.database.session import get_db
from app.core.http.pagination import DEFAULT_PAGE_SIZE, MAX_PAGE_SIZE
from app.features.test_management.router.dependencies import _CASE
from app.features.test_management.services.excel_case_import_service import HEADERS, SERVICE as _EXCEL_IMPORT


router = APIRouter()


@router.get("/projects/{project_id}/test-cases/import-template", summary="下载测试用例 Excel 模板")
def download_case_import_template(
    project_id: int, db: Session = Depends(get_db), user: User = Depends(get_current_user),
):
    """生成包含优先级与测试维度下拉选项的空白模板。"""
    from app.platform.projects.services.access_service import require_writable_project

    require_writable_project(db, project_id, user)
    workbook = Workbook()
    sheet = workbook.active
    sheet.title = "测试用例"
    sheet.append(HEADERS)
    sheet.freeze_panes = "A2"
    sheet.auto_filter.ref = "A1:D1001"
    for column, width in {"A": 34, "B": 14, "C": 18, "D": 60}.items():
        sheet.column_dimensions[column].width = width
    priority_validation = DataValidation(type="list", formula1='"P0,P1,P2,P3"', allow_blank=True)
    dimension_validation = DataValidation(
        type="list",
        formula1='"FUNCTIONAL,BUSINESS,NEGATIVE,BOUNDARY,PERMISSION,SECURITY,EXCEPTION"',
        allow_blank=True,
    )
    sheet.add_data_validation(priority_validation)
    sheet.add_data_validation(dimension_validation)
    priority_validation.add("B2:B1001")
    dimension_validation.add("C2:C1001")
    instructions = workbook.create_sheet("填写说明")
    instructions.append(["列名", "规则"])
    instructions.append(["用例名称（必填）", "1-200 字；同一文件与当前项目内不可重名"])
    instructions.append(["优先级", "P0-P3；留空按 P1"])
    instructions.append(["测试维度", "FUNCTIONAL、BUSINESS、NEGATIVE、BOUNDARY、PERMISSION、SECURITY、EXCEPTION；留空按 FUNCTIONAL"])
    instructions.append(["用例描述", "可留空，最多 1000 字；保留换行"])
    instructions.append(["目标目录", "上传预览页会固定当前项目、测试方向和目录"])
    output = BytesIO()
    workbook.save(output)
    filename = "test-case-import-template.xlsx"
    return Response(
        content=output.getvalue(),
        media_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        headers={"Content-Disposition": f"attachment; filename*=UTF-8''{quote(filename)}"},
    )


@router.post("/projects/{project_id}/test-cases/import-preview", summary="预览测试用例 Excel 导入")
async def preview_case_import(
    project_id: int,
    file: UploadFile = File(...),
    direction: str = Form(...),
    scope_node_id: int | None = Form(None),
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
):
    """解析并校验工作簿，不写入用例。"""
    content = await _read_xlsx(file)
    return _EXCEL_IMPORT.parse(
        content, project_id=project_id, direction=direction, scope_node_id=scope_node_id, db=db, actor=user,
    )


@router.post("/projects/{project_id}/test-cases/import-confirm", summary="确认测试用例 Excel 导入")
async def confirm_case_import(
    project_id: int,
    file: UploadFile = File(...),
    direction: str = Form(...),
    request_key: str = Form(...),
    source_hash: str = Form(...),
    scope_node_id: int | None = Form(None),
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
):
    """重新校验后以单事务写入；同一请求键重试返回原批次结果。"""
    content = await _read_xlsx(file)
    return _EXCEL_IMPORT.confirm(
        content, project_id=project_id, direction=direction, scope_node_id=scope_node_id,
        request_key=request_key, expected_source_hash=source_hash, db=db, actor=user,
    )


async def _read_xlsx(file: UploadFile) -> bytes:
    if not (file.filename or "").lower().endswith(".xlsx"):
        raise HTTPException(status_code=422, detail="仅支持 .xlsx 文件")
    content = await file.read(5 * 1024 * 1024 + 1)
    if len(content) > 5 * 1024 * 1024:
        raise HTTPException(status_code=413, detail="Excel 文件不能超过 5 MiB")
    return content


@router.get("/projects/{project_id}/test-cases", response_model=list, summary="测试用例列表")
def list_cases(
    project_id: int,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
    page: int = Query(1, ge=1),
    page_size: int = Query(DEFAULT_PAGE_SIZE, ge=1, le=MAX_PAGE_SIZE),
    test_point_id: int | None = Query(None, ge=1),
    target_type: str | None = Query(None),
    case_type: str | None = Query(None),
    strategy_id: int | None = Query(None, ge=1),
    status: str | None = Query(None),
    keyword: str | None = Query(None),
):
    """列出`cases`。"""
    return _CASE.list_cases(
        db, project_id, user, test_point_id=test_point_id, target_type=target_type,
        case_type=case_type, strategy_id=strategy_id,
        status=status, keyword=keyword, page=page, page_size=page_size,
    ).items


@router.get(
    "/projects/{project_id}/test-cases/coverage",
    response_model=TestCaseCoverageResponse,
    summary="用例覆盖矩阵（被测对象 × 用例维度）",
)
def case_coverage(
    project_id: int,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
    target_type: str | None = Query(None),
):
    """按 被测对象 × 用例维度 聚合用例数与关联接口数，供用例库双维过滤展示。"""
    return _CASE.coverage(db, project_id, user, target_type=target_type)


@router.post("/projects/{project_id}/test-cases", status_code=status.HTTP_201_CREATED, summary="新建测试用例")
def create_case(
    project_id: int, body: TestCaseCreate,
    db: Session = Depends(get_db), user: User = Depends(get_current_user),
):
    """创建用例。"""
    return _CASE.create_case(db, project_id, body, actor=user)


@router.get("/test-cases/{case_id}", summary="测试用例基本信息")
def get_case(case_id: int, db: Session = Depends(get_db), user: User = Depends(get_current_user)):
    """获取用例。"""
    return _CASE.get_case(db, case_id, user)


@router.get("/test-cases/{case_id}/detail", summary="测试用例聚合详情（前置条件/数据/步骤/断言）")
def get_case_detail(case_id: int, db: Session = Depends(get_db), user: User = Depends(get_current_user)):
    """获取用例详情。"""
    return _CASE.get_case_detail(db, case_id, user)


@router.patch("/test-cases/{case_id}", summary="编辑测试用例（乐观锁）")
def update_case(
    case_id: int, body: TestCaseUpdate,
    db: Session = Depends(get_db), user: User = Depends(get_current_user),
):
    """更新用例。"""
    return _CASE.update_case(db, case_id, body, actor=user)


@router.delete("/test-cases/{case_id}", status_code=status.HTTP_204_NO_CONTENT, summary="删除测试用例")
def delete_case(case_id: int, db: Session = Depends(get_db), user: User = Depends(get_current_user)):
    """删除用例。"""
    _CASE.delete_case(db, case_id, actor=user)
    return None


@router.get("/test-cases/{case_id}/preconditions", response_model=list, summary="前置条件列表")
def list_preconditions(case_id: int, db: Session = Depends(get_db), user: User = Depends(get_current_user)):
    """列出`preconditions`。"""
    return _CASE.list_preconditions(db, case_id, user)


@router.post("/test-cases/{case_id}/preconditions", status_code=status.HTTP_201_CREATED, summary="新增前置条件")
def create_precondition(
    case_id: int, body: TestCasePreconditionCreate,
    db: Session = Depends(get_db), user: User = Depends(get_current_user),
):
    """创建前置条件。"""
    return _CASE.create_precondition(db, case_id, body, actor=user)


@router.get("/test-cases/{case_id}/data", response_model=list, summary="测试数据列表")
def list_data(case_id: int, db: Session = Depends(get_db), user: User = Depends(get_current_user)):
    """列出数据。"""
    return _CASE.list_data(db, case_id, user)


@router.post("/test-cases/{case_id}/data", status_code=status.HTTP_201_CREATED, summary="新增测试数据")
def create_data(
    case_id: int, body: TestCaseDataCreate,
    db: Session = Depends(get_db), user: User = Depends(get_current_user),
):
    """创建数据。"""
    return _CASE.create_data(db, case_id, body, actor=user)


@router.get("/test-cases/{case_id}/fixtures", response_model=list, summary="所需 Fixture 列表")
def list_case_fixtures(case_id: int, db: Session = Depends(get_db), user: User = Depends(get_current_user)):
    """列出用例`fixtures`。"""
    return _CASE.list_fixtures(db, case_id, user)


@router.put("/test-cases/{case_id}/fixtures", summary="整体替换所需 Fixture")
def replace_case_fixtures(
    case_id: int, body: TestCaseFixtureReplace,
    db: Session = Depends(get_db), user: User = Depends(get_current_user),
):
    """替换用例关联的固定数据。"""
    return _CASE.replace_fixtures(db, case_id, body, actor=user)


@router.get("/test-cases/{case_id}/steps", response_model=list, summary="测试步骤列表")
def list_steps(case_id: int, db: Session = Depends(get_db), user: User = Depends(get_current_user)):
    """列出`steps`。"""
    return _CASE.list_steps(db, case_id, user)


@router.post("/test-cases/{case_id}/steps", status_code=status.HTTP_201_CREATED, summary="新增测试步骤")
def create_step(
    case_id: int, body: TestStepCreate,
    db: Session = Depends(get_db), user: User = Depends(get_current_user),
):
    """创建`step`。"""
    return _CASE.create_step(db, case_id, body, actor=user)


@router.get("/test-cases/{case_id}/assertions", response_model=list, summary="断言列表")
def list_assertions(case_id: int, db: Session = Depends(get_db), user: User = Depends(get_current_user)):
    """列出`assertions`。"""
    return _CASE.list_assertions(db, case_id, user)


@router.post("/test-cases/{case_id}/assertions", status_code=status.HTTP_201_CREATED, summary="新增断言")
def create_assertion(
    case_id: int, body: TestAssertionCreate,
    db: Session = Depends(get_db), user: User = Depends(get_current_user),
):
    """创建断言。"""
    return _CASE.create_assertion(db, case_id, body, actor=user)
