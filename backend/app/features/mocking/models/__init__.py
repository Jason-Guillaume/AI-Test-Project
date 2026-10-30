"""Mock Management ORM 模型（Phase 1）。

Mock 解决「测试执行期间依赖服务应如何表现」，与 Data Factory（测试前造数）严格分离。
六个 feature-local 表，不进 app/models/__init__.py（红线 17），由迁移 0010 显式建表。

表与依赖顺序：
- mock_service：一个 Mock 依赖服务（地图 / 支付 / AI 模型 …）。service_key 项目内唯一。
- mock_endpoint：一个 Mock 接口。(mock_service_id, method, path) 唯一；api_id 可空关联。
- mock_scenario：一个 Endpoint 的多个场景。(mock_endpoint_id, scenario_key) 唯一；
  同 Endpoint 只允许一个 is_default=true（部分唯一索引）。
- mock_matcher：Scenario 的匹配规则（source/field/operator/expected_value）。
- mock_context：CaseExecution 激活的执行作用域，承载 scenario_overrides，支持并发隔离。
- mock_execution：Mock Runtime 每次调用的快照记录（敏感字段经 SensitiveDataMasker 脱敏）。
- test_case_mock：用例声明的 required_mocks（关联 service/endpoint/scenario + scope）。

mock_service.default_scenario_id 不建 FK（避免 service ↔ scenario 循环依赖），由服务层校验
归属；真正的「未匹配兜底」走 per-endpoint 的 is_default（§九 匹配规则）。
"""

from __future__ import annotations

from sqlalchemy import (
    Boolean,
    Column,
    DateTime,
    ForeignKey,
    Index,
    Integer,
    JSON,
    String,
    UniqueConstraint,
)
from sqlalchemy.sql import func, text

from app.core.database.base import Base


class MockService(Base):
    """一个 Mock 依赖服务（如地图服务 / 支付服务 / AI 模型服务）。"""

    __tablename__ = "mock_service"
    __table_args__ = (
        UniqueConstraint("project_id", "service_key", name="uq_mock_service_project_key"),
        Index("ix_mock_service_project_enabled", "project_id", "enabled"),
        {"comment": "Mock 依赖服务：service_key 项目内唯一"},
    )

    id = Column(Integer, primary_key=True, index=True, autoincrement=True)
    project_id = Column(
        Integer, ForeignKey("project.id", ondelete="CASCADE"),
        nullable=False, index=True, comment="所属项目ID",
    )
    name = Column(String(200), nullable=False, comment="服务名称")
    description = Column(String(1000), nullable=True, comment="描述")
    service_key = Column(String(100), nullable=False, comment="服务唯一键：^[A-Z][A-Z0-9_]{0,99}$")
    base_path = Column(String(500), nullable=True, comment="服务基础路径（展示用，不参与匹配）")
    enabled = Column(
        Boolean, nullable=False, default=True, server_default=text("true"),
        comment="是否启用（停用后 Runtime 拒绝调用）",
    )
    default_scenario_id = Column(
        Integer, nullable=True,
        comment="服务级默认场景引用（软引用，不建 FK；匹配兜底走 per-endpoint is_default）",
    )
    public_runtime = Column(
        Boolean, nullable=False, default=False, server_default=text("false"),
        comment="是否允许匿名调用 Runtime（默认 false，必须带 X-Mock-Token）",
    )
    # runtime_token_hash 只存哈希；明文仅在创建 / 重置时返回一次（§五十）。
    runtime_token_hash = Column(String(128), nullable=True, comment="Runtime Token 哈希（不明文）")
    created_by = Column(Integer, ForeignKey("user.id", ondelete="SET NULL"), nullable=True, comment="创建人")
    created_at = Column(DateTime, nullable=False, server_default=func.now(), comment="创建时间")
    updated_at = Column(
        DateTime, nullable=False, server_default=func.now(), onupdate=func.now(), comment="更新时间",
    )
    revision = Column(Integer, nullable=False, server_default=text("1"), comment="乐观锁版本号")


