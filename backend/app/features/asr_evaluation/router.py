"""ASR 评测 HTTP 适配层。

本模块只解析路径、查询与 DTO 并调用领域 service；项目权限、事务、敏感信息保护和外部 IO 均在服务层完成。
所有路由由 app.main 统一挂载到 /api/v1。
"""

from __future__ import annotations

from fastapi import APIRouter, Depends, Header, Query, Response, status
from sqlalchemy.orm import Session

from app.core.database.session import get_db
from app.core.http.errors import bad_request, not_found
from app.core.models.identity import User
from app.core.security.auth import get_current_user
from app.features.asr_evaluation.models import AsrAudio, AsrConnection, AsrDiffBlock
from app.features.asr_evaluation.schemas import (
    AudioCreate, AudioImport, AudioUpdate, ConnectionCheck, ConnectionCreate, DiarizationRunCreate,
    ExperimentCreate, JobCreate, ParameterSetCreate, ReviewInput, ScheduleCreate, ScheduleUpdate,
    SpeakerFusionCreate, SpeakerNameUpdate, SpeakerReviewInput,
)
from app.features.asr_evaluation.funasr_schemas import (
    FunAsrBindingCreate, FunAsrBindingUpdate, FunAsrGroundTruthCreate,
    FunAsrNormalizePreview, FunAsrTuningCreate,
)
from app.features.asr_evaluation.services.assets_service import (
    check_audio, create_audio, create_connections, create_parameter_set, create_schedule,
    import_audios, list_audios, list_connections, list_parameter_sets, list_schedules, update_audio, update_schedule,
)
from app.features.asr_evaluation.services.job_service import (
    cancel_job, create_connection_check, create_job, get_job, list_audio_recent_runs, list_job_audio_runs,
    list_jobs, rerun_job, retry_job, runtime_status,
)
from app.features.asr_evaluation.services.comparison_service import (
    create_experiment, create_suggestions, export_comparison, get_comparison, list_review_history,
    list_blocks, list_comparisons, list_experiments, list_suggestions, review_block, run_experiment,
)
from app.features.asr_evaluation.services.media_service import stream_audio
from app.features.asr_evaluation.services.media_analysis_service import (
    create_media_analysis_run, get_audio_metadata, get_audio_peaks,
)
from app.features.asr_evaluation.services.diarization_service import (
    create_diarization_run, create_run_fusion_by_id, export_run_workbench, get_processing_run,
    list_speaker_turns, list_speakers, rename_speaker, retry_processing_run, review_speaker_assignment,
)
from app.features.asr_evaluation.services.segments_service import get_native_statistics, get_run_workbench, list_transcript_segments
from app.features.asr_evaluation.services.evaluation_artifact_service import (
    create_evaluation_artifacts, list_evaluation_artifacts, read_evaluation_artifact,
)
from app.features.asr_evaluation.services.content_review_service import cancel_review, create_review, get_review, list_review_models, list_reviews, retry_review, review_summary
from app.features.asr_evaluation.services.suggestion_job_service import (
    create_suggestion_job, list_suggestion_jobs, retry_suggestion_job,
)
from app.features.asr_evaluation.services import funasr_tuning_service as funasr_service

router = APIRouter(prefix="/asr", tags=["ASR 评测"])


@router.get("/funasr/definitions")
def funasr_parameter_definitions():
    """返回经用户参数说明确认的字段约束；文档默认值不代表已选择的任务基线。"""
    return {"items": funasr_service.FUNASR_DEFINITIONS, "source": "Paraformer V2 参数说明归档",
            "source_version": "2026-11-06", "response_mapping_configured": False}


@router.get("/funasr/interfaces")
def funasr_interfaces(project_id: int = Query(gt=0), db: Session = Depends(get_db), actor: User = Depends(get_current_user)):
    """从当前项目接口管理列出可绑定接口。"""
    return funasr_service.list_fun_asr_interfaces(db, project_id, actor)


@router.get("/funasr/environments")
def funasr_environments(project_id: int = Query(gt=0), db: Session = Depends(get_db), actor: User = Depends(get_current_user)):
    """列出当前项目已关联的安全环境选项，不返回默认鉴权头。"""
    return funasr_service.list_fun_asr_environments(db, project_id, actor)


@router.get("/funasr/bindings")
def funasr_binding_list(project_id: int = Query(gt=0), db: Session = Depends(get_db), actor: User = Depends(get_current_user)):
    return funasr_service.list_fun_asr_bindings(db, project_id, actor)


