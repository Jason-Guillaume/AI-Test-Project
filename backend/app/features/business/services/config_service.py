"""业务动作子配置服务层：前置条件 / 输入输出变量 / 状态。

三者都挂在 BusinessAction 下，权限经 resolve_action_project_id 回溯到项目校验。
service owns commit；唯一性冲突用 409，参数非法用 400，越权与不存在共用 404。
"""

from __future__ import annotations

from sqlalchemy.orm import Session

from app.features.business.models.business_precondition import BusinessPrecondition
from app.features.business.models.business_state import BusinessState
from app.features.business.models.business_variable import BusinessVariable
from app.features.business.schemas import (
    BusinessPreconditionCreate,
    BusinessPreconditionResponse,
    BusinessPreconditionUpdate,
    BusinessStateCreate,
    BusinessStateResponse,
    BusinessStateUpdate,
    BusinessVariableCreate,
    BusinessVariableResponse,
    BusinessVariableUpdate,
)
from app.features.business.services.access_service import resolve_action_project_id
from app.platform.projects.services.access_service import get_project_or_404, require_writable_project
from app.core.models.identity import User
from app.core.http.errors import conflict, not_found


def _precondition_response(p: BusinessPrecondition) -> BusinessPreconditionResponse:
    """构造`precondition`响应数据。"""
    return BusinessPreconditionResponse.model_validate(p)


def _variable_response(v: BusinessVariable) -> BusinessVariableResponse:
    """构造`variable`响应数据。"""
    return BusinessVariableResponse.model_validate(v)


def _state_response(s: BusinessState) -> BusinessStateResponse:
    """构造状态响应数据。"""
    return BusinessStateResponse.model_validate(s)


