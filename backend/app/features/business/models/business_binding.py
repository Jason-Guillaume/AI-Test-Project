"""业务绑定（Business Binding）ORM 模型。

业务动作不直接保存接口 ID，而是通过独立的 Binding 建立 action ↔ 接口的关系。
binding_type 预留 API/WEB/MOBILE 三种通道，当前第一阶段只真正支持 API：通过 api_id
引用接口管理（api_catalog）的 api_interface 表。

关键设计：api_id 外键 ondelete=SET NULL（**非** CASCADE）——接口被删除时绑定行保留、
api_id 置空，服务层据此识别「绑定接口已失效」。若用 CASCADE 会静默删除绑定、隐藏断裂，
违背「失效可见」的要求。接口状态（DEPRECATED 等）在服务层按需联查 ApiInterface 判断。

feature-local 表，由迁移 0004 显式建立。
"""

from sqlalchemy import JSON, Boolean, Column, DateTime, ForeignKey, Index, Integer, String, UniqueConstraint
from sqlalchemy.sql import func, text

from app.shared.database import Base


class BusinessBinding(Base):
    """业务绑定：业务动作与具体执行接口（API/Web/Mobile）的关系。"""

    __tablename__ = "business_binding"
    __table_args__ = (
        UniqueConstraint("action_id", "binding_type", name="uq_business_binding_action_type"),
        {"comment": "业务绑定：业务动作与具体执行接口的关系"},
    )
    # 唯一约束 (action_id, binding_type)：同一动作对同一通道（API/WEB/MOBILE）最多一个绑定。

    id = Column(Integer, primary_key=True, index=True, autoincrement=True)
    action_id = Column(
        Integer,
        ForeignKey("business_action.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
        comment="所属业务动作ID",
    )
    # action_id 带 ondelete=CASCADE：动作被删除时绑定一并清理。
    binding_type = Column(
        String(20), nullable=False, default="API", server_default=text("'API'"),
        comment="绑定通道：API/WEB/MOBILE（第一阶段仅 API 真正可用）",
    )
    api_id = Column(
        Integer,
        ForeignKey("api_interface.id", ondelete="SET NULL"),
        nullable=True,
        index=True,
        comment="绑定的接口ID（api_catalog.ApiInterface）；接口删除后置空，由服务层标记失效",
    )
    # api_id 用 ondelete=SET NULL（**非** CASCADE）：接口被删除时绑定保留、api_id 置空，
    # 服务层据此渲染「绑定接口已失效」。CASCADE 会静默删绑定、隐藏断裂，违背失效可见要求。
    # 跨 feature 引用接口管理表：仅外键 + 按需联查，不复制接口 Schema。
    config_json = Column(
        JSON, nullable=True,
        comment="通道相关配置（如超时、请求头覆盖等），第一阶段主要为预留",
    )
    enabled = Column(
        Boolean, nullable=False, default=True, server_default=text("true"), comment="是否启用该绑定",
    )
    created_at = Column(DateTime, nullable=False, server_default=func.now(), comment="创建时间")
    updated_at = Column(
        DateTime, nullable=False, server_default=func.now(), onupdate=func.now(), comment="更新时间",
    )
