"""统一模板解析器：`${namespace.path}` 唯一入口。

这是测试数据中心与用例执行器共用的**唯一**模板解析实现（§11）。之前
`test_case_executor._resolve_tokens` 里有一份只认 `data` / `env` 两个命名空间的
私有正则，Fixture 步骤里又需要 `fixture.<KEY>.<out>` 与 `${faker.phone}`，两份正则
必然漂移（口径不一致 = 同一个 `${env.base_url}` 在两边取值不同）。收口到这一处：

命名空间：
    fixture.<KEY>.<path>  ExecutionContext 里已注入的 Fixture 输出
                          （先按点路径走嵌套 dict，再按整体扁平键回退）
    faker.<generator>     白名单生成器，每次调用产新值（不缓存，保证 CASE 间不同）
    env.<key>             Environment 属性与 default_headers（键名单只此一份）
    runtime.<key>         ExecutionContext.variables 顶层键（也接受已带前缀的业务变量）；
                          额外 runtime.request_id / runtime.timestamp 由 ResolveScope 显式提供
                          （Mock Response Template 用，§十二）
    data.<name>           已解析的 test_case_data（先整体精确键，再点路径）
    request.<section>.<field>  Mock Response Template 专用（§十二）：section ∈ path/query/
                          header/body；header 大小写不敏感，body 支持点路径下钻
                          （${request.body.order_id} / ${request.header.X-User-Id}）。
                          仅当 ResolveScope.request 非 None 时生效，未提供时按缺失处理。

求值顺序（§11.4）：Fixture 输出已注入的 runtime > 本条 test_case_data > Environment >
Provider 配置里的字面量。本解析器只做「模板 → 值」，不决定优先级；优先级由调用方把
正确的 dict 放进 `ResolveScope`。

缺失语义：`required=true` 缺变量 → `VARIABLE_RESOLVE_FAILED`；非必需缺变量 → 空串
（与今天映射缺失必填才报错的口径对齐）。整段字符串恰好是一个占位符时保留原类型
（`_resolve_token_str` 的原行为），混合文本拼接成字符串。

安全边界：
    - ResolveScope 只放普通 dict / Environment / faker 实例，不放 Session；解析器不做 I/O，
      唯一的副作用是 Faker 的随机函数。
    - 嵌套 `${}` 最多递归 3 层，超过即报错，防止自引用造成死循环。
    - FAKER 只调固定白名单方法，不开放任意 Faker 方法名，不执行用户代码。
"""

from __future__ import annotations

import random
import re
from dataclasses import dataclass, field
from typing import TYPE_CHECKING, Any

from app.shared.errors import CODE_VARIABLE_RESOLVE_FAILED, AppError

if TYPE_CHECKING:  # 仅类型标注，避免运行期导入 ORM 模型
    from app.models.configuration import Environment

# `${namespace.path}`：命名空间是字母开头的标识符，path 由点号连接的标识符组成。
# 命名空间名本身不含点，path 可以多层（fixture.SUCCESS_TASK.task_id）。
TOKEN_PATTERN = re.compile(
    r"\$\{([A-Za-z][A-Za-z0-9_]*)(?:\.([A-Za-z0-9_]+(?:\.[A-Za-z0-9_]+)*))?\}"
)

# 嵌套解析上限：解析结果里还带 `${}` 时最多再解析 3 轮，防止自引用环。
MAX_NESTED_DEPTH = 3

# --------------------------------------------------------------------------- FAKER 白名单

FAKER_LOCALES = ("zh_CN", "en_US")

#: 允许的生成器 → 固定方法。不开放任意 Faker 方法名（不执行用户代码，§9.4）。
FAKER_GENERATORS = (
    "uuid",
    "name",
    "phone",
    "email",
    "string",
    "integer",
    "timestamp",
    "date",
    "url",
    "ip",
    "random_choice",
    "project_name",
)

#: 字符串形态生成器：`random_choice` 要求 choices，其余产出字符串或数字。
_FAKE_STRING_LEN = (8, 16)


def _make_faker(locale: str):
    """按 locale 新建 Faker 实例。非法 locale 只回退到 zh_CN，不抛错。"""
    from faker import Faker

    return Faker(locale if locale in FAKER_LOCALES else "zh_CN")


