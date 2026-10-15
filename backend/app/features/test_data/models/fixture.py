"""Fixture ORM 模型：配方、显式依赖、步骤、输出契约。

Fixture 是「测试需要的业务状态配方」，不是静态 JSON 结果。
- fixture_key 是大写标识符（^[A-Z][A-Z0-9_]{0,99}$），用例与 Agent 只引用它；
- scope ∈ CASE / RUN / PROJECT / GLOBAL，决定共享范围与缓存键；
- GLOBAL 仍有所属 project_id（拥有者），其他项目只能按 key 读取 ACTIVE 定义来执行，
  不能修改；执行记录的 project_id 永远是**消费方**项目。

模型 feature-local，不进 app/models/__init__.py；由 alembic 0009 显式建表。
"""

from sqlalchemy import Boolean, Column, DateTime, ForeignKey, Index, Integer, JSON, String, UniqueConstraint
from sqlalchemy.sql import func, text

from app.shared.database import Base


class Fixture(Base):
    """测试需要的业务状态配方。"""

    __tablename__ = "fixture"
    __table_args__ = (
        UniqueConstraint("project_id", "fixture_key", name="uq_fixture_project_key"),
        Index("ix_fixture_project_status", "project_id", "status"),
        Index("ix_fixture_project_entity", "project_id", "entity_type"),
        # 部分唯一索引：两个项目不能发布同一个 GLOBAL 键（迁移里 IF NOT EXISTS 创建）。
        Index(
            "uq_fixture_global_key", "fixture_key", unique=True,
            postgresql_where=text("scope = 'GLOBAL'"),
        ),
        {"comment": "Fixture：测试需要的业务状态配方（非静态 JSON 结果）"},
    )

    id = Column(Integer, primary_key=True, index=True, autoincrement=True)
    project_id = Column(
        Integer, ForeignKey("project.id", ondelete="CASCADE"),
        nullable=False, index=True, comment="所属项目ID（GLOBAL 时为拥有者）",
    )
    name = Column(String(200), nullable=False, comment="Fixture 名称")
    fixture_key = Column(String(100), nullable=False, comment="唯一引用键：^[A-Z][A-Z0-9_]{0,99}$")
    entity_type = Column(String(50), nullable=False, comment="实体类型：USER/PROJECT/TASK 等")
    description = Column(String(1000), nullable=True, comment="描述")
    scope = Column(
        String(20), nullable=False, default="CASE", server_default=text("'CASE'"),
        comment="作用域：CASE/RUN/PROJECT/GLOBAL",
    )
    status = Column(
        String(20), nullable=False, default="DRAFT", server_default=text("'DRAFT'"),
        comment="状态：DRAFT/ACTIVE/DISABLED，只有 ACTIVE 可执行与引用",
    )
    cache_enabled = Column(
        Boolean, nullable=False, default=True, server_default=text("true"),
        comment="是否允许按 scope 复用缓存输出",
    )
    cleanup_policy = Column(
        String(20), nullable=False, default="AFTER_CASE", server_default=text("'AFTER_CASE'"),
        comment="清理策略：AFTER_CASE/AFTER_RUN/MANUAL/NEVER",
    )
    created_by = Column(Integer, ForeignKey("user.id", ondelete="SET NULL"), nullable=True, comment="创建人")
    created_at = Column(DateTime, nullable=False, server_default=func.now(), comment="创建时间")
    updated_at = Column(
        DateTime, nullable=False, server_default=func.now(), onupdate=func.now(), comment="更新时间",
    )


