"""Security Testing 运行时的数据结构与引擎哨兵异常。

这里只放数据容器：不查库、不发 HTTP、不做算子逻辑。三条约定：

- ``BaselineRequest`` 的字段与 ``ApiRequestExecutor.execute`` 的参数一一对齐，
  所以 ``MutatedRequest.request`` 可以直接展开成执行器入参，不需要再转换。
- ``content_type`` + ``raw_body`` 是 Content-Type 变异的通道：httpx 走 ``json=``
  时会自己补 ``application/json``，所以 CONTENT_TYPE_MUTATION 必须把请求体落成
  原始 JSON 文本走 ``raw_body``（开发计划 §6.4）。
- 引擎异常只有三类出口：配置不合法 ``SECURITY_MUTATION_INVALID``、类别未开放
  ``SECURITY_MUTATION_NOT_ALLOWED``、缺确认 ``SECURITY_CONFIRMATION_REQUIRED``。
  后两类是执行结果而不是接口错误，Runner 写进 execution.error_code。
"""

from __future__ import annotations

import copy
from dataclasses import dataclass, field, replace
from typing import Any

from app.core.http.errors import (
    CODE_SECURITY_CONFIRMATION_REQUIRED,
    CODE_SECURITY_MUTATION_INVALID,
    AppError,
)


class RuleNotApplicableError(AppError):
    """规则与当前目标不匹配，应跳过而不是当执行失败。

    错误码仍是 ``SECURITY_MUTATION_INVALID``（§19），区别在类：Runner catch 这个
    子类时记 SKIPPED / INCONCLUSIVE，catch 普通 AppError 时记 FAILED_EXECUTION。
    典型场景是 ZERO 点在一个 string 字段上、或参数规则没有展开到具体字段。
    """


class ConfirmationRequiredError(AppError):
    """高风险变异未经成员确认，禁止发出请求。

    错误码 ``SECURITY_CONFIRMATION_REQUIRED``：接口层 400（确认接口缺 body），
    执行期写进 execution.error_code 并 SKIPPED（§18.4）。
    """


@dataclass
class FieldSpec:
    """一个可变异字段的 schema 描述，由 ``schema_reader`` 产出。

    ``json_path`` 用于 body 字段的定位（``$.parent.child``）；PATH/QUERY/HEADER/COOKIE
    没有路径，只靠 name。``type`` 保留原始写法，nullable 用 ``integer|null`` 这种
    形式承载，取主类型用 ``primary_type``。
    """

    location: str  # 请求字段位置：PATH / QUERY / HEADER / COOKIE / BODY
    name: str
    json_path: str | None = None
    type: str = "string"  # 支持的数据类型：integer / number / string / boolean / object / array
    required: bool = False
    enum: list[Any] | None = None
    minimum: float | None = None
    maximum: float | None = None
    min_length: int | None = None
    max_length: int | None = None
    format: str | None = None  # 支持的格式：email / date / uuid / uri
    example: Any = None

    @property
    def primary_type(self) -> str:
        """主类型：剥掉 ``|null`` 这类联合标记，空串归一为 string。"""
        base = (self.type or "").lower().split("|")[0].strip()
        return base or "string"

    @property
    def nullable(self) -> bool:
        """schema 是否显式声明可空（``type`` 含 null，或 example 就是 null）。"""
        return "null" in (self.type or "").lower()


@dataclass
class MutationRuleView:
    """引擎看到的规则只读视图。

    规则表上没有 category 列（category 在策略上），所以这里允许为空：为空时引擎
    按 mutation_type 反查（``operators.CATEGORY_BY_MUTATION_TYPE``）。视图不引用
    ORM 实例，保证引擎可以在没有会话的情况下被调用。
    """

    mutation_type: str
    target_location: str
    target_field: str | None = None
    mutation_config: dict[str, Any] = field(default_factory=dict)
    expected_security_behavior: str = "EXPECTED_DENY"
    expected_status_codes: list[int] | None = None
    severity: str = "MEDIUM"
    category: str | None = None
    confirmation_required: bool = False

    @classmethod
    def from_row(cls, row: Any) -> MutationRuleView:
        """从 ORM 行或 dict 构造视图，缺列按默认值补齐。"""

        def pick(name: str, default: Any = None) -> Any:
            """选取对应数据。"""
            if isinstance(row, dict):
                return row.get(name, default)
            return getattr(row, name, default)

        return cls(
            mutation_type=str(pick("mutation_type") or ""),
            target_location=str(pick("target_location") or "").upper(),
            target_field=pick("target_field"),
            mutation_config=dict(pick("mutation_config") or {}),
            expected_security_behavior=str(pick("expected_security_behavior") or "EXPECTED_DENY"),
            expected_status_codes=pick("expected_status_codes"),
            severity=str(pick("severity") or "MEDIUM"),
            category=pick("category"),
            confirmation_required=bool(pick("confirmation_required")),
        )


