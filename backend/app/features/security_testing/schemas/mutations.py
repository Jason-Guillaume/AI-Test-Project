"""security_testing 资源契约；字段、默认值、校验和 wire 名称保持不变。"""

from __future__ import annotations

from app.core.http.errors import CODE_SECURITY_MUTATION_INVALID
from datetime import datetime
from typing import Any
from pydantic import BaseModel, ConfigDict, Field, field_validator
from app.features.security_testing.schemas.common import DEFAULT_EXPECTATION_BY_TYPE
from app.features.security_testing.schemas.common import FORBIDDEN_CONFIG_KEYS
from app.features.security_testing.schemas.common import MUTATION_EXPECTATIONS
from app.features.security_testing.schemas.common import MUTATION_TYPES
from app.features.security_testing.schemas.common import REPLAY_INTERVAL_MAX_MS
from app.features.security_testing.schemas.common import SECURITY_EXPECTATIONS
from app.features.security_testing.schemas.common import SEVERITY_LEVELS
from app.features.security_testing.schemas.common import TARGET_LOCATIONS
from app.features.security_testing.schemas.common import _ORM


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
    from app.core.http.errors import CODE_SECURITY_MUTATION_INVALID, AppError

    def walk(node: Any, path: str) -> None:
        """遍历对应数据。"""
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
        """检查`codes`。"""
        if value is None:
            return None
        for code in value:
            if not 100 <= code <= 599:
                raise ValueError(f"期望状态码必须是 100-599 之间的整数：{code}")
        return value

    @field_validator("severity")
    @classmethod
    def _check_severity(cls, value: str | None) -> str | None:
        """检查严重级别。"""
        if value is None:
            return None
        if value not in SEVERITY_LEVELS:
            raise ValueError(f"不支持的严重级别：{value}")
        return value

    @field_validator("mutation_type")
    @classmethod
    def _check_type(cls, value: str) -> str:
        """检查类型。"""
        if value not in MUTATION_TYPES:
            raise ValueError(f"不支持的变异类型：{value}")
        return value

    @field_validator("target_location")
    @classmethod
    def _check_location(cls, value: str) -> str:
        """检查`location`。"""
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
        """检查`codes`。"""
        if value is None:
            return None
        for code in value:
            if not 100 <= code <= 599:
                raise ValueError(f"期望状态码必须是 100-599 之间的整数：{code}")
        return value

    @field_validator("severity")
    @classmethod
    def _check_severity(cls, value: str | None) -> str | None:
        """检查严重级别。"""
        if value is None:
            return None
        if value not in SEVERITY_LEVELS:
            raise ValueError(f"不支持的严重级别：{value}")
        return value

    @field_validator("mutation_type")
    @classmethod
    def _check_type(cls, value: str | None) -> str | None:
        """检查类型。"""
        if value is not None and value not in MUTATION_TYPES:
            raise ValueError(f"不支持的变异类型：{value}")
        return value

    @field_validator("target_location")
    @classmethod
    def _check_location(cls, value: str | None) -> str | None:
        """检查`location`。"""
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

    from app.core.http.errors import CODE_SECURITY_MUTATION_INVALID, AppError

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
    from app.core.http.errors import CODE_SECURITY_EXPECTATION_INVALID, AppError

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
