"""Seed governed security assessment skills.

Revision ID: 0023
Revises: 0022
"""

from alembic import op
import sqlalchemy as sa

revision = "0023"
down_revision = "0022"
branch_labels = None
depends_on = None


_SKILLS = (
    (
        "a1318505-e8fa-4119-b2fa-31d6f90c6a01",
        "API 授权边界审查",
        "按项目登记 API 和已批准策略检查认证、授权与对象级访问控制。",
        """# API 授权边界审查

- 只评估任务明确选择、且归属当前项目的登记 API。
- 以已启用的结构化策略和功能用例基线为准，不推测用户身份、角色或凭据。
- 将认证缺失、对象级授权、租户隔离和状态权限作为不同检查点说明；没有策略或证据时标记为未覆盖。
- 不扩展 API 范围，不生成原始请求、脚本、凭据或新的变异项。
- 计划经用户确认后才会创建安全用例；高风险项需要单独授权。
""",
    ),
    (
        "a1318505-e8fa-4119-b2fa-31d6f90c6a02",
        "结构化 API 变异评估",
        "解释平台生成的结构化变异计划，区分预览、批准和实际执行。",
        """# 结构化 API 变异评估

- 只解释服务端从已登记接口、启用策略和功能用例基线生成的计划预览。
- 不创建、改写或补全请求值、断言、URL、脚本或策略规则。
- 按 API 展示方法、路径、策略、变异字段、预期安全行为和阻断原因。
- `DRAFT` 计划仅供审阅；方案确认前不得称为已批准或已执行。
- 计划被截断、基线失效或目标停用时，应指出限制并要求重新规划。
""",
    ),
    (
        "a1318505-e8fa-4119-b2fa-31d6f90c6a03",
        "安全 Finding 证据分诊",
        "基于真实执行记录和脱敏 Finding 摘要进行保守分诊。",
        """# 安全 Finding 证据分诊

- 仅依据登记的 TestRun、已批准安全用例、执行状态和 Finding 摘要作判断。
- Finding 的标题与严重级别是线索，不等同于漏洞已确认；使用“疑似问题”表述。
- 不补造请求、响应、复现步骤、影响范围或用户权限事实。
- 缺少证据时说明需要人工复核；不得读取、复述或要求提供凭据、Cookie、Token 或响应正文。
- 只有现有执行结果能支持的结论才写入报告，并明确未覆盖项。
""",
    ),
    (
        "a1318505-e8fa-4119-b2fa-31d6f90c6a04",
        "受控 Web 页面被动安全观察",
        "只对项目已授权浏览器会话的当前页面检查有限响应头与 DOM 信号。",
        """# 受控 Web 页面被动安全观察

- 只检查用户明确选择、归属当前项目并处于活动状态的受控浏览器会话当前页面。
- 不导航、不点击、不提交表单、不改变页面状态，不访问会话之外的 URL。
- 仅依据响应头是否存在和有限 DOM 结构信号；不读取表单值、Cookie、响应正文或原始头值。
- 缺失安全头或页面结构信号只是低置信度候选项，不等同于漏洞确认。
- 明确报告检查范围与扫描上限，不把未观察到的页面、路由或资源说成已覆盖。
""",
    ),
)


def upgrade():
    """处理`upgrade`相关逻辑。"""
    bind = op.get_bind()
    skills = sa.table(
        "skill_definition",
        sa.column("id", sa.Integer),
        sa.column("key", sa.String(36)),
        sa.column("name", sa.String(120)),
        sa.column("description", sa.Text),
        sa.column("content", sa.Text),
        sa.column("is_enabled", sa.Boolean),
        sa.column("version", sa.Integer),
    )
    revisions = sa.table(
        "skill_definition_revision",
        sa.column("skill_definition_id", sa.Integer),
        sa.column("version", sa.Integer),
        sa.column("snapshot_json", sa.JSON),
    )
    for key, name, description, content in _SKILLS:
        skill_id = bind.execute(
            sa.select(skills.c.id).where(skills.c.key == key),
        ).scalar_one_or_none()
        if skill_id is None:
            bind.execute(skills.insert().values(
                key=key, name=name, description=description, content=content,
                is_enabled=True, version=1,
            ))
            skill_id = bind.execute(
                sa.select(skills.c.id).where(skills.c.key == key),
            ).scalar_one()
        revision_exists = bind.execute(
            sa.select(revisions.c.skill_definition_id).where(
                revisions.c.skill_definition_id == skill_id,
                revisions.c.version == 1,
            ),
        ).first()
        if revision_exists is None:
            bind.execute(revisions.insert().values(
                skill_definition_id=skill_id,
                version=1,
                snapshot_json={
                    "name": name,
                    "description": description,
                    "content": content,
                    "is_enabled": True,
                },
            ))


def downgrade():
    """处理`downgrade`相关逻辑。"""
    bind = op.get_bind()
    keys = [skill[0] for skill in _SKILLS]
    skills = sa.table(
        "skill_definition",
        sa.column("id", sa.Integer),
        sa.column("key", sa.String(36)),
    )
    revisions = sa.table(
        "skill_definition_revision",
        sa.column("skill_definition_id", sa.Integer),
    )
    skill_ids = sa.select(skills.c.id).where(skills.c.key.in_(keys))
    bind.execute(revisions.delete().where(revisions.c.skill_definition_id.in_(skill_ids)))
    bind.execute(skills.delete().where(skills.c.key.in_(keys)))
