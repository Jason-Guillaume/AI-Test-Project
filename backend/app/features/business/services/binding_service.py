"""业务绑定 / API 映射服务层。

业务动作通过独立的 Binding 与 API 或 Web 用例建立关系；API 绑定使用 api_id 引用
接口管理（api_catalog）的 api_interface 表，Web 绑定通过 config_json 引用 Web 用例。

失效判定（「失效可见」要求）：
- api_id 为 None（接口被硬删 → ondelete=SET NULL 置空）→ valid=False，「已删除」。
- api_id 非空但接口行不存在（异常残留）→ valid=False，「已删除」。
- 接口 status == DEPRECATED → valid=False，「已废弃」。
- 其余 → valid=True。

跨 feature 引用：仅 import ApiInterface 模型类做按主键只读联查，不调用 api_catalog
service、不复制接口 Schema（遵循「通过 api_id 建立关系」约定，避免循环依赖与事务分裂）。
"""

from __future__ import annotations

from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.features.api_catalog.models.api_interface import ApiInterface
from app.features.business.models.business_api_mapping import BusinessApiMapping
from app.features.business.models.business_binding import BusinessBinding
from app.features.business.schemas import (
    BusinessApiMappingCreate,
    BusinessApiMappingResponse,
    BusinessApiMappingUpdate,
    BusinessBindingCreate,
    BusinessBindingDetailResponse,
    BusinessBindingResponse,
    BusinessBindingUpdate,
)
from app.features.business.services._access import (
    get_project_or_404,
    require_writable_project,
    resolve_action_project_id,
    resolve_binding_project_id,
)
from app.models.identity import User
from app.shared.errors import bad_request, conflict, not_found
from app.shared.notify import notify

# OUTPUT 映射只能取 RESPONSE；INPUT 映射取 BODY/HEADER/QUERY/PATH（不含 RESPONSE）。
_INPUT_LOCATIONS = {"BODY", "HEADER", "QUERY", "PATH"}


def _mapping_response(m: BusinessApiMapping) -> BusinessApiMappingResponse:
    """构造映射响应数据。"""
    return BusinessApiMappingResponse.model_validate(m)


def _validate_mapping_location(direction: str, api_location: str) -> None:
    """校验映射方向与接口位置一致性，捕捉明显的客户端配置错误。"""
    if direction == "OUTPUT" and api_location != "RESPONSE":
        raise bad_request("OUTPUT 映射的接口位置必须为 RESPONSE")
    if direction == "INPUT" and api_location not in _INPUT_LOCATIONS:
        raise bad_request("INPUT 映射的接口位置必须为 BODY/HEADER/QUERY/PATH")


def _binding_detail(db: Session, binding: BusinessBinding) -> BusinessBindingDetailResponse:
    """由绑定构造详情：基本信息 + 失效判定 + 输入/输出映射。

    被 flow_service.get_flow_detail 复用，保证详情与单条查询口径一致。
    """
    base = BusinessBindingResponse.model_validate(binding)
    valid = True
    invalid_reason: str | None = None
    api_name = api_method = api_path = api_status = None

    if binding.api_id is None:
        # api_id 为 None 的情况：
        # - API 绑定：ondelete=SET NULL 置空 → 接口已被硬删，绑定失效
        # - WEB 绑定：api_id 设计上为空，不视为失效
        if binding.binding_type == "API":
            valid = False
            invalid_reason = "绑定接口已失效（已删除）"
        else:
            # WEB 通道绑定的 api_id 为空属正常，具体有效性由 Web 用例关系判断。
            pass
    else:
        iface = db.get(ApiInterface, binding.api_id)
        if iface is None:
            valid = False
            invalid_reason = "绑定接口已失效（已删除）"
        else:
            api_name = iface.name
            api_method = iface.method
            api_path = iface.path
            api_status = iface.status
            if iface.status == "DEPRECATED":
                valid = False
                invalid_reason = "绑定接口已废弃"

    if binding.binding_type == "WEB":
        from app.features.test_management.models.test_case import TestCase
        from app.features.web_ui.models import WebCase
        case_id = (binding.config_json or {}).get("web_case_id")
        case = db.get(TestCase, case_id) if isinstance(case_id, int) else None
        valid = bool(case and case.project_id == resolve_binding_project_id(db, binding.id) and db.get(WebCase, case_id))
        invalid_reason = None if valid else "绑定的 Web 用例已失效"
    elif binding.binding_type == "MOBILE":
        # 历史预留值只保留可读性，不再允许新建、更新或参与流程执行。
        valid = False
        invalid_reason = "移动端绑定尚未接入，不能用于执行"

    mappings = (
        db.query(BusinessApiMapping)
        .filter(BusinessApiMapping.binding_id == binding.id)
        .order_by(BusinessApiMapping.id.asc())
        .all()
    )
    input_mappings = [_mapping_response(m) for m in mappings if m.direction == "INPUT"]
    output_mappings = [_mapping_response(m) for m in mappings if m.direction == "OUTPUT"]
    return BusinessBindingDetailResponse(
        **base.model_dump(),
        valid=valid,
        invalid_reason=invalid_reason,
        api_name=api_name,
        api_method=api_method,
        api_path=api_path,
        api_status=api_status,
        input_mappings=input_mappings,
        output_mappings=output_mappings,
    )


