"""领域职责提取；保留原权限、事务和执行顺序。"""

from __future__ import annotations

from sqlalchemy.orm import Session
from app.features.api_catalog.schemas import (
    ApiChangeLogResponse,
    ApiInterfaceCreate,
    ApiInterfaceDetailResponse,
    ApiInterfaceListResponse,
    ApiInterfaceUpdate,
    ApiModuleCreate,
    ApiModuleMove,
    ApiModuleResponse,
    ApiModuleUpdate,
    ApiRelationCreate,
    ApiRelationResponse,
    ApiRequestBundle,
    ApiRequestBundleResponse,
    ApiResponsesBundle,
    ApiResponsesBundleResponse,
)
from app.core.models.identity import User
from app.features.api_catalog.services.interface_service import create_interface
from app.features.api_catalog.services.module_service import create_module
from app.features.api_catalog.services.relation_service import create_relation
from app.features.api_catalog.services.interface_service import delete_interface
from app.features.api_catalog.services.module_service import delete_module
from app.features.api_catalog.services.relation_service import delete_relation
from app.features.api_catalog.services.interface_service import get_interface
from app.features.api_catalog.services.request_service import get_request
from app.features.api_catalog.services.request_service import get_responses
from app.features.api_catalog.services.change_service import list_history
from app.features.api_catalog.services.change_service import list_import_records
from app.features.api_catalog.services.interface_service import list_interfaces
from app.features.api_catalog.services.module_service import list_modules
from app.features.api_catalog.services.relation_service import list_relations
from app.features.api_catalog.services.interface_service import move_interface
from app.features.api_catalog.services.module_service import move_module
from app.features.api_catalog.services.request_service import save_request
from app.features.api_catalog.services.request_service import save_responses
from app.features.api_catalog.services.interface_service import update_interface
from app.features.api_catalog.services.module_service import update_module


class ApiService:
    """稳定领域门面；各资源由唯一实现持有。"""


    def list_modules(self, db: Session, project_id: int, user: User) -> list[ApiModuleResponse]:
        """委托规范职责入口，保留调用契约。"""
        return list_modules(db, project_id, user)

    def create_module(self, db: Session, project_id: int, body: ApiModuleCreate, *, actor: User) -> ApiModuleResponse:
        """委托规范职责入口，保留调用契约。"""
        return create_module(db, project_id, body, actor=actor)

    def update_module(self, db: Session, module_id: int, body: ApiModuleUpdate, *, actor: User) -> ApiModuleResponse:
        """委托规范职责入口，保留调用契约。"""
        return update_module(db, module_id, body, actor=actor)

    def move_module(self, db: Session, module_id: int, body: ApiModuleMove, *, actor: User) -> ApiModuleResponse:
        """委托规范职责入口，保留调用契约。"""
        return move_module(db, module_id, body, actor=actor)

    def delete_module(self, db: Session, module_id: int, *, actor: User) -> None:
        """委托规范职责入口，保留调用契约。"""
        return delete_module(db, module_id, actor=actor)


    def list_interfaces(self, db: Session, project_id: int, user: User, *, keyword: str | None=None, method: str | None=None, module_id: int | None=None, status: str | None=None, page: int=1, page_size: int=20) -> ApiInterfaceListResponse:
        """委托规范职责入口，保留调用契约。"""
        return list_interfaces(db, project_id, user, keyword=keyword, method=method, module_id=module_id, status=status, page=page, page_size=page_size)

    def create_interface(self, db: Session, project_id: int, body: ApiInterfaceCreate, *, actor: User) -> ApiInterfaceDetailResponse:
        """委托规范职责入口，保留调用契约。"""
        return create_interface(db, project_id, body, actor=actor)

    def get_interface(self, db: Session, api_id: int, user: User) -> ApiInterfaceDetailResponse:
        """委托规范职责入口，保留调用契约。"""
        return get_interface(db, api_id, user)

    def update_interface(self, db: Session, api_id: int, body: ApiInterfaceUpdate, *, actor: User) -> ApiInterfaceDetailResponse:
        """委托规范职责入口，保留调用契约。"""
        return update_interface(db, api_id, body, actor=actor)

    def move_interface(self, db: Session, api_id: int, body, *, actor: User) -> ApiInterfaceDetailResponse:
        """委托规范职责入口，保留调用契约。"""
        return move_interface(db, api_id, body, actor=actor)

    def delete_interface(self, db: Session, api_id: int, *, actor: User) -> None:
        """委托规范职责入口，保留调用契约。"""
        return delete_interface(db, api_id, actor=actor)


    def get_request(self, db: Session, api_id: int, user: User) -> ApiRequestBundleResponse:
        """委托规范职责入口，保留调用契约。"""
        return get_request(db, api_id, user)

    def save_request(self, db: Session, api_id: int, body: ApiRequestBundle, *, actor: User) -> ApiRequestBundleResponse:
        """委托规范职责入口，保留调用契约。"""
        return save_request(db, api_id, body, actor=actor)

    def get_responses(self, db: Session, api_id: int, user: User) -> ApiResponsesBundleResponse:
        """委托规范职责入口，保留调用契约。"""
        return get_responses(db, api_id, user)

    def save_responses(self, db: Session, api_id: int, body: ApiResponsesBundle, *, actor: User) -> ApiResponsesBundleResponse:
        """委托规范职责入口，保留调用契约。"""
        return save_responses(db, api_id, body, actor=actor)

    def list_relations(self, db: Session, api_id: int, user: User) -> list[ApiRelationResponse]:
        """委托规范职责入口，保留调用契约。"""
        return list_relations(db, api_id, user)

    def create_relation(self, db: Session, api_id: int, body: ApiRelationCreate, *, actor: User) -> ApiRelationResponse:
        """委托规范职责入口，保留调用契约。"""
        return create_relation(db, api_id, body, actor=actor)

    def delete_relation(self, db: Session, relation_id: int, *, actor: User) -> None:
        """委托规范职责入口，保留调用契约。"""
        return delete_relation(db, relation_id, actor=actor)

    def list_history(self, db: Session, api_id: int, user: User, *, page: int=1, page_size: int=20) -> tuple[list[ApiChangeLogResponse], int]:
        """委托规范职责入口，保留调用契约。"""
        return list_history(db, api_id, user, page=page, page_size=page_size)

    def list_import_records(self, db: Session, project_id: int, user: User, *, page: int=1, page_size: int=20) -> tuple[list, int]:
        """委托规范职责入口，保留调用契约。"""
        return list_import_records(db, project_id, user, page=page, page_size=page_size)
