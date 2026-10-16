"""项目级安全执行环境开关。

读接口「没有行则返回默认值，不隐式插入」，避免只读用户也能在库里留下一行配置。
写接口需要 editor+；``allow_production`` 即使传 true 也照存，但执行器不读它，
生产永远拒绝（SECURITY_PRODUCTION_FORBIDDEN）。
"""

from __future__ import annotations

from sqlalchemy.orm import Session

from app.models.identity import User
from app.shared.errors import conflict
from app.shared.roles import PROJECT_ROLE_VIEWER, has_project_role, project_role_for
from app.shared.errors import not_found

from app.features.security_testing.models import SecurityProjectSetting
from app.features.security_testing.schemas import SecuritySettingRead, SecuritySettingUpdate
from app.features.security_testing.services._access import (
    get_project_or_404,
    require_manage_project,
)


class SecuritySettingService:
    """项目环境开关服务。所有 commit 都在这里发生。"""

    def get_setting(self, db: Session, project_id: int, user: User) -> SecuritySettingRead:
        """读取开关；没有行时返回默认值（dev/test 允许，staging/prod 拒绝），不插库。"""
        project = get_project_or_404(db, project_id, user)
        row = (
            db.query(SecurityProjectSetting)
            .filter(SecurityProjectSetting.project_id == project_id)
            .one_or_none()
        )
        if row is None:
            return SecuritySettingRead(project_id=project_id)
        return self._to_response(row)

    def update_setting(
        self, db: Session, project_id: int, body: SecuritySettingUpdate, *, actor: User,
    ) -> SecuritySettingRead:
        """更新开关。乐观锁 revision 不匹配返回 409。"""
        project = require_manage_project(db, project_id, actor)
        row = (
            db.query(SecurityProjectSetting)
            .filter(SecurityProjectSetting.project_id == project_id)
            .one_or_none()
        )
        if row is None:
            if body.revision is not None:
                # 客户端带了 revision 但库里没有行，说明并发创建了两次。
                raise conflict("配置已被他人修改，请刷新后重试")
            row = SecurityProjectSetting(project_id=project_id)
            db.add(row)

        data = body.model_dump(exclude_unset=True, exclude_none=True)
        if data.get("revision") == row.revision:
            data.pop("revision", None)
        elif "revision" in data:
            raise conflict("配置已被他人修改，请刷新后重试")

        if not data:
            return self._to_response(row)

        for field in ("allow_dev", "allow_test", "allow_staging", "allow_production"):
            if field in data:
                # allow_production 照存但永不生效：这里只做类型收敛，不做语义判断。
                setattr(row, field, bool(data[field]))
        row.updated_by = actor.id
        # 新建的行 revision 还是 None（server_default=1 要等 flush 才落），按 1 起算，
        # 否则第一次保存会得到 revision=1，看起来像没变过。
        row.revision = (row.revision or 1) + 1
        db.commit()
        db.refresh(row)
        return self._to_response(row)

    @staticmethod
    def _to_response(row: SecurityProjectSetting) -> SecuritySettingRead:
        return SecuritySettingRead.model_validate(row)