def generate_faker_value(generator: str, locale: str = "zh_CN", choices: list | None = None) -> Any:
    """按白名单生成器产一个新值。非法生成器 → `VARIABLE_RESOLVE_FAILED`。

    每次调用都重新生成，不做缓存：CASE 之间要拿到不同的值。
    """
    gen = (generator or "").strip()
    if gen not in FAKER_GENERATORS:
        raise AppError(
            f"不支持的 FAKER 生成器：{generator!r}（仅支持 {'/'.join(FAKER_GENERATORS)}）",
            status_code=400,
            code=CODE_VARIABLE_RESOLVE_FAILED,
        )
    faker = _make_faker(locale)
    if gen == "random_choice":
        if not choices or not isinstance(choices, list):
            raise AppError(
                "random_choice 需要非空 choices 数组（元素只能是字符串或数字）",
                status_code=400,
                code=CODE_VARIABLE_RESOLVE_FAILED,
            )
        if any(not isinstance(c, (str, int)) for c in choices):
            raise AppError(
                "random_choice 的元素只能是字符串或数字",
                status_code=400,
                code=CODE_VARIABLE_RESOLVE_FAILED,
            )
        return random.choice(choices)
    if gen == "uuid":
        return str(faker.uuid4())
    if gen == "name":
        return str(faker.name())
    if gen == "phone":
        return str(faker.phone_number())
    if gen == "email":
        return str(faker.email())
    if gen == "string":
        return str(faker.pystr(min_chars=_FAKE_STRING_LEN[0], max_chars=_FAKE_STRING_LEN[1]))
    if gen == "integer":
        return int(faker.pyint(min_value=1, max_value=99999))
    if gen == "timestamp":
        return int(faker.date_time_this_year().timestamp())
    if gen == "date":
        return faker.date_this_year().isoformat()
    if gen == "url":
        return str(faker.url())
    if gen == "ip":
        return str(faker.ipv4())
    if gen == "project_name":
        # 用 company / catch_phrase 截断，不开放任意方法名。
        base = str(faker.catch_phrase() or faker.company() or "测试项目")
        return base[:40]
    raise AppError(  # 理论上不可达：FAKER_GENERATORS 与分支已对齐
        f"未实现的 FAKER 生成器：{generator!r}",
        status_code=400,
        code=CODE_VARIABLE_RESOLVE_FAILED,
    )


# --------------------------------------------------------------------------- 环境键

#: Environment 上可直接取的属性键（与 test_case_executor 原 `_ENV_ATTR_KEYS` 同一份名单）。
ENV_ATTR_KEYS = frozenset({
    "base_url", "gateway_prefix", "display_name", "name", "description",
    "is_active", "is_default",
})


def resolve_env_key(environment: "Environment | None", key: str) -> Any:
    """按与 `_resolve_env_value` 相同的规则读取环境值：先属性，再 default_headers。

    键名单集中在此处一份，ENVIRONMENT Provider、`${env.X}` 模板、用例执行器都调用它，
    避免三份名单漂移（§9.5 / §11）。
    """
    raw = (key or "").strip()
    if not raw or environment is None:
        return ""
    if raw in ENV_ATTR_KEYS:
        return str(getattr(environment, raw, "") or "")
    headers = environment.default_headers
    if isinstance(headers, dict):
        return str(headers.get(raw, ""))
    return ""


def is_valid_identifier(name: str) -> bool:
    """校验输出变量名 / 路径片段：字母开头，字母数字下划线。"""
    return bool(re.fullmatch(r"[A-Za-z_][A-Za-z0-9_]*", name or ""))


# --------------------------------------------------------------------------- ResolveScope

_MISSING = object()


@dataclass
class RequestContext:
    """Mock Response Template 的请求上下文（§十二：${request.*}）。

    只放纯数据；header 查找大小写不敏感（HTTP 头习惯用连字符 / 大小写不一）。
    body 可以是 dict / list / 标量，walk_path 按点路径下钻。
    """

    path_params: dict[str, Any] = field(default_factory=dict)
    query: dict[str, Any] = field(default_factory=dict)
    headers: dict[str, str] = field(default_factory=dict)
    body: Any = None

    def header(self, name: str) -> object:
        """大小写、连字符 / 下划线不敏感地取请求头值。"""
        target = _normalize_header_name(name)
        for key, value in self.headers.items():
            if _normalize_header_name(key) == target:
                return value
        return _MISSING


