import importlib.util
from pathlib import Path
from uuid import uuid4

import pytest
from sqlalchemy import create_engine

from alembic.migration import MigrationContext
from alembic.operations import Operations


def _revision(number):
    files = list((Path(__file__).resolve().parents[1] / "alembic" / "versions").glob(f"{number}_*.py"))
    assert len(files) == 1, f"Expected one ASR migration {number}"
    spec = importlib.util.spec_from_file_location(f"asr_migration_{number}", files[0])
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


@pytest.fixture
def asr_history(db):
    """Build the historical ASR domain in a private namespace for independent connections."""
    source = db.get_bind()
    schema = "asr_migration_" + uuid4().hex
    with source.begin() as conn:
        conn.exec_driver_sql(f"CREATE SCHEMA {schema}")
    engine = create_engine(source.url, connect_args={"options": f"-csearch_path={schema}"})
    try:
        with engine.begin() as conn:
            sql = conn.exec_driver_sql
            for name in ('"user"', "project"):
                sql(f"CREATE TABLE {name} (id integer PRIMARY KEY)")
                sql(f"INSERT INTO {name} VALUES (1)")
            with Operations.context(MigrationContext.configure(conn)):
                _revision("0032").upgrade()
                _revision("0033").upgrade()
                _revision("0039").upgrade()
                sql("INSERT INTO asr_audio(project_id,name,url_ciphertext,url_display) VALUES (1,'audio','x','x')")
                sql("INSERT INTO asr_audio_version(audio_id,version,name,url_ciphertext,url_display) VALUES (1,1,'v','x','x')")
                sql("INSERT INTO asr_connection(project_id,name,role,model_id,endpoint_ciphertext,endpoint_display,config_json) "
                    "VALUES (1,'one','TEST','m','x','x','{}'),(1,'two','TEST','m','x','x','{}')")
                sql("INSERT INTO asr_job(project_id,config_snapshot) VALUES (1,'{}')")
                sql("INSERT INTO asr_model_run(project_id,job_id,audio_id,connection_id,role,idempotency_key,"
                    "execution_ciphertext,request_snapshot,status) VALUES (1,1,1,1,'TEST','one','x','{}','PENDING'),"
                    "(1,1,1,2,'REFERENCE','two','x','{}','PENDING')")
                sql("INSERT INTO asr_processing_run(project_id,audio_id,audio_version_id,task_type,parameter_hash,deadline_at) "
                    "VALUES (1,1,1,'DIARIZATION','h',now() + interval '1 day'),(1,1,1,'MEDIA_ANALYSIS','h',now() + interval '1 day')")
                sql("INSERT INTO asr_comparison(project_id,job_id,audio_id) VALUES (1,1,1)")
                sql("INSERT INTO asr_diff_block(comparison_id,ordinal) VALUES (1,1)")
                sql("INSERT INTO asr_diarization_result(project_id,audio_id,audio_version_id,processing_run_id,source_model_id) "
                    "VALUES (1,1,1,1,'m')")
                sql("INSERT INTO asr_speaker(result_id,source_label,display_name) VALUES (1,'s','speaker')")
                sql("INSERT INTO asr_fusion_version(project_id,model_run_id,audio_version_id,diarization_result_id) VALUES (1,1,1,1)")
                sql("INSERT INTO asr_speaker_assignment(fusion_version_id,assignment_status) VALUES (1,'ASSIGNED')")
        yield engine
    finally:
        engine.dispose()
        with source.begin() as conn:
            conn.exec_driver_sql(f"DROP SCHEMA {schema} CASCADE")


def test_typed_asr_migration_round_trips_leases_review_subjects_and_allocators(asr_history):
    with asr_history.begin() as conn:
        sql = conn.exec_driver_sql
        with Operations.context(MigrationContext.configure(conn)):
            sql("INSERT INTO asr_work_item(run_id,lease_owner,lease_generation,lease_expires_at,attempts) "
                "VALUES (1,'old-worker',4,now(),9)")
            sql("INSERT INTO asr_processing_work_item(processing_run_id) VALUES (1)")
            sql("INSERT INTO asr_review_audit(block_id,reviewer_id,version,review_status,confirmed_text,include_reference_sample) "
                "VALUES (1,1,2,'CONFIRMED','',true)")
            sql("INSERT INTO asr_speaker_review_audit(assignment_id,version,reviewer_id,speaker_id,review_status) "
                "VALUES (1,2,1,1,'CONFIRMED')")
            sql("INSERT INTO asr_speaker_name_audit(speaker_id,reviewer_id,revision,previous_name,next_name) "
                "VALUES (1,1,2,'old','new')")
            tables = ("asr_work_item", "asr_processing_work_item", "asr_review_audit",
                      "asr_speaker_review_audit", "asr_speaker_name_audit")
            def read(name):
                return sql(f"SELECT * FROM {name} ORDER BY id").all()

            saved = {name: read(name) for name in tables}
            sql("SELECT setval('asr_processing_work_item_id_seq',80,true)")
            sql("SELECT setval('asr_speaker_name_audit_id_seq',60,true)")
            migration = _revision("0102")
            migration.upgrade()
            assert {name: read(name) for name in tables} == saved
            assert sql("SELECT count(*) FROM asr_queue_item WHERE public_id=1").scalar() == 2
            assert sql("SELECT count(*) FROM asr_review_event WHERE public_id=1").scalar() == 3
            # Older applications and canonical writes share each original sequence.
            assert sql("INSERT INTO asr_work_item(run_id) VALUES (2) RETURNING id").scalar() == 2
            assert sql("INSERT INTO asr_queue_item(kind,processing_run_id) VALUES ('PROCESSING_RUN',2) "
                       "RETURNING public_id").scalar() == 81
            assert sql("INSERT INTO asr_speaker_name_audit(speaker_id,revision,previous_name,next_name) "
                       "VALUES (1,3,'new','newer') RETURNING id").scalar() == 61
            sql("UPDATE asr_work_item SET lease_generation = 5 WHERE id = 1")
            sql("DELETE FROM asr_work_item WHERE id = 2")
            sql("DELETE FROM asr_speaker WHERE id = 1")
            assert read("asr_speaker_name_audit") == []
            assert sql("SELECT assignment_id,speaker_id FROM asr_speaker_review_audit").one() == (1, None)
            changed = {name: read(name) for name in tables}
            migration.downgrade()
            assert {name: read(name) for name in tables} == changed
            assert sql("INSERT INTO asr_work_item(run_id) VALUES (2) RETURNING id").scalar() == 3
            assert sql("SELECT nextval('asr_speaker_name_audit_id_seq')").scalar() == 62
            migration.upgrade()
            assert read("asr_work_item")[-1].id == 3

