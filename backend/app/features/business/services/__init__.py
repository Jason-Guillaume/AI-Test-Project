"""业务管理服务层入口。

集中导出各子服务，供路由层复用单例。服务无状态，跨请求复用同一实例。
"""

from app.features.business.services.binding_service import BindingService
from app.features.business.services.config_service import ConfigService
from app.features.business.services.domain_service import DomainService
from app.features.business.services.flow_service import FlowService
from app.features.business.services.ref_service import RefService
from app.features.business.services.rule_service import RuleService

__all__ = [
    "BindingService",
    "ConfigService",
    "DomainService",
    "FlowService",
    "RefService",
    "RuleService",
    "resolve_flow_project_id",
    "resolve_action_project_id",
    "resolve_binding_project_id",
]

from app.features.business.services.access_service import (
    resolve_flow_project_id,
    resolve_action_project_id,
    resolve_binding_project_id,
)
