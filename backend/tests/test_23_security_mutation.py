"""验收项 23：Security Testing Phase B/C 单元测试——变异引擎与纯函数。

覆盖开发计划 §6（引擎）、§10（Fixture 数据约定）、§18（边界）、§19（错误码）与
§20.1（算子、trace 脱敏、断言与严重级别），以及 Phase C 的授权 / IDOR 算子。全部是纯函数测试：不连数据库、不发 HTTP、
不启动 FastAPI，因此不会碰 testplatform_dev。

关键锁点：
- 引擎纯函数：runtime 目录禁止 import httpx / sqlalchemy，禁止 eval（AST 级断言）
- 认证类算子用固定哨兵，不伪造 JWT；基线没有鉴权头时记无法下结论而不是 PASS
- 参数变异只执行规则点名的字段，无 schema 不自动 fuzz
- 授权 / IDOR 候选只来自 Fixture 输出：有候选则替换；无候选抛 SECURITY_FIXTURE_REQUIRED，
  退回平台 project_id 的机会一次都没有
- Content-Type 变异必须走 raw_body，否则 httpx 会改回 application/json
- Trace 落库前脱敏：Authorization 的 before/after 都是 ******，资源 ID 保持明文
- 断言与严重级别只走固定表，不出现 VULNERABLE
"""

from __future__ import annotations

import ast
from pathlib import Path
from types import SimpleNamespace

import pytest

from app.features.api_catalog.models.api_parameter import ApiParameter
from app.features.api_catalog.models.api_request_body import ApiRequestBody

from app.features.security_testing.runtime.assertion import assert_expectation
from app.features.security_testing.runtime.candidate_resolver import (
    parse_source,
    read_sources,
    resource_target,
    resolve_value,
)
from app.features.security_testing.runtime.mutation_engine import SecurityMutationEngine
from app.features.security_testing.runtime.operators import (
    CONTENT_TYPE_TARGET,
    OPERATORS,
    INVALID_TOKEN_VALUE,
    MALFORMED_TOKEN_VALUE,
    WRONG_AUTH_SCHEME_VALUE,
    get_operator,
    resolve_auth_header,
)
from app.features.security_testing.runtime.schema_reader import (
    INVALID_FORMAT_SAMPLES,
    body_fields,
    field_spec_from_parameter,
    find_field,
    integer_variants,
    invalid_enum_value,
    invalid_format_value,
    over_max_capped,
    over_max_value,
    read_fields,
    resolve_nested_spec,
    type_mutation_value,
    under_min_value,
    value_for,
)
from app.features.security_testing.runtime.severity import (
    DEFAULT_FINDING_SEVERITY,
    SeverityContext,
    resolve_severity,
)
from app.features.security_testing.runtime.trace import (
    MASKED,
    entries_to_dicts,
    mask_value,
    request_diff,
    request_snapshot,
)
from app.features.security_testing.runtime.types import (
    BaselineRequest,
    ConfirmationRequiredError,
    FieldSpec,
    MutationRuleView,
    MutationTraceEntry,
    ResolveScope,
    RuleNotApplicableError,
)
from app.features.security_testing.schemas import (
    MAX_MUTATION_STRING_LENGTH,
    MUTATION_TYPES,
    SECURITY_EXPECTATIONS,
    SECURITY_RESULTS,
)
from app.shared.errors import (
    CODE_SECURITY_CONFIRMATION_REQUIRED,
    CODE_SECURITY_EXPECTATION_INVALID,
    CODE_SECURITY_FIXTURE_REQUIRED,
    CODE_SECURITY_MUTATION_INVALID,
    CODE_SECURITY_MUTATION_NOT_ALLOWED,
    AppError,
)
from tests.conftest import BACKEND_DIR

RUNTIME_DIR = BACKEND_DIR / "app" / "features" / "security_testing" / "runtime"

#: 执行器所在模块。runtime 里只有 runner.py 允许引用它。
_EXECUTOR_MODULE = "app.features.business.executors.api_executor"


def _imports_executor(path: Path) -> bool:
    """这个文件是否真的 import 了请求执行器（只看 AST，不含注释/docstring）。"""
    tree = ast.parse(path.read_text())
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            refs = [alias.name for alias in node.names]
        elif isinstance(node, ast.ImportFrom):
            refs = [node.module or ""]
        else:
            continue
        if any(ref == _EXECUTOR_MODULE or ref.startswith(_EXECUTOR_MODULE + ".") for ref in refs):
            return True
    return False

# 一个真实样子的 Bearer Token，用来验证脱敏与「不被伪造」两条断言。
TOKEN = "Bearer eyJhbGciOiJIUzI1NiJ9.eyJzdWIiOiJ1c2VyLTAwMSJ9.c2ln"
# 另一个用户的 Token（Fixture 输出，不是平台签发的）。
OTHER_TOKEN = "Bearer user-b-token-from-fixture"


# --------------------------------------------------------------------------- 构造助手


def _baseline(**overrides) -> BaselineRequest:
    """一条带鉴权头与 JSON 请求体的基线请求。"""
    base = dict(
        method="POST",
        path="/api/projects/{project_id}/tasks",
        path_params={"project_id": "7"},
        query={"page": "1"},
        headers={"Authorization": TOKEN, "Content-Type": "application/json"},
        cookies={"session_id": "sess-001"},
        json_body={"name": "任务A", "priority": 3},
        content_type="application/json",
        api_id=1,
        project_id=7,
        auth_type="bearer",
    )
    base.update(overrides)
    return BaselineRequest(**base)


def _rule(mutation_type: str = "REMOVE_TOKEN", **overrides) -> MutationRuleView:
    """一条认证类规则；测试里按需覆盖字段。"""
    base = dict(
        mutation_type=mutation_type,
        target_location="HEADER",
        target_field="Authorization",
        mutation_config={},
        expected_security_behavior="EXPECTED_DENY",
        expected_status_codes=None,
        severity="MEDIUM",
        category=None,
        confirmation_required=False,
    )
    base.update(overrides)
    return MutationRuleView(**base)


def _apply(
    rule: MutationRuleView,
    *,
    baseline: BaselineRequest | None = None,
    scope=None,
    fields=None,
    confirmed: bool = False,
    auth_type: str | None = None,
):
    """跑一次引擎，返回 MutatedRequest。"""
    return SecurityMutationEngine.apply(
        baseline or _baseline(),
        rule,
        scope=scope,
        fields=fields,
        confirmed=confirmed,
        auth_type=auth_type,
    )


def _body_rule(mutation_type: str, target_field: str = "priority", **overrides) -> MutationRuleView:
    """一条参数类规则（目标位置 BODY）。"""
    base = dict(
        mutation_type=mutation_type,
        target_location="BODY",
        target_field=target_field,
        expected_security_behavior="EXPECTED_VALIDATION_ERROR",
    )
    base.update(overrides)
    return _rule(**base)


def _spec(**overrides) -> FieldSpec:
    """构造安全测试字段规范。"""
    base = dict(location="BODY", name="priority", type="integer", required=True)
    base.update(overrides)
    return FieldSpec(**base)


def _expect_error(exc_type, code: str, fn):
    """断言抛出的异常类型与错误码，返回异常实例。"""
    with pytest.raises(exc_type) as caught:
        fn()
    assert caught.value.code == code, caught.value.code
    return caught.value


def _fields_for(rule: MutationRuleView, spec: FieldSpec) -> list[FieldSpec]:
    """让规则的目标位置与 spec 对齐（避免测试被定位逻辑干扰）。"""
    if rule.target_location != "BODY":
        spec.location = rule.target_location
        spec.json_path = None
    return [spec]


# --------------------------------------------------------------------------- 源码边界


class TestSourceGuards:
    """§6.3：引擎是纯函数，禁止出站、查库、eval。

    ``runner.py`` 是文档化的唯一例外（§21 Phase E）：它负责查库、写 execution、
    调 ``ApiRequestExecutor``。变异、断言、严重级别仍然是纯函数。对 runner 单独
    断言「不直接 import httpx」——出站必须经由执行器，不能自己拼 httpx 调用。
    """

    def test_runtime_modules_do_no_http_db_or_eval(self) -> None:
        """验证运行时`modules``do`无HTTP数据库或`eval`场景及其预期结果。"""
        for path in sorted(RUNTIME_DIR.glob("*.py")):
            is_runner = path.name == "runner.py"
            tree = ast.parse(path.read_text())
            for node in ast.walk(tree):
                if isinstance(node, ast.Import):
                    roots = [alias.name.split(".")[0] for alias in node.names]
                    assert "httpx" not in roots, f"{path.name} 直接 import httpx"
                    if not is_runner:
                        assert "sqlalchemy" not in roots, f"{path.name} 直接 import sqlalchemy"
                elif isinstance(node, ast.ImportFrom):
                    root = (node.module or "").split(".")[0]
                    assert root not in {"httpx"}, f"{path.name} import {root}"
                    if not is_runner:
                        assert root not in {"sqlalchemy"}, f"{path.name} import {root}"
                elif isinstance(node, ast.Call):
                    func = node.func
                    if isinstance(func, ast.Name) and func.id in {"eval", "exec", "compile"}:
                        pytest.fail(f"{path.name} 调用了 {func.id}()")

    def test_runner_is_the_only_outbound_module(self) -> None:
        """出站执行器只允许 runner.py 引用；其余模块必须保持纯函数。

        按 AST 看 import，不做全文子串匹配：``baseline`` / ``types`` / ``replay`` 的
        docstring 会提到执行器名，只为说明字段与超时和谁对齐，那不是依赖。
        """
        offenders = [
            path.name
            for path in sorted(RUNTIME_DIR.glob("*.py"))
            if path.name != "runner.py"
            and _imports_executor(path)
        ]
        assert offenders == [], f"只有 runner.py 可以引用执行器：{offenders}"

    def test_runner_imports_the_executor(self) -> None:
        """runner 必须真的接上执行器，否则所有闸门都只拦自己。"""
        assert _imports_executor(RUNTIME_DIR / "runner.py")

    def test_no_result_value_uses_vulnerable(self) -> None:
        """§5.6：结果只用五态，不使用「已确认漏洞」。"""
        assert "VULNERABLE" not in SECURITY_RESULTS
        result = assert_expectation("EXPECTED_DENY", 200, mutation_type="REMOVE_TOKEN")
        assert "VULNERABLE" not in result.security_result.upper()


