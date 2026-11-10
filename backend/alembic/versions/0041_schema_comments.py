"""Document all database tables and columns; clarify string-backed enums."""

from __future__ import annotations

import re

from alembic import op
from sqlalchemy import inspect as sa_inspect

from app.core.database.base import Base


revision = "0041"
down_revision = "0040"
branch_labels = None
depends_on = None


# These fields are constrained by request schemas or the corresponding state
# machine. PostgreSQL stores them as VARCHAR, so their contract belongs in the
# column comment instead of a native PostgreSQL ENUM type.
ENUM_OPTIONS: dict[str, tuple[str, ...]] = {
    "mcp_server.auth_type": ("none", "bearer"),
    "mcp_server.connection_status": ("unknown", "connected", "error"),
    "asr_audio.availability": ("UNKNOWN", "AVAILABLE", "PLATFORM_DENIED", "UNREACHABLE"),
    "asr_connection.role": ("TEST", "REFERENCE"),
    "asr_connection.task_type": ("TRANSCRIPTION", "DIARIZATION"),
    "asr_schedule.schedule_type": ("ONCE", "DAILY"),
    "asr_job.status": ("QUEUED", "RUNNING", "COMPLETED", "PARTIAL_FAILED", "FAILED", "CANCELLED", "RECONCILIATION_REQUIRED"),
    "asr_model_run.role": ("TEST", "REFERENCE"),
    "asr_model_run.status": ("PENDING", "SUBMITTING", "REMOTE_RUNNING", "SUCCEEDED", "FAILED", "CANCELLED", "RECONCILIATION_REQUIRED"),
    "asr_comparison.status": ("COMPLETE", "INCOMPLETE"),
    "asr_diff_block.timing_role": ("TEST", "REFERENCE_A", "REFERENCE_B"),
    "asr_diff_block.review_status": ("UNREVIEWED", "CONFIRMED", "UNRESOLVED"),
    "asr_review_audit.review_status": ("CONFIRMED", "UNRESOLVED"),
    "asr_evaluation_artifact.kind": ("RESPONSE_SUBMISSION", "RESPONSE_SYNC", "RESPONSE_POLL_FINAL", "REVIEW_INPUT_MD", "REVIEW_REPLY_JSON", "REVIEW_SOURCE_MD", "REVIEW_SOURCE_JSON", "REVIEW_REPORT_JSON", "SNAPSHOT_JSON", "MARKDOWN"),
    "asr_evaluation_artifact.status": ("PENDING", "READY", "FAILED"),
    "asr_experiment.status": ("DRAFT", "RUNNING", "COMPLETED", "FAILED"),
    "asr_fusion_version.status": ("UNALIGNED", "COMPLETE"),
    "asr_content_review_job.review_type": ("SINGLE", "TRIPLET", "AB"),
    "asr_content_review_job.status": ("QUEUED", "RUNNING", "SUCCEEDED", "FAILED", "CANCELLED", "RECONCILIATION_REQUIRED"),
    "asr_content_review_job.coverage_status": ("UNAVAILABLE", "PARTIAL", "COMPLETE"),
    "asr_content_review_chunk.status": ("QUEUED", "RUNNING", "SUCCEEDED", "FAILED", "CANCELLED", "RECONCILIATION_REQUIRED"),
    "asr_processing_run.task_type": ("DIARIZATION", "MEDIA_ANALYSIS"),
    "asr_processing_run.status": ("PENDING", "SUBMITTING", "REMOTE_RUNNING", "SUCCEEDED", "FAILED", "CANCELLED", "RECONCILIATION_REQUIRED"),
    "asr_media_analysis.status": ("AVAILABLE", "PARTIAL", "UNAVAILABLE"),
    "asr_speaker_assignment.assignment_status": ("ASSIGNED", "UNKNOWN", "UNALIGNED", "MIXED", "OVERLAPPED"),
    "asr_speaker_assignment.review_status": ("UNREVIEWED", "CONFIRMED", "UNRESOLVED"),
    "asr_speaker_review_audit.review_status": ("CONFIRMED", "UNRESOLVED"),
    "asr_schedule.last_trigger_status": ("MISSED", "SKIPPED_OVERLAP", "AUTHORIZATION_REVOKED", "QUEUED", "ALREADY_QUEUED", "AUTHORIZATION_OR_CONFIGURATION_ERROR"),
    "asr_suggestion.status": ("DRAFT",),
    "asr_suggestion_job.status": ("QUEUED", "RUNNING", "SUCCEEDED", "FAILED", "RECONCILIATION_REQUIRED"),
    "asr_tuning_session.mode": ("ANALYZE", "AUTO_TUNE"),
    "asr_tuning_session.status": ("QUEUED", "WAITING_WINDOW", "RUNNING", "PAUSE_REQUESTED", "PAUSED", "STOP_REQUESTED", "STOPPED", "COMPLETED", "FAILED", "RECONCILIATION_REQUIRED"),
    "asr_tuning_round.status": ("QUEUED", "RUNNING", "ANALYZING", "PARTIAL", "COMPLETED", "FAILED", "RECONCILIATION_REQUIRED"),
    "asr_tuning_item.status": ("PENDING", "SUBMITTING", "SUCCEEDED", "FAILED", "RECONCILIATION_REQUIRED"),
    "asr_tuning_item.review_status": ("PENDING", "ANALYZING", "SUCCEEDED", "FAILED", "RECONCILIATION_REQUIRED"),
    "model_resource.category": ("TEXT_GENERATION", "ASR", "DIARIZATION"),
    "model_resource.visibility": ("PLATFORM", "PROJECT"),
    "model_resource.status": ("ACTIVE", "DISABLED", "ARCHIVED"),
    "model_default_binding.category": ("TEXT_GENERATION", "ASR", "DIARIZATION"),
    "model_task_slot.task_kind": ("ASR_JOB", "ASR_SCHEDULE", "ASR_PROCESSING_RUN"),
    "model_task_slot.slot": ("TEST", "REFERENCE_A", "REFERENCE_B", "DIARIZATION"),
    "model_validation_run.status": ("QUEUED", "RUNNING", "SUCCEEDED", "FAILED"),
    "task.task_mode": ("TEST_EXECUTION", "WEB_AUTHORING"),
    "task.status": ("QUEUED", "RUNNING", "WAITING_DEPENDENCY", "WAITING_CONFIRMATION", "PAUSE_REQUESTED", "PAUSED", "CANCEL_REQUESTED", "CANCELLED", "SUCCEEDED", "SUCCEEDED_WITH_ISSUES", "FAILED", "SUPERSEDED", "RECONCILIATION_REQUIRED"),
    "task_run.status": ("QUEUED", "RUNNING", "WAITING_DEPENDENCY", "WAITING_CONFIRMATION", "PAUSE_REQUESTED", "PAUSED", "CANCEL_REQUESTED", "CANCELLED", "SUCCEEDED", "SUCCEEDED_WITH_ISSUES", "FAILED", "SUPERSEDED", "RECONCILIATION_REQUIRED"),
    "task_agent_instance.role": ("MAIN", "PLANNER", "API_WORKER", "SECURITY_WORKER", "UI_WORKER", "REVIEWER", "REPORT_AGENT", "SUB_AGENT"),
    "task_agent_instance.status": ("READY", "QUEUED", "RUNNING", "ACTIVE", "PROCESSING", "WAITING_DEPENDENCY", "WAITING_APPROVAL", "PAUSED", "COMPLETED", "FAILED", "CANCELLED", "NEEDS_RECONCILIATION"),
    "task_attempt.status": ("RUNNING", "SUCCEEDED", "FAILED", "INTERRUPTED", "NEEDS_RECONCILIATION"),
    "task_command.command_type": ("APPROVE_PLAN", "PAUSE", "RESUME", "CANCEL", "RETRY"),
    "task_command.status": ("ACCEPTED", "COMPLETED"),
    "task_message.sender_type": ("USER", "AGENT", "SYSTEM"),
    "task_message.message_type": ("TEXT", "GOAL_UPDATE", "REQUIREMENT", "WEB_TURN"),
    "task_message.status": ("RECEIVED", "PROCESSING", "PROCESSED", "FAILED"),
    "task_plan.status": ("PROPOSED", "ACCEPTED"),
    "task_resource_ref.direction": ("INPUT", "OUTPUT"),
    "task_work_item.kind": ("PLAN", "CHAT", "REPORT", "REVIEW", "FINALIZE", "SECURITY_SCAN", "EXECUTE_API", "EXECUTE_WEB", "EXECUTE_SECURITY", "EXECUTE_WEB_AUTHORING"),
    "task_work_item.status": ("PENDING", "RUNNING", "SUCCEEDED", "FAILED", "CANCELLED", "SKIPPED"),
    "task_tool_invocation.status": ("STARTED", "SUCCEEDED", "FAILED", "NEEDS_RECONCILIATION"),
    "web_agent_session.status": ("ACTIVE", "PROCESSING", "PAUSED", "CLOSED", "COMPLETED", "FAILED", "CANCELLED"),
    "web_agent_step.status": ("PROPOSED", "ACCEPTED", "REJECTED", "FAILED"),
}