@router.post("/funasr/bindings", status_code=status.HTTP_201_CREATED)
def funasr_binding_create(body: FunAsrBindingCreate, db: Session = Depends(get_db), actor: User = Depends(get_current_user)):
    return funasr_service.create_fun_asr_binding(db, body, actor)


@router.patch("/funasr/bindings/{binding_id}")
def funasr_binding_update(binding_id: int, body: FunAsrBindingUpdate, db: Session = Depends(get_db), actor: User = Depends(get_current_user)):
    return funasr_service.update_fun_asr_binding(db, binding_id, body, actor)


@router.post("/funasr/mapping-preview")
def funasr_mapping_preview(body: FunAsrNormalizePreview):
    """使用显式字段路径预览 JSON 规范化；没有映射配置时不猜响应结构。"""
    return funasr_service.preview_fun_asr_mapping(body.document, body.mapping, body.source, body.audio_version_id)


@router.get("/funasr/ground-truth")
def funasr_ground_truth_list(project_id: int = Query(gt=0), db: Session = Depends(get_db), actor: User = Depends(get_current_user)):
    return funasr_service.list_ground_truth(db, project_id, actor)


@router.post("/funasr/audio/{audio_id}/ground-truth", status_code=status.HTTP_201_CREATED)
def funasr_ground_truth_create(audio_id: int, body: FunAsrGroundTruthCreate, db: Session = Depends(get_db), actor: User = Depends(get_current_user)):
    """保存不可变答案版本；重传会新增版本并固定映射与音频版本。"""
    return funasr_service.create_ground_truth(db, audio_id, body, actor)


@router.get("/funasr/models")
def funasr_model_list(project_id: int = Query(gt=0), db: Session = Depends(get_db), actor: User = Depends(get_current_user)):
    return funasr_service.get_models_for_project(db, project_id, actor)


@router.get("/funasr/sessions")
def funasr_session_list(project_id: int = Query(gt=0), db: Session = Depends(get_db), actor: User = Depends(get_current_user)):
    return funasr_service.list_tuning_sessions(db, project_id, actor)


@router.post("/funasr/sessions", status_code=status.HTTP_202_ACCEPTED)
def funasr_session_create(body: FunAsrTuningCreate, db: Session = Depends(get_db), actor: User = Depends(get_current_user)):
    return funasr_service.create_tuning_session(db, body, actor)


@router.get("/funasr/sessions/{session_id}")
def funasr_session_detail(session_id: int, db: Session = Depends(get_db), actor: User = Depends(get_current_user)):
    return funasr_service.get_tuning_session(db, session_id, actor)


@router.post("/funasr/sessions/{session_id}/pause")
def funasr_session_pause(session_id: int, db: Session = Depends(get_db), actor: User = Depends(get_current_user)):
    return funasr_service.pause_tuning_session(db, session_id, actor)


@router.post("/funasr/sessions/{session_id}/resume")
def funasr_session_resume(session_id: int, db: Session = Depends(get_db), actor: User = Depends(get_current_user)):
    return funasr_service.resume_tuning_session(db, session_id, actor)


@router.post("/funasr/sessions/{session_id}/stop")
def funasr_session_stop(session_id: int, db: Session = Depends(get_db), actor: User = Depends(get_current_user)):
    return funasr_service.stop_tuning_session(db, session_id, actor)


@router.post("/funasr/sessions/{session_id}/retry-failed")
def funasr_session_retry_failed(session_id: int, db: Session = Depends(get_db), actor: User = Depends(get_current_user)):
    return funasr_service.retry_failed_tuning_items(db, session_id, actor)


@router.post("/funasr/sessions/{session_id}/retry-analysis")
def funasr_session_retry_analysis(session_id: int, db: Session = Depends(get_db), actor: User = Depends(get_current_user)):
    """仅重跑明确失败的 AI 阶段；状态未知时拒绝重发。"""
    return funasr_service.retry_tuning_analysis(db, session_id, actor)


@router.get("/audio")
def audio_list(
    project_id: int = Query(gt=0), page: int = Query(1, ge=1),
    page_size: int = Query(20, ge=1, le=200), db: Session = Depends(get_db),
    keyword: str | None = Query(default=None, max_length=200),
    actor: User = Depends(get_current_user),
):
    """分页列出项目内已登记音频及链接可达性状态。"""
    return list_audios(db, project_id, actor, page=page, page_size=page_size, keyword=keyword)


