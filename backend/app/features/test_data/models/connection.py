"""被测库连接与数据库访问策略 ORM 模型。

target_database_connection 是被测库（不是平台库）连接。password_encrypted 只存
`encrypt_secret` 结果，任何读 API 都只回 `password_set: true`。

database_access_policy 的写权限是平台管理员：Environment 本身是平台级危险配置，
项目成员可读本项目策略但不能改环境开关。

模型 feature-local，不进 app/models/__init__.py；由 alembic 0009 显式建表。
"""

from sqlalchemy import Boolean, Column, DateTime, ForeignKey, Index, Integer, JSON, String, Text, UniqueConstraint
from sqlalchemy.sql import func, text

from app.core.database.base import Base


class TargetDatabaseConnection(Base):
    """被测库连接（非平台库）。第一阶段只支持 PostgreSQL。"""

    __tablename__ = "target_database_connection"
    __table_args__ = (
        UniqueConstraint(
            "project_id", "environment_id", "name", name="uq_target_db_conn"
        ),
        {"comment": "被测库连接（非平台库），password 只存 encrypt_secret 结果"},
    )

    id = Column(Integer, primary_key=True, index=True, autoincrement=True)
    project_id = Column(
        Integer, ForeignKey("project.id", ondelete="CASCADE"),
        nullable=False, index=True, comment="所属项目ID",
    )
    environment_id = Column(
        Integer, ForeignKey("environment.id", ondelete="RESTRICT"),
        nullable=False, index=True,
        comment="绑定环境ID（RESTRICT：删环境需先处理连接）",
    )
    name = Column(String(200), nullable=False, comment="连接名称")
    host = Column(String(255), nullable=False, comment="主机地址")
    port = Column(
        Integer, nullable=False, default=5432, server_default=text("5432"), comment="端口，默认 5432",
    )
    database_name = Column(String(128), nullable=False, comment="数据库名")
    username = Column(String(128), nullable=False, comment="用户名")
    password_encrypted = Column(
        Text, nullable=False, comment="encrypt_secret 结果，禁止存储明文，禁止回显",
    )
    schema_name = Column(
        String(128), nullable=True, comment="schema 名（作为 search_path，表名仍是裸标识符）",
    )
    enabled = Column(
        Boolean, nullable=False, default=True, server_default=text("true"), comment="是否启用",
    )
    created_by = Column(Integer, ForeignKey("user.id", ondelete="SET NULL"), nullable=True, comment="创建人")
    created_at = Column(DateTime, nullable=False, server_default=func.now(), comment="创建时间")
    updated_at = Column(
        DateTime, nullable=False, server_default=func.now(), onupdate=func.now(), comment="更新时间",
    )


class DatabaseAccessPolicy(Base):
    """数据库访问策略：表白名单 + 操作白名单。

    PRODUCTION 归类的环境 enabled 强制 false，服务层拒绝写成 true；
    DEV / TEST 也要求存在策略行（没有策略 = 拒绝），不做「开发环境默许」。
    """

    __tablename__ = "database_access_policy"
    __table_args__ = (
        UniqueConstraint("project_id", "environment_id", name="uq_db_policy_project_env"),
        {"comment": "数据库访问策略：表白名单 + 操作白名单，PRODUCTION 强制关闭"},
    )

    id = Column(Integer, primary_key=True, index=True, autoincrement=True)
    project_id = Column(
        Integer, ForeignKey("project.id", ondelete="CASCADE"),
        nullable=False, index=True, comment="所属项目ID",
    )
    environment_id = Column(
        Integer, ForeignKey("environment.id", ondelete="RESTRICT"),
        nullable=False, index=True, comment="绑定环境ID",
    )
    enabled = Column(
        Boolean, nullable=False, default=False, server_default=text("false"),
        comment="是否允许数据库造数（默认关闭；PRODUCTION 不可开启）",
    )
    allowed_tables = Column(
        JSON, nullable=False, default=list, server_default=text("'[]'"),
        comment="允许的表名数组（精确匹配，不支持通配符与 schema 前缀）",
    )
    allowed_operations = Column(
        JSON, nullable=False, default=list,
        server_default=text("'[\"INSERT\", \"UPDATE\", \"SELECT\"]'"),
        comment="允许的操作数组：INSERT/UPDATE/SELECT（DELETE 需额外双重确认）",
    )
    created_by = Column(Integer, ForeignKey("user.id", ondelete="SET NULL"), nullable=True, comment="创建人")
    created_at = Column(DateTime, nullable=False, server_default=func.now(), comment="创建时间")
    updated_at = Column(
        DateTime, nullable=False, server_default=func.now(), onupdate=func.now(), comment="更新时间",
    )
