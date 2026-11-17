"""自动化测试中心业务服务。

负责接入配置、执行编排、报告接收和飞书通知；外部 CI 调用委托给 Provider。
事务在本服务提交，路由层不写库。
"""

from __future__ import annotations

import hashlib
import hmac
import json
import logging
import re
import secrets
import shutil
from contextlib import contextmanager
from datetime import datetime, timedelta
from typing import Any, Iterator

from sqlalchemy import and_, or_
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.core.config import settings
from app.core.http.errors import bad_request, conflict, forbidden, not_found
from app.core.http.pagination import paginate
from app.core.models.identity import User
from app.core.security.crypto import decrypt_secret, encrypt_secret
from app.features.automation_center.models.entities import (
    AutomationArtifact,
    AutomationCallbackReceipt,
    AutomationExecution,
    AutomationExecutionIdempotency,
    AutomationIntegrationConfig,
    AutomationPipeline,
    AutomationProject,
    AutomationReport,
    AutomationReportGrant,
)
from app.features.automation_center.providers.base import AutomationProvider, ProviderError, ProviderExecution
from app.features.automation_center.providers.factory import provider_factory
from app.features.automation_center.schemas import (
    AutomationProjectCreate,
    AutomationProjectListResponse,
    AutomationProjectResponse,
    AutomationProjectUpdate,
    CallbackResponse,
    ConnectionTestResponse,
    ConsoleLogResponse,
    ExecutionListResponse,
    ExecutionResponse,
    ExecutionTrigger,
    IntegrationCreate,
    IntegrationListResponse,
    IntegrationResponse,
    IntegrationUpdate,
    DaguDagListResponse,
    ReportCompareResponse,
    ReportGrantResponse,
    ReportListResponse,
    ReportResponse,
)
from app.features.automation_center.services.card import build_automation_card
from app.features.automation_center.services import storage
from app.features.automation_center.services.stats import (
    TERMINAL_STATUSES,
    apply_test_outcome,
    map_pipeline_status,
    pass_rate,
)
from app.platform.notifications.models.channel import NotificationChannel
from app.platform.notifications.services.feishu_service import FeishuNotificationService
from app.platform.projects.services.access_service import get_project_or_404, require_writable_project
from app.core.security.roles import PROJECT_ROLE_EDITOR, has_project_role, project_role_for

logger = logging.getLogger(__name__)
APPROVED_DAGU_DAGS = frozenset({"automation-pytest-allure"})
_IDEMPOTENCY_TTL = timedelta(hours=24)
_ENV_KEY = re.compile(r"[A-Za-z_][A-Za-z0-9_]{0,63}")
_SECRET_KEY = re.compile(r"(?i)(secret|token|password|webhook|credential|api[_-]?key|private[_-]?key)")
_SECRET_VALUE = re.compile(
    r"(?i)(secret|token|password|webhook_url|credential|api[_-]?key|private[_-]?key)\s*[:=]\s*\S+",
)
_PAT = re.compile(r"pt-[A-Za-z0-9_*\-]{6,}")


def sign_callback(
    secret: str, timestamp: str, callback_key: str, idempotency_key: str,
    report_sha: str, metadata_sha: str,
) -> str:
    """计算回调签名。五段用换行连接，避免字段拼接后产生歧义。"""
    canonical = "\n".join([timestamp, callback_key, idempotency_key, report_sha, metadata_sha])
    return hmac.new(secret.encode("utf-8"), canonical.encode("utf-8"), hashlib.sha256).hexdigest()


def _sha(data: bytes) -> str:
    """摘要工具。空内容也有稳定摘要，签名字段不能省略。"""
    return hashlib.sha256(data).hexdigest()


def _redact(text: str) -> str:
    """去掉日志里的令牌和形如 secret= 的赋值，再截断入库。"""
    cleaned = _PAT.sub("pt-***", text.replace("\x00", ""))
    cleaned = _SECRET_VALUE.sub(lambda match: f"{match.group(1)}=***", cleaned)
    return cleaned[:20000]