@router.get("/audio/recent-runs")
def audio_recent_runs(
    project_id: int = Query(gt=0), audio_ids: str = Query(default="", max_length=2400),
    db: Session = Depends(get_db), actor: User = Depends(get_current_user),
):
    """返回当前音频页的最近运行链接，不包含识别文本或敏感请求字段。"""
    try:
        parsed_ids = [int(value) for value in audio_ids.split(",") if value]
    except ValueError:
        raise bad_request("音频编号格式无效") from None
    if len(parsed_ids) > 200:
        raise bad_request("一次最多读取 200 条音频")
    return {"items": list_audio_recent_runs(db, project_id, parsed_ids, actor)}


@router.post("/audio", status_code=status.HTTP_201_CREATED)
def audio_create(body: AudioCreate, db: Session = Depends(get_db), actor: User = Depends(get_current_user)):
    """创建单条加密保存的音频 URL 资源。"""
    return create_audio(db, body.project_id, body.audio, actor)


@router.post("/audio/import", status_code=status.HTTP_201_CREATED)
def audio_import(body: AudioImport, db: Session = Depends(get_db), actor: User = Depends(get_current_user)):
    """一次性导入多条已有音频链接，不上传原始媒体文件。"""
    return {"items": import_audios(db, body.project_id, body.items, actor)}


@router.get("/audio/{audio_id}")
def audio_detail(audio_id: int, db: Session = Depends(get_db), actor: User = Depends(get_current_user)):
    """读取音频资源脱敏详情。"""
    row = db.get(AsrAudio, audio_id)
    if row is None:
        raise not_found("音频资源不存在")
    from app.platform.projects.services.access_service import get_project_or_404
    from app.features.asr_evaluation.services.assets_service import _dump_audio
    get_project_or_404(db, row.project_id, actor)
    return _dump_audio(row)


@router.patch("/audio/{audio_id}")
def audio_update(
    audio_id: int, body: AudioUpdate, db: Session = Depends(get_db),
    actor: User = Depends(get_current_user),
):
    """更新名称、URL 或时长；URL 变更产生新内容版本。"""
    return update_audio(
        db, audio_id, name=body.name, url=str(body.url) if body.url else None,
        duration_seconds=body.duration_seconds, actor=actor,
    )


@router.post("/audio/{audio_id}/check")
def audio_check(audio_id: int, db: Session = Depends(get_db), actor: User = Depends(get_current_user)):
    """分别检查项目出站授权和上游 URL 可达性，不把 HEAD 不支持当作音频无效。"""
    return check_audio(db, audio_id, actor)


@router.get("/audio/{audio_id}/media")
def audio_media(
    audio_id: int, range_header: str | None = Header(default=None, alias="Range"),
    db: Session = Depends(get_db), actor: User = Depends(get_current_user),
):
    """按项目权限流式代理音频并支持浏览器 Range 回听。"""
    return stream_audio(db, audio_id, actor, range_header)


@router.get("/audio/{audio_id}/versions/{audio_version_id}/media")
def audio_version_media(
    audio_id: int, audio_version_id: int, range_header: str | None = Header(default=None, alias="Range"),
    db: Session = Depends(get_db), actor: User = Depends(get_current_user),
):
    """按固定音频版本代理 Range 流，链接变更后历史运行仍绑定原版本。"""
    return stream_audio(db, audio_id, actor, range_header, audio_version_id=audio_version_id)


@router.get("/audio/{audio_id}/versions/{audio_version_id}/metadata")
def audio_version_metadata(
    audio_id: int, audio_version_id: int, db: Session = Depends(get_db),
    actor: User = Depends(get_current_user),
):
    """读取固定版本的来源、原文件属性和后台媒体分析结果。"""
    return get_audio_metadata(db, audio_id, audio_version_id, actor)


@router.post("/audio/{audio_id}/versions/{audio_version_id}/analysis-runs", status_code=status.HTTP_202_ACCEPTED)
def audio_analysis_create(
    audio_id: int, audio_version_id: int, db: Session = Depends(get_db),
    actor: User = Depends(get_current_user),
):
    """显式排队媒体分析；读取工作台或打开信息抽屉不会触发整条音频下载。"""
    return create_media_analysis_run(db, audio_id, audio_version_id, actor)


@router.get("/audio/{audio_id}/versions/{audio_version_id}/peaks")
def audio_version_peaks(
    audio_id: int, audio_version_id: int, resolution: int = Query(default=2048),
    db: Session = Depends(get_db), actor: User = Depends(get_current_user),
):
    """按需返回后台生成的 2048 或 8192 档多声道峰值。"""
    return get_audio_peaks(db, audio_id, audio_version_id, resolution, actor)


