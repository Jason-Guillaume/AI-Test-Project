"""模型配置与执行环境配置。

ModelConfiguration.api_key_encrypted 只保存密文，任何接口都不得返回该字段。
Environment.base_url 决定测试流量真正打到哪台服务器，因此写操作仅限平台管理员。
"""

from sqlalchemy import (
    Boolean,
    Column,
    DateTime,
    Float,
    ForeignKey,
    Index,
    Integer,
    JSON,
    String,
    Text,
)
from sqlalchemy.sql import func, text

from app.shared.database import Base


class ModelConfiguration(Base):
    """平台级大模型连接配置。"""

    __tablename__ = "model_configuration"
    __table_args__ = {"comment": "大模型连接、调用参数及启停状态配置"}

    id = Column(Integer, primary_key=True, index=True, autoincrement=True)
    domain_id = Column(String(100), unique=True, nullable=False, index=True, comment="稳定逻辑ID")
    # domain_id 是对外稳定的逻辑键：前端下拉、授权白名单（organization_member.allowed_model_ids）
    # 以及组织级模型分配都只认它，自增 id 仅供内部引用。
    label = Column(String(120), nullable=False, comment="前端展示名称")
    provider = Column(String(50), nullable=False, default="openai-compatible", server_default=text("'openai-compatible'"),
                      comment="模型供应商")
    # 默认值写在 Python 侧（default）与数据库侧（server_default）各一份：
    # 前者服务于 ORM 直接插入，后者服务于绕过 ORM 的写入路径，两者必须保持一致。
    api_base = Column(String(500), nullable=False, comment="OpenAI兼容接口根地址")
    api_key_encrypted = Column(Text, nullable=True, comment="加密后的API Key")
    # 密钥只在库里存密文；响应序列化必须剔除或掩码该字段，任何接口都不返回明文（密钥掩码约定）。
    model_name = Column(String(200), nullable=False, comment="供应商模型名称")
    temperature = Column(Float, nullable=False, default=0.2, server_default=text("0.2"), comment="采样温度")
    max_tokens = Column(Integer, nullable=False, default=4096, server_default=text("4096"), comment="最大输出Token")
    timeout = Column(Integer, nullable=False, default=60, server_default=text("60"), comment="请求超时秒数")
    cost_per_1k_input = Column(Float, nullable=False, default=0.0, server_default=text("0"), comment="千输入Token成本")
    cost_per_1k_output = Column(Float, nullable=False, default=0.0, server_default=text("0"), comment="千输出Token成本")
    is_enabled = Column(Boolean, nullable=False, default=True, server_default=text("true"), index=True, comment="是否启用")
    # is_enabled 与 is_default 都建了索引：列表页按启用态过滤、调用链按默认态挑选，都是高频路径。
    is_default = Column(Boolean, nullable=False, default=False, server_default=text("false"), index=True,
                        comment="是否默认模型")
    # 平台级「默认模型」标记，语义上应保证最多只有一个为真——写入方负责维护该不变量。
    sort_order = Column(Integer, nullable=False, default=0, server_default=text("0"), comment="展示顺序")
    created_by = Column(Integer, ForeignKey("user.id"), nullable=True, comment="创建人ID")
    created_at = Column(DateTime, nullable=False, server_default=func.now(), comment="创建时间")
    updated_at = Column(DateTime, nullable=False, server_default=func.now(), onupdate=func.now(), comment="更新时间")


class Environment(Base):
    """一个被测环境的路由配置（dev/test/staging/prod 或自定义）。"""

    __tablename__ = "environment"
    __table_args__ = (
        Index("ix_environment_active_default", "is_active", "is_default"),
        {"comment": "接口执行环境路由配置"},
    )
    # 上面这个 (is_active, is_default) 复合索引服务于最热的一条查询：
    # 「当前生效的默认环境」（先按 is_active 过滤，再取 is_default 为真者）。

    id = Column(Integer, primary_key=True, index=True, autoincrement=True)
    # name 会被写进执行记录等列（String(50)），长度需保持一致。
    name = Column(String(50), nullable=False, unique=True, index=True, comment="环境唯一标识，如 dev/test")
    display_name = Column(String(100), nullable=False, default="", server_default=text("''"), comment="展示名称")
    base_url = Column(String(500), nullable=False, default="", server_default=text("''"), comment="被测服务基础URL")
    # 危险字段：它决定测试流量真正打到哪台服务器，因此写操作仅限平台管理员（见模块 docstring）。
    gateway_prefix = Column(String(200), nullable=False, default="", server_default=text("''"), comment="网关路径前缀")
    default_headers = Column(JSON, nullable=False, default=dict, server_default=text("'{}'"), comment="该环境默认请求头")
    description = Column(Text, nullable=True, comment="环境用途说明")
    is_default = Column(Boolean, nullable=False, default=False, server_default=text("false"), index=True,
                        comment="未指定环境时的兜底")
    is_active = Column(Boolean, nullable=False, default=True, server_default=text("true"), index=True,
                       comment="停用后不可被选择")
    # 停用不是删除：停用后选择器与执行链路都跳过该环境，但历史执行记录仍引用它。
    created_by = Column(Integer, ForeignKey("user.id", ondelete="SET NULL"), nullable=True, index=True)
    updated_by = Column(Integer, ForeignKey("user.id", ondelete="SET NULL"), nullable=True, index=True)
    # 这两个外键带 ondelete="SET NULL"：审计人账号被删时保留环境配置本身，只清掉操作者引用。
    created_at = Column(DateTime, nullable=False, server_default=func.now())
    updated_at = Column(DateTime, nullable=False, server_default=func.now(), onupdate=func.now())
