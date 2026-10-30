"""Data Provider 服务层：CRUD、启停、按 type 校验 config。

关键约束：
- config_json 由 `PROVIDER_CONFIG_MODELS` 里的 Pydantic 模型校验，`extra=forbid`，
  出现 `sql` / `raw_sql` / `statement` 等键直接 422（§10.1）。
- 配置里禁止出现密码类字段；数据库操作只存 connection_id，不存连接串。
- DATABASE_* 类型的创建/编辑/删除需要平台管理员（与目标库连接同级）。
- 风险等级：创建时缺省按 provider_type 推断，允许调高；DATABASE_* 不允许调成 LOW；
  配置里显式含 DELETE 时强制 CRITICAL 且默认 enabled=false。

service owns commit。
"""

from __future__ import annotations

from sqlalchemy.orm import Session

from app.features.test_data.models.fixture import FixtureStep
from app.features.test_data.models.provider import DataProvider
from app.features.test_data.schemas import (
    DB_OPERATIONS,
    PROVIDER_CONFIG_MODELS,
    PROVIDER_TYPES,
    RISK_LEVELS,
    DataProviderCreate,
    DataProviderListResponse,
    DataProviderResponse,
    DataProviderUpdate,
)
from app.features.test_data.services.access_service import require_admin, resolve_provider_project_id
from app.platform.projects.services.access_service import get_project_or_404, require_writable_project
from app.core.models.identity import User
from app.core.http.errors import (
    CODE_DATABASE_OPERATION_FORBIDDEN,
    AppError,
    bad_request,
    conflict,
    not_found,
)
from app.core.http.pagination import DEFAULT_PAGE_SIZE

# 各类型的默认风险等级。
DEFAULT_RISK_BY_TYPE: dict[str, str] = {
    "STATIC": "LOW",
    "ENVIRONMENT": "LOW",
    "FAKER": "LOW",
    "EXISTING_POOL": "LOW",
    "API_CREATE": "MEDIUM",
    "BUSINESS_ACTION": "MEDIUM",
    "BUSINESS_FLOW": "MEDIUM",
    "DATABASE_INSERT": "HIGH",
    "DATABASE_PATCH": "HIGH",
}

# 风险等级可调高的顺序（数值越大越严格）。
_RISK_RANK = {"LOW": 0, "MEDIUM": 1, "HIGH": 2, "CRITICAL": 3}

# config 顶层禁止出现的敏感键。
_FORBIDDEN_CONFIG_KEYS = frozenset(
    {"password", "passwd", "pwd", "secret", "token", "api_key", "apikey", "credential"}
)

# _STRICT_CONFIG_MODELS 是 Pydantic 校验器，按 provider_type 取用。
_STRICT_CONFIG_MODELS = PROVIDER_CONFIG_MODELS


def infer_risk(provider_type: str, config: dict | None) -> tuple[str, bool | None]:
    """推断风险等级；返回 (risk_level, enabled 覆盖值)。

    配置里显式包含 DELETE 时强制 CRITICAL 且默认 enabled=false。
    DATABASE_* 不允许 LOW。
    """
    risk = DEFAULT_RISK_BY_TYPE.get(provider_type, "MEDIUM")
    if config and provider_type.startswith("DATABASE") and isinstance(config.get("operation"), str):
        if config["operation"].strip().upper() == "DELETE":
            return "CRITICAL", False
    if provider_type.startswith("DATABASE") and risk == "LOW":
        risk = "HIGH"
    return risk, None


def validate_provider_config(provider_type: str, config: dict | None) -> dict:
    """按 provider_type 用 Pydantic 模型校验配置，返回校验后的 dict。

    - 未知 type → 400
    - extra=forbid：多出的键（含 sql）→ 422
    - 顶层禁止密码类键 → 400
    - DATABASE_* 的表名必须是合法标识符，operation 必须在白名单内
    """
    if provider_type not in PROVIDER_TYPES:
        raise bad_request(f"未知的 Provider 类型：{provider_type}")
    model_cls = _STRICT_CONFIG_MODELS.get(provider_type)
    if model_cls is None:
        raise bad_request(f"未知的 Provider 类型：{provider_type}")
    payload = dict(config or {})
    lowered = {str(k).strip().lower(): k for k in payload}
    for bad in _FORBIDDEN_CONFIG_KEYS:
        if bad in lowered:
            raise AppError(
                f"Provider 配置不允许包含 {str(lowered[bad])} 字段：数据库连接只存 connection_id",
                status_code=400,
                code=CODE_DATABASE_OPERATION_FORBIDDEN,
            )
    try:
        parsed = model_cls.model_validate(payload)
    except Exception as exc:  # noqa: BLE001  Pydantic ValidationError 转 422 信封
        raise AppError(
            f"Provider 配置校验失败：{exc}", status_code=422, code="ERR_VALIDATION"
        ) from exc
    validated = parsed.model_dump(exclude_none=True)

    if provider_type.startswith("DATABASE"):
        from app.features.test_data.security import db_guard

        db_guard.validate_identifier(validated.get("table"), field="table")
        operation = str(validated.get("operation") or "INSERT").upper()
        if operation not in DB_OPERATIONS:
            raise bad_request(f"不支持的数据库操作：{operation}")
        if validated.get("where"):
            for key in validated["where"]:
                db_guard.validate_identifier(str(key), field="where 列名")
        for key in validated.get("columns") or []:
            db_guard.validate_identifier(str(key), field="列名")
        for key in validated.get("values") or {}:
            db_guard.validate_identifier(str(key), field="列名")
        if str(validated.get("operation") or "").upper() == "DELETE":
            # DELETE 需要 allow_delete + CRITICAL（risk_level 在创建时统一强制）。
            if not validated.get("allow_delete"):
                raise AppError(
                    "DELETE 操作需要 config.allow_delete=true，且风险等级为 CRITICAL",
                    status_code=400,
                    code=CODE_DATABASE_OPERATION_FORBIDDEN,
                )
    return validated


