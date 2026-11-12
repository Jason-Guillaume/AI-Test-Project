"""被测目标出站策略协调。

解析 HTTP 目标并通过 projects 的公开服务查询显式启用的项目白名单；策略不自动放行私网地址。
"""

from __future__ import annotations

import ipaddress
from dataclasses import dataclass
from urllib.parse import urlsplit

from sqlalchemy.orm import Session

from app.core.models.project import ProjectOutboundTarget
from app.platform.projects.services.outbound_service import find_enabled_outbound_target


@dataclass(frozen=True)
class OutboundTargetDecision:
    """返回白名单目标及供业务执行器显示的拒绝原因。"""

    target: ProjectOutboundTarget | None
    private_address: bool
    rejection_message: str | None


def is_private_ip(host: str) -> bool:
    """判断主机是否为环回、私有、保留、链路本地或未指定 IP 地址。"""
    try:
        address = ipaddress.ip_address(host)
    except ValueError:
        return False
    return (
        address.is_loopback
        or address.is_link_local
        or address.is_reserved
        or address.is_private
        or address.is_unspecified
    )


def resolve_project_outbound_target(
    db: Session,
    url: str,
    project_id: int,
) -> OutboundTargetDecision:
    """解析目标四元组并查找启用白名单项；非法端口继续抛出 ValueError。"""
    parsed = urlsplit(url)
    scheme = (parsed.scheme or "http").lower()
    host = (parsed.hostname or "").lower()
    # 保持 urlsplit 对非法端口的 ValueError，让调试与执行适配器分别保留原错误语义。
    port = parsed.port or (443 if scheme == "https" else 80)
    private_address = is_private_ip(host)
    target = find_enabled_outbound_target(db, project_id, scheme, host, port)
    if target is not None:
        return OutboundTargetDecision(target, private_address, None)
    if private_address:
        message = f"目标地址 {host}:{port} 为私网/环回地址，不在出站白名单"
    else:
        message = "目标不在项目出站白名单"
    return OutboundTargetDecision(None, private_address, message)


__all__ = ["OutboundTargetDecision", "is_private_ip", "resolve_project_outbound_target"]
