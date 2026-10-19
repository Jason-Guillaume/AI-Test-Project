"""Security Testing 契约定义（Pydantic v2）。

只放请求 / 响应模型与字面量；service、runtime 与 router 共用本文件作为两层接口契约。
枚举在数据库层是 String，合法取值由 Literal + 服务层校验决定（与 test_data / Mock 一致）。

分层约定：
- 本模块只定义**配置侧**的字面量与校验，变异逻辑在 ``runtime/``，不做 HTTP。
- ``mutation_config`` 一律 ``extra="forbid"``，脚本类键在 ``FORBIDDEN_CONFIG_KEYS`` 显式拒绝。
- 严重级别、状态迁移表都是固定规则，不接收 LLM 或前端传入的级别。
"""

from __future__ import annotations

from datetime import datetime
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator

# --------------------------------------------------------------------------- 枚举字面量

# 策略范围：SYSTEM 模板 project_id 为空；PROJECT 自定义必须带 project_id。
STRATEGY_SCOPES = ("SYSTEM", "PROJECT")
StrategyScope = Literal["SYSTEM", "PROJECT"]

# 策略类别：前 10 个第一阶段可执行，后 4 个只保存不执行（执行时直接拒绝，不携带攻击载荷）。
EXECUTABLE_CATEGORIES = (
    "AUTHENTICATION",
    "AUTHORIZATION",
    "IDOR",
    "PARAMETER",
    "HEADER",
    "METHOD",
    "REPLAY",
    "DUPLICATE_SUBMIT",
    "BUSINESS_STATE",
    "SEQUENCE_BYPASS",
)
RESERVED_CATEGORIES = ("INJECTION", "RATE_LIMIT", "UPLOAD", "SSRF")
STRATEGY_CATEGORIES = EXECUTABLE_CATEGORIES + RESERVED_CATEGORIES
StrategyCategory = Literal[*STRATEGY_CATEGORIES]

# 变异类型（算子白名单）。不在此集合里的值一律 SECURITY_MUTATION_INVALID。
AUTHENTICATION_MUTATION_TYPES = (
    "REMOVE_TOKEN",
    "EMPTY_TOKEN",
    "INVALID_TOKEN",
    "MALFORMED_TOKEN",
    "WRONG_AUTH_SCHEME",
    "EXPIRED_TOKEN",
)
AUTHORIZATION_MUTATION_TYPES = (
    "CROSS_USER",
    "CROSS_PROJECT",
    "ROLE_DOWNGRADE",
    "RESOURCE_OWNER_CHANGE",
    "IDOR",
)
PARAMETER_MUTATION_TYPES = (
    "REMOVE_FIELD",
    "NULL_VALUE",
    "EMPTY_STRING",
    "TYPE_MUTATION",
    "ZERO",
    "NEGATIVE",
    "OVER_MAX",
    "UNDER_MIN",
    "INVALID_ENUM",
    "INVALID_FORMAT",
)
HEADER_MUTATION_TYPES = (
    "REMOVE_HEADER",
    "EMPTY_HEADER",
    "INVALID_HEADER_VALUE",
    "CONTENT_TYPE_MUTATION",
    "AUTHORIZATION_MUTATION",
)
METHOD_MUTATION_TYPES = ("METHOD_MUTATION",)
REPLAY_MUTATION_TYPES = ("REPLAY_SAME_REQUEST",)
BUSINESS_MUTATION_TYPES = ("BUSINESS_STATE", "SEQUENCE_BYPASS", "DUPLICATE_SUBMIT")
MUTATION_TYPES = (
    AUTHENTICATION_MUTATION_TYPES
    + AUTHORIZATION_MUTATION_TYPES
    + PARAMETER_MUTATION_TYPES
    + HEADER_MUTATION_TYPES
    + METHOD_MUTATION_TYPES
    + REPLAY_MUTATION_TYPES
    + BUSINESS_MUTATION_TYPES
)
MutationType = Literal[*MUTATION_TYPES]

