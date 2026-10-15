"""业务管理第二阶段：执行引擎基础。

变更：
1. business_action.action_type 默认值从 'API' 改为 'NORMAL'
2. business_binding 增加 name/is_default/sort，移除 (action_id, binding_type) 唯一约束，
   增加部分唯一索引：同一 action + binding_type 最多一个默认绑定
3. business_variable_ref 增加 source_variable_id / target_variable_id FK
4. business_flow / business_action 增加 revision 乐观锁字段
5. 新建 flow_execution / action_execution 两张执行记录表

幂等设计：inspect() 检查表/列/索引存在性。

迁移事务：alembic 在线模式已用 context.begin_transaction() 包裹整批迁移，本迁移内的
语句直接在该事务上执行（conn.execute / op.* 操作），**不得**再 ``with conn.begin():``
显式开第二层事务——SQLAlchemy 2.0 会抛
「This connection has already initialized a Transaction object via begin() or autobegin」。
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op
from sqlalchemy import inspect, text

revision = "0005"
down_revision = "0004"
branch_labels = None
depends_on = None


def upgrade() -> None:
    conn = op.get_bind()
    inspector = inspect(conn)

    # ----------------------------------------------------------------- 1. action_type 默认值
    # 先将现有 action_type='API' 的更新为 'NORMAL'（API 通道现在由 binding 承载）。
    conn.execute(sa.text("UPDATE business_action SET action_type = 'NORMAL' WHERE action_type = 'API'"))
    # 修改列默认值。
    op.alter_column(
        "business_action", "action_type",
        server_default=sa.text("'NORMAL'"),
    )

    # ----------------------------------------------------------------- 2. binding 增强
    cols = {c["name"] for c in inspector.get_columns("business_binding")}
    if "name" not in cols:
        op.add_column("business_binding", sa.Column(
            "name", sa.String(200), nullable=True,
            comment="绑定名称（如 API v1 / API v2）",
        ))
    if "is_default" not in cols:
        op.add_column("business_binding", sa.Column(
            "is_default", sa.Boolean(), nullable=False,
            server_default=sa.text("true"),
            comment="是否为默认绑定（执行时使用）",
        ))
    if "sort" not in cols:
        op.add_column("business_binding", sa.Column(
            "sort", sa.Integer(), nullable=False,
            server_default=sa.text("0"),
            comment="绑定排序值",
        ))

    # 移除旧的 (action_id, binding_type) 唯一约束（如果存在）。
    # 唯一约束在 PG 中会自动建同名索引；直接 DROP INDEX 会因「约束依赖该索引」失败，
    # 必须先 ALTER TABLE DROP CONSTRAINT（连带删除其同名索引），再清理残留纯索引。
    existing_uqs = [c["name"] for c in inspector.get_unique_constraints("business_binding")
                    if (c.get("name") or "").startswith("uq_business_binding")]
    for cname in existing_uqs:
        conn.execute(sa.text(f'ALTER TABLE business_binding DROP CONSTRAINT IF EXISTS "{cname}"'))
    existing_indexes = [idx["name"] for idx in inspector.get_indexes("business_binding")
                        if (idx.get("name") or "").startswith("uq_business_binding")]
    for iname in existing_indexes:
        conn.execute(sa.text(f'DROP INDEX IF EXISTS "{iname}"'))

    # 增加部分唯一索引：同一 action + binding_type 最多一个默认绑定。
    conn.execute(sa.text(
        "CREATE UNIQUE INDEX IF NOT EXISTS ix_business_binding_action_default "
        "ON business_binding (action_id, binding_type) WHERE is_default = true"
    ))

    # ----------------------------------------------------------------- 3. variable_ref FK 增强
    ref_cols = {c["name"] for c in inspector.get_columns("business_variable_ref")}
    if "source_variable_id" not in ref_cols:
        op.add_column("business_variable_ref", sa.Column(
            "source_variable_id", sa.Integer(),
            sa.ForeignKey("business_variable.id", ondelete="SET NULL"),
            nullable=True,
            comment="来源变量ID（FK → business_variable）",
        ))
    if "target_variable_id" not in ref_cols:
        op.add_column("business_variable_ref", sa.Column(
            "target_variable_id", sa.Integer(),
            sa.ForeignKey("business_variable.id", ondelete="SET NULL"),
            nullable=True,
            comment="目标变量ID（FK → business_variable）",
        ))

    # ----------------------------------------------------------------- 4. 乐观锁 revision
    flow_cols = {c["name"] for c in inspector.get_columns("business_flow")}
    if "revision" not in flow_cols:
        op.add_column("business_flow", sa.Column(
            "revision", sa.Integer(), nullable=False,
            server_default=sa.text("1"),
            comment="乐观锁版本号",
        ))

    action_cols = {c["name"] for c in inspector.get_columns("business_action")}
    if "revision" not in action_cols:
        op.add_column("business_action", sa.Column(
            "revision", sa.Integer(), nullable=False,
            server_default=sa.text("1"),
            comment="乐观锁版本号",
        ))

    # ----------------------------------------------------------------- 5. flow_execution
    if "flow_execution" not in inspector.get_table_names():
        op.create_table(
            "flow_execution",
            sa.Column("id", sa.Integer(), primary_key=True, autoincrement=True),
            sa.Column("project_id", sa.Integer(),
                      sa.ForeignKey("project.id", ondelete="CASCADE"),
                      nullable=False, index=True),
            sa.Column("flow_id", sa.Integer(),
                      sa.ForeignKey("business_flow.id", ondelete="CASCADE"),
                      nullable=False, index=True),
            sa.Column("environment_id", sa.Integer(),
                      sa.ForeignKey("environment.id", ondelete="SET NULL"),
                      nullable=True),
            sa.Column("status", sa.String(20), nullable=False,
                      server_default=sa.text("'PENDING'"), index=True,
                      comment="执行状态：PENDING/RUNNING/SUCCESS/FAILED/CANCELLED"),
            sa.Column("started_at", sa.DateTime(), nullable=True),
            sa.Column("finished_at", sa.DateTime(), nullable=True),
            sa.Column("context_json", sa.JSON(), nullable=True,
                      comment="运行时上下文（变量键值对）"),
            sa.Column("error_message", sa.Text(), nullable=True,
                      comment="整体错误信息"),
            sa.Column("error_code", sa.String(50), nullable=True,
                      comment="标准化错误代码"),
            sa.Column("created_by", sa.Integer(),
                      sa.ForeignKey("user.id", ondelete="SET NULL"),
                      nullable=True),
            sa.Column("revision", sa.Integer(), nullable=False,
                      server_default=sa.text("1"),
                      comment="乐观锁版本号"),
            sa.Column("created_at", sa.DateTime(), nullable=False,
                      server_default=sa.text("now()")),
            sa.Column("updated_at", sa.DateTime(), nullable=False,
                      server_default=sa.text("now()"), onupdate=sa.text("now()")),
            comment="业务流程执行记录",
        )
        conn.execute(sa.text(
            "CREATE INDEX IF NOT EXISTS ix_flow_execution_project_status "
            "ON flow_execution (project_id, status)"
        ))

    # ----------------------------------------------------------------- 6. action_execution
    if "action_execution" not in inspector.get_table_names():
        op.create_table(
            "action_execution",
            sa.Column("id", sa.Integer(), primary_key=True, autoincrement=True),
            sa.Column("flow_execution_id", sa.Integer(),
                      sa.ForeignKey("flow_execution.id", ondelete="CASCADE"),
                      nullable=False, index=True),
            sa.Column("action_id", sa.Integer(),
                      sa.ForeignKey("business_action.id", ondelete="SET NULL"),
                      nullable=True, index=True),
            sa.Column("binding_id", sa.Integer(),
                      sa.ForeignKey("business_binding.id", ondelete="SET NULL"),
                      nullable=True),
            sa.Column("sequence", sa.Integer(), nullable=False,
                      server_default=sa.text("0"),
                      comment="执行序号（从 0 开始）"),
            sa.Column("status", sa.String(20), nullable=False,
                      server_default=sa.text("'PENDING'"), index=True,
                      comment="步骤状态：PENDING/RUNNING/SUCCESS/FAILED/SKIPPED"),
            sa.Column("request_snapshot", sa.JSON(), nullable=True,
                      comment="请求快照（脱敏后）：method/url/headers/query/body"),
            sa.Column("response_snapshot", sa.JSON(), nullable=True,
                      comment="响应快照（脱敏后）：status_code/headers/body"),
            sa.Column("input_context", sa.JSON(), nullable=True,
                      comment="步骤输入上下文"),
            sa.Column("output_context", sa.JSON(), nullable=True,
                      comment="步骤输出上下文"),
            sa.Column("started_at", sa.DateTime(), nullable=True),
            sa.Column("finished_at", sa.DateTime(), nullable=True),
            sa.Column("duration_ms", sa.Integer(), nullable=True,
                      comment="执行耗时（毫秒）"),
            sa.Column("error_message", sa.Text(), nullable=True,
                      comment="错误信息"),
            sa.Column("error_code", sa.String(50), nullable=True,
                      comment="标准化错误代码"),
            sa.Column("unverified_preconditions", sa.JSON(), nullable=True,
                      comment="无法自动验证的前置条件列表（BUSINESS/TEXT 类型）"),
            sa.Column("created_at", sa.DateTime(), nullable=False,
                      server_default=sa.text("now()")),
            sa.Column("updated_at", sa.DateTime(), nullable=False,
                      server_default=sa.text("now()"), onupdate=sa.text("now()")),
            comment="业务步骤执行记录",
        )
        conn.execute(sa.text(
            "CREATE INDEX IF NOT EXISTS ix_action_execution_flow_sequence "
            "ON action_execution (flow_execution_id, sequence)"
        ))


def downgrade() -> None:
    conn = op.get_bind()

    # 6. action_execution
    conn.execute(sa.text("DROP TABLE IF EXISTS action_execution"))

    # 5. flow_execution
    conn.execute(sa.text("DROP TABLE IF EXISTS flow_execution"))

    # 4. 乐观锁
    conn.execute(sa.text("ALTER TABLE business_action DROP COLUMN IF EXISTS revision"))
    conn.execute(sa.text("ALTER TABLE business_flow DROP COLUMN IF EXISTS revision"))

    # 3. variable_ref FK
    conn.execute(sa.text("ALTER TABLE business_variable_ref DROP COLUMN IF EXISTS source_variable_id"))
    conn.execute(sa.text("ALTER TABLE business_variable_ref DROP COLUMN IF EXISTS target_variable_id"))

    # 2. binding 增强
    inspector = inspect(conn)
    idx_names = [i["name"] for i in inspector.get_indexes("business_binding")]
    if "ix_business_binding_action_default" in idx_names:
        conn.execute(sa.text("DROP INDEX IF EXISTS ix_business_binding_action_default"))
    conn.execute(sa.text("ALTER TABLE business_binding DROP COLUMN IF EXISTS name"))
    conn.execute(sa.text("ALTER TABLE business_binding DROP COLUMN IF EXISTS is_default"))
    conn.execute(sa.text("ALTER TABLE business_binding DROP COLUMN IF EXISTS sort"))

    # 0004 建的 (action_id, binding_type) 唯一约束由本迁移移除，回退必须补回，
    # 否则降级后 binding 表就完全没有唯一性约束了。
    uq_names = [c["name"] for c in inspector.get_unique_constraints("business_binding")]
    if "uq_business_binding_action_type" not in uq_names:
        # 0005 允许同一 action + binding_type 挂多条绑定，直接补建约束会因重复行
        # 冲突而失败；先删掉每组多余的行（保留 id 最小的一条）再建。
        conn.execute(sa.text(
            "DELETE FROM business_binding WHERE id NOT IN ("
            "SELECT MIN(id) FROM business_binding GROUP BY action_id, binding_type)"
        ))
        conn.execute(sa.text(
            "ALTER TABLE business_binding ADD CONSTRAINT uq_business_binding_action_type "
            "UNIQUE (action_id, binding_type)"
        ))

    # 1. action_type 默认值回退
    conn.execute(sa.text("UPDATE business_action SET action_type = 'API' WHERE action_type = 'NORMAL'"))
    op.alter_column(
        "business_action", "action_type",
        server_default=sa.text("'API'"),
    )
