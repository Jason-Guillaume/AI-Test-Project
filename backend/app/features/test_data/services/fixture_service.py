"""Fixture 服务层：CRUD、依赖、步骤、输出契约、环检测、引用关系。

规则要点（§4 / §6.1）：
- fixture_key 是 `^[A-Z][A-Z0-9_]{0,99}$`；同项目唯一（409），跨项目 404。
- GLOBAL 有所属 project_id（拥有者）；其他项目只能按 key 读取 ACTIVE 定义执行，不能改。
- FIXTURE 步骤通过 `config_json.fixture_key` 引用被依赖方，服务层同步写入
  fixture_dependency 一行；PUT /steps 替换步骤时按「步骤派生」的口径重建这些边，
  非步骤派生的手动边保留。
- 依赖合法性：同 project_id，或被依赖方 scope=GLOBAL 且 ACTIVE；
  跨项目私有 Fixture 一律 404（隐藏存在性）；被依赖方必须 ACTIVE。
- 环检测：保存步骤或依赖时若成环，400 FIXTURE_DEPENDENCY_CYCLE，消息带出
  `A → B → C → A`，事务回滚不留脏边。
- 删除：仍被 test_case_fixture 或其他 Fixture 依赖时 409。

service owns commit。
"""

from __future__ import annotations

import re

from sqlalchemy import or_
from sqlalchemy.orm import Session

from app.features.test_data.models.case_fixture import TestCaseFixture
from app.features.test_data.models.fixture import (
    Fixture,
    FixtureDependency,
    FixtureOutput,
    FixtureStep,
)
from app.features.test_data.schemas import (
    FIXTURE_CLEANUP_POLICIES,
    FIXTURE_KEY_PATTERN,
    FIXTURE_ON_FAILURE,
    FIXTURE_PHASES,
    FIXTURE_SCOPES,
    FIXTURE_STATUSES,
    FIXTURE_STEP_TYPES,
    VALUE_TYPES,
    FixtureBriefResponse,
    FixtureCreate,
    FixtureDependencyResponse,
    FixtureDetailResponse,
    FixtureListResponse,
    FixtureOutputInput,
    FixtureOutputResponse,
    FixtureStepInput,
    FixtureStepResponse,
    FixtureStepsReplace,
    FixtureOutputsReplace,
    FixtureTreeNodeResponse,
    FixtureUpdate,
)
from app.features.test_data.services._access import (
    get_project_or_404,
    require_writable_project,
    resolve_fixture_project_id,
)
from app.features.test_data.services.provider_service import provider_visible
from app.models.identity import User
from app.shared.errors import (
    CODE_FIXTURE_DEPENDENCY_CYCLE,
    CODE_FIXTURE_NOT_FOUND,
    CODE_PROVIDER_NOT_FOUND,
    AppError,
    bad_request,
    conflict,
    not_found,
)
from app.shared.pagination import DEFAULT_PAGE_SIZE


# --------------------------------------------------------------------------- 校验与异常


def _raise_cycle(path_keys: list[str]) -> None:
    """环检测失败：400 FIXTURE_DEPENDENCY_CYCLE，带出环上的 key 序列。"""
    raise AppError(
        "Fixture 依赖存在环：" + " → ".join(path_keys),
        status_code=400,
        code=CODE_FIXTURE_DEPENDENCY_CYCLE,
    )


def _raise_not_found(message: str = "Fixture 不存在") -> None:
    """资源不存在或不可见时抛出 404 错误。"""
    raise AppError(message, status_code=404, code=CODE_FIXTURE_NOT_FOUND)


def _validate_scope(value: str) -> str:
    """校验范围。"""
    if value not in FIXTURE_SCOPES:
        raise bad_request("作用域取值非法：CASE/RUN/PROJECT/GLOBAL")
    return value


def _validate_status(value: str) -> str:
    """校验状态。"""
    if value not in FIXTURE_STATUSES:
        raise bad_request("状态取值非法：DRAFT/ACTIVE/DISABLED")
    return value


def _validate_cleanup_policy(value: str) -> str:
    """校验清理策略。"""
    if value not in FIXTURE_CLEANUP_POLICIES:
        raise bad_request("清理策略取值非法：AFTER_CASE/AFTER_RUN/MANUAL/NEVER")
    return value


