"""资源路由；认证、响应模型与原 method/path 保持不变。"""

from __future__ import annotations

from fastapi import APIRouter, Depends, Query, status
from sqlalchemy.orm import Session
from app.features.business.schemas import (
    BusinessActionCreate,
    BusinessActionReorder,
    BusinessActionResponse,
    BusinessFlowCreate,
    BusinessFlowDetailResponse,
    BusinessFlowListResponse,
    BusinessFlowResponse,
    BusinessFlowUpdate,
    BusinessVariableRefCreate,
    BusinessVariableRefResponse,
    FlowExecutionRequest,
    FlowExecutionResponse,
)
from app.core.models.identity import User
from app.core.security.auth import get_current_user
from app.core.database.session import get_db
from app.core.http.pagination import DEFAULT_PAGE_SIZE, MAX_PAGE_SIZE
from app.features.business.router.dependencies import _EXECUTION
from app.features.business.router.dependencies import _FLOW
from app.features.business.router.dependencies import _REF


router = APIRouter()


@router.get(
    "/projects/{project_id}/business-flows",
    response_model=BusinessFlowListResponse,
    summary="业务流程列表（domain_id/status/keyword 过滤）",
)
def list_flows(
    project_id: int,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
    page: int = Query(1, ge=1),
    page_size: int = Query(DEFAULT_PAGE_SIZE, ge=1, le=MAX_PAGE_SIZE),
    domain_id: int | None = Query(None, ge=1),
    status: str | None = Query(None),
    keyword: str | None = Query(None),
):
    """列出`flows`。"""
    return _FLOW.list_flows(
        db, project_id, user,
        domain_id=domain_id, status=status, keyword=keyword, page=page, page_size=page_size,
    )


@router.post(
    "/projects/{project_id}/business-flows",
    response_model=BusinessFlowResponse,
    status_code=status.HTTP_201_CREATED,
    summary="新建业务流程",
)
def create_flow(
    project_id: int,
    body: BusinessFlowCreate,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
):
    """创建流程。"""
    return _FLOW.create_flow(db, project_id, body, actor=user)


@router.get("/business-flows/{flow_id}", response_model=BusinessFlowResponse, summary="业务流程基本信息")
def get_flow(flow_id: int, db: Session = Depends(get_db), user: User = Depends(get_current_user)):
    """获取流程。"""
    return _FLOW.get_flow(db, flow_id, user)


@router.get(
    "/business-flows/{flow_id}/detail",
    response_model=BusinessFlowDetailResponse,
    summary="业务流程聚合详情（动作/前置条件/变量/状态/绑定/映射/引用/规则）",
)
def get_flow_detail(flow_id: int, db: Session = Depends(get_db), user: User = Depends(get_current_user)):
    """获取流程详情。"""
    return _FLOW.get_flow_detail(db, flow_id, user)


@router.patch("/business-flows/{flow_id}", response_model=BusinessFlowResponse, summary="编辑业务流程")
def update_flow(
    flow_id: int,
    body: BusinessFlowUpdate,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
):
    """更新流程。"""
    return _FLOW.update_flow(db, flow_id, body, actor=user)


@router.delete(
    "/business-flows/{flow_id}",
    status_code=status.HTTP_204_NO_CONTENT,
    summary="删除业务流程（级联清理动作及子配置）",
)
def delete_flow(flow_id: int, db: Session = Depends(get_db), user: User = Depends(get_current_user)):
    """删除流程。"""
    _FLOW.delete_flow(db, flow_id, actor=user)
    return None


@router.get(
    "/business-flows/{flow_id}/actions",
    response_model=list[BusinessActionResponse],
    summary="业务动作列表（按 sort 升序）",
)
def list_actions(flow_id: int, db: Session = Depends(get_db), user: User = Depends(get_current_user)):
    """列出`actions`。"""
    return _FLOW.list_actions(db, flow_id, user)


@router.post(
    "/business-flows/{flow_id}/actions",
    response_model=BusinessActionResponse,
    status_code=status.HTTP_201_CREATED,
    summary="新增业务动作（默认追加到末尾）",
)
def create_action(
    flow_id: int,
    body: BusinessActionCreate,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
):
    """创建动作。"""
    return _FLOW.create_action(db, flow_id, body, actor=user)


@router.patch(
    "/business-flows/{flow_id}/actions/reorder",
    response_model=list[BusinessActionResponse],
    summary="批量重排业务动作顺序",
)
def reorder_actions(
    flow_id: int,
    body: BusinessActionReorder,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
):
    """重新排序动作。"""
    return _FLOW.reorder_actions(db, flow_id, body, actor=user)


@router.get(
    "/business-flows/{flow_id}/variable-refs",
    response_model=list[BusinessVariableRefResponse],
    summary="变量引用列表（动作间输出→输入）",
)
def list_variable_refs(flow_id: int, db: Session = Depends(get_db), user: User = Depends(get_current_user)):
    """列出变量`refs`。"""
    return _REF.list_variable_refs(db, flow_id, user)


@router.post(
    "/business-flows/{flow_id}/variable-refs",
    response_model=BusinessVariableRefResponse,
    status_code=status.HTTP_201_CREATED,
    summary="新增变量引用",
)
def create_variable_ref(
    flow_id: int,
    body: BusinessVariableRefCreate,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
):
    """创建变量`ref`。"""
    return _REF.create_variable_ref(db, flow_id, body, actor=user)


@router.post(
    "/business-flows/{flow_id}/execute",
    response_model=FlowExecutionResponse,
    status_code=status.HTTP_200_OK,
    summary="执行业务流程",
)
def execute_flow_endpoint(
    flow_id: int,
    body: FlowExecutionRequest,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
):
    """执行流程接口。"""
    return _EXECUTION.execute_flow(db, flow_id, body, actor=user)
