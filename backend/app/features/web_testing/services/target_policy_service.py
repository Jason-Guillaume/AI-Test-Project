"""Web 授权目标查询适配；浏览器策略本身不访问数据库。"""

from app.core.models.project import ProjectOutboundTarget
from app.execution.browser.policy import TargetPolicy


def build_target_policy(db, project_id):
    """读取项目启用目标快照并构造本次执行使用的 DNS 冻结策略。"""
    targets = db.query(ProjectOutboundTarget).filter_by(
        project_id=project_id, enabled=True
    ).all()
    return TargetPolicy((row.scheme, row.host, row.port) for row in targets)
