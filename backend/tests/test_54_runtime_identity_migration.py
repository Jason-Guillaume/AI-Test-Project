"""0051 增量迁移验收：历史分组有据回填，不伪造 Trace，回退不删除任务。"""
import os
import psycopg
from alembic import command
from alembic.config import Config
from tests.test_50_migration_0049 import scratch, _upgrade, _url, BACKEND_DIR


def test_0050_data_survives_runtime_identity_upgrade_and_downgrade(scratch):
    """从旧批次关联推导根，普通运行与历史 Trace 保持空值，回退保留全部业务行。"""
    _upgrade(scratch, '0050')
    plain = _url(scratch).replace('+psycopg', '')
    with psycopg.connect(plain, autocommit=True) as conn:
        conn.execute('INSERT INTO "user" (username, hashed_password) VALUES (\'runtime-migration\', \'x\')')
        conn.execute("INSERT INTO organization (name,owner_id) VALUES ('runtime-org',1)")
        conn.execute("INSERT INTO project (name,organization_id,owner_id) VALUES ('runtime-project',1,1)")
        conn.execute("INSERT INTO task (project_id,title,goal) VALUES (1,'生成','需求'),(1,'普通','需求')")
        conn.execute("INSERT INTO task_run (task_id,run_number,goal_snapshot) VALUES (1,1,'子'),(1,2,'协调'),(2,1,'普通')")
        conn.execute("""INSERT INTO case_generation_batch (project_id,direction,supervisor_version,supervisor_name,
            requirements,modules_json,status,review_gaps_json,module_errors_json,task_run_id)
            VALUES (1,'API',1,'主Agent','需求','["api"]','QUEUED','[]','[]',2)""")
    _upgrade(scratch, '0051')
    with psycopg.connect(plain) as conn:
        assert conn.execute('SELECT id,execution_root_run_id,trace_id,deadline_at FROM task_run ORDER BY id').fetchall() == [
            (1,2,None,None),(2,2,None,None),(3,None,None,None)]
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
        assert conn.execute('SELECT count(*) FROM task_run').fetchone() == (3,)
        assert conn.execute('SELECT task_run_id FROM case_generation_batch').fetchone() == (2,)
