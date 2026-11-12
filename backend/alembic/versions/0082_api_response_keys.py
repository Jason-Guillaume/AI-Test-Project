"""Preserve exact, range, and default OpenAPI response keys."""

from alembic import op
import sqlalchemy as sa


revision = "0082"
down_revision = "0081"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("api_response", sa.Column("response_key", sa.String(length=16), nullable=True))
    op.execute("UPDATE api_response SET response_key = CAST(status_code AS VARCHAR(16))")
    op.alter_column("api_response", "response_key", nullable=False)
    op.alter_column("api_response", "status_code", existing_type=sa.Integer(), nullable=True)


def downgrade() -> None:
    # Range/default keys cannot be represented by the old integer-only schema.
    op.execute("UPDATE api_response SET status_code = 200 WHERE status_code IS NULL")
    op.alter_column("api_response", "status_code", existing_type=sa.Integer(), nullable=False)
    op.drop_column("api_response", "response_key")
