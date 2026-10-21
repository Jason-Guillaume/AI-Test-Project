"""Security Testing Phase 2 ORM 模型（OWASP ZAP 集成）。

六张 feature-local 表，**不进 app/models/__init__.py**（红线 17），由迁移 0012 显式建表：

- security_scan_target：扫描目标。base_url / entry_url 创建时必须过 scope_guard，
  authorization_status 只有 AUTHORIZED 才允许发起扫描；active_scan_allowed 是环境
  级主动扫描开关的显式记录（Staging 默认关闭）。
- security_scan_profile：扫描策略。内置 6 个（code 非空、is_builtin=True、created_by 为空），
  Agent 只能选后端已批准的 Profile，不能自己拼参数。
- security_scan_auth_profile：认证配置。**只存密文**（token / session 值经
  encrypt_secret），任何接口都不回显明文（§十一）。
- security_scan_job：一次扫描任务。是 Phase 2 自己的任务记录，不是伪造的 CaseExecution
  （§二十二）；test_run_id 可空，报告层做统一聚合。
- security_scan_event：过程事件。是审计记录，不是日志替代品；payload_json 必须先脱敏
  （§二十一「不存原始敏感 Request/Response」）。
- security_scan_finding：扫描任务与 security_finding 的多对多关系表。Finding 本身复用
  Phase 1 的表与部分唯一索引，这里只记录「哪次扫描命中了哪条 Finding」，重复扫描不重置
  人工确认状态（§十九、§二十）。
"""

from app.features.security_testing.zap.models.auth_profile import SecurityScanAuthProfile
from app.features.security_testing.zap.models.finding_link import SecurityScanFinding
from app.features.security_testing.zap.models.job import SecurityScanEvent, SecurityScanJob
from app.features.security_testing.zap.models.profile import SecurityScanProfile
from app.features.security_testing.zap.models.target import SecurityScanTarget

__all__ = [
    "SecurityScanAuthProfile",
    "SecurityScanEvent",
    "SecurityScanFinding",
    "SecurityScanJob",
    "SecurityScanProfile",
    "SecurityScanTarget",
]