def _validate_step(step: FixtureStepInput) -> None:
    """步骤字面量校验；provider_id 归属校验由调用方完成。"""
    if step.phase not in FIXTURE_PHASES:
        raise bad_request("步骤阶段取值非法：GENERATE/CLEANUP")
    if step.step_type not in FIXTURE_STEP_TYPES:
        raise bad_request(f"步骤类型取值非法：{step.step_type}")
    if step.on_failure not in FIXTURE_ON_FAILURE:
        raise bad_request("失败策略取值非法：ABORT/CONTINUE")
    if not step.name.strip():
        raise bad_request("步骤名称不能为空")


def _validate_output(out: FixtureOutputInput) -> None:
    """校验输出。"""
    if out.value_type not in VALUE_TYPES:
        raise bad_request(f"输出值类型取值非法：{out.value_type}")
    if not out.source_path.strip():
        raise bad_request("输出 source_path 不能为空")
    if not out.name.strip():
        raise bad_request("输出名称不能为空")


def _validate_outputs_unique(outputs: list[FixtureOutputInput]) -> None:
    """校验`outputs``unique`。"""
    names = [out.name.strip() for out in outputs]
    if len(set(names)) != len(names):
        raise conflict("输出契约名称必须唯一")


# --------------------------------------------------------------------------- 解析


def _resolve_key_to_fixture(
    db: Session, project_id: int, fixture_key: str, *, for_dependency: bool = False
) -> Fixture:
    """按 key 解析 Fixture：本项目同 key，或 scope=GLOBAL 且 ACTIVE 的定义。

    跨项目私有 Fixture 一律 404（隐藏存在性）。依赖场景额外要求 ACTIVE。
    """
    key = (fixture_key or "").strip()
    if not key:
        raise bad_request("fixture_key 不能为空")
    own = (
        db.query(Fixture)
        .filter(Fixture.project_id == project_id, Fixture.fixture_key == key)
        .first()
    )
    if own is not None:
        if for_dependency and own.status != "ACTIVE":
            _raise_not_found(f"依赖的 Fixture {key} 不是 ACTIVE 状态")
        return own
    other = (
        db.query(Fixture)
        .filter(Fixture.fixture_key == key, Fixture.scope == "GLOBAL", Fixture.status == "ACTIVE")
        .first()
    )
    if other is not None:
        return other
    _raise_not_found(f"Fixture {key} 不存在")


def _assert_dependency_allowed(owner: Fixture, target: Fixture) -> None:
    """依赖合法性：禁止自依赖；跨项目只允许 GLOBAL 且 ACTIVE。"""
    if target.id == owner.id:
        _raise_cycle([owner.fixture_key, owner.fixture_key])
    if target.project_id != owner.project_id:
        if target.scope != "GLOBAL" or target.status != "ACTIVE":
            _raise_not_found(f"Fixture {target.fixture_key} 不存在")


def _resolve_step_targets(
    db: Session, fixture: Fixture, steps: list[FixtureStepInput]
) -> set[int]:
    """解析 FIXTURE 步骤引用的 fixture_key，返回被依赖的 Fixture ID 集合。

    其他步骤若引用 Provider，这里校验归属（跨项目引用显示为 404）。
    """
    targets: set[int] = set()
    for step in steps:
        config = step.config_json or {}
        if step.step_type == "FIXTURE":
            target = _resolve_key_to_fixture(
                db, fixture.project_id, str(config.get("fixture_key") or ""),
                for_dependency=True,
            )
            _assert_dependency_allowed(fixture, target)
            targets.add(target.id)
        elif step.provider_id is not None:
            if provider_visible(db, step.provider_id, fixture.project_id) is None:
                raise AppError(
                    f"步骤引用的 Provider {step.provider_id} 不存在",
                    status_code=404,
                    code=CODE_PROVIDER_NOT_FOUND,
                )
    return targets


# --------------------------------------------------------------------------- 环检测


