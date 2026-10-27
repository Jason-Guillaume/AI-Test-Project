"""业务变量引用服务层。

在业务流程内建立不同 Business Action 之间的变量引用关系（一个动作输出 → 另一动作输入）。
第一阶段只做配置与展示，不执行真正的数据传递。

权限：读 viewer+、写 member+、越权与不存在共用 404。service owns commit。
创建时校验：source_action_id 与 target_action_id 都必须属于当前流程（跨资源不一致 → 400）。
"""

from __future__ import annotations

from sqlalchemy.orm import Session

from app.features.business.models.business_action import BusinessAction
from app.features.business.models.business_variable import BusinessVariable
from app.features.business.models.business_variable_ref import BusinessVariableRef
from app.features.business.schemas import (
    BusinessVariableRefCreate,
    BusinessVariableRefResponse,
)
from app.features.business.services._access import (
    get_project_or_404,
    require_writable_project,
    resolve_flow_project_id,
)
from app.models.identity import User
from app.shared.errors import bad_request, not_found


def _ref_response(ref: BusinessVariableRef) -> BusinessVariableRefResponse:
    """构造`ref`响应数据。"""
    return BusinessVariableRefResponse.model_validate(ref)


class RefService:
    """业务变量引用服务。无状态，路由层复用单例。"""

    def list_variable_refs(
        self, db: Session, flow_id: int, user: User
    ) -> list[BusinessVariableRefResponse]:
        """列出变量`refs`。"""
        get_project_or_404(db, resolve_flow_project_id(db, flow_id), user)
        items = (
            db.query(BusinessVariableRef)
            .filter(BusinessVariableRef.flow_id == flow_id)
            .order_by(BusinessVariableRef.id.asc())
            .all()
        )
        return [_ref_response(r) for r in items]

    def create_variable_ref(
        self, db: Session, flow_id: int, body: BusinessVariableRefCreate, *, actor: User
    ) -> BusinessVariableRefResponse:
        """创建变量`ref`。"""
        project = require_writable_project(db, resolve_flow_project_id(db, flow_id), actor)
        # 两个动作都必须属于当前流程，避免跨流程引用。
        source = db.get(BusinessAction, body.source_action_id)
        target = db.get(BusinessAction, body.target_action_id)
        if source is None or source.flow_id != flow_id:
            raise bad_request("来源动作不存在或不属于当前流程")
        if target is None or target.flow_id != flow_id:
            raise bad_request("目标动作不存在或不属于当前流程")
        if body.source_action_id == body.target_action_id:
            raise bad_request("不能引用动作自身的变量")
        # 校验变量在对应动作中存在（source → OUTPUT 变量，target → INPUT 变量），
        # 同时获取变量 ID 用于 FK 填充。
        source_var = db.query(BusinessVariable).filter(
            BusinessVariable.action_id == body.source_action_id,
            BusinessVariable.direction == "OUTPUT",
            BusinessVariable.name == body.source_variable,
        ).first()
        if source_var is None:
            raise bad_request("来源动作不存在该输出变量")
        target_var = db.query(BusinessVariable).filter(
            BusinessVariable.action_id == body.target_action_id,
            BusinessVariable.direction == "INPUT",
            BusinessVariable.name == body.target_variable,
        ).first()
        if target_var is None:
            raise bad_request("目标动作不存在该输入变量")
        ref = BusinessVariableRef(
            flow_id=flow_id,
            source_action_id=body.source_action_id,
            source_variable=body.source_variable,
            source_variable_id=source_var.id,
            target_action_id=body.target_action_id,
            target_variable=body.target_variable,
            target_variable_id=target_var.id,
        )
        db.add(ref)
        db.flush()
        db.commit()
        db.refresh(ref)
        return _ref_response(ref)

    def delete_variable_ref(self, db: Session, ref_id: int, *, actor: User) -> None:
        """删除变量`ref`。"""
        ref = db.get(BusinessVariableRef, ref_id)
        if ref is None:
            raise not_found("变量引用不存在")
        require_writable_project(db, resolve_flow_project_id(db, ref.flow_id), actor)
        db.delete(ref)
        db.commit()
