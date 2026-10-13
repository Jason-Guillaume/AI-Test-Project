"""缺陷模块的 ORM 模型包。

Bug 是缺陷管理的核心实体，回归关联（DefectRegressionLink / TestPoint 等）
在 Phase-1 不接入，见 backend/app/features/defects/__init__.py 中的说明。
"""

from app.features.defects.models.bug import Bug

__all__ = ["Bug"]
