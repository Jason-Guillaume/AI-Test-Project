"""环境配置服务层：校验、默认项归一化与内置环境回退。

环境的 base_url 决定测试流量真正打到哪台服务器，因此写操作仅限平台管理员。
集中处理三件容易出错的事：环境名规范化、唯一默认环境的归一化、表为空时的回退。
"""

from __future__ import annotations

from types import SimpleNamespace

from sqlalchemy.orm import Session

from app.features.environment_configuration.schemas import (
    EnvironmentCreate,
    EnvironmentUpdate,
    ProjectEnvironmentCreate,
    ProjectEnvironmentUpdate,
    builtin_environments,
    normalize_environment_name,
)
from app.models.configuration import Environment
from app.features.environment_configuration.models import ProjectEnvironment
from app.shared.errors import bad_request, conflict, not_found
from app.shared.roles import is_platform_admin

BUILTIN_NAMES = frozenset({"dev", "test", "staging", "prod"})


def _require_admin(actor) -> None:
    """权限判定：写环境配置必须平台管理员，否则抛 403。"""
    if not is_platform_admin(actor):
        from app.shared.errors import forbidden

        raise forbidden("仅管理员可执行该操作")


def response_for(row: Environment) -> dict:
    """构建响应体，字段与前端环境管理页面一一对应。

    所有可空字段统一回退为空串，避免前端拿到 null 后还要判空。
    """
    return {
        "id": row.id,
        "project_id": None,
        "name": row.name,
        "display_name": row.display_name or row.name,
        "base_url": row.base_url or "",
        "gateway_prefix": row.gateway_prefix or "",
        "default_headers": dict(row.default_headers or {}),
        "description": row.description or "",
        "is_default": bool(row.is_default),
        "is_active": bool(row.is_active),
        "created_by": row.created_by,
        "updated_by": row.updated_by,
        "created_at": row.created_at,
        "updated_at": row.updated_at,
    }


def response_for_builtin(config: dict) -> dict:
    """内置默认环境的响应体：id 为空表示尚未落库、不可编辑。"""
    return {
        "id": None,
        "name": config["name"],
        "display_name": config.get("display_name") or config["name"],
        "base_url": config.get("base_url") or "",
        "gateway_prefix": config.get("gateway_prefix") or "",
        "default_headers": dict(config.get("default_headers") or {}),
        "description": config.get("description") or "",
        "is_default": bool(config.get("is_default")),
        "is_active": True,
        "created_by": None,
        "updated_by": None,
        "created_at": None,
        "updated_at": None,
    }


def _list_environments(db: Session, *, include_inactive: bool = True) -> list[Environment]:
    """按「默认优先、其次创建顺序」列出环境，与执行器的选择顺序一致。"""
    query = db.query(Environment)
    if not include_inactive:
        query = query.filter(Environment.is_active.is_(True))
    return query.order_by(Environment.is_default.desc(), Environment.id.asc()).all()


def list_environments(db: Session, *, include_inactive: bool = True) -> list[dict]:
    """环境列表响应体。

    表为空时（旧库刚升级、或播种前）回退到内置默认值，让前端选择器与执行链路
    看到同一份配置，而不是一个空下拉框。
    """
    rows = _list_environments(db, include_inactive=include_inactive)
    if rows:
        return [response_for(row) for row in rows]
    # 降级路径：库表为空时不报错，改用内置环境兜底。
    return [
        response_for_builtin(config)
        for config in builtin_environments()
        if include_inactive or config.get("is_active", True)
    ]


def get_by_name(db: Session, name: str) -> Environment | None:
    """按名称查环境，找不到返回 None（不做权限判断，由调用方决定如何呈现）。"""
    return db.query(Environment).filter(Environment.name == name).first()


def get_or_404(db: Session, name: str) -> Environment:
    """按名称取环境，不存在抛 400（环境名是业务主键，不存在视为参数错误）。"""
    row = get_by_name(db, name)
    if row is None:
        raise bad_request("环境不存在")
    return row


def normalize_headers(headers: dict | None) -> dict:
    """规范化默认请求头：只接受字符串值，键不能为空。"""
    result: dict = {}
    for key, value in (headers or {}).items():
        key_text = str(key).strip()
        if not key_text:
            raise bad_request("默认请求头不能包含空键")
        if len(str(value)) > 500:
            raise bad_request("默认请求头值过长")
        result[key_text] = str(value)
    return result


def _validate_base_url(value: str) -> str:
    """规范化被测服务地址：只保留 http(s) 与网关前缀，去掉首尾斜杠。"""
    base_url = (value or "").strip()
    if base_url and not base_url.startswith(("http://", "https://")):
        raise bad_request("base_url 必须以 http:// 或 https:// 开头")
    return base_url.rstrip("/")