@router.post(
    "/audio/{audio_id}/versions/{audio_version_id}/diarization-runs",
    status_code=status.HTTP_202_ACCEPTED,
)
def diarization_run_create(
    audio_id: int, audio_version_id: int, body: DiarizationRunCreate,
    db: Session = Depends(get_db), actor: User = Depends(get_current_user),
):
    """独立排队固定音频版本的说话人分析，与三方转写任务分离。"""
    return create_diarization_run(db, audio_id, audio_version_id, body, actor)


@router.get("/processing-runs/{processing_run_id}")
def processing_run_detail(
    processing_run_id: int, db: Session = Depends(get_db), actor: User = Depends(get_current_user),
):
    """查询说话人或媒体处理状态，不以三方批次状态代替阶段状态。"""
    return get_processing_run(db, processing_run_id, actor)


@router.post("/processing-runs/{processing_run_id}/retry", status_code=status.HTTP_202_ACCEPTED)
def processing_run_retry(
    processing_run_id: int, db: Session = Depends(get_db), actor: User = Depends(get_current_user),
):
    """只重试明确失败的说话人或媒体阶段，不重新提交待测及参考 ASR。"""
    return retry_processing_run(db, processing_run_id, actor)


@router.get("/runs/{run_id}")
def run_workbench(
    run_id: int, db: Session = Depends(get_db), actor: User = Depends(get_current_user),
):
    """读取单模型工作台摘要、固定音频版本、参数快照和独立说话人状态。"""
    return get_run_workbench(db, run_id, actor)


@router.get("/runs/{run_id}/segments")
def run_segments(
    run_id: int, page: int = Query(1, ge=1), page_size: int = Query(100, ge=1, le=1000),
    at_ms: int | None = Query(default=None, ge=0),
    start_ms: int | None = Query(default=None, ge=0), end_ms: int | None = Query(default=None, ge=0),
    speaker_id: int | None = Query(default=None, gt=0), unknown_only: bool = False,
    mixed_only: bool = False, search: str | None = Query(default=None, max_length=200),
    native_speaker_id: str | None = Query(default=None, max_length=255),
    locate_segment_id: str | None = Query(default=None, max_length=80),
    db: Session = Depends(get_db), actor: User = Depends(get_current_user),
):
    """分页读取稳定转写段、原生说话人字段和独立模型关联。"""
    return list_transcript_segments(
        db, run_id, actor, page=page, page_size=page_size, speaker_id=speaker_id,
        unknown_only=unknown_only, mixed_only=mixed_only, search=search,
        native_speaker_id=native_speaker_id, at_ms=at_ms, start_ms=start_ms, end_ms=end_ms,
        locate_segment_id=locate_segment_id,
    )


@router.get("/runs/{run_id}/statistics")
def run_statistics(run_id: int, db: Session = Depends(get_db), actor: User = Depends(get_current_user)):
    """读取完整转写结果的原生标签统计，不将其与独立说话人归属混同。"""
    return get_native_statistics(db, run_id, actor)


@router.get("/content-review-models")
def content_review_models(project_id: int = Query(gt=0), db: Session = Depends(get_db), actor: User = Depends(get_current_user)):
    """列出当前项目成员可用于内容评审的文本模型摘要。"""
    return list_review_models(db, project_id, actor)


@router.post("/runs/{run_id}/content-review-jobs", status_code=status.HTTP_202_ACCEPTED)
def run_content_review_create(run_id: int, model_config_id: int = Query(gt=0), db: Session = Depends(get_db), actor: User = Depends(get_current_user)):
    """基于已有运行创建单条内容评审。"""
    return create_review(db, "SINGLE", run_id, model_config_id, actor)


@router.get("/runs/{run_id}/content-review-jobs")
def run_content_review_list(run_id: int, page: int = Query(1, ge=1), page_size: int = Query(20, ge=1, le=100),
                            db: Session = Depends(get_db), actor: User = Depends(get_current_user)):
    """列出当前运行的单条评审。"""
    return list_reviews(db, "run", run_id, actor, page=page, page_size=page_size)


@router.post("/comparisons/{comparison_id}/content-review-jobs", status_code=status.HTTP_202_ACCEPTED)
def comparison_content_review_create(comparison_id: int, model_config_id: int = Query(gt=0), db: Session = Depends(get_db), actor: User = Depends(get_current_user)):
    """基于同版本三方运行创建内容评审。"""
    return create_review(db, "TRIPLET", comparison_id, model_config_id, actor)


@router.get("/comparisons/{comparison_id}/content-review-jobs")
def comparison_content_review_list(comparison_id: int, page: int = Query(1, ge=1), page_size: int = Query(20, ge=1, le=100),
                                   db: Session = Depends(get_db), actor: User = Depends(get_current_user)):
    """列出当前对比的内容评审。"""
    return list_reviews(db, "comparison", comparison_id, actor, page=page, page_size=page_size)


