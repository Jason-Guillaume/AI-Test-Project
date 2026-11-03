"""统一模型中心 ORM：资源、不可变修订、参数方案、授权、默认槽位与诊断。"""

from sqlalchemy import Boolean, Column, DateTime, ForeignKey, Index, Integer, JSON, String, Text, UniqueConstraint
from sqlalchemy.sql import func, text

from app.core.database.base import Base


class ModelResource(Base):
    """按类别和可见范围管理的模型逻辑资源。"""

    __tablename__ = "model_resource"
    __table_args__ = (
        Index("ix_model_resource_scope_category", "visibility", "project_id", "category", "status"),
        {"comment": "统一模型逻辑资源；供应商、适配器、能力和任务角色分别存储"},
    )

    id = Column(Integer, primary_key=True, autoincrement=True)
    resource_key = Column(String(120), nullable=False, unique=True, index=True)
    category = Column(String(30), nullable=False, index=True)
    visibility = Column(String(20), nullable=False, server_default=text("'PLATFORM'"))
    project_id = Column(Integer, ForeignKey("project.id", ondelete="CASCADE"), nullable=True, index=True)
    display_name = Column(String(160), nullable=False)
    status = Column(String(20), nullable=False, server_default=text("'ACTIVE'"), index=True)
    current_revision_id = Column(Integer, nullable=True)
    legacy_model_id = Column(Integer, ForeignKey("model_configuration.id", ondelete="SET NULL"), nullable=True, unique=True)
    created_by = Column(Integer, ForeignKey("user.id", ondelete="SET NULL"), nullable=True)
    created_at = Column(DateTime(timezone=True), nullable=False, server_default=func.now())
    updated_at = Column(DateTime(timezone=True), nullable=False, server_default=func.now(), onupdate=func.now())


class ModelRevision(Base):
    """不可变模型连接修订；秘密凭据保存在独立表。"""

    __tablename__ = "model_revision"
    __table_args__ = (UniqueConstraint("resource_id", "version", name="uq_model_revision_version"),)

    id = Column(Integer, primary_key=True, autoincrement=True)
    resource_id = Column(Integer, ForeignKey("model_resource.id", ondelete="CASCADE"), nullable=False, index=True)
    version = Column(Integer, nullable=False)
    provider = Column(String(60), nullable=False)
    adapter_key = Column(String(100), nullable=False)
    model_name = Column(String(200), nullable=False)
    endpoint_ciphertext = Column(Text, nullable=True)
    endpoint_display = Column(String(500), nullable=True)
    config_json = Column(JSON, nullable=False, server_default=text("'{}'"))
    capabilities = Column(JSON, nullable=False, server_default=text("'[]'"))
    parameter_schema = Column(JSON, nullable=False, server_default=text("'[]'"))
    enabled = Column(Boolean, nullable=False, server_default=text("true"))
    legacy_connection_id = Column(Integer, ForeignKey("asr_connection.id", ondelete="SET NULL"), nullable=True, unique=True)
    created_by = Column(Integer, ForeignKey("user.id", ondelete="SET NULL"), nullable=True)
    created_at = Column(DateTime(timezone=True), nullable=False, server_default=func.now())


class ModelCredential(Base):
    """保存模型修订的加密凭据，不在任何响应合同中暴露密文。"""

    __tablename__ = "model_credential"
    __table_args__ = (UniqueConstraint("revision_id", name="uq_model_credential_revision"),)

    id = Column(Integer, primary_key=True, autoincrement=True)
    revision_id = Column(Integer, ForeignKey("model_revision.id", ondelete="CASCADE"), nullable=False)
    ciphertext = Column(Text, nullable=False)
    cipher_format = Column(String(40), nullable=False, server_default=text("'shared-fernet'"))
    header_name = Column(String(100), nullable=True)
    created_at = Column(DateTime(timezone=True), nullable=False, server_default=func.now())


class ModelParameterProfile(Base):
    """绑定指定模型修订的不可变参数方案版本。"""

    __tablename__ = "model_parameter_profile"
    __table_args__ = (UniqueConstraint("resource_id", "revision_id", "name", "version", name="uq_model_profile_version"),)

    id = Column(Integer, primary_key=True, autoincrement=True)
    resource_id = Column(Integer, ForeignKey("model_resource.id", ondelete="CASCADE"), nullable=False, index=True)
    revision_id = Column(Integer, ForeignKey("model_revision.id", ondelete="RESTRICT"), nullable=False, index=True)
    name = Column(String(120), nullable=False)
    version = Column(Integer, nullable=False)
    parameter_values = Column("parameter_values", JSON, nullable=False, server_default=text("'{}'"))
    definitions = Column(JSON, nullable=False, server_default=text("'[]'"))
    legacy_parameter_set_id = Column(Integer, ForeignKey("asr_parameter_set.id", ondelete="SET NULL"), nullable=True, unique=True)
    created_by = Column(Integer, ForeignKey("user.id", ondelete="SET NULL"), nullable=True)
    created_at = Column(DateTime(timezone=True), nullable=False, server_default=func.now())


