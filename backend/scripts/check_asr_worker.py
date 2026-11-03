"""Fail the container health check unless the configured ASR worker heartbeat is fresh and ready."""

from __future__ import annotations

import sys
from datetime import datetime, timedelta, timezone

from app.core.database.session import SessionLocal
from app.core.config import settings
from app.features.asr_evaluation.models import AsrWorkerHeartbeat


def main() -> int:
    worker_id = settings.ASR_WORKER_ID
    timeout = max(15, settings.ASR_WORKER_HEARTBEAT_TIMEOUT_SECONDS)
    db = SessionLocal()
    try:
        row = db.get(AsrWorkerHeartbeat, worker_id)
        now = datetime.now(timezone.utc)
        if row is None or row.last_seen_at < now - timedelta(seconds=timeout) or not row.business_ready:
            return 1
        return 0
    except Exception:
        return 1
    finally:
        db.close()


if __name__ == "__main__":
    sys.exit(main())