_MEANINGS = {
    "none": "不使用鉴权", "bearer": "使用 Bearer Token 鉴权",
    "UNKNOWN": "未知或尚未检查", "AVAILABLE": "可访问", "PLATFORM_DENIED": "平台侧出站访问策略拒绝", "UNREACHABLE": "目标链接不可达",
    "TEST": "待测对象/测试模型", "REFERENCE": "参考模型", "REFERENCE_A": "第一参考模型", "REFERENCE_B": "第二参考模型",
    "TRANSCRIPTION": "语音转写", "DIARIZATION": "说话人分离", "MEDIA_ANALYSIS": "音频媒体分析",
    "SINGLE": "单模型单运行内容评审", "TRIPLET": "测试模型与两个参考模型的三方对比评审", "AB": "基线与候选模型的 A/B 对比评审",
    "ONCE": "单次执行", "DAILY": "每日重复执行", "TEXT_GENERATION": "文本生成模型", "ASR": "语音识别模型", "PLATFORM": "平台级共享", "PROJECT": "项目级可见",
    "QUEUED": "排队等待执行", "PENDING": "待处理", "RUNNING": "执行中", "SUBMITTING": "正在提交", "REMOTE_RUNNING": "远端执行中",
    "SUCCEEDED": "成功完成", "SUCCESS": "成功", "COMPLETED": "已完成", "COMPLETE": "完整/已完成", "READY": "已就绪",
    "FAILED": "失败", "ERROR": "发生错误", "PARTIAL_FAILED": "部分失败", "PARTIAL": "部分完成",
    "CANCELLED": "已取消", "DRAFT": "草稿", "ACTIVE": "启用/活动中", "DISABLED": "已停用", "ARCHIVED": "已归档",
    "RECONCILIATION_REQUIRED": "需要人工核对外部执行结果", "UNALIGNED": "尚未完成时间对齐", "UNREVIEWED": "尚未人工复核",
    "CONFIRMED": "已确认", "UNRESOLVED": "未解决/待进一步确认", "UNAVAILABLE": "不可用或无覆盖数据", "ANALYZING": "分析中",
    "ACCEPTED": "已接受", "APPROVED": "已批准", "REJECTED": "已拒绝", "APPLIED": "已应用", "PROPOSED": "待审核提议",
    "WAITING_WINDOW": "等待允许的运行时间窗口", "WAITING_CONFIRMATION": "等待人工确认", "WAITING_DEPENDENCY": "等待前置依赖",
    "MISSED": "计划时间已错过", "SKIPPED_OVERLAP": "因已有重叠任务而跳过", "AUTHORIZATION_REVOKED": "出站访问授权已撤销",
    "ALREADY_QUEUED": "本次计划任务已在队列中", "AUTHORIZATION_OR_CONFIGURATION_ERROR": "授权或配置校验失败",
    "PAUSE_REQUESTED": "已请求暂停", "PAUSED": "已暂停", "STOP_REQUESTED": "已请求停止", "STOPPED": "已停止",
    "CANCEL_REQUESTED": "已请求取消", "SUCCEEDED_WITH_ISSUES": "已完成但存在问题", "SUPERSEDED": "已被更新版本替代",
    "RECEIVED": "已接收", "PROCESSING": "处理中", "PROCESSED": "已处理", "STARTED": "已开始", "INTERRUPTED": "执行中断",
    "READY": "就绪", "WAITING_APPROVAL": "等待审批", "NEEDS_RECONCILIATION": "需要核对后再继续", "SKIPPED": "已跳过",
    "ASSIGNED": "已匹配到说话人", "UNASSIGNED": "未匹配说话人", "MIXED": "包含多个说话人", "OVERLAPPING": "说话人时间区间重叠",
    "ANALYZE": "仅独立分析，不修改参数", "AUTO_TUNE": "执行批量自动调优",
    "PLANNER": "规划智能体", "API_WORKER": "接口测试执行智能体", "WEB_WORKER": "网页测试执行智能体", "SECURITY_WORKER": "安全测试执行智能体", "UI_WORKER": "网页编写智能体",
    "MAIN": "主智能体", "REVIEWER": "审阅智能体", "REPORT_AGENT": "报告智能体", "SUB_AGENT": "子智能体",
    "TEST_EXECUTION": "测试执行任务", "WEB_AUTHORING": "网页编写任务", "APPROVE_PLAN": "批准执行计划", "PAUSE": "暂停任务", "RESUME": "恢复任务", "CANCEL": "取消任务", "RETRY": "重试失败步骤",
    "GOAL_UPDATE": "更新任务目标", "REQUIREMENT": "补充任务要求", "INPUT": "输入资源", "OUTPUT": "输出资源",
    "SCREENSHOT": "页面截图", "DOM": "页面结构快照", "TRACE": "执行轨迹", "DOWNLOAD": "下载文件",
    "REQUEST": "请求内容", "RESPONSE": "响应内容", "REPORT": "报告产物",
    "RESPONSE_SUBMISSION": "提交响应原文", "RESPONSE_SYNC": "同步响应原文", "RESPONSE_POLL_FINAL": "轮询最终响应原文",
    "REVIEW_INPUT_MD": "评审输入 Markdown", "REVIEW_REPLY_JSON": "评审回复 JSON", "REVIEW_SOURCE_MD": "评审来源 Markdown",
    "REVIEW_SOURCE_JSON": "评审来源 JSON", "REVIEW_REPORT_JSON": "评审报告 JSON", "SNAPSHOT_JSON": "评测快照 JSON", "MARKDOWN": "评测 Markdown 文档",
    "OVERLAPPED": "存在说话人时间区间重叠", "UNALIGNED": "缺少可用时间戳，无法对齐", "UNKNOWN": "无法确定说话人归属",
    "PARTIAL": "部分分析结果可用", "UNAVAILABLE": "分析结果不可用", "MAIN": "主智能体",
    "REVIEWER": "评审智能体", "REPORT_AGENT": "报告智能体", "SUB_AGENT": "子智能体", "CLOSED": "已关闭",
    "ASR_JOB": "批量 ASR 评测任务", "ASR_SCHEDULE": "ASR 定时计划", "ASR_PROCESSING_RUN": "ASR 说话人/媒体处理运行",
    "REVIEW": "结果评审工作项", "SECURITY_SCAN": "安全扫描工作项",
}