class ModelLegacyBinding(Base):
    """明确关联旧整数 ID 与规范资源，保存原角色供历史兼容读取。"""

    __tablename__ = "model_legacy_binding"
    __table_args__ = (UniqueConstraint("legacy_kind", "legacy_id", name="uq_model_legacy_binding"),)

    id = Column(Integer, primary_key=True, autoincrement=True)
    legacy_kind = Column(String(40), nullable=False)
    legacy_id = Column(Integer, nullable=False)
    resource_id = Column(Integer, ForeignKey("model_resource.id", ondelete="CASCADE"), nullable=False, index=True)
    revision_id = Column(Integer, ForeignKey("model_revision.id", ondelete="CASCADE"), nullable=False)
    legacy_domain_id = Column(String(120), nullable=True, index=True)
    legacy_role = Column(String(20), nullable=True)
    legacy_task_type = Column(String(30), nullable=True)
    created_at = Column(DateTime(timezone=True), nullable=False, server_default=func.now())


class ModelResourceGrant(Base):
    """把平台共享模型显式授权给可访问项目。"""

    __tablename__ = "model_resource_grant"
    __table_args__ = (UniqueConstraint("resource_id", "project_id", name="uq_model_resource_grant"),)

    id = Column(Integer, primary_key=True, autoincrement=True)
    resource_id = Column(Integer, ForeignKey("model_resource.id", ondelete="CASCADE"), nullable=False, index=True)
    project_id = Column(Integer, ForeignKey("project.id", ondelete="CASCADE"), nullable=False, index=True)
    granted_by = Column(Integer, ForeignKey("user.id", ondelete="SET NULL"), nullable=True)
    created_at = Column(DateTime(timezone=True), nullable=False, server_default=func.now())


class ModelDefaultBinding(Base):
    """按用途、类别与项目选择默认资源及同类备用策略。"""

    __tablename__ = "model_default_binding"
    __table_args__ = (UniqueConstraint("category", "purpose", "project_id", name="uq_model_default_purpose"),)

    id = Column(Integer, primary_key=True, autoincrement=True)
    category = Column(String(30), nullable=False)
    purpose = Column(String(40), nullable=False)
    project_id = Column(Integer, ForeignKey("project.id", ondelete="CASCADE"), nullable=True)
    resource_id = Column(Integer, ForeignKey("model_resource.id", ondelete="RESTRICT"), nullable=False)
    revision_id = Column(Integer, ForeignKey("model_revision.id", ondelete="RESTRICT"), nullable=False)
    profile_id = Column(Integer, ForeignKey("model_parameter_profile.id", ondelete="RESTRICT"), nullable=True)
    fallback_resource_ids = Column(JSON, nullable=False, server_default=text("'[]'"))
    automatic_fallback = Column(Boolean, nullable=False, server_default=text("false"))
    updated_by = Column(Integer, ForeignKey("user.id", ondelete="SET NULL"), nullable=True)
    updated_at = Column(DateTime(timezone=True), nullable=False, server_default=func.now(), onupdate=func.now())


class ModelValidationRun(Base):
    """显式触发的后台模型诊断及脱敏结果。"""

    __tablename__ = "model_validation_run"
    __table_args__ = (Index("ix_model_validation_resource_created", "resource_id", "created_at"),)

    id = Column(Integer, primary_key=True, autoincrement=True)
    resource_id = Column(Integer, ForeignKey("model_resource.id", ondelete="CASCADE"), nullable=False, index=True)
    revision_id = Column(Integer, ForeignKey("model_revision.id", ondelete="CASCADE"), nullable=False)
    profile_id = Column(Integer, ForeignKey("model_parameter_profile.id", ondelete="SET NULL"), nullable=True)
    project_id = Column(Integer, ForeignKey("project.id", ondelete="CASCADE"), nullable=True, index=True)
    audio_id = Column(Integer, ForeignKey("asr_audio.id", ondelete="SET NULL"), nullable=True)
    status = Column(String(20), nullable=False, server_default=text("'QUEUED'"), index=True)
    diagnostic_kind = Column(String(30), nullable=False)
    result_json = Column(JSON, nullable=False, server_default=text("'{}'"))
    requested_by = Column(Integer, ForeignKey("user.id", ondelete="SET NULL"), nullable=True)
    created_at = Column(DateTime(timezone=True), nullable=False, server_default=func.now())
    started_at = Column(DateTime(timezone=True), nullable=True)
    finished_at = Column(DateTime(timezone=True), nullable=True)


class ModelTaskSlot(Base):
    """把任务或计划的角色固定到资源、连接修订和参数方案版本。"""

    __tablename__ = "model_task_slot"
    __table_args__ = (UniqueConstraint("task_kind", "task_id", "slot", name="uq_model_task_slot"),)

    id = Column(Integer, primary_key=True, autoincrement=True)
    task_kind = Column(String(30), nullable=False)
    task_id = Column(Integer, nullable=False)
    slot = Column(String(30), nullable=False)
    resource_id = Column(Integer, ForeignKey("model_resource.id", ondelete="RESTRICT"), nullable=False, index=True)
    revision_id = Column(Integer, ForeignKey("model_revision.id", ondelete="RESTRICT"), nullable=False)
    profile_id = Column(Integer, ForeignKey("model_parameter_profile.id", ondelete="RESTRICT"), nullable=True)
    legacy_connection_id = Column(Integer, ForeignKey("asr_connection.id", ondelete="SET NULL"), nullable=True)
    created_at = Column(DateTime(timezone=True), nullable=False, server_default=func.now())


__all__ = [
    "ModelCredential", "ModelDefaultBinding", "ModelLegacyBinding", "ModelParameterProfile",
    "ModelResource", "ModelResourceGrant", "ModelRevision", "ModelTaskSlot", "ModelValidationRun",
]