def _normalize_header_name(name: str) -> str:
    """归一化头名：小写并把 '-' / ' ' 视作 '_'，与 SensitiveDataMasker 口径一致。"""
    return (name or "").lower().replace("-", "_").replace(" ", "_")


@dataclass
class ResolveScope:
    """一次模板求值可见的来源。只放纯数据，不放 Session（解析器不做 I/O）。

    Attributes:
        variables: 运行时变量（ExecutionContext.variables 的副本，或 Fixture 私有 dict）。
            `fixture.<KEY>.<out>` 与 `runtime.<key>` 都从这里取。
        data_values: 已解析的 test_case_data（`${data.name}`）。
        environment: Environment 实体（`${env.key}`）。
        locale: FAKER locale，仅 zh_CN / en_US。
        faker: 可选的 Faker 实例；不传时按 locale 新建。
        request: Mock Response Template 的请求上下文（`${request.*}`），非 Mock 场景为 None。
        runtime_request_id: `${runtime.request_id}` 的值（Mock Runtime 注入）。
        runtime_timestamp: `${runtime.timestamp}` 的值（Mock Runtime 注入）。
    """

    variables: dict[str, Any] | None = None
    data_values: dict[str, Any] | None = None
    environment: Any = None
    locale: str = "zh_CN"
    faker: Any = field(default=None)
    request: "RequestContext | None" = None
    runtime_request_id: str = ""
    runtime_timestamp: Any = None

    def get_variable(self, path: str) -> object:
        """按点路径在 variables 里取值：先走嵌套 dict，再回退整体扁平键。"""
        source = self.variables or {}
        value = walk_path(source, path)
        if value is not _MISSING:
            return value
        return source.get(path, _MISSING)

    def get_data_value(self, path: str) -> object:
        """`${data.name}`：先整体精确键（允许名字里带点），再点路径。"""
        source = self.data_values or {}
        if path in source:
            return source[path]
        return walk_path(source, path)

    def _faker(self) -> Any:
        if self.faker is None:
            self.faker = _make_faker(self.locale)
        return self.faker


def walk_path(source: Any, path: str) -> object:
    """按点路径逐段下钻；任一段不是 dict 或键缺失返回 _MISSING。"""
    current: Any = source
    for part in (path or "").split("."):
        if isinstance(current, dict) and part in current:
            current = current[part]
        else:
            return _MISSING
    return current


