"""业务管理路由。

单 APIRouter（无自身前缀），挂在 /api/v1 下，资源级路径与 plan 路由表一致：
- /projects/{project_id}/business-domains、/business-domains/{domain_id}
- /projects/{project_id}/business-flows、/business-flows/{flow_id}(/detail)
- /business-flows/{flow_id}/actions、/business-actions/{action_id}(/reorder)
- /business-actions/{action_id}/(preconditions|variables|states|bindings)
- /business-(preconditions|variables|states)/{id}
- /business-bindings/{binding_id}、/business-bindings/{binding_id}/mappings、/business-api-mappings/{id}
- /business-flows/{flow_id}/variable-refs、/business-variable-refs/{id}
- /projects/{project_id}/business-rules、/business-rules/{rule_id}

权限：读 viewer+、写 member+、越权与不存在共用 404。
端点统一 sync def；service owns commit，router 不提交。
"""

from __future__ import annotations

from fastapi import APIRouter, Depends, Query, status
from sqlalchemy.orm import Session

from app.features.business.schemas import (
    BusinessActionCreate,
    BusinessActionReorder,
    BusinessActionResponse,
    BusinessActionUpdate,
    BusinessApiMappingCreate,
    BusinessApiMappingResponse,
    BusinessApiMappingUpdate,
    BusinessBindingCreate,
    BusinessBindingDetailResponse,
    BusinessBindingUpdate,
    BusinessDomainCreate,
    BusinessDomainListResponse,
    BusinessDomainResponse,
    BusinessDomainUpdate,
    BusinessFlowCreate,
    BusinessFlowDetailResponse,
    BusinessFlowListResponse,
    BusinessFlowResponse,
    BusinessFlowUpdate,
    BusinessPreconditionCreate,
    BusinessPreconditionResponse,
    BusinessPreconditionUpdate,
    BusinessRuleCreate,
    BusinessRuleListResponse,
    BusinessRuleResponse,
    BusinessRuleUpdate,
    BusinessStateCreate,
    BusinessStateResponse,
    BusinessStateUpdate,
    BusinessVariableCreate,
    BusinessVariableResponse,
    BusinessVariableRefCreate,
    BusinessVariableRefResponse,
    BusinessVariableUpdate,
)
from app.features.business.services.binding_service import BindingService
from app.features.business.services.config_service import ConfigService
from app.features.business.services.domain_service import DomainService
from app.features.business.services.flow_service import FlowService
from app.features.business.services.ref_service import RefService
from app.features.business.services.rule_service import RuleService
from app.models.identity import User
from app.shared.auth import get_current_user
from app.shared.database import get_db
from app.shared.pagination import DEFAULT_PAGE_SIZE, MAX_PAGE_SIZE

router = APIRouter(tags=["业务管理"])

# 服务无状态，路由层复用单例。
_DOMAIN = DomainService()
_FLOW = FlowService()
_CONFIG = ConfigService()
_BINDING = BindingService()
_REF = RefService()
_RULE = RuleService()


# --------------------------------------------------------------------------- 业务域


@router.get(
    "/projects/{project_id}/business-domains",
    response_model=BusinessDomainListResponse,
    summary="业务域列表（keyword/status 过滤）",
)
def list_domains(
    project_id: int,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
    page: int = Query(1, ge=1),
    page_size: int = Query(DEFAULT_PAGE_SIZE, ge=1, le=MAX_PAGE_SIZE),
    keyword: str | None = Query(None),
    status: str | None = Query(None),
):
    return _DOMAIN.list_domains(
        db, project_id, user, keyword=keyword, status=status, page=page, page_size=page_size
    )


@router.post(
    "/projects/{project_id}/business-domains",
    response_model=BusinessDomainResponse,
    status_code=status.HTTP_201_CREATED,
    summary="新建业务域",
)
def create_domain(
    project_id: int,
    body: BusinessDomainCreate,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
):
    return _DOMAIN.create_domain(db, project_id, body, actor=user)


@router.get("/business-domains/{domain_id}", response_model=BusinessDomainResponse, summary="业务域详情")
def get_domain(domain_id: int, db: Session = Depends(get_db), user: User = Depends(get_current_user)):
    return _DOMAIN.get_domain(db, domain_id, user)


