"""统一模型中心 ORM：资源、不可变修订、参数方案、授权、默认槽位与诊断。"""

from sqlalchemy import (Boolean, CheckConstraint, Column, Computed, DateTime, Float, ForeignKey,
                        ForeignKeyConstraint, Index, Integer, JSON, String, Text, UniqueConstraint)
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
    text_sort_order = Column(Integer, nullable=False, server_default=text("0"))
    text_fallback_ids = Column(JSON, nullable=False, server_default=text("'[]'"))
    text_created_by = Column(Integer, ForeignKey("user.id"))
    text_created_at = Column(DateTime)
    text_updated_at = Column(DateTime)
    text_deleted_at = Column(DateTime)
    text_deleted_by = Column(Integer, ForeignKey("user.id", ondelete="SET NULL"))
    text_deletion_reason = Column(String(500))
    text_deletion_batch_id = Column(String(36))
    created_by = Column(Integer, ForeignKey("user.id", ondelete="SET NULL"), nullable=True)
    created_at = Column(DateTime(timezone=True), nullable=False, server_default=func.now())
    updated_at = Column(DateTime(timezone=True), nullable=False, server_default=func.now(), onupdate=func.now())


class ModelRevision(Base):
    """不可变模型连接修订；秘密凭据保存在独立表。"""

    __tablename__ = "model_revision"
    __table_args__ = (
        UniqueConstraint("resource_id", "version", name="uq_model_revision_version"),
        UniqueConstraint("resource_id", "id", name="uq_model_revision_owner"),
    )

    id = Column(Integer, primary_key=True, autoincrement=True)
    resource_id = Column(Integer, ForeignKey("model_resource.id", ondelete="CASCADE"), nullable=False, index=True)
    version = Column(Integer, nullable=False)
    text_cost_input = Column(Float, nullable=False, server_default=text("0"))
    text_cost_output = Column(Float, nullable=False, server_default=text("0"))
    text_profile_id = Column(Integer, ForeignKey("model_parameter_profile.id", ondelete="SET NULL", use_alter=True,
                                                name="model_revision_text_profile_id_fkey"))
    text_api_base = Column(String(500))
    text_timeout = Column(Integer)
    text_provider = Column(String(50))
    text_key_is_null = Column(Boolean, nullable=False, server_default=text("false"))
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
    __table_args__ = (
        UniqueConstraint("revision_id", name="uq_model_credential_revision"),
        CheckConstraint("(revision_id IS NULL) <> (alias_binding_id IS NULL)", name="ck_model_credential_owner"),
        CheckConstraint("revision_id IS NULL OR ciphertext IS NOT NULL", name="ck_model_revision_credential_data"),
    )

    id = Column(Integer, primary_key=True, autoincrement=True)
    revision_id = Column(Integer, ForeignKey("model_revision.id", ondelete="CASCADE"))
    alias_binding_id = Column(Integer, ForeignKey("model_legacy_binding.id", ondelete="CASCADE"), unique=True)
    alias_endpoint_ciphertext = Column(Text)
    text_ciphertext = Column(Text)
    ciphertext = Column(Text)
    cipher_format = Column(String(40), nullable=False, server_default=text("'shared-fernet'"))
    header_name = Column(String(100), nullable=True)
    created_at = Column(DateTime(timezone=True), nullable=False, server_default=func.now())


