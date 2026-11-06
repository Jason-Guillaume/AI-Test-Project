"""Cross-process semaphore for outbound ASR and diarization HTTP requests."""

from __future__ import annotations

import threading
import time
from contextlib import contextmanager
from typing import Iterator

from sqlalchemy import text
from sqlalchemy.engine import Engine

from app.core.config import settings
from app.core.database.session import engine

_LOCAL_SLOTS = threading.BoundedSemaphore(max(1, min(settings.ASR_WORKER_CONCURRENCY, 16)))
_ADVISORY_NAMESPACE = 4_276_562  # "ASR"; isolated from other PostgreSQL advisory-lock users.


@contextmanager
def asr_request_slot(bind: Engine | None = None) -> Iterator[None]:
    """Share ASR request capacity across the legacy and FunASR workers in all processes."""
    capacity = max(1, min(settings.ASR_WORKER_CONCURRENCY, 16))
    target_engine = bind or engine
    if target_engine.dialect.name != "postgresql":
        with _LOCAL_SLOTS:
            yield
        return

    deadline = time.monotonic() + 1800
    connection = None
    acquired_slot: int | None = None
    try:
        while acquired_slot is None:
            if connection is None:
                connection = target_engine.connect()
            for slot in range(capacity):
                acquired = connection.execute(text("SELECT pg_try_advisory_lock(:namespace, :slot)"),
                    {"namespace": _ADVISORY_NAMESPACE, "slot": slot}).scalar()
                if acquired:
                    acquired_slot = slot
                    connection.commit()
                    break
            if acquired_slot is None:
                connection.rollback()
                if time.monotonic() >= deadline:
                    raise TimeoutError("等待 ASR 全局并发名额超时")
                time.sleep(0.2)
        yield
    finally:
        if connection is not None:
            try:
                if acquired_slot is not None:
                    connection.execute(text("SELECT pg_advisory_unlock(:namespace, :slot)"),
                        {"namespace": _ADVISORY_NAMESPACE, "slot": acquired_slot})
                    connection.commit()
            finally:
                connection.close()


__all__ = ["asr_request_slot"]