@router.patch("/business-domains/{domain_id}", response_model=BusinessDomainResponse, summary="编辑业务域")
def update_domain(
    domain_id: int,
    body: BusinessDomainUpdate,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
):
    return _DOMAIN.update_domain(db, domain_id, body, actor=user)


@router.delete(
    "/business-domains/{domain_id}",
    status_code=status.HTTP_204_NO_CONTENT,
    summary="删除业务域（级联清理下属流程/动作/绑定）",
)
def delete_domain(domain_id: int, db: Session = Depends(get_db), user: User = Depends(get_current_user)):
    _DOMAIN.delete_domain(db, domain_id, actor=user)
    return None


# --------------------------------------------------------------------------- 业务流程


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
    return _FLOW.create_flow(db, project_id, body, actor=user)


@router.get("/business-flows/{flow_id}", response_model=BusinessFlowResponse, summary="业务流程基本信息")
def get_flow(flow_id: int, db: Session = Depends(get_db), user: User = Depends(get_current_user)):
    return _FLOW.get_flow(db, flow_id, user)


@router.get(
    "/business-flows/{flow_id}/detail",
    response_model=BusinessFlowDetailResponse,
    summary="业务流程聚合详情（动作/前置条件/变量/状态/绑定/映射/引用/规则）",
)
def get_flow_detail(flow_id: int, db: Session = Depends(get_db), user: User = Depends(get_current_user)):
    return _FLOW.get_flow_detail(db, flow_id, user)


@router.patch("/business-flows/{flow_id}", response_model=BusinessFlowResponse, summary="编辑业务流程")
def update_flow(
    flow_id: int,
    body: BusinessFlowUpdate,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
):
    return _FLOW.update_flow(db, flow_id, body, actor=user)


@router.delete(
    "/business-flows/{flow_id}",
    status_code=status.HTTP_204_NO_CONTENT,
    summary="删除业务流程（级联清理动作及子配置）",
)
def delete_flow(flow_id: int, db: Session = Depends(get_db), user: User = Depends(get_current_user)):
    _FLOW.delete_flow(db, flow_id, actor=user)
    return None


# --------------------------------------------------------------------------- 业务动作


@router.get(
    "/business-flows/{flow_id}/actions",
    response_model=list[BusinessActionResponse],
    summary="业务动作列表（按 sort 升序）",
)
def list_actions(flow_id: int, db: Session = Depends(get_db), user: User = Depends(get_current_user)):
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
    return _FLOW.create_action(db, flow_id, body, actor=user)


@router.patch("/business-actions/{action_id}", response_model=BusinessActionResponse, summary="编辑业务动作")
def update_action(
    action_id: int,
    body: BusinessActionUpdate,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
):
    return _FLOW.update_action(db, action_id, body, actor=user)


@router.delete(
    "/business-actions/{action_id}",
    status_code=status.HTTP_204_NO_CONTENT,
    summary="删除业务动作（级联清理子配置与绑定）",
)
def delete_action(action_id: int, db: Session = Depends(get_db), user: User = Depends(get_current_user)):
    _FLOW.delete_action(db, action_id, actor=user)
    return None


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
    return _FLOW.reorder_actions(db, flow_id, body, actor=user)


# --------------------------------------------------------------------------- 前置条件


@router.get(
    "/business-actions/{action_id}/preconditions",
    response_model=list[BusinessPreconditionResponse],
    summary="前置条件列表",
)
def list_preconditions(action_id: int, db: Session = Depends(get_db), user: User = Depends(get_current_user)):
    return _CONFIG.list_preconditions(db, action_id, user)


@router.post(
    "/business-actions/{action_id}/preconditions",
    response_model=BusinessPreconditionResponse,
    status_code=status.HTTP_201_CREATED,
    summary="新增前置条件",
)
def create_precondition(
    action_id: int,
    body: BusinessPreconditionCreate,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
):
    return _CONFIG.create_precondition(db, action_id, body, actor=user)


@router.patch(
    "/business-preconditions/{precondition_id}",
    response_model=BusinessPreconditionResponse,
    summary="编辑前置条件",
)
def update_precondition(
    precondition_id: int,
    body: BusinessPreconditionUpdate,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
):
    return _CONFIG.update_precondition(db, precondition_id, body, actor=user)


