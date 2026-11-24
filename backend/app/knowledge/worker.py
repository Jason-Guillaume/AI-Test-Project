"""Durable QUEUED versions are recovered after restart; row locks serialize parsers."""
import logging
import threading
from app.core.database.session import SessionLocal
from app.knowledge.models import KnowledgeVersion
from app.knowledge.service import parse_version
from app.knowledge.indexing import claim_job, run_job


def run(stop):
    while not stop.is_set():
        try:
            with SessionLocal() as db:
                row = db.query(KnowledgeVersion).filter_by(status='QUEUED').with_for_update(skip_locked=True).first()
                if row:
                    parse_version(db, row.id)
                    continue
                claim = claim_job(db)
                if claim:
                    run_job(db, *claim)
                    continue
        except Exception:
            logging.getLogger(__name__).exception('Knowledge parsing worker failed')
        stop.wait(3)


def start():
    stop = threading.Event()
    thread = threading.Thread(target=run, args=(stop,), daemon=True, name='knowledge-parser')
    thread.start()
    return stop