_TOKEN_MEANINGS = {
    "TEXT": "文本", "GENERATION": "生成", "SPEAKER": "说话人", "PLATFORM": "平台", "PROJECT": "项目",
    "TEST": "测试", "REFERENCE": "参考", "A": "A", "B": "B", "API": "接口", "WEB": "网页",
    "SECURITY": "安全", "AUTHORING": "编写", "EXECUTE": "执行", "PLAN": "计划", "CHAT": "对话",
    "FINALIZE": "收尾", "GOAL": "目标", "UPDATE": "更新", "REQUIRED": "必需", "CHANGED": "变更",
    "PARAM": "参数", "CONFIRMATION": "确认", "DEPENDENCY": "依赖", "WINDOW": "时间窗口", "PAUSE": "暂停",
    "STOP": "停止", "CANCEL": "取消", "REQUESTED": "已请求", "WAITING": "等待", "SUCCEEDED": "成功",
    "WITH": "并且", "ISSUES": "问题", "PARTIAL": "部分", "FAILED": "失败", "RECONCILIATION": "核对",
    "REQUIRED": "需要", "UNREVIEWED": "未复核", "UNRESOLVED": "未解决", "CONFIRMED": "已确认",
    "AVAILABLE": "可用", "UNAVAILABLE": "不可用", "DIARIZATION": "说话人分离", "TRANSCRIPTION": "语音转写",
    "ONCE": "单次", "DAILY": "每日", "NONE": "无", "BEARER": "Bearer", "ERROR": "错误",
}

