"""自动化测试中心 ORM 导出。"""

from app.features.automation_center.models.entities import (
    AutomationArtifact,
    AutomationCallbackReceipt,
    AutomationExecution,
    AutomationIntegrationConfig,
    AutomationPipeline,
    AutomationProject,
    AutomationReport,
    AutomationReportGrant,
)

__all__ = [
    "AutomationArtifact",
    "AutomationCallbackReceipt",
    "AutomationExecution",
    "AutomationIntegrationConfig",
    "AutomationPipeline",
    "AutomationProject",
    "AutomationReport",
    "AutomationReportGrant",
]
