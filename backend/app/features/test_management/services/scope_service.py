"""测试范围服务：目录树、归属、资产关联和按节点查用例。

范围节点只做导航。移动目录不改 TestCase.api_id 等执行外键。
待整理节点在读树时补齐，是因为迁移之后新建的项目没有这三行，未归类用例会无处可挂。

权限与测试用例一致：读 viewer+，写 member+，跨项目 404。写方法在本服务内 commit；
attach_new_case 给用例创建流程复用，由调用方提交。
"""

from __future__ import annotations

from collections import defaultdict

from sqlalchemy import case as sql_case
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.agents.models.definition import AgentDefinition
from app.core.http.errors import bad_request, conflict, not_found
from app.core.models.identity import User
from app.features.api_catalog.models.api_interface import ApiInterface
from app.features.api_catalog.models.api_module import ApiModule
from app.features.business.models.business_action import BusinessAction
from app.features.business.models.business_domain import BusinessDomain
from app.features.business.models.business_flow import BusinessFlow
from app.features.test_management.models.execution import CaseExecution
from app.features.test_management.models.test_case import TestCase
from app.features.test_management.models.test_point import TestPoint
from app.features.test_management.models.test_scope import TestCaseAsset, TestCaseScope, TestScopeNode
from app.features.test_management.schemas.scopes import (
    CaseAssetReplace,
    CaseAssetResponse,
    CaseExecutionBrief,
    ScopeCaseArchiveRequest,
    ScopeCaseListResponse,
    ScopeCaseMoveRequest,
    ScopeCaseQueryItem,
    ScopeLinkReplace,
    ScopeMutationResult,
    ScopeNodeCreate,
    ScopeNodeDetailResponse,
    ScopeNodeMove,
    ScopeNodeResponse,
    ScopeNodeUpdate,
    ScopePathItem,
    ScopePathResponse,
    ScopeStatsResponse,
    ScopeTreeResponse,
)
from app.features.test_management.scope_placement import (
    ASSET_TYPES,
    DIRECTIONS,
    INBOX_NAME,
    SCOPE_STATUSES,
    direction_of_target,
)
from app.features.web_testing.models.web_ui import PageObject
from app.platform.projects.services.access_service import get_project_or_404, require_writable_project


