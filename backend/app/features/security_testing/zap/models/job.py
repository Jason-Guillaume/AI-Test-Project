"""security_scan_job 与 security_scan_event：扫描任务与过程事件。"""

from __future__ import annotations

from sqlalchemy import (
    BigInteger,
    Boolean,
    Column,
    DateTime,
    ForeignKey,
    Index,
    Integer,
    JSON,
    String,
)
from sqlalchemy.sql import func, text

from app.shared.database import Base


class SecurityScanJob(Base):
    """一次 OWASP ZAP 扫描任务（§七、§二十二）。

    这是 Phase 2 自己的任务记录，**不是伪造的 CaseExecution**：ZAP 扫描任务不是
    普通 API 单用例，不为统一而造假。test_run_id 可空——若本次扫描被挂在一次测试
    运行下，报告层用 SecurityScanJob + TestRun 统一聚合，否则独立成报告（§二十二）。

    状态推进只由 Worker 写（§八）：
    PENDING → PREPARING → AUTHENTICATING → CRAWLING → PASSIVE_SCANNING →
    ACTIVE_SCANNING → IMPORTING_RESULTS → COMPLETED / FAILED / CANCELLED / TIMED_OUT。
    cancel_requested 是持久化的取消标记（不是进程内字典），重启后仍生效。
    heartbeat_at 用于判定「进程重启后残留的在跑任务」。
    """

    __tablename__ = "security_scan_job"
    __table_args__ = (
        Index("ix_security_scan_job_project_status", "project_id", "status"),
        Index("ix_security_scan_job_inflight_heartbeat", "status", "heartbeat_at"),
        Index("ix_security_scan_job_target", "target_id"),
        {"comment": "OWASP ZAP 扫描任务：DB 支撑的异步执行，不由 FastAPI 后台任务承担"},
    )

    id = Column(Integer, primary_key=True, index=True, autoincrement=True)
    project_id = Column(
        Integer, ForeignKey("project.id", ondelete="CASCADE"),
        nullable=False, index=True, comment="所属平台项目ID",
    )
    target_id = Column(
        Integer, ForeignKey("security_scan_target.id", ondelete="SET NULL"),
        nullable=False, index=True, comment="扫描目标ID",
    )
    environment_id = Column(
        Integer, ForeignKey("environment.id", ondelete="SET NULL"),
        nullable=True, index=True, comment="被测环境ID（快照）",
    )
    scan_profile_id = Column(
        Integer, ForeignKey("security_scan_profile.id", ondelete="SET NULL"),
        nullable=False, index=True, comment="扫描策略ID",
    )
    scan_mode = Column(
        String(30), nullable=False, comment="扫描模式快照",
    )
    status = Column(
        String(24), nullable=False, default="PENDING", server_default=text("'PENDING'"),
        comment="任务状态",
    )
    progress = Column(
        Integer, nullable=False, default=0, server_default=text("0"),
        comment="总体进度百分比；-1 表示无法给出精确进度（只展示阶段与计数）",
    )
    stage = Column(String(40), nullable=True, comment="当前阶段描述")
    authentication_mode = Column(
        String(20), nullable=True, comment="认证模式快照：NONE / BEARER_TOKEN / HEADER_BASED / "
        "BROWSER_AUTH / MANUAL",
    )
    authentication_status = Column(
        String(20), nullable=True, comment="登录态验证结果：LOGGED_IN / LOGGED_OUT / UNVERIFIABLE",
    )
    browser_session_established = Column(
        Boolean, nullable=False, default=False, server_default=text("false"),
        comment="浏览器里是否真的建立了登录态（区别于「配了 Authorization 头」）",
    )
    initiated_by = Column(Integer, ForeignKey("user.id", ondelete="SET NULL"), nullable=True, index=True)
    # 主动扫描的批准记录（§十五「操作审计」）：记录批准人，而不是仅记发起人。
    approved_by = Column(
        Integer, ForeignKey("user.id", ondelete="SET NULL"), nullable=True,
        comment="主动扫描批准人ID（被动扫描为空）",
    )
    approval_note = Column(String(500), nullable=True, comment="批准说明（主动扫描用）")
    zap_scan_reference = Column(
        String(100), nullable=True, comment="ZAP 侧扫描引用（scanId / contextId）",
    )
    test_run_id = Column(
        Integer, ForeignKey("test_run.id", ondelete="SET NULL"),
        nullable=True, index=True, comment="关联测试运行ID（可空）",
    )
    # 结果快照
    started_at = Column(DateTime, nullable=True, comment="开始时间")
    finished_at = Column(DateTime, nullable=True, comment="结束时间")
    duration_ms = Column(BigInteger, nullable=True, comment="耗时（毫秒）")
    total_alerts = Column(Integer, nullable=False, default=0, server_default=text("0"), comment="告警总数")
    high_count = Column(Integer, nullable=False, default=0, server_default=text("0"), comment="High 数")
    medium_count = Column(Integer, nullable=False, default=0, server_default=text("0"), comment="Medium 数")
    low_count = Column(Integer, nullable=False, default=0, server_default=text("0"), comment="Low 数")
    info_count = Column(Integer, nullable=False, default=0, server_default=text("0"), comment="Info 数")
    urls_discovered = Column(Integer, nullable=False, default=0, server_default=text("0"), comment="已发现 URL 数")
    requests_made = Column(Integer, nullable=False, default=0, server_default=text("0"), comment="已处理请求数")
    new_findings_count = Column(
        Integer, nullable=False, default=0, server_default=text("0"),
        comment="本次新建 Finding 数（不含重复命中）",
    )
    duplicate_findings_count = Column(
        Integer, nullable=False, default=0, server_default=text("0"),
        comment="本次重复命中的 Finding 数",
    )
    # 覆盖统计快照（§三十一）：DISCOVERED / REQUESTED / RESPONDED / PASSIVE_ANALYZED /
    # ACTIVE_SCANNED / NOT_COVERED 各阶段计数。
    coverage_summary = Column(JSON, nullable=True, comment="覆盖阶段计数快照")
    error_code = Column(String(60), nullable=True, comment="失败原因错误码")
    error_message = Column(String(500), nullable=True, comment="失败原因（脱敏）")
    # ---------------------------------------------------------- Worker 执行控制
    cancel_requested = Column(
        Boolean, nullable=False, default=False, server_default=text("false"),
        comment="是否请求取消（持久化标记，重启后仍生效）",
    )
    worker_owner = Column(
        String(64), nullable=True, comment="当前领取该任务的 Worker 标识（防重复领取）",
    )
    heartbeat_at = Column(
        DateTime, nullable=True, comment="Worker 最近一次心跳时间",
    )
    started_by_worker_at = Column(DateTime, nullable=True, comment="Worker 领取时间")
    poll_count = Column(
        Integer, nullable=False, default=0, server_default=text("0"), comment="已轮询次数",
    )
    created_at = Column(DateTime, nullable=False, server_default=func.now(), comment="创建时间")
    updated_at = Column(
        DateTime, nullable=False, server_default=func.now(), onupdate=func.now(), comment="更新时间",
    )