# --------------------------------------------------------------------------- 结构读取器 Schema Reader


class TestSchemaReader:
    """§6.5：字段 schema 读取与取值生成。"""

    def test_parameter_row_schema_overrides_column_type(self) -> None:
        """验证`parameter``row`结构定义`overrides``column`类型场景及其预期结果。"""
        row = ApiParameter(
            name="limit", location="QUERY", type="string", required=True,
            schema_json={"type": "integer", "minimum": 0, "maximum": 100},
        )
        spec = field_spec_from_parameter(row)
        assert spec.location == "QUERY"
        assert spec.name == "limit"
        assert spec.primary_type == "integer"
        assert spec.minimum == 0.0
        assert spec.maximum == 100.0
        assert spec.required is True

    def test_parameter_row_without_schema_keeps_column_type(self) -> None:
        """验证`parameter``row`不带结构定义`keeps``column`类型场景及其预期结果。"""
        row = ApiParameter(name="trace", location="HEADER", type="string", required=False)
        spec = field_spec_from_parameter(row)
        assert spec.primary_type == "string"
        assert spec.maximum is None

    def test_body_json_schema_expands_first_level_only(self) -> None:
        """验证请求体JSON结构定义`expands``first``level`仅场景及其预期结果。"""
        body = ApiRequestBody(
            body_type="json",
            schema_json={
                "type": "object",
                "required": ["name", "priority"],
                "properties": {
                    "name": {"type": "string", "maxLength": 20},
                    "priority": {"type": "integer", "minimum": 1, "maximum": 10},
                    "nested": {"type": "object", "properties": {"a": {"type": "string"}}},
                },
            },
        )
        specs = body_fields(body)
        assert [s.name for s in specs] == ["name", "priority", "nested"]
        by_name = {s.name: s for s in specs}
        assert by_name["name"].max_length == 20
        assert by_name["name"].required is True
        assert by_name["priority"].minimum == 1.0
        # 第二层只在规则点名时读取，不递归整棵树。
        assert by_name["nested"].type == "object"
        assert resolve_nested_spec(body, "$.nested.a").name == "a"
        assert resolve_nested_spec(body, "$.nested.a").json_path == "$.nested.a"
        assert resolve_nested_spec(body, "$.nested.missing") is None

    def test_nullable_type_marks_spec_nullable(self) -> None:
        """验证可空类型`marks``spec`可空场景及其预期结果。"""
        body = ApiRequestBody(
            body_type="json",
            schema_json={"properties": {"remark": {"type": ["string", "null"]}}},
        )
        spec = body_fields(body)[0]
        assert spec.primary_type == "string"
        assert spec.nullable is True

    def test_form_field_tree(self) -> None:
        """验证`form`字段`tree`场景及其预期结果。"""
        body = ApiRequestBody(
            body_type="form",
            schema_json={"fields": [
                {"name": "file_name", "type": "string", "required": True},
                {"name": "size", "type": "integer"},
            ]},
        )
        specs = body_fields(body)
        assert [(s.name, s.location, s.required) for s in specs] == [
            ("file_name", "BODY", True),
            ("size", "BODY", False),
        ]

    def test_no_schema_yields_no_parameter_fields(self) -> None:
        """§20.1：无 schema 时不生成参数变异。"""
        assert read_fields([], None) == []
        assert body_fields(None) == []
        assert body_fields(ApiRequestBody(body_type="json", schema_json=None)) == []
        assert body_fields(ApiRequestBody(body_type="raw", schema_json={"raw": "x"})) == []

    def test_find_field_case_rules(self) -> None:
        """验证查找字段用例`rules`场景及其预期结果。"""
        specs = [
            FieldSpec(location="HEADER", name="X-Request-Id"),
            FieldSpec(location="BODY", name="trace", json_path="$.trace"),
        ]
        assert find_field(specs, "HEADER", "x-request-id") is not None
        assert find_field(specs, "BODY", "trace") is not None
        assert find_field(specs, "BODY", "TRACE") is None
        assert find_field([], "HEADER", "Authorization") is None
        assert find_field(specs, "HEADER", "") is None

    def test_integer_variants_are_the_fixed_set(self) -> None:
        """整数 schema 展开 null / "abc" / -1 / 0 / maximum+1，不生成随机长串。"""
        assert integer_variants(_spec(type="integer", maximum=10)) == [None, "abc", -1, 0, 11]
        assert integer_variants(_spec(type="integer")) == [None, "abc", -1, 0]

    def test_over_max_value_for_number_and_string(self) -> None:
        """验证`over``max`值用于`number`和`string`场景及其预期结果。"""
        assert over_max_value(_spec(type="integer", maximum=10)) == 11
        assert len(over_max_value(_spec(type="string", max_length=10))) == 11
        assert over_max_capped(_spec(type="string", max_length=10)) is False

    def test_over_max_string_is_capped_at_256(self) -> None:
        """验证`over``max``string`是否`capped``at`场景及其预期结果。"""
        spec = _spec(type="string", max_length=100000)
        assert over_max_capped(spec) is True
        assert len(over_max_value(spec)) == MAX_MUTATION_STRING_LENGTH

    def test_under_min_value(self) -> None:
        """验证`under``min`值场景及其预期结果。"""
        assert under_min_value(_spec(type="integer", minimum=1)) == 0
        assert len(under_min_value(_spec(type="string", min_length=5))) == 4
        _expect_error(
            RuleNotApplicableError, CODE_SECURITY_MUTATION_INVALID,
            lambda: under_min_value(_spec(type="string", min_length=1)),
        )
        _expect_error(
            RuleNotApplicableError, CODE_SECURITY_MUTATION_INVALID,
            lambda: under_min_value(_spec(type="string")),
        )

    def test_invalid_enum_prefers_unknown_then_fallback(self) -> None:
        """验证无效`enum``prefers`未知`then``fallback`场景及其预期结果。"""
        assert invalid_enum_value(_spec(enum=["A", "B"])) == "UNKNOWN"
        assert invalid_enum_value(_spec(enum=["A", "UNKNOWN"])) == "__INVALID__"
        _expect_error(
            RuleNotApplicableError, CODE_SECURITY_MUTATION_INVALID,
            lambda: invalid_enum_value(_spec()),
        )

    @pytest.mark.parametrize("fmt,sample", sorted(INVALID_FORMAT_SAMPLES.items()))
    def test_invalid_format_samples(self, fmt: str, sample: str) -> None:
        """验证无效格式化`samples`场景及其预期结果。"""
        spec = _spec(type="string", format=fmt)
        assert invalid_format_value(spec) == sample
        assert value_for(spec, "INVALID_FORMAT") == sample

    def test_invalid_format_rejects_unknown_format(self) -> None:
        """验证无效格式化拒绝未知格式化场景及其预期结果。"""
        _expect_error(
            RuleNotApplicableError, CODE_SECURITY_MUTATION_INVALID,
            lambda: invalid_format_value(_spec(type="string", format="phone")),
        )

    def test_type_mutation_matrix(self) -> None:
        """验证类型变异`matrix`场景及其预期结果。"""
        assert type_mutation_value(_spec(type="integer")) == "abc"
        assert type_mutation_value(_spec(type="number")) == "abc"
        assert type_mutation_value(_spec(type="string")) == 1
        assert type_mutation_value(_spec(type="boolean")) == "yes"
        _expect_error(
            RuleNotApplicableError, CODE_SECURITY_MUTATION_INVALID,
            lambda: type_mutation_value(_spec(type="object")),
        )

    def test_value_for_rejects_null_when_nullable_and_optional(self) -> None:
        """验证值用于拒绝`null`当可空和可选场景及其预期结果。"""
        _expect_error(
            RuleNotApplicableError, CODE_SECURITY_MUTATION_INVALID,
            lambda: value_for(_spec(type="string|null", required=False), "NULL_VALUE"),
        )
        assert value_for(_spec(type="string|null", required=True), "NULL_VALUE") is None

    def test_value_for_rejects_mismatched_operators(self) -> None:
        """验证值用于拒绝`mismatched``operators`场景及其预期结果。"""
        _expect_error(RuleNotApplicableError, CODE_SECURITY_MUTATION_INVALID,
                      lambda: value_for(_spec(type="integer"), "EMPTY_STRING"))
        _expect_error(RuleNotApplicableError, CODE_SECURITY_MUTATION_INVALID,
                      lambda: value_for(_spec(type="string"), "ZERO"))
        _expect_error(RuleNotApplicableError, CODE_SECURITY_MUTATION_INVALID,
                      lambda: value_for(_spec(type="string"), "INVALID_ENUM"))


# --------------------------------------------------------------------------- 认证算子


