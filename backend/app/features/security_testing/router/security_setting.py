"""资源路由；认证、响应模型与原 method/path 保持不变。"""

from __future__ import annotations

from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session
from app.features.security_testing.schemas import SecuritySettingRead, SecuritySettingUpdate
from app.core.models.identity import User
from app.core.security.auth import get_current_user
from app.core.database.session import get_db
from app.features.security_testing.router.dependencies import _SETTING


router = APIRouter()


@router.get("/projects/{project_id}/security-setting", response_model=SecuritySettingRead)
def get_security_setting(
    project_id: int,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
) -> SecuritySettingRead:
    """获取安全`setting`。"""
    return _SETTING.get_setting(db, project_id, user)


@router.put("/projects/{project_id}/security-setting", response_model=SecuritySettingRead)
def update_security_setting(
    project_id: int,
    body: SecuritySettingUpdate,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
) -> SecuritySettingRead:
    """更新安全`setting`。"""
    return _SETTING.update_setting(db, project_id, body, actor=user)
