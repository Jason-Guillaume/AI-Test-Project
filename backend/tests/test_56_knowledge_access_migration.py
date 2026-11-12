"""0052-0056 知识范围、运行事实及子 Agent 恢复检查点迁移验收。"""

import psycopg

from tests.test_50_migration_0049 import _upgrade, _url, scratch


def test_0052_0056_runtime_schema_is_compatible_and_reversible(scratch, test_database_head):
    """知识绑定沿用共享默认，运行事实保留关联，Agent 检查点可安全降级。"""
    _upgrade(scratch, "0051")
    _upgrade(scratch, test_database_head)
    plain = _url(scratch).replace("+psycopg", "")
    with psycopg.connect(plain) as conn:
        default = conn.execute(
            """SELECT column_default FROM information_schema.columns
               WHERE table_name = 'project_agent_knowledge_binding' AND column_name = 'access_mode'"""
        ).fetchone()
    assert default and "PROJECT_SHARED" in default[0]
    with psycopg.connect(plain) as conn:
        call_fact_columns = {row[0] for row in conn.execute(
            "SELECT column_name FROM information_schema.columns WHERE table_name = 'runtime_call_fact'"
        )}
    assert {"call_id", "task_run_id", "execution_root_run_id", "attempt_id", "trace_id",
            "agent_session_id", "model_config_id", "input_tokens", "output_tokens", "cost_amount"} <= call_fact_columns
    with psycopg.connect(plain) as conn:
        call_indexes = {row[0] for row in conn.execute(
            "SELECT indexname FROM pg_indexes WHERE tablename = 'runtime_call_fact'"
        )}
    assert "ix_runtime_call_fact_root" in call_indexes
    with psycopg.connect(plain) as conn:
        event_columns = {row[0] for row in conn.execute(
            "SELECT column_name FROM information_schema.columns WHERE table_name = 'runtime_event_fact'"
        )}
    assert {"event_id", "task_run_id", "execution_root_run_id", "attempt_id", "agent_session_id",
            "trace_id", "event_type", "duration_ms", "event_metadata"} <= event_columns
    with psycopg.connect(plain) as conn:
        event_indexes = {row[0] for row in conn.execute(
            "SELECT indexname FROM pg_indexes WHERE tablename = 'runtime_event_fact'"
        )}
    assert "ix_runtime_event_fact_root_time" in event_indexes
    with psycopg.connect(plain) as conn:
        instance_columns = {row[0] for row in conn.execute(
            "SELECT column_name FROM information_schema.columns WHERE table_name = 'task_agent_instance'"
        )}
    assert "result_json" in instance_columns

    import os
    from alembic import command
    from alembic.config import Config
    from tests.test_50_migration_0049 import BACKEND_DIR

    previous = os.environ.get("DATABASE_URL")
    os.environ["DATABASE_URL"] = _url(scratch)
    try:
        config = Config(str(BACKEND_DIR / "alembic.ini"))
        config.set_main_option("script_location", str(BACKEND_DIR / "alembic"))
        command.downgrade(config, "0051")
    finally:
        if previous is None:
            os.environ.pop("DATABASE_URL", None)
        else:
            os.environ["DATABASE_URL"] = previous
    with psycopg.connect(plain) as conn:
        columns = {row[0] for row in conn.execute(
            """SELECT column_name FROM information_schema.columns
               WHERE table_name = 'project_agent_knowledge_binding'"""
        )}
    assert "access_mode" not in columns
    with psycopg.connect(plain) as conn:
        tables = {row[0] for row in conn.execute(
            "SELECT table_name FROM information_schema.tables WHERE table_schema = 'public'"
        )}
    assert "runtime_call_fact" not in tables
    assert "runtime_event_fact" not in tables
    with psycopg.connect(plain) as conn:
        instance_columns = {row[0] for row in conn.execute(
            "SELECT column_name FROM information_schema.columns WHERE table_name = 'task_agent_instance'"
        )}
    assert "result_json" not in instance_columns