class ConfigService:
    """业务动作子配置服务（前置条件 / 变量 / 状态）。无状态，路由层复用单例。"""

    # ---------------------------------------------------------------- 前置条件

    def list_preconditions(
        self, db: Session, action_id: int, user: User
    ) -> list[BusinessPreconditionResponse]:
        """列出`preconditions`。"""
        get_project_or_404(db, resolve_action_project_id(db, action_id), user)
        items = (
            db.query(BusinessPrecondition)
            .filter(BusinessPrecondition.action_id == action_id)
            .order_by(BusinessPrecondition.sort.asc(), BusinessPrecondition.id.asc())
            .all()
        )
        return [_precondition_response(p) for p in items]

    def create_precondition(
        self, db: Session, action_id: int, body: BusinessPreconditionCreate, *, actor: User
    ) -> BusinessPreconditionResponse:
        """创建前置条件。"""
        require_writable_project(db, resolve_action_project_id(db, action_id), actor)
        precondition = BusinessPrecondition(
            action_id=action_id,
            type=body.type,
            target=body.target,
            operator=body.operator,
            expected_value=body.expected_value,
            description=body.description,
            sort=body.sort,
        )
        db.add(precondition)
        db.flush()
        db.commit()
        db.refresh(precondition)
        return _precondition_response(precondition)

    def update_precondition(
        self, db: Session, precondition_id: int, body: BusinessPreconditionUpdate, *, actor: User
    ) -> BusinessPreconditionResponse:
        """更新前置条件。"""
        precondition = self._get_writable_precondition_or_404(db, precondition_id, actor)
        data = body.model_dump(exclude_unset=True)
        # 过滤 NOT NULL 字段的 None 值，避免写入空值导致 DB 错误
        data = {k: v for k, v in data.items() if v is not None or k not in ("type", "target", "operator")}
        if data:
            for field, value in data.items():
                setattr(precondition, field, value)
            db.flush()
            db.commit()
            db.refresh(precondition)
        return _precondition_response(precondition)

    def delete_precondition(self, db: Session, precondition_id: int, *, actor: User) -> None:
        """删除前置条件。"""
        precondition = self._get_writable_precondition_or_404(db, precondition_id, actor)
        db.delete(precondition)
        db.commit()

    # ---------------------------------------------------------------- 变量

    def list_variables(
        self, db: Session, action_id: int, user: User
    ) -> list[BusinessVariableResponse]:
        """列出`variables`。"""
        get_project_or_404(db, resolve_action_project_id(db, action_id), user)
        items = (
            db.query(BusinessVariable)
            .filter(BusinessVariable.action_id == action_id)
            .order_by(BusinessVariable.sort.asc(), BusinessVariable.id.asc())
            .all()
        )
        return [_variable_response(v) for v in items]

    def create_variable(
        self, db: Session, action_id: int, body: BusinessVariableCreate, *, actor: User
    ) -> BusinessVariableResponse:
        """创建变量。"""
        require_writable_project(db, resolve_action_project_id(db, action_id), actor)
        _ensure_unique_variable(db, action_id, body.direction, body.name)
        variable = BusinessVariable(
            action_id=action_id,
            direction=body.direction,
            name=body.name,
            data_type=body.data_type,
            required=body.required,
            description=body.description,
            sort=body.sort,
        )
        db.add(variable)
        db.flush()
        db.commit()
        db.refresh(variable)
        return _variable_response(variable)

    def update_variable(
        self, db: Session, variable_id: int, body: BusinessVariableUpdate, *, actor: User
    ) -> BusinessVariableResponse:
        """更新变量。"""
        variable = self._get_writable_variable_or_404(db, variable_id, actor)
        data = body.model_dump(exclude_unset=True)
        # 过滤 NOT NULL 字段的 None 值，避免写入空值导致 DB 错误
        data = {k: v for k, v in data.items() if v is not None or k not in ("direction", "name", "data_type")}
        if data:
            new_direction = data.get("direction", variable.direction)
            new_name = data.get("name", variable.name)
            if new_name != variable.name or new_direction != variable.direction:
                _ensure_unique_variable(
                    db, variable.action_id, new_direction, new_name, exclude_id=variable.id
                )
            for field, value in data.items():
                setattr(variable, field, value)
            db.flush()
            db.commit()
            db.refresh(variable)
        return _variable_response(variable)

    def delete_variable(self, db: Session, variable_id: int, *, actor: User) -> None:
        """删除变量。"""
        variable = self._get_writable_variable_or_404(db, variable_id, actor)
        db.delete(variable)
        db.commit()

    # ---------------------------------------------------------------- 状态

    def list_states(self, db: Session, action_id: int, user: User) -> list[BusinessStateResponse]:
        """列出`states`。"""
        get_project_or_404(db, resolve_action_project_id(db, action_id), user)
        items = (
            db.query(BusinessState)
            .filter(BusinessState.action_id == action_id)
            .order_by(BusinessState.id.asc())
            .all()
        )
        return [_state_response(s) for s in items]

    def create_state(
        self, db: Session, action_id: int, body: BusinessStateCreate, *, actor: User
    ) -> BusinessStateResponse:
        """创建状态。"""
        require_writable_project(db, resolve_action_project_id(db, action_id), actor)
        _ensure_unique_state(db, action_id, body.entity)
        state = BusinessState(
            action_id=action_id,
            entity=body.entity,
            pre_state=body.pre_state,
            post_state=body.post_state,
        )
        db.add(state)
        db.flush()
        db.commit()
        db.refresh(state)
        return _state_response(state)

    def update_state(
        self, db: Session, state_id: int, body: BusinessStateUpdate, *, actor: User
    ) -> BusinessStateResponse:
        """更新状态。"""
        state = self._get_writable_state_or_404(db, state_id, actor)
        data = body.model_dump(exclude_unset=True)
        # 过滤 NOT NULL 字段的 None 值，避免写入空值导致 DB 错误
        data = {k: v for k, v in data.items() if v is not None or k not in ("entity",)}
        if data:
            new_entity = data.get("entity", state.entity)
            if new_entity != state.entity:
                _ensure_unique_state(db, state.action_id, new_entity, exclude_id=state.id)
            for field, value in data.items():
                setattr(state, field, value)
            db.flush()
            db.commit()
            db.refresh(state)
        return _state_response(state)

    def delete_state(self, db: Session, state_id: int, *, actor: User) -> None:
        """删除状态。"""
        state = self._get_writable_state_or_404(db, state_id, actor)
        db.delete(state)
        db.commit()

    # ---------------------------------------------------------------- 取实体

    def _get_writable_precondition_or_404(
        self, db: Session, precondition_id: int, actor: User
    ) -> BusinessPrecondition:
        """获取可写前置条件或。"""
        precondition = db.get(BusinessPrecondition, precondition_id)
        if precondition is None:
            raise not_found("前置条件不存在")
        require_writable_project(db, resolve_action_project_id(db, precondition.action_id), actor)
        return precondition

    def _get_writable_variable_or_404(
        self, db: Session, variable_id: int, actor: User
    ) -> BusinessVariable:
        """获取可写变量或。"""
        variable = db.get(BusinessVariable, variable_id)
        if variable is None:
            raise not_found("业务变量不存在")
        require_writable_project(db, resolve_action_project_id(db, variable.action_id), actor)
        return variable

    def _get_writable_state_or_404(
        self, db: Session, state_id: int, actor: User
    ) -> BusinessState:
        """获取可写状态或。"""
        state = db.get(BusinessState, state_id)
        if state is None:
            raise not_found("业务状态不存在")
        require_writable_project(db, resolve_action_project_id(db, state.action_id), actor)
        return state


def _ensure_unique_variable(
    db: Session, action_id: int, direction: str, name: str, *, exclude_id: int | None = None
) -> None:
    """确保`unique`变量。"""
    query = db.query(BusinessVariable).filter(
        BusinessVariable.action_id == action_id,
        BusinessVariable.direction == direction,
        BusinessVariable.name == name,
    )
    if exclude_id is not None:
        query = query.filter(BusinessVariable.id != exclude_id)
    if query.first() is not None:
        raise conflict("同方向下变量名已存在")


def _ensure_unique_state(
    db: Session, action_id: int, entity: str, *, exclude_id: int | None = None
) -> None:
    """确保`unique`状态。"""
    query = db.query(BusinessState).filter(
        BusinessState.action_id == action_id, BusinessState.entity == entity
    )
    if exclude_id is not None:
        query = query.filter(BusinessState.id != exclude_id)
    if query.first() is not None:
        raise conflict("该动作对此实体已存在状态定义")
