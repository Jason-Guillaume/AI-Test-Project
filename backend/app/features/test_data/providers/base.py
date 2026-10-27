"""Data Provider 统一协议（§9）。

所有 Provider 实现 ``run(ctx) -> ProviderResult``，不互相调用、不共享状态：
每个实例都是无状态的，可以在进程级复用。

关键约定：
- ``cleanup_handle`` 是**结构化描述**而不是可调用闭包，以便落库后进程重启仍能清理。
  例：``{"type": "API", "method": "DELETE", "path": "/api/project/${fixture.X.id}"}``、
  ``{"type": "POOL_LEASE", "lease_id": 12, "item_id": 3}``。
- Provider 只把结果放进返回值，不自己写执行记录；写 ``provider_execution`` 是
  ``runtime/data_factory.py`` 的职责（它负责脱敏、计时、状态流转）。
- Provider 不做权限判断；project 归属在 ``data_factory`` 里已经校验过一遍。
  但 API_CREATE / BUSINESS_* / EXISTING_POOL 内部会再按 project_id 过滤资源，
  防止跨项目引用（对调用方隐藏不存在）。
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import TYPE_CHECKING, Any

from app.shared.errors import AppError

if TYPE_CHECKING:  # 仅类型标注
    from sqlalchemy.orm import Session

    from app.features.test_data.models.fixture import FixtureStep
    from app.features.test_data.models.provider import DataProvider
    from app.features.test_data.runtime.variable_resolver import ResolveScope
    from app.models.configuration import Environment
    from app.models.identity import User

#: ``output_snapshot`` / ``fixture_cache.output_json`` 的保留键：结构化 cleanup 句柄。
#: 该键不进入 Fixture 契约输出（§9）。
CLEANUP_HANDLE_KEY = "_cleanup"

#: outputs 里的保留键：Provider 的完整响应体（dict）。
#: data_factory 把它摊平进私有变量，让输出契约能用 ``$.data.id`` 这种 JSON 路径
#: 取值，与只写输出映射名（``task_id``）两种写法并存。不进 Fixture 契约输出。
RESPONSE_BODY_KEY = "_response"

STATUS_SUCCESS = "SUCCESS"
STATUS_FAILED = "FAILED"


@dataclass
class ProviderContext:
    """一次 Provider 执行的上下文。

    Attributes:
        db: 平台库会话（Provider 只做短连接访问被测库，不在 db 上执行自建 SQL）。
        project_id: 消费方项目 ID。
        environment: 本次运行 / 试跑的环境。
        actor: 触发者。
        variables: **私有变量** dict，Provider 直接往里写输出。步骤中间键只存在于这里，
            不进入 Fixture 输出契约，也不注入给用例。
        scope: 模板求值作用域（`${fixture.X.y}` / `${faker.phone}` / `${env.*}`）。
        test_run_id / case_execution_id: 归属记录；手工试跑两者都为空。
        runtime_scope: 生效作用域 CASE/RUN/PROJECT/GLOBAL/MANUAL。
        step: 触发本执行的 Fixture 步骤（手工试跑 Provider 时为空）。
        provider: 被引用的 DataProvider（步骤内联配置时为空）。
    """

    db: "Session"
    project_id: int
    environment: "Environment"
    actor: "User"
    variables: dict[str, Any] = field(default_factory=dict)
    scope: "ResolveScope" = field(default_factory=lambda: ResolveScope())
    test_run_id: int | None = None
    case_execution_id: int | None = None
    runtime_scope: str = "MANUAL"
    step: "FixtureStep | None" = None
    provider: "DataProvider | None" = None

    @property
    def actor_id(self) -> int | None:
        """获取操作人标识。"""
        return getattr(self.actor, "id", None)


@dataclass
class ProviderResult:
    """Provider 执行结果。快照必须由 Provider 自己脱敏后再放进这里。"""

    status: str
    outputs: dict[str, Any] = field(default_factory=dict)
    request_snapshot: dict[str, Any] | None = None
    response_snapshot: dict[str, Any] | None = None
    error_code: str | None = None
    error_message: str | None = None
    cleanup_handle: dict[str, Any] | None = None

    @property
    def success(self) -> bool:
        """判断操作是否成功。"""
        return self.status == STATUS_SUCCESS

    @classmethod
    def ok(
        cls,
        outputs: dict[str, Any] | None = None,
        *,
        request_snapshot: dict[str, Any] | None = None,
        response_snapshot: dict[str, Any] | None = None,
        cleanup_handle: dict[str, Any] | None = None,
    ) -> "ProviderResult":
        """构造成功的提供器执行结果。"""
        return cls(
            status=STATUS_SUCCESS,
            outputs=dict(outputs or {}),
            request_snapshot=request_snapshot,
            response_snapshot=response_snapshot,
            error_code=None,
            error_message=None,
            cleanup_handle=cleanup_handle,
        )

    @classmethod
    def fail(
        cls,
        error_code: str,
        error_message: str,
        *,
        request_snapshot: dict[str, Any] | None = None,
        response_snapshot: dict[str, Any] | None = None,
        outputs: dict[str, Any] | None = None,
    ) -> "ProviderResult":
        """生成失败结果并保留错误信息。"""
        return cls(
            status=STATUS_FAILED,
            outputs=dict(outputs or {}),
            request_snapshot=request_snapshot,
            response_snapshot=response_snapshot,
            error_code=error_code,
            error_message=error_message,
            cleanup_handle=None,
        )


def config_of(ctx: ProviderContext) -> dict[str, Any]:
    """取当前执行的配置：优先引用 Provider 行，其次步骤内联 ``config_json``。

    两种来源都可能有配置时，Provider 行为准——避免「步骤里改配置，Provider 里是另一份」
    的两套配置漂移。
    """
    if ctx.provider is not None:
        return dict(ctx.provider.config_json or {})
    if ctx.step is not None:
        return dict(ctx.step.config_json or {})
    return {}


class BaseProvider:
    """Provider 基类：只声明协议，不做任何 I/O。"""

    #: 类型名，与 schemas.PROVIDER_TYPES 对齐（数据库造数有两个类型共用一个实现）。
    provider_type: str = "STATIC"

    def run(self, ctx: ProviderContext) -> ProviderResult:
        """运行对应数据。"""
        # noqa: D401 - 协议方法
        raise NotImplementedError

    # ---------------------------------------------------------------- 配置装载

    @staticmethod
    def load_config(config_json: dict[str, Any] | None, model_cls: type) -> Any:
        """用 schemas 里的严格模型校验配置（``extra="forbid"``，多出的键直接报错）。

        配置不合法属于配置错误，统一报 ``FIXTURE_INVALID``：不要把它伪装成
        ``VARIABLE_RESOLVE_FAILED``，否则排障时会被带去查变量而不是查配置。
        """
        from pydantic import ValidationError

        from app.shared.errors import CODE_FIXTURE_INVALID, AppError

        try:
            return model_cls.model_validate(config_json or {})
        except ValidationError as exc:
            first = exc.errors()[0]
            loc = ".".join(str(p) for p in first.get("loc", []))
            raise AppError(
                f"Provider 配置不合法（{loc or '根节点'}）：{first.get('msg', '校验失败')}",
                status_code=400,
                code=CODE_FIXTURE_INVALID,
            ) from exc

    @staticmethod
    def resolve_mapping(scope: "ResolveScope", mappings: list[Any]) -> dict[str, Any]:
        """把 ``target/location/expression`` 形式的映射求值成 ``{target: value}``。"""
        from app.features.test_data.runtime.variable_resolver import resolve_token_str

        resolved: dict[str, Any] = {}
        for m in mappings or []:
            target = getattr(m, "target", None) or (m.get("target") if isinstance(m, dict) else None)
            expression = getattr(m, "expression", None) or (m.get("expression") if isinstance(m, dict) else None)
            if not target or not expression:
                continue
            try:
                resolved[target] = resolve_token_str(expression, scope, required=True)
            except Exception as exc:  # noqa: BLE001 - 需要把错误码原样上抛
                if isinstance(exc, Exception) and hasattr(exc, "code"):
                    raise
                from app.shared.errors import CODE_VARIABLE_RESOLVE_FAILED, AppError

                raise AppError(
                    f"映射 {target} 求值失败：{exc}",
                    status_code=400,
                    code=CODE_VARIABLE_RESOLVE_FAILED,
                ) from exc
        return resolved


def run_safe(provider: BaseProvider, ctx: ProviderContext) -> ProviderResult:
    """调用 ``provider.run`` 并把异常收敛成 ``ProviderResult.fail``，绝不抛出。

    Data Factory 与 Cleanup Runner 共用这一处收敛逻辑，保证「Provider 崩了」和
    「Provider 返回失败」在记录里是同一种形状（状态 + 错误码 + 错误信息）。
    """
    try:
        return provider.run(ctx)
    except AppError as exc:
        return ProviderResult.fail(exc.code or "FIXTURE_GENERATION_FAILED", str(exc))
    except Exception as exc:  # noqa: BLE001 - Provider 内部异常收敛成统一错误码
        return ProviderResult.fail("FIXTURE_GENERATION_FAILED", str(exc)[:300])
