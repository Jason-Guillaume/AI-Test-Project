"""模型配置服务层：加密、校验、默认项归一化。

沿用旧项目的加密规则（Fernet + SECRET_KEY 派生），因此历史密文可继续解密。
密钥只在写入时接收，任何响应只暴露 has_api_key 与脱敏串。
"""

from __future__ import annotations

import base64
import hashlib

from cryptography.fernet import Fernet, InvalidToken
from sqlalchemy.orm import Session

from app.models.configuration import ModelConfiguration
from app.shared.config import runtime_model_config_key
from app.shared.errors import bad_request
from app.shared.notify import notify
from app.shared.roles import is_platform_admin
from app.features.model_configuration.schemas import (
    ModelConfigurationCreate,
    ModelConfigurationUpdate,
    normalize_provider,
)
from app.models.identity import User

_MAX_API_KEY_LENGTH = 1000


def _fernet() -> Fernet:
    """用独立配置或应用 SECRET_KEY 派生稳定的 Fernet 密钥。"""
    material = runtime_model_config_key()
    # 每次调用都重新派生：不缓存实例，SECRET_KEY 轮换后立刻按新密钥读写。
    digest = hashlib.sha256(material.encode("utf-8")).digest()
    return Fernet(base64.urlsafe_b64encode(digest))


def encrypt_api_key(api_key: str) -> str:
    """加密 API Key；空值返回空串，表示该模型没有配置密钥。"""
    value = (api_key or "").strip()
    if not value:
        return ""
    return _fernet().encrypt(value.encode("utf-8")).decode("ascii")


def decrypt_api_key(ciphertext: str | None) -> str:
    """解密 API Key；密钥已轮换或密文损坏时返回空串而不是抛错。"""
    if not ciphertext:
        return ""
    try:
        return _fernet().decrypt(ciphertext.encode("ascii")).decode("utf-8")
    except (InvalidToken, ValueError):
        # 降级路径：解不出来只当作「没有密钥」，不能让整个响应 500。
        return ""


def mask_api_key(api_key: str) -> str:
    """脱敏展示：保留首 3 位与末 4 位，短值全部隐藏。"""
    value = (api_key or "").strip()
    if not value:
        return ""
    if len(value) <= 8:
        return "****"
    return f"{value[:3]}****{value[-4:]}"


def validate_api_key(api_key: str | None) -> str:
    """校验密钥长度，返回原值。"""
    value = (api_key or "").strip()
    if len(value) > _MAX_API_KEY_LENGTH:
        raise bad_request("API Key 过长")
    return value


def normalize_api_base(api_base: str) -> str:
    """规范化接口根地址：只保留 http(s)，去掉尾部斜杠。"""
    value = (api_base or "").strip().rstrip("/")
    if not value.startswith(("http://", "https://")):
        raise bad_request("API Base 必须以 http:// 或 https:// 开头")
    if not value:
        raise bad_request("API Base 不能为空")
    return value


def response_for(row: ModelConfiguration) -> dict:
    """构建白名单响应，绝不暴露数据库密文或真实密钥。"""
    # 只在内存里解一次算脱敏串，解出的明文绝不进入响应体。
    api_key = decrypt_api_key(row.api_key_encrypted)
    return {
        "id": row.id,
        "domain_id": row.domain_id,
        "label": row.label,
        "provider": row.provider,
        "api_base": row.api_base,
        "model_name": row.model_name,
        "temperature": row.temperature,
        "max_tokens": row.max_tokens,
        "timeout": row.timeout,
        "cost_per_1k_input": row.cost_per_1k_input,
        "cost_per_1k_output": row.cost_per_1k_output,
        "is_enabled": bool(row.is_enabled),
        "is_default": bool(row.is_default),
        "fallback_model_ids": list(row.fallback_model_ids or []),
        "sort_order": row.sort_order,
        # 密钥状态只回布尔位与脱敏前缀，明文与 api_key_encrypted 都永不回传。
        "has_api_key": bool(api_key),
        "masked_api_key": mask_api_key(api_key),
        "created_by": row.created_by,
        "created_at": row.created_at,
        "updated_at": row.updated_at,
    }


