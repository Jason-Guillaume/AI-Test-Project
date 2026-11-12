"""test_data 资源契约；字段、默认值、校验和 wire 名称保持不变。"""

from __future__ import annotations

from typing import Literal
from pydantic import BaseModel


FIXTURE_KEY_PATTERN = r"^[A-Z][A-Z0-9_]{0,99}$"


FIXTURE_SCOPES = ("CASE", "RUN", "PROJECT", "GLOBAL")


FixtureScope = Literal["CASE", "RUN", "PROJECT", "GLOBAL"]


FIXTURE_STATUSES = ("DRAFT", "ACTIVE", "DISABLED")


FixtureStatus = Literal["DRAFT", "ACTIVE", "DISABLED"]


FIXTURE_CLEANUP_POLICIES = ("AFTER_CASE", "AFTER_RUN", "MANUAL", "NEVER")


FixtureCleanupPolicy = Literal["AFTER_CASE", "AFTER_RUN", "MANUAL", "NEVER"]


FIXTURE_PHASES = ("GENERATE", "CLEANUP")


FixturePhase = Literal["GENERATE", "CLEANUP"]


FIXTURE_STEP_TYPES_EXECUTABLE = (
    "FIXTURE", "API", "BUSINESS_ACTION", "BUSINESS_FLOW",
    "FAKER", "STATIC", "DATABASE_INSERT", "DATABASE_PATCH",
)


FIXTURE_STEP_TYPES_RESERVED = ("WAIT", "DATABASE_QUERY", "EXTERNAL_PROVIDER")


FIXTURE_STEP_TYPES = FIXTURE_STEP_TYPES_EXECUTABLE + FIXTURE_STEP_TYPES_RESERVED


FixtureStepType = Literal[
    "FIXTURE", "API", "BUSINESS_ACTION", "BUSINESS_FLOW", "FAKER", "STATIC",
    "DATABASE_INSERT", "DATABASE_PATCH", "WAIT", "DATABASE_QUERY", "EXTERNAL_PROVIDER",
]


FIXTURE_ON_FAILURE = ("ABORT", "CONTINUE")


FixtureOnFailure = Literal["ABORT", "CONTINUE"]


VALUE_TYPES = ("STRING", "INTEGER", "NUMBER", "BOOLEAN", "OBJECT", "ARRAY")


ValueType = Literal["STRING", "INTEGER", "NUMBER", "BOOLEAN", "OBJECT", "ARRAY"]


PROVIDER_TYPES = (
    "STATIC", "ENVIRONMENT", "FAKER", "API_CREATE",
    "BUSINESS_ACTION", "BUSINESS_FLOW", "EXISTING_POOL",
    "DATABASE_INSERT", "DATABASE_PATCH",
)


ProviderType = Literal[
    "STATIC", "ENVIRONMENT", "FAKER", "API_CREATE",
    "BUSINESS_ACTION", "BUSINESS_FLOW", "EXISTING_POOL",
    "DATABASE_INSERT", "DATABASE_PATCH",
]


RISK_LEVELS = ("LOW", "MEDIUM", "HIGH", "CRITICAL")


RiskLevel = Literal["LOW", "MEDIUM", "HIGH", "CRITICAL"]


ASSET_SOURCES = ("STATIC", "POOL", "FIXTURE")


AssetSource = Literal["STATIC", "POOL", "FIXTURE"]


ASSET_STATUSES = ("ACTIVE", "DISABLED", "EXPIRED")


AssetStatus = Literal["ACTIVE", "DISABLED", "EXPIRED"]


POOL_STATUSES = ("ACTIVE", "DISABLED")


PoolStatus = Literal["ACTIVE", "DISABLED"]


POOL_ITEM_STATUSES = ("AVAILABLE", "OCCUPIED", "EXPIRED", "DISABLED")


PoolItemStatus = Literal["AVAILABLE", "OCCUPIED", "EXPIRED", "DISABLED"]


LEASE_STATUSES = ("ACTIVE", "RELEASED", "EXPIRED")


LeaseStatus = Literal["ACTIVE", "RELEASED", "EXPIRED"]


DB_OPERATIONS = ("INSERT", "UPDATE", "SELECT", "DELETE")


DbOperation = Literal["INSERT", "UPDATE", "SELECT", "DELETE"]


DB_ENV_CLASSES = ("DEV", "TEST", "STAGING", "PRODUCTION")


DbEnvironmentClass = Literal["DEV", "TEST", "STAGING", "PRODUCTION"]


DATA_EXECUTION_STATUSES = (
    "PENDING", "GENERATING", "READY", "FAILED", "EXPIRED", "DIRTY", "CLEANING", "CLEANED",
)


DataExecutionStatus = Literal[
    "PENDING", "GENERATING", "READY", "FAILED", "EXPIRED", "DIRTY", "CLEANING", "CLEANED",
]


PROVIDER_EXECUTION_STATUSES = ("PENDING", "RUNNING", "SUCCESS", "FAILED", "SKIPPED")


ProviderExecutionStatus = Literal["PENDING", "RUNNING", "SUCCESS", "FAILED", "SKIPPED"]


CLEANUP_STATUSES = ("PENDING", "SUCCESS", "FAILED", "SKIPPED")


CleanupStatus = Literal["PENDING", "SUCCESS", "FAILED", "SKIPPED"]


FAKER_GENERATORS = (
    "uuid", "name", "phone", "email", "string", "integer",
    "timestamp", "date", "url", "ip", "random_choice", "project_name",
)


FAKER_LOCALES = ("zh_CN", "en_US")


RESOLVE_NAMESPACES = ("fixture", "faker", "env", "runtime", "data")


MAPPING_LOCATIONS = ("HEADER", "QUERY", "PATH", "BODY", "COOKIE")


MappingLocation = Literal["HEADER", "QUERY", "PATH", "BODY", "COOKIE"]


class PageResponse(BaseModel):
    """分页壳（由各列表响应的 items 承载具体类型）。"""

    page: int
    page_size: int
    total: int
