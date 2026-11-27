"""缺陷项目级配置：队列灰度开关、积压提醒订阅与项目模板。

模板按版本管理：草稿可预览，发布后生效；同一项目至多一个 published 版本。
模板字段清单排除人员指派。
"""

from __future__ import annotations

from datetime import datetime

from sqlalchemy.orm import Session

from app.features.defects.models.project_setting import DefectProjectSetting
from app.features.defects.models.template import DefectTemplate
from app.features.defects.schemas import (
    BUG_CATEGORIES,
    DefectTemplateConfig,
)
from app.core.models.identity import User
from app.core.http.errors import bad_request, conflict, not_found
from app.platform.projects.services.access_service import check_writable, get_project_or_404
from app.core.security.roles import PROJECT_ROLE_EDITOR, has_project_role, project_role_for

# 模板可配置的缺陷事实字段；人员指派字段被明确排除。
TEMPLATE_FIELDS = (
    "title", "category", "description", "expected_result", "actual_result",
    "severity", "priority", "steps_to_reproduce", "environment", "affected_version",
    "api_method", "api_url", "api_request_headers", "api_request_body", "api_response",
)


def validate_template_config(config: DefectTemplateConfig) -> None:
    for field in config.hidden_fields:
        if field not in TEMPLATE_FIELDS:
            raise bad_request(f"模板字段不支持：{field}")
    for stage in (config.required_on_create, config.required_on_confirm, config.required_on_regression):
        for field in stage:
            if field not in TEMPLATE_FIELDS:
                raise bad_request(f"模板必填字段不支持：{field}")
            if field in config.hidden_fields:
                raise bad_request(f"字段 {field} 已隐藏，不能同时设为必填")
    for field, value in config.defaults.items():
        if field not in TEMPLATE_FIELDS:
            raise bad_request(f"模板默认值字段不支持：{field}")
        if field in ("severity", "priority") and value not in (1, 2, 3, 4):
            raise bad_request(f"{field} 默认值必须是 1-4")
        if field == "category" and value not in BUG_CATEGORIES:
            raise bad_request("category 默认值必须是前端、前后端或接口")
        if field in ("environment", "affected_version") and not isinstance(value, str):
            raise bad_request(f"{field} 默认值必须是文本")


class DefectProjectConfigService:
    """项目开关与模板的权限、版本与事务边界。"""

    # ---------------------------------------------------------------- 开关

    def get_setting(self, db: Session, project_id: int, user: User) -> DefectProjectSetting:
        get_project_or_404(db, project_id, user)
        row = db.get(DefectProjectSetting, project_id)
        if row is None:
            row = DefectProjectSetting(
                project_id=project_id, queue_enabled=True,
                reminder_enabled=False, stale_reminder_days=7,
            )
        return row

    def update_setting(
        self, db: Session, project_id: int, user: User, *,
        queue_enabled: bool | None, reminder_enabled: bool | None,
        stale_reminder_days: int | None,
    ) -> DefectProjectSetting:
        project = get_project_or_404(db, project_id, user)
        check_writable(db, project, user)
        if not has_project_role(project_role_for(db, project, user), PROJECT_ROLE_EDITOR):
            from app.core.http.errors import forbidden
            raise forbidden("修改缺陷项目开关需要项目管理员权限")
        row = db.get(DefectProjectSetting, project_id)
        if row is None:
            row = DefectProjectSetting(project_id=project_id)
            db.add(row)
        if queue_enabled is not None:
            row.queue_enabled = queue_enabled
        if reminder_enabled is not None:
            row.reminder_enabled = reminder_enabled
        if stale_reminder_days is not None:
            row.stale_reminder_days = stale_reminder_days
        row.updated_by = user.id
        db.commit()
        db.refresh(row)
        return row

    # ---------------------------------------------------------------- 模板

    def active_config(self, db: Session, project_id: int) -> dict | None:
        row = (
            db.query(DefectTemplate)
            .filter(DefectTemplate.project_id == project_id, DefectTemplate.status == "published")
            .order_by(DefectTemplate.version.desc())
            .first()
        )
        return row.config if row else None

    def list_templates(self, db: Session, project_id: int, user: User) -> list[DefectTemplate]:
        get_project_or_404(db, project_id, user)
        return (
            db.query(DefectTemplate)
            .filter(DefectTemplate.project_id == project_id)
            .order_by(DefectTemplate.version.desc())
            .all()
        )

    def _check_editor(self, db: Session, project_id: int, user: User):
        project = get_project_or_404(db, project_id, user)
        check_writable(db, project, user)
        if not has_project_role(project_role_for(db, project, user), PROJECT_ROLE_EDITOR):
            from app.core.http.errors import forbidden
            raise forbidden("管理缺陷模板需要项目管理员权限")
        return project

    def create_draft(
        self, db: Session, project_id: int, user: User, config: DefectTemplateConfig
    ) -> DefectTemplate:
        self._check_editor(db, project_id, user)
        validate_template_config(config)
        max_version = (
            db.query(DefectTemplate.version)
            .filter(DefectTemplate.project_id == project_id)
            .order_by(DefectTemplate.version.desc())
            .first()
        )
        row = DefectTemplate(
            project_id=project_id,
            version=(max_version[0] + 1) if max_version else 1,
            config=config.model_dump(),
            status="draft",
            created_by=user.id,
        )
        db.add(row)
        db.commit()
        db.refresh(row)
        return row

    def publish(self, db: Session, template_id: int, user: User) -> DefectTemplate:
        row = db.get(DefectTemplate, template_id)
        if row is None:
            raise not_found("模板不存在")
        self._check_editor(db, row.project_id, user)
        if row.status == "published":
            return row
        if row.status == "retired":
            raise conflict("已停用版本不能重新发布，请创建新草稿")
        validate_template_config(DefectTemplateConfig(**row.config))
        current = (
            db.query(DefectTemplate)
            .filter(DefectTemplate.project_id == row.project_id, DefectTemplate.status == "published")
            .all()
        )
        for previous in current:
            previous.status = "retired"
        row.status = "published"
        row.published_at = datetime.now()
        db.commit()
        db.refresh(row)
        return row

    def preview(self, config: DefectTemplateConfig) -> dict:
        """发布前预览：示例缺陷按模板默认值渲染，隐藏字段不出现在示例中。"""
        validate_template_config(config)
        sample = {
            "title": "示例：登录页提交后无响应",
            "category": "前端",
            "description": "点击登录按钮后页面无任何反馈",
            "steps_to_reproduce": "1. 打开登录页\n2. 输入账号密码\n3. 点击登录",
            "expected_result": "登录成功并跳转工作台",
            "actual_result": "按钮无响应，控制台报错",
            "severity": 3,
            "priority": 2,
            "environment": "test",
            "affected_version": "v1.0.0",
        }
        sample.update(config.defaults)
        sample = {key: value for key, value in sample.items() if key not in config.hidden_fields}
        return {
            "sample": sample,
            "hidden_fields": config.hidden_fields,
            "required_on_create": config.required_on_create,
            "required_on_confirm": config.required_on_confirm,
            "required_on_regression": config.required_on_regression,
        }