class FixtureDependency(Base):
    """Fixture 显式依赖边：fixture_id 依赖 depends_on_fixture_id。"""

    __tablename__ = "fixture_dependency"
    __table_args__ = (
        UniqueConstraint("fixture_id", "depends_on_fixture_id", name="uq_fixture_dependency"),
        {"comment": "Fixture 显式依赖边（环检测与执行顺序）"},
    )

    id = Column(Integer, primary_key=True, index=True, autoincrement=True)
    fixture_id = Column(
        Integer, ForeignKey("fixture.id", ondelete="CASCADE"),
        nullable=False, index=True, comment="依赖方 Fixture ID",
    )
    depends_on_fixture_id = Column(
        Integer, ForeignKey("fixture.id", ondelete="CASCADE"),
        nullable=False, index=True,
        comment="被依赖 Fixture ID（同项目，或 GLOBAL 且 ACTIVE）",
    )
    sort = Column(Integer, nullable=False, default=0, server_default=text("0"), comment="排序")


class FixtureStep(Base):
    """Fixture 步骤：GENERATE 造数，CLEANUP 清理。

    config_json 按 step_type 约定（服务层 Pydantic 校验，不信任任意 JSON）。
    预留类型 WAIT / DATABASE_QUERY / EXTERNAL_PROVIDER 只保存不执行。
    """

    __tablename__ = "fixture_step"
    __table_args__ = (
        Index("ix_fixture_step_fixture_phase_sort", "fixture_id", "phase", "sort"),
        {"comment": "Fixture 步骤（GENERATE/CLEANUP，config_json 按 step_type 约定）"},
    )

    id = Column(Integer, primary_key=True, index=True, autoincrement=True)
    fixture_id = Column(
        Integer, ForeignKey("fixture.id", ondelete="CASCADE"),
        nullable=False, index=True, comment="所属 Fixture ID",
    )
    phase = Column(
        String(20), nullable=False, default="GENERATE", server_default=text("'GENERATE'"),
        comment="阶段：GENERATE/CLEANUP",
    )
    step_type = Column(
        String(30), nullable=False,
        comment="FIXTURE/API/BUSINESS_ACTION/BUSINESS_FLOW/FAKER/STATIC/DATABASE_INSERT/DATABASE_PATCH",
    )
    name = Column(String(200), nullable=False, comment="步骤名称")
    sort = Column(Integer, nullable=False, default=0, server_default=text("0"), comment="步骤顺序")
    provider_id = Column(
        Integer, ForeignKey("data_provider.id", ondelete="SET NULL"),
        nullable=True, index=True,
        comment="引用的 Provider ID（优先引用 Provider，避免两套配置）",
    )
    config_json = Column(JSON, nullable=True, comment="步骤配置（按 step_type 约定，脱敏后落库）")
    on_failure = Column(
        String(20), nullable=False, default="ABORT", server_default=text("'ABORT'"),
        comment="失败策略：ABORT/CONTINUE（CLEANUP 阶段默认 CONTINUE）",
    )


class FixtureOutput(Base):
    """Fixture 输出契约：用例只能引用这里声明的名字。

    生成结束后只有这些键进入 ExecutionContext，命名空间 fixture.<fixture_key>.<name>。
    步骤中间变量留在 Fixture 私有 dict，不暴露给用例。
    """

    __tablename__ = "fixture_output"
    __table_args__ = (
        UniqueConstraint("fixture_id", "name", name="uq_fixture_output_name"),
        {"comment": "Fixture 输出契约：用例只能引用这里声明的名字"},
    )

    id = Column(Integer, primary_key=True, index=True, autoincrement=True)
    fixture_id = Column(
        Integer, ForeignKey("fixture.id", ondelete="CASCADE"),
        nullable=False, index=True, comment="所属 Fixture ID",
    )
    name = Column(String(100), nullable=False, comment="输出变量名")
    value_type = Column(
        String(20), nullable=False, default="STRING", server_default=text("'STRING'"),
        comment="STRING/INTEGER/NUMBER/BOOLEAN/OBJECT/ARRAY",
    )
    source_path = Column(
        String(200), nullable=False,
        comment="从 Fixture 私有上下文取值路径：task_id 或 $.data.id",
    )
    description = Column(String(500), nullable=True, comment="说明")
    sort = Column(Integer, nullable=False, default=0, server_default=text("0"), comment="排序")