@router.delete(
    "/business-preconditions/{precondition_id}",
    status_code=status.HTTP_204_NO_CONTENT,
    summary="删除前置条件",
)
def delete_precondition(
    precondition_id: int, db: Session = Depends(get_db), user: User = Depends(get_current_user)
):
    _CONFIG.delete_precondition(db, precondition_id, actor=user)
    return None


# --------------------------------------------------------------------------- 业务变量


@router.get(
    "/business-actions/{action_id}/variables",
    response_model=list[BusinessVariableResponse],
    summary="业务变量列表（INPUT/OUTPUT 混排）",
)
def list_variables(action_id: int, db: Session = Depends(get_db), user: User = Depends(get_current_user)):
    return _CONFIG.list_variables(db, action_id, user)


@router.post(
    "/business-actions/{action_id}/variables",
    response_model=BusinessVariableResponse,
    status_code=status.HTTP_201_CREATED,
    summary="新增业务变量",
)
def create_variable(
    action_id: int,
    body: BusinessVariableCreate,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
):
    return _CONFIG.create_variable(db, action_id, body, actor=user)


@router.patch("/business-variables/{variable_id}", response_model=BusinessVariableResponse, summary="编辑业务变量")
def update_variable(
    variable_id: int,
    body: BusinessVariableUpdate,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
):
    return _CONFIG.update_variable(db, variable_id, body, actor=user)


@router.delete(
    "/business-variables/{variable_id}",
    status_code=status.HTTP_204_NO_CONTENT,
    summary="删除业务变量",
)
def delete_variable(variable_id: int, db: Session = Depends(get_db), user: User = Depends(get_current_user)):
    _CONFIG.delete_variable(db, variable_id, actor=user)
    return None


# --------------------------------------------------------------------------- 业务状态


@router.get(
    "/business-actions/{action_id}/states",
    response_model=list[BusinessStateResponse],
    summary="业务状态列表",
)
def list_states(action_id: int, db: Session = Depends(get_db), user: User = Depends(get_current_user)):
    return _CONFIG.list_states(db, action_id, user)


@router.post(
    "/business-actions/{action_id}/states",
    response_model=BusinessStateResponse,
    status_code=status.HTTP_201_CREATED,
    summary="新增业务状态（每动作每实体一组 Pre/Post）",
)
def create_state(
    action_id: int,
    body: BusinessStateCreate,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
):
    return _CONFIG.create_state(db, action_id, body, actor=user)


@router.patch("/business-states/{state_id}", response_model=BusinessStateResponse, summary="编辑业务状态")
def update_state(
    state_id: int,
    body: BusinessStateUpdate,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
):
    return _CONFIG.update_state(db, state_id, body, actor=user)


@router.delete(
    "/business-states/{state_id}",
    status_code=status.HTTP_204_NO_CONTENT,
    summary="删除业务状态",
)
def delete_state(state_id: int, db: Session = Depends(get_db), user: User = Depends(get_current_user)):
    _CONFIG.delete_state(db, state_id, actor=user)
    return None


# --------------------------------------------------------------------------- 业务绑定


@router.get(
    "/business-actions/{action_id}/bindings",
    response_model=list[BusinessBindingDetailResponse],
    summary="业务绑定列表（含失效判定与映射）",
)
def list_bindings(action_id: int, db: Session = Depends(get_db), user: User = Depends(get_current_user)):
    return _BINDING.list_bindings(db, action_id, user)


@router.post(
    "/business-actions/{action_id}/bindings",
    response_model=BusinessBindingDetailResponse,
    status_code=status.HTTP_201_CREATED,
    summary="新增业务绑定（第一阶段仅 API 通道）",
)
def create_binding(
    action_id: int,
    body: BusinessBindingCreate,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
):
    return _BINDING.create_binding(db, action_id, body, actor=user)


@router.get(
    "/business-bindings/{binding_id}",
    response_model=BusinessBindingDetailResponse,
    summary="业务绑定详情（含失效判定与输入/输出映射）",
)
def get_binding(binding_id: int, db: Session = Depends(get_db), user: User = Depends(get_current_user)):
    return _BINDING.get_binding(db, binding_id, user)


@router.patch("/business-bindings/{binding_id}", response_model=BusinessBindingDetailResponse, summary="编辑业务绑定")
def update_binding(
    binding_id: int,
    body: BusinessBindingUpdate,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
):
    return _BINDING.update_binding(db, binding_id, body, actor=user)


