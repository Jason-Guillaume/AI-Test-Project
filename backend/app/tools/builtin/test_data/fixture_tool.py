"""Agent Tool 层：可用 Fixture 清单（Phase C，§13）。

Agent **只能引用**当前项目已注册的 Fixture，不能生成或执行 SQL：

- 只返回 ``fixture_key`` / ``entity_type`` / ``scope`` / 输出契约名；
- 不含 ``config_json``、Provider 配置、连接信息与任何输出值——没有这些，
  LLM 既造不出数，也拿不到可连库的信息；
- 输出的契约名供 ``test_data`` 的 ``source_type=FIXTURE`` 绑定，以及
  ``${fixture.<KEY>.<name>}`` 模板使用（§12.4：用例里不写死真实 ID）。

可见口径与 Data Factory 一致：本项目 ACTIVE，或 GLOBAL 且 ACTIVE。
"""

from __future__ import annotations

from collections import defaultdict

from sqlalchemy import or_
from sqlalchemy.orm import Session

from app.features.test_data.models.fixture import Fixture, FixtureOutput


def list_active_fixtures(db: Session, project_id: int) -> list[dict]:
    """列出 Agent 可引用的 Fixture（本项目 ACTIVE，或 GLOBAL 且 ACTIVE）。

    返回字段刻意白名单化：任何后续新增的敏感列都不会自动进入提示词。
    """
    rows = (
        db.query(Fixture)
        .filter(
            Fixture.status == "ACTIVE",
            or_(Fixture.project_id == project_id, Fixture.scope == "GLOBAL"),
        )
        .order_by(Fixture.fixture_key.asc())
        .all()
    )
    outputs: dict[int, list[str]] = defaultdict(list)
    fixture_ids = [r.id for r in rows]
    if fixture_ids:
        for fixture_id, name in (
            db.query(FixtureOutput.fixture_id, FixtureOutput.name)
            .filter(FixtureOutput.fixture_id.in_(fixture_ids))
            .order_by(FixtureOutput.sort.asc(), FixtureOutput.id.asc())
            .all()
        ):
            outputs[fixture_id].append(name)
    return [
        {
            "fixture_key": r.fixture_key,
            "entity_type": r.entity_type,
            "scope": r.scope,
            "outputs": outputs.get(r.id, []),
        }
        for r in rows
    ]


__all__ = ["list_active_fixtures"]


from app.tools.registry import bind_module_handlers

bind_module_handlers(globals(), {
    'list_active_fixtures': ('runtime.test_data.list_active_fixtures', 'read'),
})