def get_or_404(db: Session, config_id: int) -> ModelConfiguration:
    """按 ID 取模型配置，不存在抛 400（平台资源不区分「不存在」与「越权」）。"""
    row = db.get(ModelConfiguration, config_id)
    if row is None:
        raise bad_request("模型配置不存在")
    return row


def _require_admin(actor: User) -> None:
    """模型配置属于平台级资源，仅平台管理员可读写。"""
    if not is_platform_admin(actor):
        from app.shared.errors import forbidden

        raise forbidden("仅管理员可执行该操作")


def _unique_domain(db: Session, domain_id: str, *, exclude_id: int | None = None) -> None:
    """校验 domain_id 全局唯一；更新场景排除自身以免误判重复。"""
    query = db.query(ModelConfiguration).filter(ModelConfiguration.domain_id == domain_id)
    if exclude_id is not None:
        query = query.filter(ModelConfiguration.id != exclude_id)
    if query.first() is not None:
        raise bad_request("该 domain_id 已存在")


def _validate_fallback_models(db: Session, model_ids: list[int], *, primary_id: int | None = None) -> list[int]:
    """验证备用模型引用存在、保序且不重复，避免配置错误形成无效路由。"""
    ids = list(model_ids or [])
    if len(ids) > 3 or len(ids) != len(set(ids)) or (primary_id is not None and primary_id in ids):
        raise bad_request("备用模型最多三个，不能重复或引用自身")
    found = {row.id for row in db.query(ModelConfiguration.id).filter(ModelConfiguration.id.in_(ids or [-1])).all()}
    if found != set(ids):
        raise bad_request("备用模型配置不存在")
    return ids


def _validate_payload(
    *,
    domain_id: str,
    api_base: str,
    is_enabled: bool,
    is_default: bool,
    has_api_key: bool,
) -> tuple[str, str]:
    """集中校验组合约束，返回规范化后的 domain_id 与 api_base。"""
    domain_id = domain_id.strip()
    if not domain_id:
        raise bad_request("domain_id 不能为空")
    api_base = normalize_api_base(api_base)
    if is_enabled and not has_api_key:
        raise bad_request("启用模型前必须填写 API Key")
    if is_default and not is_enabled:
        raise bad_request("停用的模型不能设为默认模型")
    return domain_id, api_base


def _normalize_defaults(db: Session, keep: ModelConfiguration | None) -> None:
    """保证至多一个默认模型；没有默认项时把排序最靠前的启用模型提上来。

    默认模型是「未显式指定」时的兜底，两个默认项会让调用结果取决于查询顺序。

    Args:
        db: 数据库会话。
        keep: 期望保留为默认的模型；为 None 时按排序重新分配默认位。
    """
    if keep is not None and keep.is_enabled:
        for row in db.query(ModelConfiguration).filter(ModelConfiguration.is_default.is_(True)).all():
            if row.id != keep.id:
                row.is_default = False
        keep.is_default = True
        return

    rows = (
        db.query(ModelConfiguration)
        .filter(ModelConfiguration.is_enabled.is_(True))
        .order_by(ModelConfiguration.sort_order.asc(), ModelConfiguration.id.asc())
        .all()
    )
    fallback = rows[0] if rows else None
    for row in db.query(ModelConfiguration).all():
        row.is_default = bool(fallback and row.id == fallback.id)