# 变异类型 → 允许的期望。REMOVE_TOKEN 配 EXPECTED_IDEMPOTENT 属于配置错误。
MUTATION_EXPECTATIONS: dict[str, tuple[str, ...]] = {
    "REMOVE_TOKEN": ("EXPECTED_DENY",),
    "EMPTY_TOKEN": ("EXPECTED_DENY",),
    "INVALID_TOKEN": ("EXPECTED_DENY",),
    "MALFORMED_TOKEN": ("EXPECTED_DENY",),
    "WRONG_AUTH_SCHEME": ("EXPECTED_DENY",),
    "EXPIRED_TOKEN": ("EXPECTED_DENY",),
    "CROSS_USER": ("EXPECTED_DENY",),
    "CROSS_PROJECT": ("EXPECTED_DENY",),
    "ROLE_DOWNGRADE": ("EXPECTED_DENY",),
    "RESOURCE_OWNER_CHANGE": ("EXPECTED_DENY",),
    "IDOR": ("EXPECTED_DENY",),
    "REMOVE_FIELD": ("EXPECTED_VALIDATION_ERROR",),
    "NULL_VALUE": ("EXPECTED_VALIDATION_ERROR",),
    "EMPTY_STRING": ("EXPECTED_VALIDATION_ERROR",),
    "TYPE_MUTATION": ("EXPECTED_VALIDATION_ERROR",),
    "ZERO": ("EXPECTED_VALIDATION_ERROR",),
    "NEGATIVE": ("EXPECTED_VALIDATION_ERROR",),
    "OVER_MAX": ("EXPECTED_VALIDATION_ERROR",),
    "UNDER_MIN": ("EXPECTED_VALIDATION_ERROR",),
    "INVALID_ENUM": ("EXPECTED_VALIDATION_ERROR",),
    "INVALID_FORMAT": ("EXPECTED_VALIDATION_ERROR",),
    "REMOVE_HEADER": ("EXPECTED_VALIDATION_ERROR",),
    "EMPTY_HEADER": ("EXPECTED_VALIDATION_ERROR",),
    "INVALID_HEADER_VALUE": ("EXPECTED_VALIDATION_ERROR",),
    "CONTENT_TYPE_MUTATION": ("EXPECTED_VALIDATION_ERROR",),
    "AUTHORIZATION_MUTATION": ("EXPECTED_DENY",),
    "METHOD_MUTATION": ("EXPECTED_DENY",),
    "REPLAY_SAME_REQUEST": ("EXPECTED_IDEMPOTENT",),
    "DUPLICATE_SUBMIT": ("EXPECTED_IDEMPOTENT",),
    "BUSINESS_STATE": ("EXPECTED_DENY",),
    "SEQUENCE_BYPASS": ("EXPECTED_DENY",),
}

# 变异类型 → 默认期望（规则创建时允许省略，按算子推导）。
DEFAULT_EXPECTATION_BY_TYPE: dict[str, str] = {
    k: v[0] for k, v in MUTATION_EXPECTATIONS.items()
}

# 目标位置。METHOD 只用于 METHOD_MUTATION，REQUEST 表示整条请求（重放类）。
TARGET_LOCATIONS = ("HEADER", "QUERY", "PATH", "BODY", "METHOD", "REQUEST")
TargetLocation = Literal["HEADER", "QUERY", "PATH", "BODY", "METHOD", "REQUEST"]

# 安全期望。
SECURITY_EXPECTATIONS = (
    "EXPECTED_DENY",
    "EXPECTED_ALLOW",
    "EXPECTED_VALIDATION_ERROR",
    "EXPECTED_IDEMPOTENT",
)
SecurityExpectation = Literal["EXPECTED_DENY", "EXPECTED_ALLOW", "EXPECTED_VALIDATION_ERROR",
                             "EXPECTED_IDEMPOTENT"]