def _find_cycle(db: Session, start_ids: set[int], *, max_nodes: int = 256) -> list[int] | None:
    """在依赖图上从 start_ids 出发做 DFS，返回一条环路径（首尾重复）。

    依赖边只可能因当前 Fixture 的出边变更而新增成环，所以从变更方出发
    即可覆盖全部新增环。
    """
    WHITE, GRAY, BLACK = 0, 1, 2
    color: dict[int, int] = {}
    counter = 0
    result: list[int] | None = None

    def successors(fixture_id: int) -> list[int]:
        """获取当前节点的后继节点。"""
        return [
            row[0]
            for row in db.query(FixtureDependency.depends_on_fixture_id)
            .filter(FixtureDependency.fixture_id == fixture_id)
            .order_by(FixtureDependency.sort, FixtureDependency.id)
            .all()
        ]

    def dfs(start: int) -> None:
        """按深度优先顺序遍历依赖节点。"""
        nonlocal result, counter
        stack: list[tuple[int, list[int]]] = [(start, successors(start))]
        color[start] = GRAY
        while stack:
            node, succ = stack[-1]
            if not succ:
                color[node] = BLACK
                stack.pop()
                continue
            nxt = succ.pop()
            state = color.get(nxt, WHITE)
            if state == GRAY:
                # 栈底→栈顶是当前 DFS 路径；nxt 是路径中某个 GRAY 节点，
                # node → nxt 这条回边把 nxt..node 这段接成环。
                # 取栈中 nxt 及其之后（到 node）的节点，再补回 nxt，得到
                # 首尾重复的环序列，例如 C → A → B → C。
                frames = [s[0] for s in stack]
                start_idx = frames.index(nxt)
                result = frames[start_idx:] + [nxt]
                return
            if state == WHITE:
                counter += 1
                if counter > max_nodes:
                    return
                color[nxt] = GRAY
                stack.append((nxt, successors(nxt)))

    for sid in sorted(start_ids):
        if result is not None:
            break
        if color.get(sid, WHITE) != WHITE:
            continue
        dfs(sid)
    return result


def _cycle_message(db: Session, path_ids: list[int]) -> list[str]:
    """环路径转 key 列表（首尾重复），交由 _raise_cycle 用「 → 」拼接展示。

    返回 list 而非已拼接字符串：_raise_cycle 会对入参做 join，若这里先 join 成
    单个字符串，_raise_cycle 再 join 会把字符串按字符拆开（C_NODE → C → _ → N …）。
    """
    keys: list[str] = []
    for fid in path_ids:
        row = db.get(Fixture, fid)
        keys.append(row.fixture_key if row else str(fid))
    return keys


# --------------------------------------------------------------------------- 装配


def _steps_from_inputs(fixture_id: int, steps: list[FixtureStepInput]) -> list[FixtureStep]:
    """从`steps`输入。"""
    rows: list[FixtureStep] = []
    for step in steps:
        on_failure = step.on_failure or ("CONTINUE" if step.phase == "CLEANUP" else "ABORT")
        rows.append(
            FixtureStep(
                fixture_id=fixture_id,
                phase=step.phase,
                step_type=step.step_type,
                name=step.name.strip(),
                sort=step.sort,
                provider_id=step.provider_id,
                config_json=step.config_json,
                on_failure=on_failure,
            )
        )
    return rows


def _outputs_from_inputs(fixture_id: int, outputs: list[FixtureOutputInput]) -> list[FixtureOutput]:
    """从输出输入。"""
    return [
        FixtureOutput(
            fixture_id=fixture_id,
            name=out.name.strip(),
            value_type=out.value_type,
            source_path=out.source_path.strip(),
            description=(out.description or "").strip() or None,
            sort=out.sort,
        )
        for out in outputs
    ]


def _add_dependency_row(db: Session, fixture_id: int, target_id: int) -> None:
    """写入一条依赖边（幂等：已存在则跳过）。"""
    exists = db.query(FixtureDependency).filter(
        FixtureDependency.fixture_id == fixture_id,
        FixtureDependency.depends_on_fixture_id == target_id,
    ).first()
    if exists is None:
        db.add(FixtureDependency(fixture_id=fixture_id, depends_on_fixture_id=target_id, sort=0))


