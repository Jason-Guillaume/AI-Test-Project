"""Durable QUEUED versions are recovered after restart; row locks serialize parsers."""
import logging
import threading
from itertools import cycle
from app.core.database.session import SessionLocal
from app.knowledge.models import KnowledgeDocument, KnowledgeVersion
from app.knowledge.service import parse_version
from app.knowledge.indexing import claim_job, parse_queue, run_job


def _parse_one(db):
    # Claim with the same document-first lock order used by upload and parse_version.
    row = parse_queue(db).order_by(KnowledgeVersion.id).with_for_update(
        of=KnowledgeDocument, skip_locked=True,
    ).first()
    if row is None:
        return False
    parse_version(db, row.id)
    return True


def _index_one(db):
    claim = claim_job(db)
    if claim is None:
        return False
    run_job(db, *claim)
    return True


def run(stop):
    for preferred, fallback in cycle(((_parse_one, _index_one), (_index_one, _parse_one))):
        if stop.is_set():
            return
        try:
            with SessionLocal() as db:
                if preferred(db) or fallback(db):
                    continue
        except Exception:
            logging.getLogger(__name__).exception('Knowledge worker failed')
        stop.wait(3)


def start():
    stop = threading.Event()
    thread = threading.Thread(target=run, args=(stop,), daemon=True, name='knowledge-parser')
    thread.start()
    return stop