# 严重级别 / 风险级别：策略与规则上的 risk_level 复用同一套值。
SEVERITY_LEVELS = ("INFO", "LOW", "MEDIUM", "HIGH", "CRITICAL")
SeverityLevel = Literal["INFO", "LOW", "MEDIUM", "HIGH", "CRITICAL"]

# 计划状态与目标类型。
PLAN_STATUSES = ("DRAFT", "CONFIRMED", "DISCARDED")
PlanStatus = Literal["DRAFT", "CONFIRMED", "DISCARDED"]
PLAN_TARGET_TYPES = ("API", "TEST_CASE", "BUSINESS_ACTION")
PlanTargetType = Literal["API", "TEST_CASE", "BUSINESS_ACTION"]

# 安全结论（五态）。不使用「已确认漏洞」作为自动结果。
SECURITY_RESULTS = ("PASS", "POTENTIAL_ISSUE", "FAILED_EXECUTION", "INCONCLUSIVE", "SKIPPED")
SecurityResult = Literal["PASS", "POTENTIAL_ISSUE", "FAILED_EXECUTION", "INCONCLUSIVE", "SKIPPED"]

# 结论分类。
CLASSIFICATIONS = (
    "EXPECTED_DENY_MET",
    "EXPECTED_VALIDATION_MET",
    "EXPECTED_IDEMPOTENT_MET",
    "POTENTIAL_ISSUE",
    "UNEXPECTED_SERVER_ERROR",
    "BASELINE_FAILED",
    "FIXTURE_REQUIRED",
    "CONFIRMATION_REQUIRED",
    "TARGET_BLOCKED",
    "TRANSPORT_ERROR",
)
Classification = Literal[*CLASSIFICATIONS]

# 安全结论 → case_execution.status（现有枚举，不改表）。
SECURITY_RESULT_TO_CASE_STATUS: dict[str, str] = {
    "PASS": "PASSED",
    "POTENTIAL_ISSUE": "FAILED",
    "FAILED_EXECUTION": "ERROR",
    "INCONCLUSIVE": "SKIPPED",
    "SKIPPED": "SKIPPED",
}

# Finding 状态与合法迁移（状态变更需要 editor+）。
FINDING_STATUSES = ("OPEN", "CONFIRMED", "FALSE_POSITIVE", "RESOLVED", "IGNORED")
FindingStatus = Literal["OPEN", "CONFIRMED", "FALSE_POSITIVE", "RESOLVED", "IGNORED"]
FINDING_STATUS_TRANSITIONS: dict[str, tuple[str, ...]] = {
    "OPEN": ("CONFIRMED", "FALSE_POSITIVE", "IGNORED", "RESOLVED"),
    "CONFIRMED": ("RESOLVED", "FALSE_POSITIVE"),
    "FALSE_POSITIVE": ("OPEN",),
    "IGNORED": ("OPEN",),
    "RESOLVED": ("OPEN",),
}
# 占用 fingerprint 部分唯一索引的状态；其余状态不再阻塞新 Finding。
FINDING_OPEN_STATUSES = ("OPEN", "CONFIRMED")

# 基线结论。
BASELINE_STATUSES = ("PASSED", "FAILED")
BaselineStatus = Literal["PASSED", "FAILED"]

# mutation_config 里禁止出现的键：出现即 SECURITY_MUTATION_INVALID，不允许脚本或外部载荷文件。
FORBIDDEN_CONFIG_KEYS = frozenset({"script", "python", "sql", "shell", "payload_file", "command"})

# 重放上限：只能是 2 或 3，间隔不超过 5 秒。
REPLAY_COUNTS = (2, 3)
REPLAY_INTERVAL_MAX_MS = 5000

# 单次 preview 硬上限：超出截断并在响应里标记 truncated，不静默丢弃。
MAX_PREVIEW_ITEMS = 50

# 报告摘要里最多展示几条 Finding。
MAX_TOP_FINDINGS = 5

# 超长字符串封顶，避免巨大 body。
MAX_MUTATION_STRING_LENGTH = 256