class MockEndpoint(Base):
    """一个 Mock 接口。(mock_service_id, method, path) 唯一。"""

    __tablename__ = "mock_endpoint"
    __table_args__ = (
        UniqueConstraint("mock_service_id", "method", "path", name="uq_mock_endpoint_service_method_path"),
        Index("ix_mock_endpoint_service_enabled", "mock_service_id", "enabled"),
        Index("ix_mock_endpoint_project", "project_id"),
        {"comment": "Mock 接口：method + path 匹配，api_id 可空关联 API Catalog"},
    )

    id = Column(Integer, primary_key=True, index=True, autoincrement=True)
    project_id = Column(
        Integer, ForeignKey("project.id", ondelete="CASCADE"),
        nullable=False, index=True, comment="所属项目ID",
    )
    mock_service_id = Column(
        Integer, ForeignKey("mock_service.id", ondelete="CASCADE"),
        nullable=False, index=True, comment="所属 Mock 服务ID",
    )
    api_id = Column(
        Integer, ForeignKey("api_interface.id", ondelete="SET NULL"),
        nullable=True, index=True, comment="关联接口ID（可空，仅关联不复制定义）",
    )
    name = Column(String(200), nullable=False, comment="接口名称")
    method = Column(String(10), nullable=False, comment="HTTP 方法")
    path = Column(String(500), nullable=False, comment="接口路径，支持 {param} 路径参数")
    description = Column(String(1000), nullable=True, comment="描述")
    enabled = Column(
        Boolean, nullable=False, default=True, server_default=text("true"), comment="是否启用",
    )
    created_at = Column(DateTime, nullable=False, server_default=func.now(), comment="创建时间")
    updated_at = Column(
        DateTime, nullable=False, server_default=func.now(), onupdate=func.now(), comment="更新时间",
    )
    revision = Column(Integer, nullable=False, server_default=text("1"), comment="乐观锁版本号")


class MockScenario(Base):
    """一个 Endpoint 的多个场景。(mock_endpoint_id, scenario_key) 唯一。"""

    __tablename__ = "mock_scenario"
    __table_args__ = (
        UniqueConstraint("mock_endpoint_id", "scenario_key", name="uq_mock_scenario_endpoint_key"),
        Index("ix_mock_scenario_endpoint_enabled", "mock_endpoint_id", "enabled"),
        # 部分唯一索引：同一 Endpoint 只允许一个 is_default=true（§三十六）。
        Index(
            "uq_mock_scenario_default", "mock_endpoint_id", unique=True,
            postgresql_where=text("is_default = true"),
        ),
        {"comment": "Mock 场景：行为类型 + 响应配置 + 延迟/超时"},
    )

    id = Column(Integer, primary_key=True, index=True, autoincrement=True)
    project_id = Column(
        Integer, ForeignKey("project.id", ondelete="CASCADE"),
        nullable=False, index=True, comment="所属项目ID",
    )
    mock_endpoint_id = Column(
        Integer, ForeignKey("mock_endpoint.id", ondelete="CASCADE"),
        nullable=False, index=True, comment="所属接口ID",
    )
    name = Column(String(200), nullable=False, comment="场景名称")
    scenario_key = Column(String(100), nullable=False, comment="场景唯一键：^[A-Z][A-Z0-9_]{0,99}$")
    description = Column(String(1000), nullable=True, comment="描述")
    enabled = Column(
        Boolean, nullable=False, default=True, server_default=text("true"), comment="是否启用",
    )
    is_default = Column(
        Boolean, nullable=False, default=False, server_default=text("false"),
        comment="是否为该 Endpoint 的默认场景（未匹配时兜底）",
    )
    priority = Column(
        Integer, nullable=False, default=0, server_default=text("0"),
        comment="匹配优先级，数值越高越优先；相同按 id ASC",
    )
    behavior_type = Column(
        String(30), nullable=False, default="STATIC_RESPONSE", server_default=text("'STATIC_RESPONSE'"),
        comment="行为类型：STATIC_RESPONSE/DELAY_RESPONSE/TIMEOUT/EMPTY_RESPONSE",
    )
    delay_ms = Column(Integer, nullable=True, comment="延迟毫秒（DELAY_RESPONSE / TIMEOUT 用）")
    status_code = Column(
        Integer, nullable=False, default=200, server_default=text("200"),
        comment="响应 HTTP 状态码",
    )
    response_headers = Column(JSON, nullable=True, comment="响应头（JSON dict）")
    response_body = Column(JSON, nullable=True, comment="响应体（JSON Object/Array/String/null）")
    response_template = Column(
        JSON, nullable=True,
        comment="响应模板：含 ${request.*} / ${runtime.*} 占位符，构建时解析",
    )
    created_by = Column(Integer, ForeignKey("user.id", ondelete="SET NULL"), nullable=True, comment="创建人")
    created_at = Column(DateTime, nullable=False, server_default=func.now(), comment="创建时间")
    updated_at = Column(
        DateTime, nullable=False, server_default=func.now(), onupdate=func.now(), comment="更新时间",
    )
    revision = Column(Integer, nullable=False, server_default=text("1"), comment="乐观锁版本号")


