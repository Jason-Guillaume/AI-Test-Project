"""领域职责提取；保留原权限、事务和执行顺序。"""

from __future__ import annotations

import re
from sqlalchemy import or_
from sqlalchemy.orm import Session
from app.features.test_data.models.case_fixture import TestCaseFixture
from app.features.test_data.models.fixture import Fixture, FixtureDependency, FixtureOutput, FixtureStep
from app.features.test_data.schemas import (
    FIXTURE_KEY_PATTERN,
    FixtureCreate,
    FixtureDetailResponse,
    FixtureListResponse,
    FixtureStepsReplace,
    FixtureOutputsReplace,
    FixtureTreeNodeResponse,
    FixtureUpdate,
)
from app.platform.projects.services.access_service import get_project_or_404, require_writable_project
from app.core.models.identity import User
from app.core.http.errors import bad_request, conflict
from app.core.http.pagination import DEFAULT_PAGE_SIZE
from app.features.test_data.services.fixture_dependencies import add_manual_dependency
from app.features.test_data.services.fixture_response import attach_counters
from app.features.test_data.services.fixture_dependencies import check_cycles
from app.features.test_data.services.fixture_response import detail_response
from app.features.test_data.services.fixture_access import get_or_404
from app.features.test_data.services.fixture_access import get_writable_or_404
from app.features.test_data.services.fixture_storage import outputs_from_inputs
from app.features.test_data.services.fixture_dependencies import reconcile_step_edges
from app.features.test_data.services.fixture_references import resolve_key_to_fixture
from app.features.test_data.services.fixture_references import resolve_step_targets
from app.features.test_data.services.fixture_storage import save_outputs
from app.features.test_data.services.fixture_storage import save_steps
from app.features.test_data.services.fixture_storage import steps_from_inputs
from app.features.test_data.services.fixture_validation import validate_cleanup_policy
from app.features.test_data.services.fixture_validation import validate_output
from app.features.test_data.services.fixture_validation import validate_outputs_unique
from app.features.test_data.services.fixture_validation import validate_scope
from app.features.test_data.services.fixture_validation import validate_status
from app.features.test_data.services.fixture_validation import validate_step