class AutomationCenterService:
    """自动化项目、执行和报告的统一服务。"""

    def __init__(self) -> None:
        self._feishu = FeishuNotificationService()

    # ---------------------------------------------------------------- 接入配置

    def list_integrations(
        self, db: Session, project_id: int, actor: User, *, page: int, page_size: int,
    ) -> IntegrationListResponse:
        """列出当前业务项目的 CI 接入配置。"""
        get_project_or_404(db, project_id, actor)
        query = db.query(AutomationIntegrationConfig).filter_by(project_id=project_id).order_by(
            AutomationIntegrationConfig.id.desc(),
        )
        page_data = paginate(query, page, page_size)
        return IntegrationListResponse(
            items=[self._integration_response(row) for row in page_data["items"]],
            total=page_data["total"], page=page_data["page"], page_size=page_data["page_size"],
        )

    def create_integration(
        self, db: Session, project_id: int, body: IntegrationCreate, actor: User,
    ) -> IntegrationResponse:
        """保存接入配置。明文凭证在入库前加密。"""
        require_writable_project(db, project_id, actor)
        if body.provider_type == "DAGU":
            self._require_ci_admin(db, project_id, actor)
        row = AutomationIntegrationConfig(
            project_id=project_id,
            name=body.name.strip(),
            provider_type=body.provider_type,
            enabled=body.enabled,
            api_base_url=body.api_base_url or "",
            organization_id=body.organization_id or "",
            deployment=body.deployment,
            access_token_encrypted=encrypt_secret(body.access_token),
            dagu_base_url=body.dagu_base_url,
            dagu_api_key_encrypted=encrypt_secret(body.dagu_api_key),
            dagu_api_key_configured=bool(body.dagu_api_key),
            callback_key=secrets.token_urlsafe(18),
            callback_secret_encrypted=encrypt_secret(body.callback_secret),
            default_timeout_seconds=body.default_timeout_seconds,
            created_by=actor.id,
        )
        db.add(row)
        self._commit_unique(db, "同名接入配置已存在")
        db.refresh(row)
        return self._integration_response(row)

    def update_integration(
        self, db: Session, config_id: int, body: IntegrationUpdate, actor: User,
    ) -> IntegrationResponse:
        """更新接入配置。空令牌表示不替换原密文。"""
        row = self._config_for_write(db, config_id, actor)
        if body.provider_type is not None and body.provider_type != row.provider_type:
            raise bad_request("已有接入配置不能切换执行平台，请新建对应类型的配置")
        if row.provider_type == "LEGACY":
            raise bad_request("历史执行平台配置已停用，请新建 Dagu 或云效接入")
        if row.provider_type == "DAGU":
            self._require_ci_admin(db, row.project_id, actor)
        if body.name is not None:
            row.name = body.name.strip()
        if row.provider_type == "YUNXIAO" and body.api_base_url is not None:
            row.api_base_url = body.api_base_url
        if row.provider_type == "YUNXIAO" and body.organization_id is not None:
            row.organization_id = body.organization_id
        if row.provider_type == "YUNXIAO" and body.deployment is not None:
            row.deployment = body.deployment
        if body.enabled is not None:
            row.enabled = body.enabled
        if row.provider_type == "DAGU":
            if body.dagu_base_url is not None:
                row.dagu_base_url = body.dagu_base_url
            if body.dagu_api_key:
                if len(body.dagu_api_key) < 8:
                    raise bad_request("Dagu API Key 过短")
                row.dagu_api_key_encrypted = encrypt_secret(body.dagu_api_key)
                row.dagu_api_key_configured = True
        if body.default_timeout_seconds is not None:
            row.default_timeout_seconds = body.default_timeout_seconds
        if row.provider_type == "YUNXIAO" and body.access_token:
            if len(body.access_token) < 8:
                raise bad_request("云效访问令牌过短")
            row.access_token_encrypted = encrypt_secret(body.access_token)
        if body.callback_secret:
            if len(body.callback_secret) < 8:
                raise bad_request("回调密钥过短")
            row.callback_secret_encrypted = encrypt_secret(body.callback_secret)
        if row.provider_type == "YUNXIAO":
            self._require_organization(row)
        self._commit_unique(db, "同名接入配置已存在")
        db.refresh(row)
        return self._integration_response(row)

    def delete_integration(self, db: Session, config_id: int, actor: User) -> None:
        """将未被活跃自动化项目引用的接入配置移入回收站。"""
        from app.lifecycle.service import delete_resource

        row = (
            db.query(AutomationIntegrationConfig).execution_options(include_deleted=True)
            .filter(AutomationIntegrationConfig.id == config_id).first()
        )
        if row is None:
            raise not_found("接入配置不存在")
        require_writable_project(db, row.project_id, actor)
        if row.provider_type == "DAGU":
            self._require_ci_admin(db, row.project_id, actor)
        delete_resource(db, "automation_integration", config_id, actor=actor, project_id=row.project_id)

    def rotate_callback_key(self, db: Session, config_id: int, actor: User) -> IntegrationResponse:
        """更换回调标识。旧流水线在更新地址前不能再回传。"""
        row = self._config_for_write(db, config_id, actor)
        if row.provider_type == "DAGU":
            self._require_ci_admin(db, row.project_id, actor)
        row.callback_key = secrets.token_urlsafe(18)
        db.commit()
        db.refresh(row)
        return self._integration_response(row)

    def test_connection(
        self, db: Session, config_id: int, actor: User, pipeline_id: str | None = None,
    ) -> ConnectionTestResponse:
        """通过绑定的 Provider 验证凭据和流水线标识。"""
        row = self._config_for_write(db, config_id, actor)
        if row.provider_type == "DAGU":
            self._require_ci_admin(db, row.project_id, actor)
        try:
            with self._provider_session(row) as provider:
                result = provider.test_connection(pipeline_id)
        except ProviderError as exc:
            raise bad_request(str(exc)) from exc
        return ConnectionTestResponse(
            ok=result.ok, message=result.message, sample_run_count=result.sample_run_count,
            service_version=result.service_version,
        )

    def list_dagu_dags(self, db: Session, config_id: int, actor: User) -> DaguDagListResponse:
        """List readable Dagu DAGs for an automation project binding."""
        config = self._config_for_read(db, config_id, actor)
        if config.provider_type != "DAGU":
            raise bad_request("此接入配置不是 Dagu")
        self._require_ci_admin(db, config.project_id, actor)
        try:
            with self._provider_session(config) as provider:
                items = provider.list_dags()
        except ProviderError as exc:
            raise bad_request(str(exc)) from exc
        normalized = []
        for item in items:
            dag = item.get("dag") if isinstance(item.get("dag"), dict) else {}
            name = str(
                item.get("fileName") or item.get("file_name") or item.get("name")
                or item.get("dagName") or item.get("dag_name") or dag.get("name") or ""
            ).strip()
            if name and name in APPROVED_DAGU_DAGS:
                description = item.get("description") or dag.get("description") or ""
                normalized.append({"name": name, "description": str(description)[:500]})
        return DaguDagListResponse(items=normalized)

    # ---------------------------------------------------------------- 自动化项目

    def list_projects(
        self, db: Session, project_id: int, actor: User, *, page: int, page_size: int, keyword: str | None,
    ) -> AutomationProjectListResponse:
        """列出自动化项目，并附上最近一次执行状态。"""
        get_project_or_404(db, project_id, actor)
        query = db.query(AutomationProject).filter_by(project_id=project_id)
        if keyword and keyword.strip():
            query = query.filter(AutomationProject.name.ilike(f"%{keyword.strip()}%"))
        query = query.order_by(AutomationProject.id.desc())
        page_data = paginate(query, page, page_size)
        return AutomationProjectListResponse(
            items=[self._project_response(db, row) for row in page_data["items"]],
            total=page_data["total"], page=page_data["page"], page_size=page_data["page_size"],
        )

    def create_project(
        self, db: Session, project_id: int, body: AutomationProjectCreate, actor: User,
    ) -> AutomationProjectResponse:
        """创建自动化项目并绑定默认流水线。"""
        require_writable_project(db, project_id, actor)
        config = self._owned_config(db, project_id, body.integration_config_id)
        self._validate_resource_id(config.provider_type, body.pipeline_id)
        pipeline_params = self._public_params(body.pipeline_params)
        if config.provider_type == "DAGU":
            self._validate_repository_url(body.repository_url)
            self._validate_run_options(
                body.default_branch, body.default_environment, body.pytest_args, body.test_tags, body.test_scope,
            )
        self._ensure_channel(db, project_id, body.notification_channel_id)
        row = AutomationProject(
            project_id=project_id,
            integration_config_id=config.id,
            name=body.name.strip(),
            description=body.description,
            repository_url=body.repository_url.strip(),
            repository_id=body.repository_id.strip(),
            default_branch=body.default_branch.strip() or "master",
            default_environment=body.default_environment.strip(),
            pytest_args=body.pytest_args.strip(),
            test_tags=body.test_tags.strip(),
            test_scope=body.test_scope.strip(),
            pipeline_params=pipeline_params,
            timeout_seconds=body.timeout_seconds,
            notification_channel_id=body.notification_channel_id,
            notify_condition=body.notify_condition,
            created_by=actor.id,
        )
        db.add(row)
        try:
            db.flush()
        except IntegrityError as exc:
            db.rollback()
            raise conflict("同名自动化项目已存在") from exc
        db.add(AutomationPipeline(
            automation_project_id=row.id,
            name=body.pipeline_name.strip() or body.pipeline_id,
            pipeline_id=body.pipeline_id,
            is_default=True,
        ))
        db.commit()
        db.refresh(row)
        return self._project_response(db, row)

    def update_project(
        self, db: Session, automation_project_id: int, body: AutomationProjectUpdate, actor: User,
    ) -> AutomationProjectResponse:
        """更新自动化项目和默认流水线绑定。"""
        row = self._automation_for(db, automation_project_id, actor, write=True)
        if body.integration_config_id is not None:
            self._owned_config(db, row.project_id, body.integration_config_id)
            row.integration_config_id = body.integration_config_id
        bound_config = db.get(AutomationIntegrationConfig, row.integration_config_id)
        if bound_config is None:
            raise not_found("接入配置不存在")
        if bound_config.provider_type == "LEGACY":
            raise bad_request("旧执行平台接入已停用，请先绑定 Dagu 或云效接入")
        bound_pipeline = self._default_pipeline(db, row)
        self._validate_resource_id(
            bound_config.provider_type,
            body.pipeline_id if body.pipeline_id is not None else bound_pipeline.pipeline_id,
        )
        for field in (
            "name", "description", "repository_url", "repository_id", "default_branch",
            "default_environment", "pytest_args", "test_tags", "test_scope",
        ):
            value = getattr(body, field)
            if value is not None:
                setattr(row, field, value.strip())
        if body.pipeline_params is not None:
            row.pipeline_params = self._public_params(body.pipeline_params)
        if body.timeout_seconds is not None:
            row.timeout_seconds = body.timeout_seconds
        if body.notify_condition is not None:
            row.notify_condition = body.notify_condition
        if body.enabled is not None:
            row.enabled = body.enabled
        if body.clear_notification_channel:
            row.notification_channel_id = None
        elif body.notification_channel_id is not None:
            self._ensure_channel(db, row.project_id, body.notification_channel_id)
            row.notification_channel_id = body.notification_channel_id
        if body.pipeline_id is not None:
            config = db.get(AutomationIntegrationConfig, row.integration_config_id)
            if config is None:
                raise not_found("接入配置不存在")
            self._validate_resource_id(config.provider_type, body.pipeline_id)
            pipeline = self._default_pipeline(db, row)
            pipeline.pipeline_id = body.pipeline_id
            if body.pipeline_name is not None:
                pipeline.name = body.pipeline_name.strip() or body.pipeline_id
        effective_config = db.get(AutomationIntegrationConfig, row.integration_config_id)
        if effective_config is not None and effective_config.provider_type == "DAGU":
            self._validate_repository_url(row.repository_url)
            self._validate_run_options(
                row.default_branch, row.default_environment, row.pytest_args, row.test_tags, row.test_scope,
            )
        self._commit_unique(db, "同名自动化项目或流水线已存在")
        db.refresh(row)
        return self._project_response(db, row)

    def delete_project(self, db: Session, automation_project_id: int, actor: User) -> None:
        """将自动化项目移入回收站。执行记录、报告文件和流水线绑定都保留。"""
        from app.lifecycle.service import delete_resource

        row = (
            db.query(AutomationProject).execution_options(include_deleted=True)
            .filter(AutomationProject.id == automation_project_id).first()
        )
        if row is None:
            raise not_found("自动化项目不存在")
        require_writable_project(db, row.project_id, actor)
        delete_resource(
            db, "automation_project", automation_project_id, actor=actor, project_id=row.project_id,
        )

    def verify_project(self, db: Session, automation_project_id: int, actor: User) -> ConnectionTestResponse:
        """按项目绑定的默认流水线做一次真实连通性检查。"""
        row = self._automation_for(db, automation_project_id, actor, write=True)
        config = db.get(AutomationIntegrationConfig, row.integration_config_id)
        pipeline = self._default_pipeline(db, row)
        if config is None:
            raise not_found("接入配置不存在")
        return self.test_connection(db, config.id, actor, pipeline.pipeline_id)

    # ---------------------------------------------------------------- 执行

    def trigger(
        self, db: Session, automation_project_id: int, body: ExecutionTrigger, actor: User,
    ) -> ExecutionResponse:
        """创建执行记录。Dagu 先提交本地记录和稳定运行 ID，再入队。"""
        project = self._automation_for(db, automation_project_id, actor, write=True)
        if not project.enabled:
            raise bad_request("自动化项目已停用")
        config = db.get(AutomationIntegrationConfig, project.integration_config_id)
        if config is None:
            raise not_found("接入配置不存在")
        if config.provider_type == "LEGACY":
            raise bad_request("历史执行平台已停用，不能发起新的执行")
        if not config.enabled:
            raise bad_request("CI 接入配置已停用")
        pipeline = self._pipeline_for_trigger(db, project, body.pipeline_id)
        self._validate_resource_id(config.provider_type, pipeline.pipeline_id)
        if body.idempotency_key and not re.fullmatch(r"[A-Za-z0-9_.:-]{8,120}", body.idempotency_key):
            raise bad_request("幂等键不合法")
        fingerprint = self._request_fingerprint(body, project, pipeline.pipeline_id)
        existing = self._existing_idempotent_execution(db, project.id, body.idempotency_key, fingerprint)
        if existing is not None:
            return self._execution_response(db, existing)
        self._purge_expired_idempotency(db)
        execution = AutomationExecution(
            project_id=project.project_id,
            automation_project_id=project.id,
            pipeline_binding_id=pipeline.id,
            integration_config_id=config.id,
            provider_type=config.provider_type,
            external_pipeline_id=pipeline.pipeline_id,
            trigger_source="MANUAL",
            status="PENDING",
            dispatch_state="PENDING" if config.provider_type == "DAGU" else "CONFIRMED",
            branch=(body.branch if body.branch is not None else project.default_branch).strip(),
            environment_name=(body.environment_name if body.environment_name is not None else project.default_environment).strip(),
            pytest_args=(body.pytest_args if body.pytest_args is not None else project.pytest_args).strip(),
            test_tags=(body.test_tags if body.test_tags is not None else project.test_tags).strip(),
            test_scope=(body.test_scope if body.test_scope is not None else project.test_scope).strip(),
            notify_status="WAITING",
            created_by=actor.id,
        )
        db.add(execution)
        db.flush()
        params = self._execution_params(config, project, pipeline, execution)
        execution.run_params = params
        execution.timeout_at = datetime.now() + timedelta(seconds=project.timeout_seconds)
        if config.provider_type == "DAGU":
            # 稳定 ID 在调用 Dagu 之前写入并提交，超时或进程重启后仍能找回同一次运行。
            execution.pipeline_run_id = f"automation-{execution.id}"
            self._remember_idempotency(db, project.id, body.idempotency_key, fingerprint, execution.id)
            try:
                db.commit()
            except IntegrityError:
                db.rollback()
                raced = self._existing_idempotent_execution(db, project.id, body.idempotency_key, fingerprint)
                if raced is not None:
                    return self._execution_response(db, raced)
                raise
            self._dispatch_dagu(db, execution.id)
            db.refresh(execution)
            return self._execution_response(db, execution)
        try:
            with self._provider_session(config) as provider:
                result = provider.trigger_run(pipeline.pipeline_id, params)
            if not result.external_run_id:
                raise ProviderError("CI 平台未返回运行实例 ID")
        except ProviderError as exc:
            execution.status = "FAILED"
            execution.dispatch_state = "FAILED"
            execution.error_message = str(exc)[:500]
            execution.finished_at = datetime.now()
            execution.notify_status = "SKIPPED"
            self._remember_idempotency(db, project.id, body.idempotency_key, fingerprint, execution.id)
            db.commit()
            raise bad_request(str(exc)) from exc
        execution.pipeline_run_id = result.external_run_id
        execution.dispatch_state = "CONFIRMED"
        execution.external_run_url = result.run_url or ""
        execution.status = result.status
        execution.external_status = result.external_status or result.status
        execution.started_at = result.started_at or (
            datetime.now() if config.provider_type == "YUNXIAO" and result.status == "RUNNING" else None
        )
        execution.finished_at = result.finished_at
        execution.duration_ms = result.duration_ms
        self._remember_idempotency(db, project.id, body.idempotency_key, fingerprint, execution.id)
        try:
            db.commit()
        except IntegrityError:
            db.rollback()
            existing = self._existing_idempotent_execution(db, project.id, body.idempotency_key, fingerprint)
            if existing is not None:
                return self._execution_response(db, existing)
            existing = db.query(AutomationExecution).filter_by(
                integration_config_id=config.id,
                automation_project_id=project.id,
                pipeline_run_id=result.external_run_id,
            ).first()
            if existing is not None:
                return self._execution_response(db, existing)
            raise
        db.refresh(execution)
        return self._execution_response(db, execution)

    def _request_fingerprint(self, body: ExecutionTrigger, project: AutomationProject, pipeline_id: str) -> str:
        """用实际会执行的参数计算摘要，相同幂等键配不同参数时拒绝合并。"""
        payload = {
            "pipeline_id": pipeline_id,
            "branch": (body.branch if body.branch is not None else project.default_branch).strip(),
            "environment_name": (body.environment_name if body.environment_name is not None else project.default_environment).strip(),
            "pytest_args": (body.pytest_args if body.pytest_args is not None else project.pytest_args).strip(),
            "test_tags": (body.test_tags if body.test_tags is not None else project.test_tags).strip(),
            "test_scope": (body.test_scope if body.test_scope is not None else project.test_scope).strip(),
        }
        return _sha(json.dumps(payload, ensure_ascii=False, sort_keys=True).encode("utf-8"))

    def _existing_idempotent_execution(
        self, db: Session, automation_project_id: int, idempotency_key: str | None, fingerprint: str,
    ) -> AutomationExecution | None:
        """相同请求返回已有执行；参数不一致时拒绝，避免重试打到另一次运行。"""
        if not idempotency_key:
            return None
        receipt = db.query(AutomationExecutionIdempotency).filter_by(
            automation_project_id=automation_project_id, idempotency_key=idempotency_key,
        ).first()
        if receipt is None:
            return None
        execution = db.get(AutomationExecution, receipt.execution_id)
        if execution is None:
            return None
        if receipt.expires_at < datetime.now() and execution.status in TERMINAL_STATUSES:
            db.delete(receipt)
            db.flush()
            return None
        if receipt.request_fingerprint != fingerprint:
            raise conflict("相同幂等键对应的执行参数不一致")
        return execution

    def _remember_idempotency(
        self, db: Session, automation_project_id: int, idempotency_key: str | None,
        fingerprint: str, execution_id: int,
    ) -> None:
        """把幂等键和执行记录放进当前事务，由唯一约束处理并发重复提交。"""
        if not idempotency_key:
            return
        db.add(AutomationExecutionIdempotency(
            automation_project_id=automation_project_id,
            idempotency_key=idempotency_key,
            request_fingerprint=fingerprint,
            execution_id=execution_id,
            expires_at=datetime.now() + _IDEMPOTENCY_TTL,
        ))

    def _purge_expired_idempotency(self, db: Session) -> None:
        """只清理已经结束的过期幂等记录，进行中的执行仍要挡住重复触发。"""
        stale = (
            db.query(AutomationExecutionIdempotency.id)
            .join(AutomationExecution, AutomationExecution.id == AutomationExecutionIdempotency.execution_id)
            .filter(AutomationExecutionIdempotency.expires_at < datetime.now())
            .filter(AutomationExecution.status.in_(list(TERMINAL_STATUSES)))
            .limit(100)
            .all()
        )
        if not stale:
            return
        db.query(AutomationExecutionIdempotency).filter(
            AutomationExecutionIdempotency.id.in_([row.id for row in stale]),
        ).delete(synchronize_session=False)

    def _dispatch_dagu(self, db: Session, execution_id: int) -> None:
        """按已提交的稳定运行 ID 入队。不确定是否成功时保留记录，交给 Poller 查询。"""
        execution = db.get(AutomationExecution, execution_id)
        if execution is None or execution.dispatch_state == "CONFIRMED":
            return
        config, resource_id = self._execution_provider_args(db, execution)
        params = dict(execution.run_params or {})
        try:
            with self._provider_session(config) as provider:
                result = provider.trigger_run(resource_id, params)
            if not result.external_run_id:
                raise ProviderError("CI 平台未返回运行实例 ID")
        except ProviderError as exc:
            execution = db.get(AutomationExecution, execution_id)
            if execution is None:
                raise bad_request(str(exc)) from exc
            uncertain = exc.status_code in {None, 408, 409, 429, 500, 502, 503, 504} or "超时" in str(exc) or "无法连接" in str(exc) or "不确定" in str(exc)
            execution.error_message = str(exc)[:500]
            if uncertain:
                execution.dispatch_state = "PENDING"
                execution.status = "PENDING"
                db.commit()
                return
            execution.status = "FAILED"
            execution.dispatch_state = "FAILED"
            execution.finished_at = datetime.now()
            execution.notify_status = "SKIPPED"
            db.commit()
            raise bad_request(str(exc)) from exc
        execution = db.get(AutomationExecution, execution_id)
        if execution is None:
            return
        execution.pipeline_run_id = result.external_run_id
        execution.dispatch_state = "CONFIRMED"
        execution.external_run_url = result.run_url or ""
        execution.status = result.status or "PENDING"
        execution.external_status = result.external_status or result.status or "queued"
        execution.error_message = ""
        db.commit()

    def list_executions(
        self, db: Session, project_id: int, actor: User, *, page: int, page_size: int,
        automation_project_id: int | None, status: str | None, branch: str | None,
        environment_name: str | None, started_from: datetime | None, started_to: datetime | None,
        provider_type: str | None = None, pipeline_id: str | None = None,
    ) -> ExecutionListResponse:
        """按项目、状态、分支、环境和时间筛选执行历史。"""
        get_project_or_404(db, project_id, actor)
        query = db.query(AutomationExecution).filter_by(project_id=project_id)
        if automation_project_id is not None:
            query = query.filter_by(automation_project_id=automation_project_id)
        if status:
            query = query.filter_by(status=status)
        if branch:
            query = query.filter(AutomationExecution.branch == branch)
        if environment_name:
            query = query.filter(AutomationExecution.environment_name == environment_name)
        if provider_type:
            query = query.filter(AutomationExecution.provider_type == provider_type.upper())
        if pipeline_id:
            query = query.filter(AutomationExecution.external_pipeline_id == pipeline_id)
        if started_from is not None:
            query = query.filter(AutomationExecution.created_at >= started_from)
        if started_to is not None:
            query = query.filter(AutomationExecution.created_at <= started_to)
        query = query.order_by(AutomationExecution.id.desc())
        page_data = paginate(query, page, page_size)
        return ExecutionListResponse(
            items=[self._execution_response(db, row) for row in page_data["items"]],
            total=page_data["total"], page=page_data["page"], page_size=page_data["page_size"],
        )

    def get_execution(self, db: Session, execution_id: int, actor: User) -> ExecutionResponse:
        """读取单次执行。不可见项目统一按不存在处理。"""
        row = self._execution_for(db, execution_id, actor, write=False)
        return self._execution_response(db, row)

    def get_console_log(self, db: Session, execution_id: int, actor: User) -> ConsoleLogResponse:
        """Fetch a bounded execution log through the server-side Provider."""
        row = self._execution_for(db, execution_id, actor, write=False)
        content = row.log_excerpt or ""
        if row.pipeline_run_id and row.provider_type in {"DAGU", "YUNXIAO"}:
            try:
                config, resource_id = self._execution_provider_args(db, row)
                with self._provider_session(config) as provider:
                    content = provider.get_log(
                        resource_id, row.pipeline_run_id, max_bytes=200_000,
                    ) or content
                callback_secret = decrypt_secret(config.callback_secret_encrypted)
                if callback_secret:
                    content = content.replace(callback_secret, "***")
            except ProviderError as exc:
                raise bad_request(str(exc)) from exc
        safe = _redact(content)
        return ConsoleLogResponse(
            execution_id=row.id,
            content=safe,
            truncated=len(content.encode("utf-8", errors="replace")) >= 200_000,
        )

    def cancel(self, db: Session, execution_id: int, actor: User) -> ExecutionResponse:
        """云效在停止接口确认后立即结束；Dagu 只记录停止请求，等 Poller 看到终态。"""
        row = self._execution_for(db, execution_id, actor, write=True)
        if row.provider_type == "LEGACY":
            raise bad_request("历史执行记录只读，不能取消")
        if row.status in TERMINAL_STATUSES:
            return self._execution_response(db, row)
        if row.status not in {"PENDING", "RUNNING"}:
            raise bad_request("当前状态不能取消")
        if row.provider_type == "DAGU":
            if row.stop_requested_at is not None:
                return self._execution_response(db, row)
            if not row.pipeline_run_id:
                self._transition(row, "CANCELLED")
                row.dispatch_state = "FAILED"
                row.external_status = "NO_EXTERNAL_RUN"
                row.stop_requested_at = None
                db.commit()
                self._notify(db, row.id)
                db.refresh(row)
                return self._execution_response(db, row)
            row.stop_reason = "CANCELLED"
            row.stop_requested_at = datetime.now()
            row.external_status = "STOP_REQUESTED"
            db.commit()
            try:
                config, resource_id = self._execution_provider_args(db, row)
                with self._provider_session(config) as provider:
                    provider.stop_run(resource_id, row.pipeline_run_id)
            except ProviderError as exc:
                row = db.get(AutomationExecution, execution_id)
                if row is not None:
                    row.error_message = str(exc)[:500]
                    db.commit()
            db.refresh(row)
            return self._execution_response(db, row)
        if row.pipeline_run_id:
            config, resource_id = self._execution_provider_args(db, row)
            try:
                with self._provider_session(config) as provider:
                    stopped = provider.stop_run(resource_id, row.pipeline_run_id)
            except ProviderError as exc:
                raise bad_request(str(exc)) from exc
            if not stopped:
                raise bad_request("CI 平台未确认终止运行")
        self._transition(row, "CANCELLED")
        row.external_status = "CANCELLED"
        row.stop_reason = "CANCELLED"
        # 云效取消已经得到接口确认，不能再留下 stop_requested，否则后续轮询会把终态打回去。
        row.stop_requested_at = None
        db.commit()
        self._notify(db, row.id)
        db.refresh(row)
        return self._execution_response(db, row)

    def sync_execution(self, db: Session, execution_id: int, actor: User) -> ExecutionResponse:
        """立即向 Provider 查询一次运行状态。历史记录不再访问已下线的执行平台。"""
        row = self._execution_for(db, execution_id, actor, write=True)
        if row.provider_type == "LEGACY":
            raise bad_request("历史执行记录只读，不能同步")
        if row.provider_type == "DAGU" and row.dispatch_state == "PENDING" and row.status in {"PENDING", "RUNNING"}:
            self._dispatch_dagu(db, row.id)
            db.refresh(row)
            if row.dispatch_state != "CONFIRMED":
                return self._execution_response(db, row)
        self._sync_one(db, row.id, force=True)
        db.refresh(row)
        return self._execution_response(db, row)

    # ---------------------------------------------------------------- 报告

    def list_reports(
        self, db: Session, project_id: int, actor: User, *, page: int, page_size: int,
        automation_project_id: int | None, environment_name: str | None, branch: str | None,
        started_from: datetime | None, started_to: datetime | None,
    ) -> ReportListResponse:
        """列出 Allure 报告元数据。"""
        get_project_or_404(db, project_id, actor)
        query = db.query(AutomationReport).filter_by(project_id=project_id)
        if automation_project_id is not None:
            query = query.filter_by(automation_project_id=automation_project_id)
        if any(value is not None and value != "" for value in (environment_name, branch, started_from, started_to)):
            query = query.join(AutomationExecution, AutomationExecution.id == AutomationReport.execution_id)
            if environment_name:
                query = query.filter(AutomationExecution.environment_name == environment_name)
            if branch:
                query = query.filter(AutomationExecution.branch == branch)
            if started_from is not None:
                query = query.filter(AutomationReport.created_at >= started_from)
            if started_to is not None:
                query = query.filter(AutomationReport.created_at <= started_to)
        query = query.order_by(AutomationReport.id.desc())
        page_data = paginate(query, page, page_size)
        return ReportListResponse(
            items=[self._report_response(db, row) for row in page_data["items"]],
            total=page_data["total"], page=page_data["page"], page_size=page_data["page_size"],
        )

    def get_report(self, db: Session, report_id: int, actor: User) -> ReportResponse:
        """读取报告统计。文件内容走独立的授权地址。"""
        report = self._report_for(db, report_id, actor)
        return self._report_response(db, report)

    def compare_reports(
        self, db: Session, left_id: int, right_id: int, actor: User,
    ) -> ReportCompareResponse:
        """对比两次执行的用例统计。两次报告必须属于同一业务项目。"""
        left = self._report_for(db, left_id, actor)
        right = self._report_for(db, right_id, actor)
        if left.project_id != right.project_id:
            raise not_found("报告不存在")
        left_body = self._report_response(db, left)
        right_body = self._report_response(db, right)
        fields = ("total_cases", "passed_cases", "failed_cases", "broken_cases", "skipped_cases", "pass_rate")
        delta = {field: getattr(right_body, field) - getattr(left_body, field) for field in fields}
        return ReportCompareResponse(left=left_body, right=right_body, delta=delta)

    def issue_grant(self, db: Session, report_id: int, actor: User) -> ReportGrantResponse:
        """签发两小时有效的报告文件凭据。凭据只授权这一份报告的静态文件。"""
        report = self._report_for(db, report_id, actor)
        raw = secrets.token_urlsafe(32)
        db.query(AutomationReportGrant).filter(
            AutomationReportGrant.report_id == report.id,
            AutomationReportGrant.expires_at < datetime.now(),
        ).delete(synchronize_session=False)
        db.add(AutomationReportGrant(
            report_id=report.id,
            user_id=actor.id,
            token_hash=_sha(raw.encode("utf-8")),
            expires_at=datetime.now() + timedelta(hours=2),
        ))
        db.commit()
        return ReportGrantResponse(
            token=raw,
            expires_at=datetime.now() + timedelta(hours=2),
            index_url=f"/api/v1/automation-reports/{report.id}/content/{raw}/index.html",
        )

    def open_report_file(self, db: Session, report_id: int, token: str, file_path: str):
        """校验报告凭据和项目权限后定位文件。"""
        grant = db.query(AutomationReportGrant).filter_by(
            report_id=report_id, token_hash=_sha(token.encode("utf-8")),
        ).first()
        if grant is None or grant.expires_at < datetime.now():
            raise not_found("报告文件不存在")
        user = db.get(User, grant.user_id)
        report = db.get(AutomationReport, report_id)
        if user is None or report is None or report.status != "READY":
            raise not_found("报告文件不存在")
        get_project_or_404(db, report.project_id, user)
        return storage.resolve_report_file(report.storage_dir, file_path)

    def report_archive(self, db: Session, report_id: int, actor: User):
        """定位报告压缩包，供已登录且有项目权限的用户下载。"""
        report = self._report_for(db, report_id, actor)
        artifact = db.query(AutomationArtifact).filter_by(report_id=report.id, kind="ALLURE_HTML_ZIP").first()
        if artifact is None:
            raise not_found("报告压缩包不存在")
        path = (storage.report_root() / artifact.relative_path).resolve()
        if not path.is_relative_to(storage.report_root()) or not path.is_file():
            raise not_found("报告压缩包不存在")
        return path

    def trend(
        self, db: Session, project_id: int, actor: User, *, automation_project_id: int | None,
        environment_name: str | None, branch: str | None,
    ) -> list[ReportResponse]:
        """返回用于趋势展示的历史报告，按时间正序。"""
        listed = self.list_reports(
            db, project_id, actor, page=1, page_size=100,
            automation_project_id=automation_project_id, environment_name=environment_name,
            branch=branch, started_from=None, started_to=None,
        )
        return list(reversed(listed.items))

    # ---------------------------------------------------------------- 回调

    def ingest_callback(
        self, db: Session, callback_key: str, headers: dict[str, str],
        metadata_text: str, report_bytes: bytes, results_bytes: bytes, log_bytes: bytes,
    ) -> CallbackResponse:
        """校验签名后保存报告并更新执行。相同幂等键直接返回已有结果。"""
        config = db.query(AutomationIntegrationConfig).filter_by(callback_key=callback_key).first()
        if config is None:
            raise not_found("回调配置不存在")
        secret = decrypt_secret(config.callback_secret_encrypted)
        self._verify_signature(secret, callback_key, headers, report_bytes, metadata_text)
        if not config.enabled or config.provider_type == "LEGACY":
            raise bad_request("回调接入配置未启用")
        idempotency_key = headers.get("x-idempotency-key", "").strip()
        existing = db.query(AutomationCallbackReceipt).filter_by(
            integration_config_id=config.id, idempotency_key=idempotency_key,
        ).first()
        if existing and existing.execution_id:
            execution = db.get(AutomationExecution, existing.execution_id)
            report = db.query(AutomationReport).filter_by(execution_id=existing.execution_id).first()
            if execution is not None:
                return CallbackResponse(
                    execution_id=execution.id, report_id=report.id if report else None,
                    status=execution.status, duplicate=True,
                )
        try:
            metadata = json.loads(metadata_text or "{}")
        except ValueError as exc:
            raise bad_request("回调元数据不是 JSON") from exc
        if not isinstance(metadata, dict):
            raise bad_request("回调元数据不是 JSON 对象")
        if secret:
            if isinstance(metadata.get("log_excerpt"), str):
                metadata["log_excerpt"] = metadata["log_excerpt"].replace(secret, "***")
            log_bytes = log_bytes.replace(secret.encode("utf-8"), b"***")
        created_dir: str | None = None
        try:
            execution = self._resolve_callback_execution(db, config, metadata)
            report = db.query(AutomationReport).filter_by(execution_id=execution.id).first()
            if report is not None and report_bytes:
                raise conflict("该执行已有报告，不能覆盖")
            if report_bytes:
                html_dir = storage.execution_dir(execution.project_id, execution.id) / "html"
                created_dir = str(html_dir)
                storage.safe_extract(report_bytes, html_dir)
                report = self._store_report(db, execution, html_dir, report_bytes, metadata)
            self._apply_callback_metadata(execution, metadata, report, config=config)
            self._store_optional_files(db, execution, report, results_bytes, log_bytes)
            db.add(AutomationCallbackReceipt(
                integration_config_id=config.id,
                idempotency_key=idempotency_key,
                execution_id=execution.id,
                payload_sha256=_sha(metadata_text.encode("utf-8")),
            ))
            db.commit()
        except IntegrityError as exc:
            db.rollback()
            if created_dir:
                shutil.rmtree(created_dir, ignore_errors=True)
            raced = db.query(AutomationCallbackReceipt).filter_by(
                integration_config_id=config.id, idempotency_key=idempotency_key,
            ).first()
            if raced and raced.execution_id:
                execution = db.get(AutomationExecution, raced.execution_id)
                report = db.query(AutomationReport).filter_by(execution_id=raced.execution_id).first()
                if execution is not None:
                    return CallbackResponse(
                        execution_id=execution.id, report_id=report.id if report else None,
                        status=execution.status, duplicate=True,
                    )
            raise conflict("回调正在处理") from exc
        except Exception:
            db.rollback()
            if created_dir:
                shutil.rmtree(created_dir, ignore_errors=True)
            raise
        self._notify(db, execution.id)
        db.refresh(execution)
        report = db.query(AutomationReport).filter_by(execution_id=execution.id).first()
        return CallbackResponse(
            execution_id=execution.id, report_id=report.id if report else None,
            status=execution.status, duplicate=False,
        )

    def history_archive(
        self, db: Session, callback_key: str, automation_project_id: int, headers: dict[str, str],
    ) -> bytes:
        """把上一份报告的 history 打成压缩包，供下一次 Allure 生成继承趋势。"""
        config = db.query(AutomationIntegrationConfig).filter_by(callback_key=callback_key).first()
        if config is None:
            raise not_found("回调配置不存在")
        metadata = str(automation_project_id)
        self._verify_signature(
            decrypt_secret(config.callback_secret_encrypted), callback_key, headers, b"", metadata,
        )
        project = db.get(AutomationProject, automation_project_id)
        if project is None or project.integration_config_id != config.id:
            raise not_found("没有可继承的 Allure history")
        report = (
            db.query(AutomationReport)
            .filter_by(automation_project_id=project.id, status="READY")
            .order_by(AutomationReport.id.desc())
            .first()
        )
        if report is None:
            raise not_found("没有可继承的 Allure history")
        return self._zip_history(storage.report_root() / report.storage_dir)

    # ---------------------------------------------------------------- 轮询

    def poll(self, db: Session) -> None:
        """轮询运行中的实例，并通过支持发现的 Provider 导入外部运行。"""
        active_status = AutomationExecution.status.in_(["PENDING", "RUNNING"])
        stopping_terminal = and_(
            AutomationExecution.status.in_(list(TERMINAL_STATUSES)),
            AutomationExecution.stop_requested_at.isnot(None),
        )
        pending_dispatch = (
            db.query(AutomationExecution.id)
            .filter(AutomationExecution.provider_type == "DAGU")
            .filter(AutomationExecution.dispatch_state == "PENDING")
            .filter(AutomationExecution.status.in_(["PENDING", "RUNNING"]))
            .order_by(AutomationExecution.id.asc())
            .limit(20)
            .all()
        )
        for (execution_id,) in pending_dispatch:
            try:
                self._dispatch_dagu(db, execution_id)
            except Exception:  # noqa: BLE001 — 单条补投失败不能拦住其余执行。
                logger.warning("补投 Dagu 执行失败 execution=%s", execution_id)
                db.rollback()
        active = (
            db.query(AutomationExecution.id)
            .filter(AutomationExecution.provider_type.in_(["DAGU", "YUNXIAO"]))
            .filter(or_(active_status, stopping_terminal))
            .filter(AutomationExecution.pipeline_run_id.isnot(None))
            .filter(or_(
                AutomationExecution.provider_type != "DAGU",
                AutomationExecution.dispatch_state == "CONFIRMED",
            ))
            .filter(or_(
                AutomationExecution.last_sync_at.is_(None),
                AutomationExecution.last_sync_at <= datetime.now() - timedelta(seconds=15),
            ))
            .order_by(AutomationExecution.last_sync_at.asc().nullsfirst())
            .limit(20)
            .all()
        )
        for (execution_id,) in active:
            try:
                self._sync_one(db, execution_id)
            except Exception:  # noqa: BLE001 — 单条失败不能拦住其余执行。
                logger.warning("同步自动化执行失败 execution=%s", execution_id)
                db.rollback()
        self._discover(db)
        waiting = (
            db.query(AutomationExecution.id)
            .filter(AutomationExecution.status.in_(list(TERMINAL_STATUSES)))
            .filter(AutomationExecution.notify_status.in_(["WAITING", "FAILED", "SENDING"]))
            .limit(20)
            .all()
        )
        for (execution_id,) in waiting:
            self._notify(db, execution_id)

    def _sync_one(self, db: Session, execution_id: int, *, force: bool = False) -> None:
        """Sync one run; stop and timeout outcomes remain pending until the provider confirms termination."""
        execution = (
            db.query(AutomationExecution).filter_by(id=execution_id)
            .with_for_update(skip_locked=True).one_or_none()
        )
        if execution is None:
            return
        if execution.provider_type not in {"DAGU", "YUNXIAO"}:
            # 已归档的 Jenkins 记录不再进入 Provider 同步。
            db.rollback()
            return
        if execution.provider_type == "DAGU" and execution.dispatch_state != "CONFIRMED":
            db.rollback()
            return
        if execution.status in TERMINAL_STATUSES and execution.stop_requested_at is None:
            return
        now = datetime.now()
        if not force and execution.last_sync_at and execution.last_sync_at > now - timedelta(seconds=15):
            db.rollback()
            return
        if not execution.pipeline_run_id:
            return
        if execution.status in {"PENDING", "RUNNING"} and execution.timeout_at and execution.timeout_at <= now:
            self._mark_timeout(db, execution)
            return

        config, resource_id = self._execution_provider_args(db, execution)
        execution.last_sync_at = now
        db.commit()
        stop_error = None
        try:
            with self._provider_session(config) as provider:
                if execution.stop_requested_at is not None:
                    try:
                        provider.stop_run(resource_id, execution.pipeline_run_id)
                    except ProviderError as exc:
                        stop_error = str(exc)
                result = provider.get_run(resource_id, external_run_id=execution.pipeline_run_id)
        except ProviderError as exc:
            execution = db.get(AutomationExecution, execution_id)
            if execution is not None:
                if (
                    execution.provider_type == "DAGU"
                    and execution.stop_requested_at is not None
                    and exc.status_code == 404
                ):
                    # Dagu removes dequeued runs from its run endpoint. A 404 after an
                    # accepted stop is therefore the terminal confirmation for that run.
                    execution.external_status = "NOT_FOUND_AFTER_STOP"
                    execution.status = execution.stop_reason or "CANCELLED"
                    execution.stop_requested_at = None
                    execution.finished_at = execution.finished_at or datetime.now()
                    execution.error_message = "Dagu 已从队列移除本次运行"
                    execution.last_sync_at = datetime.now()
                    db.commit()
                    self._notify(db, execution.id)
                    return
                execution.error_message = str(exc)[:500]
                execution.last_sync_at = datetime.now()
                db.commit()
            return

        execution = db.get(AutomationExecution, execution_id)
        if execution is None:
            return
        mapped = result.status
        raw_status = (result.external_status or "").lower()
        if raw_status == "aborted":
            mapped = execution.stop_reason if execution.stop_reason in {"CANCELLED", "TIMEOUT"} else "FAILED"
        remote_terminal = result.status in TERMINAL_STATUSES or raw_status == "aborted"
        if execution.status == "TIMEOUT" and execution.stop_reason == "TIMEOUT":
            mapped = "TIMEOUT"
        execution.external_status = (result.external_status or mapped)[:40]
        if execution.started_at is None and result.started_at is not None:
            execution.started_at = result.started_at
        if result.duration_ms is not None:
            execution.duration_ms = result.duration_ms
        if result.error_message:
            execution.error_message = result.error_message[:500]
        elif stop_error and result.status in {"PENDING", "RUNNING"}:
            execution.error_message = stop_error[:500]
        if result.run_url:
            execution.external_run_url = result.run_url[:1000]
        if result.finished_at is not None:
            execution.finished_at = result.finished_at
        if isinstance(result.raw.get("git_commit"), str) and result.raw["git_commit"]:
            execution.git_commit = result.raw["git_commit"][:64]
        execution.last_sync_at = datetime.now()
        if remote_terminal:
            execution.stop_requested_at = None
            execution.finished_at = execution.finished_at or datetime.now()
        self._transition(execution, mapped)
        db.commit()
        if (
            execution.status in {"PENDING", "RUNNING"}
            and execution.created_at
            and execution.created_at <= datetime.now() - timedelta(minutes=30)
        ):
            logger.warning(
                "自动化执行长时间未结束 execution=%s provider=%s status=%s",
                execution.id, execution.provider_type, execution.status,
            )
        if execution.status in TERMINAL_STATUSES and execution.stop_requested_at is None:
            self._notify(db, execution.id)

    def _mark_timeout(self, db: Session, execution: AutomationExecution) -> None:
        """云效超时后直接终态；Dagu 先请求停止，等远端确认后再清除停止标记。"""
        self._transition(execution, "TIMEOUT")
        execution.stop_reason = "TIMEOUT"
        execution.last_sync_at = datetime.now()
        if execution.provider_type == "DAGU" and execution.pipeline_run_id and execution.dispatch_state == "CONFIRMED":
            execution.stop_requested_at = execution.stop_requested_at or datetime.now()
            execution.external_status = "STOP_REQUESTED"
            execution.error_message = "执行超时，正在请求 Dagu 停止任务"
            db.commit()
            try:
                config, resource_id = self._execution_provider_args(db, execution)
                with self._provider_session(config) as provider:
                    provider.stop_run(resource_id, execution.pipeline_run_id)
            except ProviderError:
                logger.warning("超时后请求 Dagu 停止任务失败 execution=%s", execution.id)
            return
        execution.stop_requested_at = None
        execution.external_status = "TIMEOUT"
        execution.error_message = "执行超时"
        db.commit()
        if execution.pipeline_run_id and execution.provider_type == "YUNXIAO":
            try:
                config, resource_id = self._execution_provider_args(db, execution)
                with self._provider_session(config) as provider:
                    provider.stop_run(resource_id, execution.pipeline_run_id)
            except ProviderError:
                logger.warning("超时后请求云效停止任务失败 execution=%s", execution.id)
        self._notify(db, execution.id)

    def _discover(self, db: Session) -> None:
        """把 Provider 上新出现、且不是本平台触发的运行登记为执行记录。"""
        projects = (
            db.query(AutomationProject).filter_by(enabled=True).order_by(AutomationProject.id.asc()).limit(10).all()
        )
        for project in projects:
            config = db.get(AutomationIntegrationConfig, project.integration_config_id)
            pipeline = db.query(AutomationPipeline).filter_by(automation_project_id=project.id, is_default=True).first()
            if config is None or pipeline is None or not config.enabled or config.provider_type != "YUNXIAO":
                continue
            try:
                with self._provider_session(config) as provider:
                    runs = provider.list_runs(pipeline.pipeline_id, per_page=10)
            except ProviderError as exc:
                logger.warning("读取外部运行列表失败 project=%s: %s", project.id, exc)
                continue
            for item in runs:
                self._import_remote_run(db, project, pipeline, item)
        try:
            db.commit()
        except IntegrityError:
            db.rollback()
            logger.warning("外部运行发现时遇到唯一标识冲突，已回滚本批次；下一轮会重试")

    def _import_remote_run(
        self, db: Session, project: AutomationProject, pipeline: AutomationPipeline, item: ProviderExecution,
    ) -> None:
        """Import recent Yunxiao runs that were triggered outside this platform."""
        run_id = item.external_run_id
        start = item.started_at
        if run_id is None or start is None:
            return
        if start < project.created_at or start < datetime.now() - timedelta(hours=24):
            return
        exists = db.query(AutomationExecution.id).filter_by(
            automation_project_id=project.id, pipeline_run_id=str(run_id),
        ).first()
        if exists:
            return
        status = item.status
        execution = AutomationExecution(
            project_id=project.project_id,
            automation_project_id=project.id,
            pipeline_binding_id=pipeline.id,
            integration_config_id=project.integration_config_id,
            provider_type=item.provider_type,
            external_pipeline_id=pipeline.pipeline_id,
            pipeline_run_id=str(run_id),
            external_run_url=item.run_url or "",
            git_commit=str(item.raw.get("git_commit") or "")[:64],
            trigger_source=item.trigger_source,
            status=status,
            branch=project.default_branch,
            environment_name=project.default_environment,
            pytest_args=project.pytest_args,
            test_tags=project.test_tags,
            test_scope=project.test_scope,
            external_status=(item.external_status or status)[:40],
            started_at=start,
            finished_at=item.finished_at or (datetime.now() if status in TERMINAL_STATUSES else None),
            duration_ms=item.duration_ms,
            notify_status="WAITING",
        )
        try:
            with db.begin_nested():
                db.add(execution)
                db.flush()
        except IntegrityError:
            logger.info("忽略并发重复导入的外部执行 project=%s provider=%s", project.id, item.provider_type)

    # ---------------------------------------------------------------- 内部

    def _notify(self, db: Session, execution_id: int) -> None:
        """报告就绪或终态等待超时后发送飞书卡片。已发送的执行不会再发。"""
        execution = (
            db.query(AutomationExecution).filter_by(id=execution_id).with_for_update().one_or_none()
        )
        if execution is None or execution.notify_status in {"SENT", "SKIPPED"}:
            db.commit()
            return
        if execution.stop_requested_at is not None:
            db.commit()
            return
        if execution.notify_attempts >= 3 and execution.notify_status == "FAILED":
            db.commit()
            return
        if (
            execution.notify_status == "SENDING"
            and execution.updated_at
            and execution.updated_at > datetime.now() - timedelta(seconds=120)
        ):
            db.commit()
            return
        project = db.get(AutomationProject, execution.automation_project_id)
        report = db.query(AutomationReport).filter_by(execution_id=execution.id, status="READY").first()
        if project is None:
            execution.notify_status = "SKIPPED"
            db.commit()
            return
        if project.notify_condition == "NEVER":
            execution.notify_status = "SKIPPED"
            db.commit()
            return
        grace = execution.finished_at and execution.finished_at <= datetime.now() - timedelta(seconds=120)
        if report is None and not (execution.status in TERMINAL_STATUSES and grace):
            execution.notify_status = "WAITING"
            db.commit()
            return
        if project.notify_condition == "ONLY_FAILED" and execution.status != "FAILED" and execution.status != "TIMEOUT":
            if report is not None or grace:
                execution.notify_status = "SKIPPED"
                db.commit()
                return
        channel = self._channel_for(db, project, execution.project_id)
        if channel is None:
            execution.notify_status = "SKIPPED"
            db.commit()
            return
        execution.notify_status = "SENDING"
        execution.notify_attempts += 1
        card = build_automation_card(
            project_name=project.name,
            status=execution.status,
            branch=execution.branch,
            environment_name=execution.environment_name,
            total=report.total_cases if report else 0,
            passed=report.passed_cases if report else 0,
            failed=report.failed_cases if report else 0,
            skipped=report.skipped_cases if report else 0,
            broken=report.broken_cases if report else 0,
            pass_rate=f"{float(report.pass_rate) if report else 0:.2f}",
            duration_ms=report.duration_ms if report and report.duration_ms is not None else execution.duration_ms,
            started_at=execution.started_at.strftime("%Y-%m-%d %H:%M:%S") if execution.started_at else "",
            report_id=report.id if report else None,
            report_ready=report is not None,
        )
        db.commit()
        record = self._feishu.send_card(db, channel, None, card, actor_id=execution.created_by)
        execution.notify_status = "SENT" if record.status == "SUCCESS" else "FAILED"
        db.commit()

    def _store_report(self, db, execution, html_dir, report_bytes, metadata) -> AutomationReport:
        """写入报告元数据和压缩包索引。"""
        parsed, suites, history = storage.read_allure_summary(html_dir)
        stats = self._merge_stats(parsed, metadata.get("stats"))
        rate = pass_rate(
            passed=stats["passed"], failed=stats["failed"], broken=stats["broken"],
            skipped=stats["skipped"], unknown=stats["unknown"],
        )
        relative_html = f"{execution.project_id}/{execution.id}/html"
        archive_rel = f"{execution.project_id}/{execution.id}/report.zip"
        storage.write_bytes(storage.report_root() / archive_rel, report_bytes)
        report = AutomationReport(
            execution_id=execution.id,
            project_id=execution.project_id,
            automation_project_id=execution.automation_project_id,
            storage_dir=relative_html,
            archive_sha256=storage.sha256_bytes(report_bytes),
            archive_size=len(report_bytes),
            status="READY",
            total_cases=stats["total"],
            passed_cases=stats["passed"],
            failed_cases=stats["failed"],
            broken_cases=stats["broken"],
            skipped_cases=stats["skipped"],
            unknown_cases=stats["unknown"],
            pass_rate=rate,
            duration_ms=self._duration(metadata, execution),
            suite_summary=metadata.get("suites") if isinstance(metadata.get("suites"), list) else suites,
            history_included=history,
            generated_at=datetime.now(),
        )
        db.add(report)
        db.flush()
        db.add(AutomationArtifact(
            execution_id=execution.id, report_id=report.id, kind="ALLURE_HTML_ZIP",
            relative_path=archive_rel, sha256=report.archive_sha256, size_bytes=len(report_bytes),
        ))
        return report

    def _apply_callback_metadata(
        self, execution, metadata: dict, report: AutomationReport | None,
        *, config: AutomationIntegrationConfig | None = None,
    ) -> None:
        """Apply runner metadata and let Allure test outcomes refine the provider result."""
        for field, key in (
            ("branch", "branch"), ("environment_name", "environment"), ("git_commit", "git_commit"),
        ):
            value = metadata.get(key)
            if isinstance(value, str) and value.strip():
                setattr(execution, field, value.strip()[:200] if field != "git_commit" else value.strip()[:64])
        if isinstance(metadata.get("log_excerpt"), str):
            execution.log_excerpt = _redact(metadata["log_excerpt"])
        duration = metadata.get("duration_ms")
        if isinstance(duration, int):
            execution.duration_ms = duration
        started_ms = metadata.get("started_at_ms")
        if isinstance(started_ms, int) and started_ms > 0:
            execution.started_at = datetime.fromtimestamp(started_ms / 1000)
        callback_run_id = metadata.get("dag_run_id") or metadata.get("pipeline_run_id")
        if execution.provider_type == "DAGU" and callback_run_id:
            if str(callback_run_id) != str(execution.pipeline_run_id):
                raise bad_request("回调 Dagu Run ID 与平台执行记录不匹配")
        requested_status = str(metadata.get("status") or execution.external_status or "").upper()
        incoming = map_pipeline_status(requested_status or "SUCCESS")
        if requested_status == "ABORTED":
            incoming = execution.stop_reason if execution.stop_reason in {"CANCELLED", "TIMEOUT"} else "FAILED"
        # 客户端可以声明成功，但已经解析出的 Allure 结果才能把成功改成失败。
        failed = report.failed_cases if report is not None else 0
        broken = report.broken_cases if report is not None else 0
        self._transition(execution, apply_test_outcome(incoming, failed=failed, broken=broken))
        execution.external_status = requested_status[:40] or incoming
        if execution.started_at is None:
            execution.started_at = datetime.now()
        if execution.status in TERMINAL_STATUSES:
            execution.finished_at = execution.finished_at or datetime.now()

    def _store_optional_files(self, db, execution, report, results_bytes: bytes, log_bytes: bytes) -> None:
        """保存原始结果和日志文件，原始结果不自动解压。"""
        if results_bytes:
            if len(results_bytes) > settings.AUTOMATION_REPORT_MAX_BYTES or results_bytes[:2] != b"PK":
                raise bad_request("原始结果不是有效的 ZIP 或超过大小限制")
            relative = f"{execution.project_id}/{execution.id}/results.zip"
            storage.write_bytes(storage.report_root() / relative, results_bytes)
            db.add(AutomationArtifact(
                execution_id=execution.id, report_id=report.id if report else None, kind="ALLURE_RESULTS",
                relative_path=relative, sha256=storage.sha256_bytes(results_bytes), size_bytes=len(results_bytes),
            ))
        if log_bytes:
            if len(log_bytes) > 2_000_000:
                raise bad_request("执行日志超过大小限制")
            text = _redact(log_bytes.decode("utf-8", errors="replace"))
            relative = f"{execution.project_id}/{execution.id}/run.log"
            data = text.encode("utf-8")
            storage.write_bytes(storage.report_root() / relative, data)
            execution.log_excerpt = text[:20000]
            db.add(AutomationArtifact(
                execution_id=execution.id, report_id=report.id if report else None, kind="LOG",
                relative_path=relative, sha256=storage.sha256_bytes(data), size_bytes=len(data),
            ))

    def _resolve_callback_execution(self, db, config, metadata: dict) -> AutomationExecution:
        """确认回调、接入配置、项目和运行 ID 属于同一次执行，不匹配则不创建报告。"""
        project = self._callback_project(db, config, metadata)
        execution_id = metadata.get("execution_id")
        run_id = metadata.get("dag_run_id") or metadata.get("pipeline_run_id")
        execution = None
        if execution_id is not None:
            try:
                parsed_id = int(execution_id)
            except (TypeError, ValueError) as exc:
                raise bad_request("回调执行记录不存在") from exc
            execution = db.get(AutomationExecution, parsed_id)
            if execution is None:
                raise not_found("执行记录不存在")
        elif run_id is not None:
            execution = db.query(AutomationExecution).filter_by(
                automation_project_id=project.id, pipeline_run_id=str(run_id),
            ).first()
        if execution is None:
            if config.provider_type == "DAGU" and not run_id:
                raise bad_request("回调 Dagu Run ID 与平台执行记录不匹配")
            pipeline = self._default_pipeline(db, project)
            if config.provider_type == "DAGU":
                self._validate_resource_id(config.provider_type, str(metadata.get("pipeline_id") or pipeline.pipeline_id))
            execution = AutomationExecution(
                project_id=project.project_id,
                automation_project_id=project.id,
                pipeline_binding_id=pipeline.id,
                integration_config_id=config.id,
                provider_type=config.provider_type,
                external_pipeline_id=str(metadata.get("pipeline_id") or pipeline.pipeline_id),
                pipeline_run_id=str(run_id) if run_id is not None else None,
                dispatch_state="CONFIRMED",
                trigger_source=str(metadata.get("trigger_source") or "CODE_PUSH")[:20],
                status="RUNNING",
                branch=str(metadata.get("branch") or project.default_branch)[:200],
                environment_name=str(metadata.get("environment") or project.default_environment)[:100],
                pytest_args=project.pytest_args,
                test_tags=project.test_tags,
                test_scope=project.test_scope,
                started_at=datetime.now(),
                notify_status="WAITING",
            )
            db.add(execution)
            db.flush()
        self._assert_callback_ownership(execution, config, project, metadata)
        return execution

    def _assert_callback_ownership(self, execution, config, project, metadata: dict) -> None:
        """回调只能更新自己的接入配置、项目和运行 ID，不能靠元数据改写别的执行。"""
        if execution.integration_config_id != config.id or execution.provider_type != config.provider_type:
            raise bad_request("回调执行记录不属于当前接入配置")
        if execution.automation_project_id != project.id or execution.project_id != project.project_id:
            raise not_found("执行记录不存在")
        if execution.provider_type == "DAGU":
            callback_run_id = metadata.get("dag_run_id") or metadata.get("pipeline_run_id")
            if not callback_run_id or str(callback_run_id) != str(execution.pipeline_run_id):
                raise bad_request("回调 Dagu Run ID 与平台执行记录不匹配")
        stated_execution_id = metadata.get("execution_id")
        if stated_execution_id is not None and str(stated_execution_id) != str(execution.id):
            raise bad_request("回调执行记录不存在")

    def _callback_project(self, db, config, metadata: dict) -> AutomationProject:
        """确认回调指向的自动化项目属于这套接入配置。"""
        project_id = metadata.get("automation_project_id")
        if project_id is None:
            raise bad_request("回调缺少自动化项目")
        project = db.get(AutomationProject, int(project_id))
        if project is None or project.integration_config_id != config.id:
            raise not_found("自动化项目不存在")
        return project

    def _verify_signature(self, secret: str, callback_key: str, headers: dict[str, str], report: bytes, metadata: str) -> None:
        """校验时间窗和 HMAC。密钥不写入错误信息。"""
        timestamp = headers.get("x-automation-timestamp", "")
        signature = headers.get("x-automation-signature", "")
        idempotency_key = headers.get("x-idempotency-key", "").strip()
        if not timestamp or not signature or not idempotency_key:
            raise bad_request("回调缺少签名或幂等键")
        if not re.fullmatch(r"[A-Za-z0-9_.:-]{1,120}", idempotency_key):
            raise bad_request("幂等键不合法")
        try:
            stamp = int(timestamp)
        except ValueError as exc:
            raise bad_request("回调时间无效") from exc
        if abs(int(datetime.now().timestamp()) - stamp) > 300:
            raise bad_request("回调已过期")
        if not secret:
            raise bad_request("回调密钥未配置")
        expected = sign_callback(
            secret, timestamp, callback_key, idempotency_key, _sha(report), _sha(metadata.encode("utf-8")),
        )
        if not hmac.compare_digest(expected, signature):
            raise bad_request("回调签名无效")

    def _execution_params(self, config, project, pipeline, execution) -> dict[str, Any]:
        """Build the provider-neutral payload; only the Dagu adapter translates it to API fields."""
        base = settings.PUBLIC_APP_BASE_URL.strip().rstrip("/")
        callback_url = ""
        history_url = ""
        if base.startswith(("http://", "https://")):
            callback_url = f"{base}/api/v1/automation-callbacks/{config.callback_key}"
            history_url = (
                f"{base}/api/v1/automation-callbacks/{config.callback_key}/history"
                f"?automation_project_id={project.id}"
            )
        variables = self._public_params(project.pipeline_params)
        variables.update(self._public_params(pipeline.extra_params))
        if config.provider_type == "DAGU":
            if not callback_url.startswith("https://"):
                raise bad_request("Dagu 回调要求 PUBLIC_APP_BASE_URL 配置为 HTTPS")
            self._validate_repository_url(project.repository_url)
            self._validate_run_options(
                execution.branch, execution.environment_name, execution.pytest_args,
                execution.test_tags, execution.test_scope,
            )
        return {
            "branch": execution.branch,
            "environment_name": execution.environment_name,
            "pytest_args": execution.pytest_args,
            "test_tags": execution.test_tags,
            "test_scope": execution.test_scope,
            "execution_id": str(execution.id),
            "automation_project_id": str(project.id),
            "integration_config_id": str(config.id),
            "callback_key": config.callback_key,
            "callback_url": callback_url,
            "history_url": history_url,
            "repository_url": project.repository_url,
            "repository_id": project.repository_id,
            "timeout_seconds": project.timeout_seconds,
            "queue": "automation-tests",
            "variables": variables,
        }

    @staticmethod
    def _validate_run_options(
        branch: str, environment: str, pytest_args: str, test_tags: str, test_scope: str,
    ) -> None:
        """Validate values consumed by the shell-free Dagu Runner."""
        if branch and (
            not re.fullmatch(r"[A-Za-z0-9._/-]{1,200}", branch)
            or branch.startswith("-") or ".." in branch or "//" in branch or "@{" in branch
        ):
            raise bad_request("Git 分支名不合法")
        if environment and not re.fullmatch(r"[A-Za-z0-9_.-]{1,100}", environment):
            raise bad_request("测试环境名只允许字母、数字、点、下划线和连字符")
        if any(char in pytest_args for char in "\r\n\x00"):
            raise bad_request("pytest 参数不能包含换行或控制字符")
        if test_tags and not re.fullmatch(r"[A-Za-z0-9_ .()!&|]{1,200}", test_tags):
            raise bad_request("测试标签只允许 pytest marker 表达式字符")
        for raw_path in filter(None, (part.strip() for part in test_scope.split(","))):
            path = raw_path.split("::", 1)[0]
            if path.startswith(("/", "-")) or ".." in path.split("/") or "\\" in path or any(ord(c) < 32 for c in path):
                raise bad_request("测试范围必须是仓库内的相对路径")
        allowed = {"-q", "-v", "-x", "--disable-warnings", "--capture=no", "--tb=short", "--strict-markers"}
        try:
            import shlex
            tokens = shlex.split(pytest_args)
        except ValueError as exc:
            raise bad_request("pytest 参数格式不合法") from exc
        index = 0
        while index < len(tokens):
            token = tokens[index]
            if token in allowed:
                index += 1
                continue
            if token.startswith("--maxfail=") and re.fullmatch(r"--maxfail=[1-9][0-9]?", token):
                index += 1
                continue
            if token == "--maxfail" and index + 1 < len(tokens) and re.fullmatch(r"[1-9][0-9]?", tokens[index + 1]):
                index += 2
                continue
            if token == "-k" and index + 1 < len(tokens) and re.fullmatch(r"[A-Za-z0-9_ .:'\"()!&|=-]{1,200}", tokens[index + 1]):
                index += 2
                continue
            raise bad_request(f"pytest 参数不在安全允许列表中：{token[:80]}")

    @staticmethod
    def _validate_repository_url(value: str) -> None:
        """Allow only credential-free Codeup HTTPS/SSH repository URLs."""
        if not value or any(char in value for char in "\r\n\x00"):
            raise bad_request("Codeup 仓库地址不合法")
        from urllib.parse import urlsplit

        if value.startswith("git@"):
            match = re.fullmatch(r"git@codeup\.aliyun\.com:([A-Za-z0-9_.-]+(?:/[A-Za-z0-9_.-]+)*)(?:\.git)?", value)
            if not match or any(part in {".", ".."} for part in match.group(1).split("/")):
                raise bad_request("私有仓库 SSH 地址必须位于 codeup.aliyun.com")
            return
        parsed = urlsplit(value)
        if (
            parsed.scheme not in {"https", "ssh"} or parsed.hostname != "codeup.aliyun.com"
            or parsed.password or parsed.query or parsed.fragment
            or (parsed.username not in {None, "git"})
            or not parsed.path.strip("/")
            or any(part in {".", ".."} for part in parsed.path.split("/"))
        ):
            raise bad_request("仓库地址必须是授权的 Codeup HTTPS/SSH 地址，且不能内嵌凭据")

    def _provider(self, config: AutomationIntegrationConfig) -> AutomationProvider:
        """按配置选择 Provider；阶段 1 的既有记录默认走云效适配器。"""
        return provider_factory.get(getattr(config, "provider_type", "YUNXIAO"), config)

    @contextmanager
    def _provider_session(self, config: AutomationIntegrationConfig) -> Iterator[AutomationProvider]:
        """在单次服务操作范围内管理 Provider 连接生命周期。"""
        provider = self._provider(config)
        try:
            yield provider
        finally:
            close = getattr(provider, "close", None)
            if callable(close):
                close()

    def _execution_provider_args(self, db, execution: AutomationExecution):
        """取出调用 Provider 所需的接入配置和外部 Job/流水线标识。"""
        config_id = execution.integration_config_id
        if config_id is None:
            project = db.get(AutomationProject, execution.automation_project_id)
            if project is None:
                raise not_found("自动化项目不存在")
            config_id = project.integration_config_id
        config = (
            db.query(AutomationIntegrationConfig).execution_options(include_deleted=True)
            .filter(AutomationIntegrationConfig.id == config_id).first()
        )
        if config is None:
            raise not_found("接入配置不存在")
        return config, execution.external_pipeline_id

    def _transition(self, execution: AutomationExecution, new_status: str) -> None:
        """保护终态不被运行中状态覆盖。成功可以被随后确认的用例失败修正。"""
        if execution.status in TERMINAL_STATUSES:
            if execution.status == "SUCCESS" and new_status == "FAILED":
                execution.status = "FAILED"
            return
        execution.status = new_status
        if new_status in TERMINAL_STATUSES and execution.finished_at is None:
            execution.finished_at = datetime.now()

    def _config_for_write(self, db, config_id: int, actor: User) -> AutomationIntegrationConfig:
        """读取可写的接入配置。"""
        row = db.get(AutomationIntegrationConfig, config_id)
        if row is None:
            raise not_found("接入配置不存在")
        require_writable_project(db, row.project_id, actor)
        return row

    def _config_for_read(self, db, config_id: int, actor: User) -> AutomationIntegrationConfig:
        row = db.get(AutomationIntegrationConfig, config_id)
        if row is None:
            raise not_found("接入配置不存在")
        get_project_or_404(db, row.project_id, actor)
        return row

    @staticmethod
    def _require_ci_admin(db, project_id: int, actor: User) -> None:
        """Dagu endpoints and credentials are restricted to project administrators."""
        project = get_project_or_404(db, project_id, actor)
        role = project_role_for(db, project, actor)
        if not has_project_role(role, PROJECT_ROLE_EDITOR):
            raise forbidden("Dagu 接入地址和 API Key 需要项目管理员权限")

    @staticmethod
    def _validate_resource_id(provider_type: str, resource_id: str) -> None:
        if provider_type == "DAGU":
            if (
                len(resource_id) > 255
                or not re.fullmatch(r"[A-Za-z0-9_.-]{1,200}(?:/[A-Za-z0-9_.-]{1,200})*", resource_id)
                or any(part in {".", ".."} for part in resource_id.split("/"))
            ):
                raise bad_request("Dagu DAG Name 不合法")
            if resource_id not in APPROVED_DAGU_DAGS:
                raise bad_request("Dagu DAG 不在平台允许的自动化测试白名单中")
        elif provider_type == "YUNXIAO" and not re.fullmatch(r"[A-Za-z0-9_-]{1,64}", resource_id):
            raise bad_request("云效流水线 ID 不合法")
        elif provider_type not in {"YUNXIAO", "DAGU"}:
            raise bad_request("此历史执行平台已停用")

    def _owned_config(self, db, project_id: int, config_id: int) -> AutomationIntegrationConfig:
        """接入配置必须属于同一个业务项目。"""
        config = db.get(AutomationIntegrationConfig, config_id)
        if config is None or config.project_id != project_id:
            raise not_found("接入配置不存在")
        return config

    def _automation_for(self, db, automation_project_id: int, actor: User, *, write: bool) -> AutomationProject:
        """按可见性读取自动化项目。"""
        row = db.get(AutomationProject, automation_project_id)
        if row is None:
            raise not_found("自动化项目不存在")
        if write:
            require_writable_project(db, row.project_id, actor)
        else:
            get_project_or_404(db, row.project_id, actor)
        return row

    def _execution_for(self, db, execution_id: int, actor: User, *, write: bool) -> AutomationExecution:
        """按可见性读取执行记录。"""
        row = db.get(AutomationExecution, execution_id)
        if row is None:
            raise not_found("执行记录不存在")
        if write:
            require_writable_project(db, row.project_id, actor)
        else:
            get_project_or_404(db, row.project_id, actor)
        return row

    def _report_for(self, db, report_id: int, actor: User) -> AutomationReport:
        """按可见性读取报告。"""
        row = db.get(AutomationReport, report_id)
        if row is None:
            raise not_found("报告不存在")
        get_project_or_404(db, row.project_id, actor)
        return row

    def _default_pipeline(self, db, project: AutomationProject) -> AutomationPipeline:
        """读取默认流水线绑定。"""
        pipeline = (
            db.query(AutomationPipeline)
            .filter_by(automation_project_id=project.id, is_default=True)
            .order_by(AutomationPipeline.id.asc())
            .first()
        )
        if pipeline is None:
            raise not_found("流水线绑定不存在")
        return pipeline

    def _pipeline_for_trigger(self, db, project, pipeline_id: str | None) -> AutomationPipeline:
        """手动触发时允许在该项目已绑定的流水线中选择。"""
        if not pipeline_id:
            return self._default_pipeline(db, project)
        pipeline = db.query(AutomationPipeline).filter_by(
            automation_project_id=project.id, pipeline_id=pipeline_id,
        ).first()
        if pipeline is None:
            raise not_found("流水线绑定不存在")
        return pipeline

    def _ensure_channel(self, db, project_id: int, channel_id: int | None) -> None:
        """通知渠道必须属于当前业务项目。"""
        if channel_id is None:
            return
        channel = db.get(NotificationChannel, channel_id)
        if channel is None or channel.project_id != project_id:
            raise not_found("通知渠道不存在")

    def _channel_for(self, db, project: AutomationProject, project_id: int) -> NotificationChannel | None:
        """优先使用项目指定渠道，否则使用该业务项目第一条启用的飞书渠道。"""
        if project.notification_channel_id:
            channel = db.get(NotificationChannel, project.notification_channel_id)
            if channel is not None and channel.enabled and channel.project_id == project_id:
                return channel
        return (
            db.query(NotificationChannel)
            .filter_by(project_id=project_id, channel_type="FEISHU_WEBHOOK", enabled=True)
            .order_by(NotificationChannel.id.asc())
            .first()
        )

    def _integration_response(self, row: AutomationIntegrationConfig) -> IntegrationResponse:
        """组装不含密文的配置响应。"""
        configured = bool(row.dagu_api_key_configured) if row.provider_type == "DAGU" else bool(
            row.access_token_encrypted
        )
        return IntegrationResponse(
            id=row.id, project_id=row.project_id, name=row.name,
            provider_type=row.provider_type, enabled=row.enabled,
            dagu_base_url=row.dagu_base_url,
            dagu_api_key_configured=bool(row.dagu_api_key_configured),
            api_base_url=row.api_base_url,
            organization_id=row.organization_id, deployment=row.deployment,
            token_configured=configured, callback_key=row.callback_key,
            callback_secret_configured=bool(row.callback_secret_encrypted),
            callback_path=f"/api/v1/automation-callbacks/{row.callback_key}",
            default_timeout_seconds=row.default_timeout_seconds, created_at=row.created_at,
        )

    def _project_response(self, db, row: AutomationProject) -> AutomationProjectResponse:
        """组装项目响应和最近执行摘要。"""
        pipeline = db.query(AutomationPipeline).filter_by(automation_project_id=row.id, is_default=True).first()
        latest = (
            db.query(AutomationExecution).filter_by(automation_project_id=row.id)
            .order_by(AutomationExecution.id.desc()).first()
        )
        config = db.get(AutomationIntegrationConfig, row.integration_config_id)
        return AutomationProjectResponse(
            id=row.id, project_id=row.project_id, integration_config_id=row.integration_config_id,
            provider_type=config.provider_type if config else "YUNXIAO",
            name=row.name, description=row.description, repository_url=row.repository_url,
            repository_id=row.repository_id, pipeline_id=pipeline.pipeline_id if pipeline else "",
            pipeline_name=pipeline.name if pipeline else "", default_branch=row.default_branch,
            default_environment=row.default_environment, pytest_args=row.pytest_args,
            test_tags=row.test_tags, test_scope=row.test_scope,
            pipeline_params=row.pipeline_params or {}, timeout_seconds=row.timeout_seconds,
            notification_channel_id=row.notification_channel_id, notify_condition=row.notify_condition,
            enabled=row.enabled, last_status=latest.status if latest else None,
            last_execution_at=latest.created_at if latest else None, created_at=row.created_at,
        )

    def _execution_response(self, db, row: AutomationExecution) -> ExecutionResponse:
        """组装执行响应。"""
        project = db.get(AutomationProject, row.automation_project_id)
        report = db.query(AutomationReport).filter_by(execution_id=row.id).first()
        return ExecutionResponse(
            id=row.id, project_id=row.project_id, automation_project_id=row.automation_project_id,
            automation_project_name=project.name if project else "", pipeline_id=row.external_pipeline_id,
            pipeline_run_id=row.pipeline_run_id, provider_type=row.provider_type,
            external_run_url=row.external_run_url, trigger_source=row.trigger_source, status=row.status,
            branch=row.branch, environment_name=row.environment_name, pytest_args=row.pytest_args,
            test_tags=row.test_tags, test_scope=row.test_scope, git_commit=row.git_commit,
            external_status=row.external_status, stop_requested=row.stop_requested_at is not None,
            stop_reason=row.stop_reason, log_excerpt=row.log_excerpt, error_message=row.error_message,
            started_at=row.started_at, finished_at=row.finished_at, duration_ms=row.duration_ms,
            notify_status=row.notify_status, report_id=report.id if report else None, created_at=row.created_at,
        )

    def _report_response(self, db, row: AutomationReport) -> ReportResponse:
        """组装报告响应。"""
        execution = db.get(AutomationExecution, row.execution_id)
        project = db.get(AutomationProject, row.automation_project_id)
        return ReportResponse(
            id=row.id, execution_id=row.execution_id, project_id=row.project_id,
            automation_project_id=row.automation_project_id,
            automation_project_name=project.name if project else "", status=row.status,
            total_cases=row.total_cases, passed_cases=row.passed_cases, failed_cases=row.failed_cases,
            broken_cases=row.broken_cases, skipped_cases=row.skipped_cases, unknown_cases=row.unknown_cases,
            pass_rate=float(row.pass_rate), duration_ms=row.duration_ms,
            suite_summary=row.suite_summary or [], history_included=row.history_included,
            branch=execution.branch if execution else "", environment_name=execution.environment_name if execution else "",
            git_commit=execution.git_commit if execution else "",
            provider_type=execution.provider_type if execution else "YUNXIAO",
            external_run_url=execution.external_run_url if execution else "",
            generated_at=row.generated_at, created_at=row.created_at,
        )

    @staticmethod
    def _public_params(params: dict | None) -> dict[str, str]:
        """过滤掉名称像凭证的流水线变量，避免平台主动把密钥传给云效。"""
        if not isinstance(params, dict):
            return {}
        clean = {}
        for key, value in params.items():
            if _ENV_KEY.fullmatch(str(key)) and not _SECRET_KEY.search(str(key)):
                clean[str(key)] = str(value)[:500]
        return clean

    @staticmethod
    def _merge_stats(parsed: dict[str, int], raw: Any) -> dict[str, int]:
        """只采用 Allure 实际统计。回调里自报的数字不能覆盖报告文件。"""
        del raw
        stats = dict(parsed)
        if not stats["total"]:
            stats["total"] = stats["passed"] + stats["failed"] + stats["broken"] + stats["skipped"] + stats["unknown"]
        return stats

    @staticmethod
    def _duration(metadata: dict, execution: AutomationExecution) -> int | None:
        """读取执行耗时。"""
        value = metadata.get("duration_ms")
        if isinstance(value, int):
            return value
        return execution.duration_ms

    @staticmethod
    def _zip_history(html_dir) -> bytes:
        """打包 Allure history。没有历史文件时返回 404，让首次执行继续。"""
        import io
        import zipfile
        from pathlib import Path

        root = Path(html_dir)
        files: list[tuple[str, bytes]] = []
        history = root / "history"
        if history.is_dir():
            for path in history.rglob("*"):
                if path.is_file() and ".." not in path.relative_to(history).parts:
                    files.append((path.relative_to(history).as_posix(), path.read_bytes()))
        else:
            widgets = root / "widgets"
            for name in ("history-trend.json", "duration-trend.json", "categories-trend.json", "retry-trend.json"):
                path = widgets / name
                if path.is_file():
                    files.append((name, path.read_bytes()))
        if not files:
            raise not_found("没有可继承的 Allure history")
        buffer = io.BytesIO()
        with zipfile.ZipFile(buffer, "w") as archive:
            for name, data in files:
                archive.writestr(f"history/{name}", data)
        return buffer.getvalue()

    @staticmethod
    def _require_organization(row: AutomationIntegrationConfig) -> None:
        """中心版必须保留合法企业 ID。"""
        if row.deployment == "central" and not re.fullmatch(r"[A-Za-z0-9_-]{1,64}", row.organization_id or ""):
            raise bad_request("中心版必须填写云效企业 ID")

    @staticmethod
    def _commit_unique(db: Session, message: str) -> None:
        """把唯一约束冲突转换成可理解的 409。"""
        try:
            db.commit()
        except IntegrityError as exc:
            db.rollback()
            raise conflict(message) from exc