class TestAuthenticationOperators:
    """§6.4 认证类算子：固定哨兵，不伪造 JWT。"""

    def test_remove_token_drops_authorization_and_masks_trace(self) -> None:
        """Phase B 验收：输出请求没有 Authorization，trace 已脱敏。"""
        result = _apply(_rule("REMOVE_TOKEN"))
        assert "Authorization" not in result.request.headers
        assert result.changed is True
        assert result.notes == []
        (entry,) = result.traces
        assert entry.field == "Authorization"
        assert entry.before == TOKEN          # 内存里保留原值用于比对
        assert entry.after is None
        dumped = result.to_dicts()[0]
        assert dumped["before"] == MASKED
        assert dumped["after"] is None
        assert TOKEN not in result.to_dicts()[0]["before"]

    def test_engine_does_not_mutate_baseline(self) -> None:
        """验证引擎是否不`mutate`基线场景及其预期结果。"""
        baseline = _baseline()
        snapshot = baseline.copy()
        _apply(_rule("REMOVE_TOKEN"), baseline=baseline)
        assert baseline == snapshot
        assert baseline.headers["Authorization"] == TOKEN
        assert baseline.json_body == {"name": "任务A", "priority": 3}

    def test_empty_token_keeps_bearer_prefix(self) -> None:
        """验证空值令牌`keeps``bearer``prefix`场景及其预期结果。"""
        result = _apply(_rule("EMPTY_TOKEN"))
        assert result.request.headers["Authorization"] == "Bearer "

    def test_empty_token_without_scheme_becomes_empty_string(self) -> None:
        """验证空值令牌不带`scheme``becomes`空值`string`场景及其预期结果。"""
        result = _apply(
            _rule("EMPTY_TOKEN"),
            baseline=_baseline(headers={"Authorization": "dG9rZW4=", "Content-Type": "application/json"}),
        )
        assert result.request.headers["Authorization"] == ""

    def test_invalid_token_uses_fixed_sentinel(self) -> None:
        """验证无效令牌`uses``fixed``sentinel`场景及其预期结果。"""
        result = _apply(_rule("INVALID_TOKEN"))
        assert result.request.headers["Authorization"] == INVALID_TOKEN_VALUE

    def test_malformed_token_uses_fixed_sentinel(self) -> None:
        """验证`malformed`令牌`uses``fixed``sentinel`场景及其预期结果。"""
        result = _apply(_rule("MALFORMED_TOKEN"))
        assert result.request.headers["Authorization"] == MALFORMED_TOKEN_VALUE

    def test_wrong_auth_scheme_uses_fixed_invalid_basic(self) -> None:
        """验证`wrong`认证`scheme``uses``fixed`无效基础场景及其预期结果。"""
        result = _apply(_rule("WRONG_AUTH_SCHEME"))
        assert result.request.headers["Authorization"] == WRONG_AUTH_SCHEME_VALUE
        assert "Bearer" not in result.request.headers["Authorization"]

    def test_sentinels_are_not_jwt_shaped(self) -> None:
        """固定哨兵不是伪造的 JWT：没有三段 base64 结构。"""
        for value in (INVALID_TOKEN_VALUE, MALFORMED_TOKEN_VALUE, WRONG_AUTH_SCHEME_VALUE):
            payload = value.split(" ", 1)[-1]
            assert payload.count(".") < 2, value

    def test_missing_auth_header_is_inconclusive_not_pass(self) -> None:
        """基线没有鉴权头时记「无法下结论」，不假装测过。"""
        result = _apply(
            _rule("REMOVE_TOKEN"),
            baseline=_baseline(headers={"Content-Type": "application/json"}),
        )
        assert result.changed is False
        assert result.notes == ["基线无 Authorization 头，无法验证认证是否生效"]
        assert result.traces[0].note == "基线无此头"

    def test_cookie_auth_targets_cookie_header(self) -> None:
        """auth_type=cookie 时按 Cookie 头定位；有头就删，没有才记无法下结论。"""
        result = _apply(
            _rule("REMOVE_TOKEN"),
            baseline=_baseline(headers={"Cookie": "sid=abc", "Content-Type": "application/json"}),
            auth_type="cookie",
        )
        assert "Cookie" not in result.request.headers
        assert result.traces[0].field == "Cookie"
        assert result.notes == []

        missing = _apply(
            _rule("REMOVE_TOKEN"),
            baseline=_baseline(headers={"Content-Type": "application/json"}),
            auth_type="cookie",
        )
        assert missing.changed is False
        assert missing.notes == ["基线无 Cookie 头，无法验证认证是否生效"]

    @pytest.mark.parametrize(
        "auth_type,headers,expected",
        [
            ("bearer", {"Authorization": TOKEN}, "Authorization"),
            ("basic", {"Authorization": "Basic abc"}, "Authorization"),
            ("cookie", {"Cookie": "sid=1"}, "Cookie"),
            ("apikey", {"X-Api-Key": "k"}, "X-Api-Key"),
            ("apikey", {"api_key": "k"}, "api_key"),
            ("apikey", {"Authorization": TOKEN}, "Authorization"),
            ("unknown", {"Authorization": TOKEN}, "Authorization"),
            ("none", {"X-Api-Key": "k"}, "X-Api-Key"),
            ("none", {"Content-Type": "application/json"}, "Authorization"),
        ],
    )
    def test_resolve_auth_header(self, auth_type: str, headers: dict, expected: str) -> None:
        """验证解析并确定认证请求头场景及其预期结果。"""
        assert resolve_auth_header(auth_type, headers) == expected

    def test_expired_token_requires_fixture_source(self) -> None:
        """平台没有过期 JWT 生成器：没有 token_source 直接拒绝。"""
        err = _expect_error(
            RuleNotApplicableError, CODE_SECURITY_MUTATION_INVALID,
            lambda: _apply(_rule("EXPIRED_TOKEN")),
        )
        assert "EXPIRED_TOKEN" in err.message

    def test_expired_token_missing_fixture_output(self) -> None:
        """验证`expired`令牌缺失固定数据输出场景及其预期结果。"""
        err = _expect_error(
            AppError, CODE_SECURITY_FIXTURE_REQUIRED,
            lambda: _apply(
                _rule("EXPIRED_TOKEN", mutation_config={"token_source": {"fixture_key": "USER_A", "output": "expired_token"}}),
                scope=ResolveScope.from_mapping({"USER_A": {"token": TOKEN}}),
            ),
        )
        assert "Fixture" in err.message

    def test_expired_token_uses_fixture_value_verbatim(self) -> None:
        """过期 Token 原样取自 Fixture 输出：不解码、不拼接。"""
        expired = "expired-jwt-from-tester"
        result = _apply(
            _rule("EXPIRED_TOKEN", mutation_config={"token_source": {"fixture_key": "USER_A", "output": "expired_token"}}),
            scope=ResolveScope.from_mapping({"USER_A": {"expired_token": expired}}),
        )
        assert result.request.headers["Authorization"] == expired
        assert result.traces[0].note == "过期 Token 取自 Fixture 输出"

    def test_authorization_mutation_with_source_swaps_identity(self) -> None:
        """带 token_source 时换成 Fixture 里的另一个身份；值原样取用。"""
        result = _apply(
            _rule("AUTHORIZATION_MUTATION", target_location="HEADER", target_field="Authorization",
                  mutation_config={"token_source": {"fixture_key": "USER_B", "output": "token"}}),
            scope=ResolveScope.from_mapping({"USER_B": {"token": OTHER_TOKEN}}),
        )
        assert result.request.headers["Authorization"] == OTHER_TOKEN
        assert result.traces[0].note == "鉴权头取自 Fixture 输出"

    def test_authorization_mutation_without_source_removes_header(self) -> None:
        """验证授权变异不带`source``removes`请求头场景及其预期结果。"""
        result = _apply(_rule("AUTHORIZATION_MUTATION"))
        assert "Authorization" not in result.request.headers


# --------------------------------------------------------------------------- 参数算子