def _requires_admin(provider_type: str) -> bool:
    """DATABASE_* 需要平台管理员。"""
    return str(provider_type or "").startswith("DATABASE")


def _usage_count(db: Session, provider_id: int) -> int:
    """被多少条步骤引用（fixture_step.provider_id）。"""
    return int(
        db.query(FixtureStep.id)
        .filter(FixtureStep.provider_id == provider_id)
        .count()
    )


def _last_status(db: Session, provider_id: int) -> str | None:
    """最近一次 provider_execution 的状态（Phase A 无运行时数据时为空）。"""
    from app.features.test_data.models.execution import ProviderExecution

    row = (
        db.query(ProviderExecution.status)
        .filter(ProviderExecution.provider_id == provider_id)
        .order_by(ProviderExecution.id.desc())
        .first()
    )
    return row[0] if row else None


def _response(p: DataProvider, db: Session | None = None) -> DataProviderResponse:
    """响应体不含密码：config_json 由 schema 保证不存密码字段。"""
    resp = DataProviderResponse.model_validate(p)
    if db is not None:
        resp.usage_count = _usage_count(db, p.id)
        resp.last_status = _last_status(db, p.id)
    return resp


class ProviderService:
    """Data Provider 服务。无状态，路由层复用单例。"""

    def list_providers(
        self, db: Session, project_id: int, user: User, *,
        provider_type: str | None = None, enabled: bool | None = None,
        keyword: str | None = None, page: int = 1, page_size: int = DEFAULT_PAGE_SIZE,
    ) -> DataProviderListResponse:
        """列出`providers`。"""
        get_project_or_404(db, project_id, user)
        q = db.query(DataProvider).filter(DataProvider.project_id == project_id)
        if provider_type:
            if provider_type not in PROVIDER_TYPES:
                raise bad_request("Provider 类型取值非法")
            q = q.filter(DataProvider.provider_type == provider_type)
        if enabled is not None:
            q = q.filter(DataProvider.enabled.is_(enabled))
        kw = (keyword or "").strip()
        if kw:
            q = q.filter(DataProvider.name.ilike(f"%{kw}%"))
        total = int(q.count())
        items = q.order_by(DataProvider.id.desc()).offset((page - 1) * page_size).limit(page_size).all()
        return DataProviderListResponse(
            items=[_response(p, db) for p in items], total=total, page=page, page_size=page_size
        )

    def create_provider(
        self, db: Session, project_id: int, body: DataProviderCreate, *, actor: User,
    ) -> DataProviderResponse:
        """创建提供器。"""
        project = require_writable_project(db, project_id, actor)
        if _requires_admin(body.provider_type):
            require_admin(db, actor)
        if body.provider_type not in PROVIDER_TYPES:
            raise bad_request(f"未知的 Provider 类型：{body.provider_type}")
        name = body.name.strip()
        if not name:
            raise bad_request("Provider 名称不能为空")
        if db.query(DataProvider).filter(
            DataProvider.project_id == project.id, DataProvider.name == name
        ).first() is not None:
            raise conflict("Provider 名称已存在")

        inferred_risk, forced_enabled = infer_risk(body.provider_type, body.config_json)
        risk = body.risk_level or inferred_risk
        if risk not in RISK_LEVELS:
            raise bad_request("风险等级取值非法")
        if _requires_admin(body.provider_type) and _RISK_RANK.get(risk, 0) < _RISK_RANK["HIGH"]:
            raise bad_request("数据库 Provider 风险等级不能低于 HIGH")
        # 允许调高不允许调低到默认之下：数据库类不能调成 LOW。
        validated = validate_provider_config(body.provider_type, body.config_json)
        if str(validated.get("operation") or "").upper() == "DELETE":
            risk = "CRITICAL"
            if body.enabled:
                raise bad_request("含 DELETE 的 Provider 默认禁用，请显式 enabled=false 后再启用")

        provider = DataProvider(
            project_id=project.id,
            name=name,
            provider_type=body.provider_type,
            config_json=validated,
            enabled=(False if forced_enabled is False else body.enabled),
            risk_level=risk,
            description=(body.description or "").strip() or None,
            created_by=actor.id,
        )
        db.add(provider)
        db.commit()
        db.refresh(provider)
        return _response(provider, db)

    def get_provider(self, db: Session, provider_id: int, user: User) -> DataProviderResponse:
        """获取提供器。"""
        return _response(self._get_or_404(db, provider_id, user), db)

    def update_provider(
        self, db: Session, provider_id: int, body: DataProviderUpdate, *, actor: User,
    ) -> DataProviderResponse:
        """更新提供器。"""
        provider = self._get_writable_or_404(db, provider_id, actor)
        data = body.model_dump(exclude_unset=True)
        if not data:
            return _response(provider, db)

        provider_type = data.get("provider_type") or provider.provider_type
        if provider_type not in PROVIDER_TYPES:
            raise bad_request("Provider 类型取值非法")
        config = data.get("config_json", provider.config_json)
        risk = data.get("risk_level") or provider.risk_level

        if _requires_admin(provider_type):
            require_admin(db, actor)

        name = data.get("name")
        if name is not None:
            name = name.strip()
            if not name:
                raise bad_request("Provider 名称不能为空")
            exists = db.query(DataProvider).filter(
                DataProvider.project_id == provider.project_id,
                DataProvider.name == name,
                DataProvider.id != provider.id,
            ).first()
            if exists is not None:
                raise conflict("Provider 名称已存在")
            provider.name = name

        validated = validate_provider_config(provider_type, config)
        inferred_risk, forced_enabled = infer_risk(provider_type, validated)
        if risk not in RISK_LEVELS:
            raise bad_request("风险等级取值非法")
        if _requires_admin(provider_type) and _RISK_RANK.get(risk, 0) < _RISK_RANK["HIGH"]:
            raise bad_request("数据库 Provider 风险等级不能低于 HIGH")
        if str(validated.get("operation") or "").upper() == "DELETE" and not risk == "CRITICAL":
            raise bad_request("含 DELETE 的 Provider 风险等级必须为 CRITICAL")

        provider.provider_type = provider_type
        provider.config_json = validated
        provider.risk_level = "CRITICAL" if str(validated.get("operation") or "").upper() == "DELETE" else risk
        if data.get("description") is not None:
            provider.description = data["description"].strip() or None
        if data.get("enabled") is not None:
            if str(validated.get("operation") or "").upper() == "DELETE" and data["enabled"]:
                require_admin(db, actor)
            provider.enabled = bool(data["enabled"])
        if forced_enabled is False and provider.enabled:
            provider.enabled = False

        db.commit()
        db.refresh(provider)
        return _response(provider, db)

    def set_enabled(
        self, db: Session, provider_id: int, *, enabled: bool, actor: User,
    ) -> DataProviderResponse:
        """设置启用状态。"""
        provider = self._get_writable_or_404(db, provider_id, actor)
        if _requires_admin(provider.provider_type) and enabled:
            require_admin(db, actor)
        if (
            enabled
            and str((provider.config_json or {}).get("operation") or "").upper() == "DELETE"
            and provider.risk_level != "CRITICAL"
        ):
            raise bad_request("含 DELETE 的 Provider 风险等级必须为 CRITICAL")
        provider.enabled = enabled
        db.commit()
        db.refresh(provider)
        return _response(provider, db)

    def delete_provider(self, db: Session, provider_id: int, *, actor: User) -> None:
        """删除提供器。"""
        provider = self._get_writable_or_404(db, provider_id, actor)
        if _requires_admin(provider.provider_type):
            require_admin(db, actor)
        used = _usage_count(db, provider.id)
        if used:
            raise conflict(f"该 Provider 正被 {used} 条 Fixture 步骤引用，请先移除引用")
        db.delete(provider)
        db.commit()

    def _get_or_404(self, db: Session, provider_id: int, user: User) -> DataProvider:
        """获取或。"""
        row = db.get(DataProvider, provider_id)
        if row is None:
            raise not_found("数据 Provider 不存在")
        get_project_or_404(db, row.project_id, user)
        return row

    def _get_writable_or_404(self, db: Session, provider_id: int, actor: User) -> DataProvider:
        """获取可写或。"""
        row = db.get(DataProvider, provider_id)
        if row is None:
            raise not_found("数据 Provider 不存在")
        require_writable_project(db, resolve_provider_project_id(db, provider_id), actor)
        return row


def get_provider_or_none(db: Session, provider_id: int | None) -> DataProvider | None:
    """内部使用：取 Provider 行（不校验权限），供 runtime 使用。"""
    if provider_id is None:
        return None
    return db.get(DataProvider, provider_id)


def provider_visible(db: Session, provider_id: int, project_id: int) -> DataProvider | None:
    """内部使用：只取属于该项目的 Provider，跨项目返回 None（对调用方隐藏）。"""
    if provider_id is None:
        return None
    row = db.get(DataProvider, provider_id)
    if row is None or row.project_id != project_id:
        return None
    return row


__all__ = [
    "ProviderService",
    "DEFAULT_RISK_BY_TYPE",
    "get_provider_or_none",
    "infer_risk",
    "provider_visible",
    "validate_provider_config",
]