_FIELD_MEANINGS = {
    "id": "本表记录的唯一主键", "project_id": "所属项目 ID", "organization_id": "所属组织 ID",
    "created_by": "创建该记录的用户 ID", "updated_by": "最后更新该记录的用户 ID",
    "created_at": "记录创建时间", "updated_at": "记录最后更新时间", "deleted_at": "软删除时间",
    "status": "业务状态", "name": "名称", "display_name": "展示名称", "title": "标题", "description": "说明文本",
    "enabled": "是否启用", "is_active": "是否为当前生效记录", "version": "版本号", "revision": "修订号",
    "config": "配置", "config_json": "JSON 格式配置", "config_snapshot": "创建时配置快照",
    "request_json": "请求 JSON 数据", "response_json": "响应 JSON 数据", "result_json": "结果 JSON 数据",
    "parameters": "参数集合", "parameter_hash": "参数集合的 SHA-256 摘要", "payload_json": "JSON 格式负载",
    "metadata": "扩展元数据", "scope": "作用范围", "role": "角色", "type": "类型", "kind": "类别",
    "mode": "运行模式", "category": "分类", "visibility": "可见范围", "direction": "数据方向",
    "url_display": "脱敏后展示的 URL", "url_ciphertext": "加密保存的 URL 密文", "secret_ciphertext": "加密保存的凭据密文",
    "endpoint_display": "脱敏后展示的服务地址", "endpoint_ciphertext": "加密保存的服务地址密文",
    "error_message": "错误详情", "failure_reason": "失败原因", "stop_reason": "停止原因",
    "started_at": "开始时间", "finished_at": "结束时间", "expires_at": "过期时间", "lease_expires_at": "租约到期时间",
    "attempts": "已尝试次数", "retry_count": "重试次数", "duration_ms": "耗时（毫秒）", "duration_seconds": "时长（秒）",
    "count": "记录数量", "ordinal": "顺序编号", "sort_order": "排序序号", "version_num": "Alembic 迁移版本标识",
    "audio_ids": "音频记录 ID 列表", "connection_ids": "连接记录 ID 列表", "tags": "标签列表",
    "availability": "音频链接可用性检查状态",
}

