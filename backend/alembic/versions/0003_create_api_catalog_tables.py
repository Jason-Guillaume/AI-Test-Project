"""新增接口管理 8 张表（api_catalog feature-local）。

Revision ID: 0003
Revises: 0002
Create Date: 2026-10-12

延续 0002 风格：显式 op.create_table（0001 之后的表不能再用 create_all），
幂等保护（inspect 检查表存在性，索引用 IF NOT EXISTS）。
seed_admin.py 每次 stamp base + upgrade head 会重放整条迁移链，因此本迁移必须可重复执行。
模型**不**加入 app/models/__init__.py（feature-local），与 Bug 同款。

建表顺序遵循外键依赖：api_module → api_interface → 其余子表。
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op
from sqlalchemy.sql import func, text


revision = "0003"
down_revision = "0002"
branch_labels = None
depends_on = None


# 表创建顺序（遵循外键依赖）。
_TABLES_IN_ORDER = [
    "api_module",
    "api_interface",
    "api_request_body",
    "api_parameter",
    "api_response",
    "api_relation",
    "api_import_record",
    "api_change_log",
]


def _table_definitions() -> dict[str, list]:
    """每张表的列与约束定义（与 ORM 模型逐列对齐）。"""
    return {
        "api_module": [
            sa.Column("id", sa.Integer(), autoincrement=True, nullable=False),
            sa.Column("project_id", sa.Integer(), nullable=False),
            sa.Column("name", sa.String(length=100), nullable=False),
            sa.Column("parent_id", sa.Integer(), nullable=True),
            sa.Column("sort", sa.Integer(), server_default=text("0"), nullable=False),
            sa.Column("is_default", sa.Boolean(), server_default=text("false"), nullable=False),
            sa.Column("created_at", sa.DateTime(), server_default=func.now(), nullable=False),
            sa.Column("updated_at", sa.DateTime(), server_default=func.now(), nullable=False),
            sa.ForeignKeyConstraint(["project_id"], ["project.id"], ondelete="CASCADE"),
            sa.ForeignKeyConstraint(["parent_id"], ["api_module.id"], ondelete="CASCADE"),
            sa.PrimaryKeyConstraint("id", name="pk_api_module"),
            sa.UniqueConstraint("project_id", "name", name="uq_api_module_project_name"),
        ],
        "api_interface": [
            sa.Column("id", sa.Integer(), autoincrement=True, nullable=False),
            sa.Column("project_id", sa.Integer(), nullable=False),
            sa.Column("module_id", sa.Integer(), nullable=True),
            sa.Column("name", sa.String(length=200), nullable=False),
            sa.Column("description", sa.String(length=1000), nullable=True),
            sa.Column("method", sa.String(length=10), nullable=False),
            sa.Column("path", sa.String(length=500), nullable=False),
            sa.Column("auth_type", sa.String(length=30), server_default=text("'none'"), nullable=False),
            sa.Column("content_type", sa.String(length=100), server_default=text("'application/json'"), nullable=False),
            sa.Column("status", sa.String(length=20), server_default=text("'DRAFT'"), nullable=False),
            sa.Column("source_type", sa.String(length=20), server_default=text("'MANUAL'"), nullable=False),
            sa.Column("version", sa.Integer(), server_default=text("1"), nullable=False),
            sa.Column("source_hash", sa.String(length=64), nullable=True),
            sa.Column("created_at", sa.DateTime(), server_default=func.now(), nullable=False),
            sa.Column("updated_at", sa.DateTime(), server_default=func.now(), nullable=False),
            sa.ForeignKeyConstraint(["project_id"], ["project.id"], ondelete="CASCADE"),
            sa.ForeignKeyConstraint(["module_id"], ["api_module.id"], ondelete="SET NULL"),
            sa.PrimaryKeyConstraint("id", name="pk_api_interface"),
            sa.UniqueConstraint("project_id", "method", "path", name="uq_api_interface_project_method_path"),
        ],
        "api_request_body": [
            sa.Column("id", sa.Integer(), autoincrement=True, nullable=False),
            sa.Column("interface_id", sa.Integer(), nullable=False),
            sa.Column("body_type", sa.String(length=20), server_default=text("'none'"), nullable=False),
            sa.Column("content_type", sa.String(length=100), nullable=True),
            sa.Column("schema_json", sa.JSON(), nullable=True),
            sa.Column("raw_text", sa.Text(), nullable=True),
            sa.Column("created_at", sa.DateTime(), server_default=func.now(), nullable=False),
            sa.Column("updated_at", sa.DateTime(), server_default=func.now(), nullable=False),
            sa.ForeignKeyConstraint(["interface_id"], ["api_interface.id"], ondelete="CASCADE"),
            sa.PrimaryKeyConstraint("id", name="pk_api_request_body"),
            sa.UniqueConstraint("interface_id", name="uq_api_request_body_interface"),
        ],
        "api_parameter": [
            sa.Column("id", sa.Integer(), autoincrement=True, nullable=False),
            sa.Column("interface_id", sa.Integer(), nullable=False),
            sa.Column("name", sa.String(length=100), nullable=False),
            sa.Column("location", sa.String(length=10), nullable=False),
            sa.Column("type", sa.String(length=30), server_default=text("'string'"), nullable=False),
            sa.Column("required", sa.Boolean(), server_default=text("false"), nullable=False),
            sa.Column("description", sa.String(length=500), nullable=True),
            sa.Column("example", sa.Text(), nullable=True),
            sa.Column("default_value", sa.Text(), nullable=True),
            sa.Column("schema_json", sa.JSON(), nullable=True),
            sa.Column("sort", sa.Integer(), server_default=text("0"), nullable=False),
            sa.Column("created_at", sa.DateTime(), server_default=func.now(), nullable=False),
            sa.ForeignKeyConstraint(["interface_id"], ["api_interface.id"], ondelete="CASCADE"),
            sa.PrimaryKeyConstraint("id", name="pk_api_parameter"),
        ],
        "api_response": [
            sa.Column("id", sa.Integer(), autoincrement=True, nullable=False),
            sa.Column("interface_id", sa.Integer(), nullable=False),
            sa.Column("status_code", sa.Integer(), nullable=False),
            sa.Column("description", sa.String(length=500), nullable=True),
            sa.Column("schema_json", sa.JSON(), nullable=True),
            sa.Column("example_json", sa.Text(), nullable=True),
            sa.Column("sort", sa.Integer(), server_default=text("0"), nullable=False),
            sa.Column("created_at", sa.DateTime(), server_default=func.now(), nullable=False),
            sa.Column("updated_at", sa.DateTime(), server_default=func.now(), nullable=False),
            sa.ForeignKeyConstraint(["interface_id"], ["api_interface.id"], ondelete="CASCADE"),
            sa.PrimaryKeyConstraint("id", name="pk_api_response"),
        ],
        "api_relation": [
            sa.Column("id", sa.Integer(), autoincrement=True, nullable=False),
            sa.Column("project_id", sa.Integer(), nullable=False),
            sa.Column("source_api_id", sa.Integer(), nullable=False),
            sa.Column("target_api_id", sa.Integer(), nullable=False),
            sa.Column("relation_type", sa.String(length=20), nullable=False),
            sa.Column("variable_name", sa.String(length=100), nullable=True),
            sa.Column("extract_path", sa.String(length=500), nullable=True),
            sa.Column("created_at", sa.DateTime(), server_default=func.now(), nullable=False),
            sa.ForeignKeyConstraint(["project_id"], ["project.id"], ondelete="CASCADE"),
            sa.ForeignKeyConstraint(["source_api_id"], ["api_interface.id"], ondelete="CASCADE"),
            sa.ForeignKeyConstraint(["target_api_id"], ["api_interface.id"], ondelete="CASCADE"),
            sa.PrimaryKeyConstraint("id", name="pk_api_relation"),
            sa.UniqueConstraint(
                "source_api_id", "target_api_id", "relation_type", "variable_name",
                name="uq_api_relation_src_tgt_type_var",
            ),
        ],
        "api_import_record": [
            sa.Column("id", sa.Integer(), autoincrement=True, nullable=False),
            sa.Column("project_id", sa.Integer(), nullable=False),
            sa.Column("source_type", sa.String(length=20), nullable=False),
            sa.Column("file_name", sa.String(length=300), nullable=True),
            sa.Column("source_hash", sa.String(length=64), nullable=True),
            sa.Column("total", sa.Integer(), server_default=text("0"), nullable=False),
            sa.Column("created_count", sa.Integer(), server_default=text("0"), nullable=False),
            sa.Column("updated_count", sa.Integer(), server_default=text("0"), nullable=False),
            sa.Column("skipped_count", sa.Integer(), server_default=text("0"), nullable=False),
            sa.Column("created_by", sa.Integer(), nullable=True),
            sa.Column("created_at", sa.DateTime(), server_default=func.now(), nullable=False),
            sa.ForeignKeyConstraint(["project_id"], ["project.id"], ondelete="CASCADE"),
            sa.ForeignKeyConstraint(["created_by"], ["user.id"], ondelete="SET NULL"),
            sa.PrimaryKeyConstraint("id", name="pk_api_import_record"),
        ],
        "api_change_log": [
            sa.Column("id", sa.Integer(), autoincrement=True, nullable=False),
            sa.Column("interface_id", sa.Integer(), nullable=False),
            sa.Column("change_type", sa.String(length=30), nullable=False),
            sa.Column("diff_json", sa.JSON(), nullable=True),
            sa.Column("source_hash_before", sa.String(length=64), nullable=True),
            sa.Column("source_hash_after", sa.String(length=64), nullable=True),
            sa.Column("summary", sa.Text(), nullable=True),
            sa.Column("created_by", sa.Integer(), nullable=True),
            sa.Column("created_at", sa.DateTime(), server_default=func.now(), nullable=False),
            sa.ForeignKeyConstraint(["interface_id"], ["api_interface.id"], ondelete="CASCADE"),
            sa.ForeignKeyConstraint(["created_by"], ["user.id"], ondelete="SET NULL"),
            sa.PrimaryKeyConstraint("id", name="pk_api_change_log"),
        ],
    }


# 每张表的非唯一索引（与 ORM index=True / __table_args__ Index 一一对应）。
_INDEX_DEFINITIONS: dict[str, list[tuple[str, list[str]]]] = {
    "api_module": [
        ("ix_api_module_id", ["id"]),
        ("ix_api_module_project_id", ["project_id"]),
        ("ix_api_module_project_parent", ["project_id", "parent_id"]),
    ],
    "api_interface": [
        ("ix_api_interface_id", ["id"]),
        ("ix_api_interface_project_id", ["project_id"]),
        ("ix_api_interface_module_id", ["module_id"]),
        ("ix_api_interface_method", ["method"]),
        ("ix_api_interface_status", ["status"]),
        ("ix_api_interface_project_module", ["project_id", "module_id"]),
        ("ix_api_interface_source_hash", ["source_hash"]),
    ],
    "api_request_body": [
        ("ix_api_request_body_id", ["id"]),
    ],
    "api_parameter": [
        ("ix_api_parameter_id", ["id"]),
        ("ix_api_parameter_interface_id", ["interface_id"]),
        ("ix_api_parameter_interface_location", ["interface_id", "location"]),
    ],
    "api_response": [
        ("ix_api_response_id", ["id"]),
        ("ix_api_response_interface_id", ["interface_id"]),
        ("ix_api_response_interface_status", ["interface_id", "status_code"]),
    ],
    "api_relation": [
        ("ix_api_relation_id", ["id"]),
        ("ix_api_relation_project", ["project_id"]),
        ("ix_api_relation_source", ["source_api_id"]),
    ],
    "api_import_record": [
        ("ix_api_import_record_id", ["id"]),
        ("ix_api_import_record_project_id", ["project_id"]),
        ("ix_api_import_record_source_hash", ["source_hash"]),
        ("ix_api_import_record_created_by", ["created_by"]),
        ("ix_api_import_record_project_created", ["project_id", "created_at"]),
    ],
    "api_change_log": [
        ("ix_api_change_log_id", ["id"]),
        ("ix_api_change_log_interface_id", ["interface_id"]),
        ("ix_api_change_log_created_by", ["created_by"]),
        ("ix_api_change_log_interface_created", ["interface_id", "created_at"]),
    ],
}

# 表注释（与 ORM __table_args__ comment 对齐）。
_TABLE_COMMENTS: dict[str, str] = {
    "api_module": "接口模块（最多两级，含项目级未分类默认模块）",
    "api_interface": "接口定义（去重键：project_id + method + path）",
    "api_request_body": "接口请求体（json/form/multipart/raw）",
    "api_parameter": "接口请求参数（PATH/QUERY/HEADER/COOKIE/BODY）",
    "api_response": "接口响应（按 HTTP status_code 保存结构）",
    "api_relation": "接口关联（PRECONDITION/OUTPUT_INPUT/FOLLOW_UP）",
    "api_import_record": "接口导入批次记录",
    "api_change_log": "接口变更记录",
}


def upgrade() -> None:
    """正向迁移：建 8 张表 + 索引（幂等）。"""
    from sqlalchemy import inspect

    bind = op.get_bind()
    inspector = inspect(bind)
    existing_tables = set(inspector.get_table_names())
    definitions = _table_definitions()

    for table in _TABLES_IN_ORDER:
        if table in existing_tables:
            continue
        op.create_table(
            table,
            *definitions[table],
            comment=_TABLE_COMMENTS.get(table),
        )

    # 索引：逐表 IF NOT EXISTS 补齐，允许在已建索引的库上安全重放。
    for table in _TABLES_IN_ORDER:
        if table not in inspect(bind).get_table_names():
            continue
        existing_indexes = {idx["name"] for idx in inspector.get_indexes(table)}
        for name, columns in _INDEX_DEFINITIONS.get(table, []):
            if name in existing_indexes:
                continue
            columns_sql = ", ".join(f'"{c}"' for c in columns)
            bind.execute(
                text(f"CREATE INDEX IF NOT EXISTS {name} ON {table} ({columns_sql})")
            )


def downgrade() -> None:
    """反向迁移：删 8 张表及其索引（全 IF EXISTS，可安全重放）。"""
    bind = op.get_bind()
    # 先删索引（含唯一约束产生的索引）再删表；按外键依赖逆序删表。
    for table in reversed(_TABLES_IN_ORDER):
        for name, _columns in _INDEX_DEFINITIONS.get(table, []):
            bind.execute(text(f"DROP INDEX IF EXISTS {name}"))
        bind.execute(text(f"DROP TABLE IF EXISTS {table}"))