def _normalize_default(db: Session, keep: Environment | None) -> None:
    """保证至多一个默认环境；没有任何默认项时把第一个启用环境提上来。

    默认环境是「未指定环境」时的兜底目标，两个默认项会让执行结果取决于查询顺序。
    """
    if keep is not None and keep.is_active:
        # 先清掉其它默认标记，再把保留项设为默认，保证「至多一个」这个不变量。
        for row in db.query(Environment).filter(Environment.is_default.is_(True)).all():
            if row.id != keep.id:
                row.is_default = False
        keep.is_default = True
        return

    rows = _list_environments(db, include_inactive=False)
    defaults = [row for row in rows if row.is_default]
    fallback = defaults[0] if defaults else (rows[0] if rows else None)
    for row in db.query(Environment).all():
        row.is_default = bool(fallback and row.id == fallback.id)


def _normalize_project_default(db: Session, project_id: int, keep: ProjectEnvironment | None) -> None:
    """每个项目单独维护唯一默认环境。"""
    active = (
        db.query(ProjectEnvironment)
        .filter(
            ProjectEnvironment.project_id == project_id,
            ProjectEnvironment.is_active.is_(True),
        )
        .order_by(ProjectEnvironment.id.asc())
        .all()
    )
    if keep is not None and keep.is_active:
        for row in active:
            row.is_default = row.id == keep.id
        return
    default = next((row for row in active if row.is_default), active[0] if active else None)
    for row in db.query(ProjectEnvironment).filter(ProjectEnvironment.project_id == project_id).all():
        row.is_default = bool(default and row.id == default.id)


def ensure_project_environments(db: Session, project_id: int, *, actor_id: int | None = None) -> None:
    """为没有环境绑定的项目复制模板配置；兼容迁移前已存在的项目。"""
    if db.query(ProjectEnvironment.id).filter(ProjectEnvironment.project_id == project_id).first() is not None:
        return

    templates = _list_environments(db, include_inactive=True)
    if actor_id is not None:
        # 新项目默认只获得内置环境类型；其它类型由管理员显式加入，避免把
        # 某一个项目新建的自定义环境自动扩散到之后创建的所有项目。
        templates = [row for row in templates if row.name in BUILTIN_NAMES]
    if not templates:
        configs = builtin_environments()
        if actor_id is not None:
            configs = [config for config in configs if config["name"] in BUILTIN_NAMES]
        for config in configs:
            row = Environment(
                name=config["name"], display_name=config["display_name"],
                base_url=config["base_url"], gateway_prefix=config["gateway_prefix"],
                default_headers=config["default_headers"], description=config["description"],
                is_default=config["is_default"], is_active=config["is_active"],
                created_by=actor_id, updated_by=actor_id,
            )
            db.add(row)
            templates.append(row)
        db.flush()

    for template in templates:
        db.add(ProjectEnvironment(
            project_id=project_id,
            environment_id=template.id,
            display_name=template.display_name or template.name,
            base_url=template.base_url or "",
            gateway_prefix=template.gateway_prefix or "",
            default_headers=dict(template.default_headers or {}),
            description=template.description,
            is_default=bool(template.is_default),
            is_active=bool(template.is_active),
            created_by=actor_id,
            updated_by=actor_id,
        ))
    db.flush()
    _normalize_project_default(db, project_id, None)


def project_environment_response(db: Session, binding: ProjectEnvironment) -> dict:
    """管理端响应：项目环境字段覆盖模板中的旧全局目标值。"""
    template = db.get(Environment, binding.environment_id)
    if template is None:
        return {}
    return {
        **response_for(template),
        "project_id": binding.project_id,
        "display_name": binding.display_name or template.display_name or template.name,
        "base_url": binding.base_url or "",
        "gateway_prefix": binding.gateway_prefix or "",
        "default_headers": dict(binding.default_headers or {}),
        "description": binding.description or "",
        "is_default": bool(binding.is_default),
        "is_active": bool(binding.is_active),
        "created_by": binding.created_by,
        "updated_by": binding.updated_by,
        "created_at": binding.created_at,
        "updated_at": binding.updated_at,
    }


def list_project_environment_configs(
    db: Session, project_id: int, *, include_inactive: bool = True
) -> list[dict]:
    """列出项目环境`configs`。"""
    ensure_project_environments(db, project_id)
    query = db.query(ProjectEnvironment).filter(ProjectEnvironment.project_id == project_id)
    if not include_inactive:
        query = query.filter(ProjectEnvironment.is_active.is_(True))
    rows = query.order_by(ProjectEnvironment.is_default.desc(), ProjectEnvironment.id.asc()).all()
    result = [project_environment_response(db, row) for row in rows]
    db.commit()  # 仅当旧项目缺少初始环境绑定时才写入。
    return result


