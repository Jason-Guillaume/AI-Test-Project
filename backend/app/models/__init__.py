"""ORM 模型集合。

所有表定义集中在此包，由 Alembic 通过 Base.metadata 生成迁移；
应用启动不会自动创建或修改表结构。
"""

from app.shared.database import Base
# 下面逐个导入子模块里的模型类，有两个用途：
# 1) 供应用代码复用模型定义；
# 2) 保证 alembic（env.py 与 0001 迁移）导入本包时，所有表都已注册进 Base.metadata，
#    否则 autogenerate 与 create_all 只会看到部分表，生成出缺表的迁移。
# 注意：Bug 模型**不**在此导入。它属于缺陷特性的 feature-local 模型，
# 由 alembic/versions/0002_add_bug_table.py 用显式 op.create_table 建立，
# 若在此导入会同时进入 0001 的 Base.metadata.create_all，导致 0002 再次建表冲突。
from app.models.configuration import Environment, ModelConfiguration
from app.models.identity import Organization, OrganizationMember, User
from app.models.notification import Notification
from app.models.project import Project, ProjectMember, ProjectOutboundTarget

# __all__ 列出本包对外暴露的名字，顺序与上面的导入顺序一致，便于对照排查。
__all__ = [
    "Base",
    "User",
    "Organization",
    "OrganizationMember",
    "Project",
    "ProjectMember",
    "ProjectOutboundTarget",
    "ModelConfiguration",
    "Environment",
    "Notification",
]