_TABLE_DESCRIPTIONS = {
    "asr_api_binding": "FunASR 调优使用的项目 API 绑定、执行密文和响应字段映射配置。",
    "asr_ground_truth_version": "与固定音频版本关联的标准答案原文、字段映射快照和规范化结果版本。",
    "asr_tuning_session": "FunASR 独立分析或批量自动调优会话、调用预算、运行窗口和 Worker 租约。",
    "asr_tuning_round": "调优会话中按顺序执行的参数候选、评测指标及分析报告。",
    "asr_tuning_item": "调优轮次内单条音频和标准答案版本的执行响应、评测与复核状态。",
}

_COLUMN_TOKENS = {
    "id": "ID", "project": "项目", "organization": "组织", "org": "组织", "user": "用户", "owner": "所有者",
    "audio": "音频", "version": "版本", "content": "内容", "fingerprint": "指纹", "availability": "可用性",
    "connection": "连接", "parameter": "参数", "set": "方案", "schedule": "计划", "job": "任务", "run": "运行",
    "model": "模型", "role": "角色", "task": "任务", "type": "类型", "kind": "类别", "mode": "模式",
    "status": "状态", "category": "分类", "visibility": "可见范围", "slot": "槽位", "scope": "范围",
    "review": "复核", "reviewer": "复核人", "assignment": "归属", "speaker": "说话人", "fusion": "融合",
    "result": "结果", "artifact": "产物", "source": "来源", "target": "目标", "direction": "方向",
    "input": "输入", "output": "输出", "request": "请求", "response": "响应", "payload": "负载",
    "config": "配置", "snapshot": "快照", "json": "JSON", "raw": "原始", "normalized": "规范化",
    "created": "创建", "updated": "更新", "deleted": "删除", "started": "开始", "finished": "结束",
    "at": "时间", "time": "时间", "date": "日期", "name": "名称", "display": "展示", "title": "标题",
    "description": "说明", "message": "消息", "text": "文本", "content": "内容", "value": "值",
    "count": "数量", "total": "总数", "limit": "上限", "max": "最大", "min": "最小", "attempts": "尝试次数",
    "duration": "时长", "seconds": "秒", "ms": "毫秒", "hash": "摘要", "sha256": "SHA-256", "key": "键",
    "url": "URL", "endpoint": "服务地址", "secret": "凭据", "token": "令牌", "ciphertext": "密文",
    "enabled": "启用", "active": "生效", "cancel": "取消", "requested": "请求", "error": "错误",
    "failure": "失败", "reason": "原因", "version": "版本", "revision": "修订", "ordinal": "顺序",
    "timezone": "时区", "local": "本地", "time": "时间", "next": "下次", "last": "最近",
    "provider": "服务提供方", "environment": "环境", "organization": "组织", "member": "成员",
    "case": "用例", "execution": "执行", "plan": "计划", "step": "步骤", "agent": "智能体",
    "tool": "工具", "event": "事件", "command": "命令", "message": "消息", "sender": "发送方",
    "resource": "资源", "work": "工作", "attempt": "尝试", "validation": "验证", "diagnostic": "诊断",
    "review_status": "复核状态", "assignment_status": "分配状态", "task_mode": "任务模式", "task_type": "任务类型",
    "schedule_type": "计划类型", "auth_type": "鉴权方式", "connection_status": "连接状态", "source_type": "来源类型",
    "created_by": "创建用户 ID", "updated_by": "更新用户 ID", "project_id": "项目 ID", "organization_id": "组织 ID",
}