def create_configuration(db: Session, body: ModelConfigurationCreate, *, actor: User) -> ModelConfiguration:
    """新增模型配置。"""
    _require_admin(actor)
    api_key = validate_api_key(body.api_key)
    # 明确要求启用但没有密钥时直接拒绝，而不是偷偷存成停用状态——
    # 后者会让管理员以为模型已生效，实际执行链路永远选不到它。
    if body.is_enabled and not api_key:
        raise bad_request("启用状态的模型必须配置 API Key")
    is_enabled = bool(body.is_enabled and api_key)
    domain_id, api_base = _validate_payload(
        domain_id=body.domain_id,
        api_base=body.api_base,
        is_enabled=is_enabled,
        is_default=body.is_default,
        has_api_key=bool(api_key),
    )
    _unique_domain(db, domain_id)

    row = ModelConfiguration(
        domain_id=domain_id,
        label=body.label.strip(),
        provider=normalize_provider(body.provider),
        api_base=api_base,
        api_key_encrypted=encrypt_api_key(api_key),
        model_name=body.model_name.strip(),
        temperature=body.temperature,
        max_tokens=body.max_tokens,
        timeout=body.timeout,
        cost_per_1k_input=body.cost_per_1k_input,
        cost_per_1k_output=body.cost_per_1k_output,
        is_enabled=is_enabled,
        is_default=False,
        fallback_model_ids=_validate_fallback_models(db, body.fallback_model_ids),
        sort_order=body.sort_order,
        created_by=actor.id,
    )
    db.add(row)
    db.flush()
    _validate_payload(
        domain_id=row.domain_id,
        api_base=row.api_base,
        is_enabled=row.is_enabled,
        is_default=body.is_default,
        has_api_key=bool(api_key),
    )
    _normalize_defaults(db, row if body.is_default else None)
    db.commit()
    db.refresh(row)
    return row


def update_configuration(
    db: Session, config_id: int, body: ModelConfigurationUpdate, *, actor: User
) -> ModelConfiguration:
    """更新模型配置；密钥为空表示保留原值。"""
    _require_admin(actor)
    row = get_or_404(db, config_id)

    # exclude_unset：前端「不传」和「传空串」语义不同——只有非空才覆盖密钥。
    data = body.model_dump(exclude_unset=True)
    if not data:
        return row
    if data.get("fallback_model_ids", []) is None:
        raise bad_request("备用模型列表不能为 null")

    if "provider" in data and data["provider"] is not None:
        data["provider"] = normalize_provider(data["provider"])
    if "api_base" in data and data["api_base"] is not None:
        data["api_base"] = data["api_base"].strip()
    if "domain_id" in data and data["domain_id"] is not None:
        data["domain_id"] = data["domain_id"].strip()
        _unique_domain(db, data["domain_id"], exclude_id=row.id)
    for text_field in ("label", "model_name"):
        if data.get(text_field):
            data[text_field] = data[text_field].strip()

    next_api_key: str | None = None
    if data.get("api_key"):
        next_api_key = validate_api_key(data.pop("api_key"))
    elif data.get("api_key") == "":
        data.pop("api_key")

    for field, value in data.items():
        setattr(row, field, value)

    if "fallback_model_ids" in data and data["fallback_model_ids"] is not None:
        row.fallback_model_ids = _validate_fallback_models(db, data["fallback_model_ids"], primary_id=row.id)

    # 未替换密钥时沿用库里的旧密文判定 has_api_key。
    has_api_key = bool(next_api_key) if next_api_key is not None else bool(decrypt_api_key(row.api_key_encrypted))
    _validate_payload(
        domain_id=row.domain_id,
        api_base=row.api_base,
        is_enabled=bool(row.is_enabled),
        is_default=bool(row.is_default),
        has_api_key=has_api_key,
    )
    if next_api_key is not None:
        row.api_key_encrypted = encrypt_api_key(next_api_key)

    _normalize_defaults(db, row if row.is_default else None)
    db.commit()
    db.refresh(row)
    return row


def delete_configuration(db: Session, config_id: int, *, actor: User) -> None:
    """删除模型配置。"""
    _require_admin(actor)
    row = get_or_404(db, config_id)
    if row.is_default:
        raise bad_request("默认模型不能删除，请先指定新的默认模型")
    db.delete(row)
    # 删除后重新分配默认位，保证未显式指定模型的调用总有兜底。
    _normalize_defaults(db, None)
    db.commit()


def set_default(db: Session, config_id: int, *, actor: User) -> ModelConfiguration:
    """把指定模型设为默认模型；被设为默认的模型必须处于启用状态。"""
    _require_admin(actor)
    row = get_or_404(db, config_id)
    if not row.is_enabled:
        raise bad_request("停用的模型不能设为默认模型")
    _normalize_defaults(db, row)
    db.commit()
    db.refresh(row)
    return row