def list_project_environment_options(
    db: Session, project_id: int, *, include_inactive: bool = False
) -> list[dict]:
    """前端执行选择器响应：只返回项目已关联环境，不暴露默认请求头。"""
    query = (
        db.query(ProjectEnvironment, Environment)
        .join(Environment, Environment.id == ProjectEnvironment.environment_id)
        .filter(ProjectEnvironment.project_id == project_id)
    )
    if not include_inactive:
        query = query.filter(ProjectEnvironment.is_active.is_(True))
    rows = query.order_by(ProjectEnvironment.is_default.desc(), ProjectEnvironment.id.asc()).all()
    result = [
        {
            "id": template.id,
            "project_id": binding.project_id,
            "name": template.name,
            "display_name": binding.display_name or template.display_name or template.name,
            "base_url": binding.base_url or "",
            "gateway_prefix": binding.gateway_prefix or "",
            "default_headers": {},
            "description": binding.description or "",
            "is_default": bool(binding.is_default),
            "is_active": bool(binding.is_active),
            "created_by": binding.created_by,
            "updated_by": binding.updated_by,
            "created_at": binding.created_at,
            "updated_at": binding.updated_at,
        }
        for binding, template in rows
    ]
    return result


def resolve_project_environment(db: Session, project_id: int, environment_id: int):
    """解析项目实际使用的环境；执行时必须存在活动的项目绑定。"""
    pair = (
        db.query(ProjectEnvironment, Environment)
        .join(Environment, Environment.id == ProjectEnvironment.environment_id)
        .filter(
            ProjectEnvironment.project_id == project_id,
            ProjectEnvironment.environment_id == environment_id,
            ProjectEnvironment.is_active.is_(True),
        )
        .first()
    )
    if pair is None:
        raise not_found("该环境未关联当前项目或已停用")
    binding, template = pair
    return SimpleNamespace(
        id=template.id,
        name=template.name,
        display_name=binding.display_name or template.display_name or template.name,
        base_url=binding.base_url or "",
        gateway_prefix=binding.gateway_prefix or "",
        default_headers=dict(binding.default_headers or {}),
        description=binding.description,
        is_default=bool(binding.is_default),
        is_active=True,
        created_by=binding.created_by,
        updated_by=binding.updated_by,
        created_at=binding.created_at,
        updated_at=binding.updated_at,
    )


def resolve_project_environment_by_name(db: Session, project_id: int, name: str):
    """解析并确定项目环境按名称。"""
    template = get_by_name(db, name)
    if template is None:
        raise not_found("环境未关联当前项目或已停用")
    return resolve_project_environment(db, project_id, template.id)


def create_project_environment(
    db: Session, project_id: int, body: ProjectEnvironmentCreate, *, actor
) -> ProjectEnvironment:
    """新增项目环境配置，并在需要时创建可复用的环境类型模板。"""
    _require_admin(actor)
    from app.models.project import Project

    if db.get(Project, project_id) is None:
        raise not_found("项目不存在")
    name = normalize_environment_name(body.name)
    if not name:
        raise bad_request("环境名只能包含字母、数字、下划线和短横线，且以字母或数字开头")
    if body.is_default and not body.is_active:
        raise bad_request("停用环境不能设为默认环境")
    template = get_by_name(db, name)
    if template is None:
        template = Environment(
            name=name,
            display_name=body.display_name.strip() or name,
            base_url="",
            gateway_prefix="",
            default_headers={},
            description=(body.description or "").strip() or None,
            is_default=False,
            is_active=True,
            created_by=actor.id,
            updated_by=actor.id,
        )
        db.add(template)
        db.flush()
    if db.query(ProjectEnvironment.id).filter(
        ProjectEnvironment.project_id == project_id,
        ProjectEnvironment.environment_id == template.id,
    ).first() is not None:
        raise conflict("该环境已关联当前项目")
    row = ProjectEnvironment(
        project_id=project_id,
        environment_id=template.id,
        display_name=body.display_name.strip() or template.display_name or template.name,
        base_url=_validate_base_url(body.base_url),
        gateway_prefix=(body.gateway_prefix or "").strip(),
        default_headers=normalize_headers(body.default_headers),
        description=(body.description or "").strip() or None,
        is_active=bool(body.is_active),
        is_default=False,
        created_by=actor.id,
        updated_by=actor.id,
    )
    db.add(row)
    db.flush()
    _normalize_project_default(db, project_id, row if body.is_default else None)
    db.commit()
    db.refresh(row)
    return row


