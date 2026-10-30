"""业务绑定（Business Binding）ORM 模型。

业务动作不直接保存接口 ID，而是通过独立的 Binding 建立 action ↔ API 或 Web 用例的关系。
API 通道通过 api_id 引用接口管理（api_catalog）的 api_interface 表；Web 通道引用 Web 用例。
MOBILE 是历史预留值，当前不接受新建或更新，也不参与流程执行。

关键设计：api_id 外键 ondelete=SET NULL（**非** CASCADE）——接口被删除时绑定行保留、
api_id 置空，服务层据此识别「绑定接口已失效」。若用 CASCADE 会静默删除绑定、隐藏断裂，
违背「失效可见」的要求。接口状态（DEPRECATED 等）在服务层按需联查 ApiInterface 判断。

feature-local 表，由迁移 0004 显式建立。
"""

from sqlalchemy import JSON, Boolean, Column, DateTime, ForeignKey, Index, Integer, String, UniqueConstraint
from sqlalchemy.sql import func, text

from app.core.database.base import Base


class BusinessBinding(Base):
    """业务绑定：业务动作与 API 接口或 Web 用例的关系。"""

    __tablename__ = "business_binding"
    __table_args__ = (
        # 部分唯一索引：同一 action + binding_type 最多一个默认绑定（is_default=True）。
        # 与迁移 0005 里的 CREATE UNIQUE INDEX IF NOT EXISTS 同名同义——必须在 ORM 声明，
        # 否则走 AUTO_CREATE_SCHEMA（Base.metadata.create_all、不跑 Alembic）建出的库缺这条约束。
        Index(
            "ix_business_binding_action_default",
            "action_id", "binding_type",
            unique=True,
            postgresql_where=text("is_default = true"),
        ),
        {"comment": "业务绑定：业务动作与具体执行接口的关系"},
    )

    id = Column(Integer, primary_key=True, index=True, autoincrement=True)
    action_id = Column(
        Integer,
        ForeignKey("business_action.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
        comment="所属业务动作ID",
    )
    binding_type = Column(
        String(20), nullable=False, default="API", server_default=text("'API'"),
        comment="绑定通道：API/WEB；MOBILE 为历史预留值",
    )
    name = Column(
        String(200), nullable=True,
        comment="绑定名称（如 API v1 / API v2）",
    )
    is_default = Column(
        Boolean, nullable=False, default=True, server_default=text("true"),
        comment="是否为默认绑定（执行时使用）",
    )
    sort = Column(
        Integer, nullable=False, default=0, server_default=text("0"),
        comment="绑定排序值",
    )
    api_id = Column(
        Integer,
        ForeignKey("api_interface.id", ondelete="SET NULL"),
        nullable=True,
        index=True,
        comment="绑定的接口ID（api_catalog.ApiInterface）；接口删除后置空，由服务层标记失效",
    )
    config_json = Column(
        JSON, nullable=True,
        comment="通道相关配置（如超时、请求头覆盖等）",
    )
    enabled = Column(
        Boolean, nullable=False, default=True, server_default=text("true"), comment="是否启用该绑定",
    )
    created_at = Column(DateTime, nullable=False, server_default=func.now(), comment="创建时间")
    updated_at = Column(
        DateTime, nullable=False, server_default=func.now(), onupdate=func.now(), comment="更新时间",
    )