class TestParameterOperators:
    """§6.4 参数类算子：只执行规则点名的字段。"""

    def test_remove_field_on_required_body_field(self) -> None:
        """验证移除字段`on`必填请求体字段场景及其预期结果。"""
        spec = _spec()
        result = _apply(_body_rule("REMOVE_FIELD"), fields=_fields_for(_body_rule("REMOVE_FIELD"), spec))
        assert "priority" not in result.request.json_body
        assert result.traces[0].before == 3

    def test_remove_field_refuses_optional_field(self) -> None:
        """验证移除字段`refuses`可选字段场景及其预期结果。"""
        spec = _spec(required=False)
        _expect_error(
            RuleNotApplicableError, CODE_SECURITY_MUTATION_INVALID,
            lambda: _apply(_body_rule("REMOVE_FIELD"), fields=_fields_for(_body_rule("REMOVE_FIELD"), spec)),
        )

    def test_parameter_mutation_requires_named_field(self) -> None:
        """规则没有点名字段时不自动展开（展开发生在 Phase E 的 preview）。"""
        _expect_error(
            RuleNotApplicableError, CODE_SECURITY_MUTATION_INVALID,
            lambda: _apply(_body_rule("ZERO", target_field=None), fields=[_spec()]),
        )

    def test_parameter_mutation_requires_schema(self) -> None:
        """验证`parameter`变异需要结构定义场景及其预期结果。"""
        _expect_error(
            RuleNotApplicableError, CODE_SECURITY_MUTATION_INVALID,
            lambda: _apply(_body_rule("ZERO"), fields=[]),
        )

    def test_null_value(self) -> None:
        """验证`null`值场景及其预期结果。"""
        result = _apply(_body_rule("NULL_VALUE"), fields=_fields_for(_body_rule("NULL_VALUE"), _spec()))
        assert result.request.json_body["priority"] is None
        assert result.traces[0].after is None

    def test_empty_string(self) -> None:
        """验证空值`string`场景及其预期结果。"""
        spec = _spec(name="name", type="string", max_length=20)
        result = _apply(_body_rule("EMPTY_STRING", "name"), fields=_fields_for(_body_rule("EMPTY_STRING", "name"), spec))
        assert result.request.json_body["name"] == ""

    @pytest.mark.parametrize(
        "field_type,expected",
        [("integer", "abc"), ("number", "abc"), ("string", 1), ("boolean", "yes")],
    )
    def test_type_mutation(self, field_type: str, expected) -> None:
        """验证类型变异场景及其预期结果。"""
        spec = _spec(name="priority", type=field_type)
        result = _apply(_body_rule("TYPE_MUTATION"), fields=_fields_for(_body_rule("TYPE_MUTATION"), spec))
        assert result.request.json_body["priority"] == expected

    def test_zero_and_negative(self) -> None:
        """验证`zero`和`negative`场景及其预期结果。"""
        spec = _spec(name="priority", type="integer", minimum=0)
        rule = _body_rule("ZERO")
        assert _apply(rule, fields=_fields_for(rule, spec)).request.json_body["priority"] == 0
        rule = _body_rule("NEGATIVE")
        assert _apply(rule, fields=_fields_for(rule, spec)).request.json_body["priority"] == -1

    def test_negative_refuses_when_schema_allows_negative(self) -> None:
        """验证`negative``refuses`当结构定义`allows``negative`场景及其预期结果。"""
        spec = _spec(name="delta", type="integer", minimum=-10)
        rule = _body_rule("NEGATIVE", "delta")
        _expect_error(RuleNotApplicableError, CODE_SECURITY_MUTATION_INVALID,
                      lambda: _apply(rule, fields=_fields_for(rule, spec)))

    def test_over_max_writes_value_and_reports_capping(self) -> None:
        """验证`over``max``writes`值和`reports``capping`场景及其预期结果。"""
        spec = _spec(name="remark", type="string", max_length=100000)
        rule = _body_rule("OVER_MAX", "remark")
        result = _apply(rule, fields=_fields_for(rule, spec))
        assert len(result.request.json_body["remark"]) == MAX_MUTATION_STRING_LENGTH
        assert "封顶" in result.traces[0].note
        spec = _spec(name="priority", type="integer", maximum=10)
        rule = _body_rule("OVER_MAX")
        assert _apply(rule, fields=_fields_for(rule, spec)).request.json_body["priority"] == 11

    def test_under_min(self) -> None:
        """验证`under``min`场景及其预期结果。"""
        spec = _spec(name="priority", type="integer", minimum=5)
        rule = _body_rule("UNDER_MIN")
        assert _apply(rule, fields=_fields_for(rule, spec)).request.json_body["priority"] == 4

    def test_invalid_enum(self) -> None:
        """验证无效`enum`场景及其预期结果。"""
        spec = _spec(name="status", type="string", enum=["A", "B"])
        rule = _body_rule("INVALID_ENUM", "status")
        result = _apply(rule, fields=_fields_for(rule, spec))
        assert result.request.json_body["status"] == "UNKNOWN"
        assert result.request.json_body["status"] not in spec.enum

    def test_invalid_format(self) -> None:
        """验证无效格式化场景及其预期结果。"""
        spec = _spec(name="contact", type="string", format="email")
        rule = _body_rule("INVALID_FORMAT", "contact")
        result = _apply(rule, fields=_fields_for(rule, spec))
        assert result.request.json_body["contact"] == "not-an-email"

    def test_nested_body_field_by_json_path(self) -> None:
        """验证`nested`请求体字段按JSON路径场景及其预期结果。"""
        spec = _spec(name="priority", type="integer", json_path="$.filter.priority")
        rule = _body_rule("ZERO", "priority")
        rule.mutation_config = {"location": "BODY", "field": "filter.priority"}
        baseline = _baseline(json_body={"filter": {"priority": 5}})
        result = _apply(rule, baseline=baseline, fields=[spec])
        assert result.request.json_body == {"filter": {"priority": 0}}
        assert result.traces[0].field == "priority"

    @pytest.mark.parametrize("location", ["PATH", "QUERY", "HEADER", "COOKIE"])
    def test_parameter_operator_writes_each_location(self, location: str) -> None:
        """参数算子按位置落地：PATH 改 path_params，QUERY 改 query，等等。"""
        spec = _spec(name="limit", type="integer", maximum=10)
        if location == "HEADER":
            baseline = _baseline(headers={"Authorization": TOKEN, "limit": "5"})
        elif location == "COOKIE":
            baseline = _baseline(cookies={"limit": "5"})
        elif location == "PATH":
            baseline = _baseline(path_params={"limit": "5"}, path="/api/l{limit}")
        else:
            baseline = _baseline(query={"limit": "5"})
        rule = _body_rule("ZERO", "limit", target_location=location)
        result = _apply(rule, baseline=baseline, fields=_fields_for(rule, spec))

        if location == "PATH":
            assert result.request.path_params["limit"] == "0"
        elif location == "QUERY":
            assert result.request.query["limit"] == "0"
        elif location == "HEADER":
            assert result.request.headers["limit"] == "0"
        else:
            assert result.request.cookies["limit"] == "0"
        assert result.traces[0].location == location
        # 路径模板不被重写：替换发生在 path_params 上。
        if location == "PATH":
            assert result.request.path == "/api/l{limit}"

    def test_header_case_insensitive_lookup(self) -> None:
        """验证请求头用例`insensitive``lookup`场景及其预期结果。"""
        baseline = _baseline(headers={"authorization": TOKEN, "Content-Type": "application/json"})
        result = _apply(_rule("REMOVE_TOKEN"), baseline=baseline)
        assert "authorization" not in result.request.headers
        assert result.traces[0].field == "authorization"


# --------------------------------------------------------------------------- 请求头与方法算子


class TestHeaderAndMethodOperators:
    """§6.4 请求头与方法算子，含 Content-Type 必须走 raw_body 的风险项。"""

    def test_remove_header_defaults_to_content_type(self) -> None:
        """验证移除请求头`defaults`到内容类型场景及其预期结果。"""
        rule = _rule("REMOVE_HEADER", target_location="HEADER", target_field=None)
        result = _apply(rule)
        assert "Content-Type" not in result.request.headers
        assert result.traces[0].field == "Content-Type"

    def test_remove_header_records_json_content_type_limitation(self) -> None:
        """验证移除请求头记录JSON内容类型`limitation`场景及其预期结果。"""
        rule = _rule("REMOVE_HEADER", target_location="HEADER", target_field="Content-Type")
        result = _apply(rule)
        assert "Content-Type" not in result.request.headers
        assert "httpx" in result.traces[0].note

    def test_remove_header_missing_records_note(self) -> None:
        """验证移除请求头缺失记录`note`场景及其预期结果。"""
        baseline = _baseline(headers={"Authorization": TOKEN})
        rule = _rule("REMOVE_HEADER", target_location="HEADER", target_field="X-Trace")
        result = _apply(rule, baseline=baseline)
        assert result.changed is False
        assert result.traces[0].note == "基线无此头"

    def test_empty_header(self) -> None:
        """验证空值请求头场景及其预期结果。"""
        baseline = _baseline(headers={"Authorization": TOKEN, "X-Trace": "t-1"})
        rule = _rule("EMPTY_HEADER", target_location="HEADER", target_field="X-Trace")
        result = _apply(rule, baseline=baseline)
        assert result.request.headers["X-Trace"] == ""

    def test_invalid_header_value(self) -> None:
        """验证无效请求头值场景及其预期结果。"""
        baseline = _baseline(headers={"Authorization": TOKEN, "X-Request-Id": "r-1"})
        rule = _rule("INVALID_HEADER_VALUE", target_location="HEADER", target_field="X-Request-Id")
        result = _apply(rule, baseline=baseline)
        assert result.request.headers["X-Request-Id"] == "invalid"

    def test_invalid_header_value_refuses_auth_header(self) -> None:
        """验证无效请求头值`refuses`认证请求头场景及其预期结果。"""
        rule = _rule("INVALID_HEADER_VALUE", target_location="HEADER", target_field="Authorization")
        _expect_error(RuleNotApplicableError, CODE_SECURITY_MUTATION_INVALID, lambda: _apply(rule))

    def test_content_type_mutation_uses_raw_body(self) -> None:
        """Phase B 风险项：Content-Type 变异若仍走 json_body，httpx 会改回 application/json。"""
        rule = _rule("CONTENT_TYPE_MUTATION", target_location="HEADER",
                     expected_security_behavior="EXPECTED_VALIDATION_ERROR")
        result = _apply(rule)
        assert result.request.json_body is None
        assert result.request.raw_body == '{"name":"任务A","priority":3}'
        assert result.request.content_type == CONTENT_TYPE_TARGET
        assert result.request.headers["Content-Type"] == CONTENT_TYPE_TARGET
        assert "raw_body" in result.traces[0].note
        # 基线仍然是完整的 JSON body，没有被破坏。
        assert _baseline().json_body == {"name": "任务A", "priority": 3}

    def test_content_type_mutation_requires_json_body(self) -> None:
        """验证内容类型变异需要JSON请求体场景及其预期结果。"""
        baseline = _baseline(json_body=None, query={"id": "1"})
        rule = _rule("CONTENT_TYPE_MUTATION", target_location="HEADER")
        _expect_error(RuleNotApplicableError, CODE_SECURITY_MUTATION_INVALID,
                      lambda: _apply(rule, baseline=baseline))

    @pytest.mark.parametrize(
        "original,expected", [("POST", "GET"), ("post", "GET"), ("GET", "POST")]
    )
    def test_method_mutation_default_pair(self, original: str, expected: str) -> None:
        """验证方法变异默认`pair`场景及其预期结果。"""
        baseline = _baseline(method=original)
        rule = _rule("METHOD_MUTATION", target_location="METHOD", target_field=None,
                     expected_security_behavior="EXPECTED_DENY")
        result = _apply(rule, baseline=baseline)
        assert result.request.method == expected
        assert result.traces[0].before == original.upper()

    def test_method_mutation_uses_config_whitelist(self) -> None:
        """验证方法变异`uses`配置`whitelist`场景及其预期结果。"""
        baseline = _baseline(method="POST")
        rule = _rule("METHOD_MUTATION", target_location="METHOD", target_field=None,
                     mutation_config={"methods": ["PUT", "PATCH"]})
        result = _apply(rule, baseline=baseline)
        assert result.request.method == "PUT"

    def test_method_mutation_rejects_unknown_method(self) -> None:
        """验证方法变异拒绝未知方法场景及其预期结果。"""
        rule = _rule("METHOD_MUTATION", target_location="METHOD", target_field=None,
                     mutation_config={"methods": ["FETCH"]})
        err = _expect_error(AppError, CODE_SECURITY_MUTATION_INVALID, lambda: _apply(rule))
        assert "FETCH" in err.message

    def test_method_mutation_without_target_requires_whitelist(self) -> None:
        """验证方法变异不带目标需要`whitelist`场景及其预期结果。"""
        rule = _rule("METHOD_MUTATION", target_location="METHOD", target_field=None)
        _expect_error(RuleNotApplicableError, CODE_SECURITY_MUTATION_INVALID,
                      lambda: _apply(rule, baseline=_baseline(method="PUT")))

    def test_delete_requires_confirmation(self) -> None:
        """DELETE 未确认不进入执行：结果不会变成一条已发出的请求。"""
        rule = _rule("METHOD_MUTATION", target_location="METHOD", target_field=None,
                     mutation_config={"methods": ["DELETE"]})
        err = _expect_error(ConfirmationRequiredError, CODE_SECURITY_CONFIRMATION_REQUIRED,
                            lambda: _apply(rule, baseline=_baseline(method="POST")))
        assert "确认" in err.message
        baseline = _baseline(method="POST")
        _expect_error(ConfirmationRequiredError, CODE_SECURITY_CONFIRMATION_REQUIRED,
                      lambda: _apply(rule, baseline=baseline, confirmed=True))

    def test_delete_allowed_when_rule_and_case_are_confirmed(self) -> None:
        """验证删除`allowed`当规则和用例是否为`confirmed`场景及其预期结果。"""
        rule = _rule("METHOD_MUTATION", target_location="METHOD", target_field=None,
                     mutation_config={"methods": ["DELETE"]}, confirmation_required=True)
        result = _apply(rule, baseline=_baseline(method="POST"), confirmed=True)
        assert result.request.method == "DELETE"