def _ensure_api_in_project(db: Session, api_id: int | None, project_id: int) -> None:
    """若指定了 api_id，校验接口存在且属于同一项目（跨资源不一致 → not_found/bad_request）。"""
    if api_id is None:
        return
    iface = db.get(ApiInterface, api_id)
    if iface is None:
        raise not_found("接口不存在")
    if iface.project_id != project_id:
        raise bad_request("接口必须属于当前业务流程所在项目")


def _ensure_web_in_project(db, config, api_id, project_id):
    """WEB 通道只接受同项目 Web 用例引用，通用绑定入口也不能保存脚本配置。"""
    if api_id is not None or not isinstance(config, dict) or set(config) != {"web_case_id"} or type(config["web_case_id"]) is not int:
        raise bad_request("WEB 绑定只允许 config_json.web_case_id，不接受接口或脚本")
    from app.features.test_management.models.test_case import TestCase
    from app.features.web_ui.models import WebCase
    case_id = config["web_case_id"]
    case = db.get(TestCase, case_id)
    if case is None or case.project_id != project_id or db.get(WebCase, case_id) is None:
        raise not_found("Web 用例不存在")


class BindingService:
    """业务绑定与 API 映射服务。无状态，路由层复用单例。"""

    # ---------------------------------------------------------------- 绑定

    def list_bindings(
        self, db: Session, action_id: int, user: User
    ) -> list[BusinessBindingDetailResponse]:
        """列出`bindings`。"""
        get_project_or_404(db, resolve_action_project_id(db, action_id), user)
        bindings = (
            db.query(BusinessBinding)
            .filter(BusinessBinding.action_id == action_id)
            .order_by(BusinessBinding.id.asc())
            .all()
        )
        return [_binding_detail(db, b) for b in bindings]

    def get_binding(self, db: Session, binding_id: int, user: User) -> BusinessBindingDetailResponse:
        """获取绑定。"""
        binding = self._get_binding_or_404(db, binding_id, user)
        return _binding_detail(db, binding)

    def create_binding(
        self, db: Session, action_id: int, body: BusinessBindingCreate, *, actor: User
    ) -> BusinessBindingDetailResponse:
        """创建绑定。"""
        project = require_writable_project(db, resolve_action_project_id(db, action_id), actor)
        _ensure_api_in_project(db, body.api_id, project.id)
        if body.binding_type == "WEB":
            _ensure_web_in_project(db, body.config_json, body.api_id, project.id)
        # 多绑定支持：同一动作允许多个同通道绑定，但 is_default 唯一（部分唯一索引保障）。
        # 若新建 is_default=True，先将同 action+binding_type 的旧默认取消。
        if body.is_default:
            old_defaults = (
                db.query(BusinessBinding)
                .filter(
                    BusinessBinding.action_id == action_id,
                    BusinessBinding.binding_type == body.binding_type,
                    BusinessBinding.is_default.is_(True),
                )
                .all()
            )
            for old in old_defaults:
                old.is_default = False
        binding = BusinessBinding(
            action_id=action_id,
            binding_type=body.binding_type,
            api_id=body.api_id,
            name=body.name,
            is_default=body.is_default,
            sort=body.sort,
            config_json=body.config_json,
            enabled=body.enabled,
        )
        db.add(binding)
        try:
            db.flush()
            notify(
                db,
                user_id=actor.id,
                event_type="business.binding.created",
                title="你已为业务动作绑定接口",
                project_id=project.id,
                actor_id=actor.id,
                actor_username=actor.username,
                detail={"binding_id": binding.id, "action_id": action_id, "api_id": body.api_id},
            )
            db.commit()
        except IntegrityError:
            # 部分唯一索引 ix_business_binding_action_default 拦下了重复默认绑定
            # （并发创建、或库中残留了未被服务层查到的旧默认行）。
            # 必须先 rollback：IntegrityError 之后 session 处于失效状态，直接复用会抛 PendingRollbackError。
            db.rollback()
            raise conflict("同一动作的同一绑定通道下已存在默认绑定，请取消另一条绑定的默认标记后再试")
        db.refresh(binding)
        return _binding_detail(db, binding)

    def update_binding(
        self, db: Session, binding_id: int, body: BusinessBindingUpdate, *, actor: User
    ) -> BusinessBindingDetailResponse:
        """更新绑定。"""
        binding = self._get_writable_binding_or_404(db, binding_id, actor)
        data = body.model_dump(exclude_unset=True)
        # 过滤 NOT NULL 字段的 None 值，避免写入空值导致 DB 错误
        data = {k: v for k, v in data.items() if v is not None or k not in ("binding_type",)}
        if not data:
            return _binding_detail(db, binding)
        if data.get("binding_type", binding.binding_type) == "WEB":
            _ensure_web_in_project(db, data.get("config_json", binding.config_json),
                                   data.get("api_id", binding.api_id), resolve_binding_project_id(db, binding_id))
        if "api_id" in data:
            # api_id 变更时重新校验接口归属；None 表示解绑（允许）。
            _ensure_api_in_project(db, data["api_id"], resolve_binding_project_id(db, binding_id))
        # is_default 切换：若设为 True，先将同 action+binding_type 的旧默认取消。
        if data.get("is_default") is True and not binding.is_default:
            old_defaults = (
                db.query(BusinessBinding)
                .filter(
                    BusinessBinding.action_id == binding.action_id,
                    BusinessBinding.binding_type == binding.binding_type,
                    BusinessBinding.is_default.is_(True),
                    BusinessBinding.id != binding.id,
                )
                .all()
            )
            for old in old_defaults:
                old.is_default = False
        for field, value in data.items():
            setattr(binding, field, value)
        try:
            db.flush()
            db.commit()
        except IntegrityError:
            # 同上：部分唯一索引兜底。取消旧默认与本条更新在同一事务内，
            # 正常路径不会触发；残留脏数据（旧库里已有多条默认绑定）或并发切换时命中。
            db.rollback()
            raise conflict("同一动作的同一绑定通道下已存在默认绑定，请取消另一条绑定的默认标记后再试")
        db.refresh(binding)
        return _binding_detail(db, binding)

    def delete_binding(self, db: Session, binding_id: int, *, actor: User) -> None:
        """删除绑定。"""
        binding = self._get_writable_binding_or_404(db, binding_id, actor)
        # 级联：删除绑定 → 其下 api_mapping 由外键 ondelete=CASCADE 一并清理。
        db.delete(binding)
        db.commit()

    # ---------------------------------------------------------------- 映射

    def list_mappings(
        self, db: Session, binding_id: int, user: User
    ) -> list[BusinessApiMappingResponse]:
        """列出`mappings`。"""
        self._get_binding_or_404(db, binding_id, user)
        items = (
            db.query(BusinessApiMapping)
            .filter(BusinessApiMapping.binding_id == binding_id)
            .order_by(BusinessApiMapping.id.asc())
            .all()
        )
        return [_mapping_response(m) for m in items]

    def create_mapping(
        self, db: Session, binding_id: int, body: BusinessApiMappingCreate, *, actor: User
    ) -> BusinessApiMappingResponse:
        """创建映射。"""
        project = require_writable_project(db, resolve_binding_project_id(db, binding_id), actor)
        _validate_mapping_location(body.direction, body.api_location)
        # 唯一约束 (binding_id, direction, business_variable)：同绑定同方向同变量重复 → 冲突。
        existing = (
            db.query(BusinessApiMapping)
            .filter(
                BusinessApiMapping.binding_id == binding_id,
                BusinessApiMapping.direction == body.direction,
                BusinessApiMapping.business_variable == body.business_variable,
            )
            .first()
        )
        if existing is not None:
            raise conflict("该变量在此方向上已存在映射")
        mapping = BusinessApiMapping(
            binding_id=binding_id,
            direction=body.direction,
            business_variable=body.business_variable,
            api_location=body.api_location,
            api_field=body.api_field,
            expression=body.expression,
        )
        db.add(mapping)
        db.flush()
        notify(
            db,
            user_id=actor.id,
            event_type="business.mapping.created",
            title="你已配置业务变量映射",
            project_id=project.id,
            actor_id=actor.id,
            actor_username=actor.username,
            detail={"mapping_id": mapping.id, "binding_id": binding_id},
        )
        db.commit()
        db.refresh(mapping)
        return _mapping_response(mapping)

    def update_mapping(
        self, db: Session, mapping_id: int, body: BusinessApiMappingUpdate, *, actor: User
    ) -> BusinessApiMappingResponse:
        """更新映射。"""
        mapping = self._get_writable_mapping_or_404(db, mapping_id, actor)
        data = body.model_dump(exclude_unset=True)
        # 过滤 NOT NULL 字段的 None 值，避免写入空值导致 DB 错误
        data = {k: v for k, v in data.items() if v is not None or k not in ("direction", "business_variable", "api_location")}
        if not data:
            return _mapping_response(mapping)
        new_direction = data.get("direction", mapping.direction)
        new_location = data.get("api_location", mapping.api_location)
        _validate_mapping_location(new_direction, new_location)
        for field, value in data.items():
            setattr(mapping, field, value)
        db.flush()
        db.commit()
        db.refresh(mapping)
        return _mapping_response(mapping)

    def delete_mapping(self, db: Session, mapping_id: int, *, actor: User) -> None:
        """删除映射。"""
        mapping = self._get_writable_mapping_or_404(db, mapping_id, actor)
        db.delete(mapping)
        db.commit()

    # ---------------------------------------------------------------- 取实体

    def _get_binding_or_404(
        self, db: Session, binding_id: int, user: User
    ) -> BusinessBinding:
        """获取绑定或。"""
        binding = db.get(BusinessBinding, binding_id)
        if binding is None:
            raise not_found("业务绑定不存在")
        get_project_or_404(db, resolve_action_project_id(db, binding.action_id), user)
        return binding

    def _get_writable_binding_or_404(
        self, db: Session, binding_id: int, actor: User
    ) -> BusinessBinding:
        """获取可写绑定或。"""
        binding = db.get(BusinessBinding, binding_id)
        if binding is None:
            raise not_found("业务绑定不存在")
        require_writable_project(db, resolve_action_project_id(db, binding.action_id), actor)
        return binding

    def _get_writable_mapping_or_404(
        self, db: Session, mapping_id: int, actor: User
    ) -> BusinessApiMapping:
        """获取可写映射或。"""
        mapping = db.get(BusinessApiMapping, mapping_id)
        if mapping is None:
            raise not_found("业务映射不存在")
        require_writable_project(db, resolve_binding_project_id(db, mapping.binding_id), actor)
        return mapping
