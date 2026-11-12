"""Durable QUEUED versions are recovered after restart; row locks serialize parsers."""
import logging
import threading
from app.core.database.session import SessionLocal
from app.knowledge.models import KnowledgeVersion
from app.knowledge.service import parse_version


def run(stop):
    while not stop.is_set():
        try:
            with SessionLocal() as db:
                row = db.query(KnowledgeVersion).filter_by(status='QUEUED').with_for_update(skip_locked=True).first()
                if row:
                    parse_version(db, row.id)
                    continue
        except Exception:
            logging.getLogger(__name__).exception('Knowledge parsing worker failed')
        stop.wait(3)


def start():
    stop = threading.Event()
    thread = threading.Thread(target=run, args=(stop,), daemon=True, name='knowledge-parser')
    thread.start()
    return stop
