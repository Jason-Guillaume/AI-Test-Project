"""Persist execution request identity.

Revision ID: 0096
Revises: 0095
"""
from alembic import op
import sqlalchemy as sa

revision = "0096"
down_revision = "0095"
branch_labels = None
depends_on = None

def upgrade():
    op.add_column("test_run", sa.Column("request_key", sa.String(80), nullable=True))
    op.add_column("test_run", sa.Column("request_environment_id", sa.Integer(), nullable=True))
    op.create_index("uq_test_run_request_key", "test_run", ["request_key"], unique=True)

def downgrade():
    op.drop_index("uq_test_run_request_key", table_name="test_run")
    op.drop_column("test_run", "request_environment_id")
    op.drop_column("test_run", "request_key")
