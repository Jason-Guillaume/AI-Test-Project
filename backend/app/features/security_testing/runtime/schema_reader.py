"""Schema Reader：把接口定义读成 ``FieldSpec``，并算出参数变异的取值。

读取顺序（开发计划 §6.5）：

1. ``api_parameter`` 行：PATH/QUERY/HEADER/COOKIE，以及 body_type 为 form/multipart
   时的 BODY 行。``schema_json`` 里的 enum / minimum / maximum / maxLength /
   minLength / format 覆盖列上的 ``type``。
2. ``api_request_body.schema_json``：只展开 object 的第一层 ``properties``，加上
   schema 显式写出的 ``required``。不递归整棵树；第二层只在规则点名
   ``$.parent.child`` 时由 ``resolve_nested_spec`` 读取。
3. 没有 schema 就不生成参数变异（返回空列表，引擎对未点名字段抛
   ``RuleNotApplicableError``）。认证和重放不依赖字段类型，不受影响。
"""

from __future__ import annotations

from typing import Any, Sequence

from app.shared.errors import CODE_SECURITY_MUTATION_INVALID

from app.features.security_testing.runtime.types import FieldSpec, RuleNotApplicableError
from app.features.security_testing.schemas import MAX_MUTATION_STRING_LENGTH

__all__ = [
    "read_fields",
    "field_spec_from_parameter",
    "body_fields",
    "resolve_nested_spec",
    "find_field",
    "integer_variants",
    "over_max_value",
    "under_min_value",
    "over_max_capped",
    "invalid_enum_value",
    "invalid_format_value",
    "type_mutation_value",
    "value_for",
    "INVALID_FORMAT_SAMPLES",
]


#: format 对应的固定非法样例（不是随机生成的畸形串）。
INVALID_FORMAT_SAMPLES: dict[str, str] = {
    "email": "not-an-email",
    "date": "9999-99-99",
    "uuid": "not-uuid",
    "uri": "not a uri",
}


def _schema_of(row: Any) -> dict[str, Any]:
    """取一行上的 schema_json，非 dict 一律视为无 schema。"""
    raw = getattr(row, "schema_json", None) if not isinstance(row, dict) else row.get("schema_json")
    return dict(raw) if isinstance(raw, dict) else {}


def _type_string(value: Any) -> str:
    """JSON Schema 的 type 可以是字符串或联合数组（``["integer", "null"]``）。"""
    if isinstance(value, list):
        return "|".join(str(v) for v in value if v)
    return str(value or "").strip()


def _spec_from_schema(name: str, location: str, schema: dict[str, Any], required: bool) -> FieldSpec:
    """把一段字段 schema 归一成 FieldSpec。"""
    nullable = bool(schema.get("nullable"))
    type_ = _type_string(schema.get("type")) or "string"
    if nullable and "null" not in type_.lower():
        type_ = f"{type_}|null"

    def _int_or_none(value: Any) -> int | None:
        if isinstance(value, bool):
            return None
        if isinstance(value, int):
            return value
        if isinstance(value, float):
            return int(value)
        return None

    def _float_or_none(value: Any) -> float | None:
        if isinstance(value, (int, float)) and not isinstance(value, bool):
            return float(value)
        return None

    return FieldSpec(
        location=location,
        name=str(name),
        json_path=f"$.{name}" if location == "BODY" else None,
        type=type_,
        required=bool(required),
        enum=list(schema.get("enum")) if isinstance(schema.get("enum"), list) else None,
        minimum=_float_or_none(schema.get("minimum")),
        maximum=_float_or_none(schema.get("maximum")),
        min_length=_int_or_none(schema.get("minLength")),
        max_length=_int_or_none(schema.get("maxLength")),
        format=(str(schema["format"]).lower() if schema.get("format") else None),
        example=schema.get("example"),
    )


def field_spec_from_parameter(param: Any) -> FieldSpec:
    """一行 ``api_parameter`` → FieldSpec（schema 覆盖列上的 type）。"""
    schema = _schema_of(param)
    location = str(getattr(param, "location", "") or "").upper()
    name = str(getattr(param, "name", "") or "")
    if not name:
        raise ValueError("api_parameter 行缺少 name")
    if schema:
        return _spec_from_schema(name, location, schema, bool(getattr(param, "required", False)))
    return FieldSpec(
        location=location,
        name=name,
        json_path=f"$.{name}" if location == "BODY" else None,
        type=str(getattr(param, "type", "string") or "string"),
        required=bool(getattr(param, "required", False)),
        example=getattr(param, "example", None),
    )


def _field_tree(schema: Any) -> list[dict[str, Any]]:
    """兼容字段树形态：``{"fields": [...]}`` 或裸 list。"""
    if isinstance(schema, dict):
        raw = schema.get("fields")
    else:
        raw = schema
    if not isinstance(raw, list):
        return []
    return [item for item in raw if isinstance(item, dict) and str(item.get("name") or "")]