@router.post("/experiments/{experiment_id}/content-review-jobs", status_code=status.HTTP_202_ACCEPTED)
def experiment_content_review_create(experiment_id: int, model_config_id: int = Query(gt=0), db: Session = Depends(get_db), actor: User = Depends(get_current_user)):
    """基于实验的基线与候选运行创建 A/B 评审。"""
    return create_review(db, "AB", experiment_id, model_config_id, actor)


@router.get("/experiments/{experiment_id}/content-review-jobs")
def experiment_content_review_list(experiment_id: int, page: int = Query(1, ge=1), page_size: int = Query(20, ge=1, le=100),
                                   db: Session = Depends(get_db), actor: User = Depends(get_current_user)):
    """列出候选实验的 A/B 内容评审。"""
    return list_reviews(db, "experiment", experiment_id, actor, page=page, page_size=page_size)


@router.get("/content-review-jobs/{review_id}")
def content_review_detail(review_id: int, db: Session = Depends(get_db), actor: User = Depends(get_current_user)):
    """读取评审覆盖、块状态及经过验证的证据。"""
    return get_review(db, review_id, actor)


@router.post("/content-review-jobs/{review_id}/retry", status_code=status.HTTP_202_ACCEPTED)
def content_review_retry(review_id: int, chunk_id: int | None = Query(default=None, gt=0), db: Session = Depends(get_db), actor: User = Depends(get_current_user)):
    """仅重新排队明确失败的评审块。"""
    return retry_review(db, review_id, actor, chunk_id=chunk_id)


@router.post("/content-review-jobs/{review_id}/cancel")
def content_review_cancel(review_id: int, db: Session = Depends(get_db), actor: User = Depends(get_current_user)):
    """停止未发出的内容评审块，不承诺远端已取消。"""
    return cancel_review(db, review_id, actor)


@router.get("/jobs/{job_id}/content-review-summary")
def content_review_summary(job_id: int, db: Session = Depends(get_db), actor: User = Depends(get_current_user)):
    """读取批次的音频及评审覆盖分子分母。"""
    return review_summary(db, job_id, actor)


@router.post("/runs/{run_id}/evaluation-artifacts", status_code=status.HTTP_201_CREATED)
def evaluation_artifacts_create(run_id: int, db: Session = Depends(get_db), actor: User = Depends(get_current_user)):
    """冻结规范化快照并生成 Markdown，不重新调用 ASR。"""
    return create_evaluation_artifacts(db, run_id, actor)


@router.get("/runs/{run_id}/evaluation-artifacts")
def evaluation_artifacts_list(run_id: int, db: Session = Depends(get_db), actor: User = Depends(get_current_user)):
    """列出运行产物元信息及原始响应是否可用。"""
    return list_evaluation_artifacts(db, run_id, actor)


@router.get("/evaluation-artifacts/{artifact_id}")
def evaluation_artifact_download(artifact_id: int, db: Session = Depends(get_db), actor: User = Depends(get_current_user)):
    """按项目授权下载校验通过的产物。"""
    row, data = read_evaluation_artifact(db, artifact_id, actor)
    extension = "md" if row.kind in {"MARKDOWN", "REVIEW_INPUT_MD", "REVIEW_SOURCE_MD"} else "json"
    return Response(content=data, media_type="text/markdown" if extension == "md" else "application/json",
                    headers={"Content-Disposition": f'attachment; filename="asr-artifact-{row.id}.{extension}"',
                             "Cache-Control": "private, no-store", "X-Content-Type-Options": "nosniff"})


@router.post("/runs/{run_id}/speaker-assignments", status_code=status.HTTP_202_ACCEPTED)
def run_speaker_assignments(
    run_id: int, body: SpeakerFusionCreate,
    db: Session = Depends(get_db), actor: User = Depends(get_current_user),
):
    """关联同一音频版本的指定说话人结果，文本无真实时间时只保留未对齐。"""
    return create_run_fusion_by_id(db, run_id, body.diarization_result_id, actor)


@router.get("/diarization-results/{result_id}/speakers")
def diarization_speakers(
    result_id: int, db: Session = Depends(get_db), actor: User = Depends(get_current_user),
):
    """读取说话人数、每人全量片段与按区间并集计算的发言统计。"""
    return list_speakers(db, result_id, actor)


