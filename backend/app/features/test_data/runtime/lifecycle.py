"""数据生命周期编排（Phase C）：PREPARE → SETUP → EXECUTE → ASSERT → CLEANUP。

本模块是 TestRun / 用例与 Data Factory 之间唯一的接缝，两侧都不自己调 Provider：

- ``prepare_run``：RUN 作用域的 Fixture，整轮只生成一次（§12.2）；
- ``setup_case``：CASE 作用域的 Fixture，每条用例一份；
- ``cleanup_case`` / ``cleanup_run``：按 ``cleanup_policy`` 决定清理时机；
- 缓存按 scope 键共享，DIRTY 不可复用（§14）。

失败语义（§16）：
- 造数失败抛 ``AppError``，RunService 转成用例 ``ERROR`` —— **不是 FAILED**；
- 清理失败只写 ``cleanup_*``，``status`` / ``error_code`` / ``error_message`` 一律不动。

返回值约定：``{fixture_key: {output_name: value}}``。字典里的值**未脱敏**，
只在进程内注入 ExecutionContext；落库（缓存行、执行快照）一律经 Masker。
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timedelta
from typing import Any

from sqlalchemy.orm import Session

from app.features.business.executors.sensitive import SensitiveDataMasker
from app.features.test_data.models.execution import (
    DataExecution,
    FixtureCache,
    FixtureExecution,
)
from app.features.test_data.models.fixture import Fixture
from app.features.test_data.runtime.cleanup_runner import CleanupRunner
from app.features.test_data.runtime.data_factory import DataFactory
from app.models.configuration import Environment
from app.models.identity import User
from app.shared.errors import (
    CODE_DATA_RESOLVE_FAILED,
    CODE_FIXTURE_DISABLED,
    CODE_FIXTURE_NOT_FOUND,
    AppError,
)

#: PROJECT 作用域缓存的默认有效期（§14：第一阶段用常量，写在缓存行上）。
PROJECT_CACHE_TTL = timedelta(hours=24)

#: 这两种策略不自动清理（MANUAL 手工清、NEVER 不清）。
NO_AUTO_CLEANUP_POLICIES = {"MANUAL", "NEVER"}


@dataclass
class CleanupOutcome:
    """一次清理阶段的汇总，供 RunService 写 ``case_execution.cleanup_*``。"""

    cleaned: int = 0
    failures: list[str] = field(default_factory=list)

    @property
    def failed(self) -> bool:
        return bool(self.failures)


def scope_key_for(
    scope: str,
    *,
    test_run_id: int | None = None,
    case_execution_id: int | None = None,
    project_id: int | None = None,
) -> str:
    """§14 缓存键：CASE=`case_execution:{id}`，RUN=`test_run:{id}`，
    PROJECT=`project:{id}`，GLOBAL=`global`。"""
    if scope == "RUN":
        return f"test_run:{test_run_id}"
    if scope == "CASE":
        return f"case_execution:{case_execution_id}"
    if scope == "PROJECT":
        return f"project:{project_id}"
    return "global"


class LifecycleManager:
    """造数生命周期编排器。无状态，进程级复用。"""

    def __init__(self, masker: SensitiveDataMasker | None = None) -> None:
        self._masker = masker or SensitiveDataMasker()
        self._factory = DataFactory(self._masker)
        self._cleanup = CleanupRunner(self._masker)

    # ---------------------------------------------------------------- PREPARE / SETUP

    def prepare_run(
        self,
        db: Session,
        *,
        project_id: int,
        test_run_id: int,
        environment: Environment,
        actor: User,
        fixture_keys: list[str],
    ) -> dict[str, dict[str, Any]]:
        """RUN 级准备：整轮只生成一次，后续用例命中缓存。"""
        outputs: dict[str, dict[str, Any]] = {}
        for key in fixture_keys:
            outputs.update(
                self._resolve(
                    db, fixture_key=key, project_id=project_id,
                    environment=environment, actor=actor,
                    test_run_id=test_run_id, case_execution_id=None, inherited=outputs,
                )
            )
        return outputs

    def setup_case(
        self,
        db: Session,
        *,
        project_id: int,
        case_execution_id: int,
        test_run_id: int | None = None,
        environment: Environment,
        actor: User,
        fixture_keys: list[str],
    ) -> dict[str, dict[str, Any]]:
        """CASE 级准备：只属于这一条用例执行。"""
        outputs: dict[str, dict[str, Any]] = {}
        for key in fixture_keys:
            outputs.update(
                self._resolve(
                    db, fixture_key=key, project_id=project_id,
                    environment=environment, actor=actor,
                    test_run_id=test_run_id, case_execution_id=case_execution_id,
                    inherited=outputs,
                )
            )
        return outputs

    def _resolve(
        self,
        db: Session,
        *,
        fixture_key: str,
        project_id: int,
        environment: Environment,
        actor: User,
        test_run_id: int | None,
        case_execution_id: int | None,
        inherited: dict[str, dict[str, Any]],
    ) -> dict[str, dict[str, Any]]:
        """生成（或复用缓存）一个 Fixture，返回 ``{fixture_key: outputs}``。"""
        fixture = self._load_visible_by_key(db, fixture_key=fixture_key, project_id=project_id)
        if (fixture.status or "") != "ACTIVE":
            # 只有 ACTIVE 能被执行（§16.2）；执行失败语义是 ERROR，不是 FAILED。
            raise AppError(
                f"Fixture {fixture.fixture_key} 状态为 {fixture.status}，只有 ACTIVE 可执行",
                status_code=400,
                code=CODE_FIXTURE_DISABLED,
            )
        scope = fixture.scope or "CASE"
        scope_key = scope_key_for(
            scope, test_run_id=test_run_id, case_execution_id=case_execution_id, project_id=project_id,
        )

        if fixture.cache_enabled:
            cached = self._cache_lookup(
                db, project_id=project_id, fixture_id=fixture.id, scope=scope, scope_key=scope_key,
            )
            if cached is not None:
                if cached.status == "DIRTY":
                    # DIRTY = 上一次清理失败，数据状态未知：不复用（§14）。
                    raise AppError(
                        f"Fixture {fixture.fixture_key} 的上次清理失败，缓存已标 DIRTY，不能复用",
                        status_code=400,
                        code=CODE_DATA_RESOLVE_FAILED,
                    )
                now = datetime.now()
                if cached.status == "EXPIRED" or (cached.expires_at is not None and cached.expires_at < now):
                    cached.status = "EXPIRED"
                    db.flush()
                else:
                    cached.ref_count = (cached.ref_count or 0) + 1
                    db.commit()
                    return {fixture.fixture_key: dict(cached.output_json or {})}

        result = self._factory.generate(
            db,
            fixture_id=fixture.id,
            project_id=project_id,
            environment=environment,
            actor=actor,
            scope=scope,
            variables=dict(inherited),
            test_run_id=test_run_id,
            case_execution_id=case_execution_id,
        )
        self._write_cache(
            db,
            project_id=project_id,
            fixture_id=fixture.id,
            scope=scope,
            scope_key=scope_key,
            outputs=result.outputs,
            data_execution_id=result.data_execution_id,
        )
        return {fixture.fixture_key: dict(result.outputs)}

    # ---------------------------------------------------------------- CLEANUP

    def cleanup_case(
        self,
        db: Session,
        *,
        case_execution_id: int,
        project_id: int,
        actor: User,
    ) -> CleanupOutcome:
        """CASE 级清理：``cleanup_policy=AFTER_CASE`` 且 scope 不是 RUN 的记录。"""
        rows = (
            db.query(DataExecution)
            .filter(DataExecution.case_execution_id == case_execution_id)
            .order_by(DataExecution.id.asc())
            .all()
        )
        return self._apply(db, rows, actor=actor, stage="CASE")

    def cleanup_run(
        self,
        db: Session,
        *,
        test_run_id: int,
        project_id: int,
        actor: User,
    ) -> CleanupOutcome:
        """RUN 级清理：整轮一次，清 ``AFTER_RUN`` 与 RUN scope 的记录。"""
        rows = (
            db.query(DataExecution)
            .filter(DataExecution.test_run_id == test_run_id)
            .order_by(DataExecution.id.desc())
            .all()
        )
        return self._apply(db, rows, actor=actor, stage="RUN")

    def _apply(
        self,
        db: Session,
        rows: list[DataExecution],
        *,
        actor: User,
        stage: str,
    ) -> CleanupOutcome:
        outcome = CleanupOutcome()
        for data_exec in rows:
            # 已清过的记录不重复清理（CASE 阶段清过的，RUN 阶段跳过）。
            if data_exec.cleanup_status in ("SUCCESS", "FAILED"):
                continue
            if not self._should_clean_in_stage(db, data_exec, stage):
                continue
            # 生成失败且没有成功步骤：没有可清理的东西，不算清理。
            if not self._has_ready_fixture(db, data_exec.id):
                data_exec.cleanup_status = "SKIPPED"
                continue
            try:
                result = self._cleanup.run_data_execution(
                    db, data_execution_id=data_exec.id, actor=actor,
                )
            except AppError as exc:
                outcome.failures.append(exc.message)
                continue
            if result.get("status") == "FAILED":
                outcome.failures.append(result.get("error_message") or result.get("error_code") or "清理失败")
                self._mark_cache_dirty(db, data_exec.id)
            else:
                outcome.cleaned += 1
                self._invalidate_cache(db, data_exec.id)
        return outcome

    @staticmethod
    def _has_ready_fixture(db: Session, data_execution_id: int) -> bool:
        """这条造数记录里有没有真正生成成功的 Fixture（否则清理是空操作）。"""
        return (
            db.query(FixtureExecution.id)
            .filter(
                FixtureExecution.data_execution_id == data_execution_id,
                FixtureExecution.status == "READY",
            )
            .first()
            is not None
        )

    def _should_clean_in_stage(self, db: Session, data_exec: DataExecution, stage: str) -> bool:
        """清理时机由 Fixture 自己的 ``cleanup_policy`` 决定，不由调用方决定。

        父 Fixture 是这条记录里 id 最大的 ``FixtureExecution`` —— 依赖先执行、
        自己最后，与 ``expand_dependency_order`` 的顺序一致。
        """
        parent = (
            db.query(FixtureExecution)
            .filter(FixtureExecution.data_execution_id == data_exec.id)
            .order_by(FixtureExecution.id.desc())
            .first()
        )
        if parent is None:
            return False
        fixture = db.get(Fixture, parent.fixture_id) if parent.fixture_id else None
        policy = (fixture.cleanup_policy if fixture else None) or "AFTER_CASE"
        scope = data_exec.scope or parent.scope or "CASE"
        if policy in NO_AUTO_CLEANUP_POLICIES:
            return False
        if stage == "RUN":
            return scope == "RUN" or policy == "AFTER_RUN"
        return scope != "RUN" and policy == "AFTER_CASE"

    # ---------------------------------------------------------------- 缓存

    @staticmethod
    def _cache_lookup(
        db: Session, *, project_id: int, fixture_id: int, scope: str, scope_key: str,
    ) -> FixtureCache | None:
        return (
            db.query(FixtureCache)
            .filter(
                FixtureCache.project_id == project_id,
                FixtureCache.fixture_id == fixture_id,
                FixtureCache.scope == scope,
                FixtureCache.scope_key == scope_key,
            )
            .first()
        )

    def _write_cache(
        self,
        db: Session,
        *,
        project_id: int,
        fixture_id: int,
        scope: str,
        scope_key: str,
        outputs: dict[str, Any],
        data_execution_id: int,
    ) -> None:
        """写缓存行：只存脱敏后的契约输出。"""
        expires_at = datetime.now() + PROJECT_CACHE_TTL if scope == "PROJECT" else None
        row = self._cache_lookup(
            db, project_id=project_id, fixture_id=fixture_id, scope=scope, scope_key=scope_key,
        )
        if row is not None:
            row.output_json = self._masker.mask_body(dict(outputs))
            row.status = "READY"
            row.ref_count = 1
            row.data_execution_id = data_execution_id
            row.expires_at = expires_at
        else:
            row = FixtureCache(
                project_id=project_id,
                fixture_id=fixture_id,
                scope=scope,
                scope_key=scope_key,
                status="READY",
                output_json=self._masker.mask_body(dict(outputs)),
                ref_count=1,
                data_execution_id=data_execution_id,
                expires_at=expires_at,
            )
            db.add(row)
        db.commit()

    @staticmethod
    def _cache_rows(db: Session, data_execution_id: int) -> list[FixtureCache]:
        return (
            db.query(FixtureCache)
            .filter(FixtureCache.data_execution_id == data_execution_id)
            .all()
        )

    def _mark_cache_dirty(self, db: Session, data_execution_id: int) -> None:
        """清理失败 → 缓存标 DIRTY：本轮剩余用例与下一轮都不会再复用。"""
        for row in self._cache_rows(db, data_execution_id):
            row.status = "DIRTY"
        db.commit()

    def _invalidate_cache(self, db: Session, data_execution_id: int) -> None:
        """清理成功 → 删缓存行（CASE 清完就没用了；RUN 在整轮结束时删）。"""
        for row in self._cache_rows(db, data_execution_id):
            db.delete(row)
        db.commit()

    # ---------------------------------------------------------------- 归属

    @staticmethod
    def _load_visible_by_key(
        db: Session, *, fixture_key: str, project_id: int,
    ) -> Fixture:
        """按 key 加载可见 Fixture：本项目，或 GLOBAL 且 ACTIVE。

        与 ``DataFactory.generate_key`` 同一口径；跨项目私有 Fixture 报
        ``FIXTURE_NOT_FOUND``，不暴露存在性。
        """
        key = (fixture_key or "").strip()
        if not key:
            raise AppError("fixture_key 不能为空", status_code=400, code=CODE_FIXTURE_NOT_FOUND)
        fixture = (
            db.query(Fixture)
            .filter(Fixture.project_id == project_id, Fixture.fixture_key == key)
            .first()
        )
        if fixture is None:
            fixture = (
                db.query(Fixture)
                .filter(Fixture.fixture_key == key, Fixture.scope == "GLOBAL", Fixture.status == "ACTIVE")
                .first()
            )
        if fixture is None:
            raise AppError(
                f"Fixture {key} 不存在", status_code=404, code=CODE_FIXTURE_NOT_FOUND,
            )
        return fixture


__all__ = [
    "CleanupOutcome",
    "LifecycleManager",
    "PROJECT_CACHE_TTL",
    "scope_key_for",
]
