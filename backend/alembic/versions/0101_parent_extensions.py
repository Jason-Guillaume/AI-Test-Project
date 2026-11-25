"""Store optional session summaries, web case configuration and project settings on their owner."""
from alembic_support.fold_0100 import Extension

revision = "0101"
down_revision = "0100"
branch_labels = None
depends_on = None

EXTENSIONS = (
    Extension("agent_session_summary", "agent_session", "session_id", {
        "summary_version": "summary_version", "summary_kind": "summary_kind", "summary_text": "summary_text",
        "source_refs": "summary_source_refs", "source_digest": "summary_source_digest",
        "source_through_message_id": "summary_source_through_message_id", "expires_at": "summary_expires_at",
        "created_at": "summary_created_at", "updated_at": "summary_updated_at",
    }, "summary_version"),
    Extension("web_case", "test_case", "test_case_id", {
        "auth_profile_id": "web_auth_profile_id", "timeout_ms": "web_timeout_ms",
        "total_timeout_ms": "web_total_timeout_ms", "confirmed_digest": "web_confirmed_digest",
        "confirmed_by": "web_confirmed_by",
    }, "timeout_ms"),
    Extension("security_project_setting", "project", "project_id", {
        "id": "security_setting_id", "allow_dev": "security_allow_dev", "allow_test": "security_allow_test",
        "allow_staging": "security_allow_staging", "allow_production": "security_allow_production",
        "updated_by": "security_updated_by", "created_at": "security_created_at",
        "updated_at": "security_updated_at", "revision": "security_revision",
    }, "id"),
)


def upgrade() -> None:
    for extension in EXTENSIONS:
        extension.fold()


def downgrade() -> None:
    for extension in reversed(EXTENSIONS):
        extension.unfold()