@router.get("/diarization-results/{result_id}/turns")
def diarization_turns(
    result_id: int, page: int = Query(1, ge=1), page_size: int = Query(100, ge=1, le=200),
    speaker_id: int | None = Query(default=None, gt=0), unknown_only: bool = False,
    overlap_only: bool = False, start_ms: int | None = Query(default=None, ge=0),
    end_ms: int | None = Query(default=None, ge=0),
    db: Session = Depends(get_db), actor: User = Depends(get_current_user),
):
    """按说话人、未知、重叠和时间范围分页读取分段模型区间。"""
    return list_speaker_turns(
        db, result_id, actor, page=page, page_size=page_size, speaker_id=speaker_id,
        unknown_only=unknown_only, overlap_only=overlap_only, start_ms=start_ms, end_ms=end_ms,
    )


@router.put("/speaker-assignments/{assignment_id}/review")
def speaker_assignment_review(
    assignment_id: int, body: SpeakerReviewInput,
    db: Session = Depends(get_db), actor: User = Depends(get_current_user),
):
    """保存带乐观锁的人工说话人归属或未知确认，并追加审计记录。"""
    return review_speaker_assignment(db, assignment_id, body, actor)


@router.patch("/diarization-results/speakers/{speaker_id}")
def speaker_name_update(
    speaker_id: int, body: SpeakerNameUpdate,
    db: Session = Depends(get_db), actor: User = Depends(get_current_user),
):
    """修改单个说话人结果内的显示名，不跨录音合并模型原始标签。"""
    return rename_speaker(db, speaker_id, body, actor)


@router.get("/runs/{run_id}/exports")
def run_workbench_export(
    run_id: int, format: str = Query(default="json", pattern="^(json|txt)$"),
    db: Session = Depends(get_db), actor: User = Depends(get_current_user),
):
    """导出原始转写与带来源的说话人关联，不将人工结论冒充模型原文。"""
    body, media_type = export_run_workbench(db, run_id, actor, format_name=format)
    return Response(
        content=body, media_type=media_type,
        headers={"Content-Disposition": f'attachment; filename="asr-run-{run_id}.{format}"'},
    )


@router.get("/connections")
def connection_list(
    project_id: int = Query(gt=0),
    task_type: str = Query(default="TRANSCRIPTION", pattern="^(TRANSCRIPTION|DIARIZATION)$"),
    db: Session = Depends(get_db),
    actor: User = Depends(get_current_user),
):
    """列出项目中的待测与参考连接版本，凭据只返回配置状态。"""
    return {"items": list_connections(db, project_id, actor, task_type=task_type)}


@router.post("/connections", status_code=status.HTTP_201_CREATED)
def connection_create(
    body: ConnectionCreate, db: Session = Depends(get_db), actor: User = Depends(get_current_user),
):
    """保存通用 JSON HTTP 连接的不可变版本。"""
    return create_connections(db, body, actor)


@router.get("/connections/{connection_id}/versions")
def connection_versions(
    connection_id: int, db: Session = Depends(get_db), actor: User = Depends(get_current_user),
):
    """读取同名接口连接的历史版本，供新任务引用精确配置。"""
    row = db.get(AsrConnection, connection_id)
    if row is None:
        raise not_found("接口连接不存在")
    versions = [
        item for item in list_connections(db, row.project_id, actor, task_type=row.task_type)
        if item["name"] == row.name
    ]
    return {"items": versions}


@router.post("/connections/{connection_id}/checks", status_code=status.HTTP_202_ACCEPTED)
def connection_check(
    connection_id: int, body: ConnectionCheck, db: Session = Depends(get_db),
    actor: User = Depends(get_current_user),
):
    """排队执行单接口诊断并快速返回后台任务 ID。"""
    return create_connection_check(db, connection_id, body, actor)


@router.get("/parameter-sets")
def parameter_set_list(
    project_id: int = Query(gt=0), db: Session = Depends(get_db),
    actor: User = Depends(get_current_user),
):
    """列出项目待测参数方案的版本快照。"""
    return {"items": list_parameter_sets(db, project_id, actor)}


@router.post("/parameter-sets", status_code=status.HTTP_201_CREATED)
def parameter_set_create(
    body: ParameterSetCreate, db: Session = Depends(get_db), actor: User = Depends(get_current_user),
):
    """创建并校验待测参数方案新版本。"""
    return create_parameter_set(db, body, actor)


@router.get("/schedules")
def schedule_list(
    project_id: int = Query(gt=0), db: Session = Depends(get_db),
    actor: User = Depends(get_current_user),
):
    """列出一次性和每日夜间计划及下次触发时间。"""
    return {"items": list_schedules(db, project_id, actor)}