# 报告与列表筛选用的六类覆盖口径（前端概览卡片）。
COVERAGE_CATEGORIES = (
    "AUTHENTICATION",
    "AUTHORIZATION",
    "IDOR",
    "PARAMETER",
    "REPLAY",
    "BUSINESS",
)

STRATEGY_KEY_PATTERN = r"^[A-Z][A-Z0-9_]{0,99}$"

# --------------------------------------------------------------------------- 基类


class _ORM(BaseModel):
    """从 ORM 实体构造响应的基类。"""

    model_config = ConfigDict(from_attributes=True)


# --------------------------------------------------------------------------- 项目设置

class SecuritySettingRead(_ORM):
    """项目级环境开关。``production_enforced`` 说明生产永远拒绝，与 allow_production 无关。"""

    id: int | None = None
    project_id: int | None = None
    allow_dev: bool = True
    allow_test: bool = True
    allow_staging: bool = False
    allow_production: bool = False
    # 恒为 false：列上即使存了 true，执行器也不读它。
    production_enforced: bool = False
    updated_by: int | None = None
    created_at: datetime | None = None
    updated_at: datetime | None = None
    revision: int = 1


class SecuritySettingUpdate(BaseModel):
    """修改环境开关。``allow_production`` 可传入但永不生效（存库后仍拒绝）。"""

    allow_dev: bool | None = None
    allow_test: bool | None = None
    allow_staging: bool | None = None
    allow_production: bool | None = None
    revision: int | None = None


# --------------------------------------------------------------------------- 变异规则


class FixtureSource(BaseModel):
    """指向 Fixture 输出的取值来源（不复制数据，只声明引用）。"""

    model_config = ConfigDict(extra="forbid")

    fixture_key: str = Field(..., min_length=1, max_length=200)
    output: str = Field(..., min_length=1, max_length=200)


class MutationConfig(BaseModel):
    """结构化变异参数（extra=forbid，禁止脚本键）。

    不同 mutation_type 只用到其中一部分字段；未使用的字段保持 None，
    引擎按算子取需要的键。

    校验顺序在服务层：先 ``validate_no_script_keys`` 拦脚本键（400 SECURITY_MUTATION_INVALID），
    再用本模型拦未知键与取值越界（同样归 400，不是 422），避免前端拿到两种错误码。
    """

    model_config = ConfigDict(extra="forbid")

    token_source: FixtureSource | None = None
    resource_source: FixtureSource | None = None
    owner_source: FixtureSource | None = None
    location: str | None = Field(None, max_length=20)
    field: str | None = Field(None, max_length=200)
    methods: list[str] = Field(default_factory=list, max_length=10)
    replay_count: int | None = Field(None, ge=2, le=3)
    replay_interval_ms: int | None = Field(None, ge=0, le=REPLAY_INTERVAL_MAX_MS)
    state_entity: str | None = Field(None, max_length=200)
    fixture_key: str | None = Field(None, max_length=200)
    output: str | None = Field(None, max_length=200)
    skipped_action_id: int | None = None
    candidates: list[FixtureSource] = Field(default_factory=list, max_length=50)


def validate_no_script_keys(config: dict[str, Any] | None, *, what: str = "变异配置") -> None:
    """拒绝 mutation_config 里出现脚本类键（嵌套也查）。

    Args:
        config: 待校验的配置字典。
        what: 错误文案里的对象名。

    Raises:
        ValueError: 出现 ``script`` / ``python`` / ``sql`` / ``shell`` /
            ``payload_file`` / ``command`` 任一键。
    """
    from app.shared.errors import CODE_SECURITY_MUTATION_INVALID, AppError

    def walk(node: Any, path: str) -> None:
        if isinstance(node, dict):
            for key, value in node.items():
                if str(key).lower() in FORBIDDEN_CONFIG_KEYS:
                    raise AppError(
                        f"{what}不允许包含 {key!r} 字段：安全变异必须是结构化配置，不接受脚本",
                        status_code=400,
                        code=CODE_SECURITY_MUTATION_INVALID,
                    )
                walk(value, f"{path}.{key}" if path else str(key))
        elif isinstance(node, list):
            for i, value in enumerate(node):
                walk(value, f"{path}[{i}]")

    walk(config or {}, "")


