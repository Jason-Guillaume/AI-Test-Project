"""security_testing 资源契约；字段、默认值、校验和 wire 名称保持不变。"""

from __future__ import annotations

from datetime import datetime
from pydantic import BaseModel
from app.features.security_testing.schemas.common import _ORM


class SecuritySettingRead(_ORM):
    """项目级环境开关。``production_enforced`` 说明生产永远拒绝，与 allow_production 无关。"""

    id: int | None = None
    project_id: int | None = None
    allow_dev: bool = True
    allow_test: bool = True
    allow_staging: bool = False
    allow_production: bool = False
    # 恒为 false：列上即使存了 true，执行器也不读它。
    production_enforced: bool = False
    updated_by: int | None = None
    created_at: datetime | None = None
    updated_at: datetime | None = None
    revision: int = 1


class SecuritySettingUpdate(BaseModel):
    """修改环境开关。``allow_production`` 可传入但永不生效（存库后仍拒绝）。"""

    allow_dev: bool | None = None
    allow_test: bool | None = None
    allow_staging: bool | None = None
    allow_production: bool | None = None
    revision: int | None = None
