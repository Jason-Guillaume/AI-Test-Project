"""业务动作的唯一默认绑定读取与用例目标准备；不生成数据、不发请求。"""

from __future__ import annotations

from sqlalchemy.orm import Session
from app.features.business.models.business_binding import BusinessBinding
from app.features.api_catalog.models.api_interface import ApiInterface
from app.features.business.executors.contracts import PreparedActionTarget


def load_default_binding(db: Session, action_id: int, binding_type: str) -> BusinessBinding | None:
    """复用原默认/启用条件，不跨调用或跨项目缓存。"""
    return db.query(BusinessBinding).filter_by(
        action_id=action_id, binding_type=binding_type, is_default=True, enabled=True,
    ).first()


def prepare_case_action_target(db: Session, action_id: int, project_id: int) -> PreparedActionTarget:
    """按原 Web 优先顺序检查目标；错误先于 Faker/Fixture 数据解析。"""
    binding = load_default_binding(db, action_id, "WEB")
    if binding is not None:
        return PreparedActionTarget(binding=binding)
    binding = load_default_binding(db, action_id, "API")
    if binding is None or binding.api_id is None:
        return PreparedActionTarget(error_code="DEFAULT_BINDING_NOT_FOUND", error_message="业务动作未配置默认 API 绑定")
    interface = db.get(ApiInterface, binding.api_id)
    if interface is None or interface.project_id != project_id:
        return PreparedActionTarget(error_code="API_NOT_FOUND", error_message="绑定接口已失效")
    return PreparedActionTarget(binding=binding, interface=interface)
