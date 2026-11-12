"""安全测试业务服务与可见性契约的公开入口。"""

from app.features.security_testing.services.access_service import (
    require_manage_project,
    resolve_strategy_project_id,
    resolve_rule_project_id,
)