class MutationRuleCreate(BaseModel):
    """创建一条变异规则。"""

    name: str = Field(..., min_length=1, max_length=200)
    mutation_type: str = Field(..., min_length=1, max_length=40)
    target_location: str = Field(..., min_length=1, max_length=20)
    target_field: str | None = Field(None, max_length=200)
    operator: str | None = Field(None, max_length=40)
    mutation_config: dict[str, Any] = Field(default_factory=dict)
    expected_security_behavior: str | None = Field(None, max_length=40)
    expected_status_codes: list[int] | None = Field(default=None, max_length=20)
    severity: str | None = Field(None, max_length=20)
    enabled: bool = True
    confirmation_required: bool = False
    sort: int = Field(0, ge=0, le=10000)

    @field_validator("expected_status_codes")
    @classmethod
    def _check_codes(cls, value: list[int] | None) -> list[int] | None:
        if value is None:
            return None
        for code in value:
            if not 100 <= code <= 599:
                raise ValueError(f"期望状态码必须是 100-599 之间的整数：{code}")
        return value

    @field_validator("severity")
    @classmethod
    def _check_severity(cls, value: str | None) -> str | None:
        if value is None:
            return None
        if value not in SEVERITY_LEVELS:
            raise ValueError(f"不支持的严重级别：{value}")
        return value

    @field_validator("mutation_type")
    @classmethod
    def _check_type(cls, value: str) -> str:
        if value not in MUTATION_TYPES:
            raise ValueError(f"不支持的变异类型：{value}")
        return value

    @field_validator("target_location")
    @classmethod
    def _check_location(cls, value: str) -> str:
        if value not in TARGET_LOCATIONS:
            raise ValueError(f"不支持的目标位置：{value}")
        return value


class MutationRuleUpdate(BaseModel):
    """修改一条变异规则（全部可选）。"""

    name: str | None = Field(None, min_length=1, max_length=200)
    mutation_type: str | None = Field(None, min_length=1, max_length=40)
    target_location: str | None = Field(None, min_length=1, max_length=20)
    target_field: str | None = Field(None, max_length=200)
    operator: str | None = Field(None, max_length=40)
    mutation_config: dict[str, Any] | None = None
    expected_security_behavior: str | None = Field(None, max_length=40)
    expected_status_codes: list[int] | None = Field(default=None, max_length=20)
    severity: str | None = Field(None, max_length=20)
    enabled: bool | None = None
    confirmation_required: bool | None = None
    sort: int | None = Field(None, ge=0, le=10000)

    @field_validator("expected_status_codes")
    @classmethod
    def _check_codes(cls, value: list[int] | None) -> list[int] | None:
        if value is None:
            return None
        for code in value:
            if not 100 <= code <= 599:
                raise ValueError(f"期望状态码必须是 100-599 之间的整数：{code}")
        return value

    @field_validator("severity")
    @classmethod
    def _check_severity(cls, value: str | None) -> str | None:
        if value is None:
            return None
        if value not in SEVERITY_LEVELS:
            raise ValueError(f"不支持的严重级别：{value}")
        return value

    @field_validator("mutation_type")
    @classmethod
    def _check_type(cls, value: str | None) -> str | None:
        if value is not None and value not in MUTATION_TYPES:
            raise ValueError(f"不支持的变异类型：{value}")
        return value

    @field_validator("target_location")
    @classmethod
    def _check_location(cls, value: str | None) -> str | None:
        if value is not None and value not in TARGET_LOCATIONS:
            raise ValueError(f"不支持的目标位置：{value}")
        return value


