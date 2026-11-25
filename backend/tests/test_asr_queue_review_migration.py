import importlib.util
from pathlib import Path
from uuid import uuid4

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

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


def test_workers_skip_locked_items_and_fence_old_claims_on_postgres(asr_history, monkeypatch):
    from app.features.asr_evaluation.runtime import worker as runtime

    with asr_history.begin() as conn:
        with Operations.context(MigrationContext.configure(conn)):
            _revision("0102").upgrade()
        conn.exec_driver_sql(
            "INSERT INTO asr_work_item(id,run_id,available_at) VALUES (20,1,'2000-01-01'),(10,2,'2000-01-01')"
        )
        conn.exec_driver_sql("INSERT INTO asr_processing_work_item(processing_run_id) VALUES (1),(2)")
    factory = sessionmaker(asr_history, expire_on_commit=False, autoflush=False)
    monkeypatch.setattr(runtime, "SessionLocal", factory)
    first = runtime.AsrWorker(worker_id="one")
    second = runtime.AsrWorker(worker_id="two")
    with asr_history.begin() as locker:
        # The oldest public ID is locked by another connection; the worker must skip it.
        locker.exec_driver_sql("SELECT id FROM asr_queue_item WHERE kind='MODEL_RUN' AND public_id=10 FOR UPDATE")
        claim = first._claim_next()
        assert claim and claim[1] == 1
        assert second._claim_next() is None
        processing = second._claim_next_processing("DIARIZATION")
        media = first._claim_next_processing("MEDIA_ANALYSIS")
        assert (processing[1], media[1]) == (1, 2)
        assert second._claim_next_processing("DIARIZATION") is None
    assert second._claim_next()[1] == 2
    item_id, run_id, owner, generation, _ = claim
    with asr_history.begin() as conn:
        conn.exec_driver_sql("UPDATE asr_model_run SET remote_task_id='receipt' WHERE id=1")
        conn.exec_driver_sql("UPDATE asr_queue_item SET lease_expires_at=now() WHERE kind='MODEL_RUN' AND run_id=1")
    takeover = second._claim_next()
    assert takeover[:2] == (item_id, run_id)
    assert takeover[3:] == (generation + 1, False)
    first._finish(run_id, item_id, owner, generation, "FAILED", "stale")
    first._reschedule(item_id, run_id, owner, generation, delay_seconds=1, reset_submit=True)
    # A processing claim with the right token still cannot finish a different processing run.
    second._finish_processing(processing[0], media[1], processing[2], processing[3], "FAILED", "wrong run")
    with asr_history.begin() as conn:
        assert conn.exec_driver_sql("SELECT status FROM asr_model_run WHERE id=1").scalar() == "REMOTE_RUNNING"
        assert conn.exec_driver_sql("SELECT lease_owner FROM asr_queue_item WHERE run_id=1").scalar() == takeover[2]
        assert conn.exec_driver_sql("SELECT status FROM asr_processing_run ORDER BY id").scalars().all() == [
            "SUBMITTING", "SUBMITTING",
        ]


def test_claim_that_expires_while_waiting_for_the_row_lock_is_rejected(asr_history, monkeypatch):
    from concurrent.futures import ThreadPoolExecutor
    from datetime import datetime, timedelta, timezone
    from threading import Event

    from sqlalchemy import event
    from app.features.asr_evaluation.runtime import worker

    before = datetime(2030, 1, 1, tzinfo=timezone.utc)
    deadline = before + timedelta(seconds=1)
    waiting, expired = Event(), Event()

    class ControlledClock(datetime):
        @classmethod
        def now(cls, tz=None):
            return deadline + timedelta(seconds=1) if expired.is_set() else before

    with asr_history.begin() as c:
        with Operations.context(MigrationContext.configure(c)):
            _revision("0102").upgrade()
        item_id = c.exec_driver_sql(
            "INSERT INTO asr_queue_item(kind,run_id,lease_owner,lease_generation,lease_expires_at) "
            "VALUES ('MODEL_RUN',1,'worker',4,%s) RETURNING id", (deadline,),
        ).scalar_one()

    def observe_sql(conn, cursor, statement, parameters, context, executemany):
        if "FOR UPDATE" in statement:
            waiting.set()

    def check_lease():
        with sessionmaker(bind=asr_history)() as db:
            return worker._owned_item(db, worker.AsrWorkItem, item_id, 1, "worker", 4) is None

    monkeypatch.setattr(worker, "datetime", ControlledClock)
    with ThreadPoolExecutor(max_workers=1) as pool:
        with asr_history.begin() as locker:
            locker.exec_driver_sql("SELECT id FROM asr_queue_item WHERE id=%s FOR UPDATE", (item_id,))
            event.listen(asr_history, "before_cursor_execute", observe_sql)
            try:
                result = pool.submit(check_lease)
                assert waiting.wait(5)
                expired.set()
            finally:
                event.remove(asr_history, "before_cursor_execute", observe_sql)
        assert result.result(timeout=5)
