"""Add expected and actual result fields to bugs.

Revision ID: 0094
Revises: 0093
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op


revision = "0094"
down_revision = "0093"
branch_labels = None
depends_on = None


def upgrade() -> None:
    columns = {item["name"] for item in sa.inspect(op.get_bind()).get_columns("bug")}
    for name, comment in (("expected_result", "预期结果"), ("actual_result", "实际结果")):
        if name not in columns:
            op.add_column("bug", sa.Column(name, sa.Text(), nullable=True, comment=comment))


def downgrade() -> None:
    columns = {item["name"] for item in sa.inspect(op.get_bind()).get_columns("bug")}
    for name in ("actual_result", "expected_result"):
        if name in columns:
            op.drop_column("bug", name)