def parse_mutation_config(raw: dict[str, Any] | None) -> dict[str, Any]:
    """校验并规范化 mutation_config，返回可直接入库的 dict。

    顺序固定：先拦脚本键，再拦未知键与越界取值。两类错误都归
    400 ``SECURITY_MUTATION_INVALID``——配置侧错误不是请求格式错误，
    前端只需一条分支。

    Raises:
        AppError: 脚本键、未知键、重放次数或间隔越界。
    """
    from pydantic import ValidationError

    from app.shared.errors import CODE_SECURITY_MUTATION_INVALID, AppError

    config = raw or {}
    validate_no_script_keys(config)
    try:
        parsed = MutationConfig.model_validate(config)
    except ValidationError as exc:
        fields = [": ".join(str(p) for p in e.get("loc", ())) or "(root)" for e in exc.errors()]
        raise AppError(
            "变异配置不合法：" + "；".join(fields),
            status_code=400,
            code=CODE_SECURITY_MUTATION_INVALID,
        ) from exc
    # 丢掉空集合：没声明 methods / candidates 的规则应该入库为 {}，
    # 引擎读到 {"methods": []} 会误判成「显式声明了零个方法」。
    # 只丢空集合，不丢 0（replay_interval_ms=0 是合法取值）。
    data = {
        key: value
        for key, value in parsed.model_dump(exclude_none=True).items()
        if value != [] and value != {}
    }
    return data or {}


def validate_rule_expectation(mutation_type: str, expected: str | None) -> str:
    """校验期望与算子是否匹配，返回最终期望值（可推导时补默认）。

    Raises:
        ValueError: 期望不在该算子的允许集合内。
    """
    from app.shared.errors import CODE_SECURITY_EXPECTATION_INVALID, AppError

    allowed = MUTATION_EXPECTATIONS.get(mutation_type)
    if not allowed:
        raise AppError(
            f"不支持的变异类型：{mutation_type}",
            status_code=400,
            code=CODE_SECURITY_MUTATION_INVALID,
        )
    if expected is None:
        return DEFAULT_EXPECTATION_BY_TYPE[mutation_type]
    if expected not in SECURITY_EXPECTATIONS:
        raise AppError(
            f"不支持的安全期望：{expected}",
            status_code=400,
            code=CODE_SECURITY_EXPECTATION_INVALID,
        )
    if expected not in allowed:
        raise AppError(
            f"{mutation_type} 不能搭配期望 {expected}（仅支持 {'/'.join(allowed)}）",
            status_code=400,
            code=CODE_SECURITY_EXPECTATION_INVALID,
        )
    return expected


class MutationRuleResponse(_ORM):
    """变异规则响应。"""

    id: int
    project_id: int | None
    strategy_id: int
    name: str
    mutation_type: str
    target_location: str
    target_field: str | None = None
    operator: str
    mutation_config: dict[str, Any]
    expected_security_behavior: str
    expected_status_codes: list[int] | None = None
    severity: str
    enabled: bool
    confirmation_required: bool
    sort: int
    created_at: datetime | None = None
    updated_at: datetime | None = None


# --------------------------------------------------------------------------- 策略


class SecurityStrategyCreate(BaseModel):
    """创建项目自定义策略（只创建 scope=PROJECT）。

    预留攻击类允许保存，但 ``enabled`` 在服务层被强制 false。
    """

    name: str = Field(..., min_length=1, max_length=200)
    strategy_key: str = Field(..., min_length=1, max_length=100, pattern=STRATEGY_KEY_PATTERN)
    category: str = Field(..., min_length=1, max_length=40)
    description: str | None = Field(None, max_length=1000)
    enabled: bool = True
    risk_level: str = Field("MEDIUM", max_length=20)
    rules: list[MutationRuleCreate] = Field(default_factory=list, max_length=200)

    @field_validator("category")
    @classmethod
    def _check_category(cls, value: str) -> str:
        if value not in STRATEGY_CATEGORIES:
            raise ValueError(f"不支持的策略类别：{value}")
        return value

    @field_validator("risk_level")
    @classmethod
    def _check_risk(cls, value: str) -> str:
        if value not in SEVERITY_LEVELS:
            raise ValueError(f"不支持的风险级别：{value}")
        return value


