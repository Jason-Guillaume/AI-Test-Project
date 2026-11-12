"""自动化测试中心业务服务。

负责云效配置、触发、状态同步、报告接收和飞书通知。
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
from datetime import datetime, timedelta
from typing import Any

from sqlalchemy import or_
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.core.config import settings
from app.core.http.errors import bad_request, conflict, not_found
from app.core.http.pagination import paginate
from app.core.models.identity import User
from app.core.security.crypto import decrypt_secret, encrypt_secret
from app.features.automation_center.models.entities import (
    AutomationArtifact,
    AutomationCallbackReceipt,
    AutomationExecution,
    AutomationIntegrationConfig,
    AutomationPipeline,
    AutomationProject,
    AutomationReport,
    AutomationReportGrant,
)
from app.features.automation_center.providers.yunxiao_client import YunxiaoClient, YunxiaoError
from app.features.automation_center.schemas import (
    AutomationProjectCreate,
    AutomationProjectListResponse,
    AutomationProjectResponse,
    AutomationProjectUpdate,
    CallbackResponse,
    ConnectionTestResponse,
    ExecutionListResponse,
    ExecutionResponse,
    ExecutionTrigger,
    IntegrationCreate,
    IntegrationListResponse,
    IntegrationResponse,
    IntegrationUpdate,
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

logger = logging.getLogger(__name__)
_TRIGGER = {"1": "EXTERNAL", "2": "SCHEDULE", "3": "CODE_PUSH", "5": "EXTERNAL", "6": "WEBHOOK"}
_ENV_KEY = re.compile(r"[A-Za-z_][A-Za-z0-9_]{0,63}")
_SECRET_KEY = re.compile(r"(?i)secret|token|password|webhook")
_SECRET_VALUE = re.compile(r"(?i)(secret|token|password|webhook_url)\s*[:=]\s*\S+")
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
        """列出当前业务项目的云效接入配置。"""
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
        row = AutomationIntegrationConfig(
            project_id=project_id,
            name=body.name.strip(),
            api_base_url=body.api_base_url,
            organization_id=body.organization_id,
            deployment=body.deployment,
            access_token_encrypted=encrypt_secret(body.access_token),
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
        if body.name is not None:
            row.name = body.name.strip()
        if body.api_base_url is not None:
            row.api_base_url = body.api_base_url
        if body.organization_id is not None:
            row.organization_id = body.organization_id
        if body.deployment is not None:
            row.deployment = body.deployment
        if body.default_timeout_seconds is not None:
            row.default_timeout_seconds = body.default_timeout_seconds
        if body.access_token:
            if len(body.access_token) < 8:
                raise bad_request("云效访问令牌过短")
            row.access_token_encrypted = encrypt_secret(body.access_token)
        if body.callback_secret:
            if len(body.callback_secret) < 8:
                raise bad_request("回调密钥过短")
            row.callback_secret_encrypted = encrypt_secret(body.callback_secret)
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
        delete_resource(db, "automation_integration", config_id, actor=actor, project_id=row.project_id)

    def rotate_callback_key(self, db: Session, config_id: int, actor: User) -> IntegrationResponse:
        """更换回调标识。旧流水线在更新地址前不能再回传。"""
        row = self._config_for_write(db, config_id, actor)
        row.callback_key = secrets.token_urlsafe(18)
        db.commit()
        db.refresh(row)
        return self._integration_response(row)

    def test_connection(
        self, db: Session, config_id: int, actor: User, pipeline_id: str,
    ) -> ConnectionTestResponse:
        """用官方运行列表接口验证令牌、企业和流水线标识。"""
        row = self._config_for_write(db, config_id, actor)
        try:
            runs = self._client(row).list_runs(pipeline_id, per_page=1)
        except YunxiaoError as exc:
            raise bad_request(str(exc)) from exc
        return ConnectionTestResponse(ok=True, message="已连接云效流水线", sample_run_count=len(runs))

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
            pipeline_params=self._public_params(body.pipeline_params),
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
            if not re.fullmatch(r"[A-Za-z0-9_-]{1,64}", body.pipeline_id):
                raise bad_request("流水线 ID 不合法")
            pipeline = self._default_pipeline(db, row)
            pipeline.pipeline_id = body.pipeline_id
            if body.pipeline_name is not None:
                pipeline.name = body.pipeline_name.strip() or body.pipeline_id
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
        """创建独立执行记录并调用云效运行接口。"""
        project = self._automation_for(db, automation_project_id, actor, write=True)
        if not project.enabled:
            raise bad_request("自动化项目已停用")
        config = db.get(AutomationIntegrationConfig, project.integration_config_id)
        if config is None:
            raise not_found("接入配置不存在")
        pipeline = self._pipeline_for_trigger(db, project, body.pipeline_id)
        execution = AutomationExecution(
            project_id=project.project_id,
            automation_project_id=project.id,
            pipeline_binding_id=pipeline.id,
            external_pipeline_id=pipeline.pipeline_id,
            trigger_source="MANUAL",
            status="PENDING",
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
        params = self._pipeline_params(config, project, pipeline, execution)
        execution.run_params = params
        try:
            run_id = self._client(config).create_run(pipeline.pipeline_id, params)
        except YunxiaoError as exc:
            execution.status = "FAILED"
            execution.error_message = str(exc)[:500]
            execution.finished_at = datetime.now()
            execution.notify_status = "SKIPPED"
            db.commit()
            raise bad_request(str(exc)) from exc
        execution.pipeline_run_id = run_id
        execution.status = "RUNNING"
        execution.external_status = "RUNNING"
        execution.started_at = datetime.now()
        execution.timeout_at = datetime.now() + timedelta(seconds=project.timeout_seconds)
        db.commit()
        db.refresh(execution)
        return self._execution_response(db, execution)

    def list_executions(
        self, db: Session, project_id: int, actor: User, *, page: int, page_size: int,
        automation_project_id: int | None, status: str | None, branch: str | None,
        environment_name: str | None, started_from: datetime | None, started_to: datetime | None,
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

    def cancel(self, db: Session, execution_id: int, actor: User) -> ExecutionResponse:
        """请求云效终止运行。云效未确认时不在本地伪装成已取消。"""
        row = self._execution_for(db, execution_id, actor, write=True)
        if row.status not in {"PENDING", "RUNNING"}:
            raise bad_request("当前状态不能取消")
        if row.pipeline_run_id:
            config, pipeline_id = self._execution_client_args(db, row)
            try:
                stopped = self._client(config).stop_run(pipeline_id, row.pipeline_run_id)
            except YunxiaoError as exc:
                raise bad_request(str(exc)) from exc
            if not stopped:
                raise bad_request("云效未确认终止运行")
        self._transition(row, "CANCELLED")
        row.external_status = "CANCELLED"
        db.commit()
        self._notify(db, row.id)
        db.refresh(row)
        return self._execution_response(db, row)

    def sync_execution(self, db: Session, execution_id: int, actor: User) -> ExecutionResponse:
        """立即向云效查询一次运行状态。"""
        row = self._execution_for(db, execution_id, actor, write=True)
        self._sync_one(db, row.id)
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
            self._apply_callback_metadata(execution, metadata, report)
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
        """轮询运行中的实例，并发现平台外触发的新运行。"""
        active = (
            db.query(AutomationExecution.id)
            .filter(AutomationExecution.status.in_(["PENDING", "RUNNING"]))
            .filter(AutomationExecution.pipeline_run_id.isnot(None))
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

    def _sync_one(self, db: Session, execution_id: int) -> None:
        """查询云效并更新一条执行。网络调用放在行锁释放之后。"""
        execution = db.get(AutomationExecution, execution_id)
        if execution is None or execution.status in TERMINAL_STATUSES or not execution.pipeline_run_id:
            return
        if execution.timeout_at and execution.timeout_at <= datetime.now():
            self._mark_timeout(db, execution)
            return
        config, pipeline_id = self._execution_client_args(db, execution)
        run_id = execution.pipeline_run_id
        db.commit()
        try:
            payload = self._client(config).get_run(pipeline_id, run_id)
        except YunxiaoError as exc:
            execution = db.get(AutomationExecution, execution_id)
            if execution is not None:
                execution.error_message = str(exc)[:500]
                execution.last_sync_at = datetime.now()
                db.commit()
            return
        execution = db.get(AutomationExecution, execution_id)
        if execution is None:
            return
        mapped = map_pipeline_status(payload)
        execution.external_status = str(payload.get("status") or mapped)[:40]
        execution.last_sync_at = datetime.now()
        if execution.status != "FAILED" or mapped != "SUCCESS":
            self._transition(execution, mapped)
        db.commit()
        if execution.status in TERMINAL_STATUSES:
            self._notify(db, execution.id)

    def _mark_timeout(self, db: Session, execution: AutomationExecution) -> None:
        """本地超时后尝试终止云效运行，并把执行记为超时。"""
        if execution.pipeline_run_id:
            try:
                config, pipeline_id = self._execution_client_args(db, execution)
                self._client(config).stop_run(pipeline_id, execution.pipeline_run_id)
            except YunxiaoError:
                logger.warning("超时后终止云效运行失败 execution=%s", execution.id)
        self._transition(execution, "TIMEOUT")
        execution.last_sync_at = datetime.now()
        db.commit()
        self._notify(db, execution.id)

    def _discover(self, db: Session) -> None:
        """把云效上新出现、且不是本平台触发的运行登记为执行记录。"""
        projects = (
            db.query(AutomationProject).filter_by(enabled=True).order_by(AutomationProject.id.asc()).limit(10).all()
        )
        for project in projects:
            config = db.get(AutomationIntegrationConfig, project.integration_config_id)
            pipeline = db.query(AutomationPipeline).filter_by(automation_project_id=project.id, is_default=True).first()
            if config is None or pipeline is None:
                continue
            try:
                runs = self._client(config).list_runs(pipeline.pipeline_id, per_page=10)
            except YunxiaoError as exc:
                logger.warning("读取云效运行列表失败 project=%s: %s", project.id, exc)
                continue
            for item in runs:
                self._import_remote_run(db, project, pipeline, item)
        try:
            db.commit()
        except IntegrityError:
            db.rollback()

    def _import_remote_run(self, db: Session, project: AutomationProject, pipeline: AutomationPipeline, item: dict) -> None:
        """登记一条平台外的运行。没有开始时间的记录不导入，避免把旧历史全部拉进来。"""
        run_id = item.get("pipelineRunId")
        start = item.get("startTime")
        if run_id is None or not isinstance(start, int):
            return
        if start < int(project.created_at.timestamp() * 1000) or start < int((datetime.now() - timedelta(hours=24)).timestamp() * 1000):
            return
        exists = db.query(AutomationExecution.id).filter_by(
            automation_project_id=project.id, pipeline_run_id=str(run_id),
        ).first()
        if exists:
            return
        status = map_pipeline_status(str(item.get("status") or "RUNNING"))
        execution = AutomationExecution(
            project_id=project.project_id,
            automation_project_id=project.id,
            pipeline_binding_id=pipeline.id,
            external_pipeline_id=pipeline.pipeline_id,
            pipeline_run_id=str(run_id),
            trigger_source=_TRIGGER.get(str(item.get("triggerMode")), "EXTERNAL"),
            status=status,
            branch=project.default_branch,
            environment_name=project.default_environment,
            pytest_args=project.pytest_args,
            test_tags=project.test_tags,
            test_scope=project.test_scope,
            external_status=str(item.get("status") or status)[:40],
            started_at=datetime.fromtimestamp(start / 1000),
            finished_at=datetime.now() if status in TERMINAL_STATUSES else None,
            notify_status="WAITING",
        )
        db.add(execution)

    # ---------------------------------------------------------------- 内部

    def _notify(self, db: Session, execution_id: int) -> None:
        """报告就绪或终态等待超时后发送飞书卡片。已发送的执行不会再发。"""
        execution = (
            db.query(AutomationExecution).filter_by(id=execution_id).with_for_update().one_or_none()
        )
        if execution is None or execution.notify_status in {"SENT", "SKIPPED"}:
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

    def _apply_callback_metadata(self, execution, metadata: dict, report: AutomationReport | None) -> None:
        """用回传元数据补充执行信息，并把用例失败反映到执行状态。"""
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
        incoming = map_pipeline_status(str(metadata.get("status") or execution.external_status or "SUCCESS"))
        failed = report.failed_cases if report else int((metadata.get("stats") or {}).get("failed") or 0)
        broken = report.broken_cases if report else int((metadata.get("stats") or {}).get("broken") or 0)
        self._transition(execution, apply_test_outcome(incoming, failed=failed, broken=broken))
        execution.external_status = str(metadata.get("status") or incoming)[:40]
        if execution.started_at is None:
            execution.started_at = datetime.now()

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
        """找到平台已创建的执行；代码提交触发且本地没有记录时新建。"""
        project = self._callback_project(db, config, metadata)
        execution_id = metadata.get("execution_id")
        run_id = metadata.get("pipeline_run_id")
        execution = None
        if execution_id is not None:
            execution = db.get(AutomationExecution, int(execution_id))
            if execution is None or execution.automation_project_id != project.id:
                raise not_found("执行记录不存在")
        elif run_id is not None:
            execution = db.query(AutomationExecution).filter_by(
                automation_project_id=project.id, pipeline_run_id=str(run_id),
            ).first()
        if execution is None:
            pipeline = self._default_pipeline(db, project)
            execution = AutomationExecution(
                project_id=project.project_id,
                automation_project_id=project.id,
                pipeline_binding_id=pipeline.id,
                external_pipeline_id=str(metadata.get("pipeline_id") or pipeline.pipeline_id),
                pipeline_run_id=str(run_id) if run_id is not None else None,
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
        return execution

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

    def _pipeline_params(self, config, project, pipeline, execution) -> dict[str, Any]:
        """组装云效运行参数。只放非敏感变量，回调密钥由流水线变量组单独保存。"""
        envs = {
            "TEST_ENV": execution.environment_name,
            "PYTEST_ARGS": execution.pytest_args,
            "TEST_TAGS": execution.test_tags,
            "TEST_SCOPE": execution.test_scope,
            "AUTOMATION_EXECUTION_ID": str(execution.id),
            "AUTOMATION_PROJECT_ID": str(project.id),
            "AUTOMATION_CALLBACK_KEY": config.callback_key,
        }
        base = settings.PUBLIC_APP_BASE_URL.strip().rstrip("/")
        if base.startswith("http://") or base.startswith("https://"):
            envs["AUTOMATION_CALLBACK_URL"] = f"{base}/api/v1/automation-callbacks/{config.callback_key}"
            envs["AUTOMATION_HISTORY_URL"] = (
                f"{base}/api/v1/automation-callbacks/{config.callback_key}/history"
                f"?automation_project_id={project.id}"
            )
        envs.update(self._public_params(project.pipeline_params))
        envs.update(self._public_params(pipeline.extra_params))
        envs = {key: value for key, value in envs.items() if value}
        params: dict[str, Any] = {"envs": envs, "comment": f"测试平台执行 {execution.id}"}
        if execution.branch:
            params["branchModeBranchs"] = [execution.branch]
            if project.repository_url:
                params["runningBranchs"] = {project.repository_url: execution.branch}
        return params

    def _client(self, config: AutomationIntegrationConfig) -> YunxiaoClient:
        """用解密后的令牌创建客户端。令牌不进入日志。"""
        return YunxiaoClient(
            base_url=config.api_base_url,
            token=decrypt_secret(config.access_token_encrypted),
            organization_id=config.organization_id,
            deployment=config.deployment,
        )

    def _execution_client_args(self, db, execution: AutomationExecution):
        """取出调用云效所需的配置和流水线 ID。"""
        project = db.get(AutomationProject, execution.automation_project_id)
        if project is None:
            raise not_found("自动化项目不存在")
        config = db.get(AutomationIntegrationConfig, project.integration_config_id)
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
        return IntegrationResponse(
            id=row.id, project_id=row.project_id, name=row.name, api_base_url=row.api_base_url,
            organization_id=row.organization_id, deployment=row.deployment,
            token_configured=bool(row.access_token_encrypted), callback_key=row.callback_key,
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
        return AutomationProjectResponse(
            id=row.id, project_id=row.project_id, integration_config_id=row.integration_config_id,
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
            pipeline_run_id=row.pipeline_run_id, trigger_source=row.trigger_source, status=row.status,
            branch=row.branch, environment_name=row.environment_name, pytest_args=row.pytest_args,
            test_tags=row.test_tags, test_scope=row.test_scope, git_commit=row.git_commit,
            external_status=row.external_status, log_excerpt=row.log_excerpt, error_message=row.error_message,
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
            git_commit=execution.git_commit if execution else "", generated_at=row.generated_at, created_at=row.created_at,
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
        """回传统计优先，缺失字段用 Allure widgets 补齐。"""
        stats = dict(parsed)
        if isinstance(raw, dict):
            for key in stats:
                if key in raw:
                    stats[key] = int(raw.get(key) or 0)
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
