"""扩展 Agent 详情、Skill 文件和工具治理配置。"""
from alembic import op
import sqlalchemy as sa


revision = "0029"
down_revision = "0028"
branch_labels = None
depends_on = None


def upgrade():
    op.add_column("agent_definition", sa.Column("settings_json", sa.JSON(), nullable=False, server_default=sa.text("'{}'")))
    op.add_column("agent_definition", sa.Column("triggers_json", sa.JSON(), nullable=False, server_default=sa.text("'[]'")))
    op.execute("""
        UPDATE agent_definition SET settings_json = json_build_object(
            'model_binding', CASE WHEN model_config_id IS NULL THEN 'task_or_global' ELSE 'agent' END,
            'max_loop_count', 0,
            'timeout_seconds', 1200,
            'network_search_enabled', false,
            'interactive_shell_enabled', false,
            'close_step_prompt', '',
            'close_step_max_loops', 0,
            'close_task_timeout_prompt', '',
            'close_task_timeout_max_loops', 0,
            'runtime_variables', json_build_array(
                json_build_object('name', 'Now', 'value', '{{.Now}}'),
                json_build_object('name', 'DataDir', 'value', '{{.DataDir}}')
            )
        ) WHERE settings_json::text = '{}'
    """)
    op.add_column("skill_definition", sa.Column("files_json", sa.JSON(), nullable=False, server_default=sa.text("'{}'")))
    op.add_column("skill_definition", sa.Column("mcp_tool_keys_json", sa.JSON(), nullable=False, server_default=sa.text("'[]'")))
    op.execute("UPDATE skill_definition SET files_json = json_build_object('SKILL.md', content) WHERE files_json::text = '{}'")
    op.create_table(
        "agent_tool_definition_override",
        sa.Column("tool_key", sa.String(length=120), primary_key=True),
        sa.Column("description", sa.Text(), nullable=False, server_default=""),
        sa.Column("parameter_overrides_json", sa.JSON(), nullable=False, server_default=sa.text("'{}'")),
        sa.Column("is_enabled", sa.Boolean(), nullable=False, server_default=sa.true()),
        sa.Column("updated_by", sa.Integer(), sa.ForeignKey("user.id", ondelete="SET NULL"), nullable=True),
        sa.Column("updated_at", sa.DateTime(), nullable=False, server_default=sa.func.now()),
    )
    op.create_table(
        "agent_skill_usage_event",
        sa.Column("id", sa.Integer(), primary_key=True, autoincrement=True),
        sa.Column("skill_definition_id", sa.Integer(), sa.ForeignKey("skill_definition.id", ondelete="CASCADE"), nullable=False),
        sa.Column("agent_definition_id", sa.Integer(), sa.ForeignKey("agent_definition.id", ondelete="SET NULL"), nullable=True),
        sa.Column("task_run_id", sa.Integer(), sa.ForeignKey("task_run.id", ondelete="CASCADE"), nullable=False),
        sa.Column("created_at", sa.DateTime(), nullable=False, server_default=sa.func.now()),
    )
    op.create_index("ix_agent_skill_usage_event_skill_definition_id", "agent_skill_usage_event", ["skill_definition_id"])
    op.create_index("ix_agent_skill_usage_event_agent_definition_id", "agent_skill_usage_event", ["agent_definition_id"])
    op.create_index("ix_agent_skill_usage_event_task_run_id", "agent_skill_usage_event", ["task_run_id"])


def downgrade():
    op.drop_index("ix_agent_skill_usage_event_task_run_id", table_name="agent_skill_usage_event")
    op.drop_index("ix_agent_skill_usage_event_agent_definition_id", table_name="agent_skill_usage_event")
    op.drop_index("ix_agent_skill_usage_event_skill_definition_id", table_name="agent_skill_usage_event")
    op.drop_table("agent_skill_usage_event")
    op.drop_table("agent_tool_definition_override")
    op.drop_column("skill_definition", "mcp_tool_keys_json")
    op.drop_column("skill_definition", "files_json")
    op.drop_column("agent_definition", "triggers_json")
    op.drop_column("agent_definition", "settings_json")