def _reconcile_step_edges(
    db: Session,
    fixture_id: int,
    old_step_targets: set[int],
    new_step_targets: set[int],
) -> None:
    """按「步骤派生」口径调整依赖边：步骤派生的边跟随步骤重建，手动边保留。"""
    existing = {
        row[0]
        for row in db.query(FixtureDependency.depends_on_fixture_id)
        .filter(FixtureDependency.fixture_id == fixture_id)
        .all()
    }
    to_delete = (old_step_targets & existing) - new_step_targets
    to_add = new_step_targets - existing
    for target_id in to_delete:
        db.query(FixtureDependency).filter(
            FixtureDependency.fixture_id == fixture_id,
            FixtureDependency.depends_on_fixture_id == target_id,
        ).delete(synchronize_session=False)
    for target_id in to_add:
        _add_dependency_row(db, fixture_id, target_id)
    if to_delete or to_add:
        db.flush()


def _attach_counters(db: Session, items: list[Fixture]) -> list[FixtureBriefResponse]:
    """给列表项补输出名 / 步骤数 / 依赖数 / 引用数（聚合查询，避免 N+1）。"""
    ids = [row.id for row in items]
    if not ids:
        return []

    output_names: dict[int, list[str]] = {}
    for fid, name in (
        db.query(FixtureOutput.fixture_id, FixtureOutput.name)
        .filter(FixtureOutput.fixture_id.in_(ids))
        .order_by(FixtureOutput.sort, FixtureOutput.id)
        .all()
    ):
        output_names.setdefault(fid, []).append(name)

    step_counts: dict[int, int] = {fid: 0 for fid in ids}
    generate_counts: dict[int, int] = {fid: 0 for fid in ids}
    cleanup_counts: dict[int, int] = {fid: 0 for fid in ids}
    for fid, phase in (
        db.query(FixtureStep.fixture_id, FixtureStep.phase)
        .filter(FixtureStep.fixture_id.in_(ids))
        .all()
    ):
        step_counts[fid] = step_counts.get(fid, 0) + 1
        if phase == "GENERATE":
            generate_counts[fid] = generate_counts.get(fid, 0) + 1
        else:
            cleanup_counts[fid] = cleanup_counts.get(fid, 0) + 1

    dep_counts: dict[int, int] = {fid: 0 for fid in ids}
    for (fid,) in (
        db.query(FixtureDependency.fixture_id)
        .filter(FixtureDependency.fixture_id.in_(ids))
        .all()
    ):
        dep_counts[fid] = dep_counts.get(fid, 0) + 1

    ref_counts: dict[int, int] = {fid: 0 for fid in ids}
    for (fid,) in (
        db.query(TestCaseFixture.fixture_id).filter(TestCaseFixture.fixture_id.in_(ids)).all()
    ):
        ref_counts[fid] = ref_counts.get(fid, 0) + 1

    responses: list[FixtureBriefResponse] = []
    for row in items:
        resp = FixtureBriefResponse.model_validate(row)
        resp.output_names = output_names.get(row.id, [])
        resp.step_count = step_counts.get(row.id, 0)
        resp.generate_step_count = generate_counts.get(row.id, 0)
        resp.cleanup_step_count = cleanup_counts.get(row.id, 0)
        resp.dependency_count = dep_counts.get(row.id, 0)
        resp.referenced_case_count = ref_counts.get(row.id, 0)
        responses.append(resp)
    return responses