def body_fields(body: Any | None) -> list[FieldSpec]:
    """展开 body schema 的第一层字段。

    JSON body 读 ``properties`` + ``required``；form / multipart 读字段树
    （``api_parameter`` 的 BODY 行已经覆盖过同一批字段，去重靠上层合并）。
    """
    if body is None:
        return []
    schema = _schema_of(body)
    body_type = str(getattr(body, "body_type", "") or "").lower()

    if body_type == "json" or "properties" in schema:
        properties = schema.get("properties")
        if not isinstance(properties, dict):
            return []
        required_names = {str(n) for n in schema.get("required") or []}
        result: list[FieldSpec] = []
        for name, subschema in properties.items():
            if not isinstance(subschema, dict):
                continue
            result.append(_spec_from_schema(str(name), "BODY", subschema, str(name) in required_names))
        return result

    tree = _field_tree(schema)
    if not tree:
        return []
    return [_spec_from_schema(str(item["name"]), "BODY", item, bool(item.get("required"))) for item in tree]


def resolve_nested_spec(body: Any | None, json_path: str) -> FieldSpec | None:
    """按 ``$.parent.child`` 读取第二层字段；路径不存在返回 None。"""
    if body is None or not json_path:
        return None
    schema = _schema_of(body)
    if "properties" not in schema:
        return None
    parts = json_path.lstrip("$").strip(".").split(".")
    node = schema
    for part in parts[:-1]:
        properties = node.get("properties") if isinstance(node, dict) else None
        if not isinstance(properties, dict) or part not in properties:
            return None
        node = properties[part]
    if not isinstance(node, dict):
        return None
    last = parts[-1]
    properties = node.get("properties")
    if not isinstance(properties, dict) or last not in properties:
        return None
    subschema = properties[last]
    if not isinstance(subschema, dict):
        return None
    # 第二层字段没有独立的 required 声明（required 只写在 parent schema 上），
    # 规则点名到这里时一律按非必填处理，避免把「可选深层字段」误判成校验缺失。
    spec = _spec_from_schema(last, "BODY", subschema, False)
    spec.json_path = json_path
    return spec


def read_fields(parameters: Sequence[Any] | None, body: Any | None) -> list[FieldSpec]:
    """汇总一个接口全部可变异字段（api_parameter + body schema）。"""
    specs: list[FieldSpec] = []
    for param in parameters or []:
        specs.append(field_spec_from_parameter(param))
    specs.extend(body_fields(body))
    return specs


def find_field(specs: Sequence[FieldSpec] | None, location: str, name: str) -> FieldSpec | None:
    """按位置与字段名找 FieldSpec。

    HEADER / COOKIE 大小写不敏感（HTTP 头没有大小写语义）；其它位置精确匹配。
    """
    target = str(location or "").upper()
    wanted = str(name or "").strip()
    if not wanted:
        return None
    insensitive = target in {"HEADER", "COOKIE"}
    for spec in specs or []:
        if spec.location != target:
            continue
        same = (spec.name.lower() == wanted.lower()) if insensitive else (spec.name == wanted)
        if same or (spec.json_path and spec.json_path == f"$.{wanted}"):
            return spec
    return None


# --------------------------------------------------------------------------- 取值生成


def integer_variants(spec: FieldSpec) -> list[Any]:
    """整数 schema 的计划取值：null / "abc" / -1 / 0 / maximum+1。"""
    values: list[Any] = [None, "abc", -1, 0]
    if spec.maximum is not None:
        values.append(int(spec.maximum) + 1)
    return values


def over_max_value(spec: FieldSpec) -> Any:
    """超上限取值：数值用 maximum+1，字符串用 maxLength+1 且封顶 256 字符。"""
    if spec.maximum is not None:
        return int(spec.maximum) + 1
    if spec.max_length is not None:
        return "a" * min(int(spec.max_length) + 1, MAX_MUTATION_STRING_LENGTH)
    raise RuleNotApplicableError(
        f"字段 {spec.name!r} 的 schema 没有 maximum / maxLength，OVER_MAX 无适用目标",
        code=CODE_SECURITY_MUTATION_INVALID,
    )


def over_max_capped(spec: FieldSpec) -> bool:
    """maxLength 已超过封顶值：生成的字符串样本可能并不真的超长（trace 需说明）。"""
    return (
        spec.max_length is not None
        and int(spec.max_length) + 1 > MAX_MUTATION_STRING_LENGTH
    )


