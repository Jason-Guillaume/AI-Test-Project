"""测试报告 ORM 模型集合（feature-local）。

由迁移 0008 显式建表，**不**加入 app/models/__init__.py（否则 0001 的 create_all
会与 0008 的 op.create_table 冲突，见 coding-conventions §2.4 红线 17）。
"""
from app.features.reports.models.report import TestReport

__all__ = ["TestReport"]
