"""Separate agent test type from its purpose without changing workflow keys."""
from alembic import op
import sqlalchemy as sa

revision = '0045'
down_revision = '0044'
branch_labels = None
depends_on = None


def upgrade():
    op.add_column('agent_definition', sa.Column('test_types', sa.JSON(), nullable=False, server_default='["general"]'))
    op.add_column('agent_definition', sa.Column('purpose', sa.String(32), nullable=False, server_default='test_execution'))
    connection = op.get_bind()
    rows = connection.execute(sa.text('SELECT id, workflow_template, tool_keys FROM agent_definition')).mappings()
    workflow_types = {'api_test': 'api', 'web_ui': 'web', 'security': 'security', 'asr_evaluation': 'asr', 'ai_evaluation': 'ai'}
    for row in rows:
        workflow = row['workflow_template']
        tools = row['tool_keys'] or []
        if isinstance(tools, str):
            import json
            tools = json.loads(tools)
        tool_type = next((key.removeprefix('case_generation.generate_') for key in tools if key.startswith('case_generation.generate_')), None)
        types = [tool_type] if tool_type in {'api', 'web', 'security', 'asr', 'ai'} else (['api', 'web', 'security', 'asr', 'ai'] if workflow == 'case_generation' else [workflow_types.get(workflow, 'general')])
        purpose = 'case_generation' if workflow == 'case_generation' else 'test_report' if workflow == 'reporting' else 'quality_evaluation' if workflow in {'asr_evaluation', 'ai_evaluation'} else 'test_execution'
        definition = sa.table('agent_definition', sa.column('id', sa.Integer()), sa.column('test_types', sa.JSON()), sa.column('purpose', sa.String()))
        connection.execute(sa.update(definition).where(definition.c.id == row['id']).values(test_types=types, purpose=purpose))


def downgrade():
    op.drop_column('agent_definition', 'purpose')
    op.drop_column('agent_definition', 'test_types')
