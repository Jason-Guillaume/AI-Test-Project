"""ASR 评测 ORM 公开入口。

仅从唯一模型定义模块导出领域表，供 Alembic 与 ASR 服务发现；不扩展 core 基线模型集合。
"""

from app.features.asr_evaluation.models.asr_models import (
    AsrAudio, AsrAudioVersion, AsrComparison, AsrConnection, AsrDiffBlock, AsrDiarizationResult,
    AsrContentReviewChunk, AsrContentReviewJob, AsrEvaluationArtifact, AsrExperiment, AsrFusionVersion, AsrMediaAnalysis, AsrProcessingRun, AsrProcessingWorkItem,
    AsrReferenceSample, AsrSpeaker, AsrSpeakerAssignment, AsrSpeakerNameAudit, AsrSpeakerReviewAudit,
    AsrSpeakerTurn, AsrTranscriptSegment,
    AsrJob, AsrModelRun, AsrParameterSet, AsrReviewAudit, AsrSchedule,
    AsrSuggestion, AsrSuggestionJob, AsrWorkItem, AsrWorkerHeartbeat,
)
from app.features.asr_evaluation.models.funasr_models import (
    AsrApiBinding, AsrGroundTruthVersion, AsrTuningItem, AsrTuningRound, AsrTuningSession,
)

__all__ = [
    "AsrAudio", "AsrAudioVersion", "AsrComparison", "AsrConnection", "AsrDiffBlock", "AsrDiarizationResult",
    "AsrContentReviewChunk", "AsrContentReviewJob", "AsrEvaluationArtifact", "AsrExperiment", "AsrFusionVersion", "AsrMediaAnalysis", "AsrProcessingRun", "AsrProcessingWorkItem",
    "AsrReferenceSample", "AsrSpeaker", "AsrSpeakerAssignment", "AsrSpeakerNameAudit",
    "AsrSpeakerReviewAudit", "AsrSpeakerTurn", "AsrTranscriptSegment",
    "AsrJob", "AsrModelRun", "AsrParameterSet", "AsrReviewAudit", "AsrSchedule",
    "AsrSuggestion", "AsrSuggestionJob", "AsrWorkItem", "AsrWorkerHeartbeat",
    "AsrApiBinding", "AsrGroundTruthVersion", "AsrTuningSession", "AsrTuningRound", "AsrTuningItem",
]