# --------------------------------------------------------------------------- 引擎


class TestEngine:
    """§6.3 引擎流程：校验、定位、调算子、写 trace、返回副本。"""

    def test_unknown_mutation_type_is_rejected(self) -> None:
        """验证未知变异类型是否被拒绝场景及其预期结果。"""
        _expect_error(AppError, CODE_SECURITY_MUTATION_INVALID,
                      lambda: _apply(_rule("SCAN_FOR_SQLI")))

    def test_script_key_in_config_is_rejected(self) -> None:
        """验证`script`键`in`配置是否被拒绝场景及其预期结果。"""
        _expect_error(
            AppError, CODE_SECURITY_MUTATION_INVALID,
            lambda: _apply(_rule("INVALID_TOKEN", mutation_config={"script": "import os"})),
        )
        _expect_error(
            AppError, CODE_SECURITY_MUTATION_INVALID,
            lambda: _apply(_rule("INVALID_TOKEN", mutation_config={"payload_file": "/etc/passwd"})),
        )

    @pytest.mark.parametrize("category", ["INJECTION", "RATE_LIMIT", "UPLOAD", "SSRF"])
    def test_reserved_category_is_never_executed(self, category: str) -> None:
        """预留攻击类不执行、不携带攻击载荷。"""
        err = _expect_error(
            AppError, CODE_SECURITY_MUTATION_NOT_ALLOWED,
            lambda: _apply(_rule("INVALID_TOKEN", category=category),
                           baseline=_baseline(json_body={"q": "x' OR 1=1"})),
        )
        assert category in err.message

    @pytest.mark.parametrize("mutation_type", ["REPLAY_SAME_REQUEST", "DUPLICATE_SUBMIT",
                                               "BUSINESS_STATE", "SEQUENCE_BYPASS"])
    def test_unregistered_operator_is_not_allowed(self, mutation_type: str) -> None:
        """Phase D 的算子在本阶段尚未开放。"""
        assert get_operator(mutation_type) is None
        _expect_error(AppError, CODE_SECURITY_MUTATION_NOT_ALLOWED,
                      lambda: _apply(_rule(mutation_type)))

    def test_confirmation_gate_blocks_before_operator(self) -> None:
        """验证`confirmation``gate``blocks`之前运算符场景及其预期结果。"""
        _expect_error(
            ConfirmationRequiredError, CODE_SECURITY_CONFIRMATION_REQUIRED,
            lambda: _apply(_rule("REMOVE_TOKEN", confirmation_required=True)),
        )
        # 确认过的规则正常执行。
        result = _apply(_rule("REMOVE_TOKEN", confirmation_required=True), confirmed=True)
        assert "Authorization" not in result.request.headers

    def test_accepts_view_orm_row_and_dict(self) -> None:
        """三种入参形态都接受：MutationRuleView、ORM 行、dict；基线始终不被修改。"""
        baseline = _baseline()

        view = _rule("REMOVE_TOKEN")
        assert "Authorization" not in _apply(view, baseline=baseline).request.headers
        assert baseline.headers["Authorization"] == TOKEN

        row = SimpleNamespace(mutation_type="REMOVE_TOKEN", target_location="header",
                              target_field="Authorization", mutation_config={},
                              expected_security_behavior="EXPECTED_DENY", severity="MEDIUM",
                              confirmation_required=False)
        assert "Authorization" not in _apply(row, baseline=baseline).request.headers

        as_dict = {"mutation_type": "REMOVE_TOKEN", "target_location": "HEADER",
                   "target_field": "Authorization"}
        assert "Authorization" not in _apply(as_dict, baseline=baseline).request.headers
        assert SecurityMutationEngine.apply(_baseline(), as_dict).request.headers["Content-Type"] == "application/json"

    def test_rule_view_defaults_for_missing_columns(self) -> None:
        """验证规则`view``defaults`用于缺失`columns`场景及其预期结果。"""
        view = MutationRuleView.from_row({"mutation_type": "REMOVE_TOKEN", "target_location": "HEADER"})
        assert view.target_field is None
        assert view.expected_security_behavior == "EXPECTED_DENY"
        assert view.severity == "MEDIUM"
        assert view.mutation_config == {}

    def test_all_registered_types_are_in_the_contract_whitelist(self) -> None:
        """注册表里的每个算子都必须在契约白名单里（防止引擎跑未知类型）。"""
        for type_ in OPERATORS:
            assert type_ in MUTATION_TYPES

    def test_authorization_operators_are_registered(self) -> None:
        """Phase C 起授权 / IDOR 算子已开放。"""
        for type_ in ("CROSS_USER", "CROSS_PROJECT", "ROLE_DOWNGRADE",
                       "RESOURCE_OWNER_CHANGE", "IDOR"):
            assert get_operator(type_) is not None

    def test_notes_and_traces_are_separate_channels(self) -> None:
        """notes 记录「没法测」，traces 记录「改了什么」；两者可以同时出现。"""
        result = _apply(
            _rule("REMOVE_TOKEN"),
            baseline=_baseline(headers={"Content-Type": "application/json"}),
        )
        assert result.notes
        assert result.traces
        assert result.traces[0].to_dict()["before"] is None


# --------------------------------------------------------------------------- 授权 / IDOR

class TestCandidateResolver:
    """§10 数据约定：候选只来自 Fixture 输出契约，没有第二条数据来源。"""

    def test_parse_source_normalises_and_drops_incomplete(self) -> None:
        """验证解析`source``normalises`和`drops``incomplete`场景及其预期结果。"""
        assert parse_source({"fixture_key": " USER_B ", "output": "token"}) == {
            "fixture_key": "USER_B", "output": "token",
        }
        assert parse_source(None) is None
        assert parse_source("USER_B.token") is None
        assert parse_source({"fixture_key": "USER_B"}) is None
        assert parse_source({"fixture_key": "USER_B", "output": ""}) is None

    def test_read_sources_prefers_explicit_keys(self) -> None:
        """验证读取`sources``prefers``explicit``keys`场景及其预期结果。"""
        rule = _rule("CROSS_USER", mutation_config={
            "token_source": {"fixture_key": "USER_B", "output": "token"},
            "resource_source": {"fixture_key": "TASK_B", "output": "task_id"},
        })
        token, resource = read_sources(rule)
        assert token == {"fixture_key": "USER_B", "output": "token"}
        assert resource == {"fixture_key": "TASK_B", "output": "task_id"}

    def test_read_sources_splits_candidates_list(self) -> None:
        """candidates 写法：输出名像 Token 的进身份侧，其余进资源侧，顺序不敏感。"""
        rule = _rule("CROSS_USER", mutation_config={
            "candidates": [
                {"fixture_key": "TASK_B", "output": "task_id"},
                {"fixture_key": "USER_B", "output": "token"},
            ],
        })
        token, resource = read_sources(rule)
        assert token == {"fixture_key": "USER_B", "output": "token"}
        assert resource == {"fixture_key": "TASK_B", "output": "task_id"}

    def test_read_sources_ignores_malformed_candidates(self) -> None:
        """验证读取`sources``ignores``malformed``candidates`场景及其预期结果。"""
        rule = _rule("CROSS_USER", mutation_config={"candidates": [{"fixture_key": "USER_B"}, "junk"]})
        assert read_sources(rule) == (None, None)

    def test_resolve_value_accepts_numeric_id(self) -> None:
        """验证解析并确定值`accepts``numeric`标识场景及其预期结果。"""
        scope = ResolveScope.from_mapping({"TASK_B": {"task_id": 42}})
        assert resolve_value({"fixture_key": "TASK_B", "output": "task_id"}, scope,
                             label="IDOR 的资源候选") == 42

    def test_resolve_value_missing_output_raises_fixture_required(self) -> None:
        """验收：无候选则抛 SECURITY_FIXTURE_REQUIRED，不猜 ID。"""
        err = _expect_error(
            AppError, CODE_SECURITY_FIXTURE_REQUIRED,
            lambda: resolve_value({"fixture_key": "USER_B", "output": "token"}, ResolveScope(),
                                  label="CROSS_USER 的 Token 候选"),
        )
        assert "USER_B.token" in err.message

    def test_resolve_value_blank_string_counts_as_missing(self) -> None:
        """验证解析并确定值`blank``string``counts``as`缺失场景及其预期结果。"""
        scope = ResolveScope.from_mapping({"TASK_B": {"task_id": "   "}})
        _expect_error(AppError, CODE_SECURITY_FIXTURE_REQUIRED,
                      lambda: resolve_value({"fixture_key": "TASK_B", "output": "task_id"}, scope,
                                             label="IDOR 的资源候选"))

    def test_resolve_value_without_named_source_is_a_skip(self) -> None:
        """没点名候选属于配置缺陷（SECURITY_MUTATION_INVALID），不是数据缺口。"""
        _expect_error(RuleNotApplicableError, CODE_SECURITY_MUTATION_INVALID,
                      lambda: resolve_value(None, ResolveScope(), label="IDOR 的资源候选"))

    def test_resource_target_requires_location_and_field(self) -> None:
        """验证`resource`目标需要`location`和字段场景及其预期结果。"""
        rule = _rule("IDOR", mutation_config={"resource_source": {"fixture_key": "TASK_B", "output": "task_id"}})
        scope = ResolveScope.from_mapping({"TASK_B": {"task_id": 42}})
        _expect_error(RuleNotApplicableError, CODE_SECURITY_MUTATION_INVALID,
                      lambda: resource_target(rule, scope, label="IDOR 的资源候选"))

    def test_resource_target_rejects_header_location(self) -> None:
        """资源侧只允许 PATH / QUERY / BODY；鉴权头走 token 侧。"""
        rule = _rule("IDOR", mutation_config={"resource_source": {"fixture_key": "TASK_B", "output": "task_id"},
                                              "location": "HEADER", "field": "task_id"})
        scope = ResolveScope.from_mapping({"TASK_B": {"task_id": 42}})
        _expect_error(RuleNotApplicableError, CODE_SECURITY_MUTATION_INVALID,
                      lambda: resource_target(rule, scope, label="IDOR 的资源候选"))


