"""浏览器进程资源释放后的 Web 会话状态持久化。"""

from datetime import datetime, timezone

from app.core.database.session import SessionLocal
from app.features.web_testing.models import WebAgentSession


def mark_session_closed_by_runtime(session_id):
    """空闲回收器关闭浏览器句柄后，将仍处于活动态的记录标为已关闭。"""
    with SessionLocal() as db:
        db.query(WebAgentSession).filter_by(id=session_id, status="ACTIVE").update(
            {"status": "CLOSED", "closed_at": datetime.now(timezone.utc).replace(tzinfo=None)},
            synchronize_session=False,
        )
        db.commit()