def _clean_doc(value: str | None) -> str | None:
    if not value:
        return None
    return " ".join(part.strip() for part in value.splitlines() if part.strip())


def _humanize(name: str) -> str:
    if name in _COLUMN_TOKENS:
        return _COLUMN_TOKENS[name]
    parts = name.split("_")
    return "".join(_COLUMN_TOKENS.get(part, part) for part in parts)


def _fallback_column_comment(table_name: str, column, table_description: str) -> str:
    if column.primary_key:
        return "本表记录的唯一主键，用于稳定引用该记录。"
    if column.foreign_keys:
        target = next(iter(column.foreign_keys)).target_fullname
        target_table = target.split(".", 1)[0]
        return f"关联 {target_table} 表记录的外键 ID；用于定位对应业务对象。"
    if column.name in _FIELD_MEANINGS:
        return f"{_FIELD_MEANINGS[column.name]}；用于{table_description}。"
    name = _humanize(column.name)
    type_name = column.type.__class__.__name__.lower()
    if column.name.endswith("_ciphertext"):
        meaning = f"加密保存的{name.removesuffix('密文')}密文"
    elif column.name.endswith("_json") or type_name == "json":
        meaning = f"JSON 格式的{name}"
    elif column.name.endswith("_at") or type_name in {"datetime", "date"}:
        meaning = f"{name}时间"
    elif column.name.startswith("is_") or type_name == "boolean":
        meaning = f"{name}布尔标记"
    elif column.name.endswith("_id"):
        meaning = f"{name}关联标识符"
    else:
        value_kind = {"integer": "整数", "float": "数值", "numeric": "数值", "boolean": "布尔值", "text": "文本", "string": "字符串"}.get(type_name, "数据")
        meaning = f"{name}{value_kind}"
    return f"字段 {column.name}（{meaning}）；用于{table_description}。"


def _code_meaning(code: str, table_name: str = "", column_name: str = "") -> str:
    if code == "UNKNOWN" and table_name == "asr_audio" and column_name == "availability":
        return "尚未检查或暂无可用性检查结果"
    if code == "UNKNOWN" and table_name == "asr_speaker_assignment" and column_name == "assignment_status":
        return "无法确定说话人归属"
    if code in _MEANINGS:
        return _MEANINGS[code]
    words = [word for word in code.replace("*", "通配").split("_") if word]
    translated = "、".join(_TOKEN_MEANINGS.get(word, word.lower()) for word in words)
    return f"业务状态/类别：{translated}"