class TestAuthorizationAndIdor:
    """Phase C 验收：USER_A 的请求换成 USER_B 的 token 与 TASK_B 的 id。"""

    #: 两个故意不同的整数：业务项目 301（PROJECT_A）与平台项目 7，用来锁住「写混」。
    SCOPE = ResolveScope.from_mapping({
        "USER_A": {"token": TOKEN},
        "USER_B": {"token": OTHER_TOKEN, "low_priv_token": "Bearer low-priv"},
        "TASK_A": {"task_id": 5},
        "TASK_B": {"task_id": 42},
        "USER_C": {"user_id": 99},
        "PROJECT_A": {"project_id": 301},
        "PROJECT_B": {"project_id": 990},
    })

    def _task_path(self, task_id: str = "5") -> BaselineRequest:
        """生成安全测试任务的请求路径。"""
        return _baseline(path="/api/projects/{project_id}/tasks/{task_id}",
                         path_params={"project_id": "7", "task_id": task_id})

    def test_cross_user_swaps_token_and_resource_id(self) -> None:
        """验证跨项目用户`swaps`令牌和`resource`标识场景及其预期结果。"""
        rule = _rule("CROSS_USER", mutation_config={
            "token_source": {"fixture_key": "USER_B", "output": "token"},
            "resource_source": {"fixture_key": "TASK_B", "output": "task_id"},
            "location": "PATH",
            "field": "task_id",
        })
        result = _apply(rule, baseline=self._task_path(), scope=self.SCOPE)
        assert result.request.headers["Authorization"] == OTHER_TOKEN
        assert result.request.path_params == {"project_id": "7", "task_id": "42"}
        assert result.changed is True

    def test_cross_user_trace_masks_token_keeps_resource_id(self) -> None:
        """验收：trace 里 token 是 ******，task_id 是明文数字。"""
        rule = _rule("CROSS_USER", mutation_config={
            "token_source": {"fixture_key": "USER_B", "output": "token"},
            "resource_source": {"fixture_key": "TASK_B", "output": "task_id"},
            "location": "PATH",
            "field": "task_id",
        })
        dumped = _apply(rule, baseline=self._task_path(), scope=self.SCOPE).to_dicts()
        token = next(e for e in dumped if e["field"] == "Authorization")
        resource = next(e for e in dumped if e["field"] == "task_id")
        assert token["before"] == MASKED
        assert token["after"] == MASKED
        assert resource["before"] == "5"
        assert resource["after"] == 42          # 明文数字：资源 ID 不是敏感键
        assert resource["location"] == "PATH"

    def test_cross_user_missing_candidate_raises_fixture_required(self) -> None:
        """验收：无候选则抛 SECURITY_FIXTURE_REQUIRED。"""
        rule = _rule("CROSS_USER", mutation_config={"token_source": {"fixture_key": "USER_B", "output": "token"}})
        err = _expect_error(AppError, CODE_SECURITY_FIXTURE_REQUIRED,
                            lambda: _apply(rule, scope=ResolveScope()))
        assert "USER_B.token" in err.message

    def test_cross_user_without_named_source_is_skipped(self) -> None:
        """验证跨项目用户不带`named``source`是否跳过场景及其预期结果。"""
        _expect_error(RuleNotApplicableError, CODE_SECURITY_MUTATION_INVALID,
                      lambda: _apply(_rule("CROSS_USER"), scope=self.SCOPE))

    def test_idor_in_path(self) -> None:
        """验证`idor``in`路径场景及其预期结果。"""
        rule = _rule("IDOR", mutation_config={"resource_source": {"fixture_key": "TASK_B", "output": "task_id"},
                                              "location": "PATH", "field": "task_id"})
        result = _apply(rule, baseline=self._task_path(), scope=self.SCOPE)
        assert result.request.path_params == {"project_id": "7", "task_id": "42"}
        assert result.traces[0].after == 42
        # 路径模板不被重写：替换发生在 path_params 上。
        assert result.request.path == "/api/projects/{project_id}/tasks/{task_id}"

    def test_idor_in_body_supports_nested_field(self) -> None:
        """验证`idor``in`请求体`supports``nested`字段场景及其预期结果。"""
        rule = _rule("IDOR", mutation_config={"resource_source": {"fixture_key": "USER_C", "output": "user_id"},
                                              "location": "BODY", "field": "filter.owner_id"})
        result = _apply(rule, baseline=_baseline(json_body={"filter": {"owner_id": 5}}), scope=self.SCOPE)
        assert result.request.json_body == {"filter": {"owner_id": 99}}
        assert result.traces[0].before == 5

    def test_idor_in_query(self) -> None:
        """验证`idor``in`查询参数场景及其预期结果。"""
        rule = _rule("IDOR", mutation_config={"resource_source": {"fixture_key": "TASK_B", "output": "task_id"},
                                              "location": "QUERY", "field": "task_id"})
        result = _apply(rule, baseline=_baseline(), scope=self.SCOPE)
        assert result.request.query == {"page": "1", "task_id": "42"}

    def test_idor_refuses_path_without_placeholder(self) -> None:
        """路径里没有占位符时替换不会改变实际 URL，跳过而不是写一条会骗人的 trace。"""
        rule = _rule("IDOR", mutation_config={"resource_source": {"fixture_key": "TASK_B", "output": "task_id"},
                                              "location": "PATH", "field": "task_id"})
        _expect_error(RuleNotApplicableError, CODE_SECURITY_MUTATION_INVALID,
                      lambda: _apply(rule, baseline=_baseline(), scope=self.SCOPE))

    def test_cross_project_swaps_business_project_id_only(self) -> None:
        """风险项：业务 project_id 与平台 project_id 是两个故意不同的整数，绝不互相兜底。"""
        rule = _rule("CROSS_PROJECT", mutation_config={
            "resource_source": {"fixture_key": "PROJECT_B", "output": "project_id"},
            "location": "PATH",
            "field": "project_id",
        })
        baseline = self._task_path()
        baseline.path_params = {"project_id": "301", "task_id": "5"}  # 被测系统的业务项目
        baseline.project_id = 7                                        # 平台自己的项目 ID
        result = _apply(rule, baseline=baseline, scope=self.SCOPE)
        assert result.request.path_params["project_id"] == "990"
        assert result.request.project_id == 7
        assert result.traces[0].before == "301"
        assert result.traces[0].after == 990

    def test_cross_project_never_falls_back_to_platform_id(self) -> None:
        """缺候选时报错，而不是拿平台 project_id 顶上去。"""
        rule = _rule("CROSS_PROJECT", mutation_config={
            "resource_source": {"fixture_key": "PROJECT_B", "output": "project_id"},
            "location": "PATH",
            "field": "project_id",
        })
        _expect_error(AppError, CODE_SECURITY_FIXTURE_REQUIRED,
                      lambda: _apply(rule, baseline=self._task_path(), scope=ResolveScope()))

    def test_role_downgrade_uses_low_privilege_token_from_fixture(self) -> None:
        """验证角色`downgrade``uses`低风险`privilege`令牌从固定数据场景及其预期结果。"""
        rule = _rule("ROLE_DOWNGRADE", mutation_config={
            "token_source": {"fixture_key": "USER_B", "output": "low_priv_token"},
        })
        result = _apply(rule, scope=self.SCOPE)
        assert result.request.headers["Authorization"] == "Bearer low-priv"
        assert result.traces[0].note == "低权限 Token 取自 Fixture 输出"

    def test_role_downgrade_without_named_token_is_skipped(self) -> None:
        """没点名 token_source 属于配置缺陷：跳过而不是拿任何 Token 去测。"""
        _expect_error(RuleNotApplicableError, CODE_SECURITY_MUTATION_INVALID,
                      lambda: _apply(_rule("ROLE_DOWNGRADE"), scope=self.SCOPE))

    def test_role_downgrade_skips_when_fixture_has_no_low_priv_token(self) -> None:
        """低权限 Token 只能来自 Fixture：没有就跳过，不去平台用户表里改角色。"""
        rule = _rule("ROLE_DOWNGRADE", mutation_config={
            "token_source": {"fixture_key": "USER_B", "output": "low_priv_token"},
        })
        scope = ResolveScope.from_mapping({"USER_B": {"token": OTHER_TOKEN}})
        err = _expect_error(AppError, CODE_SECURITY_FIXTURE_REQUIRED, lambda: _apply(rule, scope=scope))
        assert "USER_B.low_priv_token" in err.message

    def test_resource_owner_change_replaces_body_owner(self) -> None:
        """验证`resource``owner``change``replaces`请求体`owner`场景及其预期结果。"""
        rule = _rule("RESOURCE_OWNER_CHANGE", mutation_config={
            "resource_source": {"fixture_key": "USER_C", "output": "user_id"},
            "location": "BODY",
            "field": "owner_id",
        })
        result = _apply(rule, scope=self.SCOPE)
        assert result.request.json_body["owner_id"] == 99
        assert result.request.json_body["priority"] == 3
        assert result.traces[0].before is None

    def test_authorization_operator_severities_are_still_resolved(self) -> None:
        """§8 规则表：IDOR 命中候选是 CRITICAL，跨项目是 HIGH，认证类是 HIGH。"""
        assert resolve_severity(SeverityContext(mutation_type="IDOR", status_codes=[200],
                                                auth_type="bearer",
                                                response_body={"data": {"task_id": 42}},
                                                candidate_resource_id=42)) == "CRITICAL"
        assert resolve_severity(SeverityContext(mutation_type="CROSS_PROJECT", status_codes=[200],
                                                auth_type="bearer")) == "HIGH"
        assert resolve_severity(SeverityContext(mutation_type="CROSS_USER", status_codes=[200],
                                                auth_type="bearer")) == "HIGH"
        # 403 不在 2xx 里，规则表查不到，退回规则默认级别。
        assert resolve_severity(SeverityContext(mutation_type="ROLE_DOWNGRADE", status_codes=[403],
                                                auth_type="bearer")) == DEFAULT_FINDING_SEVERITY


