"""ASR 评测 HTTP 适配层。

本模块只解析路径、查询与 DTO 并调用领域 service；项目权限、事务、敏感信息保护和外部 IO 均在服务层完成。
所有路由由 app.main 统一挂载到 /api/v1。旧任务、对比与实验入口已退役，仅保留音频资产与 FunASR 调优。
"""

from __future__ import annotations

from fastapi import APIRouter, Depends, Header, Query, status
from sqlalchemy.orm import Session

from app.core.database.session import get_db
from app.core.http.errors import not_found
from app.core.models.identity import User
from app.core.security.auth import get_current_user
from app.features.asr_evaluation.models import AsrAudio
from app.features.asr_evaluation.schemas import AudioCreate, AudioImport, AudioUpdate
from app.features.asr_evaluation.funasr_schemas import (
    FunAsrBindingCreate, FunAsrBindingUpdate, FunAsrGroundTruthCreate,
    FunAsrNormalizePreview, FunAsrTuningCreate,
)
from app.features.asr_evaluation.services.assets_service import (
    check_audio, create_audio, import_audios, list_audios, update_audio,
)
from app.features.asr_evaluation.services.media_service import stream_audio
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
def funasr_ground_truth_create(
    audio_id: int, body: FunAsrGroundTruthCreate, db: Session = Depends(get_db),
    actor: User = Depends(get_current_user),
):
    """为当前音频内容版本创建标准答案新版本。"""
    return funasr_service.create_ground_truth(db, audio_id, body, actor)


@router.get("/funasr/models")
def funasr_models(project_id: int = Query(gt=0), db: Session = Depends(get_db), actor: User = Depends(get_current_user)):
    """返回当前成员可用于分析报告的文本模型。"""
    return funasr_service.get_models_for_project(db, project_id, actor)


@router.get("/funasr/sessions")
def funasr_session_list(project_id: int = Query(gt=0), db: Session = Depends(get_db), actor: User = Depends(get_current_user)):
    return funasr_service.list_tuning_sessions(db, project_id, actor)


@router.post("/funasr/sessions", status_code=status.HTTP_202_ACCEPTED)
def funasr_session_create(body: FunAsrTuningCreate, db: Session = Depends(get_db), actor: User = Depends(get_current_user)):
    """创建单轮基线或自动多轮调优会话；实际识别由后台 Worker 执行。"""
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
    availability: str | None = Query(default=None, max_length=30),
    ground_truth_status: str | None = Query(default=None, max_length=10),
    actor: User = Depends(get_current_user),
):
    """分页列出项目内已登记音频及链接可达性状态。"""
    return list_audios(
        db, project_id, actor, page=page, page_size=page_size, keyword=keyword,
        availability=availability, ground_truth_status=ground_truth_status,
    )


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