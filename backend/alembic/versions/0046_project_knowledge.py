"""Project knowledge and safe retirement of private model configuration."""
from alembic import op
import sqlalchemy as sa
revision = '0046'
down_revision = '0045'
branch_labels = None
depends_on = None


def upgrade():
    op.create_table('knowledge_base', sa.Column('id', sa.Integer, primary_key=True), sa.Column('project_id', sa.Integer, sa.ForeignKey('project.id'), nullable=False), sa.Column('name', sa.String(160), nullable=False), sa.Column('enabled', sa.Boolean, nullable=False))
    op.create_table('knowledge_document', sa.Column('id', sa.Integer, primary_key=True), sa.Column('project_id', sa.Integer, sa.ForeignKey('project.id'), nullable=False), sa.Column('base_id', sa.Integer, sa.ForeignKey('knowledge_base.id'), nullable=False), sa.Column('name', sa.String(255), nullable=False), sa.Column('category', sa.String(100), nullable=False), sa.Column('enabled', sa.Boolean, nullable=False), sa.Column('current_version_id', sa.Integer))
    op.create_table('knowledge_document_version', sa.Column('id', sa.Integer, primary_key=True), sa.Column('document_id', sa.Integer, sa.ForeignKey('knowledge_document.id'), nullable=False), sa.Column('version', sa.Integer, nullable=False), sa.Column('digest', sa.String(64), nullable=False), sa.Column('filename', sa.String(255), nullable=False), sa.Column('content', sa.LargeBinary, nullable=False), sa.Column('status', sa.String(20), nullable=False), sa.Column('error', sa.String(500)), sa.Column('attempts', sa.Integer, nullable=False), sa.UniqueConstraint('document_id', 'version'))
    op.create_table('knowledge_chunk', sa.Column('id', sa.Integer, primary_key=True), sa.Column('version_id', sa.Integer, sa.ForeignKey('knowledge_document_version.id'), nullable=False), sa.Column('position', sa.Integer, nullable=False), sa.Column('page', sa.Integer), sa.Column('text', sa.Text, nullable=False))
    op.create_table('project_agent_knowledge_binding', sa.Column('id', sa.Integer, primary_key=True), sa.Column('project_id', sa.Integer, sa.ForeignKey('project.id'), nullable=False), sa.Column('agent_id', sa.Integer, sa.ForeignKey('agent_definition.id'), nullable=False), sa.Column('enabled', sa.Boolean, nullable=False), sa.Column('required', sa.Boolean, nullable=False), sa.Column('revision', sa.Integer, nullable=False), sa.Column('scopes', sa.JSON, nullable=False), sa.UniqueConstraint('project_id', 'agent_id'))
    for table, column in [('knowledge_base','project_id'), ('knowledge_document','project_id'), ('knowledge_document_version','document_id'), ('knowledge_chunk','version_id'), ('project_agent_knowledge_binding','project_id')]:
        op.create_index(f'ix_{table}_{column}', table, [column])
    # Audit contains identifiers and state only. Credentials and historical references stay in place.
    op.create_table('model_global_migration_audit', sa.Column('resource_id', sa.Integer, primary_key=True), sa.Column('project_id', sa.Integer), sa.Column('previous_status', sa.String(20)), sa.Column('replacement_resource_id', sa.Integer), sa.Column('decision', sa.String(40), nullable=False))
    op.execute("INSERT INTO model_global_migration_audit (resource_id, project_id, previous_status, decision) SELECT id, project_id, status, 'DISABLED_PENDING_ADMIN_REVIEW' FROM model_resource WHERE visibility = 'PROJECT'")
    op.execute("UPDATE model_resource SET status = 'DISABLED' WHERE visibility = 'PROJECT'")
    op.execute("UPDATE model_revision SET enabled = false WHERE resource_id IN (SELECT id FROM model_resource WHERE visibility = 'PROJECT')")


def downgrade():
    # Deliberately do not reactivate retired credentials during rollback.
    for table in ['model_global_migration_audit', 'project_agent_knowledge_binding', 'knowledge_chunk', 'knowledge_document_version', 'knowledge_document', 'knowledge_base']:
        op.drop_table(table)