def _detail_response(db: Session, fixture: Fixture) -> FixtureDetailResponse:
    """详情：基本信息 + 步骤 + 输出契约 + 依赖 + 引用它的用例。"""
    steps = (
        db.query(FixtureStep)
        .filter(FixtureStep.fixture_id == fixture.id)
        .order_by(FixtureStep.phase, FixtureStep.sort, FixtureStep.id)
        .all()
    )
    outputs = (
        db.query(FixtureOutput)
        .filter(FixtureOutput.fixture_id == fixture.id)
        .order_by(FixtureOutput.sort, FixtureOutput.id)
        .all()
    )
    dependencies = (
        db.query(FixtureDependency)
        .filter(FixtureDependency.fixture_id == fixture.id)
        .order_by(FixtureDependency.sort, FixtureDependency.id)
        .all()
    )

    step_responses: list[FixtureStepResponse] = []
    for step in steps:
        resp = FixtureStepResponse.model_validate(step)
        # Provider 归属校验：跨项目引用置 None（对调用方隐藏存在性）。
        if resp.provider_id is not None and provider_visible(
            db, resp.provider_id, fixture.project_id
        ) is None:
            resp.provider_id = None
        step_responses.append(resp)

    dep_responses: list[FixtureDependencyResponse] = []
    for dep in dependencies:
        target = db.get(Fixture, dep.depends_on_fixture_id)
        resp = FixtureDependencyResponse.model_validate(dep)
        if target is not None:
            resp.depends_on_key = target.fixture_key
            resp.depends_on_name = target.name
            resp.depends_on_entity_type = target.entity_type
        dep_responses.append(resp)

    referenced_cases: list[dict] = [
        {"test_case_id": row.test_case_id, "sort": row.sort}
        for row in (
            db.query(TestCaseFixture)
            .filter(TestCaseFixture.fixture_id == fixture.id)
            .order_by(TestCaseFixture.sort, TestCaseFixture.id)
            .all()
        )
    ]

    brief = _attach_counters(db, [fixture])[0]
    return FixtureDetailResponse(
        **brief.model_dump(),
        steps=step_responses,
        outputs=[FixtureOutputResponse.model_validate(o) for o in outputs],
        dependencies=dep_responses,
        referenced_cases=referenced_cases,
    )


# --------------------------------------------------------------------------- 服务


