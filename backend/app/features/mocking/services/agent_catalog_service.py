"""Mock 域的 Agent 安全查询投影。"""

from __future__ import annotations

from typing import Any

from sqlalchemy.orm import Session

from app.features.mocking.models import MockEndpoint, MockScenario, MockService
from app.platform.projects.services.access_service import get_project_or_404
from app.core.models.identity import User
from app.core.http.errors import not_found


def list_mock_services(db: Session, project_id: int, user: User) -> list[dict]:
    """列出本项目已配置的 Mock 依赖服务（字段刻意白名单化，不含 Token 相关列）。"""
    get_project_or_404(db, project_id, user)
    rows = (
        db.query(MockService)
        .filter(MockService.project_id == project_id)
        .order_by(MockService.service_key.asc())
        .all()
    )
    return [
        {
            "service_id": r.id,
            "service_key": r.service_key,
            "name": r.name,
            "enabled": bool(r.enabled),
            "description": r.description,
        }
        for r in rows
    ]


def list_mock_scenarios(
    db: Session,
    project_id: int,
    user: User,
    *,
    mock_service_id: int | None = None,
    mock_endpoint_id: int | None = None,
) -> list[dict]:
    """列出可被 ``required_mocks`` 引用的 Mock 场景（含 service/endpoint 归属与行为类型）。

    ``service_key`` / ``scenario_key`` / ``mock_scenario_id`` / ``method`` / ``path``
    是 LLM 生成用例所需的最小信息集；不带响应体内容，结构键名由 ``get_mock_scenario``
    按需拉取，避免整库灌入。
    """
    get_project_or_404(db, project_id, user)
    q = db.query(MockScenario, MockEndpoint).join(
        MockEndpoint, MockScenario.mock_endpoint_id == MockEndpoint.id
    )
    q = q.filter(MockScenario.project_id == project_id)
    if mock_service_id is not None:
        q = q.filter(MockEndpoint.mock_service_id == mock_service_id)
    if mock_endpoint_id is not None:
        q = q.filter(MockEndpoint.id == mock_endpoint_id)
    rows = q.order_by(MockScenario.priority.desc(), MockScenario.id.asc()).all()

    service_names: dict[int, tuple[str, str]] = {}
    service_ids = {e.mock_service_id for _, e in rows}
    if service_ids:
        for row in (
            db.query(MockService.id, MockService.service_key, MockService.name)
            .filter(MockService.id.in_(service_ids)).all()
        ):
            service_names[row.id] = (row.service_key, row.name)

    out: list[dict] = []
    for sc, ep in rows:
        key, name = service_names.get(ep.mock_service_id, ("", ""))
        out.append({
            "mock_scenario_id": sc.id,
            "scenario_key": sc.scenario_key,
            "name": sc.name,
            "description": sc.description,
            "mock_service_id": ep.mock_service_id,
            "service_key": key,
            "service_name": name,
            "mock_endpoint_id": ep.id,
            "method": ep.method,
            "path": ep.path,
            "api_id": ep.api_id,
            "behavior_type": sc.behavior_type,
            "status_code": sc.status_code,
            "delay_ms": sc.delay_ms,
            "is_default": bool(sc.is_default),
            "enabled": bool(sc.enabled),
        })
    return out


def get_mock_scenario(db: Session, scenario_id: int, project_id: int, user: User) -> dict:
    """取单个 Mock 场景的行为结构（只给结构，不给取值）。

    响应体 / 响应模板只回传顶层键名与占位符文本的存在性，不回传字段值：用例生成
    需要知道「有哪些字段」来判断断言口径，不需要真实数据。
    """
    get_project_or_404(db, project_id, user)
    sc = db.get(MockScenario, scenario_id)
    if sc is None or sc.project_id != project_id:
        raise not_found("Mock 场景不存在")
    endpoint = db.get(MockEndpoint, sc.mock_endpoint_id)
    service = db.get(MockService, endpoint.mock_service_id) if endpoint else None
    return {
        "mock_scenario_id": sc.id,
        "scenario_key": sc.scenario_key,
        "name": sc.name,
        "description": sc.description,
        "mock_service_id": endpoint.mock_service_id if endpoint else None,
        "service_key": service.service_key if service else None,
        "mock_endpoint_id": sc.mock_endpoint_id,
        "method": endpoint.method if endpoint else None,
        "path": endpoint.path if endpoint else None,
        "api_id": endpoint.api_id if endpoint else None,
        "behavior_type": sc.behavior_type,
        "status_code": sc.status_code,
        "delay_ms": sc.delay_ms,
        "priority": sc.priority,
        "is_default": bool(sc.is_default),
        "enabled": bool(sc.enabled),
        "response_headers_keys": _top_keys(sc.response_headers),
        "response_body_keys": _top_keys(sc.response_body),
        "has_response_template": sc.response_template is not None,
        "matcher_count": _matcher_count(db, sc.id),
    }


def find_scenario_for_api(db: Session, api_id: int, project_id: int, user: User) -> dict:
    """按 API Catalog 接口 ID 反查已配置的 Mock 场景（§二十 一键创建后的引用入口）。

    返回 ``{"api_id": ..., "scenarios": [...]}``；接口未配置 Mock 时 scenarios 为空，
    不 404（「没有」与「不存在」在生成用例时语义不同）。
    """
    get_project_or_404(db, project_id, user)
    rows = (
        db.query(MockScenario, MockEndpoint)
        .join(MockEndpoint, MockScenario.mock_endpoint_id == MockEndpoint.id)
        .filter(
            MockScenario.project_id == project_id,
            MockEndpoint.api_id == api_id,
            MockEndpoint.api_id.isnot(None),
        )
        .order_by(MockScenario.priority.desc(), MockScenario.id.asc())
        .all()
    )
    return {
        "api_id": api_id,
        "scenarios": [
            {
                "mock_scenario_id": sc.id,
                "scenario_key": sc.scenario_key,
                "name": sc.name,
                "mock_endpoint_id": ep.id,
                "method": ep.method,
                "path": ep.path,
                "behavior_type": sc.behavior_type,
                "status_code": sc.status_code,
                "is_default": bool(sc.is_default),
                "enabled": bool(sc.enabled),
            }
            for sc, ep in rows
        ],
    }


def _matcher_count(db: Session, scenario_id: int) -> int:
    """统计匹配器数量。"""
    from app.features.mocking.models import MockMatcher

    return (
        db.query(MockMatcher).filter(
            MockMatcher.scenario_id == scenario_id, MockMatcher.enabled.is_(True)
        ).count()
    )


def _top_keys(value: Any) -> list[str]:
    """取 JSON 顶层键名（Object 键；Array 返回 []；其它返回 []），不回传取值。"""
    if isinstance(value, dict):
        return [str(k) for k in value.keys()]
    return []

__all__ = ["list_mock_services", "list_mock_scenarios", "get_mock_scenario", "find_scenario_for_api"]
