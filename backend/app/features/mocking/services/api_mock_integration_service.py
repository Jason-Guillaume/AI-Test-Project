"""从 API Catalog 一键创建 Mock（§二十 / §二十一）。

输入一个 api_id + service_key + 模板列表，产出：
1. MockService（同项目同 service_key 已存在则复用，不重复创建）；
2. MockEndpoint（method+path 取自 ApiInterface，已存在则复用）；
3. 每个 template 对应一个 MockScenario（NORMAL / 4xx / 5xx / EMPTY / DELAY / TIMEOUT）。

模板 → 场景配置见 ``_TEMPLATE_CONFIG``。只做结构化创建，不执行任意代码（§十三）。
service owns commit。
"""

from __future__ import annotations

import re

from sqlalchemy.orm import Session

from app.features.api_catalog.models.api_interface import ApiInterface
from app.features.mocking.models import (
    MockEndpoint,
    MockScenario,
    MockService,
)
from app.features.mocking.schemas import (
    API_MOCK_TEMPLATES,
    SCENARIO_KEY_PATTERN,
    CreateMockFromApiRequest,
    CreateMockFromApiResponse,
)
from app.features.mocking.services.access_service import require_manage_project
from app.features.mocking.services._response import service_response
from app.features.mocking.services.token_service import (
    generate_runtime_token,
    hash_token,
)
from app.core.models.identity import User
from app.core.http.errors import bad_request, not_found

# 模板 → 场景配置（§二十一）。behavior_type / status_code / body / delay_ms。
_TEMPLATE_CONFIG: dict[str, dict] = {
    "NORMAL": {"behavior_type": "STATIC_RESPONSE", "status_code": 200, "response_body": {"code": 0, "message": "ok"}},
    "BAD_REQUEST_400": {"behavior_type": "STATIC_RESPONSE", "status_code": 400, "response_body": {"code": "BAD_REQUEST", "message": "请求参数有误"}},
    "UNAUTHORIZED_401": {"behavior_type": "STATIC_RESPONSE", "status_code": 401, "response_body": {"code": "UNAUTHORIZED", "message": "未授权"}},
    "FORBIDDEN_403": {"behavior_type": "STATIC_RESPONSE", "status_code": 403, "response_body": {"code": "FORBIDDEN", "message": "禁止访问"}},
    "NOT_FOUND_404": {"behavior_type": "STATIC_RESPONSE", "status_code": 404, "response_body": {"code": "NOT_FOUND", "message": "资源不存在"}},
    "SERVER_ERROR_500": {"behavior_type": "STATIC_RESPONSE", "status_code": 500, "response_body": {"code": "INTERNAL", "message": "服务器内部错误"}},
    "EMPTY_DATA": {"behavior_type": "EMPTY_RESPONSE", "status_code": 200, "response_body": None},
    "DELAY": {"behavior_type": "DELAY_RESPONSE", "status_code": 200, "delay_ms": 1000, "response_body": {"code": 0, "message": "ok"}},
    "TIMEOUT": {"behavior_type": "TIMEOUT", "status_code": 504, "delay_ms": 5000},
}


class ApiMockIntegrationService:
    """从 API Catalog 创建 Mock。无状态，路由层复用单例。"""

    def create_from_api(
        self, db: Session, project_id: int, api_id: int,
        body: CreateMockFromApiRequest, *, actor: User,
    ) -> CreateMockFromApiResponse:
        """创建从API。"""
        project = require_manage_project(db, project_id, actor)
        key = (body.service_key or "").strip()
        if not re.fullmatch(SCENARIO_KEY_PATTERN, key):
            raise bad_request(f"service_key 必须匹配 {SCENARIO_KEY_PATTERN}")

        iface = db.get(ApiInterface, api_id)
        if iface is None or iface.project_id != project.id:
            raise not_found("接口不存在或不属于本项目")

        templates = body.templates or ["NORMAL"]
        for t in templates:
            if t not in API_MOCK_TEMPLATES:
                raise bad_request(f"未知场景模板：{t}（仅支持 {'/'.join(API_MOCK_TEMPLATES)}）")

        # 1. MockService：复用或创建。
        service = (
            db.query(MockService)
            .filter(MockService.project_id == project.id, MockService.service_key == key)
            .first()
        )
        runtime_token: str | None = None
        if service is None:
            plaintext = (body.runtime_token or "").strip() or generate_runtime_token()
            runtime_token = plaintext
            service = MockService(
                project_id=project.id,
                name=(body.service_name or iface.name or key).strip(),
                service_key=key,
                description=f"由接口 {iface.method} {iface.path} 创建",
                enabled=True,
                public_runtime=body.public_runtime,
                runtime_token_hash=hash_token(plaintext),
                created_by=actor.id,
            )
            db.add(service)
            db.flush()

        # 2. MockEndpoint：method+path 取自接口，复用或创建。
        endpoint = (
            db.query(MockEndpoint)
            .filter(
                MockEndpoint.mock_service_id == service.id,
                MockEndpoint.method == (iface.method or "GET").upper(),
                MockEndpoint.path == iface.path,
            )
            .first()
        )
        if endpoint is None:
            endpoint = MockEndpoint(
                project_id=project.id,
                mock_service_id=service.id,
                api_id=iface.id,
                name=(body.endpoint_name or iface.name or iface.path).strip(),
                method=(iface.method or "GET").upper(),
                path=iface.path,
                enabled=True,
            )
            db.add(endpoint)
            db.flush()

        # 3. 每个 template 一个 scenario（scenario_key 用模板名，已存在则跳过）。
        scenario_ids: list[int] = []
        for tpl in templates:
            skey = tpl.upper()
            existing = (
                db.query(MockScenario)
                .filter(
                    MockScenario.mock_endpoint_id == endpoint.id,
                    MockScenario.scenario_key == skey,
                )
                .first()
            )
            if existing is not None:
                scenario_ids.append(existing.id)
                continue
            cfg = _TEMPLATE_CONFIG[tpl]
            scenario = MockScenario(
                project_id=project.id,
                mock_endpoint_id=endpoint.id,
                name=tpl,
                scenario_key=skey,
                enabled=True,
                is_default=(tpl == "NORMAL"),  # NORMAL 作为默认场景。
                priority=10,
                behavior_type=cfg["behavior_type"],
                delay_ms=cfg.get("delay_ms"),
                status_code=cfg.get("status_code", 200),
                response_body=cfg.get("response_body"),
                created_by=actor.id,
            )
            db.add(scenario)
            db.flush()
            scenario_ids.append(scenario.id)

        # 把第一个场景设为服务级默认（软引用）。
        if scenario_ids and service.default_scenario_id is None:
            service.default_scenario_id = scenario_ids[0]

        db.commit()
        db.refresh(service)
        return CreateMockFromApiResponse(
            service=service_response(db, service),
            endpoint_id=endpoint.id,
            scenario_ids=scenario_ids,
            runtime_token=runtime_token,
        )


__all__ = ["ApiMockIntegrationService"]
