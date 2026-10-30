"""运行时入口服务（Phase B）：手工试跑、Provider 试跑、手工清理。

路由只做参数解析，这里的职责是：
- 复用管理面的归属与可见性校验（不重复实现一套权限判断）；
- 解析执行环境；
- 调 ``DataFactory`` / ``CleanupRunner``。

手工试跑统一按 scope=CASE 走：不写项目级缓存，避免试跑污染项目级数据；
若 Fixture 的 ``cleanup_policy`` 是 AFTER_CASE，试跑结束也执行 Cleanup。
"""

from __future__ import annotations

from sqlalchemy.orm import Session

from app.features.test_data.models.execution import DataExecution
from app.features.test_data.models.fixture import Fixture
from app.features.test_data.models.provider import DataProvider
from app.features.test_data.runtime.cleanup_runner import CleanupRunner
from app.features.test_data.runtime.data_factory import DataFactory
from app.features.test_data.schemas import (
    DataProviderTestRequest,
    FixtureGenerateRequest,
)
from app.platform.projects.services.access_service import get_project_or_404
from app.platform.environment_configuration.services.environment_service import (
    list_project_environment_options,
    resolve_project_environment,
)
from app.core.models.configuration import Environment
from app.core.models.identity import User
from app.core.http.errors import (
    CODE_DATA_EXECUTION_NOT_FOUND,
    AppError,
    bad_request,
    not_found,
)


class RuntimeService:
    """造数运行时入口。无状态，路由层复用单例。"""

    def __init__(self) -> None:
        """初始化对象状态。"""
        self._factory = DataFactory()
        self._cleanup = CleanupRunner()

    # ---------------------------------------------------------------- 试跑 固定数据 Fixture

    def generate(
        self,
        db: Session,
        fixture_id: int,
        body: FixtureGenerateRequest,
        *,
        actor: User,
    ) -> DataExecution:
        """手工试跑一个 Fixture（含依赖链）。cleanup_policy=AFTER_CASE 时试跑完清理。

        ``body.scope`` 只接收不生效：试跑一律按 CASE 处理，不写项目缓存。
        """
        fixture = self._load_fixture_or_404(db, fixture_id, actor)
        environment = self._load_environment(db, fixture.project_id, body.environment_id)

        result = self._factory.generate(
            db,
            fixture_id=fixture_id,
            project_id=fixture.project_id,
            environment=environment,
            actor=actor,
            scope="CASE",
            variables=dict(body.variables or {}),
        )

        if fixture.cleanup_policy == "AFTER_CASE":
            self._cleanup.run_data_execution(
                db, data_execution_id=result.data_execution_id, actor=actor,
            )

        return db.get(DataExecution, result.data_execution_id)

    # ---------------------------------------------------------------- 试跑 Provider

    def test_provider(
        self,
        db: Session,
        provider_id: int,
        body: DataProviderTestRequest,
        *,
        actor: User,
    ) -> DataExecution:
        """手工试跑一个 Provider，走完整安全策略（与生产同一条路径）。"""
        provider = self._load_provider_or_404(db, provider_id, actor)
        environment = self._load_environment(db, provider.project_id, body.environment_id)
        return self._factory.test_provider(
            db,
            provider_id=provider_id,
            project_id=provider.project_id,
            environment=environment,
            actor=actor,
            variables=dict(body.variables or {}),
        )

    # ---------------------------------------------------------------- 手工清理

    def cleanup(
        self,
        db: Session,
        fixture_id: int,
        *,
        actor: User,
    ) -> DataExecution:
        """手工执行一个 Fixture 的 CLEANUP 步骤。"""
        fixture = self._load_fixture_or_404(db, fixture_id, actor)
        environment = self._load_latest_environment(db, fixture.project_id)
        return self._cleanup.cleanup_fixture(
            db,
            fixture_id=fixture_id,
            project_id=fixture.project_id,
            environment=environment,
            actor=actor,
        )

    def cleanup_execution(
        self,
        db: Session,
        data_execution_id: int,
        *,
        actor: User,
    ) -> DataExecution:
        """按一次造数记录执行清理。

        Cleanup 失败只写 ``cleanup_*`` 列，**不覆盖** ``status`` /
        ``error_code`` / ``error_message``——造数成功但清理失败的记录仍显示 READY。
        """
        data_exec = db.get(DataExecution, data_execution_id)
        if data_exec is None:
            raise AppError(
                "造数执行记录不存在",
                status_code=404,
                code=CODE_DATA_EXECUTION_NOT_FOUND,
            )
        get_project_or_404(db, data_exec.project_id, actor)
        result = self._cleanup.run_data_execution(
            db, data_execution_id=data_execution_id, actor=actor,
        )
        return db.get(DataExecution, data_execution_id)

    # ---------------------------------------------------------------- 归属与环境解析

    @staticmethod
    def _load_fixture_or_404(db: Session, fixture_id: int, user: User) -> Fixture:
        """取 Fixture 并校验可见性（与 FixtureService.get_fixture 同口径）。"""
        row = db.get(Fixture, fixture_id)
        if row is None:
            raise not_found("Fixture 不存在")
        get_project_or_404(db, row.project_id, user)
        return row

    @staticmethod
    def _load_provider_or_404(db: Session, provider_id: int, user: User) -> DataProvider:
        """取 Provider 并校验可见性（与 ProviderService.get_provider 同口径）。"""
        row = db.get(DataProvider, provider_id)
        if row is None:
            raise not_found("数据 Provider 不存在")
        get_project_or_404(db, row.project_id, user)
        return row

    @staticmethod
    def _load_environment(db: Session, project_id: int, environment_id: int) -> Environment:
        """加载环境。"""
        return resolve_project_environment(db, project_id, environment_id)

    @staticmethod
    def _load_latest_environment(db: Session, project_id: int) -> Environment:
        """手工清理时请求体不带环境：取项目最近一次造数记录的环境，没有就用默认环境。"""
        latest = (
            db.query(DataExecution)
            .filter(
                DataExecution.project_id == project_id,
                DataExecution.environment_id.isnot(None),
            )
            .order_by(DataExecution.id.desc())
            .first()
        )
        if latest is not None:
            try:
                return resolve_project_environment(db, project_id, latest.environment_id)
            except AppError:
                pass
        options = list_project_environment_options(db, project_id)
        default = next((row for row in options if row["is_default"]), None)
        if default is None:
            raise bad_request("没有可用的执行环境，无法执行清理")
        return resolve_project_environment(db, project_id, default["id"])


__all__ = ["RuntimeService"]