def under_min_value(spec: FieldSpec) -> Any:
    """低于下限取值：数值用 minimum-1，字符串用 minLength-1 字符。"""
    if spec.minimum is not None:
        return int(spec.minimum) - 1
    if spec.min_length is not None:
        length = int(spec.min_length) - 1
        if length < 1:
            raise RuleNotApplicableError(
                f"字段 {spec.name!r} 的 minLength 为 1，没有更短的非空取值可测",
                code=CODE_SECURITY_MUTATION_INVALID,
            )
        return "a" * length
    raise RuleNotApplicableError(
        f"字段 {spec.name!r} 的 schema 没有 minimum / minLength，UNDER_MIN 无适用目标",
        code=CODE_SECURITY_MUTATION_INVALID,
    )


def invalid_enum_value(spec: FieldSpec) -> str:
    """枚举外取值：优先 UNKNOWN；UNKNOWN 已在枚举里则换 __INVALID__。"""
    if not spec.enum:
        raise RuleNotApplicableError(
            f"字段 {spec.name!r} 没有声明 enum，INVALID_ENUM 无适用目标",
            code=CODE_SECURITY_MUTATION_INVALID,
        )
    members = [str(v) for v in spec.enum]
    return "__INVALID__" if "UNKNOWN" in members else "UNKNOWN"


def invalid_format_value(spec: FieldSpec) -> str:
    """按 format 给固定非法样例；未声明可识别 format 时不适用。"""
    sample = INVALID_FORMAT_SAMPLES.get(str(spec.format or "").lower())
    if sample is None:
        raise RuleNotApplicableError(
            f"字段 {spec.name!r} 的 format={spec.format!r} 不在 email/date/uuid/uri 内，"
            "INVALID_FORMAT 无适用目标",
            code=CODE_SECURITY_MUTATION_INVALID,
        )
    return sample


def type_mutation_value(spec: FieldSpec) -> Any:
    """类型错位取值：integer/number → "abc"，string → 1，boolean → "yes"。"""
    values = {"integer": "abc", "number": "abc", "string": 1, "boolean": "yes"}
    value = values.get(spec.primary_type)
    if value is None:
        raise RuleNotApplicableError(
            f"字段 {spec.name!r} 类型为 {spec.type!r}，TYPE_MUTATION 只适用于 "
            "integer/number/string/boolean",
            code=CODE_SECURITY_MUTATION_INVALID,
        )
    return value


def value_for(spec: FieldSpec, mutation_type: str) -> Any:
    """按参数算子算出目标值。

    算子与字段类型不匹配时抛 ``RuleNotApplicableError``（错误码
    ``SECURITY_MUTATION_INVALID``），Runner 记 SKIPPED 而不是 FAILED_EXECUTION。
    """
    kind = spec.primary_type
    if mutation_type == "NULL_VALUE":
        if spec.nullable and not spec.required:
            raise RuleNotApplicableError(
                f"字段 {spec.name!r} 声明可空且非必填，NULL_VALUE 不构成校验缺失",
                code=CODE_SECURITY_MUTATION_INVALID,
            )
        return None
    if mutation_type == "EMPTY_STRING":
        if kind != "string":
            raise RuleNotApplicableError(
                f"字段 {spec.name!r} 类型为 {spec.type!r}，EMPTY_STRING 只适用于 string",
                code=CODE_SECURITY_MUTATION_INVALID,
            )
        return ""
    if mutation_type == "TYPE_MUTATION":
        return type_mutation_value(spec)
    if mutation_type == "ZERO":
        if kind not in {"integer", "number"}:
            raise RuleNotApplicableError(
                f"字段 {spec.name!r} 类型为 {spec.type!r}，ZERO 只适用于 integer/number",
                code=CODE_SECURITY_MUTATION_INVALID,
            )
        return 0
    if mutation_type == "NEGATIVE":
        if kind not in {"integer", "number"}:
            raise RuleNotApplicableError(
                f"字段 {spec.name!r} 类型为 {spec.type!r}，NEGATIVE 只适用于 integer/number",
                code=CODE_SECURITY_MUTATION_INVALID,
            )
        if spec.minimum is not None and spec.minimum < 0:
            raise RuleNotApplicableError(
                f"字段 {spec.name!r} 的 minimum 已允许负数，NEGATIVE 无验证意义",
                code=CODE_SECURITY_MUTATION_INVALID,
            )
        return -1
    if mutation_type == "OVER_MAX":
        return over_max_value(spec)
    if mutation_type == "UNDER_MIN":
        return under_min_value(spec)
    if mutation_type == "INVALID_ENUM":
        return invalid_enum_value(spec)
    if mutation_type == "INVALID_FORMAT":
        return invalid_format_value(spec)
    raise RuleNotApplicableError(
        f"{mutation_type} 不是参数类算子，无法从字段 schema 推导取值",
        code=CODE_SECURITY_MUTATION_INVALID,
    )
