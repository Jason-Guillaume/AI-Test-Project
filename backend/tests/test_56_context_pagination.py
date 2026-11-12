"""持久消息上下文采用有界分页，并只在本 AgentSession 内相关召回。"""

from types import SimpleNamespace

from sqlalchemy import create_engine
from sqlalchemy.orm import Session

from app.agents.models.message import AgentMessage
from app.agents.models.session import AgentSession
from app.agents.models.context_summary import AgentSessionSummary
from app.agents.services.context_memory import load_valid_session_summary, refresh_session_summary, select_summary_sources
from app.agents.services.context_manager import assemble_history
from app.agents.services.message_store import list_context_candidates, list_latest_state_messages
from app.core.database.base import Base
import app.core.models  # noqa: F401 — 注册 AgentSession 外键目标
import app.orchestration.tasks.models  # noqa: F401 — 注册 TaskRun / TaskAgentInstance 外键目标


def test_summary_keeps_business_constraints_ahead_of_newer_noise():
    rows = [
        SimpleNamespace(id=1, content="生成结果必须进入草稿，不允许跳过人工审核"),
        *[SimpleNamespace(id=index, content=f"普通过程记录 {index}") for index in range(2, 20)],
    ]
    selected = select_summary_sources(rows, limit=4)
    assert selected[0].content.startswith("生成结果必须进入草稿")
    assert len(selected) == 4


def test_context_candidates_bound_history_and_recall_relevant_old_messages():
    engine = create_engine("sqlite://")
    Base.metadata.create_all(engine, tables=[
        AgentSession.__table__, AgentMessage.__table__, AgentSessionSummary.__table__,
    ])
    with Session(engine) as db:
        db.add(AgentSession(id=1, project_id=10, user_id=2, current_stage="UNDERSTANDING"))
        db.add(AgentSession(id=2, project_id=20, user_id=2, current_stage="UNDERSTANDING"))
        db.flush()
        db.add_all([
            AgentMessage(session_id=1, role="USER", message_type="TEXT", content="支付退款规则：仅原路退回"),
            *[
                AgentMessage(session_id=1, role="ASSISTANT", message_type="TEXT", content=f"无关历史 {index}")
                for index in range(2, 180)
            ],
            AgentMessage(session_id=1, role="USER", message_type="TEXT", content="继续支付退款"),
            AgentMessage(session_id=2, role="USER", message_type="TEXT", content="支付退款跨会话内容"),
        ])
        db.commit()

        rows, total = list_context_candidates(
            db, 1, query="支付退款", recent_limit=16, related_limit=8,
        )
        assert total == 180
        assert len(rows) <= 24
        assert rows[0].content == "支付退款规则：仅原路退回"
        assert rows[-1].content == "继续支付退款"
        assert all("跨会话" not in row.content for row in rows)
        assert len(list_latest_state_messages(db, 1)) == 1


def test_persisted_summary_has_source_fingerprint_and_is_used_as_history_index():
    engine = create_engine("sqlite://")
    Base.metadata.create_all(engine, tables=[
        AgentSession.__table__, AgentMessage.__table__, AgentSessionSummary.__table__,
    ])
    with Session(engine) as db:
        session = AgentSession(id=8, project_id=4, user_id=2, current_stage="UNDERSTANDING")
        db.add(session)
        db.flush()
        db.add_all([
            AgentMessage(
                session_id=8, role="USER" if index % 2 else "ASSISTANT",
                message_type="TEXT", content=f"支付退款业务事实 {index}",
            ) for index in range(40)
        ])
        db.commit()

        refresh_session_summary(db, 8)
        summary = load_valid_session_summary(db, 8)
        assert summary is not None
        assert summary["kind"] == "EXTRACTIVE"
        assert summary["source_refs"]
        assert "支付退款业务事实" in summary["text"]
        rows, total = list_context_candidates(db, 8, query="支付退款业务事实", recent_limit=16)
        selected, manifest = assemble_history(
            session=session, messages=rows, query="支付退款业务事实", token_budget=4000,
            max_messages=8, total_message_count=total, summary=summary,
        )
        assert selected[0]["content"].startswith("以下是同一 Agent 会话")
        assert manifest["summary_used"] is True
        assert manifest["summary_source_count"] == len(summary["source_refs"])
        assert manifest["estimated_tokens"] <= 4000

        first_source_id = summary["source_refs"][0]["message_id"]
        source_message = db.get(AgentMessage, first_source_id)
        source_message.content += " 已修订"
        db.commit()
        assert load_valid_session_summary(db, 8) is None
