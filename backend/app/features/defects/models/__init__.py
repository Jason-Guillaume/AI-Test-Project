"""缺陷模块的 ORM 模型包。

Bug 是缺陷管理的核心实体，回归关联（DefectRegressionLink / TestPoint 等）
在 Phase-1 不接入，见 backend/app/features/defects/__init__.py 中的说明。
"""

from app.features.defects.models.attachment import BugAttachment
from app.features.defects.models.bug import Bug
from app.features.defects.models.share import DefectExternalAction, DefectShareBatch, DefectShareLink
from app.features.defects.models.source_link import DefectSourceLink

__all__ = ["Bug", "BugAttachment", "DefectExternalAction", "DefectShareBatch", "DefectShareLink"]
