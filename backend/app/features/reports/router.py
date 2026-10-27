"""测试报告路由。

单 APIRouter（无自身前缀），挂在 /api/v1 下。资源级路径：
- POST /test-runs/{run_id}/report：为一次执行生成报告（member+；project_id 由 run 解析）
- GET  /projects/{project_id}/reports：项目报告列表（viewer+，支持环境/风险/状态/run 筛选）
- GET  /reports/{report_id}：报告详情（viewer+；明细实时读取 TestRun + CaseExecution，不复制快照）
- DELETE /reports/{report_id}：删除报告（member+；仅删报告，不删 TestRun / CaseExecution，§十一）
- POST /reports/{report_id}/regenerate-ai-summary：重生成 AI 总结（member+；统计字段不可变，§三十）

权限：读 viewer+、写 member+、越权与不存在共用 404。端点统一 sync def；service owns commit。
"""

from __future__ import annotations

from fastapi import APIRouter, Depends, Query, status
from sqlalchemy.orm import Session

from app.features.reports.schemas import (
    ReportGenerateRequest,
    ReportGenerateResponse,
    TestReportDetailResponse,
    TestReportListResponse,
    TestReportResponse,
)
from app.features.reports.services import ReportService
from app.models.identity import User
from app.shared.auth import get_current_user
from app.shared.database import get_db
from app.shared.pagination import DEFAULT_PAGE_SIZE, MAX_PAGE_SIZE

router = APIRouter(tags=["测试报告"])

# 服务无状态，路由层复用单例。
_REPORT = ReportService()


@router.post(
    "/test-runs/{run_id}/report",
    response_model=ReportGenerateResponse,
    status_code=status.HTTP_200_OK,
    summary="为测试执行生成报告",
)
def generate_report(
    run_id: int,
    body: ReportGenerateRequest,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
):
    """生成报告。"""
    # project_id 由 service 从 TestRun 解析；权限 member+ 在 service 内校验。
    return _REPORT.build_report(
        db, run_id, actor=user,
        generate_ai_summary=body.generate_ai_summary, regenerate=body.regenerate,
    )


@router.get(
    "/projects/{project_id}/reports",
    response_model=TestReportListResponse,
    summary="项目测试报告列表",
)
def list_reports(
    project_id: int,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
    page: int = Query(1, ge=1),
    page_size: int = Query(DEFAULT_PAGE_SIZE, ge=1, le=MAX_PAGE_SIZE),
    environment_id: int | None = Query(None, ge=1),
    risk_level: str | None = Query(None),
    status: str | None = Query(None),
    test_run_id: int | None = Query(None, ge=1),
):
    """列出`reports`。"""
    return _REPORT.list_reports(
        db, project_id, user, page=page, page_size=page_size,
        environment_id=environment_id, risk_level=risk_level, status=status, test_run_id=test_run_id,
    )


@router.get("/reports/{report_id}", response_model=TestReportDetailResponse, summary="测试报告详情")
def get_report(report_id: int, db: Session = Depends(get_db), user: User = Depends(get_current_user)):
    """获取报告。"""
    return _REPORT.get_report(db, report_id, user)


@router.delete("/reports/{report_id}", status_code=status.HTTP_204_NO_CONTENT, summary="删除测试报告")
def delete_report(report_id: int, db: Session = Depends(get_db), user: User = Depends(get_current_user)):
    """删除报告。"""
    _REPORT.delete_report(db, report_id, user)
    return None


@router.post(
    "/reports/{report_id}/regenerate-ai-summary",
    response_model=TestReportResponse,
    summary="重生成报告 AI 总结（统计字段不变）",
)
def regenerate_ai_summary(
    report_id: int,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
):
    """重新生成报告的 AI 摘要。"""
    return _REPORT.regenerate_ai_summary(db, report_id, user)