@router.delete(
    "/business-bindings/{binding_id}",
    status_code=status.HTTP_204_NO_CONTENT,
    summary="删除业务绑定（级联清理映射）",
)
def delete_binding(binding_id: int, db: Session = Depends(get_db), user: User = Depends(get_current_user)):
    _BINDING.delete_binding(db, binding_id, actor=user)
    return None


# --------------------------------------------------------------------------- API 映射


@router.get(
    "/business-bindings/{binding_id}/mappings",
    response_model=list[BusinessApiMappingResponse],
    summary="业务变量 ↔ 接口参数映射列表",
)
def list_mappings(binding_id: int, db: Session = Depends(get_db), user: User = Depends(get_current_user)):
    return _BINDING.list_mappings(db, binding_id, user)


@router.post(
    "/business-bindings/{binding_id}/mappings",
    response_model=BusinessApiMappingResponse,
    status_code=status.HTTP_201_CREATED,
    summary="新增映射（project_id→body.project_id / $.data.id→task_id 等）",
)
def create_mapping(
    binding_id: int,
    body: BusinessApiMappingCreate,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
):
    return _BINDING.create_mapping(db, binding_id, body, actor=user)


@router.patch(
    "/business-api-mappings/{mapping_id}",
    response_model=BusinessApiMappingResponse,
    summary="编辑映射",
)
def update_mapping(
    mapping_id: int,
    body: BusinessApiMappingUpdate,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
):
    return _BINDING.update_mapping(db, mapping_id, body, actor=user)


@router.delete(
    "/business-api-mappings/{mapping_id}",
    status_code=status.HTTP_204_NO_CONTENT,
    summary="删除映射",
)
def delete_mapping(mapping_id: int, db: Session = Depends(get_db), user: User = Depends(get_current_user)):
    _BINDING.delete_mapping(db, mapping_id, actor=user)
    return None


# --------------------------------------------------------------------------- 变量引用


@router.get(
    "/business-flows/{flow_id}/variable-refs",
    response_model=list[BusinessVariableRefResponse],
    summary="变量引用列表（动作间输出→输入）",
)
def list_variable_refs(flow_id: int, db: Session = Depends(get_db), user: User = Depends(get_current_user)):
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
    return _REF.create_variable_ref(db, flow_id, body, actor=user)


@router.delete(
    "/business-variable-refs/{ref_id}",
    status_code=status.HTTP_204_NO_CONTENT,
    summary="删除变量引用",
)
def delete_variable_ref(ref_id: int, db: Session = Depends(get_db), user: User = Depends(get_current_user)):
    _REF.delete_variable_ref(db, ref_id, actor=user)
    return None


# --------------------------------------------------------------------------- 业务规则


@router.get(
    "/projects/{project_id}/business-rules",
    response_model=BusinessRuleListResponse,
    summary="业务规则列表（flow_id/action_id 过滤）",
)
def list_rules(
    project_id: int,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
    page: int = Query(1, ge=1),
    page_size: int = Query(DEFAULT_PAGE_SIZE, ge=1, le=MAX_PAGE_SIZE),
    flow_id: int | None = Query(None, ge=1),
    action_id: int | None = Query(None, ge=1),
):
    return _RULE.list_rules(
        db, project_id, user,
        flow_id=flow_id, action_id=action_id, page=page, page_size=page_size,
    )


@router.post(
    "/projects/{project_id}/business-rules",
    response_model=BusinessRuleResponse,
    status_code=status.HTTP_201_CREATED,
    summary="新增业务规则",
)
def create_rule(
    project_id: int,
    body: BusinessRuleCreate,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
):
    return _RULE.create_rule(db, project_id, body, actor=user)


@router.patch("/business-rules/{rule_id}", response_model=BusinessRuleResponse, summary="编辑业务规则")
def update_rule(
    rule_id: int,
    body: BusinessRuleUpdate,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
):
    return _RULE.update_rule(db, rule_id, body, actor=user)


@router.delete(
    "/business-rules/{rule_id}",
    status_code=status.HTTP_204_NO_CONTENT,
    summary="删除业务规则",
)
def delete_rule(rule_id: int, db: Session = Depends(get_db), user: User = Depends(get_current_user)):
    _RULE.delete_rule(db, rule_id, actor=user)
    return None