class MockMatcher(Base):
    """Scenario 的匹配规则。"""

    __tablename__ = "mock_matcher"
    __table_args__ = (
        Index("ix_mock_matcher_scenario_enabled", "scenario_id", "enabled"),
        {"comment": "Mock 匹配规则：source/field/operator/expected_value"},
    )

    id = Column(Integer, primary_key=True, index=True, autoincrement=True)
    project_id = Column(
        Integer, ForeignKey("project.id", ondelete="CASCADE"),
        nullable=False, index=True, comment="所属项目ID",
    )
    scenario_id = Column(
        Integer, ForeignKey("mock_scenario.id", ondelete="CASCADE"),
        nullable=False, index=True, comment="所属场景ID",
    )
    source = Column(
        String(20), nullable=False,
        comment="匹配来源：METHOD/PATH/QUERY/HEADER/BODY",
    )
    field = Column(String(200), nullable=False, comment="字段名或 JSONPath（$.amount）")
    operator = Column(
        String(30), nullable=False,
        comment="操作符：EQ/NE/EXISTS/NOT_EXISTS/CONTAINS/IN/JSON_PATH_EQ/JSON_PATH_EXISTS",
    )
    expected_value = Column(JSON, nullable=True, comment="期望值（JSON）")
    priority = Column(
        Integer, nullable=False, default=0, server_default=text("0"), comment="规则优先级",
    )
    enabled = Column(
        Boolean, nullable=False, default=True, server_default=text("true"), comment="是否启用",
    )
    created_at = Column(DateTime, nullable=False, server_default=func.now(), comment="创建时间")


class MockContext(Base):
    """CaseExecution 激活的执行作用域，承载 scenario_overrides，支持并发隔离。"""

    __tablename__ = "mock_context"
    __table_args__ = (
        UniqueConstraint("context_id", name="uq_mock_context_id"),
        Index("ix_mock_context_project_status", "project_id", "status"),
        Index("ix_mock_context_run", "test_run_id"),
        Index("ix_mock_context_case_execution", "case_execution_id"),
        Index("ix_mock_context_expires", "expires_at"),
        {"comment": "Mock 执行作用域：X-Mock-Context 对应的 scenario_overrides"},
    )

    id = Column(Integer, primary_key=True, index=True, autoincrement=True)
    context_id = Column(String(64), nullable=False, comment="X-Mock-Context 头的值（uuid4）")
    project_id = Column(
        Integer, ForeignKey("project.id", ondelete="CASCADE"),
        nullable=False, index=True, comment="所属项目ID",
    )
    test_run_id = Column(
        Integer, ForeignKey("test_run.id", ondelete="SET NULL"),
        nullable=True, index=True, comment="关联测试执行ID",
    )
    case_execution_id = Column(
        Integer, ForeignKey("case_execution.id", ondelete="SET NULL"),
        nullable=True, index=True, comment="关联用例执行ID",
    )
    # scenario_overrides: {endpoint_id: scenario_id}，Context Override 优先于默认场景。
    scenario_overrides = Column(JSON, nullable=True, comment="场景覆盖映射 {endpoint_id: scenario_id}")
    status = Column(
        String(20), nullable=False, default="ACTIVE", server_default=text("'ACTIVE'"),
        comment="状态：ACTIVE/CLOSED/EXPIRED",
    )
    expires_at = Column(DateTime, nullable=False, comment="过期时间（默认 30 分钟）")
    created_at = Column(DateTime, nullable=False, server_default=func.now(), comment="创建时间")
    closed_at = Column(DateTime, nullable=True, comment="关闭时间")