def _lookup(namespace: str, path: str | None, scope: ResolveScope, *, required: bool) -> tuple[bool, object]:
    """解析单个占位符。返回 (是否找到, 值)。找不到且 required → 抛 VARIABLE_RESOLVE_FAILED。"""
    ns = namespace.lower()
    key = path if path else namespace

    if ns == "faker":
        return True, generate_faker_value(key, locale=scope.locale, choices=None)

    if ns == "env":
        # 环境键缺失不视为错误：回退空串（与今天的 _resolve_env_value 一致）。
        return True, resolve_env_key(scope.environment, key)

    if ns in ("fixture", "runtime"):
        # fixture.<KEY>.<out>：先走嵌套命名空间 variables["fixture"]["<KEY>"]["<out>"]，
        # 再按点路径查扁平 dict，最后把 namespace.path 拼回当整体扁平键查一次。
        vars_ = scope.variables or {}
        if ns == "fixture":
            nested = vars_.get("fixture")
            if isinstance(nested, dict):
                value = walk_path(nested, key)
                if value is not _MISSING:
                    return True, value
        value = scope.get_variable(key)
        if value is not _MISSING:
            return True, value
        full = f"{namespace}.{path}" if path else namespace
        flat = vars_.get(full, _MISSING)
        if flat is not _MISSING:
            return True, flat
        # runtime.request_id / runtime.timestamp：Mock Runtime 显式注入（§十二）。
        # 变量里没有时回退到 ResolveScope 的运行时字段，不覆盖既有 runtime.<key> 语义。
        if ns == "runtime":
            if key == "request_id" and scope.runtime_request_id:
                return True, scope.runtime_request_id
            if key == "timestamp" and scope.runtime_timestamp is not None:
                return True, scope.runtime_timestamp
        if required:
            raise AppError(
                f"模板变量 {namespace}.{path} 缺失且为必需：无法解析 {key}",
                status_code=400,
                code=CODE_VARIABLE_RESOLVE_FAILED,
            )
        return False, ""

    if ns == "request":
        # ${request.path.x} / ${request.query.x} / ${request.header.x} / ${request.body.x}（§十二）。
        # 仅 Mock Response Template 注入 ResolveScope.request；其它场景为 None → 缺失。
        req = scope.request
        if req is None:
            if required:
                raise AppError(
                    f"模板变量 {namespace}.{path} 缺失且为必需：无请求上下文",
                    status_code=400,
                    code=CODE_VARIABLE_RESOLVE_FAILED,
                )
            return False, ""
        section, _, rest = (path or "").partition(".")
        if section == "path":
            value = req.path_params.get(rest, _MISSING)
        elif section == "query":
            value = req.query.get(rest, _MISSING)
        elif section == "header":
            value = req.header(rest) if rest else _MISSING
        elif section == "body":
            if not rest:
                return True, req.body
            value = walk_path(req.body, rest)
        else:
            if required:
                raise AppError(
                    f"不支持的 request 段：{section}（仅 path/query/header/body）",
                    status_code=400,
                    code=CODE_VARIABLE_RESOLVE_FAILED,
                )
            return False, ""
        if value is _MISSING:
            if required:
                raise AppError(
                    f"模板变量 {namespace}.{path} 缺失且为必需",
                    status_code=400,
                    code=CODE_VARIABLE_RESOLVE_FAILED,
                )
            return False, ""
        return True, value

    if ns == "data":
        value = scope.get_data_value(key)
        if value is not _MISSING:
            return True, value
        if required:
            raise AppError(
                f"测试数据项 {namespace}.{path} 不存在且为必需：无法解析 {key}",
                status_code=400,
                code=CODE_VARIABLE_RESOLVE_FAILED,
            )
        return False, ""

    if required:
        raise AppError(
            f"未知的模板命名空间：{namespace}（仅支持 fixture/faker/env/runtime/data/request）",
            status_code=400,
            code=CODE_VARIABLE_RESOLVE_FAILED,
        )
    return False, ""


def resolve_token_str(
    text: str,
    scope: ResolveScope,
    *,
    required: bool = False,
    depth: int = 0,
) -> Any:
    """替换单个字符串中的占位符；整串恰好是一个占位符时保留原类型。"""
    if not isinstance(text, str):
        return text
    if not text:
        return text

    for attempt in range(MAX_NESTED_DEPTH):
        matches = list(TOKEN_PATTERN.finditer(text))
        if not matches:
            return text

        # 整串即单一占位符 → 返回原类型值（保留 int / dict 等）。
        if len(matches) == 1 and matches[0].group(0) == text:
            found, value = _lookup(matches[0].group(1), matches[0].group(2), scope, required=required)
            return value if found else ("" if not required else value)

        def repl(m: "re.Match[str]") -> str:
            found, value = _lookup(m.group(1), m.group(2), scope, required=required)
            return str(value) if found else ""

        text = TOKEN_PATTERN.sub(repl, text)

    # 超过递归上限：说明有自引用（A 的值里又带 ${A}）。
    if TOKEN_PATTERN.search(text):
        raise AppError(
            f"模板嵌套超过 {MAX_NESTED_DEPTH} 层，可能自引用：{text[:80]}",
            status_code=400,
            code=CODE_VARIABLE_RESOLVE_FAILED,
        )
    return text


def resolve_template(obj: Any, scope: ResolveScope, *, required: bool = False) -> Any:
    """递归替换 dict / list / str 里的占位符；其它类型原样返回。"""
    if isinstance(obj, str):
        return resolve_token_str(obj, scope, required=required)
    if isinstance(obj, dict):
        return {k: resolve_template(v, scope, required=required) for k, v in obj.items()}
    if isinstance(obj, list):
        return [resolve_template(v, scope, required=required) for v in obj]
    return obj


__all__ = [
    "ENV_ATTR_KEYS",
    "FAKER_GENERATORS",
    "FAKER_LOCALES",
    "MAX_NESTED_DEPTH",
    "RequestContext",
    "ResolveScope",
    "generate_faker_value",
    "is_valid_identifier",
    "resolve_env_key",
    "resolve_template",
    "resolve_token_str",
    "walk_path",
]