@router.post("/schedules", status_code=status.HTTP_201_CREATED)
def schedule_create(
    body: ScheduleCreate, db: Session = Depends(get_db), actor: User = Depends(get_current_user),
):
    """保存固定音频、连接与参数版本的一次性或每日计划。"""
    return create_schedule(db, body, actor)


@router.patch("/schedules/{schedule_id}")
def schedule_update(
    schedule_id: int, body: ScheduleUpdate,
    db: Session = Depends(get_db), actor: User = Depends(get_current_user),
):
    """暂停或恢复项目夜间计划，不改写其固定音频和参数快照。"""
    return update_schedule(db, schedule_id, enabled=body.enabled, actor=actor)


@router.get("/jobs")
def job_list(
    project_id: int = Query(gt=0), page: int = Query(1, ge=1),
    page_size: int = Query(20, ge=1, le=200), db: Session = Depends(get_db),
    actor: User = Depends(get_current_user),
):
    """分页读取批次状态和执行范围。"""
    return list_jobs(db, project_id, actor, page=page, page_size=page_size)


@router.post("/jobs", status_code=status.HTTP_202_ACCEPTED)
def job_create(body: JobCreate, db: Session = Depends(get_db), actor: User = Depends(get_current_user)):
    """持久化三方任务并立即返回批次 ID，页面无需等待长音频识别。"""
    return create_job(db, body, actor)


@router.get("/jobs/{job_id}")
def job_detail(job_id: int, summary_only: bool = False, include_text: bool = True, db: Session = Depends(get_db), actor: User = Depends(get_current_user)):
    """读取批次、模型独立状态、脱敏请求快照和已有对比入口。"""
    return get_job(db, job_id, actor, summary_only=summary_only, include_text=include_text)


@router.get("/jobs/{job_id}/audio-runs")
def job_audio_runs(job_id: int, page: int = Query(1, ge=1), page_size: int = Query(10, ge=1, le=100),
                   keyword: str | None = Query(default=None, max_length=200), status_filter: str | None = Query(default=None, alias="status", max_length=40),
                   db: Session = Depends(get_db), actor: User = Depends(get_current_user)):
    """分页读取批次音频分组及模型状态，不返回全文。"""
    return list_job_audio_runs(db, job_id, actor, page=page, page_size=page_size, keyword=keyword, status=status_filter)


@router.get("/jobs/{job_id}/runs")
def job_runs(job_id: int, db: Session = Depends(get_db), actor: User = Depends(get_current_user)):
    """读取批次内每个模型运行的提交、完成或待核实状态。"""
    return {"items": get_job(db, job_id, actor)["runs"]}


@router.post("/jobs/{job_id}/cancel")
def job_cancel(job_id: int, db: Session = Depends(get_db), actor: User = Depends(get_current_user)):
    """停止新提交；不宣称服务端已停止已提交的远端任务。"""
    return cancel_job(db, job_id, actor)


@router.post("/jobs/{job_id}/retry", status_code=status.HTTP_202_ACCEPTED)
def job_retry(
    job_id: int, idempotency_key: str | None = Header(default=None, alias="Idempotency-Key", max_length=128),
    db: Session = Depends(get_db), actor: User = Depends(get_current_user),
):
    """只重新提交明确失败项；保留其余运行结果和固定音频版本。"""
    return retry_job(db, job_id, actor, request_key=idempotency_key)


@router.post("/jobs/{job_id}/rerun", status_code=status.HTTP_202_ACCEPTED)
def job_rerun(
    job_id: int, idempotency_key: str | None = Header(default=None, alias="Idempotency-Key", max_length=128),
    db: Session = Depends(get_db), actor: User = Depends(get_current_user),
):
    """完整重跑已终态批次，仍使用原模型配置和固定音频版本。"""
    return rerun_job(db, job_id, actor, request_key=idempotency_key)


@router.get("/comparisons")
def comparison_list(
    project_id: int = Query(gt=0), page: int = Query(1, ge=1),
    page_size: int = Query(20, ge=1, le=200), db: Session = Depends(get_db),
    actor: User = Depends(get_current_user),
):
    """分页读取项目的对比版本摘要。"""
    return list_comparisons(db, project_id, actor, page=page, page_size=page_size)


@router.get("/comparisons/{comparison_id}")
def comparison_detail(
    comparison_id: int, db: Session = Depends(get_db), actor: User = Depends(get_current_user),
):
    """读取三方逐模型状态、文本差异口径和人工确认统计。"""
    return get_comparison(db, comparison_id, actor)