# --------------------------------------------------------------------------- Trace 脱敏


class TestTraceMasking:
    """§5.2 每次变异必须留下说明；Token / 口令 / Cookie 落库前脱敏。"""

    @pytest.mark.parametrize("key", ["Authorization", "authorization", "token", "access_token",
                                     "Cookie", "password", "api_key", "X-Api-Key", "x-auth-token",
                                     "signature", "session_id"])
    def test_sensitive_keys_are_masked(self, key: str) -> None:
        """验证`sensitive``keys`是否为`masked`场景及其预期结果。"""
        assert mask_value(key, "secret-value") == MASKED

    @pytest.mark.parametrize("key,value", [
        ("task_id", 123), ("project_id", "7"), ("id", "abc-1"), ("priority", 3),
        ("page", "1"), ("X-Request-Id", "r-1"),
    ])
    def test_non_sensitive_values_stay_plaintext(self, key: str, value) -> None:
        """资源 ID 不是敏感键：trace 里必须保持明文，否则没法定位问题。"""
        assert mask_value(key, value) == value

    def test_mask_value_handles_containers_and_none(self) -> None:
        """验证脱敏值`handles``containers`和`none`场景及其预期结果。"""
        assert mask_value("body", {"token": "***", "task_id": 1}) == {"token": MASKED, "task_id": 1}
        assert mask_value("items", [{"access_token": "***"}]) == [{"access_token": MASKED}]
        assert mask_value("task_id", None) is None
        assert mask_value(None, "plain") == "plain"

    def test_trace_entry_to_dict_masks_before_and_after(self) -> None:
        """验证`trace``entry`到字典`masks`之前和之后场景及其预期结果。"""
        entry = MutationTraceEntry("EMPTY_TOKEN", "HEADER", "Authorization", TOKEN, "Bearer ")
        dumped = entry.to_dict()
        assert dumped["before"] == MASKED
        assert dumped["after"] == MASKED
        assert dumped["location"] == "HEADER"

    def test_trace_entry_note_is_carried(self) -> None:
        """验证`trace``entry``note`是否`carried`场景及其预期结果。"""
        entry = MutationTraceEntry("REMOVE_TOKEN", "HEADER", "Authorization", TOKEN, None, note="基线无此头")
        assert entry.to_dict()["note"] == "基线无此头"

    def test_entries_to_dicts_is_the_persist_shape(self) -> None:
        """验证`entries`到`dicts`是否`the`持久化`shape`场景及其预期结果。"""
        entries = [MutationTraceEntry("REMOVE_TOKEN", "HEADER", "Authorization", TOKEN, None)]
        dumped = entries_to_dicts(entries)
        assert dumped == [{
            "mutation_type": "REMOVE_TOKEN",
            "location": "HEADER",
            "field": "Authorization",
            "before": MASKED,
            "after": None,
        }]

    def test_request_snapshot_masks_every_channel(self) -> None:
        """验证请求`snapshot``masks``every`渠道场景及其预期结果。"""
        baseline = _baseline(query={"page": "1", "token": "***"}, cookies={"session_id": "s1"})
        snapshot = request_snapshot(baseline)
        assert snapshot["headers"]["Authorization"] == MASKED
        assert snapshot["query"]["token"] == MASKED
        assert snapshot["query"]["page"] == "1"
        assert snapshot["cookies"]["session_id"] == MASKED
        assert snapshot["body_type"] == "json"
        assert snapshot["method"] == "POST"
        assert snapshot["path"] == "/api/projects/{project_id}/tasks"

    def test_request_diff_records_each_changed_field(self) -> None:
        """验证请求`diff`记录`each``changed`字段场景及其预期结果。"""
        before = _baseline(query={"page": "1", "size": "10"})
        after = before.copy()
        after.query["page"] = "2"
        after.headers["X-Trace"] = "new"
        after.json_body = {**before.json_body, "priority": 0}
        entries = request_diff(before, after, "ZERO")
        fields = {(e.location, e.field) for e in entries}
        assert ("QUERY", "page") in fields
        assert ("HEADER", "X-Trace") in fields
        assert ("BODY", "$.priority") in fields
        assert all(e.mutation_type == "ZERO" for e in entries)

    def test_request_diff_masks_sensitive_keys(self) -> None:
        """验证请求`diff``masks``sensitive``keys`场景及其预期结果。"""
        before = _baseline()
        after = before.copy()
        after.headers["Authorization"] = "Bearer changed"
        entries = request_diff(before, after, "INVALID_TOKEN")
        dumped = entries_to_dicts(entries)
        assert all("Bearer" not in str(d["before"]) and "Bearer" not in str(d["after"]) for d in dumped)


# --------------------------------------------------------------------------- 断言


