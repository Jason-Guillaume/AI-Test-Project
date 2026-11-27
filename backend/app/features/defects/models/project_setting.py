"""缺陷项目级开关：队列灰度与积压提醒订阅。"""

from sqlalchemy import Boolean, Column, DateTime, ForeignKey, Integer
from sqlalchemy.sql import func, text

from app.core.database.base import Base


class DefectProjectSetting(Base):
    """每个项目一行；不存在时按默认值（队列启用、提醒关闭）处理。"""

    __tablename__ = "defect_project_setting"
    __table_args__ = ({"comment": "缺陷项目级开关：队列灰度与积压提醒订阅"},)

    project_id = Column(
        Integer, ForeignKey("project.id", ondelete="CASCADE"), primary_key=True,
    )
    queue_enabled = Column(
        Boolean, nullable=False, default=True, server_default=text("true"),
        comment="界面灰度开关；服务端指派停用不受此开关影响",
    )
    reminder_enabled = Column(
        Boolean, nullable=False, default=False, server_default=text("false"),
        comment="是否订阅长期待确认/待验证积压提醒",
    )
    stale_reminder_days = Column(
        Integer, nullable=False, default=7, server_default=text("7"),
        comment="积压提醒阈值（天）",
    )
    updated_by = Column(Integer, ForeignKey("user.id", ondelete="SET NULL"), nullable=True)
    updated_at = Column(DateTime, nullable=False, server_default=func.now(), onupdate=func.now())