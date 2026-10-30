"""本领域路由使用的无状态服务装配；不拥有请求事务。"""

from __future__ import annotations

from app.features.business.services.binding_service import BindingService
from app.features.business.services.config_service import ConfigService
from app.features.business.services.domain_service import DomainService
from app.features.business.services.execution_service import ExecutionService
from app.features.business.services.flow_service import FlowService
from app.features.business.services.ref_service import RefService
from app.features.business.services.rule_service import RuleService


_DOMAIN = DomainService()


_FLOW = FlowService()


_CONFIG = ConfigService()


_BINDING = BindingService()


_REF = RefService()


_RULE = RuleService()


_EXECUTION = ExecutionService()