class ScopeService:
    """测试范围导航。无状态，路由层每次新建或复用均可。"""

    def list_tree(self, db: Session, project_id: int, user: User, direction: str) -> ScopeTreeResponse:
        """返回一个方向的全部节点，计数字段包含子孙用例。"""
        self._require_direction(direction)
        get_project_or_404(db, project_id, user)
        # 新建项目没有迁移出的收件箱，第一次打开树时补上，否则未归类没有落点。
        self.ensure_inboxes(db, project_id, commit=True)
        nodes = self._nodes(db, project_id, direction)
        counts = self._recursive_counts(db, nodes)
        return ScopeTreeResponse(
            direction=direction,
            items=[self._node_response(node, counts) for node in self._ordered(nodes)],
        )

    def get_node(self, db: Session, node_id: int, user: User) -> ScopeNodeDetailResponse:
        """读取单个节点、从根开始的路径，以及下一层子节点。"""
        node = self._visible_node(db, node_id, user)
        nodes = self._nodes(db, node.project_id, node.direction)
        counts = self._recursive_counts(db, nodes)
        by_id = {item.id: item for item in nodes}
        children = [item for item in self._ordered(nodes) if item.parent_id == node.id]
        return ScopeNodeDetailResponse(
            **self._node_response(node, counts).model_dump(),
            path=self._path(node, by_id),
            children=[self._node_response(item, counts) for item in children],
        )

    def stats(self, db: Session, project_id: int, user: User, direction: str) -> ScopeStatsResponse:
        """方向汇总：节点数、去重用例数、去重测试点数、优先级分布。"""
        self._require_direction(direction)
        get_project_or_404(db, project_id, user)
        self.ensure_inboxes(db, project_id, commit=True)
        nodes = self._nodes(db, project_id, direction)
        node_ids = [node.id for node in nodes]
        priority_counts = {"P0": 0, "P1": 0, "P2": 0, "P3": 0}
        case_ids: set[int] = set()
        point_ids: set[int] = set()
        if node_ids:
            rows = (
                db.query(TestCase.id, TestCase.priority, TestCase.test_point_id)
                .join(TestCaseScope, TestCaseScope.test_case_id == TestCase.id)
                .filter(TestCaseScope.scope_node_id.in_(node_ids), TestCase.project_id == project_id)
                .all()
            )
            for case_id, priority, point_id in rows:
                if case_id in case_ids:
                    continue
                case_ids.add(case_id)
                if priority in priority_counts:
                    priority_counts[priority] += 1
                if point_id is not None:
                    point_ids.add(point_id)
        return ScopeStatsResponse(
            direction=direction,
            scope_count=len(nodes),
            case_count=len(case_ids),
            point_count=len(point_ids),
            priority_counts=priority_counts,
        )

    def create_node(
        self, db: Session, project_id: int, body: ScopeNodeCreate, *, actor: User,
    ) -> ScopeNodeResponse:
        """创建目录或资产链接。待整理节点不允许手工创建。"""
        self._require_direction(body.direction)
        require_writable_project(db, project_id, actor)
        self.ensure_inboxes(db, project_id, commit=False)
        parent = self._parent_for_write(db, project_id, body.direction, body.parent_id)
        self._validate_node_shape(db, project_id, body.node_type, body.asset_type, body.asset_id)
        name = body.name.strip()
        if not name:
            raise bad_request("节点名称不能为空")
        self._ensure_sibling_name(db, project_id, body.direction, parent.id if parent else None, name)
        sort_order = body.sort_order
        if sort_order is None:
            sort_order = self._next_sort(db, project_id, body.direction, parent.id if parent else None)
        row = TestScopeNode(
            project_id=project_id,
            direction=body.direction,
            parent_id=parent.id if parent else None,
            node_type=body.node_type,
            name=name,
            description=(body.description or "").strip() or None,
            sort_order=sort_order,
            status="ACTIVE",
            asset_type=body.asset_type if body.node_type == "ASSET_LINK" else None,
            asset_id=body.asset_id if body.node_type == "ASSET_LINK" else None,
            is_system=False,
            created_by=actor.id,
        )
        db.add(row)
        db.commit()
        db.refresh(row)
        return self._node_response(row, {row.id: (0, 0)})

    def update_node(
        self, db: Session, node_id: int, body: ScopeNodeUpdate, *, actor: User,
    ) -> ScopeNodeResponse:
        """修改名称、说明、排序、状态。系统待整理节点不能改名。"""
        node = self._writable_node(db, node_id, actor)
        data = body.model_dump(exclude_unset=True)
        if node.is_system and "name" in data:
            raise bad_request("待整理节点不能改名")
        if "name" in data and data["name"] is not None:
            name = data["name"].strip()
            if not name:
                raise bad_request("节点名称不能为空")
            if name != node.name:
                self._ensure_sibling_name(db, node.project_id, node.direction, node.parent_id, name, exclude_id=node.id)
            node.name = name
        if "description" in data:
            node.description = (data["description"] or "").strip() or None
        if "sort_order" in data and data["sort_order"] is not None:
            node.sort_order = data["sort_order"]
        if "status" in data and data["status"] is not None:
            if data["status"] not in SCOPE_STATUSES:
                raise bad_request("节点状态取值非法")
            node.status = data["status"]
        if node.node_type == "ASSET_LINK" and ("asset_type" in data or "asset_id" in data):
            asset_type = data.get("asset_type", node.asset_type)
            asset_id = data.get("asset_id", node.asset_id)
            self._validate_node_shape(db, node.project_id, "ASSET_LINK", asset_type, asset_id)
            node.asset_type = asset_type
            node.asset_id = asset_id
        elif node.node_type != "ASSET_LINK" and ("asset_type" in data or "asset_id" in data):
            raise bad_request("只有资产链接节点可以关联资产")
        db.commit()
        db.refresh(node)
        counts = self._recursive_counts(db, self._nodes(db, node.project_id, node.direction))
        return self._node_response(node, counts)

    def move_node(self, db: Session, node_id: int, body: ScopeNodeMove, *, actor: User) -> ScopeNodeResponse:
        """移动节点。拒绝把节点放进自己的子孙，避免目录成环。"""
        node = self._writable_node(db, node_id, actor)
        if node.is_system:
            raise bad_request("待整理节点不能移动")
        parent = self._parent_for_write(db, node.project_id, node.direction, body.parent_id)
        parent_id = parent.id if parent else None
        if parent_id == node.id:
            raise bad_request("不能把节点移动到自己下面")
        if parent is not None and self._is_descendant(db, node, parent):
            raise bad_request("不能把节点移动到自己的子节点下")
        if parent_id != node.parent_id:
            self._ensure_sibling_name(db, node.project_id, node.direction, parent_id, node.name, exclude_id=node.id)
        node.parent_id = parent_id
        node.sort_order = body.sort_order
        db.commit()
        db.refresh(node)
        counts = self._recursive_counts(db, self._nodes(db, node.project_id, node.direction))
        return self._node_response(node, counts)

    def delete_node(self, db: Session, node_id: int, *, actor: User) -> None:
        """删除空目录。有子节点时拒绝；直接挂载的用例改挂到父节点或待整理，避免用例丢失。"""
        node = self._writable_node(db, node_id, actor)
        if node.is_system:
            raise bad_request("待整理节点不能删除")
        child = (
            db.query(TestScopeNode.id)
            .filter(TestScopeNode.parent_id == node.id)
            .first()
        )
        if child is not None:
            raise bad_request("请先移动或删除子节点")
        target_id = node.parent_id
        if target_id is None:
            target_id = self._inbox(db, node.project_id, node.direction).id
        if target_id == node.id:
            raise bad_request("无法为用例找到新的目录")
        links = db.query(TestCaseScope).filter(TestCaseScope.scope_node_id == node.id).all()
        already = {
            row.test_case_id
            for row in db.query(TestCaseScope.test_case_id).filter(TestCaseScope.scope_node_id == target_id).all()
        }
        for link in links:
            if link.test_case_id in already:
                db.delete(link)
            else:
                link.scope_node_id = target_id
                already.add(link.test_case_id)
        db.flush()
        db.delete(node)
        db.commit()

    def list_cases(
        self, db: Session, project_id: int, user: User, *,
        direction: str | None, scope_node_id: int | None, include_descendants: bool,
        case_type: str | None, priority: str | None, status: str | None, keyword: str | None,
        sort: str, order: str, page: int, page_size: int,
    ) -> ScopeCaseListResponse:
        """按方向或节点列出用例。默认含子孙节点，同一用例只出现一次。"""
        get_project_or_404(db, project_id, user)
        if direction is not None:
            self._require_direction(direction)
        if sort not in ("updated_at", "priority", "name"):
            raise bad_request("排序字段取值非法")
        if order not in ("asc", "desc"):
            raise bad_request("排序方向取值非法")
        node_ids = self._query_node_ids(db, project_id, direction, scope_node_id, include_descendants)
        query = db.query(TestCase).filter(TestCase.project_id == project_id)
        if node_ids is not None:
            if not node_ids:
                return ScopeCaseListResponse(items=[], total=0, page=page, page_size=page_size)
            query = query.join(TestCaseScope, TestCaseScope.test_case_id == TestCase.id).filter(
                TestCaseScope.scope_node_id.in_(node_ids),
            )
        elif direction is not None:
            query = (
                query.join(TestCaseScope, TestCaseScope.test_case_id == TestCase.id)
                .join(TestScopeNode, TestScopeNode.id == TestCaseScope.scope_node_id)
                .filter(TestScopeNode.direction == direction, TestScopeNode.project_id == project_id)
            )
        if case_type:
            query = query.filter(TestCase.case_type == case_type)
        if priority:
            query = query.filter(TestCase.priority == priority)
        if status:
            query = query.filter(TestCase.status == status)
        kw = (keyword or "").strip()
        if kw:
            query = query.filter(TestCase.name.ilike(f"%{kw}%"))
        query = query.distinct()
        total = int(query.order_by(None).count())
        rank = sql_case(
            (TestCase.priority == "P0", 0),
            (TestCase.priority == "P1", 1),
            (TestCase.priority == "P2", 2),
            else_=3,
        )
        sort_column = {"updated_at": TestCase.updated_at, "priority": rank, "name": TestCase.name}[sort]
        sorted_query = query.order_by(sort_column.asc() if order == "asc" else sort_column.desc(), TestCase.id.desc())
        rows = sorted_query.offset((page - 1) * page_size).limit(page_size).all()
        point_ids = {row.test_point_id for row in rows if row.test_point_id is not None}
        point_names = {}
        if point_ids:
            point_names = {
                point.id: point.name
                for point in db.query(TestPoint).filter(TestPoint.id.in_(point_ids)).all()
            }
        direction_by_case = self._primary_direction(db, [row.id for row in rows])
        items = [
            ScopeCaseQueryItem(
                id=row.id,
                project_id=row.project_id,
                name=row.name,
                priority=row.priority,
                case_type=row.case_type,
                target_type=row.target_type,
                status=row.status,
                source_type=row.source_type,
                test_point_id=row.test_point_id,
                test_point_name=point_names.get(row.test_point_id) if row.test_point_id else None,
                direction=direction_by_case.get(row.id) or direction_of_target(row.target_type),
                updated_at=row.updated_at,
            )
            for row in rows
        ]
        return ScopeCaseListResponse(items=items, total=total, page=page, page_size=page_size)

    def move_cases(
        self, db: Session, project_id: int, body: ScopeCaseMoveRequest, *, actor: User,
    ) -> ScopeMutationResult:
        """批量改目录归属。只替换范围链接，不改被测对象外键。"""
        require_writable_project(db, project_id, actor)
        node = self._node_in_project(db, body.scope_node_id, project_id)
        cases = self._cases_in_project(db, project_id, body.case_ids)
        for case in cases:
            db.query(TestCaseScope).filter(TestCaseScope.test_case_id == case.id).delete()
            db.add(TestCaseScope(test_case_id=case.id, scope_node_id=node.id))
        db.commit()
        return ScopeMutationResult(affected=len(cases))

    def archive_cases(
        self, db: Session, project_id: int, body: ScopeCaseArchiveRequest, *, actor: User,
    ) -> ScopeMutationResult:
        """批量归档为 DEPRECATED。归档后仍可在原目录看到，执行侧沿用原状态语义。"""
        require_writable_project(db, project_id, actor)
        cases = self._cases_in_project(db, project_id, body.case_ids)
        for case in cases:
            case.status = "DEPRECATED"
            case.revision = (case.revision or 0) + 1
        db.commit()
        return ScopeMutationResult(affected=len(cases))

    def replace_scope_links(
        self, db: Session, case_id: int, body: ScopeLinkReplace, *, actor: User,
    ) -> list[ScopePathResponse]:
        """整体替换一条用例的目录归属。节点必须属于同一项目。"""
        case = self._writable_case(db, case_id, actor)
        nodes = [self._node_in_project(db, node_id, case.project_id) for node_id in dict.fromkeys(body.scope_node_ids)]
        db.query(TestCaseScope).filter(TestCaseScope.test_case_id == case.id).delete()
        for node in nodes:
            db.add(TestCaseScope(test_case_id=case.id, scope_node_id=node.id))
        db.commit()
        return self._scope_paths(db, case.id)

    def replace_assets(
        self, db: Session, case_id: int, body: CaseAssetReplace, *, actor: User,
    ) -> list[CaseAssetResponse]:
        """整体替换被测资产关联。执行器仍读 TestCase 上的原外键，这里只补导航需要的多资产关系。"""
        case = self._writable_case(db, case_id, actor)
        seen: set[tuple[str, int]] = set()
        for item in body.items:
            if item.asset_type not in ASSET_TYPES:
                raise bad_request("资产类型取值非法")
            self._assert_asset(db, case.project_id, item.asset_type, item.asset_id)
            seen.add((item.asset_type, item.asset_id))
        db.query(TestCaseAsset).filter(TestCaseAsset.test_case_id == case.id).delete()
        rows = []
        for asset_type, asset_id in seen:
            row = TestCaseAsset(test_case_id=case.id, asset_type=asset_type, asset_id=asset_id)
            db.add(row)
            rows.append(row)
        db.commit()
        for row in rows:
            db.refresh(row)
        return [CaseAssetResponse.model_validate(row) for row in rows]

    def center_context(self, db: Session, case: TestCase) -> dict:
        """给用例详情补目录、资产、最近执行和执行器是否已开放。不提交事务。"""
        paths = self._scope_paths(db, case.id)
        assets = [
            CaseAssetResponse.model_validate(row)
            for row in db.query(TestCaseAsset).filter(TestCaseAsset.test_case_id == case.id).order_by(TestCaseAsset.id.asc()).all()
        ]
        executions = (
            db.query(CaseExecution)
            .filter(CaseExecution.test_case_id == case.id)
            .order_by(CaseExecution.id.desc())
            .limit(5)
            .all()
        )
        ready = (case.target_type or "").upper() != "AI"
        return {
            "agent_session_id": case.agent_session_id,
            "generation_version": case.generation_version,
            "direction": paths[0].direction if paths else direction_of_target(case.target_type),
            "executor_ready": ready,
            "executor_note": None if ready else "AI 用例的执行能力尚未开放，当前仅可维护，不能执行",
            "scope_paths": paths,
            "assets": assets,
            "recent_executions": [
                CaseExecutionBrief(
                    id=row.id,
                    status=row.status,
                    executor_type=row.executor_type,
                    error_code=row.error_code,
                    started_at=row.started_at,
                    finished_at=row.finished_at,
                )
                for row in executions
            ],
        }

    def attach_new_case(self, db: Session, case: TestCase) -> None:
        """新用例默认进入对应方向的待整理；已填写且属于本项目的 api_id 则挂到接口节点。不提交。"""
        self.ensure_inboxes(db, case.project_id, commit=False)
        node = None
        if (case.target_type or "").upper() == "API" and case.api_id is not None:
            node = self._ensure_interface_node(db, case.project_id, case.api_id)
            if node is not None:
                self._add_asset(db, case.id, "API_INTERFACE", case.api_id)
        if node is None:
            node = self._inbox(db, case.project_id, direction_of_target(case.target_type))
        self._add_scope(db, case.id, node.id)
        if case.business_flow_id is not None:
            self._add_asset(db, case.id, "BUSINESS_FLOW", case.business_flow_id)
        if case.business_action_id is not None:
            self._add_asset(db, case.id, "BUSINESS_ACTION", case.business_action_id)

    def ensure_inboxes(self, db: Session, project_id: int, *, commit: bool) -> None:
        """保证三个方向各有一个系统待整理节点。并发插入撞上唯一索引时回退到已有行。"""
        existing = {
            row.direction
            for row in db.query(TestScopeNode.direction).filter(
                TestScopeNode.project_id == project_id,
                TestScopeNode.is_system.is_(True),
            ).all()
        }
        missing = [direction for direction in DIRECTIONS if direction not in existing]
        if not missing:
            return
        nested = db.begin_nested()
        try:
            for direction in missing:
                db.add(TestScopeNode(
                    project_id=project_id,
                    direction=direction,
                    parent_id=None,
                    node_type="INBOX",
                    name=INBOX_NAME,
                    description="无法确定目录归属的用例放在这里",
                    sort_order=10_000,
                    status="ACTIVE",
                    is_system=True,
                ))
            db.flush()
            nested.commit()
        except IntegrityError:
            nested.rollback()
        if commit:
            db.commit()

    def _ensure_interface_node(self, db: Session, project_id: int, api_id: int) -> TestScopeNode | None:
        """按已有接口补一层模块和接口链接。接口不属于本项目时返回空，调用方改挂待整理。"""
        interface = db.get(ApiInterface, api_id)
        if interface is None or interface.project_id != project_id:
            return None
        found = self._find_asset_node(db, project_id, "API", "API_INTERFACE", interface.id)
        if found is not None:
            return found
        parent_id = None
        if interface.module_id is not None:
            module_node = self._ensure_module_node(db, project_id, interface.module_id)
            parent_id = module_node.id if module_node is not None else self._inbox(db, project_id, "API").id
        else:
            parent_id = self._inbox(db, project_id, "API").id
        return self._create_asset_node(
            db, project_id, "API", parent_id, "API_INTERFACE", interface.id, interface.name or f"接口 {interface.id}",
        )

    def _ensure_module_node(self, db: Session, project_id: int, module_id: int) -> TestScopeNode | None:
        """镜像接口模块。父模块尚未有节点时先建父节点，深度由 ApiModule 自身的两级限制卡住。"""
        module = db.get(ApiModule, module_id)
        if module is None or module.project_id != project_id:
            return None
        found = self._find_asset_node(db, project_id, "API", "API_MODULE", module.id)
        if found is not None:
            return found
        parent_id = None
        if module.parent_id is not None:
            parent = self._ensure_module_node(db, project_id, module.parent_id)
            parent_id = parent.id if parent is not None else None
        return self._create_asset_node(db, project_id, "API", parent_id, "API_MODULE", module.id, module.name)

    def _create_asset_node(
        self, db: Session, project_id: int, direction: str, parent_id: int | None,
        asset_type: str, asset_id: int, name: str,
    ) -> TestScopeNode:
        """插入资产链接。同级重名时加上资产 ID，和迁移的避让规则一致。"""
        clean = (name or "").strip() or f"{asset_type}-{asset_id}"
        if self._sibling_taken(db, project_id, direction, parent_id, clean):
            clean = f"{clean[:180]} #{asset_id}"
        row = TestScopeNode(
            project_id=project_id,
            direction=direction,
            parent_id=parent_id,
            node_type="ASSET_LINK",
            name=clean[:200],
            sort_order=0,
            status="ACTIVE",
            asset_type=asset_type,
            asset_id=asset_id,
            is_system=False,
        )
        db.add(row)
        db.flush()
        return row

    def _add_scope(self, db: Session, case_id: int, node_id: int) -> None:
        exists = db.query(TestCaseScope.id).filter(
            TestCaseScope.test_case_id == case_id,
            TestCaseScope.scope_node_id == node_id,
        ).first()
        if exists is None:
            db.add(TestCaseScope(test_case_id=case_id, scope_node_id=node_id))
            db.flush()

    def _add_asset(self, db: Session, case_id: int, asset_type: str, asset_id: int) -> None:
        exists = db.query(TestCaseAsset.id).filter(
            TestCaseAsset.test_case_id == case_id,
            TestCaseAsset.asset_type == asset_type,
            TestCaseAsset.asset_id == asset_id,
        ).first()
        if exists is None:
            db.add(TestCaseAsset(test_case_id=case_id, asset_type=asset_type, asset_id=asset_id))
            db.flush()

    def _query_node_ids(
        self, db: Session, project_id: int, direction: str | None, scope_node_id: int | None, include_descendants: bool,
    ) -> list[int] | None:
        """没有节点条件时返回 None，表示不按节点限制。节点不属于该项目则 404。"""
        if scope_node_id is None:
            return None
        node = self._node_in_project(db, scope_node_id, project_id)
        if direction is not None and node.direction != direction:
            raise bad_request("节点不属于所选测试方向")
        if not include_descendants:
            return [node.id]
        nodes = self._nodes(db, project_id, node.direction)
        children: dict[int | None, list[int]] = defaultdict(list)
        for item in nodes:
            children[item.parent_id].append(item.id)
        collected = []

        def walk(current: int) -> None:
            collected.append(current)
            for child_id in children.get(current, []):
                walk(child_id)

        walk(node.id)
        return collected

    def _recursive_counts(self, db: Session, nodes: list[TestScopeNode]) -> dict[int, tuple[int, int]]:
        """自底向上汇总用例和测试点。用例挂在多个子孙上时，祖先侧按用例 ID 去重。"""
        if not nodes:
            return {}
        node_ids = [node.id for node in nodes]
        links = db.query(TestCaseScope.scope_node_id, TestCase.id, TestCase.test_point_id).join(
            TestCase, TestCase.id == TestCaseScope.test_case_id,
        ).filter(TestCaseScope.scope_node_id.in_(node_ids)).all()
        direct_cases: dict[int, set[int]] = defaultdict(set)
        direct_points: dict[int, set[int]] = defaultdict(set)
        for node_id, case_id, point_id in links:
            direct_cases[node_id].add(case_id)
            if point_id is not None:
                direct_points[node_id].add(point_id)
        children: dict[int | None, list[int]] = defaultdict(list)
        for node in nodes:
            children[node.parent_id].append(node.id)
        cache: dict[int, tuple[set[int], set[int]]] = {}

        def walk(node_id: int) -> tuple[set[int], set[int]]:
            if node_id in cache:
                return cache[node_id]
            cases = set(direct_cases.get(node_id, set()))
            points = set(direct_points.get(node_id, set()))
            for child_id in children.get(node_id, []):
                child_cases, child_points = walk(child_id)
                cases |= child_cases
                points |= child_points
            cache[node_id] = (cases, points)
            return cache[node_id]

        for node in nodes:
            walk(node.id)
        return {node_id: (len(cases), len(points)) for node_id, (cases, points) in cache.items()}

    def _scope_paths(self, db: Session, case_id: int) -> list[ScopePathResponse]:
        links = db.query(TestCaseScope).filter(TestCaseScope.test_case_id == case_id).order_by(TestCaseScope.id.asc()).all()
        if not links:
            return []
        node_ids = [link.scope_node_id for link in links]
        nodes = db.query(TestScopeNode).filter(TestScopeNode.id.in_(node_ids)).all()
        by_id = {node.id: node for node in nodes}
        for node in nodes:
            cursor = node
            guard = 0
            while cursor.parent_id is not None and cursor.parent_id not in by_id and guard < 50:
                parent = db.get(TestScopeNode, cursor.parent_id)
                if parent is None:
                    break
                by_id[parent.id] = parent
                cursor = parent
                guard += 1
        result = []
        for link in links:
            node = by_id.get(link.scope_node_id)
            if node is None:
                continue
            result.append(ScopePathResponse(
                scope_node_id=node.id,
                direction=node.direction,
                path=self._path(node, by_id),
            ))
        return result

    def _path(self, node: TestScopeNode, by_id: dict[int, TestScopeNode]) -> list[ScopePathItem]:
        chain = [node]
        cursor = node
        guard = 0
        while cursor.parent_id is not None and guard < 50:
            parent = by_id.get(cursor.parent_id)
            if parent is None:
                break
            chain.append(parent)
            cursor = parent
            guard += 1
        chain.reverse()
        return [ScopePathItem(id=item.id, name=item.name, node_type=item.node_type) for item in chain]

    def _primary_direction(self, db: Session, case_ids: list[int]) -> dict[int, str]:
        if not case_ids:
            return {}
        rows = (
            db.query(TestCaseScope.test_case_id, TestScopeNode.direction)
            .join(TestScopeNode, TestScopeNode.id == TestCaseScope.scope_node_id)
            .filter(TestCaseScope.test_case_id.in_(case_ids))
            .order_by(TestCaseScope.id.asc())
            .all()
        )
        found: dict[int, str] = {}
        for case_id, direction in rows:
            found.setdefault(case_id, direction)
        return found

    def _nodes(self, db: Session, project_id: int, direction: str) -> list[TestScopeNode]:
        return db.query(TestScopeNode).filter(
            TestScopeNode.project_id == project_id,
            TestScopeNode.direction == direction,
        ).all()

    def _ordered(self, nodes: list[TestScopeNode]) -> list[TestScopeNode]:
        return sorted(nodes, key=lambda item: (item.parent_id or 0, item.sort_order, item.id))

    def _node_response(self, node: TestScopeNode, counts: dict[int, tuple[int, int]]) -> ScopeNodeResponse:
        case_count, point_count = counts.get(node.id, (0, 0))
        return ScopeNodeResponse(
            id=node.id,
            project_id=node.project_id,
            direction=node.direction,
            parent_id=node.parent_id,
            node_type=node.node_type,
            name=node.name,
            description=node.description,
            sort_order=node.sort_order,
            status=node.status,
            asset_type=node.asset_type,
            asset_id=node.asset_id,
            is_system=node.is_system,
            case_count=case_count,
            point_count=point_count,
            created_at=node.created_at,
            updated_at=node.updated_at,
        )

    def _visible_node(self, db: Session, node_id: int, user: User) -> TestScopeNode:
        node = db.get(TestScopeNode, node_id)
        if node is None:
            raise not_found("测试范围不存在")
        get_project_or_404(db, node.project_id, user)
        return node

    def _writable_node(self, db: Session, node_id: int, actor: User) -> TestScopeNode:
        node = db.get(TestScopeNode, node_id)
        if node is None:
            raise not_found("测试范围不存在")
        require_writable_project(db, node.project_id, actor)
        return node

    def _node_in_project(self, db: Session, node_id: int, project_id: int) -> TestScopeNode:
        node = db.get(TestScopeNode, node_id)
        if node is None or node.project_id != project_id:
            raise not_found("测试范围不存在")
        return node

    def _writable_case(self, db: Session, case_id: int, actor: User) -> TestCase:
        case = db.get(TestCase, case_id)
        if case is None:
            raise not_found("测试用例不存在")
        require_writable_project(db, case.project_id, actor)
        return case

    def _cases_in_project(self, db: Session, project_id: int, case_ids: list[int]) -> list[TestCase]:
        unique_ids = list(dict.fromkeys(case_ids))
        rows = db.query(TestCase).filter(TestCase.id.in_(unique_ids), TestCase.project_id == project_id).all()
        if len(rows) != len(unique_ids):
            raise not_found("测试用例不存在")
        return rows

    def _parent_for_write(
        self, db: Session, project_id: int, direction: str, parent_id: int | None,
    ) -> TestScopeNode | None:
        if parent_id is None:
            return None
        parent = self._node_in_project(db, parent_id, project_id)
        if parent.direction != direction:
            raise bad_request("父节点不属于所选测试方向")
        return parent

    def _is_descendant(self, db: Session, node: TestScopeNode, candidate: TestScopeNode) -> bool:
        cursor = candidate
        guard = 0
        while cursor.parent_id is not None and guard < 50:
            if cursor.parent_id == node.id:
                return True
            parent = db.get(TestScopeNode, cursor.parent_id)
            if parent is None:
                return False
            cursor = parent
            guard += 1
        return False

    def _inbox(self, db: Session, project_id: int, direction: str) -> TestScopeNode:
        row = db.query(TestScopeNode).filter(
            TestScopeNode.project_id == project_id,
            TestScopeNode.direction == direction,
            TestScopeNode.is_system.is_(True),
        ).one()
        return row

    def _find_asset_node(
        self, db: Session, project_id: int, direction: str, asset_type: str, asset_id: int,
    ) -> TestScopeNode | None:
        return db.query(TestScopeNode).filter(
            TestScopeNode.project_id == project_id,
            TestScopeNode.direction == direction,
            TestScopeNode.asset_type == asset_type,
            TestScopeNode.asset_id == asset_id,
        ).first()

    def _ensure_sibling_name(
        self, db: Session, project_id: int, direction: str, parent_id: int | None, name: str, exclude_id: int | None = None,
    ) -> None:
        if self._sibling_taken(db, project_id, direction, parent_id, name, exclude_id=exclude_id):
            raise conflict("同级已有同名节点")

    def _sibling_taken(
        self, db: Session, project_id: int, direction: str, parent_id: int | None, name: str, exclude_id: int | None = None,
    ) -> bool:
        query = db.query(TestScopeNode.id).filter(
            TestScopeNode.project_id == project_id,
            TestScopeNode.direction == direction,
            TestScopeNode.name == name,
        )
        if parent_id is None:
            query = query.filter(TestScopeNode.parent_id.is_(None))
        else:
            query = query.filter(TestScopeNode.parent_id == parent_id)
        if exclude_id is not None:
            query = query.filter(TestScopeNode.id != exclude_id)
        return query.first() is not None

    def _next_sort(self, db: Session, project_id: int, direction: str, parent_id: int | None) -> int:
        query = db.query(TestScopeNode.sort_order).filter(
            TestScopeNode.project_id == project_id,
            TestScopeNode.direction == direction,
        )
        if parent_id is None:
            query = query.filter(TestScopeNode.parent_id.is_(None))
        else:
            query = query.filter(TestScopeNode.parent_id == parent_id)
        current = query.order_by(TestScopeNode.sort_order.desc()).first()
        if current is None:
            return 0
        return int(current[0]) + 1

    def _validate_node_shape(self, db: Session, project_id: int, node_type: str, asset_type: str | None, asset_id: int | None) -> None:
        if node_type == "FOLDER":
            if asset_type is not None or asset_id is not None:
                raise bad_request("目录节点不能绑定资产")
            return
        if node_type != "ASSET_LINK":
            raise bad_request("不能手工创建待整理节点")
        if asset_type is None or asset_id is None:
            raise bad_request("资产链接必须指定资产类型和资产 ID")
        if asset_type not in ASSET_TYPES:
            raise bad_request("资产类型取值非法")
        self._assert_asset(db, project_id, asset_type, asset_id)

    def _assert_asset(self, db: Session, project_id: int, asset_type: str, asset_id: int) -> None:
        """资产必须属于当前项目。Agent 定义是平台级配置，只校验存在，不复制配置。"""
        if asset_type == "API_MODULE":
            row = db.get(ApiModule, asset_id)
            ok = row is not None and row.project_id == project_id
        elif asset_type == "API_INTERFACE":
            row = db.get(ApiInterface, asset_id)
            ok = row is not None and row.project_id == project_id
        elif asset_type == "BUSINESS_DOMAIN":
            row = db.get(BusinessDomain, asset_id)
            ok = row is not None and row.project_id == project_id
        elif asset_type == "BUSINESS_FLOW":
            row = db.get(BusinessFlow, asset_id)
            ok = row is not None and row.project_id == project_id
        elif asset_type == "BUSINESS_ACTION":
            row = db.get(BusinessAction, asset_id)
            flow = db.get(BusinessFlow, row.flow_id) if row is not None else None
            ok = flow is not None and flow.project_id == project_id
        elif asset_type == "WEB_PAGE":
            row = db.get(PageObject, asset_id)
            ok = row is not None and row.project_id == project_id
        elif asset_type == "AGENT":
            ok = db.get(AgentDefinition, asset_id) is not None
        else:
            ok = False
        if not ok:
            raise not_found("关联资产不存在")

    def _require_direction(self, direction: str) -> None:
        if direction not in DIRECTIONS:
            raise bad_request("测试方向取值非法")