class SecurityScanEvent(Base):
    """扫描过程事件（§二十一「SecurityScanEvent」）。

    是审计记录，不是日志替代品：payload_json 在写入前必须已脱敏
    （redact_mapping / redact_url），原始 Request/Response 不落库（§二十一）。
    """

    __tablename__ = "security_scan_event"
    __table_args__ = (
        # 唯一：read-then-write 算出的 seq 在 worker 与 HTTP 并发时会重复，
        # 由存储层兜底，写入方（event_log.add_event）捕获冲突后重取序号。
        Index("uq_security_scan_event_job_seq", "job_id", "seq", unique=True),
        {"comment": "OWASP ZAP 扫描过程事件（脱敏），用于审计与详情页时间线"},
    )

    id = Column(Integer, primary_key=True, index=True, autoincrement=True)
    job_id = Column(
        Integer, ForeignKey("security_scan_job.id", ondelete="CASCADE"),
        nullable=False, index=True, comment="所属扫描任务ID",
    )
    project_id = Column(
        Integer, ForeignKey("project.id", ondelete="CASCADE"),
        nullable=False, index=True, comment="所属平台项目ID（冗余，便于按项目过滤）",
    )
    seq = Column(
        Integer, nullable=False, default=0, server_default=text("0"),
        comment="任务内序号（从 0 递增）",
    )
    event_type = Column(
        String(20), nullable=False, comment="事件类型：STAGE / PROGRESS / REQUEST / ALERT / "
        "AUTH / WARNING / ERROR",
    )
    stage = Column(String(40), nullable=True, comment="事件发生的阶段")
    message = Column(String(500), nullable=True, comment="事件描述（脱敏）")
    payload_json = Column(JSON, nullable=True, comment="结构化载荷（已脱敏）")
    created_at = Column(DateTime, nullable=False, server_default=func.now(), comment="事件时间")
