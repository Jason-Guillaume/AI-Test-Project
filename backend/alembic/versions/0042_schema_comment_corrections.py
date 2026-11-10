"""Correct table context and enum meanings in the schema documentation."""

from alembic import op
from sqlalchemy import inspect


revision = "0042"
down_revision = "0041"
branch_labels = None
depends_on = None


TABLE_COMMENTS = {
    "asr_api_binding": "FunASR 调优使用的项目 API 绑定、执行密文和响应字段映射配置。",
    "asr_ground_truth_version": "与固定音频版本关联的标准答案原文、字段映射快照和规范化结果版本。",
    "asr_tuning_session": "FunASR 独立分析或批量自动调优会话、调用预算、运行窗口和 Worker 租约。",
    "asr_tuning_round": "调优会话中按顺序执行的参数候选、评测指标及分析报告。",
    "asr_tuning_item": "调优轮次内单条音频和标准答案版本的执行响应、评测与复核状态。",
}


ENUM_COMMENTS = {
    ("asr_audio", "availability"): (
        "音频链接可用性检查状态。枚举取值含义：UNKNOWN=尚未检查或暂无检查结果；"
        "AVAILABLE=可访问；PLATFORM_DENIED=平台侧出站访问策略拒绝；UNREACHABLE=目标链接不可达。"
    ),
    ("asr_schedule", "last_trigger_status"): (
        "最近一次计划触发结果。枚举取值含义：MISSED=计划时间已错过；SKIPPED_OVERLAP=因已有重叠任务而跳过；"
        "AUTHORIZATION_REVOKED=出站访问授权已撤销；QUEUED=任务已加入队列；ALREADY_QUEUED=本次任务已在队列中；"
        "AUTHORIZATION_OR_CONFIGURATION_ERROR=授权或配置校验失败。"
    ),
    ("asr_content_review_job", "review_type"): (
        "内容评审来源类型。枚举取值含义：SINGLE=单模型单运行内容评审；"
        "TRIPLET=测试模型与两个参考模型的三方对比评审；AB=基线与候选模型的 A/B 对比评审。"
    ),
    ("asr_tuning_session", "status"): (
        "调优会话状态。枚举取值含义：QUEUED=排队等待执行；WAITING_WINDOW=等待允许的运行时间窗口；"
        "RUNNING=执行中；PAUSE_REQUESTED=已请求暂停；PAUSED=已暂停；STOP_REQUESTED=已请求停止；"
        "STOPPED=已停止；COMPLETED=已完成；FAILED=失败；RECONCILIATION_REQUIRED=需人工核对外部调用结果。"
    ),
    ("asr_tuning_round", "status"): (
        "调优轮次状态。枚举取值含义：QUEUED=排队等待执行；RUNNING=执行中；ANALYZING=分析中；"
        "PARTIAL=本轮存在部分失败或不完整结果；COMPLETED=本轮执行及分析完成；FAILED=本轮失败；"
        "RECONCILIATION_REQUIRED=需要人工核对外部执行结果。"
    ),
    ("model_task_slot", "task_kind"): (
        "模型任务槽位所绑定的任务类别。枚举取值含义：ASR_JOB=批量 ASR 评测任务；"
        "ASR_SCHEDULE=ASR 定时计划；ASR_PROCESSING_RUN=ASR 说话人或媒体处理运行。"
    ),
    ("task", "status"): (
        "任务当前状态，与最新运行状态同步。枚举取值含义：QUEUED=排队等待执行；RUNNING=执行中；"
        "WAITING_DEPENDENCY=等待前置依赖；WAITING_CONFIRMATION=等待人工确认；PAUSE_REQUESTED=已请求暂停；"
        "PAUSED=已暂停；CANCEL_REQUESTED=已请求取消；CANCELLED=已取消；SUCCEEDED=成功完成；"
        "SUCCEEDED_WITH_ISSUES=已完成但存在问题；FAILED=失败；SUPERSEDED=已被新运行替代；"
        "RECONCILIATION_REQUIRED=需要人工核对执行结果。"
    ),
    ("task_command", "status"): (
        "任务命令处理状态。枚举取值含义：ACCEPTED=命令已接受；COMPLETED=命令处理完成。"
    ),
    ("task_plan", "status"): (
        "任务计划审核状态。枚举取值含义：PROPOSED=待确认的计划；ACCEPTED=已批准执行。"
    ),
    ("task_work_item", "kind"): (
        "工作项处理器类别。枚举取值含义：PLAN=生成计划；CHAT=处理对话；REPORT=生成报告；"
        "REVIEW=评审结果；FINALIZE=整理任务结果；SECURITY_SCAN=执行安全扫描；EXECUTE_API=执行接口测试；"
        "EXECUTE_WEB=执行网页测试；EXECUTE_SECURITY=执行安全评估；EXECUTE_WEB_AUTHORING=执行网页编写。"
    ),
}


def upgrade() -> None:
    bind = op.get_bind()
    inspector = inspect(bind)
    for table, comment in TABLE_COMMENTS.items():
        existing = inspector.get_table_comment(table, schema="public").get("text")
        op.create_table_comment(table, comment, schema="public", existing_comment=existing)

    table_names = set(inspector.get_table_names(schema="public"))
    wrong_context = "所有 ORM 模型共用的唯一声明式基类与 metadata。。"
    for table in table_names:
        for column in inspector.get_columns(table, schema="public"):
            old_comment = column.get("comment")
            if not old_comment:
                continue
            new_comment = old_comment
            if table in TABLE_COMMENTS and wrong_context in new_comment:
                new_comment = new_comment.replace(wrong_context, TABLE_COMMENTS[table])
            new_comment = new_comment.replace("。。", "。")
            new_comment = new_comment.replace("。；枚举取值含义：", "；枚举取值含义：")
            if new_comment != old_comment:
                op.alter_column(table, column["name"], schema="public", comment=new_comment, existing_comment=old_comment)

    for (table, column), comment in ENUM_COMMENTS.items():
        existing = next(
            item.get("comment")
            for item in inspector.get_columns(table, schema="public")
            if item["name"] == column
        )
        op.alter_column(table, column, schema="public", comment=comment, existing_comment=existing)


def downgrade() -> None:
    # Documentation corrections are intentionally retained on downgrade.
    pass
