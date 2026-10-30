"""接口（API Interface）ORM 模型。

接口归属于项目与模块；唯一性按 ``project_id + method + path`` 判断（去重键），
重新导入已有接口不会重复创建，而是走变更检测（UPDATED）。

status ∈ {ACTIVE, DRAFT, DEPRECATED, DEVELOPING, MOCK}；source_type ∈
{MANUAL, CURL, OPENAPI, SWAGGER, POSTMAN, APIFOX}；合法性由服务层校验，数据库不设 CHECK。

source_hash 为 Internal API Schema 规范化后的 sha256，用于快速判断接口是否有变更。

feature-local 表，由迁移 0003 显式建立。
"""

from sqlalchemy import (
    Column,
    DateTime,
    ForeignKey,
    Index,
    Integer,
    String,
    Text,
    UniqueConstraint,
)
from sqlalchemy.sql import func, text

from app.core.database.base import Base


class ApiInterface(Base):
    """接口定义（去重键：project_id + method + path）。"""

    __tablename__ = "api_interface"
    __table_args__ = (
        UniqueConstraint("project_id", "method", "path", name="uq_api_interface_project_method_path"),
        Index("ix_api_interface_project_module", "project_id", "module_id"),
        Index("ix_api_interface_source_hash", "source_hash"),
        {"comment": "接口定义（去重键：project_id + method + path）"},
    )
    # 去重唯一约束：(project_id, method, path) —— 重新导入同 method+path 的接口不会重复创建。
    # (project_id, module_id) 索引服务于按模块列接口；source_hash 索引服务于快速变更比对。

    id = Column(Integer, primary_key=True, index=True, autoincrement=True)
    project_id = Column(
        Integer,
        ForeignKey("project.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
        comment="所属项目ID",
    )
    module_id = Column(
        Integer,
        ForeignKey("api_module.id", ondelete="SET NULL"),
        nullable=True,
        index=True,
        comment="所属模块ID；为空表示未分类",
    )
    # module_id 用 SET NULL：模块被删时接口不丢，回落到未分类（由服务层再归位）。
    name = Column(String(200), nullable=False, comment="接口名称")
    description = Column(String(1000), nullable=True, comment="接口描述")
    method = Column(String(10), nullable=False, index=True, comment="HTTP方法：GET/POST/...")
    path = Column(String(500), nullable=False, comment="接口路径，可含 {param} 模板")
    auth_type = Column(
        String(30), nullable=False, default="none", server_default=text("'none'"), comment="鉴权类型"
    )
    content_type = Column(
        String(100), nullable=False, default="application/json", server_default=text("'application/json'"),
        comment="请求内容类型",
    )
    status = Column(
        String(20), nullable=False, default="DRAFT", server_default=text("'DRAFT'"),
        index=True, comment="状态：ACTIVE/DRAFT/DEPRECATED/DEVELOPING/MOCK",
    )
    source_type = Column(
        String(20), nullable=False, default="MANUAL", server_default=text("'MANUAL'"),
        comment="来源：MANUAL/CURL/OPENAPI/SWAGGER/POSTMAN/APIFOX",
    )
    version = Column(
        Integer, nullable=False, default=1, server_default=text("1"), comment="接口版本号，每次更新+1"
    )
    # 注意：source_hash 的索引只由 __table_args__ 里的显式 Index 提供，
    # 这里不能再写 index=True —— 那会自动生成同名索引 ix_api_interface_source_hash，
    # create_all（AUTO_CREATE_SCHEMA=true 的本地开关）会重复建同名索引而报
    # DuplicateTable（迁移 0003 走显式 op 建表，掩盖了这个冲突）。
    source_hash = Column(
        String(64), nullable=True, comment="Internal Schema 规范化 sha256，用于变更比对"
    )
    created_at = Column(DateTime, nullable=False, server_default=func.now(), comment="创建时间")
    updated_at = Column(
        DateTime, nullable=False, server_default=func.now(), onupdate=func.now(), comment="更新时间"
    )