def _comment_codes(comment: str) -> tuple[str, ...]:
    # Only slash-delimited code groups are considered. This avoids treating
    # prose, URLs, MIME types, or ordinary strings as enumerations.
    groups = re.findall(r"(?<![\w/])([A-Za-z][A-Za-z0-9_*]*(?:\s*/\s*[A-Za-z][A-Za-z0-9_*]*)+)(?![\w/])", comment)
    for group in groups:
        values = tuple(value.strip() for value in re.split(r"\s*/\s*", group))
        if values and all(value.upper() in _MEANINGS or value.lower() in _MEANINGS or value.upper().replace("*", "") for value in values):
            return values
    return ()


def _with_enum_meanings(table_name: str, column_name: str, comment: str) -> str:
    values = ENUM_OPTIONS.get(f"{table_name}.{column_name}") or _comment_codes(comment)
    if not values:
        return comment
    rendered = "；".join(f"{value}={_code_meaning(value, table_name, column_name)}" for value in values)
    if "枚举取值含义：" in comment:
        return comment
    return f"{comment}；枚举取值含义：{rendered}。"


def upgrade() -> None:
    bind = op.get_bind()
    inspector = sa_inspect(bind)
    database_tables = set(inspector.get_table_names(schema="public"))
    mapped_classes = {mapper.local_table.name: mapper.class_ for mapper in Base.registry.mappers}

    for table_name in sorted(database_tables):
        table_comment = inspector.get_table_comment(table_name, schema="public").get("text")
        model_table = Base.metadata.tables.get(table_name)
        model_class = mapped_classes.get(table_name)
        if table_name == "alembic_version":
            table_comment = table_comment or "Alembic 数据库迁移版本状态表；记录当前已应用的迁移版本。"
        elif table_name == "td_sandbox_task":
            table_comment = table_comment or "测试数据中心专用沙箱任务夹具表；供数据库 Provider 白名单与 CRUD 测试使用，不存放平台业务任务。"
        elif not table_comment:
            table_comment = (model_table.comment if model_table is not None else None) or _TABLE_DESCRIPTIONS.get(table_name) or _clean_doc(
                model_class.__dict__.get("__doc__") if model_class is not None else None
            ) or f"{table_name}：项目数据库业务记录表。"
        if table_comment:
            op.create_table_comment(table_name, table_comment, schema="public", existing_comment=inspector.get_table_comment(table_name, schema="public").get("text"))

        db_columns = {column["name"]: column for column in inspector.get_columns(table_name, schema="public")}
        model_columns = {column.name: column for column in model_table.columns} if model_table is not None else {}
        for column_name, db_column in db_columns.items():
            existing_comment = db_column.get("comment")
            model_column = model_columns.get(column_name)
            if table_name == "alembic_version" and column_name == "version_num":
                comment = existing_comment or "当前数据库已应用的 Alembic 迁移 revision 标识。"
            elif table_name == "td_sandbox_task":
                comment = existing_comment or {
                    "id": "沙箱测试记录的唯一主键。",
                    "status": "测试夹具状态样例；测试自行写入（常用 PENDING），该列没有数据库枚举约束。",
                    "name": "测试夹具记录名称。",
                    "payload_json": "测试夹具使用的 JSON 负载。",
                    "created_at": "测试记录创建时间。",
                }.get(column_name, f"测试沙箱记录字段 {column_name}。")
            elif existing_comment:
                comment = existing_comment
            elif model_column is not None and model_column.comment:
                comment = model_column.comment
            else:
                description = _TABLE_DESCRIPTIONS.get(table_name) or _clean_doc(
                    model_class.__dict__.get("__doc__") if model_class is not None else None
                ) or table_name
                source_column = model_column if model_column is not None else _ColumnProxy(column_name, db_column)
                comment = _fallback_column_comment(table_name, source_column, description)
            if table_name == "asr_content_review_chunk" and column_name == "scope":
                comment = "JSON 作用域配置（非枚举）；记录当前评审块覆盖的音频、文本范围及筛选条件。"
            comment = comment.replace("。。", "。")
            comment = _with_enum_meanings(table_name, column_name, comment)
            op.alter_column(table_name, column_name, schema="public", comment=comment, existing_comment=existing_comment)


class _ColumnProxy:
    """Small inspector-column adapter for database-only columns."""

    def __init__(self, name: str, column: dict):
        self.name = name
        self.primary_key = False
        self.foreign_keys = set()
        self.type = column["type"]


def downgrade() -> None:
    # Schema comments are additive documentation and intentionally remain on
    # downgrade; removing them would discard pre-existing database metadata.
    pass