def update_project_environment(
    db: Session, project_id: int, environment_id: int,
    body: ProjectEnvironmentUpdate, *, actor,
) -> ProjectEnvironment:
    """更新项目环境。"""
    _require_admin(actor)
    row = db.query(ProjectEnvironment).filter_by(
        project_id=project_id, environment_id=environment_id
    ).first()
    if row is None:
        raise not_found("项目环境配置不存在")
    data = body.model_dump(exclude_unset=True)
    if data.get("base_url") is not None:
        data["base_url"] = _validate_base_url(data["base_url"])
    if data.get("display_name") is not None:
        data["display_name"] = data["display_name"].strip() or row.display_name
    if data.get("gateway_prefix") is not None:
        data["gateway_prefix"] = data["gateway_prefix"].strip()
    if data.get("default_headers") is not None:
        data["default_headers"] = normalize_headers(data["default_headers"])
    if data.get("description") is not None:
        data["description"] = data["description"].strip() or None
    if data.get("is_default") is True and not data.get("is_active", row.is_active):
        raise bad_request("停用环境不能设为默认环境")
    for field, value in data.items():
        setattr(row, field, value)
    row.updated_by = actor.id
    _normalize_project_default(db, project_id, row if row.is_default else None)
    db.commit()
    db.refresh(row)
    return row


def set_project_default_environment(
    db: Session, project_id: int, environment_id: int, *, actor
) -> ProjectEnvironment:
    """设置项目默认环境。"""
    return update_project_environment(
        db, project_id, environment_id,
        ProjectEnvironmentUpdate(is_default=True), actor=actor,
    )


def deactivate_project_environment(
    db: Session, project_id: int, environment_id: int, *, actor
) -> ProjectEnvironment:
    """停用项目环境。"""
    return update_project_environment(
        db, project_id, environment_id,
        ProjectEnvironmentUpdate(is_active=False), actor=actor,
    )


def create_environment(db: Session, body: EnvironmentCreate, *, actor) -> Environment:
    """新增环境。"""
    _require_admin(actor)
    name = normalize_environment_name(body.name)
    if not name:
        raise bad_request("环境名只能包含字母、数字、下划线和短横线，且以字母或数字开头")
    if get_by_name(db, name) is not None:
        raise conflict("环境已存在")

    row = Environment(
        name=name,
        display_name=(body.display_name or "").strip() or name,
        base_url=_validate_base_url(body.base_url),
        gateway_prefix=(body.gateway_prefix or "").strip(),
        default_headers=normalize_headers(body.default_headers),
        description=(body.description or "").strip() or None,
        is_default=False,
        is_active=True,
        created_by=actor.id,
        updated_by=actor.id,
    )
    db.add(row)
    db.flush()  # 先 flush 拿到自增主键，再做默认项归一化。
    if body.is_default:
        _normalize_default(db, row)
    else:
        _normalize_default(db, None)
    db.commit()
    db.refresh(row)
    return row


def update_environment(db: Session, name: str, body: EnvironmentUpdate, *, actor) -> Environment:
    """更新环境；名称不可修改。"""
    _require_admin(actor)
    row = get_or_404(db, name)

    # exclude_unset：未提交的字段不动，空串视为「保持原名/清空说明」。
    data = body.model_dump(exclude_unset=True)
    if not data:
        return row

    if data.get("base_url") is not None:
        data["base_url"] = _validate_base_url(data["base_url"])
    if data.get("display_name") is not None:
        data["display_name"] = data["display_name"].strip() or row.name
    if data.get("gateway_prefix") is not None:
        data["gateway_prefix"] = data["gateway_prefix"].strip()
    if data.get("default_headers") is not None:
        data["default_headers"] = normalize_headers(data["default_headers"])
    if data.get("description") is not None:
        data["description"] = data["description"].strip() or None

    for field, value in data.items():
        setattr(row, field, value)
    row.updated_by = actor.id

    # 停用环境不能保持默认位：本次操作若不是默认项，则重新分配默认位。
    _normalize_default(db, row if row.is_default else None)
    db.commit()
    db.refresh(row)
    return row


def set_default_environment(db: Session, name: str, *, actor) -> Environment:
    """把指定环境设为默认环境；停用环境不能成为默认项。"""
    _require_admin(actor)
    row = get_or_404(db, name)
    if not row.is_active:
        raise bad_request("停用环境不能设为默认环境")
    _normalize_default(db, row)
    row.updated_by = actor.id
    db.commit()
    db.refresh(row)
    return row


def delete_environment(db: Session, name: str, *, actor) -> None:
    """删除未被项目引用的环境类型；项目正在使用时只能停用具体项目绑定。"""
    _require_admin(actor)
    row = get_or_404(db, name)
    if db.query(ProjectEnvironment.id).filter(ProjectEnvironment.environment_id == row.id).first() is not None:
        raise conflict("该环境类型已被项目引用，请在项目环境配置中停用对应环境")
    if row.is_default:
        raise bad_request("默认环境不能删除，请先指定新的默认环境")
    db.delete(row)
    # 删除后补一个默认项，保证执行链路始终有兜底环境。
    _normalize_default(db, None)
    db.commit()