@router.get("/comparisons/{comparison_id}/blocks")
def comparison_blocks(
    comparison_id: int, page: int = Query(1, ge=1), page_size: int = Query(100, ge=1, le=200),
    filter: str = Query(default="ALL", pattern="^(ALL|DIFFERENCES|AGREEMENT_SAMPLE|PENDING_REVIEW|CONFIRMED)$"),
    db: Session = Depends(get_db), actor: User = Depends(get_current_user),
):
    """分页查看差异块、待确认项或单独的一致片段抽查样本。"""
    return list_blocks(db, comparison_id, actor, page=page, page_size=page_size, filter_name=filter)


@router.put("/comparisons/{comparison_id}/reviews/{block_id}")
def comparison_review(
    comparison_id: int, block_id: int, body: ReviewInput,
    db: Session = Depends(get_db), actor: User = Depends(get_current_user),
):
    """保存人工文本、暂无法确认状态或明确加入校对集的操作。"""
    block = db.get(AsrDiffBlock, block_id)
    if block is None or block.comparison_id != comparison_id:
        raise not_found("差异片段不存在")
    return review_block(db, block_id, body, actor)


@router.get("/comparisons/{comparison_id}/reviews/{block_id}/history")
def comparison_review_history(
    comparison_id: int, block_id: int,
    db: Session = Depends(get_db), actor: User = Depends(get_current_user),
):
    """读取差异片段的人工复核审计历史。"""
    return {"items": list_review_history(db, comparison_id, block_id, actor)}


@router.post("/comparisons/{comparison_id}/suggestion-jobs", status_code=status.HTTP_202_ACCEPTED)
def suggestion_create(
    comparison_id: int, model_config_id: int | None = Query(default=None, gt=0),
    db: Session = Depends(get_db), actor: User = Depends(get_current_user),
):
    """Queue an idempotent background suggestion request and return its durable job ID."""
    if model_config_id is None:
        from app.core.http.errors import bad_request
        raise bad_request("请选择一个已有文本模型")
    return create_suggestion_job(db, comparison_id, model_config_id, actor)


@router.get("/comparisons/{comparison_id}/suggestion-jobs")
def suggestion_job_list(
    comparison_id: int, db: Session = Depends(get_db), actor: User = Depends(get_current_user),
):
    """Read persistent suggestion job status and results for one comparison."""
    return list_suggestion_jobs(db, comparison_id, actor)


@router.post("/suggestion-jobs/{job_id}/retry", status_code=status.HTTP_202_ACCEPTED)
def suggestion_job_retry(
    job_id: int, db: Session = Depends(get_db), actor: User = Depends(get_current_user),
):
    """Explicitly retry a failed suggestion job with the same frozen input and idempotency key."""
    return retry_suggestion_job(db, job_id, actor)


@router.get("/comparisons/{comparison_id}/suggestions")
def suggestion_list(
    comparison_id: int, db: Session = Depends(get_db), actor: User = Depends(get_current_user),
):
    """读取当前对比版本关联的证据建议。"""
    return {"items": list_suggestions(db, comparison_id, actor)}


@router.get("/comparisons/{comparison_id}/exports")
def comparison_export(
    comparison_id: int, format: str = Query(default="json", pattern="^(json|csv)$"),
    db: Session = Depends(get_db), actor: User = Depends(get_current_user),
):
    """导出当前对比版本、人工确认与建议证据。"""
    content, media_type = export_comparison(db, comparison_id, actor, format_name=format)
    return Response(
        content=content, media_type=media_type,
        headers={"Content-Disposition": f'attachment; filename="asr-comparison-{comparison_id}.{format}"'},
    )


@router.get("/experiments")
def experiment_list(
    project_id: int = Query(gt=0), db: Session = Depends(get_db),
    actor: User = Depends(get_current_user),
):
    """列出基线和候选参数对比草稿及复跑状态。"""
    return {"items": list_experiments(db, project_id, actor)}


@router.post("/experiments", status_code=status.HTTP_201_CREATED)
def experiment_create(
    body: ExperimentCreate, db: Session = Depends(get_db), actor: User = Depends(get_current_user),
):
    """创建一个不覆盖基线参数的候选版本草稿。"""
    return create_experiment(db, body, actor)


@router.post("/experiments/{experiment_id}/run", status_code=status.HTTP_202_ACCEPTED)
def experiment_run(
    experiment_id: int, db: Session = Depends(get_db), actor: User = Depends(get_current_user),
):
    """为候选参数创建新的后台三方识别批次。"""
    return run_experiment(db, experiment_id, actor)


@router.get("/runtime-status")
def asr_runtime_status(db: Session = Depends(get_db), actor: User = Depends(get_current_user)):
    """查看最近 Worker 心跳和后台执行器在线事实。"""
    return runtime_status(db)


__all__ = ["router"]