class FixtureService:
    """Fixture 服务。无状态，路由层复用单例。"""

    # ---------------------------------------------------------------- 列表 / 详情

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
            _validate_status(status)
            q = q.filter(Fixture.status == status)
        if scope:
            _validate_scope(scope)
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
            items=_attach_counters(db, items), total=total, page=page, page_size=page_size
        )

    def get_fixture(self, db: Session, fixture_id: int, user: User) -> FixtureDetailResponse:
        """获取固定数据。"""
        return _detail_response(db, self._get_or_404(db, fixture_id, user))

    # ---------------------------------------------------------------- 创建 / 删除

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
        _validate_scope(body.scope)
        _validate_status(body.status)
        _validate_cleanup_policy(body.cleanup_policy)
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
            _validate_step(step)
        for out in body.outputs:
            _validate_output(out)
        _validate_outputs_unique(body.outputs)

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
        self._save_steps(db, fixture, body.steps)
        self._save_outputs(db, fixture, body.outputs)
        for dep_id in body.dependencies or []:
            self._add_manual_dependency(db, fixture, dep_id)
        self._check_cycles(db, {fixture.id})
        db.commit()
        db.refresh(fixture)
        return _detail_response(db, fixture)

    def delete_fixture(self, db: Session, fixture_id: int, *, actor: User) -> None:
        """删除固定数据。"""
        fixture = self._get_writable_or_404(db, fixture_id, actor)
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

    # ---------------------------------------------------------------- 更新

    def update_fixture(
        self, db: Session, fixture_id: int, body: FixtureUpdate, *, actor: User,
    ) -> FixtureDetailResponse:
        """更新固定数据。"""
        fixture = self._get_writable_or_404(db, fixture_id, actor)
        data = body.model_dump(exclude_unset=True)
        if not data:
            return _detail_response(db, fixture)

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
            _validate_scope(data["scope"])
            fixture.scope = data["scope"]
        if data.get("status") is not None:
            _validate_status(data["status"])
            fixture.status = data["status"]
        if data.get("cache_enabled") is not None:
            fixture.cache_enabled = bool(data["cache_enabled"])
        if data.get("cleanup_policy") is not None:
            _validate_cleanup_policy(data["cleanup_policy"])
            fixture.cleanup_policy = data["cleanup_policy"]

        db.commit()
        db.refresh(fixture)
        return _detail_response(db, fixture)

    # ---------------------------------------------------------------- 步骤 / 输出

    def replace_steps(
        self, db: Session, fixture_id: int, body: FixtureStepsReplace, *, actor: User,
    ) -> FixtureDetailResponse:
        """替换`steps`。"""
        fixture = self._get_writable_or_404(db, fixture_id, actor)
        for step in body.steps:
            _validate_step(step)

        # 先从旧步骤里取出「步骤派生」的依赖边，替换后按新步骤重建。
        old_step_targets: set[int] = set()
        for old in db.query(FixtureStep).filter(FixtureStep.fixture_id == fixture.id).all():
            if old.step_type != "FIXTURE" or not isinstance(old.config_json, dict):
                continue
            key = str(old.config_json.get("fixture_key") or "").strip()
            if not key:
                continue
            old_step_targets.add(
                _resolve_key_to_fixture(db, fixture.project_id, key).id
            )

        new_step_targets = _resolve_step_targets(db, fixture, body.steps)
        _reconcile_step_edges(db, fixture.id, old_step_targets, new_step_targets)
        db.query(FixtureStep).filter(FixtureStep.fixture_id == fixture.id).delete(
            synchronize_session=False
        )
        db.flush()
        for row in _steps_from_inputs(fixture.id, body.steps):
            db.add(row)
        self._check_cycles(db, {fixture.id})
        db.commit()
        db.refresh(fixture)
        return _detail_response(db, fixture)

    def replace_outputs(
        self, db: Session, fixture_id: int, body: FixtureOutputsReplace, *, actor: User,
    ) -> FixtureDetailResponse:
        """替换输出。"""
        fixture = self._get_writable_or_404(db, fixture_id, actor)
        for out in body.outputs:
            _validate_output(out)
        _validate_outputs_unique(body.outputs)
        db.query(FixtureOutput).filter(FixtureOutput.fixture_id == fixture.id).delete(
            synchronize_session=False
        )
        db.flush()
        for row in _outputs_from_inputs(fixture.id, body.outputs):
            db.add(row)
        db.commit()
        db.refresh(fixture)
        return _detail_response(db, fixture)

    # ---------------------------------------------------------------- 依赖树

    def dependency_tree(
        self, db: Session, fixture_id: int, user: User, *, max_depth: int = 20
    ) -> list[FixtureTreeNodeResponse]:
        """依赖树（含子依赖），供前端树展示。环在保存时已被拒绝，正常树可递归展开。"""
        fixture = self._get_or_404(db, fixture_id, user)
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

    # ---------------------------------------------------------------- 内部

    def _save_steps(self, db: Session, fixture: Fixture, steps: list[FixtureStepInput]) -> None:
        """整体写入步骤（创建场景：无旧步骤），同时写入步骤派生的依赖边。"""
        _reconcile_step_edges(db, fixture.id, set(), _resolve_step_targets(db, fixture, steps))
        for row in _steps_from_inputs(fixture.id, steps):
            db.add(row)

    def _save_outputs(self, db: Session, fixture: Fixture, outputs: list[FixtureOutputInput]) -> None:
        """保存`outputs`。"""
        for row in _outputs_from_inputs(fixture.id, outputs):
            db.add(row)
        db.flush()

    def _add_manual_dependency(self, db: Session, fixture: Fixture, dep_id: int) -> None:
        """写入一条手动依赖边：校验存在性、归属与自依赖。"""
        target = db.get(Fixture, dep_id)
        if target is None:
            _raise_not_found(f"依赖的 Fixture {dep_id} 不存在")
        _assert_dependency_allowed(fixture, target)
        _add_dependency_row(db, fixture.id, target.id)

    def _check_cycles(self, db: Session, start_ids: set[int]) -> None:
        """检查`cycles`。"""
        path = _find_cycle(db, start_ids)
        if path is not None:
            _raise_cycle(_cycle_message(db, path))

    def _get_or_404(self, db: Session, fixture_id: int, user: User) -> Fixture:
        """获取或。"""
        row = db.get(Fixture, fixture_id)
        if row is None:
            _raise_not_found()
        get_project_or_404(db, row.project_id, user)
        return row

    def _get_writable_or_404(self, db: Session, fixture_id: int, actor: User) -> Fixture:
        """获取可写或。"""
        row = db.get(Fixture, fixture_id)
        if row is None:
            _raise_not_found()
        require_writable_project(db, resolve_fixture_project_id(db, fixture_id), actor)
        return row


__all__ = ["FixtureService", "_detail_response", "_resolve_key_to_fixture"]
