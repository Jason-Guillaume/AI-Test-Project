"""Store canonical task creation request digests for safe retries."""
from alembic import op
import sqlalchemy as sa


revision = "0031"
down_revision = "0030"
branch_labels = None
depends_on = None


def upgrade():
    op.add_column("task", sa.Column("request_digest", sa.String(length=64), nullable=True))


def downgrade():
    op.drop_column("task", "request_digest")