class ModelParameterProfile(Base):
    """绑定指定模型修订的不可变参数方案版本。"""

    __tablename__ = "model_parameter_profile"
    __table_args__ = (
        UniqueConstraint("resource_id", "revision_id", "id", name="uq_model_profile_owner"),
        Index("uq_model_profile_version", "resource_id", "revision_id", "name", "version", unique=True,
              postgresql_where=text("scope_connection_id IS NULL"), sqlite_where=text("scope_connection_id IS NULL")),
        Index("uq_model_scoped_profile_version", "scope_connection_id", "name", "version", unique=True,
              postgresql_where=text("scope_connection_id IS NOT NULL"), sqlite_where=text("scope_connection_id IS NOT NULL")),
    )
    scope_connection_id = Column(Integer, ForeignKey("model_legacy_binding.connection_public_id", ondelete="CASCADE",
                                                     use_alter=True, name="model_parameter_profile_scope_connection_id_fkey"))

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
    __table_args__ = (
        UniqueConstraint("legacy_kind", "legacy_id", name="uq_model_legacy_binding"),
        UniqueConstraint("connection_public_id", "project_id", "resource_id", "revision_id", name="uq_model_connection_owner"),
        ForeignKeyConstraint(["parent_connection_id", "project_id", "resource_id", "revision_id"],
                             ["model_legacy_binding.connection_public_id", "model_legacy_binding.project_id",
                              "model_legacy_binding.resource_id", "model_legacy_binding.revision_id"],
                             name="fk_model_parameter_connection_owner", ondelete="CASCADE"),
        ForeignKeyConstraint(["resource_id", "revision_id"], ["model_revision.resource_id", "model_revision.id"],
                             name="fk_model_binding_revision_owner", ondelete="CASCADE"),
        ForeignKeyConstraint(["resource_id", "revision_id", "profile_id"],
                             ["model_parameter_profile.resource_id", "model_parameter_profile.revision_id",
                              "model_parameter_profile.id"], name="fk_model_binding_profile_owner", ondelete="CASCADE"),
        CheckConstraint("connection_public_id IS NULL OR (project_id IS NOT NULL AND alias_name IS NOT NULL "
                        "AND alias_version IS NOT NULL AND legacy_task_type IS NOT NULL AND alias_created_at IS NOT NULL "
                        "AND alias_updated_at IS NOT NULL)", name="ck_model_connection_alias").ddl_if(dialect="postgresql"),
        CheckConstraint("parameter_public_id IS NULL OR (project_id IS NOT NULL AND parent_connection_id IS NOT NULL "
                        "AND profile_id IS NOT NULL AND alias_name IS NOT NULL AND alias_version IS NOT NULL "
                        "AND alias_created_at IS NOT NULL)", name="ck_model_parameter_alias").ddl_if(dialect="postgresql"),
        Index("ix_model_alias_scope", "project_id", "revision_id", "profile_id"),
        Index("uq_model_connection_alias_version", "project_id", "alias_name", "alias_version", unique=True,
              postgresql_where=text("connection_public_id IS NOT NULL"), sqlite_where=text("connection_public_id IS NOT NULL")),
        Index("uq_model_parameter_alias_version", "parent_connection_id", "alias_name", "alias_version", unique=True,
              postgresql_where=text("parameter_public_id IS NOT NULL"), sqlite_where=text("parameter_public_id IS NOT NULL")),
    )
    model_public_id = Column(Integer, Computed("CASE WHEN legacy_kind='MODEL_CONFIGURATION' THEN legacy_id END",
                                                persisted=True), unique=True)
    connection_public_id = Column(Integer, Computed(
        "CASE WHEN legacy_kind IN ('ASR_CONNECTION','ASR_SHARED_CONNECTION') THEN legacy_id END",
        persisted=True), unique=True)
    parameter_public_id = Column(Integer, Computed(
        "CASE WHEN legacy_kind IN ('ASR_PARAMETER_SET','ASR_SHARED_PARAMETER_SET') THEN legacy_id END",
        persisted=True), unique=True)
    profile_id = Column(Integer, ForeignKey("model_parameter_profile.id", ondelete="CASCADE"))
    parent_connection_id = Column(Integer, ForeignKey("model_legacy_binding.connection_public_id", ondelete="CASCADE",
                                                       name="fk_model_binding_parent_connection"))
    project_id = Column(Integer, ForeignKey("project.id", ondelete="CASCADE"))
    alias_name = Column(String(120))
    alias_version = Column(Integer)
    alias_enabled = Column(Boolean)
    alias_config = Column(JSON)
    alias_provider = Column(String(80))
    alias_model_name = Column(String(200))
    alias_endpoint_display = Column(String(500))
    alias_header = Column(String(100))
    allow_project_execution = Column(Boolean, nullable=False, server_default=text("false"))
    use_revision_credential = Column(Boolean, nullable=False, server_default=text("true"))
    alias_created_by = Column(Integer, ForeignKey("user.id", ondelete="SET NULL"))
    alias_created_at = Column(DateTime(timezone=True))
    alias_updated_at = Column(DateTime(timezone=True))

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