class TestAssertion:
    """§8 安全期望判定：五态结论，不用 VULNERABLE。"""

    @pytest.mark.parametrize("code", [401, 403, 404])
    def test_deny_expected_codes_pass(self, code: int) -> None:
        """验证`deny``expected``codes`通过场景及其预期结果。"""
        result = assert_expectation("EXPECTED_DENY", code, rule_name="去掉 Token", mutation_type="REMOVE_TOKEN")
        assert result.security_result == "PASS"
        assert result.classification == "EXPECTED_DENY_MET"
        assert "去掉 Token" in result.message

    def test_deny_2xx_is_potential_issue(self) -> None:
        """验证`deny``xx`是否`potential``issue`场景及其预期结果。"""
        result = assert_expectation("EXPECTED_DENY", 200, rule_name="去掉 Token", mutation_type="REMOVE_TOKEN")
        assert result.security_result == "POTENTIAL_ISSUE"
        assert result.classification == "POTENTIAL_ISSUE"
        assert "401" in result.message and "403" in result.message

    def test_deny_5xx_is_unexpected_server_error(self) -> None:
        """验证`deny``xx`是否`unexpected`服务端错误场景及其预期结果。"""
        result = assert_expectation("EXPECTED_DENY", 500, rule_name="去掉 Token")
        assert result.security_result == "POTENTIAL_ISSUE"
        assert result.classification == "UNEXPECTED_SERVER_ERROR"

    def test_deny_redirect_is_inconclusive(self) -> None:
        """验证`deny``redirect`是否`inconclusive`场景及其预期结果。"""
        result = assert_expectation("EXPECTED_DENY", 302, rule_name="去掉 Token")
        assert result.security_result == "INCONCLUSIVE"
        assert "重定向" in result.message

    def test_deny_unexpected_4xx_is_inconclusive(self) -> None:
        """验证`deny``unexpected``xx`是否`inconclusive`场景及其预期结果。"""
        result = assert_expectation("EXPECTED_DENY", 400, rule_name="去掉 Token")
        assert result.security_result == "INCONCLUSIVE"

    def test_deny_without_baseline_auth_is_inconclusive(self) -> None:
        """验证`deny`不带基线认证是否`inconclusive`场景及其预期结果。"""
        result = assert_expectation("EXPECTED_DENY", 200, rule_name="去掉 Token",
                                    baseline_auth_present=False)
        assert result.security_result == "INCONCLUSIVE"
        assert "基线" in result.message

    def test_deny_respects_rule_status_codes(self) -> None:
        """验证`deny``respects`规则状态`codes`场景及其预期结果。"""
        result = assert_expectation("EXPECTED_DENY", 400, rule_name="错误方案",
                                    expected_status_codes=[401, 400, 403])
        assert result.security_result == "PASS"

    def test_no_status_code_is_inconclusive(self) -> None:
        """验证无状态代码是否`inconclusive`场景及其预期结果。"""
        assert assert_expectation("EXPECTED_DENY", [], rule_name="去掉 Token").security_result == "INCONCLUSIVE"
        assert assert_expectation("EXPECTED_DENY", 0, rule_name="去掉 Token").security_result == "INCONCLUSIVE"

    @pytest.mark.parametrize("code", [400, 422])
    def test_validation_expected_codes_pass(self, code: int) -> None:
        """验证校验`expected``codes`通过场景及其预期结果。"""
        result = assert_expectation("EXPECTED_VALIDATION_ERROR", code, rule_name="空字符串",
                                    mutation_type="EMPTY_STRING")
        assert result.security_result == "PASS"
        assert result.classification == "EXPECTED_VALIDATION_MET"

    def test_validation_5xx_is_unexpected_server_error(self) -> None:
        """验证校验`xx`是否`unexpected`服务端错误场景及其预期结果。"""
        result = assert_expectation("EXPECTED_VALIDATION_ERROR", 500, rule_name="空字符串")
        assert (result.security_result, result.classification) == ("POTENTIAL_ISSUE", "UNEXPECTED_SERVER_ERROR")

    def test_validation_2xx_without_echo_is_inconclusive(self) -> None:
        """验证校验`xx`不带`echo`是否`inconclusive`场景及其预期结果。"""
        trace = [MutationTraceEntry("EMPTY_STRING", "BODY", "name", "任务A", "")]
        result = assert_expectation("EXPECTED_VALIDATION_ERROR", 200, rule_name="空字符串",
                                    response_body={"id": 5, "priority": 3}, trace=trace)
        assert result.security_result == "INCONCLUSIVE"

    def test_validation_2xx_with_echoed_invalid_value_is_issue(self) -> None:
        """2xx 且响应回显了非法值才算真的接受了非法输入。"""
        trace = [MutationTraceEntry("EMPTY_STRING", "BODY", "name", "任务A", "")]
        result = assert_expectation("EXPECTED_VALIDATION_ERROR", 200, rule_name="空字符串",
                                    response_body={"data": {"id": 5, "name": ""}}, trace=trace)
        assert result.security_result == "POTENTIAL_ISSUE"

    def test_validation_2xx_echo_in_list_body(self) -> None:
        """验证校验`xx``echo``in`列出请求体场景及其预期结果。"""
        trace = [MutationTraceEntry("INVALID_ENUM", "BODY", "status", "A", "UNKNOWN")]
        result = assert_expectation("EXPECTED_VALIDATION_ERROR", 200, rule_name="非法枚举",
                                    response_body=[{"status": "UNKNOWN"}], trace=trace)
        assert result.security_result == "POTENTIAL_ISSUE"

    @pytest.mark.parametrize("codes,expected", [
        ([200, 409], "PASS"), ([200, 400], "PASS"), ([200, 500], "POTENTIAL_ISSUE"),
        ([200, 200], "POTENTIAL_ISSUE"),
    ])
    def test_idempotent_second_response(self, codes: list[int], expected: str) -> None:
        """验证幂等`second`响应场景及其预期结果。"""
        result = assert_expectation(
            "EXPECTED_IDEMPOTENT", codes, rule_name="重放", mutation_type="REPLAY_SAME_REQUEST",
            response_bodies=[{"id": 1}, {"id": 2}],
        )
        assert result.security_result == expected

    def test_idempotent_same_business_id_passes(self) -> None:
        """验证幂等相同业务标识`passes`场景及其预期结果。"""
        result = assert_expectation("EXPECTED_IDEMPOTENT", [200, 200], rule_name="重放",
                                    response_bodies=[{"id": 1}, {"id": 1}])
        assert result.security_result == "PASS"
        assert result.classification == "EXPECTED_IDEMPOTENT_MET"

    def test_idempotent_missing_id_is_inconclusive(self) -> None:
        """验证幂等缺失标识是否`inconclusive`场景及其预期结果。"""
        result = assert_expectation("EXPECTED_IDEMPOTENT", [200, 200], rule_name="重放",
                                    response_bodies=[{"message": "ok"}, {"message": "ok"}])
        assert result.security_result == "INCONCLUSIVE"
        assert "业务 ID" in result.message

    def test_idempotent_single_execution_is_inconclusive(self) -> None:
        """验证幂等`single`执行记录是否`inconclusive`场景及其预期结果。"""
        assert assert_expectation("EXPECTED_IDEMPOTENT", [200], rule_name="重放").security_result == "INCONCLUSIVE"

    def test_idempotent_accepts_integer_status_code(self) -> None:
        """单条变异传一个整数也能判定（不强制调用方包成列表）。"""
        assert assert_expectation("EXPECTED_DENY", 403, rule_name="去掉 Token").security_result == "PASS"

    def test_allow_expectation(self) -> None:
        """验证`allow``expectation`场景及其预期结果。"""
        assert assert_expectation("EXPECTED_ALLOW", 200, rule_name="允许公开访问").security_result == "PASS"
        assert assert_expectation("EXPECTED_ALLOW", 403, rule_name="允许公开访问").security_result == "INCONCLUSIVE"

    def test_unknown_expectation_is_rejected(self) -> None:
        """验证未知`expectation`是否被拒绝场景及其预期结果。"""
        _expect_error(AppError, CODE_SECURITY_EXPECTATION_INVALID,
                      lambda: assert_expectation("VOLNERABLE", 200, rule_name="去掉 Token"))

    def test_result_values_are_the_five_states_only(self) -> None:
        """§20.1 的负向断言：永远不返回 VULNERABLE。"""
        cases = [
            ("EXPECTED_DENY", 200), ("EXPECTED_DENY", 401), ("EXPECTED_DENY", 500),
            ("EXPECTED_VALIDATION_ERROR", 422), ("EXPECTED_IDEMPOTENT", [200, 200]),
            ("EXPECTED_ALLOW", 200),
        ]
        for expected, codes in cases:
            result = assert_expectation(expected, codes, rule_name="规则", mutation_type="REMOVE_TOKEN")
            assert result.security_result in SECURITY_RESULTS
            assert result.security_result.upper() != "VULNERABLE"


# --------------------------------------------------------------------------- 严重级别


class TestSeverity:
    """§8 严重级别规则表：级别只由表算出。"""

    def _ctx(self, **overrides) -> SeverityContext:
        """构造安全变异执行上下文。"""
        base = dict(mutation_type="REMOVE_TOKEN", status_codes=[200], auth_type="bearer")
        base.update(overrides)
        return SeverityContext(**base)

    def test_auth_without_token_is_high(self) -> None:
        """验证认证不带令牌是否高风险场景及其预期结果。"""
        assert resolve_severity(self._ctx()) == "HIGH"

    def test_auth_on_unauthenticated_endpoint_builds_no_finding(self) -> None:
        """接口声明无需认证时，去掉 Token 仍 2xx 不建 Finding。"""
        assert resolve_severity(self._ctx(auth_type="none")) is None

    def test_idor_with_candidate_in_response_is_critical(self) -> None:
        """验证`idor`包含`candidate``in`响应是否严重场景及其预期结果。"""
        ctx = self._ctx(mutation_type="IDOR", response_body={"data": {"task_id": 99}},
                        candidate_resource_id=99)
        assert resolve_severity(ctx) == "CRITICAL"

    def test_idor_without_candidate_in_response_is_high(self) -> None:
        """验证`idor`不带`candidate``in`响应是否高风险场景及其预期结果。"""
        ctx = self._ctx(mutation_type="IDOR", response_body={"data": {"task_id": 5}},
                        candidate_resource_id=99)
        assert resolve_severity(ctx) == "HIGH"

    def test_cross_user_critical_when_candidate_leaks(self) -> None:
        """验证跨项目用户严重当`candidate``leaks`场景及其预期结果。"""
        ctx = self._ctx(mutation_type="CROSS_USER", response_body=[{"id": 99}],
                        candidate_resource_id=99)
        assert resolve_severity(ctx) == "CRITICAL"

    def test_cross_project_is_high(self) -> None:
        """验证跨项目项目是否高风险场景及其预期结果。"""
        assert resolve_severity(self._ctx(mutation_type="CROSS_PROJECT")) == "HIGH"

    def test_server_error_is_medium(self) -> None:
        """验证服务端错误是否中风险场景及其预期结果。"""
        ctx = self._ctx(mutation_type="EMPTY_STRING", status_codes=[500],
                        classification="UNEXPECTED_SERVER_ERROR")
        assert resolve_severity(ctx) == "MEDIUM"

    def test_server_error_honours_lower_rule_default(self) -> None:
        """§8：500 停在 MEDIUM，除非规则另有更低默认值。"""
        ctx = self._ctx(mutation_type="EMPTY_STRING", status_codes=[500],
                        classification="UNEXPECTED_SERVER_ERROR", rule_severity="LOW")
        assert resolve_severity(ctx) == "LOW"

    def test_critical_is_not_lowered_by_rule_default(self) -> None:
        """验证严重是否不`lowered`按规则默认场景及其预期结果。"""
        ctx = self._ctx(mutation_type="IDOR", response_body={"task_id": 1}, candidate_resource_id=1,
                        rule_severity="LOW")
        assert resolve_severity(ctx) == "CRITICAL"

    def test_method_mutation_levels(self) -> None:
        """验证方法变异`levels`场景及其预期结果。"""
        assert resolve_severity(self._ctx(mutation_type="METHOD_MUTATION", method="POST")) == "MEDIUM"
        assert resolve_severity(self._ctx(mutation_type="METHOD_MUTATION", method="DELETE")) == "HIGH"

    def test_idempotent_new_result_is_high(self) -> None:
        """验证幂等`new`结果是否高风险场景及其预期结果。"""
        assert resolve_severity(self._ctx(mutation_type="REPLAY_SAME_REQUEST")) == "HIGH"
        assert resolve_severity(self._ctx(mutation_type="DUPLICATE_SUBMIT")) == "HIGH"

    def test_business_state_levels_by_method(self) -> None:
        """验证业务状态`levels`按方法场景及其预期结果。"""
        assert resolve_severity(self._ctx(mutation_type="BUSINESS_STATE", method="POST")) == "HIGH"
        assert resolve_severity(self._ctx(mutation_type="BUSINESS_STATE", method="GET")) == "LOW"

    def test_uncovered_case_falls_back_to_rule_severity(self) -> None:
        """验证`uncovered`用例`falls``back`到规则严重级别场景及其预期结果。"""
        assert resolve_severity(self._ctx(mutation_type="INVALID_FORMAT", rule_severity="LOW")) == "LOW"
        assert resolve_severity(self._ctx(mutation_type="INVALID_FORMAT")) == DEFAULT_FINDING_SEVERITY
        assert resolve_severity(self._ctx(mutation_type="INVALID_FORMAT",
                                          rule_severity="BOGUS")) == DEFAULT_FINDING_SEVERITY

    def test_non_2xx_without_classification_uses_rule_default(self) -> None:
        """非 2xx 且无分类时表里查不到，退回规则默认值而不是 None。"""
        assert resolve_severity(self._ctx(status_codes=[404])) == DEFAULT_FINDING_SEVERITY
        assert resolve_severity(self._ctx(status_codes=[404], rule_severity="LOW")) == "LOW"
