"""接口模块（API Module）ORM 模型。

模块属于项目，支持最多两级（parent_id 指向父模块；parent 的 parent 必须为 None）。
每个项目自动存在一个 ``is_default=True``、名为「未分类」的模块：无法识别模块归属的接口落入它。
该默认模块不可删除、不可改名（由服务层校验，数据库层不做 CHECK，保持与既有表一致的灵活性）。

本表为 feature-local，**不**进 `app/models/__init__.py`；由迁移 0003 显式建立。
"""

from sqlalchemy import (
    Boolean,
    Column,
    DateTime,
    ForeignKey,
    Index,
    Integer,
    String,
    UniqueConstraint,
)
from sqlalchemy.sql import func, text

from app.shared.database import Base


class ApiModule(Base):
    """接口模块（最多两级，含项目级「未分类」默认模块）。"""

    __tablename__ = "api_module"
    __table_args__ = (
        UniqueConstraint("project_id", "name", name="uq_api_module_project_name"),
        Index("ix_api_module_project_parent", "project_id", "parent_id"),
        {"comment": "接口模块（最多两级，含项目级未分类默认模块）"},
    )
    # (project_id, name) 唯一：同一项目内模块名不重复；「未分类」因此每项目至多一行。
    # (project_id, parent_id) 复合索引服务于按项目取模块树、按父模块聚合子模块两种主查询形状。

    id = Column(Integer, primary_key=True, index=True, autoincrement=True)
    project_id = Column(
        Integer,
        ForeignKey("project.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
        comment="所属项目ID",
    )
    # 项目被删除时模块级联清除，不留下孤儿模块。
    name = Column(String(100), nullable=False, comment="模块名称")
    parent_id = Column(
        Integer,
        ForeignKey("api_module.id", ondelete="CASCADE"),
        nullable=True,
        comment="父模块ID；为空表示一级模块",
    )
    # parent_id 自引用；两级限制由服务层在 create/移动时校验（父模块的 parent_id 必须为 None）。
    sort = Column(
        Integer, nullable=False, default=0, server_default=text("0"), comment="同级排序，升序"
    )
    is_default = Column(
        Boolean,
        nullable=False,
        default=False,
        server_default=text("false"),
        comment="是否项目级未分类默认模块",
    )
    # is_default=True 的行是「未分类」：不可删、不可改名；由 ensure_default_module 幂等维护。
    created_at = Column(DateTime, nullable=False, server_default=func.now(), comment="创建时间")
    updated_at = Column(
        DateTime, nullable=False, server_default=func.now(), onupdate=func.now(), comment="更新时间"
    )