class MockExecution(Base):
    """Mock Runtime 每次调用的快照记录（敏感字段已脱敏）。"""

    __tablename__ = "mock_execution"
    __table_args__ = (
        Index("ix_mock_execution_project_created", "project_id", "created_at"),
        Index("ix_mock_execution_service", "mock_service_id"),
        Index("ix_mock_execution_run", "test_run_id"),
        Index("ix_mock_execution_case_execution", "case_execution_id"),
        Index("ix_mock_execution_context", "mock_context_id"),
        {"comment": "Mock 调用记录：请求/响应快照（敏感脱敏）+ 命中/耗时"},
    )

    id = Column(Integer, primary_key=True, index=True, autoincrement=True)
    project_id = Column(
        Integer, ForeignKey("project.id", ondelete="CASCADE"),
        nullable=False, index=True, comment="所属项目ID",
    )
    mock_service_id = Column(
        Integer, ForeignKey("mock_service.id", ondelete="SET NULL"),
        nullable=True, index=True, comment="Mock 服务ID",
    )
    mock_endpoint_id = Column(
        Integer, ForeignKey("mock_endpoint.id", ondelete="SET NULL"),
        nullable=True, index=True, comment="Mock 接口ID",
    )
    mock_scenario_id = Column(
        Integer, ForeignKey("mock_scenario.id", ondelete="SET NULL"),
        nullable=True, index=True, comment="命中场景ID（未命中为空）",
    )
    request_id = Column(String(64), nullable=True, comment="请求ID")
    method = Column(String(10), nullable=False, comment="HTTP 方法")
    path = Column(String(500), nullable=False, comment="请求路径")
    query_snapshot = Column(JSON, nullable=True, comment="查询参数快照（脱敏）")
    header_snapshot = Column(JSON, nullable=True, comment="请求头快照（脱敏）")
    body_snapshot = Column(JSON, nullable=True, comment="请求体快照（脱敏）")
    response_status = Column(Integer, nullable=True, comment="响应状态码")
    response_header_snapshot = Column(JSON, nullable=True, comment="响应头快照（脱敏）")
    response_body_snapshot = Column(JSON, nullable=True, comment="响应体快照（脱敏）")
    matched = Column(Boolean, nullable=False, default=False, server_default=text("false"), comment="是否命中场景")
    duration_ms = Column(Integer, nullable=True, comment="耗时毫秒")
    error_code = Column(String(50), nullable=True, comment="错误码")
    error_message = Column(String(2000), nullable=True, comment="错误信息")
    test_run_id = Column(Integer, nullable=True, index=True, comment="关联测试执行ID")
    case_execution_id = Column(Integer, nullable=True, index=True, comment="关联用例执行ID")
    mock_context_id = Column(String(64), nullable=True, index=True, comment="X-Mock-Context 值")
    created_at = Column(DateTime, nullable=False, server_default=func.now(), comment="创建时间")


class TestCaseMock(Base):
    """用例声明的 required_mocks（关联 service/endpoint/scenario + scope）。"""

    __tablename__ = "test_case_mock"
    __table_args__ = (
        UniqueConstraint("test_case_id", "mock_scenario_id", name="uq_test_case_mock_case_scenario"),
        Index("ix_test_case_mock_case", "test_case_id"),
        {"comment": "用例声明的 Mock 依赖：service/endpoint/scenario + scope"},
    )

    id = Column(Integer, primary_key=True, index=True, autoincrement=True)
    test_case_id = Column(
        Integer, ForeignKey("test_case.id", ondelete="CASCADE"),
        nullable=False, index=True, comment="所属用例ID",
    )
    mock_service_id = Column(
        Integer, ForeignKey("mock_service.id", ondelete="CASCADE"),
        nullable=False, index=True, comment="Mock 服务ID",
    )
    mock_endpoint_id = Column(
        Integer, ForeignKey("mock_endpoint.id", ondelete="CASCADE"),
        nullable=False, index=True, comment="Mock 接口ID",
    )
    mock_scenario_id = Column(
        Integer, ForeignKey("mock_scenario.id", ondelete="CASCADE"),
        nullable=False, index=True, comment="Mock 场景ID",
    )
    scope = Column(
        String(20), nullable=False, default="EXECUTION", server_default=text("'EXECUTION'"),
        comment="作用域：SETUP/EXECUTION/BOTH（默认 EXECUTION）",
    )
    sort = Column(Integer, nullable=False, default=0, server_default=text("0"), comment="排序")
    created_at = Column(DateTime, nullable=False, server_default=func.now(), comment="创建时间")


__all__ = [
    "MockService",
    "MockEndpoint",
    "MockScenario",
    "MockMatcher",
    "MockContext",
    "MockExecution",
    "TestCaseMock",
]
