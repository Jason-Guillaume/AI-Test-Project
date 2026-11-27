"""ASR 服务公开入口；跨模块调用只通过此处导出的方法。"""

from app.features.asr_evaluation.services.assets_service import (
    check_audio, create_audio, ensure_audio_version, import_audios, list_audios, update_audio,
)

__all__ = [
    "check_audio", "create_audio", "ensure_audio_version", "import_audios", "list_audios", "update_audio",
]