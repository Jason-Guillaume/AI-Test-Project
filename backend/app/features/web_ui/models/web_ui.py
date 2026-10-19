"""Web UI 扩展表；用例与步骤仍使用 TestCase/TestStep，执行仍使用 TestRun/CaseExecution。"""
from sqlalchemy import Column, DateTime, ForeignKey, Integer, JSON, String, Text, UniqueConstraint
from sqlalchemy.sql import func
from app.shared.database import Base


class PageObject(Base):
    """项目内页面对象：命名元素仅保存声明式定位器。"""
    __tablename__ = "web_page_object"
    __table_args__ = (UniqueConstraint("project_id", "name", name="uq_web_page_project_name"),)
    id = Column(Integer, primary_key=True)
    project_id = Column(Integer, ForeignKey("project.id", ondelete="CASCADE"), nullable=False, index=True)
    name = Column(String(200), nullable=False)
    path = Column(String(2000), nullable=False)
    elements = Column(JSON, nullable=False)
    revision = Column(Integer, nullable=False, default=1, server_default="1")
    created_at = Column(DateTime, nullable=False, server_default=func.now())


class WebAuthProfile(Base):
    """加密测试账号或人工完成扫码后的 storage_state；API 永不返回明文。"""
    __tablename__ = "web_auth_profile"
    id = Column(Integer, primary_key=True)
    project_id = Column(Integer, ForeignKey("project.id", ondelete="CASCADE"), nullable=False, index=True)
    environment_id = Column(Integer, ForeignKey("environment.id", ondelete="CASCADE"), nullable=False)
    name = Column(String(200), nullable=False)
    secret_encrypted = Column(Text, nullable=False)
    expires_at = Column(DateTime, nullable=False)
    created_by = Column(Integer, ForeignKey("user.id", ondelete="SET NULL"))
    created_at = Column(DateTime, nullable=False, server_default=func.now())


class WebCase(Base):
    """既有用例的 Web 执行配置与人工确认指纹，修改依赖后必须重新确认。"""
    __tablename__ = "web_case"
    test_case_id = Column(Integer, ForeignKey("test_case.id", ondelete="CASCADE"), primary_key=True)
    auth_profile_id = Column(Integer, ForeignKey("web_auth_profile.id", ondelete="SET NULL"))
    timeout_ms = Column(Integer, nullable=False, default=30000, server_default="30000")
    total_timeout_ms = Column(Integer, nullable=False, default=120000, server_default="120000")
    confirmed_digest = Column(String(64))
    confirmed_by = Column(Integer, ForeignKey("user.id", ondelete="SET NULL"))


class WebArtifact(Base):
    """截图和脱敏 Trace 加密落库；每个附件继承项目权限，不暴露文件系统路径。"""
    __tablename__ = "web_artifact"
    id = Column(String(36), primary_key=True)
    project_id = Column(Integer, ForeignKey("project.id", ondelete="CASCADE"), nullable=False, index=True)
    test_case_id = Column(Integer, ForeignKey("test_case.id", ondelete="SET NULL"))
    case_execution_id = Column(Integer, ForeignKey("case_execution.id", ondelete="CASCADE"), index=True)
    kind = Column(String(20), nullable=False)
    content_encrypted = Column(Text, nullable=False)
    created_at = Column(DateTime, nullable=False, server_default=func.now())
