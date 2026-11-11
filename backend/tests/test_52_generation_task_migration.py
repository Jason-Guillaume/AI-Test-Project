"""0050 增量迁移与回退保留旧审核数据，约束保证模块写入幂等。"""
import os
import psycopg
import pytest
from alembic import command
from alembic.config import Config
from tests.test_50_migration_0049 import scratch, _upgrade, _url, BACKEND_DIR


def test_0050_upgrade_and_downgrade_keep_reviewed_drafts(scratch):
    """从 0049 升级并回退，已入库草稿、审计、正式用例状态均保留。"""
    _upgrade(scratch, '0049')
    plain = _url(scratch).replace('+psycopg', '')
    with psycopg.connect(plain, autocommit=True) as conn:
        conn.execute('INSERT INTO "user" (username, hashed_password) VALUES (\'p6-migration\', \'x\')')
        conn.execute("INSERT INTO organization (name, owner_id) VALUES ('p6-org', 1)")
        conn.execute("INSERT INTO project (name, organization_id, owner_id) VALUES ('p6-project', 1, 1)")
        conn.execute("INSERT INTO test_case (project_id, name, status) VALUES (1, '已入库用例', 'DRAFT')")
        conn.execute("""INSERT INTO case_generation_batch (project_id, direction, supervisor_version, supervisor_name, requirements,
            modules_json, status, review_gaps_json, module_errors_json) VALUES (1,'API',1,'主Agent','需求','["api"]','COMPLETED','[]','[]')""")
        conn.execute("""INSERT INTO case_draft (batch_id,module,title,priority,payload_json,original_payload_json,skill_versions_json,status,test_case_id)
            VALUES (1,'api','旧草稿','P1','{}','{}','[]','ACCEPTED',1)""")
        conn.execute("INSERT INTO case_generation_audit (project_id,batch_id,draft_id,action,detail_json) VALUES (1,1,1,'APPROVE','{}')")
    _upgrade(scratch, 'head')
    with psycopg.connect(plain, autocommit=True) as conn:
        assert conn.execute('SELECT task_run_id FROM case_generation_batch').fetchone() == (None,)
        assert conn.execute('SELECT status,work_item_id,result_ordinal FROM case_draft').fetchone() == ('ACCEPTED', None, None)
        constraints = {row[0] for row in conn.execute("SELECT conname FROM pg_constraint WHERE conrelid='case_draft'::regclass")}
        assert 'uq_generation_draft_work_ordinal' in constraints
        conn.execute("INSERT INTO task (project_id,title,goal) VALUES (1,'生成','需求')")
        conn.execute("INSERT INTO task_run (task_id,run_number,goal_snapshot) VALUES (1,1,'需求')")
        conn.execute("INSERT INTO task_work_item (task_run_id,work_key,kind,idempotency_key) VALUES (1,'api','CASE_GENERATE','migration')")
        conn.execute("UPDATE case_draft SET work_item_id=1,result_ordinal=0 WHERE id=1")
        with pytest.raises(psycopg.errors.UniqueViolation):
            conn.execute("""INSERT INTO case_draft (batch_id,module,title,priority,payload_json,original_payload_json,skill_versions_json,work_item_id,result_ordinal)
                VALUES (1,'api','重复模块结果','P1','{}','{}','[]',1,0)""")
    previous = os.environ.get('DATABASE_URL')
    os.environ['DATABASE_URL'] = _url(scratch)
    try:
        config = Config(str(BACKEND_DIR / 'alembic.ini'))
        config.set_main_option('script_location', str(BACKEND_DIR / 'alembic'))
        command.downgrade(config, '0049')
    finally:
        if previous is None:
            os.environ.pop('DATABASE_URL', None)
        else:
            os.environ['DATABASE_URL'] = previous
    with psycopg.connect(plain) as conn:
        assert conn.execute('SELECT status,test_case_id FROM case_draft WHERE id=1').fetchone() == ('ACCEPTED',1)
        assert conn.execute('SELECT status FROM test_case WHERE id=1').fetchone() == ('DRAFT',)
        assert conn.execute('SELECT count(*) FROM case_generation_audit').fetchone() == (1,)
