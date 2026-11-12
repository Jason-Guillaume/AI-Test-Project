"""为知识与会话内容增加可选 trigram 候选索引。"""

import logging

from alembic import op
from sqlalchemy import text

revision = "0057"
down_revision = "0056"
branch_labels = None
depends_on = None

logger = logging.getLogger(__name__)


def _trigram_extension_installed(connection) -> bool:
    return bool(connection.execute(text(
        "SELECT EXISTS (SELECT 1 FROM pg_extension WHERE extname = 'pg_trgm')",
    )).scalar())


def upgrade():
    """可安装 pg_trgm 时创建在线 GIN 索引；环境不支持时保留 SQL 候选过滤。"""
    context = op.get_context()
    with context.autocommit_block():
        connection = op.get_bind()
        available = bool(connection.execute(text(
            "SELECT EXISTS (SELECT 1 FROM pg_available_extensions WHERE name = 'pg_trgm')",
        )).scalar())
        if available and not _trigram_extension_installed(connection):
            try:
                connection.execute(text("CREATE EXTENSION IF NOT EXISTS pg_trgm"))
            except Exception as exc:  # noqa: BLE001 — 托管 PG 可能禁止安装扩展
                logger.warning("pg_trgm 不可安装，知识检索使用数据库过滤降级：%s", type(exc).__name__)
        if _trigram_extension_installed(connection):
            connection.execute(text(
                "CREATE INDEX CONCURRENTLY IF NOT EXISTS ix_knowledge_chunk_text_trgm "
                "ON knowledge_chunk USING gin (text gin_trgm_ops)",
            ))
            connection.execute(text(
                "CREATE INDEX CONCURRENTLY IF NOT EXISTS ix_agent_message_content_trgm "
                "ON agent_message USING gin (content gin_trgm_ops)",
            ))


def downgrade():
    """移除本迁移建立的内容索引，不卸载可能被其他功能使用的 pg_trgm。"""
    with op.get_context().autocommit_block():
        connection = op.get_bind()
        connection.execute(text("DROP INDEX CONCURRENTLY IF EXISTS ix_agent_message_content_trgm"))
        connection.execute(text("DROP INDEX CONCURRENTLY IF EXISTS ix_knowledge_chunk_text_trgm"))