class SecurityStrategyUpdate(BaseModel):
    """修改策略（系统模板 403；预留类别不能重新启用）。"""

    name: str | None = Field(None, min_length=1, max_length=200)
    description: str | None = Field(None, max_length=1000)
    enabled: bool | None = None
    risk_level: str | None = Field(None, max_length=20)
    revision: int | None = None

    @field_validator("risk_level")
    @classmethod
    def _check_risk(cls, value: str | None) -> str | None:
        if value is not None and value not in SEVERITY_LEVELS:
            raise ValueError(f"不支持的风险级别：{value}")
        return value


class SecurityStrategyResponse(_ORM):
    """策略响应（可携带规则列表）。"""

    id: int
    project_id: int | None = None
    scope: str
    name: str
    strategy_key: str
    category: str
    description: str | None = None
    enabled: bool
    risk_level: str
    builtin: bool
    created_by: int | None = None
    created_at: datetime | None = None
    updated_at: datetime | None = None
    revision: int = 1
    rules: list[MutationRuleResponse] = Field(default_factory=list)


class SecurityStrategyListResponse(BaseModel):
    items: list[SecurityStrategyResponse]
    total: int
    page: int
    page_size: int


# --------------------------------------------------------------------------- 计划（Phase E）

#: 单次 preview 允许选的策略上限。
MAX_STRATEGY_IDS = 50


class PlanPreviewRequest(BaseModel):
    """生成安全计划预览：三者必须且只能给一个目标。"""

    baseline_case_id: int | None = None
    api_id: int | None = None
    business_action_id: int | None = None
    strategy_ids: list[int] = Field(..., min_length=1, max_length=MAX_STRATEGY_IDS)
    environment_id: int | None = None
    name: str | None = Field(None, max_length=200)

    @field_validator("strategy_ids")
    @classmethod
    def _dedupe(cls, value: list[int]) -> list[int]:
        return list(dict.fromkeys(value))


class PlanPreviewItem(BaseModel):
    """预览里的一条计划项，形状即 §16.3。"""

    index: int
    name: str
    mutation_type: str
    target_type: str = "API"
    api_id: int | None = None
    business_action_id: int | None = None
    method: str | None = None
    location: str | None = None
    field: str | None = None
    expectation: str = "EXPECTED_DENY"
    expected_status_codes: list[int] | None = None
    severity: str = "MEDIUM"
    risk_level: str | None = None
    confirmation_required: bool = False
    blocked_reason: str | None = None
    mutation_config: dict[str, Any] = Field(default_factory=dict)
    source_rule_id: int | None = None
    source_strategy_id: int | None = None


class PlanPreviewResponse(BaseModel):
    plan_id: int
    status: str = "DRAFT"
    estimated_count: int
    truncated: bool = False
    items: list[PlanPreviewItem] = Field(default_factory=list)
    # 按 API / 业务动作目标生成时解析出的基线用例：计划 review 需要让用户看清
    # 变异会在哪条基线上做，而不只是看到策略与算子。
    baseline_case_id: int | None = None
    baseline_case_name: str | None = None


class PlanConfirmRequest(BaseModel):
    """确认哪些预览项要落成用例；空列表表示一条都不要。"""

    accepted_item_indexes: list[int] = Field(default_factory=list, max_length=200)
    plan_name: str | None = Field(None, max_length=200)


class PlanConfirmResponse(BaseModel):
    plan_id: int
    status: str
    created_case_ids: list[int] = Field(default_factory=list)
    created_count: int
    skipped_count: int


class SecurityPlanRead(_ORM):
    """计划响应，含未落 TestCase 的预览快照。"""

    id: int
    project_id: int
    name: str
    target_type: str
    api_id: int | None = None
    baseline_case_id: int | None = None
    business_action_id: int | None = None
    strategy_ids: list[int] | None = None
    status: str
    preview_json: Any = None
    estimated_count: int
    environment_id: int | None = None
    created_by: int | None = None
    confirmed_by: int | None = None
    confirmed_at: datetime | None = None
    created_at: datetime | None = None
    updated_at: datetime | None = None
    revision: int = 1


