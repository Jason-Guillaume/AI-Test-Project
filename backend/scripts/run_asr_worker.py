"""ASR 夜间评测 Worker 启动脚本。

由独立常驻进程运行持久队列和每日计划；可用 ASR_WORKER_ID、ASR_WORKER_POLL_SECONDS、
ASR_WORKER_CONCURRENCY 与 ASR_WORKER_LEASE_SECONDS 配置实例身份和进程并发上限。
ASR_DIARIZATION_CONCURRENCY 与 ASR_MEDIA_ANALYSIS_MAX_BYTES 分别限制说话人外呼和后台媒体处理资源。
"""

from __future__ import annotations

import logging
import signal

from app.core.config import settings
from app.features.asr_evaluation.runtime.worker import AsrWorker


def main() -> None:
    """构造领域 Worker 并响应系统停止信号。"""
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s %(message)s")
    worker = AsrWorker(
        worker_id=settings.ASR_WORKER_ID,
        poll_seconds=settings.ASR_WORKER_POLL_SECONDS,
        max_concurrency=settings.ASR_WORKER_CONCURRENCY,
        max_diarization_concurrency=settings.ASR_DIARIZATION_CONCURRENCY,
        lease_seconds=settings.ASR_WORKER_LEASE_SECONDS,
    )
    signal.signal(signal.SIGINT, lambda *_: worker.stop())
    signal.signal(signal.SIGTERM, lambda *_: worker.stop())
    worker.run_forever()


if __name__ == "__main__":
    main()
