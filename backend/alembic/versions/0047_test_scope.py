"""测试范围表，并把存量用例挂到导航节点上。

Revision ID: 0047
Revises: 0046

不复制接口、业务、页面或 Agent。ApiModule / ApiInterface 只生成资产链接节点。
api_id 为空时，仅当描述里的方法+路径在项目内归一化后唯一命中才回填。
无法归属的用例进入对应方向的「待整理」，不删除任何正式测试资产。

降级会删掉范围表，并只撤销本次回填的 api_id。
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op
from sqlalchemy import text
from sqlalchemy.sql import func

from app.features.test_management.scope_placement import (
    INBOX_NAME,
    backfill_api_id,
    direction_of_target,
    interface_index,
)

revision = "0047"
down_revision = "0046"
branch_labels = None
depends_on = None

_PRESERVE_TABLES = (
    "test_case",
    "test_point",
    "test_strategy",
    "test_case_precondition",
    "test_case_data",
    "test_step",
    "test_assertion",
    "test_suite",
    "test_suite_case",
    "test_plan",
    "test_plan_suite",
    "test_run",
    "case_execution",
)


def _count(bind, table: str) -> int:
    """迁移前后对同一张正式表计数。表名来自白名单，不拼接外部输入。"""
    return int(bind.execute(text(f"SELECT COUNT(*) FROM {table}")).scalar() or 0)


def _insert_node(bind, **values) -> int:
    """插入一个范围节点并返回 ID。名称冲突由调用方事先避开。"""
    row = bind.execute(
        text(
            """
            INSERT INTO test_scope_node
                (project_id, direction, parent_id, node_type, name, description,
                 sort_order, status, asset_type, asset_id, is_system, created_at, updated_at)
            VALUES
                (:project_id, :direction, :parent_id, :node_type, :name, :description,
                 :sort_order, 'ACTIVE', :asset_type, :asset_id, :is_system, CURRENT_TIMESTAMP, CURRENT_TIMESTAMP)
            RETURNING id
            """
        ),
        values,
    ).scalar()
    return int(row)


def _take_name(used: dict[tuple, set[str]], parent_key: tuple, name: str, entity_id: int) -> str:
    """同级重名时加上资产 ID，避免唯一索引把整次迁移打回。"""
    bucket = used.setdefault(parent_key, set())
    candidate = (name or "").strip() or f"未命名-{entity_id}"
    if candidate not in bucket:
        bucket.add(candidate)
        return candidate[:200]
    suffixed = f"{candidate[:180]} #{entity_id}"
    bucket.add(suffixed)
    return suffixed


def _link_case(bind, case_id: int, node_id: int) -> None:
    bind.execute(
        text(
            """
            INSERT INTO test_case_scope (test_case_id, scope_node_id, created_at)
            VALUES (:case_id, :node_id, CURRENT_TIMESTAMP)
            ON CONFLICT (test_case_id, scope_node_id) DO NOTHING
            """
        ),
        {"case_id": case_id, "node_id": node_id},
    )


def _link_asset(bind, case_id: int, asset_type: str, asset_id: int | None) -> None:
    if asset_id is None:
        return
    bind.execute(
        text(
            """
            INSERT INTO test_case_asset (test_case_id, asset_type, asset_id, created_at)
            VALUES (:case_id, :asset_type, :asset_id, CURRENT_TIMESTAMP)
            ON CONFLICT (test_case_id, asset_type, asset_id) DO NOTHING
            """
        ),
        {"case_id": case_id, "asset_type": asset_type, "asset_id": asset_id},
    )


def upgrade():
    op.create_table(
        "test_scope_node",
        sa.Column("id", sa.Integer(), primary_key=True, autoincrement=True),
        sa.Column("project_id", sa.Integer(), sa.ForeignKey("project.id", ondelete="CASCADE"), nullable=False),
        sa.Column("direction", sa.String(10), nullable=False),
        sa.Column("parent_id", sa.Integer(), sa.ForeignKey("test_scope_node.id", ondelete="RESTRICT"), nullable=True),
        sa.Column("node_type", sa.String(20), nullable=False),
        sa.Column("name", sa.String(200), nullable=False),
        sa.Column("description", sa.String(1000), nullable=True),
        sa.Column("sort_order", sa.Integer(), nullable=False, server_default=sa.text("0")),
        sa.Column("status", sa.String(20), nullable=False, server_default=sa.text("'ACTIVE'")),
        sa.Column("asset_type", sa.String(40), nullable=True),
        sa.Column("asset_id", sa.Integer(), nullable=True),
        sa.Column("is_system", sa.Boolean(), nullable=False, server_default=sa.text("false")),
        sa.Column("created_by", sa.Integer(), sa.ForeignKey("user.id", ondelete="SET NULL"), nullable=True),
        sa.Column("created_at", sa.DateTime(), nullable=False, server_default=func.now()),
        sa.Column("updated_at", sa.DateTime(), nullable=False, server_default=func.now()),
    )
    op.create_index("ix_test_scope_node_project_id", "test_scope_node", ["project_id"])
    op.create_index(
        "ix_test_scope_project_direction_parent",
        "test_scope_node",
        ["project_id", "direction", "parent_id"],
    )
    op.create_index("ix_test_scope_asset", "test_scope_node", ["project_id", "asset_type", "asset_id"])
    op.execute(
        """
        CREATE UNIQUE INDEX uq_test_scope_root_name
        ON test_scope_node (project_id, direction, name)
        WHERE parent_id IS NULL
        """
    )
    op.execute(
        """
        CREATE UNIQUE INDEX uq_test_scope_child_name
        ON test_scope_node (project_id, direction, parent_id, name)
        WHERE parent_id IS NOT NULL
        """
    )
    op.execute(
        """
        CREATE UNIQUE INDEX uq_test_scope_system_inbox
        ON test_scope_node (project_id, direction)
        WHERE is_system IS TRUE
        """
    )
    op.create_table(
        "test_case_scope",
        sa.Column("id", sa.Integer(), primary_key=True, autoincrement=True),
        sa.Column("test_case_id", sa.Integer(), sa.ForeignKey("test_case.id", ondelete="CASCADE"), nullable=False),
        sa.Column("scope_node_id", sa.Integer(), sa.ForeignKey("test_scope_node.id", ondelete="CASCADE"), nullable=False),
        sa.Column("created_at", sa.DateTime(), nullable=False, server_default=func.now()),
        sa.UniqueConstraint("test_case_id", "scope_node_id", name="uq_test_case_scope_case_node"),
    )
    op.create_index("ix_test_case_scope_test_case_id", "test_case_scope", ["test_case_id"])
    op.create_index("ix_test_case_scope_node", "test_case_scope", ["scope_node_id"])
    op.create_table(
        "test_case_asset",
        sa.Column("id", sa.Integer(), primary_key=True, autoincrement=True),
        sa.Column("test_case_id", sa.Integer(), sa.ForeignKey("test_case.id", ondelete="CASCADE"), nullable=False),
        sa.Column("asset_type", sa.String(40), nullable=False),
        sa.Column("asset_id", sa.Integer(), nullable=False),
        sa.Column("created_at", sa.DateTime(), nullable=False, server_default=func.now()),
        sa.UniqueConstraint("test_case_id", "asset_type", "asset_id", name="uq_test_case_asset_target"),
    )
    op.create_index("ix_test_case_asset_test_case_id", "test_case_asset", ["test_case_id"])
    op.create_table(
        "test_scope_migration_check",
        sa.Column("id", sa.Integer(), primary_key=True, autoincrement=True),
        sa.Column("metric", sa.String(80), nullable=False, unique=True),
        sa.Column("before_count", sa.Integer(), nullable=False),
        sa.Column("after_count", sa.Integer(), nullable=False),
    )
    op.create_table(
        "test_scope_api_backfill",
        sa.Column("test_case_id", sa.Integer(), sa.ForeignKey("test_case.id", ondelete="CASCADE"), primary_key=True),
    )

    bind = op.get_bind()
    before = {table: _count(bind, table) for table in _PRESERVE_TABLES}
    before_api = int(bind.execute(text("SELECT COUNT(*) FROM test_case WHERE api_id IS NOT NULL")).scalar() or 0)

    projects = [int(row[0]) for row in bind.execute(text("SELECT id FROM project")).fetchall()]
    for project_id in projects:
        _place_project(bind, project_id)

    after = {table: _count(bind, table) for table in _PRESERVE_TABLES}
    after_api = int(bind.execute(text("SELECT COUNT(*) FROM test_case WHERE api_id IS NOT NULL")).scalar() or 0)
    scoped = int(bind.execute(text("SELECT COUNT(DISTINCT test_case_id) FROM test_case_scope")).scalar() or 0)
    for table, before_count in before.items():
        after_count = after[table]
        if before_count != after_count:
            raise RuntimeError(f"迁移改变了 {table} 的行数：{before_count} -> {after_count}")
        bind.execute(
            text(
                """
                INSERT INTO test_scope_migration_check (metric, before_count, after_count)
                VALUES (:metric, :before_count, :after_count)
                """
            ),
            {"metric": table, "before_count": before_count, "after_count": after_count},
        )
    if after["test_case"] != scoped:
        raise RuntimeError(f"有用例没有进入范围：用例 {after['test_case']}，已归属 {scoped}")
    if after_api < before_api:
        raise RuntimeError("迁移减少了已有 api_id")
    bind.execute(
        text(
            """
            INSERT INTO test_scope_migration_check (metric, before_count, after_count)
            VALUES ('test_case_scoped', :before_count, :after_count)
            """
        ),
        {"before_count": 0, "after_count": scoped},
    )
    bind.execute(
        text(
            """
            INSERT INTO test_scope_migration_check (metric, before_count, after_count)
            VALUES ('test_case_api_id', :before_count, :after_count)
            """
        ),
        {"before_count": before_api, "after_count": after_api},
    )


def _place_project(bind, project_id: int) -> None:
    """为一个项目补三个收件箱、接口链接节点，再把用例挂上去。"""
    used: dict[tuple, set[str]] = {}
    inboxes: dict[str, int] = {}
    for index, direction in enumerate(("API", "UI", "AI")):
        name = _take_name(used, (project_id, direction, None), INBOX_NAME, index)
        inboxes[direction] = _insert_node(
            bind,
            project_id=project_id,
            direction=direction,
            parent_id=None,
            node_type="INBOX",
            name=name,
            description="无法确定目录归属的用例放在这里",
            sort_order=10_000,
            asset_type=None,
            asset_id=None,
            is_system=True,
        )

    modules = bind.execute(
        text("SELECT id, parent_id, name, sort FROM api_module WHERE project_id = :project_id ORDER BY id"),
        {"project_id": project_id},
    ).fetchall()
    module_node: dict[int, int] = {}
    pending = list(modules)
    # 模块最多两级，多轮是为了父模块先落节点；父缺失时挂到 API 待整理下，不丢模块。
    for _ in range(4):
        if not pending:
            break
        next_pending = []
        for module_id, parent_id, name, sort in pending:
            parent_node = None
            if parent_id is not None:
                parent_node = module_node.get(int(parent_id))
                if parent_node is None and any(int(item[0]) == int(parent_id) for item in modules):
                    next_pending.append((module_id, parent_id, name, sort))
                    continue
            parent_key = (project_id, "API", parent_node)
            node_name = _take_name(used, parent_key, str(name), int(module_id))
            module_node[int(module_id)] = _insert_node(
                bind,
                project_id=project_id,
                direction="API",
                parent_id=parent_node,
                node_type="ASSET_LINK",
                name=node_name,
                description=None,
                sort_order=int(sort or 0),
                asset_type="API_MODULE",
                asset_id=int(module_id),
                is_system=False,
            )
        pending = next_pending
    for module_id, _parent_id, name, sort in pending:
        node_name = _take_name(used, (project_id, "API", inboxes["API"]), str(name), int(module_id))
        module_node[int(module_id)] = _insert_node(
            bind,
            project_id=project_id,
            direction="API",
            parent_id=inboxes["API"],
            node_type="ASSET_LINK",
            name=node_name,
            description=None,
            sort_order=int(sort or 0),
            asset_type="API_MODULE",
            asset_id=int(module_id),
            is_system=False,
        )

    interfaces = bind.execute(
        text(
            """
            SELECT id, module_id, name, method, path
            FROM api_interface
            WHERE project_id = :project_id
            ORDER BY id
            """
        ),
        {"project_id": project_id},
    ).fetchall()
    interface_node: dict[int, int] = {}
    indexed = interface_index([(int(row[0]), str(row[3]), str(row[4])) for row in interfaces])
    for interface_id, module_id, name, _method, path in interfaces:
        parent_node = module_node.get(int(module_id)) if module_id is not None else None
        if parent_node is None:
            parent_node = inboxes["API"]
        label = str(name or "").strip() or f"{_method} {path}"
        node_name = _take_name(used, (project_id, "API", parent_node), label, int(interface_id))
        interface_node[int(interface_id)] = _insert_node(
            bind,
            project_id=project_id,
            direction="API",
            parent_id=parent_node,
            node_type="ASSET_LINK",
            name=node_name,
            description=None,
            sort_order=0,
            asset_type="API_INTERFACE",
            asset_id=int(interface_id),
            is_system=False,
        )

    flows = {
        int(row[0]): str(row[1])
        for row in bind.execute(
            text("SELECT id, name FROM business_flow WHERE project_id = :project_id"),
            {"project_id": project_id},
        ).fetchall()
    }
    actions = {
        int(row[0]): (str(row[1]), int(row[2]))
        for row in bind.execute(
            text(
                """
                SELECT a.id, a.name, a.flow_id
                FROM business_action a
                JOIN business_flow f ON f.id = a.flow_id
                WHERE f.project_id = :project_id
                """
            ),
            {"project_id": project_id},
        ).fetchall()
    }
    flow_nodes: dict[int, int] = {}
    action_nodes: dict[int, int] = {}

    def ensure_flow_node(flow_id: int) -> int | None:
        if flow_id not in flows:
            return None
        if flow_id not in flow_nodes:
            node_name = _take_name(used, (project_id, "API", None), flows[flow_id], flow_id)
            flow_nodes[flow_id] = _insert_node(
                bind,
                project_id=project_id,
                direction="API",
                parent_id=None,
                node_type="ASSET_LINK",
                name=node_name,
                description=None,
                sort_order=0,
                asset_type="BUSINESS_FLOW",
                asset_id=flow_id,
                is_system=False,
            )
        return flow_nodes[flow_id]

    def ensure_action_node(action_id: int) -> int | None:
        if action_id not in actions:
            return None
        if action_id not in action_nodes:
            action_name, flow_id = actions[action_id]
            parent = ensure_flow_node(flow_id) or inboxes["API"]
            node_name = _take_name(used, (project_id, "API", parent), action_name, action_id)
            action_nodes[action_id] = _insert_node(
                bind,
                project_id=project_id,
                direction="API",
                parent_id=parent,
                node_type="ASSET_LINK",
                name=node_name,
                description=None,
                sort_order=0,
                asset_type="BUSINESS_ACTION",
                asset_id=action_id,
                is_system=False,
            )
        return action_nodes[action_id]

    cases = bind.execute(
        text(
            """
            SELECT id, target_type, api_id, description, business_flow_id, business_action_id
            FROM test_case
            WHERE project_id = :project_id
            ORDER BY id
            """
        ),
        {"project_id": project_id},
    ).fetchall()
    for case_id, target_type, api_id, description, flow_id, action_id in cases:
        case_id = int(case_id)
        direction = direction_of_target(target_type)
        chosen = None
        if (target_type or "API").upper() == "API":
            resolved = int(api_id) if api_id is not None else None
            if resolved is None:
                # 归一化后不唯一就不回填，避免把数字路径段错绑到别的接口。
                resolved = backfill_api_id(description, indexed)
                if resolved is not None:
                    bind.execute(
                        text("UPDATE test_case SET api_id = :api_id WHERE id = :case_id AND api_id IS NULL"),
                        {"api_id": resolved, "case_id": case_id},
                    )
                    bind.execute(
                        text("INSERT INTO test_scope_api_backfill (test_case_id) VALUES (:case_id)"),
                        {"case_id": case_id},
                    )
            if resolved is not None and resolved in interface_node:
                chosen = interface_node[resolved]
                # 只关联本项目接口。解析不到或命中多条时不写 api_id，用例稍后进入待整理。
                _link_asset(bind, case_id, "API_INTERFACE", resolved)
        elif (target_type or "").upper() == "BUSINESS_ACTION" and action_id is not None:
            chosen = ensure_action_node(int(action_id))
        elif (target_type or "").upper() == "BUSINESS_FLOW" and flow_id is not None:
            chosen = ensure_flow_node(int(flow_id))
        _link_case(bind, case_id, chosen or inboxes[direction])
        if flow_id is not None and int(flow_id) in flows:
            _link_asset(bind, case_id, "BUSINESS_FLOW", int(flow_id))
        if action_id is not None and int(action_id) in actions:
            _link_asset(bind, case_id, "BUSINESS_ACTION", int(action_id))


def downgrade():
    bind = op.get_bind()
    bind.execute(
        text(
            """
            UPDATE test_case
            SET api_id = NULL
            WHERE id IN (SELECT test_case_id FROM test_scope_api_backfill)
            """
        )
    )
    op.drop_table("test_scope_api_backfill")
    op.drop_table("test_scope_migration_check")
    op.drop_table("test_case_asset")
    op.drop_table("test_case_scope")
    op.execute("DROP INDEX IF EXISTS uq_test_scope_system_inbox")
    op.execute("DROP INDEX IF EXISTS uq_test_scope_child_name")
    op.execute("DROP INDEX IF EXISTS uq_test_scope_root_name")
    op.drop_table("test_scope_node")
