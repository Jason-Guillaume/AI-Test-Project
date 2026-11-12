"""0051 联合验收：执行根隔离、旧批次回填和降级不损失生成数据。"""
import os
import psycopg
import pytest
from alembic import command
from alembic.config import Config
from tests.test_50_migration_0049 import scratch, _upgrade, _url, BACKEND_DIR


def test_0051_root_backfill_isolation_and_downgrade(scratch, test_database_head):
    """旧生成分支回填到协调根，跨 Task 根引用被拒，Trace 不伪造。"""
    _upgrade(scratch, '0050')
    plain = _url(scratch).replace('+psycopg', '')
    with psycopg.connect(plain, autocommit=True) as conn:
        conn.execute('INSERT INTO "user" (username, hashed_password) VALUES (\'identity-test\', \'x\')')
        conn.execute("INSERT INTO organization (name,owner_id) VALUES ('identity-org',1)")
        conn.execute("INSERT INTO project (name,organization_id,owner_id) VALUES ('identity-project',1,1)")
        conn.execute("INSERT INTO task (project_id,title,goal,task_mode) VALUES (1,'生成','需求','CASE_GENERATION'),(1,'其他任务','需求','TEST_EXECUTION')")
        conn.execute("INSERT INTO task_run (task_id,run_number,goal_snapshot) VALUES (1,1,'模块'),(1,2,'协调'),(2,1,'另一个Task')")
        conn.execute("""INSERT INTO case_generation_batch (project_id,direction,supervisor_version,supervisor_name,requirements,
            modules_json,status,review_gaps_json,module_errors_json,task_run_id)
            VALUES (1,'API',1,'主Agent','需求','["api"]','COMPLETED','[]','[]',2)""")
    _upgrade(scratch, test_database_head)
    with psycopg.connect(plain, autocommit=True) as conn:
        assert conn.execute('SELECT execution_root_run_id,trace_id,deadline_at FROM task_run WHERE task_id=1 ORDER BY id').fetchall() == [(2,None,None),(2,None,None)]
        assert conn.execute('SELECT execution_root_run_id FROM task_run WHERE task_id=2').fetchone() == (None,)
        with pytest.raises(psycopg.errors.ForeignKeyViolation):
            conn.execute('UPDATE task_run SET execution_root_run_id=2 WHERE task_id=2')
        conn.execute("UPDATE task_run SET trace_id=repeat('a',32),deadline_at=now() WHERE id=2")
        columns = {row[0] for row in conn.execute("SELECT column_name FROM information_schema.columns WHERE table_name='task_agent_instance'")}
        assert {'agent_definition_revision_id','parent_agent_instance_id'} <= columns
        assert conn.execute("SELECT count(*) FROM information_schema.columns WHERE table_name='task_attempt' AND column_name='deadline_at'").fetchone() == (1,)
    previous = os.environ.get('DATABASE_URL')
    os.environ['DATABASE_URL'] = _url(scratch)
    try:
        config = Config(str(BACKEND_DIR / 'alembic.ini'))
        config.set_main_option('script_location', str(BACKEND_DIR / 'alembic'))
        command.downgrade(config, '0050')
    finally:
        if previous is None:
            os.environ.pop('DATABASE_URL', None)
        else:
            os.environ['DATABASE_URL'] = previous
    with psycopg.connect(plain) as conn:
        assert conn.execute('SELECT task_run_id,status FROM case_generation_batch').fetchone() == (2,'COMPLETED')
        assert conn.execute('SELECT count(*) FROM task_run').fetchone() == (3,)