@dataclass
class ResolveScope:
    """已解析的 Fixture 输出作用域。

    Phase C 由 ``candidate_resolver`` 从 RuntimeContext 填；Phase B 允许直接构造，
    便于单测。``fixtures`` 形如 ``{"USER_B": {"token": "***"}}``：外层键是
    fixture_key，内层键是 output 名。引擎只从这里取替换值——不用随机数、不拿
    平台 project.id 去猜。
    """

    fixtures: dict[str, dict[str, Any]] = field(default_factory=dict)

    def get(self, source: dict[str, Any] | None) -> Any | None:
        """按 ``{fixture_key, output}`` 取一个值；缺任一层返回 None。"""
        if not isinstance(source, dict):
            return None
        key = str(source.get("fixture_key") or "").strip()
        output = str(source.get("output") or "").strip()
        if not key or not output:
            return None
        bucket = self.fixtures.get(key)
        if not isinstance(bucket, dict):
            return None
        return bucket.get(output)

    @classmethod
    def from_mapping(cls, mapping: dict[str, Any] | None) -> ResolveScope:
        """从 ``{fixture_key: {output: value}}`` 直接构造。"""
        return cls(fixtures=dict(mapping or {}))


@dataclass
class MutationContext:
    """算子上下文：规则视图 + 目标字段 + Fixture 作用域。

    ``notes`` 是算子回报「没法测」的通道（例如基线没有 Authorization 头），
    引擎会原样带进 ``MutatedRequest.notes``，Runner 据此写 INCONCLUSIVE。
    """

    rule: MutationRuleView
    spec: FieldSpec | None
    scope: ResolveScope
    auth_header: str
    confirmed: bool = False
    notes: list[str] = field(default_factory=list)


@dataclass
class BaselineRequest:
    """基线请求：与 ``ApiRequestExecutor.execute`` 的参数集合对齐。

    ``path`` 是 Catalog 路径模板（含 ``{param}``），``path_params`` 是取值；
    URL 由执行器拼，引擎不接收绝对 URL。
    """

    method: str
    path: str
    path_params: dict[str, str] = field(default_factory=dict)
    query: dict[str, str] = field(default_factory=dict)
    headers: dict[str, str] = field(default_factory=dict)
    cookies: dict[str, str] = field(default_factory=dict)
    json_body: dict | list | None = None
    form_body: dict[str, str] | None = None
    raw_body: str | None = None
    content_type: str | None = None
    timeout: int = 30
    api_id: int | None = None
    project_id: int | None = None
    auth_type: str = "none"

    def copy(self) -> BaselineRequest:
        """深拷贝一层容器：算子只改副本，调用方入参不受影响。"""
        return replace(
            self,
            path_params=dict(self.path_params),
            query=dict(self.query),
            headers=dict(self.headers),
            cookies=dict(self.cookies),
            json_body=copy.deepcopy(self.json_body) if self.json_body is not None else None,
            form_body=copy.deepcopy(self.form_body) if self.form_body else None,
        )


@dataclass
class MutationTraceEntry:
    """一条变异记录（before/after 落库前必须脱敏）。"""

    mutation_type: str
    location: str
    field: str | None = None
    before: Any = None
    after: Any = None
    note: str | None = None

    def to_dict(self) -> dict[str, Any]:
        """落库形态。敏感键的值在这里替换成 ``******``。

        脱敏在序列化点做，保证任何调用路径都不会把 Token 原值写进数据库；
        延迟 import 是为避开 ``trace`` 与本模块的循环依赖。
        """
        from app.features.security_testing.runtime.trace import mask_value

        data: dict[str, Any] = {
            "mutation_type": self.mutation_type,
            "location": self.location,
            "field": self.field,
            "before": mask_value(self.field, self.before),
            "after": mask_value(self.field, self.after),
        }
        if self.note:
            data["note"] = self.note
        return data


@dataclass
class MutatedRequest:
    """变异后的请求 + trace。

    ``request`` 是真正要发给执行器的请求；``changed`` 为 false 且 ``notes`` 非空
    说明「基线不具备可测条件」，Runner 记 INCONCLUSIVE 而不是 PASS。
    """

    request: BaselineRequest
    mutation_type: str
    traces: list[MutationTraceEntry] = field(default_factory=list)
    notes: list[str] = field(default_factory=list)
    changed: bool = True

    def to_dicts(self) -> list[dict[str, Any]]:
        """trace 的落库形态（已脱敏）。"""
        return [entry.to_dict() for entry in self.traces]