class FixtureService:
    """稳定领域门面；各资源由唯一实现持有。"""

    def list_fixtures(
        self, db: Session, project_id: int, user: User, *,
        keyword: str | None = None, entity_type: str | None = None,
        status: str | None = None, scope: str | None = None,
        page: int = 1, page_size: int = DEFAULT_PAGE_SIZE,
    ) -> FixtureListResponse:
        """列出`fixtures`。"""
        get_project_or_404(db, project_id, user)
        q = db.query(Fixture).filter(Fixture.project_id == project_id)
        if entity_type:
            q = q.filter(Fixture.entity_type == entity_type)
        if status:
            validate_status(status)
            q = q.filter(Fixture.status == status)
        if scope:
            validate_scope(scope)
            q = q.filter(Fixture.scope == scope)
        kw = (keyword or "").strip()
        if kw:
            q = q.filter(
                or_(
                    Fixture.name.ilike(f"%{kw}%"),
                    Fixture.fixture_key.ilike(f"%{kw}%"),
                    Fixture.entity_type.ilike(f"%{kw}%"),
                )
            )
        total = int(q.count())
        items = q.order_by(Fixture.id.desc()).offset((page - 1) * page_size).limit(page_size).all()
        return FixtureListResponse(
            items=attach_counters(db, items), total=total, page=page, page_size=page_size
        )

    def get_fixture(self, db: Session, fixture_id: int, user: User) -> FixtureDetailResponse:
        """获取固定数据。"""
        return detail_response(db, get_or_404(db, fixture_id, user))

    def create_fixture(
        self, db: Session, project_id: int, body: FixtureCreate, *, actor: User,
    ) -> FixtureDetailResponse:
        """创建固定数据。"""
        project = require_writable_project(db, project_id, actor)
        fixture_key = body.fixture_key.strip()
        if not re.fullmatch(FIXTURE_KEY_PATTERN, fixture_key):
            raise bad_request(f"fixture_key 必须匹配 {FIXTURE_KEY_PATTERN}")
        name = body.name.strip()
        if not name:
            raise bad_request("Fixture 名称不能为空")
        validate_scope(body.scope)
        validate_status(body.status)
        validate_cleanup_policy(body.cleanup_policy)
        if not body.entity_type.strip():
            raise bad_request("实体类型不能为空")

        if db.query(Fixture).filter(
            Fixture.project_id == project.id, Fixture.fixture_key == fixture_key
        ).first() is not None:
            raise conflict("同项目下 fixture_key 已存在")
        if body.scope == "GLOBAL" and db.query(Fixture).filter(
            Fixture.fixture_key == fixture_key, Fixture.scope == "GLOBAL"
        ).first() is not None:
            raise conflict(f"全局键 {fixture_key} 已被其他项目使用")

        for step in body.steps:
            validate_step(step)
        for out in body.outputs:
            validate_output(out)
        validate_outputs_unique(body.outputs)

        fixture = Fixture(
            project_id=project.id,
            name=name,
            fixture_key=fixture_key,
            entity_type=body.entity_type.strip(),
            description=(body.description or "").strip() or None,
            scope=body.scope,
            status=body.status,
            cache_enabled=body.cache_enabled,
            cleanup_policy=body.cleanup_policy,
            created_by=actor.id,
        )
        db.add(fixture)
        db.flush()
        save_steps(db, fixture, body.steps)
        save_outputs(db, fixture, body.outputs)
        for dep_id in body.dependencies or []:
            add_manual_dependency(db, fixture, dep_id)
        check_cycles(db, {fixture.id})
        db.commit()
        db.refresh(fixture)
        return detail_response(db, fixture)

    def delete_fixture(self, db: Session, fixture_id: int, *, actor: User) -> None:
        """删除固定数据。"""
        fixture = get_writable_or_404(db, fixture_id, actor)
        ref_count = int(
            db.query(TestCaseFixture.id).filter(TestCaseFixture.fixture_id == fixture.id).count()
        )
        if ref_count:
            raise conflict(f"该 Fixture 正被 {ref_count} 个用例引用，请先在用例上移除引用")
        dep_count = int(
            db.query(FixtureDependency.id)
            .filter(FixtureDependency.depends_on_fixture_id == fixture.id)
            .count()
        )
        if dep_count:
            raise conflict(f"该 Fixture 正被 {dep_count} 条依赖边引用，请先移除依赖")
        db.delete(fixture)
        db.commit()

    def update_fixture(
        self, db: Session, fixture_id: int, body: FixtureUpdate, *, actor: User,
    ) -> FixtureDetailResponse:
        """更新固定数据。"""
        fixture = get_writable_or_404(db, fixture_id, actor)
        data = body.model_dump(exclude_unset=True)
        if not data:
            return detail_response(db, fixture)

        name = data.get("name")
        if name is not None:
            if not name.strip():
                raise bad_request("Fixture 名称不能为空")
            fixture.name = name.strip()
        if data.get("description") is not None:
            fixture.description = data["description"].strip() or None
        if data.get("scope") is not None:
            # GLOBAL 是跨项目可见的，切换前需重新校验全局唯一性。
            if data["scope"] == "GLOBAL" and fixture.scope != "GLOBAL":
                other = (
                    db.query(Fixture)
                    .filter(
                        Fixture.fixture_key == fixture.fixture_key,
                        Fixture.scope == "GLOBAL",
                        Fixture.id != fixture.id,
                    )
                    .first()
                )
                if other is not None:
                    raise conflict(f"全局键 {fixture.fixture_key} 已被其他项目使用")
            validate_scope(data["scope"])
            fixture.scope = data["scope"]
        if data.get("status") is not None:
            validate_status(data["status"])
            fixture.status = data["status"]
        if data.get("cache_enabled") is not None:
            fixture.cache_enabled = bool(data["cache_enabled"])
        if data.get("cleanup_policy") is not None:
            validate_cleanup_policy(data["cleanup_policy"])
            fixture.cleanup_policy = data["cleanup_policy"]

        db.commit()
        db.refresh(fixture)
        return detail_response(db, fixture)

    def replace_steps(
        self, db: Session, fixture_id: int, body: FixtureStepsReplace, *, actor: User,
    ) -> FixtureDetailResponse:
        """替换`steps`。"""
        fixture = get_writable_or_404(db, fixture_id, actor)
        for step in body.steps:
            validate_step(step)

        # 先从旧步骤里取出「步骤派生」的依赖边，替换后按新步骤重建。
        old_step_targets: set[int] = set()
        for old in db.query(FixtureStep).filter(FixtureStep.fixture_id == fixture.id).all():
            if old.step_type != "FIXTURE" or not isinstance(old.config_json, dict):
                continue
            key = str(old.config_json.get("fixture_key") or "").strip()
            if not key:
                continue
            old_step_targets.add(
                resolve_key_to_fixture(db, fixture.project_id, key).id
            )

        new_step_targets = resolve_step_targets(db, fixture, body.steps)
        reconcile_step_edges(db, fixture.id, old_step_targets, new_step_targets)
        db.query(FixtureStep).filter(FixtureStep.fixture_id == fixture.id).delete(
            synchronize_session=False
        )
        db.flush()
        for row in steps_from_inputs(fixture.id, body.steps):
            db.add(row)
        check_cycles(db, {fixture.id})
        db.commit()
        db.refresh(fixture)
        return detail_response(db, fixture)

    def replace_outputs(
        self, db: Session, fixture_id: int, body: FixtureOutputsReplace, *, actor: User,
    ) -> FixtureDetailResponse:
        """替换输出。"""
        fixture = get_writable_or_404(db, fixture_id, actor)
        for out in body.outputs:
            validate_output(out)
        validate_outputs_unique(body.outputs)
        db.query(FixtureOutput).filter(FixtureOutput.fixture_id == fixture.id).delete(
            synchronize_session=False
        )
        db.flush()
        for row in outputs_from_inputs(fixture.id, body.outputs):
            db.add(row)
        db.commit()
        db.refresh(fixture)
        return detail_response(db, fixture)

    def dependency_tree(
        self, db: Session, fixture_id: int, user: User, *, max_depth: int = 20
    ) -> list[FixtureTreeNodeResponse]:
        """依赖树（含子依赖），供前端树展示。环在保存时已被拒绝，正常树可递归展开。"""
        fixture = get_or_404(db, fixture_id, user)
        seen: set[int] = set()

        def build(fid: int, depth: int) -> FixtureTreeNodeResponse:
            """构建对应数据。"""
            row = db.get(Fixture, fid)
            if row is None:
                return FixtureTreeNodeResponse(
                    id=fid, fixture_key="", name="（已删除）", entity_type="",
                    scope="", status="", depth=depth,
                )
            node = FixtureTreeNodeResponse(
                id=row.id, fixture_key=row.fixture_key, name=row.name,
                entity_type=row.entity_type, scope=row.scope, status=row.status, depth=depth,
            )
            if depth >= max_depth or fid in seen:
                return node
            seen.add(fid)
            children = (
                db.query(FixtureDependency)
                .filter(FixtureDependency.fixture_id == fid)
                .order_by(FixtureDependency.sort, FixtureDependency.id)
                .all()
            )
            for child in children:
                node.children.append(build(child.depends_on_fixture_id, depth + 1))
            return node

        return [build(fixture.id, 0)]


__all__ = [
    'FixtureService',
    'detail_response',
    'resolve_key_to_fixture',
]