# --------------------------------------------------------------------------- 用例（Phase E）


class SecurityCaseRead(_ORM):
    """安全用例扩展数据响应。"""

    id: int
    project_id: int
    test_case_id: int
    plan_id: int | None = None
    baseline_case_id: int | None = None
    strategy_id: int | None = None
    rule_id: int | None = None
    api_id: int | None = None
    business_action_id: int | None = None
    mutation_type: str
    mutation_config: dict[str, Any] = Field(default_factory=dict)
    security_expectation: str
    risk_level: str | None = None
    confirmation_required: bool
    confirmed_by: int | None = None
    confirmed_at: datetime | None = None
    created_at: datetime | None = None
    updated_at: datetime | None = None


class SecurityCaseUpdate(BaseModel):
    """只允许改启用状态，同步 test_case.enabled。"""

    enabled: bool


class SecurityCaseDetail(SecurityCaseRead):
    """用例详情：带基线引用、最近一次执行与目标接口名。"""

    enabled: bool = True
    case_name: str | None = None
    baseline_case_name: str | None = None
    api_name: str | None = None
    rule_name: str | None = None
    latest_execution: SecurityExecutionRead | None = None


class SecurityCaseListResponse(BaseModel):
    items: list[SecurityCaseDetail]
    total: int
    page: int
    page_size: int


class SecurityRunRequest(BaseModel):
    """安全用例批量执行：内部走既有 TestPlan + TestRun，不写第二套执行器。"""

    security_case_ids: list[int] = Field(..., min_length=1, max_length=200)
    environment_id: int | None = None
    plan_name: str | None = Field(None, max_length=200)


# --------------------------------------------------------------------------- 执行（Phase E）


class SecurityExecutionRead(_ORM):
    """一次安全执行记录。mutation_trace 与 evidence 都已脱敏。"""

    id: int
    project_id: int
    test_run_id: int | None = None
    case_execution_id: int | None = None
    security_case_id: int
    environment_id: int | None = None
    actor_id: int | None = None
    baseline_status: BaselineStatus | None = None
    baseline_http_status: int | None = None
    security_result: str
    classification: str | None = None
    mutation_trace: list[dict[str, Any]] = Field(default_factory=list)
    replay_count: int = 1
    actual_status_codes: list[int] = Field(default_factory=list)
    evidence: dict[str, Any] | None = None
    error_code: str | None = None
    started_at: datetime | None = None
    finished_at: datetime | None = None
    created_at: datetime | None = None


# --------------------------------------------------------------------------- Finding（Phase E）


class SecurityFindingRead(_ORM):
    """疑似问题响应。Phase 1 不写 bug_id。"""

    id: int
    project_id: int
    test_run_id: int | None = None
    case_execution_id: int | None = None
    security_execution_id: int | None = None
    api_id: int | None = None
    business_action_id: int | None = None
    strategy_id: int | None = None
    security_case_id: int | None = None
    mutation_type: str
    severity: str
    status: str
    title: str
    description: str | None = None
    evidence: dict[str, Any] | None = None
    recommendation: str | None = None
    fingerprint: str
    bug_id: int | None = None
    created_by: int | None = None
    resolved_by: int | None = None
    created_at: datetime | None = None
    updated_at: datetime | None = None


class SecurityFindingUpdate(BaseModel):
    """只允许改状态；非法迁移由服务层 400。"""

    status: str

    @field_validator("status")
    @classmethod
    def _check_status(cls, value: str) -> str:
        if value not in FINDING_STATUSES:
            raise ValueError(f"不支持的 Finding 状态：{value}")
        return value


class SecurityFindingListResponse(BaseModel):
    items: list[SecurityFindingRead]
    total: int
    page: int
    page_size: int
